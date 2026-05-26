"""Hyperliquid whale tracker — read-only, no API keys required.

Uses two public endpoints:
  - https://stats-data.hyperliquid.xyz/Mainnet/leaderboard  (top traders, used by HL UI)
  - https://api.hyperliquid.xyz/info                        (per-wallet state)

Subcommands:
  leaderboard [--top N] [--by pnl|roi] [--window day|week|month|allTime]
  positions WALLET
  whales [--top N] [--window ...] [--coin SYMBOL]   # aggregate; --coin for single-token deep dive
  snapshot save [--top N] [--window ...]             # save JSON snapshot for morning diff
  snapshot diff                                       # compare two most recent snapshots
"""

from __future__ import annotations

import argparse
import datetime
import json
import ssl
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path

import httpx
import truststore
from rich.console import Console
from rich.table import Table

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"
SNAPSHOT_DIR = Path(__file__).parent.parent / "reports" / "whale_snapshots"

# Use Windows system trust store instead of stale bundled CAs
_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_CLIENT = httpx.Client(verify=_SSL_CTX, timeout=30.0)

console = Console()


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

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


def _fetch_top_states(
    top_n: int, window: str
) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    """Shared helper: fetch leaderboard top N + their clearinghouse states in parallel.

    Returns: (top_rows, states_by_wallet, leaderboard_by_wallet)
    """
    rows = fetch_leaderboard()

    def sort_value(row: dict) -> Decimal:
        perf = perf_for_window(row, window)
        try:
            return Decimal(perf.get("pnl", "0"))
        except Exception:
            return Decimal("0")

    top = sorted(rows, key=sort_value, reverse=True)[:top_n]
    wallets = [r.get("ethAddress", "") for r in top if r.get("ethAddress")]
    leaderboard_by_wallet = {r.get("ethAddress", ""): r for r in top}

    states: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_to_wallet = {pool.submit(fetch_clearinghouse_state, w): w for w in wallets}
        for future in as_completed(future_to_wallet):
            wallet = future_to_wallet[future]
            try:
                states[wallet] = future.result()
            except Exception as e:
                console.print(f"[red]Failed {wallet[:10]}...: {e}[/red]")

    return top, states, leaderboard_by_wallet


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

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
        addr = row.get("ethAddress", "")
        table.add_row(
            str(i),
            addr[:10] + "..." + addr[-4:],
            (row.get("displayName") or "-")[:18],
            f"${av:,.0f}",
            f"[{pnl_style}]${pnl:,.0f}[/{pnl_style}]",
            f"[{pnl_style}]{roi:+.1f}%[/{pnl_style}]",
            f"${vlm:,.0f}",
        )
    console.print(table)


def fetch_prices(coins: list[str] | None = None) -> dict[str, Decimal]:
    """Fetch current HL mark prices via allMids. Optionally filter by coin list."""
    mids = fetch_all_mids()
    result = {}
    for coin, price_str in mids.items():
        if coins is None or coin.upper() in [c.upper() for c in coins]:
            try:
                result[coin] = Decimal(str(price_str))
            except Exception:
                pass
    return result


