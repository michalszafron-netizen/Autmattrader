"""Position sizing calculator for Hyperliquid.

Two modes:
  1. notional  — you specify how much $ the position is worth
  2. risk      — you specify how much $ you're willing to LOSE if SL hits (professional)

Usage:
  python scripts/position_calc.py notional SILVER long 10 --lev 20
  python scripts/position_calc.py risk SILVER long --risk-pct 2 --sl-pct 2 --lev 5
  python scripts/position_calc.py risk BTC long --risk-usd 5 --sl-pct 1.5 --lev 10
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
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
os.environ.setdefault("REQUESTS_CA_BUNDLE", str(Path.home() / ".claude" / "windows-ca-bundle.pem"))
os.environ.setdefault("SSL_CERT_FILE", os.environ["REQUESTS_CA_BUNDLE"])

HL_API = "https://api.hyperliquid.xyz"
XYZ_DEX = "xyz"
console = Console()


# ── Price fetch ───────────────────────────────────────────────────────────────

ACCOUNT_SIZE = 49.80  # fallback when live fetch fails
_hl_mode = os.getenv("HL_TRADING_MODE") or os.getenv("TRADING_MODE", "paper")


def get_price(coin: str) -> float:
    """Get current mid price for any HL or xyz asset."""
    with httpx.Client(verify=_SSL_CTX, timeout=15) as c:
        # Try xyz first if prefix present or if std fails
        if coin.startswith("xyz:"):
            r = c.post(f"{HL_API}/info", json={"type": "allMids", "dex": XYZ_DEX})
            mid = r.json().get(coin)
            if mid:
                return float(mid)
        # Try resolving short name to xyz
        xyz_name = f"xyz:{coin.upper()}"
        r_xyz = c.post(f"{HL_API}/info", json={"type": "allMids", "dex": XYZ_DEX})
        mid_xyz = r_xyz.json().get(xyz_name)
        if mid_xyz:
            return float(mid_xyz)
        # Standard perp
        r_std = c.post(f"{HL_API}/info", json={"type": "allMids"})
        mid_std = r_std.json().get(coin.upper())
        if mid_std:
            return float(mid_std)
    raise ValueError(f"Cannot find price for {coin!r}")


def get_account_size() -> float:
    """Get live account size from HL."""
    wallet = os.getenv("HL_MAIN_WALLET_ADDRESS", "")
    if not wallet:
        return ACCOUNT_SIZE
    try:
        os.environ.setdefault("REQUESTS_CA_BUNDLE", str(Path.home() / ".claude" / "windows-ca-bundle.pem"))
        os.environ.setdefault("SSL_CERT_FILE", os.environ["REQUESTS_CA_BUNDLE"])
        with httpx.Client(verify=_SSL_CTX, timeout=10) as c:
            state = c.post(f"{HL_API}/info",
                json={"type": "clearinghouseState", "user": wallet}).json()
            spot = c.post(f"{HL_API}/info",
                json={"type": "spotClearinghouseState", "user": wallet}).json()
        perp_val = float(state.get("marginSummary", {}).get("accountValue") or 0)
        spot_usdc = next(
            (float(b["total"]) for b in spot.get("balances", []) if b["coin"] == "USDC"), 0
        )
        return perp_val + spot_usdc if (perp_val + spot_usdc) > 0 else ACCOUNT_SIZE
    except Exception:
        return ACCOUNT_SIZE


# ── Calculations ──────────────────────────────────────────────────────────────

def calc_from_notional(
    coin: str,
    is_long: bool,
    notional_usd: float,
    entry_price: float,
    leverage: int,
    sl_pct: float = 2.0,
    tp_rr: float = 2.0,
    account_size: float = ACCOUNT_SIZE,
) -> dict:
    sz = notional_usd / entry_price
    margin = notional_usd / leverage
    sl_price = entry_price * (1 - sl_pct / 100) if is_long else entry_price * (1 + sl_pct / 100)
    tp_price = entry_price * (1 + sl_pct / 100 * tp_rr) if is_long else entry_price * (1 - sl_pct / 100 * tp_rr)
    loss_at_sl = abs(sz * (entry_price - sl_price))
    gain_at_tp = abs(sz * (tp_price - entry_price))
    risk_pct = loss_at_sl / account_size * 100

    return {
        "coin": coin,
        "side": "LONG" if is_long else "SHORT",
        "entry": entry_price,
        "size": sz,
        "notional": notional_usd,
        "leverage": leverage,
        "margin": margin,
        "margin_pct_account": margin / account_size * 100,
        "sl_price": sl_price,
        "sl_pct": sl_pct,
        "tp_price": tp_price,
        "tp_rr": tp_rr,
        "loss_at_sl": loss_at_sl,
        "gain_at_tp": gain_at_tp,
        "risk_pct_account": risk_pct,
        "account_size": account_size,
    }


def calc_from_risk(
    coin: str,
    is_long: bool,
    risk_usd: float,
    entry_price: float,
    leverage: int,
    sl_pct: float = 2.0,
    tp_rr: float = 2.0,
    account_size: float = ACCOUNT_SIZE,
) -> dict:
    sl_price = entry_price * (1 - sl_pct / 100) if is_long else entry_price * (1 + sl_pct / 100)
    sl_move = abs(entry_price - sl_price)
    sz = risk_usd / sl_move
    notional = sz * entry_price
    return calc_from_notional(coin, is_long, notional, entry_price, leverage, sl_pct, tp_rr, account_size)


# ── Display ───────────────────────────────────────────────────────────────────

def display(r: dict) -> None:
    side_color = "green" if r["side"] == "LONG" else "red"
    risk_color = "green" if r["risk_pct_account"] <= 2 else "yellow" if r["risk_pct_account"] <= 5 else "red"
    margin_warn = " [red]WARNING: >50% of account![/red]" if r["margin_pct_account"] > 50 else ""

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="dim", width=22)
    table.add_column("Value")

    table.add_row("Asset", f"[cyan]{r['coin']}[/cyan]  [{side_color}]{r['side']}[/{side_color}]  {r['leverage']}x")
    table.add_row("Account size", f"${r['account_size']:,.2f}")
    table.add_row("-" * 20, "-" * 20)
    table.add_row("Entry price", f"${r['entry']:,.4f}")
    table.add_row("Size", f"{r['size']:,.4f} units")
    table.add_row("Notional (position $)", f"[bold]${r['notional']:,.2f}[/bold]  ({r['notional']/r['account_size']*100:.0f}% of account)")
    table.add_row("Margin used", f"[bold]${r['margin']:,.2f}[/bold]{margin_warn}")
    table.add_row("-" * 20, "-" * 20)
    table.add_row("Stop Loss", f"[red]${r['sl_price']:,.4f}[/red]  (-{r['sl_pct']:.1f}% from entry)")
    table.add_row("Loss if SL hit", f"[{risk_color}]-${r['loss_at_sl']:,.2f}  ({r['risk_pct_account']:.1f}% of account)[/{risk_color}]")
    table.add_row("Take Profit", f"[green]${r['tp_price']:,.4f}[/green]  (+{r['sl_pct']*r['tp_rr']:.1f}% from entry)")
    table.add_row("Gain if TP hit", f"[green]+${r['gain_at_tp']:,.2f}[/green]")
    table.add_row("R:R ratio", f"1:{r['tp_rr']:.1f}")

    # Risk assessment
    if r["risk_pct_account"] <= 1:
        assessment = "[green]Conservative (< 1% risk)[/green]"
    elif r["risk_pct_account"] <= 2:
        assessment = "[green]Professional (1-2% risk)[/green]"
    elif r["risk_pct_account"] <= 5:
        assessment = "[yellow]Aggressive (2-5% risk)[/yellow]"
    else:
        assessment = "[red]Dangerous (> 5% risk)[/red]"
    table.add_row("Risk assessment", assessment)

    console.print()
    console.print(Panel(table, title=f"[bold]Position Calculator[/bold]", expand=False))

    # Order command to copy-paste
    sz_rounded = round(r["size"], 2)
    console.print(
        f"\n[dim]Order command (paper/live):[/dim]\n"
        f"[cyan]python scripts/hl_executor.py order {r['coin']} "
        f"{'long' if r['side'] == 'LONG' else 'short'} {sz_rounded} {r['entry']:.4f}[/cyan]"
    )


# ── Multi-leverage comparison ─────────────────────────────────────────────────

def display_comparison(
    coin: str, is_long: bool, notional: float, entry: float,
    sl_pct: float, account_size: float
) -> None:
    levers = [2, 3, 5, 10, 20, 25]
    console.print(f"\n[bold]{coin} {notional:.0f}$ position — leverage comparison[/bold]\n")
    table = Table()
    table.add_column("Leverage", style="cyan", justify="center")
    table.add_column("Margin used $", justify="right")
    table.add_column("% of account", justify="right")
    table.add_column("Loss if SL (-{:.0f}%) $".format(sl_pct), justify="right")
    table.add_column("Risk % account", justify="right")

    for lev in levers:
        r = calc_from_notional(coin, is_long, notional, entry, lev, sl_pct=sl_pct, account_size=account_size)
        risk_color = "green" if r["risk_pct_account"] <= 2 else "yellow" if r["risk_pct_account"] <= 5 else "red"
        table.add_row(
            f"{lev}x",
            f"${r['margin']:,.2f}",
            f"{r['margin_pct_account']:.1f}%",
            f"-${r['loss_at_sl']:,.2f}",
            f"[{risk_color}]{r['risk_pct_account']:.1f}%[/{risk_color}]",
        )
    console.print(table)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Position sizing calculator")
    sub = p.add_subparsers(dest="mode", required=True)

    # notional mode
    n = sub.add_parser("notional", help="Size from desired $ position value")
    n.add_argument("coin")
    n.add_argument("side", choices=["long", "short"])
    n.add_argument("notional", type=float, help="Position value in USD (e.g. 10)")
    n.add_argument("--lev", type=int, default=5, dest="leverage", help="Leverage (default 5)")
    n.add_argument("--sl-pct", type=float, default=2.0, help="SL distance %% from entry (default 2)")
    n.add_argument("--tp-rr", type=float, default=2.0, help="Take profit R:R ratio (default 2)")
    n.add_argument("--entry", type=float, default=0, help="Entry price (default: live market)")
    n.add_argument("--compare", action="store_true", help="Show leverage comparison table")

    # risk mode
    r = sub.add_parser("risk", help="Size from how much you're willing to LOSE")
    r.add_argument("coin")
    r.add_argument("side", choices=["long", "short"])
    rg = r.add_mutually_exclusive_group(required=True)
    rg.add_argument("--risk-pct", type=float, help="Risk as %% of account (e.g. 2 = 2%%)")
    rg.add_argument("--risk-usd", type=float, help="Risk in USD (e.g. 1.50)")
    r.add_argument("--sl-pct", type=float, default=2.0, help="SL distance %% from entry (default 2)")
    r.add_argument("--tp-rr", type=float, default=2.0, help="Take profit R:R ratio (default 2)")
    r.add_argument("--lev", type=int, default=5, dest="leverage")
    r.add_argument("--entry", type=float, default=0)
    r.add_argument("--compare", action="store_true")

    args = p.parse_args()
    is_long = args.side == "long"

    console.print("Fetching live data…", end=" ")
    account_size = get_account_size()
    entry = args.entry if args.entry > 0 else get_price(args.coin)
    console.print(f"[green]OK[/green]  |  Account: ${account_size:,.2f}  |  {args.coin}: ${entry:,.4f}")

    if args.mode == "notional":
        result = calc_from_notional(
            args.coin, is_long, args.notional, entry, args.leverage,
            sl_pct=args.sl_pct, tp_rr=args.tp_rr, account_size=account_size
        )
        if args.compare:
            display_comparison(args.coin, is_long, args.notional, entry, args.sl_pct, account_size)
        display(result)

    else:  # risk mode
        risk_usd = args.risk_usd if args.risk_usd else (args.risk_pct / 100 * account_size)
        result = calc_from_risk(
            args.coin, is_long, risk_usd, entry, args.leverage,
            sl_pct=args.sl_pct, tp_rr=args.tp_rr, account_size=account_size
        )
        if args.compare:
            display_comparison(args.coin, is_long, result["notional"], entry, args.sl_pct, account_size)
        display(result)


if __name__ == "__main__":
    main()
