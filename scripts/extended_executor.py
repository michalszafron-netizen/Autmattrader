"""Extended Exchange executor — StarkNet DEX (extended.exchange).

Read-only via API Key. Write operations (orders) require Stark private key signing.

Usage:
    python scripts/extended_executor.py positions
    python scripts/extended_executor.py balance
    python scripts/extended_executor.py orders
    python scripts/extended_executor.py markets        # available markets + prices
    python scripts/extended_executor.py quote BTC-USD-PERP

Docs: https://api.docs.extended.exchange/
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import ssl
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL   = "https://api.starknet.extended.exchange"
API_KEY    = os.getenv("EXTENDED_API_KEY", "")
console    = Console()
_SSL       = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _headers() -> dict:
    h = {"User-Agent": "trading-ai-bot/1.0"}
    if API_KEY:
        h["X-Api-Key"] = API_KEY
    return h


def _get(path: str, params: dict | None = None) -> dict | list:
    with httpx.Client(verify=_SSL, timeout=15, headers=_headers()) as c:
        r = c.get(f"{BASE_URL}{path}", params=params or {})
        if r.status_code == 401:
            console.print("[red]401 Unauthorized — sprawdz EXTENDED_API_KEY w .env[/red]")
            sys.exit(1)
        r.raise_for_status()
        body = r.json()
        # API wraps all responses: {"status": "OK", "data": ...}
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_balance(args: argparse.Namespace) -> None:
    data = _get("/api/v1/user/balance")

    equity       = data.get("equity", "?")
    balance      = data.get("balance", "?")
    free_margin  = data.get("availableForTrade", "?")
    used_margin  = data.get("initialMargin", "?")
    unreal_pnl   = data.get("unrealisedPnl", "?")
    margin_ratio = data.get("marginRatio", "?")
    acct_health  = data.get("accountHealth", "?")
    leverage     = data.get("leverage", "?")

    try:
        from tz_utils import fmt_both
        from datetime import datetime, timezone
        ts = fmt_both(datetime.now(timezone.utc))
    except Exception:
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    console.print(f"\n[bold]Extended Exchange — Balance[/bold]  [dim]{ts}[/dim]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold white", justify="right")

    def fmt(v):
        try:
            return f"${float(v):,.2f}"
        except Exception:
            return str(v)

    pnl_val = float(unreal_pnl) if unreal_pnl != "?" else 0
    pnl_color = "green" if pnl_val >= 0 else "red"

    try:
        health_f = float(acct_health)
        hc = "green" if health_f > 0.8 else "yellow" if health_f > 0.5 else "red"
        health_str = f"[{hc}]{health_f*100:.1f}%[/{hc}]"
    except Exception:
        health_str = str(acct_health)

    try:
        mr_f = float(margin_ratio)
        mrc = "green" if mr_f < 0.5 else "yellow" if mr_f < 0.8 else "red"
        mr_str = f"[{mrc}]{mr_f*100:.2f}%[/{mrc}]"
    except Exception:
        mr_str = str(margin_ratio)

    table.add_row("Balance",          fmt(balance))
    table.add_row("Equity",           fmt(equity))
    table.add_row("Available",        fmt(free_margin))
    table.add_row("Used Margin",      fmt(used_margin))
    table.add_row("Unrealised PnL",   f"[{pnl_color}]{fmt(unreal_pnl)}[/{pnl_color}]")
    table.add_row("Margin Ratio",     mr_str)
    table.add_row("Account Health",   health_str)
    table.add_row("Avg Leverage",     f"{float(leverage):.2f}x" if leverage != "?" else "?")

    console.print(table)

    # Spot balances
    try:
        spot = _get("/api/v1/user/spot/balances")
        assets = spot if isinstance(spot, list) else spot.get("balances", [])
        if assets:
            console.print("\n[bold]Spot holdings:[/bold]")
            for a in assets:
                sym = a.get("asset", a.get("symbol", "?"))
                qty = a.get("balance", a.get("amount", "?"))
                console.print(f"  {sym}: {qty}")
    except Exception:
        pass


def cmd_positions(args: argparse.Namespace) -> None:
    data = _get("/api/v1/user/positions")
    positions = data if isinstance(data, list) else data.get("positions", [])

    if not positions:
        console.print("[dim]Extended: no open positions[/dim]")
        return

    table = Table(title="Extended — Open Positions")
    table.add_column("Market", style="cyan")
    table.add_column("Side")
    table.add_column("Size", justify="right")
    table.add_column("Entry $", justify="right")
    table.add_column("Mark $", justify="right")
    table.add_column("uPnL $", justify="right")
    table.add_column("Lev", justify="right", style="dim")

    for p in positions:
        market = p.get("market", p.get("symbol", "?"))
        side   = p.get("side", "?").upper()
        sc     = "green" if side == "LONG" else "red"
        size   = p.get("size", p.get("quantity", "?"))
        entry  = p.get("openPrice", p.get("entryPrice", "?"))
        mark   = p.get("markPrice", "?")
        upnl   = p.get("unrealisedPnl", p.get("unrealizedPnl", "?"))
        lev    = p.get("leverage", "?")

        try:
            upnl_f = float(upnl)
            uc = "green" if upnl_f >= 0 else "red"
            upnl_str = f"[{uc}]${upnl_f:+,.2f}[/{uc}]"
        except Exception:
            upnl_str = str(upnl)

        def fp(v, d=2):
            try: return f"${float(v):,.{d}f}"
            except: return str(v)

        table.add_row(
            market,
            f"[{sc}]{side}[/{sc}]",
            str(size),
            fp(entry),
            fp(mark),
            upnl_str,
            f"{lev}x" if lev != "?" else "?",
        )
    console.print(table)


def cmd_orders(args: argparse.Namespace) -> None:
    data = _get("/api/v1/user/orders")
    orders = data if isinstance(data, list) else data.get("orders", [])

    if not orders:
        console.print("[dim]Extended: no open orders[/dim]")
        return

    table = Table(title="Extended — Open Orders")
    table.add_column("Market", style="cyan")
    table.add_column("Type")
    table.add_column("Side")
    table.add_column("Price $", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Status", style="dim")

    for o in orders:
        market = o.get("market", "?")
        otype  = o.get("type", "?").upper()
        side   = o.get("side", "?").upper()
        sc     = "green" if side == "BUY" else "red"
        size   = o.get("qty", o.get("size", "?"))
        status = o.get("status", "?")

        # TPSL orders have nested tp/sl with triggerPrice
        tp = o.get("takeProfit")
        sl = o.get("stopLoss")
        if tp:
            trigger = tp.get("triggerPrice", "?")
            label = f"TP @${trigger}"
        elif sl:
            trigger = sl.get("triggerPrice", "?")
            label = f"SL @${trigger}"
        else:
            price = o.get("price", o.get("limitPrice", "?"))
            try: label = f"${float(price):,.2f}"
            except: label = str(price)

        table.add_row(market, otype, f"[{sc}]{side}[/{sc}]",
                      label, str(size), status)
    console.print(table)


def cmd_markets(args: argparse.Namespace) -> None:
    data = _get("/api/v1/info/markets")
    markets = data if isinstance(data, list) else data.get("markets", [])
    markets = [m for m in markets if m.get("status") == "ACTIVE" and m.get("active")]

    if not markets:
        console.print("[red]No markets data[/red]")
        return

    table = Table(title=f"Extended Markets — top 30 by volume ({len(markets)} active)")
    table.add_column("Market", style="cyan")
    table.add_column("Category", style="dim")
    table.add_column("Mark $", justify="right")
    table.add_column("24h %", justify="right")
    table.add_column("Vol 24h", justify="right", style="dim")

    def _vol(m):
        try: return float(m.get("marketStats", {}).get("dailyVolume", 0) or 0)
        except: return 0

    for m in sorted(markets, key=_vol, reverse=True)[:30]:
        name   = m.get("name", "?")
        cat    = m.get("subCategory", m.get("category", ""))
        s      = m.get("marketStats", {})
        mark   = s.get("markPrice", "?")
        chg    = s.get("dailyPriceChangePercentage")
        vol    = s.get("dailyVolume", "?")

        try: mark_str = f"${float(mark):,.4f}"
        except: mark_str = str(mark)

        try:
            chg_f = float(chg) * 100
            cc = "green" if chg_f >= 0 else "red"
            chg_str = f"[{cc}]{chg_f:+.2f}%[/{cc}]"
        except: chg_str = "—"

        try: vol_str = f"${float(vol)/1e6:.2f}M"
        except: vol_str = str(vol)

        table.add_row(name, cat, mark_str, chg_str, vol_str)
    console.print(table)


def cmd_quote(args: argparse.Namespace) -> None:
    data = _get("/api/v1/markets")
    markets = data if isinstance(data, list) else data.get("markets", [])
    symbol = args.symbol.upper()

    match = next((m for m in markets if m.get("market","").upper() == symbol or
                  m.get("symbol","").upper() == symbol), None)
    if not match:
        console.print(f"[red]Market '{symbol}' not found[/red]")
        return

    console.print(f"\n[bold cyan]{symbol}[/bold cyan]")
    for k in ["markPrice", "indexPrice", "lastPrice", "priceChange24h",
              "volume24h", "openInterest", "fundingRate"]:
        v = match.get(k)
        if v is not None:
            console.print(f"  {k}: {v}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Extended Exchange — positions, balance, orders")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("balance",   help="Account balance + equity").set_defaults(func=cmd_balance)
    sub.add_parser("positions", help="Open positions").set_defaults(func=cmd_positions)
    sub.add_parser("orders",    help="Open orders").set_defaults(func=cmd_orders)
    sub.add_parser("markets",   help="All markets + prices (top 30 by volume)").set_defaults(func=cmd_markets)

    q = sub.add_parser("quote", help="Single market quote")
    q.add_argument("symbol", help="e.g. BTC-USD-PERP")
    q.set_defaults(func=cmd_quote)

    args = p.parse_args()
    try:
        args.func(args)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}: {e.response.text[:300]}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise


if __name__ == "__main__":
    main()