def cmd_prices(args: argparse.Namespace) -> None:
    """Show current HL mark prices from allMids endpoint — the canonical price source."""
    coins = [c.upper() for c in args.coins] if args.coins else None
    mids = fetch_all_mids()

    items = sorted(mids.items())
    if coins:
        items = [(k, v) for k, v in items if k.upper() in coins]

    if not items:
        console.print("[yellow]No matching coins found.[/yellow]")
        return

    table = Table(title="HL Current Mark Prices (allMids) — live, exchange-native")
    table.add_column("Coin", style="cyan")
    table.add_column("Mark Price $", justify="right", style="bold green")

    for coin, price_str in items:
        try:
            price = Decimal(str(price_str))
            table.add_row(coin, f"${price:,.6f}")
        except Exception:
            table.add_row(coin, str(price_str))

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

    # Fetch live mark prices once for all coins in this wallet
    coins_in_wallet = [
        p.get("position", {}).get("coin", "") for p in asset_positions
    ]
    live_prices = fetch_prices(coins_in_wallet)

    table = Table(title="Open positions")
    table.add_column("Coin", style="cyan")
    table.add_column("Side")
    table.add_column("Size", justify="right")
    table.add_column("Entry $", justify="right", style="dim")
    table.add_column("Mark $ (live)", justify="right", style="bold green")
    table.add_column("Entry vs Mark", justify="right")
    table.add_column("Pos Value $", justify="right")
    table.add_column("uPnL", justify="right")
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

        # Live mark price from allMids (canonical source)
        mark = live_prices.get(coin)
        mark_str = f"${mark:,.4f}" if mark else "[dim]N/A[/dim]"

        # Entry vs mark delta (shows how far from entry we are)
        if mark and entry > 0:
            delta_pct = (mark - entry) / entry * 100
            delta_style = "green" if delta_pct > 0 else "red"
            delta_str = f"[{delta_style}]{delta_pct:+.2f}%[/{delta_style}]"
        else:
            delta_str = "[dim]—[/dim]"

        table.add_row(
            coin,
            f"[{side_style}]{side}[/{side_style}]",
            f"{abs(szi):,.4f}",
            f"${entry:,.4f}",
            mark_str,
            delta_str,
            f"${position_value:,.2f}",
            f"[{upnl_style}]${upnl:+,.2f}[/{upnl_style}]",
            f"{lev}x",
        )
    console.print(table)


