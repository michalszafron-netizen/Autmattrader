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

DEFAULT_THRESHOLD  = 3.0   # minimum multiplier to alert
DEFAULT_TOP_N      = 8     # max tokens per alert message
MIN_VOL_USD        = 1_000_000  # ignore tokens with <$1M 24h volume


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
    """Return list of volume anomalies above threshold multiplier."""
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
    # Sort by volume, take top 50 to check avg (limit API calls)
    futures_candidates.sort(key=lambda x: -x["vol24"])
    print(f"{len(futures_candidates)} candidates", end=" ", flush=True)

    # Spot (smaller caps not on futures)
    print("| Spot...", end=" ", flush=True)
    s_tickers = fetch_spot_tickers()
    spot_candidates = []
    futures_syms = {c["symbol"] for c in futures_candidates}
    for t in s_tickers:
        sym    = t.get("symbol", "")
        ticker = sym.replace("USDT", "")
        if ticker in IGNORE or sym in futures_syms:
            continue
        try:
            vol24 = float(t.get("quoteVolume", 0))
            price = float(t.get("lastPrice", 0))
            chg   = float(t.get("priceChangePercent", 0))
            if vol24 < MIN_VOL_USD:
                continue
            spot_candidates.append({
                "symbol": sym, "ticker": ticker,
                "vol24": vol24, "price": price, "chg": chg,
                "market": "spot",
            })
        except Exception:
            continue
    spot_candidates.sort(key=lambda x: -x["vol24"])
    print(f"{len(spot_candidates)} candidates")

    # Check 30d average for top candidates
    all_candidates = futures_candidates[:40] + spot_candidates[:20]
    print(f"  Fetching 30d averages for {len(all_candidates)} tokens...", end=" ", flush=True)

    checked = 0
    for cand in all_candidates:
        avg = fetch_30d_avg_volume(cand["symbol"], cand["market"])
        if not avg or avg < 100_000:
            continue
        multiplier = cand["vol24"] / avg
        if multiplier >= threshold:
            anomalies.append({
                **cand,
                "avg30d":     avg,
                "multiplier": multiplier,
            })
        checked += 1

    print(f"checked {checked}, found {len(anomalies)} anomalies")
    anomalies.sort(key=lambda x: -x["multiplier"])
    return anomalies


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${v/1e3:.0f}K"


def format_alert(anomalies: list[dict], ts: str, threshold: float) -> str:
    top = anomalies[:DEFAULT_TOP_N]
    lines = [
        f"📊 <b>Volume Anomaly Scanner</b> — {ts}",
        f"Prog wykrycia: {threshold}x powyżej sredniej 30-dniowej\n",
    ]
    for a in top:
        mult  = a["multiplier"]
        chg   = a["chg"]
        fire  = "🔥🔥🔥" if mult >= 10 else "🔥🔥" if mult >= 5 else "🔥"
        emoji = "🟢" if chg >= 0 else "🔴"
        market_tag = "PERP" if a["market"] == "futures" else "SPOT"
        lines.append(
            f"{fire} <b>${a['ticker']}</b> [{market_tag}] — "
            f"<b>{mult:.1f}x</b> powyzej sredniej\n"
            f"   {emoji} 24h: {_fmt(a['vol24'])} | Avg30d: {_fmt(a['avg30d'])} | "
            f"Cena: {chg:+.1f}%"
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
        msg = format_alert(anomalies, ts, threshold)
        send_telegram(msg, dry_run=dry_run)
        save_to_db(anomalies, ts)
        print(f"[{ts}] Alert sent: {len(anomalies)} anomalies")
    else:
        hb = format_heartbeat(ts, threshold)
        send_telegram(hb, dry_run=dry_run)
        print(f"[{ts}] Heartbeat sent — no anomalies above {threshold}x")

    return len(anomalies)


def main() -> None:
    p = argparse.ArgumentParser(description="Volume Anomaly Scanner")
    p.add_argument("--interval",  type=int,   default=3600,
                   help="Scan interval seconds (default: 3600 = 1h)")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"Volume multiplier threshold (default: {DEFAULT_THRESHOLD}x)")
    p.add_argument("--daemon",    action="store_true", help="Run forever")
    p.add_argument("--dry-run",   action="store_true", help="No Telegram, print only")
    args = p.parse_args()

    if args.daemon:
        print(f"Volume Scanner daemon — interval: {args.interval}s | "
              f"threshold: {args.threshold}x | "
              f"Telegram: {'DRY-RUN' if args.dry_run else 'LIVE'}")
        while True:
            run_once(args.threshold, args.dry_run)
            print(f"Sleeping {args.interval}s ({args.interval//60}min)...")
            time.sleep(args.interval)
    else:
        run_once(args.threshold, args.dry_run)


if __name__ == "__main__":
    main()
