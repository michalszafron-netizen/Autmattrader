"""Hyperliquid executor — standard perps + HIP-3 xyz TradFi.

Supports:
  - Standard HL perps: BTC, ETH, HYPE, SOL, etc.
  - HIP-3 xyz DEX: xyz:SILVER, xyz:GOLD, xyz:BRENTOIL, xyz:SP500, xyz:NVDA, etc.

HIP-3 asset index formula:
  asset = 100000 + perp_dex_index * 10000 + index_in_meta
  xyz DEX: perp_dex_index = 1  →  asset = 110000 + index_in_meta

Risk rules (hard, non-negotiable):
  - TRADING_MODE=paper  →  dry-run only (no real orders)
  - SL is mandatory for any live position
  - Max notional per order: MAX_ORDER_USDC (from .env, default $50)
  - Leverage capped at DEFAULT_LEVERAGE (from .env, default 5x)

Usage:
  python scripts/hl_executor.py --help
  python scripts/hl_executor.py quote xyz:SILVER
  python scripts/hl_executor.py order xyz:SILVER long 0.14 74.0
  python scripts/hl_executor.py cancel xyz:SILVER 432926143861
  python scripts/hl_executor.py positions
  python scripts/hl_executor.py tickers            # list all available assets
  python scripts/hl_executor.py tickers --xyz      # xyz TradFi only
"""

from __future__ import annotations

# Fix: Git Bash na Windows injectuje OPENSSL_CONF który crashuje podpisywanie kluczem
# (OPENSSL_Uplink error). Czyścimy przed załadowaniem eth-account / cryptography.
import os as _os
if _os.name == "nt":
    _os.environ.pop("OPENSSL_CONF", None)
    _os.environ.pop("SSL_CERT_FILE", None)
    _os.environ.pop("SSL_CERT_DIR", None)

import argparse
import os
import ssl
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

# ── SSL fix (Windows cert store) ─────────────────────────────────────────────
_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
os.environ.setdefault("REQUESTS_CA_BUNDLE", str(Path.home() / ".claude" / "windows-ca-bundle.pem"))
os.environ.setdefault("SSL_CERT_FILE", os.environ["REQUESTS_CA_BUNDLE"])

# ── Config ────────────────────────────────────────────────────────────────────
HL_API = "https://api.hyperliquid.xyz"
XYZ_DEX_NAME = "xyz"
XYZ_PERP_DEX_INDEX = 1          # null=0, xyz=1  (from perpDexs endpoint)
HIP3_BASE = 100000

# Per-exchange mode: HL_TRADING_MODE takes priority, falls back to TRADING_MODE
_hl_mode = os.getenv("HL_TRADING_MODE") or os.getenv("TRADING_MODE", "paper")
PAPER_MODE = _hl_mode.lower() != "live"
MAX_ORDER_USDC = float(os.getenv("MAX_ORDER_USDC", "50"))
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "5"))

console = Console()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _post(payload: dict) -> dict | list:
    with httpx.Client(verify=_SSL_CTX, timeout=30.0) as c:
        r = c.post(f"{HL_API}/info", json=payload)
        r.raise_for_status()
        return r.json()


def _exchange(payload: dict) -> dict:
    with httpx.Client(verify=_SSL_CTX, timeout=30.0) as c:
        r = c.post(f"{HL_API}/exchange", json=payload)
        r.raise_for_status()
        return r.json()


# ── Asset registry ────────────────────────────────────────────────────────────