def cmd_whales(args: argparse.Namespace) -> None:
    coin_filter = args.coin.upper() if args.coin else None

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

    title_desc = f"top {args.top} HL traders (by {args.window} pnl)"
    if coin_filter:
        title_desc = f"[cyan]{coin_filter}[/cyan] deep dive — {title_desc}"
    console.print(
        f"\n[bold]Aggregating positions: {title_desc}[/bold]\n"
        f"[dim]{_ts}[/dim]\n"
    )

    top, states, leaderboard_by_wallet = _fetch_top_states(args.top, args.window)
    fetched = len(states)

    # coin -> {"long": Decimal, "short": Decimal, "long_w": int, "short_w": int}
    agg: dict[str, dict] = defaultdict(
        lambda: {"long": Decimal("0"), "short": Decimal("0"), "long_w": 0, "short_w": 0}
    )
    coin_wallets: list[dict] = []  # per-wallet detail, populated only when --coin is set

    for wallet, state in states.items():
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            coin = pos.get("coin", "?")
            szi = Decimal(pos.get("szi", "0"))
            val = Decimal(pos.get("positionValue", "0"))

            # Aggregate (apply coin filter when specified)
            if coin_filter is None or coin == coin_filter:
                if szi > 0:
                    agg[coin]["long"] += val
                    agg[coin]["long_w"] += 1
                elif szi < 0:
                    agg[coin]["short"] += val
                    agg[coin]["short_w"] += 1

            # Per-wallet detail for deep dive
            if coin_filter and coin == coin_filter:
                entry = Decimal(pos.get("entryPx", "0"))
                upnl = Decimal(pos.get("unrealizedPnl", "0"))
                lev = pos.get("leverage", {}).get("value", "?")
                liq = pos.get("liquidationPx")
                lb_row = leaderboard_by_wallet.get(wallet, {})
                lb_perf = perf_for_window(lb_row, args.window)
                lb_pnl = Decimal(lb_perf.get("pnl", "0"))
                coin_wallets.append({
                    "wallet": wallet,
                    "name": (lb_row.get("displayName") or "Anon")[:16],
                    "side": "LONG" if szi > 0 else "SHORT",
                    "szi": szi,
                    "val": val,
                    "entry": entry,
                    "upnl": upnl,
                    "lev": lev,
                    "liq": float(liq) if liq else None,
                    "lb_pnl": lb_pnl,
                })

    if not agg:
        msg = (
            f"No positions found for [cyan]{coin_filter}[/cyan] among top {fetched} wallets."
            if coin_filter
            else "No positions found across sampled wallets."
        )
        console.print(f"[dim]{msg}[/dim]")
        return

    rows_sorted = sorted(
        agg.items(),
        key=lambda kv: kv[1]["long"] + kv[1]["short"],
        reverse=True,
    )

    limit = 1 if coin_filter else 25
    table_title = (
        f"{coin_filter} whale exposure ({fetched} wallets sampled)"
        if coin_filter
        else f"Whale aggregate exposure ({fetched} wallets sampled)"
    )

    table = Table(title=table_title)
    table.add_column("Coin", style="cyan")
    table.add_column("Long $", justify="right", style="green")
    table.add_column("Short $", justify="right", style="red")
    table.add_column("Net $", justify="right")
    table.add_column("Long wallets", justify="right", style="dim")
    table.add_column("Short wallets", justify="right", style="dim")
    table.add_column("Bias", justify="center")

    for coin, d in rows_sorted[:limit]:
        net = d["long"] - d["short"]
        net_style = "green" if net > 0 else "red"
        total = d["long"] + d["short"]
        bias = "LONG" if net > 0 else "SHORT"
        ratio = abs(net) / total * 100 if total > 0 else Decimal("0")
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

    # Per-wallet breakdown — only shown for single-coin deep dive
    if coin_filter and coin_wallets:
        coin_wallets.sort(key=lambda x: x["val"], reverse=True)

        # Fetch live mark price for this coin (single API call)
        live_mark = fetch_prices([coin_filter]).get(coin_filter)
        if live_mark:
            console.print(
                f"\n[bold]Live mark price[/bold] ([cyan]{coin_filter}[/cyan]): "
                f"[bold green]${live_mark:,.4f}[/bold green]  "
                f"[dim](source: HL allMids — use this, NOT entry prices, for current analysis)[/dim]\n"
            )

        detail = Table(title=f"{coin_filter} — per-wallet positions ({len(coin_wallets)} traders)")
        detail.add_column("#", style="dim", width=3)
        detail.add_column("Wallet", style="cyan")
        detail.add_column("Name", style="magenta")
        detail.add_column("Side")
        detail.add_column("Size", justify="right")
        detail.add_column("Pos $", justify="right")
        detail.add_column("Entry $ (hist)", justify="right", style="dim")
        detail.add_column("Mark $ (live)", justify="right", style="bold green")
        detail.add_column("uPnL", justify="right")
        detail.add_column("Lev", justify="right", style="dim")
        detail.add_column(f"PnL {args.window}", justify="right", style="dim")

        for i, w in enumerate(coin_wallets, 1):
            side_style = "green" if w["side"] == "LONG" else "red"
            upnl_style = "green" if w["upnl"] >= 0 else "red"
            pnl_style = "green" if w["lb_pnl"] >= 0 else "red"
            addr = w["wallet"]

            # Compute mark price from positionValue / abs(szi)
            abs_szi = abs(w["szi"])
            computed_mark = w["val"] / abs_szi if abs_szi > 0 else None
            mark_str = (
                f"[bold green]${computed_mark:,.4f}[/bold green]"
                if computed_mark
                else "[dim]N/A[/dim]"
            )

            detail.add_row(
                str(i),
                addr[:10] + "..." + addr[-4:],
                w["name"],
                f"[{side_style}]{w['side']}[/{side_style}]",
                f"{abs_szi:,.4f}",
                f"${w['val']:,.0f}",
                f"${w['entry']:,.4f}",
                mark_str,
                f"[{upnl_style}]${w['upnl']:+,.2f}[/{upnl_style}]",
                f"{w['lev']}x",
                f"[{pnl_style}]${w['lb_pnl']:,.0f}[/{pnl_style}]",
            )
        console.print(detail)


# ---------------------------------------------------------------------------
# Snapshot: save / diff  (Morning Alpha Scan)
# ---------------------------------------------------------------------------

