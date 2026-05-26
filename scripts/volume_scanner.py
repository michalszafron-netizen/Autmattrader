"""Volume Anomaly Scanner — detects tokens with abnormal volume spikes.

Compares current 24h volume against 30-day average.
A 3x+ spike = something is happening before most people notice.

Sources:
  Binance Futures — all perpetual contracts
  Binance Spot    — spot markets (catches altcoins not on futures)

Alert thresholds:
  3x  — elevated, worth watching
  5x  — significant anomaly
  10x+ — extreme spike (tweet, listing, hack, news)

Usage:
    python scripts/volume_scanner.py              # one-shot scan
    python scripts/volume_scanner.py --daemon     # loop every 1h
    python scripts/volume_scanner.py --threshold 5   # only 5x+ spikes
    python scripts/volume_scanner.py --dry-run    # no Telegram
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_SSL       = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")

IGNORE = {
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USDP",
    "BTC", "ETH",  # too much data noise — always high volume
}

DEFAULT_THRESHOLD  = 3.0   # minimum multiplier to alert (24h window)
DEFAULT_TOP_N      = 10    # max tokens per alert message
MIN_VOL_USD        = 500_000    # ignore tokens with <$500K 24h volume (was $1M)

# Early-detection window (4h vs rolling hourly avg)
EARLY_WINDOW_HOURS = 4     # compare last N hours vs historical hourly avg
EARLY_THRESHOLD    = 2.5   # multiplier to fire early alert (slightly lower — 4h is noisier)


# ── Binance API ───────────────────────────────────────────────────────────────

def fetch_futures_tickers() -> list[dict]:
    """All Binance Futures 24h tickers in one call."""
    try:
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        print(f"[Binance Futures] Error: {e}")
        return []


def fetch_spot_tickers() -> list[dict]:
    """All Binance Spot 24h tickers (USDT pairs only)."""
    try:
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.get("https://api.binance.com/api/v3/ticker/24hr")
            r.raise_for_status()
            return [t for t in r.json() if t.get("symbol", "").endswith("USDT")]
    except Exception as e:
        print(f"[Binance Spot] Error: {e}")
        return []


ALPHA_TOKEN_LIST_URL = "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
ALPHA_KLINES_URL     = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/klines"

_alpha_map_cache: dict[str, dict] | None = None  # lazy-loaded once per scan


def fetch_alpha_token_map() -> dict[str, dict]:
    """Fetch all Binance Alpha tokens and return {SYMBOL: token_data}.
    Result is cached for the duration of the process.
    """
    global _alpha_map_cache
    if _alpha_map_cache is not None:
        return _alpha_map_cache
    try:
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.get(ALPHA_TOKEN_LIST_URL)
            r.raise_for_status()
            tokens = r.json().get("data", [])
        _alpha_map_cache = {
            t["symbol"].upper(): t
            for t in tokens
            if not t.get("fullyDelisted") and not t.get("offline")
        }
    except Exception as e:
        print(f"[Alpha token list] Error: {e}")
        _alpha_map_cache = {}
    return _alpha_map_cache


def fetch_alpha_30d_avg(alpha_id: str) -> float | None:
    """Fetch 30 daily klines for a Binance Alpha token and return average daily USDT volume."""
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            r = c.get(ALPHA_KLINES_URL, params={
                "symbol": f"{alpha_id}USDT",
                "interval": "1d",
                "limit": "30",
            })
            r.raise_for_status()
            candles = r.json().get("data", [])
        if not candles:
            return None
        # Format: [openTime, open, high, low, close, baseVol, closeTime, quoteVol, ...]
        volumes = [float(c[7]) for c in candles[:-1]]  # exclude today (incomplete)
        return sum(volumes) / len(volumes) if volumes else None
    except Exception:
        return None


def fetch_recent_pct_changes(
    symbol: str,
    market: str = "futures",
    alpha_id: str = "",
    days: int = 4,
) -> list[float] | None:
    """Return last N daily open→close % changes, oldest first.

    E.g. days=4 → [pct_4d_ago, pct_3d_ago, pct_2d_ago, pct_yesterday]
    Today's (incomplete) candle is excluded.
    """
    try:
        limit = days + 1  # +1 so we can safely exclude today
        if market == "alpha" and alpha_id:
            with httpx.Client(verify=_SSL, timeout=10) as c:
                r = c.get(ALPHA_KLINES_URL, params={
                    "symbol": f"{alpha_id}USDT", "interval": "1d", "limit": str(limit),
                })
                r.raise_for_status()
                candles = r.json().get("data", [])
        else:
            base = "https://fapi.binance.com" if market == "futures" else "https://api.binance.com"
            path = "/fapi/v1/klines"       if market == "futures" else "/api/v3/klines"
            with httpx.Client(verify=_SSL, timeout=10) as c:
                r = c.get(f"{base}{path}", params={
                    "symbol": symbol, "interval": "1d", "limit": str(limit),
                })
                r.raise_for_status()
                candles = r.json()

        if not candles or len(candles) < days:
            return None
        # Exclude today (last candle, possibly incomplete); take the previous 'days' candles
        closed = candles[-(days + 1):-1]
        result = []
        for c in closed:
            o = float(c[1])
            cl = float(c[4])
            result.append(round((cl - o) / o * 100, 1) if o else 0.0)
        return result or None
    except Exception:
        return None


def fetch_short_window_multiplier(
    symbol: str,
    market: str = "futures",
    hours: int = EARLY_WINDOW_HOURS,
) -> tuple[float, float, float] | None:
    """Detect early volume spikes using recent N-hour window vs historical hourly average.

    Returns (recent_vol, baseline_vol, multiplier) or None on error.

    How it works:
      - Fetches ~20 days of 1h klines (Binance limit=500 for 1h)
      - recent_vol  = sum of last `hours` CLOSED 1h candles (quoteVol)
      - baseline    = mean hourly vol over all older candles * hours
      - multiplier  = recent_vol / baseline

    Why this catches spikes 12-18h earlier than the 24h ticker:
      The 24h rolling window dilutes a spike by mixing it with 20h of normal volume.
      A 4h window is immediately dominated by the spike — no dilution.
    """
    try:
        limit = min(20 * 24 + hours + 1, 500)  # up to ~20 days of 1h candles
        if market == "futures":
            base = "https://fapi.binance.com"
            path = "/fapi/v1/klines"
        else:
            base = "https://api.binance.com"
            path = "/api/v3/klines"

        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(f"{base}{path}", params={
                "symbol": symbol, "interval": "1h", "limit": str(limit),
            })
            r.raise_for_status()
            candles = r.json()

        if not candles or len(candles) < hours + 48:
            return None

        # Exclude current incomplete candle (last one)
        closed = candles[:-1]

        # Recent window: last `hours` closed candles
        recent_candles = closed[-hours:]
        recent_vol = sum(float(c[7]) for c in recent_candles)

        # Baseline: average hourly volume from all older candles
        older_candles = closed[:-hours]
        if len(older_candles) < 24:
            return None
        avg_hourly = sum(float(c[7]) for c in older_candles) / len(older_candles)
        baseline = avg_hourly * hours  # scale to same window size

        if baseline <= 0:
            return None

        return (recent_vol, baseline, recent_vol / baseline)

    except Exception:
        return None


def fetch_30d_avg_volume(symbol: str, market: str = "futures") -> float | None:
    """Fetch 30 daily candles and return average daily volume in USD."""
    try:
        base = "https://fapi.binance.com" if market == "futures" else "https://api.binance.com"
        path = "/fapi/v1/klines" if market == "futures" else "/api/v3/klines"
        with httpx.Client(verify=_SSL, timeout=10) as c:
            r = c.get(f"{base}{path}",
                      params={"symbol": symbol, "interval": "1d", "limit": "30"})
            r.raise_for_status()
            candles = r.json()
        if not candles:
            return None
        # Each candle: [open_time, open, high, low, close, volume, close_time, quote_volume, ...]
        # quote_volume (index 7) = volume in USDT
        volumes = [float(c[7]) for c in candles[:-1]]  # exclude today (incomplete)
        return sum(volumes) / len(volumes) if volumes else None
    except Exception:
        return None


# ── Core analysis ─────────────────────────────────────────────────────────────

def find_anomalies(threshold: float) -> list[dict]:
    """Return list of volume anomalies above threshold multiplier.

    For futures anomalies: also fetches spot volume for the same token
    so the alert can show side-by-side Futures vs Spot comparison.
    """
    anomalies = []

    # Futures
    print("  Futures...", end=" ", flush=True)
    f_tickers = fetch_futures_tickers()
    futures_candidates = []
    for t in f_tickers:
        sym    = t.get("symbol", "")
        ticker = sym.replace("USDT", "").replace("PERP", "")
        if ticker in IGNORE:
            continue
        try:
            vol24  = float(t.get("quoteVolume", 0))
            price  = float(t.get("lastPrice", 0))
            chg    = float(t.get("priceChangePercent", 0))
            if vol24 < MIN_VOL_USD:
                continue
            futures_candidates.append({
                "symbol": sym, "ticker": ticker,
                "vol24": vol24, "price": price, "chg": chg,
                "market": "futures",
            })
        except Exception:
            continue
    futures_candidates.sort(key=lambda x: -x["vol24"])
    futures_ticker_set = {c["ticker"] for c in futures_candidates}
    print(f"{len(futures_candidates)} candidates", end=" ", flush=True)

    # Spot — fetch ALL tickers, build a lookup map
    print("| Spot...", end=" ", flush=True)
    s_tickers = fetch_spot_tickers()
    # spot_map: ticker → {symbol, vol24, price, chg}
    spot_map: dict[str, dict] = {}
    for t in s_tickers:
        sym    = t.get("symbol", "")
        ticker = sym.replace("USDT", "")
        if ticker in IGNORE:
            continue
        try:
            vol24 = float(t.get("quoteVolume", 0))
            price = float(t.get("lastPrice", 0))
            chg   = float(t.get("priceChangePercent", 0))
            if vol24 >= MIN_VOL_USD:
                spot_map[ticker] = {
                    "symbol": sym, "vol24": vol24, "price": price, "chg": chg
                }
        except Exception:
            continue

    # Standalone spot candidates: tokens NOT listed on futures
    spot_candidates = []
    for ticker, d in spot_map.items():
        if ticker not in futures_ticker_set:
            spot_candidates.append({
                "symbol": d["symbol"], "ticker": ticker,
                "vol24": d["vol24"], "price": d["price"], "chg": d["chg"],
                "market": "spot",
            })
    spot_candidates.sort(key=lambda x: -x["vol24"])
    print(f"{len(spot_map)} in map | {len(spot_candidates)} standalone")

    # ── Pass 1: 24h window vs 30d daily average ──────────────────────────────
    # Larger candidate pool: 80 futures + 40 spot (was 40+20)
    all_candidates = futures_candidates[:80] + spot_candidates[:40]
    print(f"  Fetching 30d averages for {len(all_candidates)} tokens...", end=" ", flush=True)

    found_24h: dict[str, dict] = {}  # ticker → anomaly (24h detections)
    checked = 0
    for cand in all_candidates:
        avg = fetch_30d_avg_volume(cand["symbol"], cand["market"])
        if not avg or avg < 50_000:
            continue
        multiplier = cand["vol24"] / avg
        if multiplier >= threshold:
            entry = {
                **cand,
                "avg30d":       avg,
                "multiplier":   multiplier,
                "mult_24h":     multiplier,
                "mult_4h":      None,
                "detection":    "24h",
            }
            found_24h[cand["ticker"]] = entry
            anomalies.append(entry)
        checked += 1
    print(f"checked {checked}, found {len(found_24h)} via 24h window")

    # ── Pass 2: 4h early-detection window ────────────────────────────────────
    # Run for ALL candidates — catches spikes that haven't yet dominated the 24h window
    print(
        f"  Early-detection 4h scan for {len(all_candidates)} tokens...",
        end=" ", flush=True,
    )
    early_found = 0
    for cand in all_candidates:
        result = fetch_short_window_multiplier(cand["symbol"], cand["market"])
        if not result:
            continue
        recent_vol, baseline, mult_4h = result
        if mult_4h < EARLY_THRESHOLD:
            continue

        ticker = cand["ticker"]
        if ticker in found_24h:
            # Already flagged by 24h — just enrich with 4h data
            found_24h[ticker]["mult_4h"] = mult_4h
            found_24h[ticker]["detection"] = "both"
        else:
            # NEW early detection — not yet visible in 24h window
            # Fetch 30d avg for context (don't filter by it though)
            avg30d = fetch_30d_avg_volume(cand["symbol"], cand["market"]) or 0.0
            entry = {
                **cand,
                "avg30d":     avg30d,
                "multiplier": mult_4h,   # show 4h multiplier as headline
                "mult_24h":   cand["vol24"] / avg30d if avg30d > 0 else None,
                "mult_4h":    mult_4h,
                "detection":  "4h",
            }
            anomalies.append(entry)
            early_found += 1

    print(f"found {early_found} additional early (4h-only) anomalies")
    print(f"  Total anomalies: {len(anomalies)}")
    anomalies.sort(key=lambda x: -x["multiplier"])
    anomalies.sort(key=lambda x: -x["multiplier"])

    # ── Spot cross-check for futures anomalies ────────────────────────────────
    # For each futures anomaly, look up its corresponding spot market
    # and fetch spot 30d avg so we can compare futures spike vs spot spike.
    futures_anomalies = [a for a in anomalies if a["market"] == "futures"]
    if futures_anomalies:
        print(
            f"  Spot cross-check for {len(futures_anomalies)} futures anomalies...",
            end=" ", flush=True,
        )
        done = 0
        for anomaly in futures_anomalies:
            ticker    = anomaly["ticker"]
            spot_data = spot_map.get(ticker)
            if not spot_data:
                anomaly["spot_vol24"]  = None   # token not listed on spot
                continue
            spot_avg = fetch_30d_avg_volume(spot_data["symbol"], "spot")
            if spot_avg and spot_avg > 0:
                anomaly["spot_vol24"]  = spot_data["vol24"]
                anomaly["spot_avg30d"] = spot_avg
                anomaly["spot_mult"]   = spot_data["vol24"] / spot_avg
            else:
                anomaly["spot_vol24"]  = spot_data["vol24"]
                anomaly["spot_avg30d"] = None
                anomaly["spot_mult"]   = None
            done += 1
        print(f"done ({done}/{len(futures_anomalies)})")

    # ── Binance Alpha cross-check — for futures anomalies with NO Binance Spot ─
    no_spot = [a for a in futures_anomalies if a.get("spot_vol24") is None]
    if no_spot:
        print(f"  Binance Alpha check for {len(no_spot)} tokens...", end=" ", flush=True)
        alpha_map = fetch_alpha_token_map()
        done_alpha = 0
        for anomaly in no_spot:
            token = alpha_map.get(anomaly["ticker"].upper())
            if not token:
                continue
            alpha_id    = token.get("alphaId", "")
            alpha_vol   = float(token.get("volume24h", 0))
            alpha_chg   = float(token.get("percentChange24h", 0))
            alpha_chain = token.get("chainName", "?")
            alpha_avg   = fetch_alpha_30d_avg(alpha_id) if alpha_id else None
            anomaly["alpha_vol24"]  = alpha_vol
            anomaly["alpha_avg30d"] = alpha_avg
            anomaly["alpha_mult"]   = (alpha_vol / alpha_avg) if alpha_avg else None
            anomaly["alpha_chg"]    = alpha_chg
            anomaly["alpha_chain"]  = alpha_chain
            anomaly["alpha_id"]     = alpha_id
            done_alpha += 1
        print(f"done ({done_alpha}/{len(no_spot)})")

    # ── 4-day price history for each anomaly (only top N, no extra cost for rest) ─
    top_anomalies = anomalies[:DEFAULT_TOP_N]
    print(f"  4d price history for {len(top_anomalies)} anomalies...", end=" ", flush=True)
    for anomaly in top_anomalies:
        mkt      = anomaly["market"]
        sym      = anomaly["symbol"]
        alpha_id = anomaly.get("alpha_id", "")
        # If token is futures-only but found on Alpha → use Alpha klines (more accurate)
        if mkt == "futures" and anomaly.get("spot_vol24") is None and alpha_id:
            changes = fetch_recent_pct_changes(sym, "alpha", alpha_id)
        else:
            changes = fetch_recent_pct_changes(anomaly["symbol"], mkt)
        if changes:
            anomaly["price_4d"] = changes
    print("done")

    return anomalies


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${v/1e3:.0f}K"


def _spot_cross_label(spot_mult: float | None) -> str:
    """Human-readable spot multiplier label with icon."""
    if spot_mult is None:
        return "⚪ brak danych"
    if spot_mult >= 5.0:
        return f"🔥🔥 {spot_mult:.1f}x SPIKE"
    if spot_mult >= 3.0:
        return f"🔥 {spot_mult:.1f}x spike"
    if spot_mult >= 1.5:
        return f"🟡 {spot_mult:.1f}x podwyższony"
    return f"⚪ {spot_mult:.1f}x normalny"


def format_alert(anomalies: list[dict], ts: str, threshold: float, part: int = 0, total_parts: int = 0) -> str:
    top = anomalies  # caller slices before passing
    part_tag = f" — część {part}/{total_parts}" if total_parts > 1 else ""
    lines = [
        f"📊 <b>Volume Anomaly Scanner</b> — {ts}{part_tag}",
        f"Prog wykrycia: {threshold}x powyżej sredniej 30-dniowej\n",
    ]
    for a in top:
        mult       = a["multiplier"]
        mult_24h   = a.get("mult_24h")
        mult_4h    = a.get("mult_4h")
        detection  = a.get("detection", "24h")
        chg        = a["chg"]
        fire       = "🔥🔥🔥" if mult >= 10 else "🔥🔥" if mult >= 5 else "🔥"
        emoji      = "🟢" if chg >= 0 else "🔴"
        sym        = a["symbol"]

        # Detection window label — most important UX signal
        if detection == "4h":
            detect_tag = "⚡ <b>EARLY 4h</b>"  # spike just started — act now
        elif detection == "both":
            detect_tag = "⚡ 4h + 📊 24h"       # confirmed by both windows
        else:
            detect_tag = "📊 24h"               # standard detection

        # Multiplier breakdown line
        mult_line = f"   {detect_tag} — {mult:.1f}x"
        if mult_4h is not None and mult_24h is not None:
            mult_line += f"  (4h: {mult_4h:.1f}x | 24h: {mult_24h:.1f}x)"
        elif mult_4h is not None:
            mult_line += f"  (4h: {mult_4h:.1f}x)"

        if a["market"] == "futures":
            market_label = "Futures"
            exchange_label = "Binance Futures (PERP)"
            trade_url = f"https://www.binance.com/en/futures/{sym}"
        else:
            market_label = "Spot"
            exchange_label = "Binance Spot"
            trade_url = f"https://www.binance.com/en/trade/{a['ticker']}_USDT"

        # Spot / Alpha cross-check line — only for futures anomalies
        spot_line = ""
        if a["market"] == "futures":
            sv = a.get("spot_vol24")
            sa = a.get("spot_avg30d")
            sm = a.get("spot_mult")
            if sv is None:
                # Not on Binance Spot — check if it's on Binance Alpha
                av  = a.get("alpha_vol24")
                aa  = a.get("alpha_avg30d")
                am  = a.get("alpha_mult")
                ach = a.get("alpha_chg", 0.0)
                acn = a.get("alpha_chain", "?")
                if av is not None:
                    alpha_chg_str = f"{ach:+.1f}%"
                    if am is not None:
                        spot_line = (
                            f"\n   {_spot_cross_label(am)} "
                            f"| Alpha ({acn}): {_fmt(av)} | Avg30d: {_fmt(aa)} | {alpha_chg_str}"
                        )
                    else:
                        spot_line = (
                            f"\n   📗 Alpha ({acn}): {_fmt(av)} 24h | {alpha_chg_str}"
                        )
                else:
                    spot_line = "\n   ⚫ Spot: brak listingu (nie na Alpha)"
            elif sa is None:
                spot_line = f"\n   ⚪ Spot: {_fmt(sv)} | brak historii avg"
            else:
                spot_line = (
                    f"\n   {_spot_cross_label(sm)} "
                    f"| Spot 24h: {_fmt(sv)} | Avg30d: {_fmt(sa)}"
                )

        # 4-day price trend line
        trend_line = ""
        changes = a.get("price_4d")
        if changes:
            def _pc(v: float) -> str:
                arrow = "▲" if v >= 0 else "▼"
                col   = "+" if v >= 0 else ""
                return f"{arrow}{col}{v:.1f}%"
            trend_parts = " → ".join(_pc(v) for v in changes)
            # Assess last 24h vs earlier days to flag "just started"
            last   = changes[-1]  if changes else 0
            total  = sum(changes) if changes else 0
            if abs(total) < 5 and abs(last) < 5:
                status = "🎯 cichy"
            elif abs(last) > 20:
                status = "🚀 rakieta"
            elif abs(total) > 30:
                status = "⚠️ spóźniony?"
            else:
                status = "📈 rośnie"
            trend_line = f"\n   📅 4d: {trend_parts}  [{status}]"

        # Solana swap command if token exists on Solana
        solana_cmd = ""
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from solana_executor import KNOWN_MINTS
            if a["ticker"] in KNOWN_MINTS:
                solana_cmd = (
                    f"\n   ⚡ <code>python scripts/solana_executor.py swap SOL "
                    f"{a['ticker']} 0.01 --yes</code>"
                )
        except Exception:
            pass

        lines.append(
            f"{fire} <b>${a['ticker']}</b> — <b>{mult:.1f}x</b> powyzej sredniej\n"
            f"{mult_line}\n"
            f"   📍 {exchange_label}\n"
            f"   {emoji} {market_label} 24h: {_fmt(a['vol24'])} | Avg30d: {_fmt(a['avg30d'])} | "
            f"Cena: {chg:+.1f}%"
            f"{spot_line}"
            f"{trend_line}\n"
            f"   🔗 <a href='{trade_url}'>Handluj na Binance</a>"
            f"{solana_cmd}"
        )
    lines.append(f"\n⚡ {len(anomalies)} anomalii | Prog: {threshold}x")
    return "\n".join(lines)


def format_heartbeat(ts: str, threshold: float) -> str:
    return (
        f"📡 <b>Volume Scanner</b> — {ts}\n"
        f"\n"
        f"✅ Brak anomalii powyzej {threshold}x sredniej 30d\n"
        f"Monitorowane: Binance Futures + Spot\n"
        f"\n"
        f"<i>Nastepne sprawdzenie za 1h</i>"
    )


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"\n[DRY-RUN]\n{text}\n")
        return
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            c.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": text,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
            )
    except Exception as e:
        print(f"[Telegram] {e}")


# ── DB save ───────────────────────────────────────────────────────────────────

def save_to_db(anomalies: list[dict], ts: str) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()
        db._sqlite.execute("""
            CREATE TABLE IF NOT EXISTS volume_anomalies (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                ticker     TEXT NOT NULL,
                market     TEXT,
                vol24      REAL,
                avg30d     REAL,
                multiplier REAL,
                price      REAL,
                chg_pct    REAL
            )""")
        for a in anomalies:
            db._sqlite.execute(
                """INSERT INTO volume_anomalies
                   (ts, ticker, market, vol24, avg30d, multiplier, price, chg_pct)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ts, a["ticker"], a["market"], a["vol24"], a["avg30d"],
                 a["multiplier"], a["price"], a["chg"]),
            )
    except Exception as e:
        print(f"[DB] {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_once(threshold: float, dry_run: bool) -> int:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{ts}] Scanning for volume anomalies (threshold: {threshold}x)...")
    anomalies = find_anomalies(threshold)

    if anomalies:
        # Split into chunks so each Telegram message stays under the 4096-char limit
        chunk_size = DEFAULT_TOP_N
        chunks = [anomalies[i:i + chunk_size] for i in range(0, len(anomalies), chunk_size)]
        total = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            msg = format_alert(chunk, ts, threshold, part=idx, total_parts=total)
            send_telegram(msg, dry_run=dry_run)
        save_to_db(anomalies, ts)
        print(f"[{ts}] Alert sent: {len(anomalies)} anomalies in {total} message(s)")
    else:
        hb = format_heartbeat(ts, threshold)
        send_telegram(hb, dry_run=dry_run)
        print(f"[{ts}] Heartbeat sent — no anomalies above {threshold}x")

    return len(anomalies)