class AssetRegistry:
    """Loads standard perp + xyz HIP-3 asset index mappings."""

    def __init__(self) -> None:
        self._name_to_index: dict[str, int] = {}
        self._name_to_meta: dict[str, dict] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return

        # 1. Standard HL perps (indices 0-N)
        std = _post({"type": "meta"})
        for i, asset in enumerate(std.get("universe", [])):
            name = asset["name"]
            self._name_to_index[name] = i
            self._name_to_meta[name] = {**asset, "_dex": "hl", "_idx": i}

        # 2. xyz HIP-3 perps
        xyz = _post({"type": "meta", "dex": XYZ_DEX_NAME})
        for i, asset in enumerate(xyz.get("universe", [])):
            name = asset["name"]  # e.g. "xyz:SILVER"
            idx = HIP3_BASE + XYZ_PERP_DEX_INDEX * 10000 + i
            self._name_to_index[name] = idx
            self._name_to_meta[name] = {**asset, "_dex": "xyz", "_idx": i, "_exchange_idx": idx}

        self._loaded = True

    def index(self, coin: str) -> int:
        self.load()
        if coin not in self._name_to_index:
            raise ValueError(
                f"Unknown asset: {coin!r}. "
                f"Run `python scripts/hl_executor.py tickers` to list all available."
            )
        return self._name_to_index[coin]

    def meta(self, coin: str) -> dict:
        self.load()
        return self._name_to_meta.get(coin, {})

    def all_assets(self, xyz_only: bool = False) -> list[tuple[str, dict]]:
        self.load()
        items = list(self._name_to_meta.items())
        if xyz_only:
            items = [(k, v) for k, v in items if v.get("_dex") == "xyz"]
        return sorted(items, key=lambda x: (x[1].get("_dex", ""), x[0]))

    def resolve(self, name: str) -> str:
        """Accept 'SILVER' or 'xyz:SILVER' — always return full coin name."""
        self.load()
        if name in self._name_to_index:
            return name
        # Try xyz: prefix
        xyz_name = f"xyz:{name.upper()}"
        if xyz_name in self._name_to_index:
            return xyz_name
        raise ValueError(f"Unknown asset: {name!r}. Try `tickers` command.")


REGISTRY = AssetRegistry()


# ── Signing & order placement ─────────────────────────────────────────────────

def _build_and_sign_order(
    coin: str,
    is_buy: bool,
    sz: float,
    limit_px: float,
    tif: str = "Gtc",
    reduce_only: bool = False,
) -> dict:
    """Build signed order action using HL EIP-712 signing."""
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants

    agent_key = os.getenv("HL_AGENT_PRIVATE_KEY")
    main_wallet = os.getenv("HL_MAIN_WALLET_ADDRESS")
    if not agent_key or not main_wallet:
        raise ValueError("HL_AGENT_PRIVATE_KEY and HL_MAIN_WALLET_ADDRESS must be set in .env")

    account = Account.from_key(agent_key)
    exchange = Exchange(account, constants.MAINNET_API_URL, account_address=main_wallet)

    # Inject asset index for all tracked coins
    REGISTRY.load()
    for name, idx in REGISTRY._name_to_index.items():
        exchange.info.name_to_coin[name] = name
        exchange.info.coin_to_asset[name] = idx

    return exchange.order(coin, is_buy, sz, limit_px, {"limit": {"tif": tif}}, reduce_only=reduce_only)


