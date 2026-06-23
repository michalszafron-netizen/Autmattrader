"""Open Interest tracker — Binance + Bybit + Extended Exchange.

Aggregates OI across three sources, shows a 14-day trend (sparkline + %)
per coin with an expert-style OI/price-quadrant interpretation, tracks
spikes vs the previous snapshot, and always persists to SQLite so the
trend has data to draw on.

History source: a VPS cron runs `--save --no-history` hourly into its
local DB, exposed read-only via GET /oi_history on tv_webhook.py (see
SERWER.md). If that's unreachable, falls back to the local SQLite DB.

Usage:
    python scripts/oi_tracker.py                    # full report + 14D trend + Expert View
    python scripts/oi_tracker.py --brief            # compact for daily alpha (+ trend + interpretation)
    python scripts/oi_tracker.py --coins BTC ETH    # specific coins only
    python scripts/oi_tracker.py --trend            # compare TOTAL vs previous single snapshot
    python scripts/oi_tracker.py --no-history       # skip 14D fetch (faster, used by cron)

Sources:
    Binance  — fapi.binance.com  (no key, crypto perps)
    Bybit    — api.bybit.com     (no key, crypto perps)
    Extended — starknet.extended.exchange (API key, crypto + TradFi)
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

_SSL     = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
console  = Console()

EXTENDED_API_KEY = os.getenv("EXTENDED_API_KEY", "")
TV_SECRET        = os.getenv("TV_SECRET", "")
OI_HISTORY_URL   = os.getenv("VPS_OI_HISTORY_URL", "https://tv.prawosfera.online/oi_history")
HISTORY_DAYS     = 14

# Instruments to track (symbol: Binance ticker, Bybit ticker, Extended name)
INSTRUMENTS = {
    "BTC":   ("BTCUSDT",  "BTCUSDT",  "BTC-USD"),
    "ETH":   ("ETHUSDT",  "ETHUSDT",  "ETH-USD"),
    "SOL":   ("SOLUSDT",  "SOLUSDT",  "SOL-USD"),
    "XRP":   ("XRPUSDT",  "XRPUSDT",  "XRP-USD"),
    "BNB":   ("BNBUSDT",  "BNBUSDT",  "BNB-USD"),
    "HYPE":  (None,        None,       "HYPE-USD"),   # DEX only
    "LINK":  ("LINKUSDT",  "LINKUSDT", "LINK-USD"),   # Chainlink — Binance + Bybit + Extended
    "XAU":   (None,        None,       "XAU-USD"),    # TradFi on Extended
    "XAG":   (None,        None,       "XAG-USD"),    # TradFi on Extended
    "WTI":   (None,        None,       "WTI-USD"),    # TradFi on Extended
    "SPX":   (None,        None,       "SPX500m-USD"),
    "TECH":  (None,        None,       "TECH100m-USD"),
}


# ── Binance ───────────────────────────────────────────────────────────────────

def fetch_binance_oi(symbols: list[str]) -> dict[str, dict]:
    """Returns {symbol: {oi_tokens, oi_usd, mark_price, funding_rate}}"""
    results = {}
    with httpx.Client(verify=_SSL, timeout=10) as c:
        for sym in symbols:
            if not sym:
                continue
            try:
                r_oi = c.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}")
                r_px = c.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}")
                oi_data = r_oi.json()
                px_data = r_px.json()

                oi_tokens  = float(oi_data.get("openInterest", 0))
                mark_price = float(px_data.get("markPrice", 0))
                funding    = float(px_data.get("lastFundingRate", 0))

                results[sym] = {
                    "oi_tokens":   oi_tokens,
                    "oi_usd":      oi_tokens * mark_price,
                    "mark_price":  mark_price,
                    "funding_rate": funding,
                }
            except Exception:
                pass
    return results


# ── Bybit ─────────────────────────────────────────────────────────────────────

def fetch_bybit_oi(symbols: list[str]) -> dict[str, dict]:
    results = {}
    with httpx.Client(verify=_SSL, timeout=10) as c:
        for sym in symbols:
            if not sym:
                continue
            try:
                r_oi = c.get(
                    "https://api.bybit.com/v5/market/open-interest",
                    params={"category": "linear", "symbol": sym,
                            "intervalTime": "1h", "limit": 1},
                )
                r_tk = c.get(
                    "https://api.bybit.com/v5/market/tickers",
                    params={"category": "linear", "symbol": sym},
                )
                oi_list = r_oi.json().get("result", {}).get("list", [])
                tk_list = r_tk.json().get("result", {}).get("list", [])

                if not oi_list or not tk_list:
                    continue

                oi_tokens  = float(oi_list[0].get("openInterest", 0))
                mark_price = float(tk_list[0].get("markPrice", 0))
                funding    = float(tk_list[0].get("fundingRate", 0))

                results[sym] = {
                    "oi_tokens":   oi_tokens,
                    "oi_usd":      oi_tokens * mark_price,
                    "mark_price":  mark_price,
                    "funding_rate": funding,
                }
            except Exception:
                pass
    return results


# ── Extended Exchange ─────────────────────────────────────────────────────────

def fetch_extended_oi(market_names: list[str]) -> dict[str, dict]:
    if not EXTENDED_API_KEY:
        return {}
    try:
        headers = {"User-Agent": "bot/1.0", "X-Api-Key": EXTENDED_API_KEY}
        with httpx.Client(verify=_SSL, timeout=12, headers=headers) as c:
            r = c.get("https://api.starknet.extended.exchange/api/v1/info/markets")
            body = r.json()
            markets = body.get("data", body) if isinstance(body, dict) else body
    except Exception:
        return {}

    lookup = {m.get("name"): m for m in markets if m.get("status") == "ACTIVE"}
    results = {}

    for name in market_names:
        if not name:
            continue
        m = lookup.get(name)
        if not m:
            continue
        try:
            s          = m.get("marketStats", {})
            oi_usd     = float(s.get("openInterest", 0) or 0)
            mark_price = float(s.get("markPrice", 0) or 0)
            funding    = float(s.get("fundingRate", 0) or 0)
            vol24      = float(s.get("dailyVolume", 0) or 0)
            results[name] = {
                "oi_usd":      oi_usd,
                "mark_price":  mark_price,
                "funding_rate": funding,
                "vol24h_usd":  vol24,
            }
        except Exception:
            pass
    return results


# ── Aggregation ───────────────────────────────────────────────────────────────

def collect_all(coins: list[str] | None = None, with_history: bool = True) -> list[dict]:
    targets = {k: v for k, v in INSTRUMENTS.items()
               if not coins or k in [c.upper() for c in coins]}

    bnb_syms = [v[0] for v in targets.values() if v[0]]
    bbt_syms = [v[1] for v in targets.values() if v[1]]
    ext_syms = [v[2] for v in targets.values() if v[2]]

    console.print("[dim]Fetching: Binance...[/dim]", end=" ")
    bnb = fetch_binance_oi(bnb_syms)
    console.print("[dim]Bybit...[/dim]", end=" ")
    bbt = fetch_bybit_oi(bbt_syms)
    console.print("[dim]Extended...[/dim]")
    ext = fetch_extended_oi(ext_syms)

    rows = []
    for coin, (bnb_sym, bbt_sym, ext_name) in targets.items():
        b  = bnb.get(bnb_sym, {})
        bb = bbt.get(bbt_sym, {})
        e  = ext.get(ext_name, {})

        oi_bnb = b.get("oi_usd", 0)
        oi_bbt = bb.get("oi_usd", 0)
        oi_ext = e.get("oi_usd", 0)
        total  = oi_bnb + oi_bbt + oi_ext

        # Use best available mark price
        mark = (b.get("mark_price") or bb.get("mark_price") or
                e.get("mark_price") or 0)

        # Funding: average of available sources
        fundings = [x for x in [b.get("funding_rate"), bb.get("funding_rate"),
                                 e.get("funding_rate")] if x is not None]
        funding_avg = sum(fundings) / len(fundings) if fundings else None

        if total == 0 and oi_ext == 0:
            continue

        rows.append({
            "coin":     coin,
            "ext_name": ext_name,
            "oi_bnb":   oi_bnb,
            "oi_bbt":   oi_bbt,
            "oi_ext":   oi_ext,
            "oi_total": total,
            "mark":     mark,
            "funding":  funding_avg,
            "vol24h":   e.get("vol24h_usd", 0),
        })

    if with_history:
        hist_map = fetch_history_all(HISTORY_DAYS)
        for r in rows:
            stats = trend_stats(hist_map.get(r["coin"], []))
            r["trend"] = stats
            r["view"]  = interpret_oi(stats["oi_chg_pct"], stats["price_chg_pct"], r["funding"]) if stats else None
    else:
        for r in rows:
            r["trend"], r["view"] = None, None

    return sorted(rows, key=lambda x: -x["oi_total"])


# ── History & trend ───────────────────────────────────────────────────────────

def fetch_history_all(days: int = HISTORY_DAYS) -> dict[str, list[dict]]:
    """Fetch per-coin OI history from the VPS (24/7 collector). Falls back to local DB."""
    try:
        params = {"days": days}
        if TV_SECRET:
            params["secret"] = TV_SECRET
        with httpx.Client(verify=_SSL, timeout=6) as c:
            r = c.get(OI_HISTORY_URL, params=params)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data:
                return data
    except Exception:
        pass
    return _local_history_all(days)


def _local_history_all(days: int) -> dict[str, list[dict]]:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = db._sqlite.query(
            "SELECT coin, ts, oi_total, mark_price FROM oi_snapshots WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        )
        out: dict[str, list[dict]] = {}
        for row in rows:
            out.setdefault(row["coin"], []).append(
                {"ts": row["ts"], "oi_total": row["oi_total"], "mark_price": row["mark_price"]}
            )
        return out
    except Exception:
        return {}


_BARS = "▁▂▃▄▅▆▇█"  # no blank — lowest value still renders a visible bar, not a gap

def _sparkline(values: list[float]) -> str:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = hi - lo
    if rng == 0:
        return _BARS[4] * len(vals)
    return "".join(_BARS[int((v - lo) / rng * (len(_BARS) - 1))] for v in vals)


def _bucket_daily(history: list[dict]) -> list[dict]:
    """One point per UTC day (last snapshot of that day). `history` must be ts-ascending."""
    by_day: dict[str, dict] = {}
    for h in history:
        by_day[h["ts"][:10]] = h
    return [by_day[d] for d in sorted(by_day)]


def trend_stats(history: list[dict]) -> dict | None:
    daily = _bucket_daily(history)
    if len(daily) < 2:
        return None
    oi_vals = [d["oi_total"] for d in daily]
    px_vals = [d.get("mark_price") or 0 for d in daily]
    oi_chg = (oi_vals[-1] - oi_vals[0]) / oi_vals[0] * 100 if oi_vals[0] else 0.0
    px_chg = (px_vals[-1] - px_vals[0]) / px_vals[0] * 100 if px_vals[0] else 0.0
    return {
        "days_covered": len(daily),
        "oi_chg_pct":   oi_chg,
        "price_chg_pct": px_chg,
        "spark":        _sparkline(oi_vals),
    }


def interpret_oi(oi_chg: float, px_chg: float, funding: float | None) -> str:
    """Classic OI/price quadrant read — what the move likely means."""
    FLAT = 2.0
    oi_up, oi_dn = oi_chg > FLAT, oi_chg < -FLAT
    px_up, px_dn = px_chg > FLAT, px_chg < -FLAT

    if oi_up and px_up:
        txt = "nowy kapital naplywa na longi — trend wzrostowy potwierdzony swiezymi pozycjami (kontynuacja)"
    elif oi_dn and px_up:
        txt = "cena rosnie przy spadku OI — to short-covering / realizacja zyskow, nie swiezy popyt (ruch moze sie wypalac)"
    elif oi_up and px_dn:
        txt = "nowy kapital naplywa na shorty — trend spadkowy potwierdzony (kontynuacja spadkow)"
    elif oi_dn and px_dn:
        txt = "cena spada przy spadku OI — likwidacje longow / zamykanie pozycji, presja slabnie (mozliwe wyczerpanie spadku)"
    elif oi_up:
        txt = "OI rosnie przy plaskiej cenie — budowa pozycji przed ruchem, rynek czeka na katalizator"
    elif oi_dn:
        txt = "OI spada przy plaskiej cenie — wygaszanie zaangazowania, spadek zainteresowania"
    else:
        txt = "brak wyraznego trendu OI — konsolidacja, rynek czeka na nowy impuls"

    if funding is not None:
        if funding > 0.0005:
            txt += "; funding dodatni — longi przewazaja i placa (ryzyko squeeze'u w dol)"
        elif funding < -0.0005:
            txt += "; funding ujemny — shorty przewazaja i placa (ryzyko squeeze'u w gore)"
    return txt


# ── Display ───────────────────────────────────────────────────────────────────

def _fmt_usd(v: float, decimals: int = 0) -> str:
    if v >= 1e9:  return f"${v/1e9:.2f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    if v >= 1e3:  return f"${v/1e3:.0f}K"
    return f"${v:.{decimals}f}"


def _funding_str(f: float | None) -> str:
    if f is None:
        return "—"
    pct = f * 100
    color = "green" if pct < 0 else "red" if pct > 0.05 else "yellow"
    return f"[{color}]{pct:+.4f}%[/{color}]"


def display_full(rows: list[dict], prev: dict | None = None) -> None:
    try:
        from tz_utils import fmt_both
        ts = fmt_both(datetime.now(timezone.utc))
    except Exception:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    table = Table(title=f"Open Interest — {ts}")
    table.add_column("Coin",    style="cyan", min_width=6)
    table.add_column("Binance", justify="right")
    table.add_column("Bybit",   justify="right")
    table.add_column("Extended",justify="right")
    table.add_column("TOTAL",   justify="right", style="bold white")
    table.add_column("Trend",   justify="right")
    table.add_column(f"{HISTORY_DAYS}D", justify="right")
    table.add_column("Funding", justify="right")

    for r in rows:
        coin = r["coin"]
        trend_str = "—"
        if prev and coin in prev:
            old = prev[coin]
            if old > 0:
                chg = (r["oi_total"] - old) / old * 100
                tc  = "green" if chg > 0 else "red"
                spike = " ⚠" if abs(chg) > 15 else ""
                trend_str = f"[{tc}]{chg:+.1f}%[/{tc}]{spike}"

        trend14 = r.get("trend")
        if trend14:
            tc14 = "green" if trend14["oi_chg_pct"] > 0 else "red" if trend14["oi_chg_pct"] < 0 else "yellow"
            trend14_str = f"[{tc14}]{trend14['oi_chg_pct']:+.1f}%[/{tc14}] {trend14['spark']}"
        else:
            trend14_str = "[dim]zbiera sie...[/dim]"

        table.add_row(
            coin,
            _fmt_usd(r["oi_bnb"]) if r["oi_bnb"] else "—",
            _fmt_usd(r["oi_bbt"]) if r["oi_bbt"] else "—",
            _fmt_usd(r["oi_ext"]) if r["oi_ext"] else "—",
            _fmt_usd(r["oi_total"]),
            trend_str,
            trend14_str,
            _funding_str(r["funding"]),
        )

    console.print(table)
    console.print("[dim]Funding: ujemny=shorci placa=bullish signal | dodatni=longi placa=crowded long[/dim]")

    views = [r for r in rows if r.get("view")]
    if views:
        console.print(f"\n[bold cyan]📊 Expert View — interpretacja OI ({HISTORY_DAYS}D):[/bold cyan]")
        for r in views[:8]:
            console.print(f"  [bold]{r['coin']}[/bold]: {r['view']}")
    elif not (prev):
        console.print(
            f"\n[dim]Historia OI zbiera sie od teraz (kolektor co 1h na VPS) — "
            f"trend {HISTORY_DAYS}D bedzie widoczny po kilku dniach.[/dim]"
        )

    # Spike alerts
    if prev:
        for r in rows:
            coin = r["coin"]
            if coin in prev and prev[coin] > 0:
                chg = (r["oi_total"] - prev[coin]) / prev[coin] * 100
                if abs(chg) > 15:
                    c = "green" if chg > 0 else "red"
                    console.print(
                        f"\n[bold {c}]SPIKE {coin}:[/bold {c}] OI {chg:+.1f}% — "
                        f"{'nowe pozycje otwierane agresywnie' if chg > 0 else 'masowe zamkniecia / likwidacje'}"
                    )


def display_brief(rows: list[dict]) -> None:
    parts = []
    for r in rows[:6]:
        trend = r.get("trend")
        tag = f" ({trend['oi_chg_pct']:+.1f}% {HISTORY_DAYS}D)" if trend else ""
        parts.append(f"{r['coin']}: {_fmt_usd(r['oi_total'])}{tag}")
    print("OI aggregate: " + "  |  ".join(parts))

    movers = sorted((r for r in rows if r.get("view")), key=lambda r: -abs(r["trend"]["oi_chg_pct"]))
    if movers:
        print("Interpretacja OI:")
        for r in movers[:3]:
            print(f"  {r['coin']}: {r['view']}")
    elif not any(r.get("trend") for r in rows):
        print(f"(historia OI zbiera sie od teraz — trend {HISTORY_DAYS}D widoczny po kilku dniach)")

    # Funding warnings
    warnings = []
    for r in rows:
        f = r.get("funding")
        if f and abs(f) > 0.0005:
            direction = "long crowded" if f > 0 else "short crowded"
            warnings.append(f"{r['coin']} funding {f*100:+.4f}% ({direction})")
    if warnings:
        print("Funding alerts: " + " | ".join(warnings[:3]))


# ── DB integration ────────────────────────────────────────────────────────────

def load_prev_snapshot() -> dict | None:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()
        rows = db._sqlite.query(
            "SELECT coin, oi_total FROM oi_snapshots ORDER BY ts DESC LIMIT 50"
        )
        if not rows:
            return None
        # Get most recent per coin
        seen = {}
        for row in rows:
            if row["coin"] not in seen:
                seen[row["coin"]] = row["oi_total"]
        return seen
    except Exception:
        return None


def save_snapshot(rows: list[dict]) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in rows:
            db._sqlite.execute(
                """INSERT OR IGNORE INTO oi_snapshots
                   (ts, coin, oi_binance, oi_bybit, oi_extended, oi_total, mark_price, funding_rate)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ts, r["coin"], r["oi_bnb"], r["oi_bbt"], r["oi_ext"],
                 r["oi_total"], r["mark"], r["funding"]),
            )
        console.print(f"[dim]Saved {len(rows)} coins to DB[/dim]")
    except Exception as ex:
        console.print(f"[dim]DB save skipped: {ex}[/dim]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="OI tracker — Binance + Bybit + Extended")
    p.add_argument("--coins",  nargs="+", metavar="COIN",
                   help="Filter: BTC ETH SOL etc.")
    p.add_argument("--brief",  action="store_true",
                   help="Compact output for daily alpha")
    p.add_argument("--save",   action="store_true",
                   help="(zachowane dla kompatybilnosci — zapis do SQLite jest teraz zawsze wlaczony)")
    p.add_argument("--trend",  action="store_true",
                   help="Compare to previous DB snapshot")
    p.add_argument("--no-history", action="store_true",
                   help=f"Pomin pobieranie {HISTORY_DAYS}D historii/interpretacji (szybszy odczyt, np. dla cronu)")
    args = p.parse_args()

    rows = collect_all(coins=args.coins, with_history=not args.no_history)
    if not rows:
        console.print("[red]No data returned[/red]")
        sys.exit(1)

    prev = load_prev_snapshot() if args.trend else None

    if args.brief:
        display_brief(rows)
    else:
        display_full(rows, prev=prev)

    save_snapshot(rows)  # zawsze — buduje historie do trendu 14D automatycznie


if __name__ == "__main__":
    main()
