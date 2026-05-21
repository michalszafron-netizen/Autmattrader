"""Alpaca paper trading executor — US stocks via REST API.

Usage:
    python scripts/alpaca_executor.py quote MKSI
    python scripts/alpaca_executor.py order MKSI long 5 150.00    # limit order
    python scripts/alpaca_executor.py market MKSI long 5          # market order
    python scripts/alpaca_executor.py close MKSI                  # close all
    python scripts/alpaca_executor.py positions
    python scripts/alpaca_executor.py orders
    python scripts/alpaca_executor.py cancel ORDER_ID
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY    = os.getenv("ALPACA_API_KEY", "")
API_SECRET = os.getenv("ALPACA_API_SECRET", "")
IS_PAPER   = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE_URL   = "https://paper-api.alpaca.markets" if IS_PAPER else "https://api.alpaca.markets"
MODE       = "PAPER" if IS_PAPER else "LIVE"

console = Console()
_SSL    = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

HEADERS = {
    "APCA-API-KEY-ID":     API_KEY,
    "APCA-API-SECRET-KEY": API_SECRET,
    "Content-Type":        "application/json",
}


def client() -> httpx.Client:
    return httpx.Client(verify=_SSL, timeout=20, headers=HEADERS)


def get_account() -> dict:
    with client() as c:
        r = c.get(f"{BASE_URL}/v2/account")
    r.raise_for_status()
    return r.json()


def get_quote(symbol: str) -> dict:
    with client() as c:
        r = c.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest",
                  headers=HEADERS)
    if r.status_code == 200:
        return r.json().get("quote", {})
    # fallback: last trade
    with client() as c:
        r2 = c.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
                   headers=HEADERS)
    return r2.json().get("trade", {}) if r2.status_code == 200 else {}


def get_positions() -> list[dict]:
    with client() as c:
        r = c.get(f"{BASE_URL}/v2/positions")
    r.raise_for_status()
    return r.json()


def get_position(symbol: str) -> dict | None:
    with client() as c:
        r = c.get(f"{BASE_URL}/v2/positions/{symbol}")
    if r.status_code == 200:
        return r.json()
    return None


def get_orders() -> list[dict]:
    with client() as c:
        r = c.get(f"{BASE_URL}/v2/orders?status=open&limit=20")
    r.raise_for_status()
    return r.json()


def place_order(symbol: str, side: str, qty: float, price: float | None = None) -> dict:
    order_type = "limit" if price else "market"
    payload: dict = {
        "symbol":        symbol.upper(),
        "qty":           str(qty),
        "side":          side,      # "buy" or "sell"
        "type":          order_type,
        "time_in_force": "day",
    }
    if price:
        payload["limit_price"] = str(round(price, 2))

    with client() as c:
        r = c.post(f"{BASE_URL}/v2/orders", json=payload)
    r.raise_for_status()
    return r.json()


def close_position(symbol: str) -> dict:
    with client() as c:
        r = c.delete(f"{BASE_URL}/v2/positions/{symbol}")
    if r.status_code == 200:
        return r.json()
    return {"error": r.text}


def cancel_order(order_id: str) -> bool:
    with client() as c:
        r = c.delete(f"{BASE_URL}/v2/orders/{order_id}")
    return r.status_code == 204


# ── Display ───────────────────────────────────────────────────────────────────

def show_positions() -> None:
    acct       = get_account()
    equity     = float(acct.get("equity", 0))
    cash       = float(acct.get("cash", 0))
    buying_pwr = float(acct.get("buying_power", 0))
    day_pnl    = equity - float(acct.get("last_equity", equity))
    pnl_color  = "green" if day_pnl >= 0 else "red"
    console.print(
        f"\n[bold]Alpaca {MODE}[/bold] | Equity: [cyan]${equity:,.2f}[/cyan] | "
        f"Cash: ${cash:,.2f} | Buying Power: ${buying_pwr:,.2f} | "
        f"Day P&L: [{pnl_color}]${day_pnl:+,.2f}[/{pnl_color}]\n"
    )

    positions = get_positions()
    if not positions:
        console.print("[dim]Alpaca: brak otwartych pozycji[/dim]")
        return

    table = Table(title="Open Positions")
    table.add_column("Symbol", style="cyan")
    table.add_column("Side")
    table.add_column("Qty", justify="right")
    table.add_column("Avg Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("uPnL", justify="right")
    table.add_column("uPnL %", justify="right")

    for p in positions:
        upnl  = float(p.get("unrealized_pl", 0))
        upct  = float(p.get("unrealized_plpc", 0)) * 100
        color = "green" if upnl >= 0 else "red"
        side  = p.get("side", "long")
        table.add_row(
            p["symbol"],
            side.upper(),
            p.get("qty", "0"),
            f"${float(p.get('avg_entry_price',0)):.2f}",
            f"${float(p.get('current_price',0)):.2f}",
            f"[{color}]${upnl:+.2f}[/{color}]",
            f"[{color}]{upct:+.2f}%[/{color}]",
        )
    console.print(table)


def show_orders() -> None:
    orders = get_orders()
    if not orders:
        console.print("[dim]No open orders[/dim]")
        return
    table = Table(title="Open Orders")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Symbol", style="cyan")
    table.add_column("Side")
    table.add_column("Qty", justify="right")
    table.add_column("Type")
    table.add_column("Limit", justify="right")
    table.add_column("Status")
    for o in orders:
        table.add_row(
            o["id"][:8],
            o["symbol"],
            o["side"].upper(),
            o.get("qty", ""),
            o.get("type", ""),
            f"${float(o['limit_price']):.2f}" if o.get("limit_price") else "MKT",
            o.get("status", ""),
        )
    console.print(table)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not API_KEY:
        console.print("[red]ALPACA_API_KEY not set in .env[/red]")
        sys.exit(1)

    p = argparse.ArgumentParser(description="Alpaca paper trading executor")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("positions")
    sub.add_parser("orders")

    q = sub.add_parser("quote")
    q.add_argument("symbol")

    o = sub.add_parser("order")
    o.add_argument("symbol")
    o.add_argument("side", choices=["long", "short", "buy", "sell"])
    o.add_argument("qty",   type=float)
    o.add_argument("price", type=float)

    m = sub.add_parser("market")
    m.add_argument("symbol")
    m.add_argument("side", choices=["long", "short", "buy", "sell"])
    m.add_argument("qty", type=float)

    cl = sub.add_parser("close")
    cl.add_argument("symbol")

    cn = sub.add_parser("cancel")
    cn.add_argument("order_id")

    args = p.parse_args()

    if args.cmd == "positions":
        show_positions()

    elif args.cmd == "orders":
        show_orders()

    elif args.cmd == "quote":
        q = get_quote(args.symbol.upper())
        price = q.get("ap") or q.get("p") or "N/A"
        console.print(f"[cyan]{args.symbol.upper()}[/cyan] last: [bold]${price}[/bold]")

    elif args.cmd in ("order", "market"):
        side = "buy" if args.side in ("long", "buy") else "sell"
        price = getattr(args, "price", None)
        result = place_order(args.symbol.upper(), side, args.qty, price)
        oid = result.get("id", "?")[:12]
        status = result.get("status", "?")
        lp = result.get("limit_price", "")
        console.print(f"[green]Order placed[/green] [{MODE}] | {args.symbol.upper()} {side.upper()} {args.qty} "
                      f"{'@ $'+str(lp) if lp else 'MARKET'} | status={status} | OID={oid}")
        print(f"Order placed — OID: {result.get('id','')}")

    elif args.cmd == "close":
        pos = get_position(args.symbol.upper())
        if not pos:
            console.print(f"[yellow]No open position for {args.symbol.upper()}[/yellow]")
            return
        qty  = pos.get("qty", "?")
        side = pos.get("side", "?")
        result = close_position(args.symbol.upper())
        console.print(f"[green]Position closed[/green] | {args.symbol.upper()} {side} {qty} | {result.get('status','done')}")
        print(f"Position closed — {args.symbol.upper()} {qty} {side}")

    elif args.cmd == "cancel":
        ok = cancel_order(args.order_id)
        console.print("[green]Cancelled[/green]" if ok else "[red]Failed to cancel[/red]")

    else:
        p.print_help()


if __name__ == "__main__":
    main()