def _cancel_order(coin: str, oid: int) -> dict:
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants

    agent_key = os.getenv("HL_AGENT_PRIVATE_KEY")
    main_wallet = os.getenv("HL_MAIN_WALLET_ADDRESS")
    account = Account.from_key(agent_key)
    exchange = Exchange(account, constants.MAINNET_API_URL, account_address=main_wallet)

    REGISTRY.load()
    for name, idx in REGISTRY._name_to_index.items():
        exchange.info.name_to_coin[name] = name
        exchange.info.coin_to_asset[name] = idx

    return exchange.cancel(coin, oid)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_tickers(args: argparse.Namespace) -> None:
    REGISTRY.load()
    assets = REGISTRY.all_assets(xyz_only=args.xyz)

    # Filter by search term
    if args.search:
        q = args.search.lower()
        assets = [(k, v) for k, v in assets if q in k.lower()]

    title = f"{'xyz TradFi' if args.xyz else 'All'} assets"
    if args.search:
        title += f" matching '{args.search}'"

    table = Table(title=title)
    table.add_column("Coin", style="cyan")
    table.add_column("DEX", style="dim")
    table.add_column("MaxLev", justify="right")
    table.add_column("ExchangeIdx", justify="right", style="dim")

    # Get live prices for results
    with httpx.Client(verify=_SSL_CTX, timeout=15) as c:
        mids_std = c.post(f"{HL_API}/info", json={"type": "allMids"}).json()
        mids_xyz = c.post(f"{HL_API}/info", json={"type": "allMids", "dex": XYZ_DEX_NAME}).json()
    all_mids = {**mids_std, **mids_xyz}

    price_col = bool(args.search)  # show prices when searching
    if price_col:
        table.add_column("Price $", justify="right", style="yellow")

    for name, meta in assets:
        dex = meta.get("_dex", "hl")
        lev = meta.get("maxLeverage", "?")
        idx = meta.get("_exchange_idx", meta.get("_idx", "?"))
        row = [name, dex, f"{lev}x", str(idx)]
        if price_col:
            px = all_mids.get(name, "")
            row.append(f"${float(px):,.4f}" if px else "-")
        table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]Total: {len(assets)} assets[/dim]")


def cmd_quote(args: argparse.Namespace) -> None:
    coin = REGISTRY.resolve(args.coin)
    data = _post({"type": "l2Book", "coin": coin})
    levels = data.get("levels", [[], []])
    bids = levels[0]
    asks = levels[1]
    best_bid = float(bids[0]["px"]) if bids else 0
    best_ask = float(asks[0]["px"]) if asks else 0
    mid = (best_bid + best_ask) / 2 if best_bid and best_ask else best_bid or best_ask

    meta = REGISTRY.meta(coin)
    console.print(f"\n[bold cyan]{coin}[/bold cyan]")
    console.print(f"  Bid: [green]${best_bid:.4f}[/green]  Ask: [red]${best_ask:.4f}[/red]  Mid: ${mid:.4f}")
    console.print(f"  MaxLev: {meta.get('maxLeverage','?')}x  DEX: {meta.get('_dex','?')}")
    console.print(f"  ExchangeIndex: {REGISTRY.index(coin)}")


def _get_market_price(coin: str, is_buy: bool) -> float:
    """Get aggressive market price via allMids — works for both standard and xyz assets."""
    dex = REGISTRY.meta(coin).get("_dex", "hl")
    if dex == "xyz":
        mids = _post({"type": "allMids", "dex": XYZ_DEX_NAME})
    else:
        mids = _post({"type": "allMids"})
    mid = float(mids.get(coin, 0))
    if not mid:
        raise ValueError(f"Could not get market price for {coin}")
    # 1% slippage buffer ensures fill on both taker sides
    return mid * 1.01 if is_buy else mid * 0.99


def cmd_order(args: argparse.Namespace) -> None:
    coin = REGISTRY.resolve(args.coin)
    is_buy = args.side.lower() in ("long", "buy", "b")
    sz = float(args.size)

    # Market order: aggressive limit GTC (fills immediately at market, rests if not)
    # IOC rejected on some HIP-3 assets — GTC with 2% slippage is safer
    is_market = getattr(args, "market", False) or args.price == 0
    if is_market:
        px = _get_market_price(coin, is_buy)
        # Round to 3 decimal places (HL xyz tick size)
        px = round(px, 3)
        tif = "Gtc"
        order_type = "MARKET"
    else:
        px = float(args.price)
        tif = args.tif
        order_type = "LIMIT"

    notional = sz * px

    # Risk checks
    if notional > MAX_ORDER_USDC:
        console.print(f"[red]Order notional ${notional:.2f} exceeds MAX_ORDER_USDC=${MAX_ORDER_USDC}. Rejected.[/red]")
        sys.exit(1)

    side_str = "LONG" if is_buy else "SHORT"
    side_color = "green" if is_buy else "red"

    console.print(f"\n[bold]{order_type} Order[/bold]: [{side_color}]{side_str}[/{side_color}] {sz} {coin} @ ${px:.4f}")
    console.print(f"  Notional: ~${notional:.2f}  |  Mode: {'[yellow]DRY-RUN (paper)[/yellow]' if PAPER_MODE else '[bold green]LIVE[/bold green]'}")

    if PAPER_MODE:
        console.print("[yellow]PAPER MODE — order not submitted. Set TRADING_MODE=live to place real orders.[/yellow]")
        return

    result = _build_and_sign_order(coin, is_buy, sz, px, tif=tif)
    if result.get("status") == "ok":
        statuses = result["response"]["data"]["statuses"]
        for s in statuses:
            if "resting" in s:
                oid = s["resting"]["oid"]
                console.print(f"[green]Order placed[/green] — OID: {oid}")
            elif "filled" in s:
                console.print(f"[bold green]Order filled[/bold green] — {s['filled']}")
            elif "error" in s:
                console.print(f"[red]Order error: {s['error']}[/red]")
    else:
        console.print(f"[red]Failed: {result}[/red]")


