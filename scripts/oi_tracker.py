"""Open Interest tracker — Binance + Bybit + Extended Exchange.

Aggregates OI across three sources, tracks trends vs previous snapshot,
saves to SQLite, alerts on spikes >15%.

Usage:
    python scripts/oi_tracker.py                    # full report
    python scripts/oi_tracker.py --brief            # compact for daily alpha
    python scripts/oi_tracker.py --coins BTC ETH    # specific coins only
    python scripts/oi_tracker.py --save             # save snapshot to DB
    python scripts/oi_tracker.py --trend            # compare to last snapshot

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
from datetime import datetime, timezone
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

# Instruments to track (symbol: Binance ticker, Bybit ticker, Extended name)
INSTRUMENTS = {
    "BTC":   ("BTCUSDT",  "BTCUSDT",  "BTC-USD"),
    "ETH":   ("ETHUSDT",  "ETHUSDT",  "ETH-USD"),
    "SOL":   ("SOLUSDT",  "SOLUSDT",  "SOL-USD"),
    "XRP":   ("XRPUSDT",  "XRPUSDT",  "XRP-USD"),
    "BNB":   ("BNBUSDT",  "BNBUSDT",  "BNB-USD"),
    "HYPE":  (None,        None,       "HYPE-USD"),   # DEX only
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

def collect_all(coins: list[str] | None = None) -> list[dict]:
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

    return sorted(rows, key=lambda x: -x["oi_total"])


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

        table.add_row(
            coin,
            _fmt_usd(r["oi_bnb"]) if r["oi_bnb"] else "—",
            _fmt_usd(r["oi_bbt"]) if r["oi_bbt"] else "—",
            _fmt_usd(r["oi_ext"]) if r["oi_ext"] else "—",
            _fmt_usd(r["oi_total"]),
            trend_str,
            _funding_str(r["funding"]),
        )

    console.print(table)
    console.print("[dim]Funding: ujemny=shorci placa=bullish signal | dodatni=longi placa=crowded long[/dim]")

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
        parts.append(f"{r['coin']}: {_fmt_usd(r['oi_total'])}")
    print("OI aggregate: " + "  |  ".join(parts))

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
                   help="Save snapshot to SQLite")
    p.add_argument("--trend",  action="store_true",
                   help="Compare to previous DB snapshot")
    args = p.parse_args()

    rows = collect_all(coins=args.coins)
    if not rows:
        console.print("[red]No data returned[/red]")
        sys.exit(1)

    prev = load_prev_snapshot() if args.trend else None

    if args.brief:
        display_brief(rows)
    else:
        display_full(rows, prev=prev)

    if args.save:
        save_snapshot(rows)


if __name__ == "__main__":
    main()