def cmd_snapshot_save(args: argparse.Namespace) -> None:
    """Fetch current whale state and persist as a timestamped JSON snapshot."""
    console.print(
        f"\n[bold]Saving whale snapshot[/bold] "
        f"(top {args.top}, window={args.window})\n"
    )

    top, states, leaderboard_by_wallet = _fetch_top_states(args.top, args.window)

    # Coin-level aggregation (plain floats for JSON serialisation)
    coin_agg: dict[str, dict] = defaultdict(
        lambda: {"long": 0.0, "short": 0.0, "long_w": 0, "short_w": 0}
    )
    # Wallet-level positions (only wallets with at least one open position)
    wallet_positions: dict[str, dict] = {}

    for wallet, state in states.items():
        positions = []
        for p in state.get("assetPositions", []):
            pos = p.get("position", {})
            coin = pos.get("coin", "?")
            szi = float(pos.get("szi", "0"))
            val = float(pos.get("positionValue", "0"))
            entry = float(pos.get("entryPx", "0"))
            upnl = float(pos.get("unrealizedPnl", "0"))

            if szi > 0:
                coin_agg[coin]["long"] += val
                coin_agg[coin]["long_w"] += 1
                positions.append({"coin": coin, "side": "LONG", "size": abs(szi),
                                   "val": val, "entry": entry, "upnl": upnl})
            elif szi < 0:
                coin_agg[coin]["short"] += val
                coin_agg[coin]["short_w"] += 1
                positions.append({"coin": coin, "side": "SHORT", "size": abs(szi),
                                   "val": val, "entry": entry, "upnl": upnl})

        if positions:
            lb_row = leaderboard_by_wallet.get(wallet, {})
            perf = perf_for_window(lb_row, args.window)
            wallet_positions[wallet] = {
                "name": lb_row.get("displayName") or "Anonymous",
                "pnl": float(perf.get("pnl", "0")),
                "positions": positions,
            }

    now = datetime.datetime.now(datetime.timezone.utc)
    snapshot = {
        "ts": now.isoformat(),
        "window": args.window,
        "top": args.top,
        "wallets_fetched": len(states),
        "coins": dict(coin_agg),
        "wallets": wallet_positions,
    }

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    filename = SNAPSHOT_DIR / f"whale_{now.strftime('%Y%m%d_%H%M%S')}.json"
    filename.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    console.print(f"[green]Saved:[/green] {filename}")
    console.print(f"  Coins tracked:          {len(coin_agg)}")
    console.print(f"  Wallets with positions: {len(wallet_positions)}")
    console.print(f"  Total wallets fetched:  {len(states)}")