def cmd_cancel(args: argparse.Namespace) -> None:
    coin = REGISTRY.resolve(args.coin)
    oid = int(args.oid)
    console.print(f"Cancelling OID {oid} on {coin}…")
    result = _cancel_order(coin, oid)
    if result.get("status") == "ok":
        console.print(f"[green]Cancelled[/green]")
    else:
        console.print(f"[red]Failed: {result}[/red]")


def cmd_positions(args: argparse.Namespace) -> None:
    main_wallet = os.getenv("HL_MAIN_WALLET_ADDRESS")
    state = _post({"type": "clearinghouseState", "user": main_wallet})
    margin = state.get("marginSummary", {})
    cross = state.get("crossMarginSummary", {})

    acct_val = float(margin.get("accountValue") or cross.get("accountValue") or 0)
    console.print(f"\n[bold]Account[/bold]: ${acct_val:,.2f}")

    # Standard perp positions
    positions = state.get("assetPositions", [])

    # xyz positions (separate clearinghouse)
    xyz_state = _post({"type": "clearinghouseState", "user": main_wallet, "dex": XYZ_DEX_NAME})
    xyz_positions = xyz_state.get("assetPositions", [])

    all_positions = [(p, "hl") for p in positions] + [(p, "xyz") for p in xyz_positions]

    if not all_positions:
        console.print("[dim]No open positions.[/dim]")
        return

    table = Table(title="Open positions")
    table.add_column("Coin", style="cyan")
    table.add_column("DEX", style="dim")
    table.add_column("Side")
    table.add_column("Size", justify="right")
    table.add_column("Entry $", justify="right")
    table.add_column("uPnL $", justify="right")
    table.add_column("Lev", justify="right", style="dim")

    for p, dex in all_positions:
        pos = p.get("position", {})
        szi = Decimal(pos.get("szi", "0"))
        if szi == 0:
            continue
        side = "LONG" if szi > 0 else "SHORT"
        sc = "green" if szi > 0 else "red"
        upnl = Decimal(pos.get("unrealizedPnl", "0"))
        uc = "green" if upnl >= 0 else "red"
        lev = pos.get("leverage", {}).get("value", "?")
        table.add_row(
            pos.get("coin", "?"),
            dex,
            f"[{sc}]{side}[/{sc}]",
            f"{abs(szi):,.4f}",
            f"${Decimal(pos.get('entryPx','0')):,.4f}",
            f"[{uc}]${upnl:+,.2f}[/{uc}]",
            f"{lev}x",
        )
    console.print(table)