def main() -> None:
    p = argparse.ArgumentParser(description="Volume Anomaly Scanner")
    p.add_argument("--interval",  type=int,   default=900,
                   help="Scan interval seconds (default: 900 = 15min; was 3600)")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"Volume multiplier threshold (default: {DEFAULT_THRESHOLD}x)")
    p.add_argument("--daemon",    action="store_true", help="Run forever")
    p.add_argument("--dry-run",   action="store_true", help="No Telegram, print only")
    args = p.parse_args()

    if args.daemon:
        import subprocess, os, signal

        # ── PID lockfile — tylko jeden daemon na raz ─────────────────────────
        lockfile = Path(__file__).parent.parent / ".volume_scanner.pid"
        if lockfile.exists():
            old_pid = int(lockfile.read_text().strip())
            try:
                os.kill(old_pid, 0)   # sprawdź czy proces żyje
                print(f"[WARN] Znaleziono stary daemon (PID {old_pid}) — zabijam...")
                os.kill(old_pid, signal.SIGTERM)
                time.sleep(2)
            except (ProcessLookupError, PermissionError):
                pass  # stary PID nie istnieje — można nadpisać
        lockfile.write_text(str(os.getpid()))
        print(f"[PID {os.getpid()}] Lockfile zapisany → {lockfile.name}")

        print(f"Volume Scanner daemon — interval: {args.interval}s | "
              f"threshold: {args.threshold}x | "
              f"Telegram: {'DRY-RUN' if args.dry_run else 'LIVE'}")
        print("Tryb: fresh subprocess per scan (zmiany w kodzie widoczne automatycznie)")
        try:
            while True:
                # Fresh subprocess — picks up any code changes without daemon restart
                cmd = [sys.executable, __file__, "--threshold", str(args.threshold)]
                if args.dry_run:
                    cmd.append("--dry-run")
                subprocess.run(cmd, cwd=Path(__file__).parent.parent)
                print(f"Sleeping {args.interval}s ({args.interval//60}min)...")
                time.sleep(args.interval)
        finally:
            # Wyczyść lockfile przy zamknięciu
            if lockfile.exists() and lockfile.read_text().strip() == str(os.getpid()):
                lockfile.unlink()
    else:
        run_once(args.threshold, args.dry_run)


if __name__ == "__main__":
    main()
