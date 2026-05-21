"""Hyperliquid whale tracker — read-only, no API keys required.

Uses two public endpoints:
  - https://stats-data.hyperliquid.xyz/Mainnet/leaderboard  (top traders, used by HL UI)
  - https://api.hyperliquid.xyz/info                        (per-wallet state)

Subcommands:
  leaderboard [--top N] [--by pnl|roi] [--window day|week|month|allTime]
  positions WALLET
  whales [--top N] [--window ...]   # leaderboard + aggregate net exposure
"""

from __future__ import annotations

import argparse
import ssl
import sys
from collections import defaultdict
from decimal import Decimal

import httpx
import truststore
from rich.console import Console
from rich.table import Table

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"

# Use Windows system trust store instead of stale bundled CAs
_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_CLIENT = httpx.Client(verify=_SSL_CTX, timeout=30.0)

console = Console()


def fetch_leaderboard() -> list[dict]:
    r = _CLIENT.get(LEADERBOARD_URL)
    r.raise_for_status()
    data = r.json()
    return data.get("leaderboardRows", [])


def fetch_clearinghouse_state(wallet: str) -> dict:
    r = _CLIENT.post(
        INFO_URL,
        json={"type": "clearinghouseState", "user": wallet},
    )
    r.raise_for_status()
    return r.json()


def fetch_all_mids() -> dict[str, str]:
    r = _CLIENT.post(INFO_URL, json={"type": "allMids"})
    r.raise_for_status()
    return r.json()


def perf_for_window(row: dict, window: str) -> dict:
    for w, perf in row.get("windowPerformances", []):
        if w == window:
            return perf
    return {}


def cmd_leaderboard(args: argparse.Namespace) -> None:
    rows = fetch_leaderboard()
    sort_key = args.by
    window = args.window

    def sort_value(row: dict) -> Decimal:
        perf = perf_for_window(row, window)
        try:
            return Decimal(perf.get(sort_key, "0"))
        except Exception:
            return Decimal("0")

    rows_sorted = sorted(rows, key=sort_value, reverse=True)[: args.top]

    table = Table(title=f"Hyperliquid Leaderboard — top {args.top} by {sort_key} ({window})")
    table.add_column("#", style="dim", width=3)
    table.add_column("Wallet", style="cyan")
    table.add_column("Display", style="magenta")
    table.add_column("Account $", justify="right", style="green")
    table.add_column(f"PnL {window}", justify="right")
    table.add_column(f"ROI {window}", justify="right")
    table.add_column("Vol", justify="right", style="dim")

    for i, row in enumerate(rows_sorted, 1):
        perf = perf_for_window(row, window)
        pnl = Decimal(perf.get("pnl", "0"))
        roi = Decimal(perf.get("roi", "0")) * 100
        vlm = Decimal(perf.get("vlm", "0"))
        av = Decimal(row.get("accountValue", "0"))
        pnl_style = "green" if pnl >= 0 else "red"
        table.add_row(
            str(i),
            row.get("ethAddress", "")[:10] + "…" + row.get("ethAddress", "")[-4:],
            (row.get("displayName") or "-")[:18],
            f"${av:,.0f}",
            f"[{pnl_style}]${pnl:,.0f}[/{pnl_style}]",
            f"[{pnl_style}]{roi:+.1f}%[/{pnl_style}]",
            f"${vlm:,.0f}",
        )
    console.print(table)


def cmd_positions(args: argparse.Namespace) -> None:
    state = fetch_clearinghouse_state(args.wallet)
    asset_positions = state.get("assetPositions", [])
    margin = state.get("marginSummary", {})

    console.print(f"\n[bold]Wallet:[/bold] [cyan]{args.wallet}[/cyan]")
    console.print(
        f"[bold]Account value:[/bold] ${Decimal(margin.get('accountValue', '0')):,.2f}  "
        f"[bold]Margin used:[/bold] ${Decimal(margin.get('totalMarginUsed', '0')):,.2f}\n"
    )

    if not asset_positions:
        console.print("[dim]No open positions.[/dim]")
        return

    table = Table(title="Open positions")
    table.add_column("Coin", style="cyan")
    table.add_column("Side")
    table.add_column("Size", justify="right")
    table.add_column("Entry $", justify="right")
    table.add_column("Mark/Pos $", justify="right")
    table.add_column("Unrealized PnL", justify="right")
    table.add_column("Lev", justify="right", style="dim")

    for p in asset_positions:
        pos = p.get("position", {})
        coin = pos.get("coin", "?")
        szi = Decimal(pos.get("szi", "0"))
        side = "LONG" if szi > 0 else "SHORT"
        side_style = "green" if szi > 0 else "red"
        entry = Decimal(pos.get("entryPx", "0"))
        upnl = Decimal(pos.get("unrealizedPnl", "0"))
        upnl_style = "green" if upnl >= 0 else "red"
        lev = pos.get("leverage", {}).get("value", "?")
        position_value = Decimal(pos.get("positionValue", "0"))
        table.add_row(
            coin,
            f"[{side_style}]{side}[/{side_style}]",
            f"{abs(szi):,.4f}",
            f"${entry:,.4f}",
            f"${position_value:,.2f}",
            f"[{upnl_style}]${upnl:+,.2f}[/{upnl_style}]",
            f"{lev}x",
        )
    console.print(table)