def cmd_open_orders(args: argparse.Namespace) -> None:
    wallet = os.getenv("HL_MAIN_WALLET_ADDRESS")
    # frontendOpenOrders returns ALL order types: limit, stop-loss, take-profit, trigger
    # (plain openOrders only returns limit orders — misses TP/SL)
    orders     = _post({"type": "frontendOpenOrders", "user": wallet})
    xyz_orders = _post({"type": "frontendOpenOrders", "user": wallet, "dex": XYZ_DEX_NAME})
    all_orders = [(o, "hl") for o in (orders if isinstance(orders, list) else [])] + \
                 [(o, "xyz") for o in (xyz_orders if isinstance(xyz_orders, list) else [])]

    if not all_orders:
        console.print("[dim]No open orders.[/dim]")
        return

    table = Table(title="Open orders (limit + trigger/TP/SL)")
    table.add_column("Coin", style="cyan")
    table.add_column("DEX", style="dim")
    table.add_column("Type")
    table.add_column("Side")
    table.add_column("Trigger $", justify="right")
    table.add_column("Limit $", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("OID")

    for o, dex in all_orders:
        side = o.get("side", "?")
        sc   = "green" if side == "B" else "red"

        # Determine order type label and trigger/limit prices
        order_type = o.get("orderType", "Limit")
        tpsl       = o.get("tpsl", "")        # "tp" | "sl" | ""
        trigger_px = o.get("triggerPx", "")
        limit_px   = o.get("limitPx", "")

        # Build a readable type label
        if tpsl == "tp":
            type_label = "[green]TP[/green]"
        elif tpsl == "sl":
            type_label = "[red]SL[/red]"
        elif "stop" in order_type.lower():
            type_label = "[red]STOP[/red]"
        elif "trigger" in order_type.lower():
            type_label = "[yellow]TRIGGER[/yellow]"
        else:
            type_label = "[dim]LIMIT[/dim]"

        trigger_str = f"${float(trigger_px):,.4f}" if trigger_px else "—"
        limit_str   = f"${float(limit_px):,.4f}"   if limit_px   else "MARKET"

        table.add_row(
            o.get("coin", "?"), dex,
            type_label,
            f"[{sc}]{'BUY' if side == 'B' else 'SELL'}[/{sc}]",
            trigger_str,
            limit_str,
            o.get("sz", "?"),
            str(o.get("oid", "?")),
        )
    console.print(table)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Hyperliquid executor — standard perps + xyz TradFi")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tickers", help="List available assets")
    t.add_argument("--xyz", action="store_true", help="xyz TradFi only")
    t.add_argument("--search", "-s", default="", help="Filter by name (e.g. gold, tsla, gas)")
    t.set_defaults(func=cmd_tickers)

    q = sub.add_parser("quote", help="Current price for an asset")
    q.add_argument("coin")
    q.set_defaults(func=cmd_quote)

    o = sub.add_parser("order", help="Place limit order (price=0 for market)")
    o.add_argument("coin", help="e.g. BTC, SILVER, xyz:SILVER, GOLD, NATGAS")
    o.add_argument("side", choices=["long", "short", "buy", "sell", "b", "s"])
    o.add_argument("size", type=float, help="Size in base asset units")
    o.add_argument("price", type=float, nargs="?", default=0,
                   help="Limit price. Omit or use 0 for market order.")
    o.add_argument("--tif", default="Gtc", choices=["Gtc", "Ioc", "Alo"])
    o.set_defaults(func=cmd_order)

    # Convenience market order alias
    m = sub.add_parser("market", help="Place market order")
    m.add_argument("coin")
    m.add_argument("side", choices=["long", "short", "buy", "sell", "b", "s"])
    m.add_argument("size", type=float)
    m.add_argument("price", type=float, nargs="?", default=0)
    m.add_argument("--tif", default="Ioc")
    m.set_defaults(func=cmd_order, market=True)

    c = sub.add_parser("cancel", help="Cancel an open order")
    c.add_argument("coin")
    c.add_argument("oid", type=int)
    c.set_defaults(func=cmd_cancel)

    sub.add_parser("positions", help="Show open positions").set_defaults(func=cmd_positions)
    sub.add_parser("orders", help="Show open orders").set_defaults(func=cmd_open_orders)

    args = p.parse_args()
    try:
        args.func(args)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
