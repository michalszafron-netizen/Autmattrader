"""Live price quotes for all TradFi instruments — Hyperliquid xyz + Finnhub.

Single `allMids` call to HL xyz returns ALL prices instantly (no per-asset calls).
Finnhub used for US stocks not on HL, and as fallback.

Usage:
    python scripts/quotes.py                    # full table grouped by category
    python scripts/quotes.py --brief            # compact one-liner per category
    python scripts/quotes.py --json             # machine-readable JSON
    python scripts/quotes.py --group metals     # only metals
    python scripts/quotes.py --group energy     # energy
    python scripts/quotes.py --group indices    # indices + DXY + VIX
    python scripts/quotes.py --group agri       # corn, wheat
    python scripts/quotes.py --group stocks     # NVDA, TSLA, AAPL etc.
    python scripts/quotes.py --coins GOLD CORN SP500  # custom list
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

_SSL    = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
HL_API  = "https://api.hyperliquid.xyz"
XYZ_DEX = "xyz"
console = Console()

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_URL = "https://finnhub.io/api/v1"

# ── Instrument catalogue ──────────────────────────────────────────────────────
# Format: (display_name, hl_ticker, finnhub_symbol, decimals, unit_note)
# hl_ticker=None → use Finnhub only
# finnhub_symbol=None → use HL only

CATALOGUE: dict[str, list[tuple]] = {
    # ZASADA: nigdy nie używaj ETF proxy (GLD/SLV/USO) jako ceny spot — to nie to samo.
    # Wszystkie ceny towarów/indeksów bierzemy z HL xyz (live, bez opóźnień, prawdziwe ceny).
    # Finnhub tylko dla akcji US których nie ma na HL xyz.
    "metals": [
        ("Gold",      "xyz:GOLD",      None, 2, "USD/oz"),
        ("Silver",    "xyz:SILVER",    None, 3, "USD/oz"),
        ("Copper",    "xyz:COPPER",    None, 4, "USD/lb"),
        ("Platinum",  "xyz:PLATINUM",  None, 2, "USD/oz"),
        ("Palladium", "xyz:PALLADIUM", None, 2, "USD/oz"),
    ],
    "energy": [
        ("Brent Oil", "xyz:BRENTOIL", None, 2, "USD/bbl"),
        ("US Oil",    "xyz:CL",       None, 2, "USD/bbl"),
        ("Nat Gas",   "xyz:NATGAS",   None, 4, "USD/MMBtu"),
        ("EU Gas TTF","xyz:TTF",      None, 2, "EUR/MWh"),
    ],
    "agri": [
        ("Corn",    "xyz:CORN",    None, 4, "USD/bu"),
        ("Wheat",   "xyz:WHEAT",   None, 4, "USD/bu"),
        ("Uranium", "xyz:URANIUM", None, 3, "USD/lb"),
    ],
    "indices": [
        ("S&P 500", "xyz:SP500", None, 2, "pts"),
        ("VIX",     "xyz:VIX",   None, 2, "pts"),
        ("DXY",     "xyz:DXY",   None, 3, "index"),
        ("EUR/USD", "xyz:EUR",   None, 5, "rate"),
        ("GBP/USD", "xyz:GBP",   None, 5, "rate"),
        ("JPY/USD", "xyz:JPY",   None, 6, "rate"),
        ("Nikkei",  "xyz:JP225", None, 0, "pts"),
    ],
    "stocks": [
        # HL xyz ma prawie wszystkie duże US stocks — Finnhub tylko jako backup
        ("NVDA",  "xyz:NVDA",  "NVDA",  2, "USD"),
        ("TSLA",  "xyz:TSLA",  "TSLA",  2, "USD"),
        ("AAPL",  "xyz:AAPL",  "AAPL",  2, "USD"),
        ("MSFT",  "xyz:MSFT",  "MSFT",  2, "USD"),
        ("META",  "xyz:META",  "META",  2, "USD"),
        ("GOOGL", "xyz:GOOGL", "GOOGL", 2, "USD"),
        ("AMZN",  "xyz:AMZN",  "AMZN",  2, "USD"),
        ("PLTR",  "xyz:PLTR",  "PLTR",  2, "USD"),
        ("COIN",  "xyz:COIN",  "COIN",  2, "USD"),
    ],
}

ALL_INSTRUMENTS = {
    name: info
    for group in CATALOGUE.values()
    for (name, *info) in [(item[0], item[1:]) for item in group]
}


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_hl_mids() -> dict[str, float]:
    """Single call — returns ALL xyz mid prices."""
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            r = c.post(f"{HL_API}/info", json={"type": "allMids", "dex": XYZ_DEX})
            r.raise_for_status()
            raw = r.json()
            return {k: float(v) for k, v in raw.items() if v}
    except Exception as e:
        console.print(f"[red]HL allMids error: {e}[/red]")
        return {}


def fetch_finnhub_quote(symbol: str) -> dict | None:
    """Single stock/ETF quote from Finnhub."""
    if not FINNHUB_KEY or not symbol:
        return None
    try:
        with httpx.Client(verify=_SSL, timeout=8) as c:
            r = c.get(f"{FINNHUB_URL}/quote",
                      params={"symbol": symbol, "token": FINNHUB_KEY})
            r.raise_for_status()
            data = r.json()
            return data if data.get("c") else None
    except Exception:
        return None


def fetch_all_quotes(groups: list[str] | None = None,
                     coins: list[str] | None = None) -> list[dict]:
    """Fetch prices for requested instruments. Returns list of result dicts."""
    # Determine which instruments to fetch
    if coins:
        targets = []
        for grp in CATALOGUE.values():
            for item in grp:
                if item[0].upper() in [c.upper() for c in coins]:
                    targets.append(item)
    elif groups:
        targets = []
        for g in groups:
            targets.extend(CATALOGUE.get(g, []))
    else:
        targets = [item for grp in CATALOGUE.values() for item in grp]

    # Single HL call for all xyz prices
    hl_mids = fetch_hl_mids()

    results = []
    for (name, hl_ticker, fh_symbol, decimals, unit) in targets:
        price = None
        source = None

        # Try HL first
        if hl_ticker and hl_ticker in hl_mids:
            price = hl_mids[hl_ticker]
            source = "HL"

        # Finnhub fallback / supplement
        if price is None and fh_symbol:
            fh = fetch_finnhub_quote(fh_symbol)
            if fh:
                price = fh.get("c")
                source = "FH"

        results.append({
            "name":     name,
            "hl":       hl_ticker,
            "fh":       fh_symbol,
            "price":    price,
            "decimals": decimals,
            "unit":     unit,
            "source":   source,
        })
    return results


# ── Display ───────────────────────────────────────────────────────────────────

def _fmt_price(price: float | None, decimals: int) -> str:
    if price is None:
        return "[dim]—[/dim]"
    if price >= 10000:
        return f"${price:,.0f}"
    if price >= 100:
        return f"${price:,.{min(decimals,2)}f}"
    return f"${price:,.{decimals}f}"


def display_full(results: list[dict], group_name: str = "") -> None:
    try:
        from tz_utils import fmt_both
        ts = fmt_both(datetime.now(timezone.utc))
    except Exception:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    title = f"Live Quotes — {ts}"
    if group_name:
        title += f"  [{group_name}]"

    table = Table(title=title)
    table.add_column("Instrument", style="cyan", min_width=12)
    table.add_column("Price", justify="right", style="bold white")
    table.add_column("Unit", style="dim", justify="right")
    table.add_column("Src", style="dim", justify="center")

    for r in results:
        price_str = _fmt_price(r["price"], r["decimals"])
        src_color = "green" if r["source"] == "HL" else "yellow" if r["source"] == "FH" else "red"
        src = f"[{src_color}]{r['source'] or '—'}[/{src_color}]"
        table.add_row(r["name"], price_str, r["unit"], src)

    console.print(table)
    console.print("[dim]Src: HL=Hyperliquid live | FH=Finnhub[/dim]")


def display_brief(results: list[dict]) -> None:
    """Compact output for daily alpha — one line per group."""
    groups_order = [
        ("Metals",  ["Gold", "Silver", "Copper"]),
        ("Energy",  ["Brent Oil", "US Oil", "Nat Gas"]),
        ("Indices", ["S&P 500", "VIX", "DXY"]),
        ("Agri",    ["Corn", "Wheat"]),
        ("Stocks",  ["NVDA", "TSLA", "AAPL"]),
    ]
    by_name = {r["name"]: r for r in results}

    for label, names in groups_order:
        parts = []
        for n in names:
            r = by_name.get(n)
            if r and r["price"]:
                parts.append(f"{n}: {_fmt_price(r['price'], r['decimals'])}")
        if parts:
            print(f"{label}: " + "  |  ".join(parts))


def display_json(results: list[dict]) -> None:
    out = {r["name"]: r["price"] for r in results}
    print(json.dumps(out, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Live TradFi quotes — HL xyz + Finnhub")
    p.add_argument("--group",  choices=list(CATALOGUE.keys()),
                   help="Filter by asset group")
    p.add_argument("--coins",  nargs="+", metavar="COIN",
                   help="Specific instruments e.g. GOLD CORN SP500")
    p.add_argument("--brief",  action="store_true",
                   help="Compact one-liners for daily alpha")
    p.add_argument("--json",   action="store_true",
                   help="JSON output for programmatic use")
    args = p.parse_args()

    groups = [args.group] if args.group else None
    results = fetch_all_quotes(groups=groups, coins=args.coins)

    if args.json:
        display_json(results)
    elif args.brief:
        display_brief(results)
    else:
        display_full(results, group_name=args.group or "")


if __name__ == "__main__":
    main()