def cmd_snapshot_diff(args: argparse.Namespace) -> None:
    """Compare the two most recent snapshots — Morning Alpha Scan output."""
    if not SNAPSHOT_DIR.exists():
        console.print("[yellow]No snapshot directory found. Run 'snapshot save' first.[/yellow]")
        return

    snapshots = sorted(SNAPSHOT_DIR.glob("whale_*.json"))
    if len(snapshots) < 2:
        console.print(
            f"[yellow]Need at least 2 snapshots (found {len(snapshots)}). "
            "Run 'snapshot save' again later.[/yellow]"
        )
        return

    old_snap = json.loads(snapshots[-2].read_text(encoding="utf-8"))
    new_snap = json.loads(snapshots[-1].read_text(encoding="utf-8"))

    console.print(
        f"\n[bold]Morning Alpha Scan — Snapshot Diff[/bold]\n"
        f"  [dim]Old:[/dim] {old_snap['ts']}  ({snapshots[-2].name})\n"
        f"  [yellow]New:[/yellow] {new_snap['ts']}  ({snapshots[-1].name})\n"
    )

    old_coins: dict = old_snap.get("coins", {})
    new_coins: dict = new_snap.get("coins", {})

    # Per-wallet coin sets — for opening / closing detection
    old_wallet_coins = {
        wallet: {pos["coin"] for pos in data.get("positions", [])}
        for wallet, data in old_snap.get("wallets", {}).items()
    }
    new_wallet_coins = {
        wallet: {pos["coin"] for pos in data.get("positions", [])}
        for wallet, data in new_snap.get("wallets", {}).items()
    }

    new_entries_set = set(new_coins) - set(old_coins)
    dropped_set = set(old_coins) - set(new_coins)
    all_coins = set(old_coins) | set(new_coins)

    changes = []
    for coin in sorted(all_coins):
        old = old_coins.get(coin, {"long": 0.0, "short": 0.0, "long_w": 0, "short_w": 0})
        new = new_coins.get(coin, {"long": 0.0, "short": 0.0, "long_w": 0, "short_w": 0})

        old_net = old["long"] - old["short"]
        new_net = new["long"] - new["short"]
        old_bias = "LONG" if old_net > 0 else ("SHORT" if old_net < 0 else "NEUTRAL")
        new_bias = "LONG" if new_net > 0 else ("SHORT" if new_net < 0 else "NEUTRAL")

        old_total = old["long"] + old["short"]
        new_total = new["long"] + new["short"]
        pct_change = ((new_total - old_total) / old_total * 100) if old_total > 0 else float("inf")

        is_new = coin in new_entries_set
        is_dropped = coin in dropped_set
        bias_flipped = (not is_new) and (not is_dropped) and (old_bias != new_bias)
        big_move = (not is_new) and (not is_dropped) and abs(pct_change) >= 20

        if is_new or is_dropped or bias_flipped or big_move:
            changes.append({
                "coin": coin,
                "old_net": old_net, "new_net": new_net,
                "old_bias": old_bias, "new_bias": new_bias,
                "old_total": old_total, "new_total": new_total,
                "pct_change": pct_change,
                "old_long_w": old["long_w"], "new_long_w": new["long_w"],
                "old_short_w": old["short_w"], "new_short_w": new["short_w"],
                "is_new": is_new, "is_dropped": is_dropped,
                "bias_flipped": bias_flipped, "big_move": big_move,
            })

    # ---- Coin-level change table ----
    if changes:
        # Sort: new entries first, then bias flips, then biggest % moves
        changes.sort(key=lambda x: (not x["is_new"], not x["bias_flipped"], -abs(x["pct_change"])))

        table = Table(title="Coin-level changes")
        table.add_column("Coin", style="cyan")
        table.add_column("Signal", style="bold")
        table.add_column("Bias", justify="center")
        table.add_column("Exposure", justify="right")
        table.add_column("Wallets L/S", justify="right", style="dim")

        for c in changes:
            # Signal tag
            if c["is_new"]:
                tag = "[green]NEW[/green]"
            elif c["is_dropped"]:
                tag = "[dim]GONE[/dim]"
            elif c["bias_flipped"]:
                tag = "[yellow]FLIP[/yellow]"
            elif c["pct_change"] > 0:
                tag = f"[green]+{c['pct_change']:.0f}%[/green]"
            else:
                tag = f"[red]{c['pct_change']:.0f}%[/red]"

            # Bias column
            if c["is_new"]:
                nb_color = "green" if c["new_bias"] == "LONG" else "red"
                bias_str = f"[{nb_color}]{c['new_bias']}[/{nb_color}]"
            elif c["is_dropped"]:
                bias_str = f"[dim]{c['old_bias']} -> GONE[/dim]"
            else:
                nb_color = "green" if c["new_bias"] == "LONG" else "red"
                bias_str = f"[dim]{c['old_bias']}[/dim] -> [{nb_color}]{c['new_bias']}[/{nb_color}]"

            # Exposure column
            if c["is_new"]:
                exp_str = f"[green]${c['new_total']:,.0f}[/green]"
            elif c["is_dropped"]:
                exp_str = f"[dim]${c['old_total']:,.0f} -> 0[/dim]"
            else:
                arrow_color = "green" if c["new_total"] > c["old_total"] else "red"
                exp_str = (
                    f"${c['old_total']:,.0f} -> "
                    f"[{arrow_color}]${c['new_total']:,.0f}[/{arrow_color}]"
                )

            # Wallets column
            if c["is_new"]:
                w_str = f"L:{c['new_long_w']} S:{c['new_short_w']}"
            elif c["is_dropped"]:
                w_str = f"[dim]L:{c['old_long_w']} S:{c['old_short_w']}[/dim]"
            else:
                w_str = (
                    f"L:{c['old_long_w']}->{c['new_long_w']} "
                    f"S:{c['old_short_w']}->{c['new_short_w']}"
                )

            table.add_row(c["coin"], tag, bias_str, exp_str, w_str)

        console.print(table)
    else:
        console.print("[green]No significant coin-level changes between snapshots.[/green]\n")

    # ---- Per-wallet: new positions opened ----
    console.print("\n[bold]Positions opened since last snapshot:[/bold]")
    new_opened_any = False
    for wallet, new_set in new_wallet_coins.items():
        old_set = old_wallet_coins.get(wallet, set())
        opened = new_set - old_set
        if not opened:
            continue
        new_opened_any = True
        data = new_snap["wallets"].get(wallet, {})
        pnl = data.get("pnl", 0)
        pnl_style = "green" if pnl >= 0 else "red"
        console.print(
            f"  [cyan]{wallet[:10]}...{wallet[-4:]}[/cyan] "
            f"([dim]{data.get('name', '?')}[/dim], "
            f"[{pnl_style}]${pnl:,.0f}[/{pnl_style}]) "
            f"opened: [yellow]{', '.join(sorted(opened))}[/yellow]"
        )
    if not new_opened_any:
        console.print("  [dim]None detected.[/dim]")

    # ---- Per-wallet: positions closed ----
    console.print("\n[bold]Positions closed since last snapshot:[/bold]")
    closed_any = False
    for wallet, old_set in old_wallet_coins.items():
        new_set = new_wallet_coins.get(wallet, set())
        closed = old_set - new_set
        if not closed:
            continue
        closed_any = True
        data = old_snap["wallets"].get(wallet, {})
        console.print(
            f"  [cyan]{wallet[:10]}...{wallet[-4:]}[/cyan] "
            f"([dim]{data.get('name', '?')}[/dim]) "
            f"closed: [red]{', '.join(sorted(closed))}[/red]"
        )
    if not closed_any:
        console.print("  [dim]None detected.[/dim]")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Hyperliquid whale tracker (read-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # --- prices ---
    pr = sub.add_parser(
        "prices",
        help="Show live HL mark prices (allMids) — canonical price source for analysis",
    )
    pr.add_argument(
        "coins", nargs="*", metavar="COIN",
        help="Specific coins to show (e.g. NEAR AAVE BTC). Omit for all.",
    )
    pr.set_defaults(func=cmd_prices)

    # --- leaderboard ---
    lb = sub.add_parser("leaderboard", help="Show top traders ranked by performance")
    lb.add_argument("--top", type=int, default=20)
    lb.add_argument("--by", choices=["pnl", "roi", "vlm"], default="pnl")
    lb.add_argument("--window", choices=["day", "week", "month", "allTime"], default="day")
    lb.set_defaults(func=cmd_leaderboard)

    # --- positions ---
    ps = sub.add_parser("positions", help="Show open positions for a single wallet")
    ps.add_argument("wallet", help="0x... wallet address")
    ps.set_defaults(func=cmd_positions)

    # --- whales ---
    wh = sub.add_parser("whales", help="Aggregate net exposure across top traders")
    wh.add_argument("--top", type=int, default=20)
    wh.add_argument("--window", choices=["day", "week", "month", "allTime"], default="week")
    wh.add_argument(
        "--coin", type=str, default=None, metavar="SYMBOL",
        help="Single-token deep dive: show only this coin + per-wallet breakdown (e.g. --coin ETH)",
    )
    wh.set_defaults(func=cmd_whales)

    # --- snapshot ---
    snap = sub.add_parser("snapshot", help="Save/diff whale snapshots for Morning Alpha Scan")
    snap_sub = snap.add_subparsers(dest="snap_action", required=True)

    ss = snap_sub.add_parser("save", help="Fetch and persist a timestamped snapshot")
    ss.add_argument("--top", type=int, default=20)
    ss.add_argument("--window", choices=["day", "week", "month", "allTime"], default="week")
    ss.set_defaults(func=cmd_snapshot_save)

    sd = snap_sub.add_parser("diff", help="Compare two most recent snapshots (Morning Alpha Scan)")
    sd.set_defaults(func=cmd_snapshot_diff)

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
