"""COT (Commitment of Traders) tracker — institutional positioning for TradFi.

Data source: CFTC (Commodity Futures Trading Commission) — free, public, weekly.
Published every Friday for the previous Tuesday's positions.

Covers: Gold, Silver, Oil, S&P 500, Nasdaq 100, US Dollar Index.

How to read COT for trading:
  COMMODITIES (Gold, Silver, Oil):
    - "Commercials" = hedgers (miners, producers, banks). These know physical market best.
    - When Commercials are at EXTREME NET LONG → bullish signal (buying dips below cost)
    - When Commercials are at EXTREME NET SHORT → bearish signal
    - Use %ile of 3-year range: >80%ile = extreme, <20%ile = opposite extreme

  EQUITIES (S&P, Nasdaq):
    - "Non-Commercials" (large specs / hedge funds) are the trend followers
    - Extreme long = crowded trade, risk of reversal
    - Extreme short = potential short squeeze

Usage:
  python scripts/cot_tracker.py                    # all 6 assets
  python scripts/cot_tracker.py --asset GOLD       # single asset
  python scripts/cot_tracker.py --years 3          # use 3y history for %ile (default)
  python scripts/cot_tracker.py --brief            # one-liner per asset (for daily brief)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Fix: requests → httpx proxy (prevents OPENSSL_Uplink crash on Windows) ───
# Python's native ssl module / OpenSSL triggers OPENSSL_Uplink on this setup.
# cot_reports uses requests internally to download CFTC zip files.
# We replace requests.get / requests.Session with httpx equivalents (Windows SChannel).
import ssl as _ssl
import types as _types
import httpx as _httpx
import truststore as _truststore

_SSL_CTX_PATCH = _truststore.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)


class _FakeResponse:
    def __init__(self, r: _httpx.Response) -> None:
        self.status_code = r.status_code
        self.content     = r.content
        self.text        = r.text
        self.headers     = dict(r.headers)
        self._r          = r

    def raise_for_status(self) -> None:
        self._r.raise_for_status()


def _httpx_get(url: str, **kw) -> _FakeResponse:
    kw.pop("stream", None)
    kw.pop("verify", None)
    return _FakeResponse(
        _httpx.get(url, verify=_SSL_CTX_PATCH, follow_redirects=True,
                   timeout=kw.pop("timeout", 120), **kw)
    )


class _FakeSession:
    def get(self, url: str, **kw) -> _FakeResponse:
        return _httpx_get(url, **kw)
    def __enter__(self):  return self
    def __exit__(self, *a): pass


_fake_requests = _types.ModuleType("requests")
_fake_requests.get = _httpx_get  # type: ignore[attr-defined]
_fake_requests.Session = _FakeSession  # type: ignore[attr-defined]
_fake_requests.exceptions = _types.ModuleType("requests.exceptions")  # type: ignore[attr-defined]
_fake_requests.exceptions.RequestException = Exception  # type: ignore[attr-defined]
sys.modules["requests"] = _fake_requests
# ─────────────────────────────────────────────────────────────────────────────

console = Console()

# ── Asset definitions ─────────────────────────────────────────────────────────

ASSETS = {
    "GOLD": {
        "search": "GOLD - COMMODITY EXCHANGE",
        "smart_money": "Commercials",   # hedgers = smart money for commodities
        "interpretation": "bearish when commercials extreme long (contrarian vs futures shorts)",
    },
    "SILVER": {
        "search": "SILVER - COMMODITY EXCHANGE",
        "smart_money": "Commercials",
    },
    "OIL": {
        "search": "CRUDE OIL, LIGHT SWEET-WTI - ICE FUTURES EUROPE",
        "smart_money": "Commercials",
    },
    "SP500": {
        "search": "S&P 500 Consol",
        "smart_money": "NonComm",       # large specs drive equity trends
        "interpretation": "extreme long = crowded, risk of pullback",
    },
    "NASDAQ": {
        "search": "NASDAQ-100 Consol",
        "smart_money": "NonComm",
    },
    "EURO": {
        "search": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
        "smart_money": "NonComm",
        "interpretation": "inverted USD proxy — spec long Euro = spec short USD",
    },

    # ── Soft Commodities (rolnicze) ──────────────────────────────────────────
    # Commercials = producenci/przetwórcy = smart money w rolnictwie
    # Wysoki %ile commercial long = oczekują wzrostu cen = BULLISH
    "CORN": {
        "search": "CORN - CHICAGO BOARD OF TRADE",
        "smart_money": "Commercials",
        "interpretation": "hedgers include grain elevators and food processors",
    },
    "COFFEE": {
        "search": "COFFEE C - ICE FUTURES U.S.",
        "smart_money": "Commercials",
        "interpretation": "hedgers include coffee roasters and exporters",
    },
    "COCOA": {
        "search": "COCOA - ICE FUTURES U.S.",
        "smart_money": "Commercials",
        "interpretation": "hedgers include chocolate manufacturers",
    },
    "SUGAR": {
        "search": "SUGAR NO. 11 - ICE FUTURES U.S.",
        "smart_money": "Commercials",
        "interpretation": "global sugar #11 benchmark, hedgers include refiners",
    },
    "WHEAT": {
        "search": "WHEAT-SRW - CHICAGO BOARD OF TRADE",
        "smart_money": "Commercials",
        "interpretation": "soft red winter wheat benchmark",
    },
    "SOYBEANS": {
        "search": "SOYBEANS - CHICAGO BOARD OF TRADE",
        "smart_money": "Commercials",
        "interpretation": "key for animal feed and biofuel, China demand proxy",
    },
}

# Column name mappings (legacy_fut format)
COL_NAME = "Market and Exchange Names"
COL_DATE = "As of Date in Form YYYY-MM-DD"
COL_OI   = "Open Interest (All)"

# Long/Short columns per category (exact names from CFTC legacy_fut)
COLS = {
    "Commercials": ("Commercial Positions-Long (All)", "Commercial Positions-Short (All)"),
    "NonComm":     ("Noncommercial Positions-Long (All)", "Noncommercial Positions-Short (All)"),
    "NonRept":     ("Nonreportable Positions-Long (All)", "Nonreportable Positions-Short (All)"),
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_cot(years: int = 3) -> pd.DataFrame:
    import cot_reports as cot
    import datetime

    current_year = datetime.datetime.now().year
    frames = []
    for y in range(current_year - years + 1, current_year + 1):
        try:
            df = cot.cot_year(year=y, cot_report_type="legacy_fut")
            frames.append(df)
        except Exception as e:
            console.print(f"[dim]Warning: could not load {y}: {e}[/dim]")
    if not frames:
        raise RuntimeError("Could not load any COT data")
    combined = pd.concat(frames, ignore_index=True)
    combined[COL_DATE] = pd.to_datetime(combined[COL_DATE], errors="coerce")
    return combined.sort_values(COL_DATE)


def get_asset_series(df: pd.DataFrame, asset_key: str) -> pd.DataFrame:
    cfg = ASSETS[asset_key]
    mask = df[COL_NAME].str.contains(cfg["search"], case=False, na=False)
    sub = df[mask].copy()
    if sub.empty:
        raise ValueError(f"No COT data found for {asset_key} (search: {cfg['search']})")
    return sub


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyze(asset_key: str, df: pd.DataFrame) -> dict:
    cfg = ASSETS[asset_key]
    series = get_asset_series(df, asset_key)
    sm = cfg["smart_money"]
    long_col, short_col = COLS[sm]

    series = series.copy()
    series["net"] = series[long_col] - series[short_col]
    series["net_pct_oi"] = series["net"] / series[COL_OI] * 100

    latest = series.iloc[-1]
    prev   = series.iloc[-2] if len(series) > 1 else latest

    net_now  = float(latest["net"])
    net_prev = float(prev["net"])
    net_pct  = float(latest["net_pct_oi"])
    oi       = float(latest[COL_OI])
    date     = latest[COL_DATE].strftime("%Y-%m-%d")

    # Percentile within full history
    net_series = series["net"].dropna()
    pctile = float((net_series < net_now).mean() * 100)

    # Change vs last week
    delta = net_now - net_prev
    delta_str = f"{'+' if delta > 0 else ''}{delta:,.0f}"

    return {
        "asset": asset_key,
        "date": date,
        "smart_money_type": sm,
        "net_contracts": net_now,
        "net_pct_oi": net_pct,
        "open_interest": oi,
        "week_change": delta,
        "week_change_str": delta_str,
        "percentile": pctile,
        "signal": _signal(pctile, sm),
        "history_years": len(series["As of Date in Form YYYY-MM-DD"].dt.year.unique()),
    }


def _signal(pctile: float, sm_type: str) -> str:
    """Interpret percentile as trading signal."""
    if sm_type == "Commercials":
        # Commercials: net long = they're hedging against price RISE
        # High %ile (commercials net very long) = they expect prices to rise = BULLISH
        if pctile >= 80:
            return "BULLISH (extreme commercial long)"
        elif pctile >= 60:
            return "mildly bullish"
        elif pctile <= 20:
            return "BEARISH (extreme commercial short)"
        elif pctile <= 40:
            return "mildly bearish"
        else:
            return "neutral"
    else:
        # Large specs: extreme long = crowded = bearish risk
        if pctile >= 80:
            return "CROWDED LONG (reversal risk)"
        elif pctile >= 60:
            return "leaning long"
        elif pctile <= 20:
            return "EXTREME SHORT (squeeze risk)"
        elif pctile <= 40:
            return "leaning short"
        else:
            return "neutral"


# ── Display ───────────────────────────────────────────────────────────────────

def display_table(results: list[dict]) -> None:
    table = Table(title="COT — Institutional Positioning (CFTC)")
    table.add_column("Asset", style="cyan")
    table.add_column("Smart Money", style="dim")
    table.add_column("Net (contracts)", justify="right")
    table.add_column("% of OI", justify="right")
    table.add_column("Wk Change", justify="right")
    table.add_column("Percentile", justify="center")
    table.add_column("Signal")
    table.add_column("Date", style="dim")

    for r in results:
        pct = r["percentile"]
        pct_color = "green" if pct >= 70 else "red" if pct <= 30 else "yellow"
        sig = r["signal"]
        sig_color = "green" if "BULLISH" in sig or "squeeze" in sig else \
                    "red" if "BEARISH" in sig or "CROWDED" in sig else "yellow"
        chg = r["week_change"]
        chg_color = "green" if chg > 0 else "red" if chg < 0 else "dim"
        table.add_row(
            r["asset"],
            r["smart_money_type"],
            f"{r['net_contracts']:+,.0f}",
            f"{r['net_pct_oi']:+.1f}%",
            f"[{chg_color}]{r['week_change_str']}[/{chg_color}]",
            f"[{pct_color}]{pct:.0f}%ile[/{pct_color}]",
            f"[{sig_color}]{sig}[/{sig_color}]",
            r["date"],
        )

    console.print()
    console.print(table)
    console.print(
        "\n[dim]Percentile vs full history. "
        "Commercials = hedgers (smart for commodities). "
        "NonComm = large specs (hedge funds).[/dim]"
    )


def display_brief(results: list[dict]) -> None:
    console.print("\n[bold]COT Brief:[/bold]")
    for r in results:
        pct = r["percentile"]
        sig = r["signal"]
        color = "green" if "BULLISH" in sig or "squeeze" in sig else \
                "red" if "BEARISH" in sig or "CROWDED" in sig else "yellow"
        console.print(
            f"  [{color}]{r['asset']:8}[/{color}] "
            f"{r['net_contracts']:>+10,.0f} contracts  "
            f"{pct:>3.0f}%ile  [{color}]{sig}[/{color}]"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="CFTC COT institutional positioning tracker")
    p.add_argument("--asset", choices=list(ASSETS), help="Single asset (default: all)")
    p.add_argument("--years", type=int, default=3, help="History years for percentile (default 3)")
    p.add_argument("--brief", action="store_true", help="One-liner output for daily brief")
    args = p.parse_args()

    targets = [args.asset] if args.asset else list(ASSETS)

    console.print(f"\n[bold]Loading COT data ({args.years}y history)…[/bold]", end=" ")
    try:
        df = load_cot(years=args.years)
        console.print(f"[green]OK[/green] — {len(df):,} records")
    except Exception as e:
        console.print(f"[red]FAILED: {e}[/red]")
        sys.exit(1)

    results = []
    for key in targets:
        try:
            results.append(analyze(key, df))
        except Exception as e:
            console.print(f"[red]{key}: {e}[/red]")

    if not results:
        console.print("[red]No data to display.[/red]")
        sys.exit(1)

    if args.brief:
        display_brief(results)
    else:
        display_table(results)


if __name__ == "__main__":
    main()