def cmd_whales(args: argparse.Namespace) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    rows = fetch_leaderboard()

    def sort_value(row: dict) -> Decimal:
        perf = perf_for_window(row, args.window)
        try:
            return Decimal(perf.get("pnl", "0"))
        except Exception:
            return Decimal("0")

    top = sorted(rows, key=sort_value, reverse=True)[: args.top]
    wallets = [r.get("ethAddress", "") for r in top if r.get("ethAddress")]

    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent))
        from tz_utils import fmt_both
        from datetime import datetime as _dt, timezone as _tz
        _ts = fmt_both(_dt.now(_tz.utc))
    except Exception:
        from datetime import datetime as _dt
        _ts = _dt.now().strftime("%Y-%m-%d %H:%M")
    console.print(
        f"\n[bold]Aggregating positions across top {args.top} HL traders "
        f"(by {args.window} pnl)…[/bold] fetching {len(wallets)} wallets in parallel\n"
        f"[dim]{_ts}[/dim]\n"
    )

    # Parallel fetch — up to 10 concurrent requests
    states: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_to_wallet = {pool.submit(fetch_clearinghouse_state, w): w for w in wallets}
        for future in as_completed(future_to_wallet):
            wallet = future_to_wallet[future]
            try:
                states[wallet] = future.result()
            except Exception as e:
                console.print(f"[red]Failed {wallet[:10]}…: {e}[/red]")

    # coin -> {"long": Decimal, "short": Decimal, "long_wallets": int, "short_wallets": int}
    agg: dict[str, dict] = defaultdict(
        lambda: {"long": Decimal("0"), "short": Decimal("0"), "long_w": 0, "short_w": 0}
    )

    fetched = len(states)
    for state in states.values():
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            coin = pos.get("coin", "?")
            szi = Decimal(pos.get("szi", "0"))
            val = Decimal(pos.get("positionValue", "0"))
            if szi > 0:
                agg[coin]["long"] += val
                agg[coin]["long_w"] += 1
            elif szi < 0:
                agg[coin]["short"] += val
                agg[coin]["short_w"] += 1

    if not agg:
        console.print("[dim]No positions found across sampled wallets.[/dim]")
        return

    rows_sorted = sorted(
        agg.items(),
        key=lambda kv: kv[1]["long"] + kv[1]["short"],
        reverse=True,
    )

    table = Table(title=f"Whale aggregate exposure ({fetched} wallets sampled)")
    table.add_column("Coin", style="cyan")
    table.add_column("Long $", justify="right", style="green")
    table.add_column("Short $", justify="right", style="red")
    table.add_column("Net $", justify="right")
    table.add_column("Long wallets", justify="right", style="dim")
    table.add_column("Short wallets", justify="right", style="dim")
    table.add_column("Bias", justify="center")

    for coin, d in rows_sorted[:25]:
        net = d["long"] - d["short"]
        net_style = "green" if net > 0 else "red"
        total = d["long"] + d["short"]
        bias = "LONG" if net > 0 else "SHORT"
        if total > 0:
            ratio = abs(net) / total * 100
        else:
            ratio = Decimal("0")
        table.add_row(
            coin,
            f"${d['long']:,.0f}",
            f"${d['short']:,.0f}",
            f"[{net_style}]${net:+,.0f}[/{net_style}]",
            str(d["long_w"]),
            str(d["short_w"]),
            f"[{net_style}]{bias} {ratio:.0f}%[/{net_style}]",
        )
    console.print(table)


def main() -> None:
    p = argparse.ArgumentParser(description="Hyperliquid whale tracker (read-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    lb = sub.add_parser("leaderboard", help="Show top traders")
    lb.add_argument("--top", type=int, default=20)
    lb.add_argument("--by", choices=["pnl", "roi", "vlm"], default="pnl")
    lb.add_argument(
        "--window", choices=["day", "week", "month", "allTime"], default="day"
    )
    lb.set_defaults(func=cmd_leaderboard)

    ps = sub.add_parser("positions", help="Show positions for one wallet")
    ps.add_argument("wallet", help="0x... wallet address")
    ps.set_defaults(func=cmd_positions)

    wh = sub.add_parser("whales", help="Aggregate net exposure across top traders")
    wh.add_argument("--top", type=int, default=20)
    wh.add_argument(
        "--window", choices=["day", "week", "month", "allTime"], default="week"
    )
    wh.set_defaults(func=cmd_whales)

    args = p.parse_args()
    try:
        args.func(args)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}: {e.response.text[:200]}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
