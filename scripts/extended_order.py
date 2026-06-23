"""Extended Exchange — order placement via x10 SDK v2.0.0.

Requires .env:
    EXTENDED_API_KEY         — z API Management na extended.exchange
    EXTENDED_STARK_PUBLIC    — publiczny klucz Stark (0x...)
    EXTENDED_STARK_PRIVATE   — prywatny klucz Stark (0x...)
    EXTENDED_VAULT           — numer vault (liczba calkowita)
    TRADING_MODE=live        — lub EXTENDED_TRADING_MODE=live (domyslnie dry-run)

Usage:
    python scripts/extended_order.py order ETH-USD long  0.01 2500.00
    python scripts/extended_order.py order ETH-USD short 0.01 2500.00
    python scripts/extended_order.py order BTC-USD long  0.0033 68000 --sl 65000
    python scripts/extended_order.py order ETH-USD long  0.01 2500 --sl 2300 --tp 2800
    python scripts/extended_order.py order ETH-USD long  0.01 2500 --reduce-only
    python scripts/extended_order.py cancel-id  <order_id_int>
    python scripts/extended_order.py cancel-ext <external_order_id_str>
    python scripts/extended_order.py cancel-all

Market names: ETH-USD, BTC-USD, SOL-USD, TECH100m-USD, itp.
  -> pelna lista: python scripts/extended_executor.py markets
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

# Force UTF-8 on Windows to avoid cp1252 issues
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console(force_terminal=False, highlight=False)

# ── Env ───────────────────────────────────────────────────────────────────────

API_KEY     = os.getenv("EXTENDED_API_KEY", "")
PUBLIC_KEY  = os.getenv("EXTENDED_STARK_PUBLIC", "")
PRIVATE_KEY = os.getenv("EXTENDED_STARK_PRIVATE", "")
VAULT_RAW   = os.getenv("EXTENDED_VAULT", "")

_ext_mode = os.getenv("EXTENDED_TRADING_MODE") or os.getenv("TRADING_MODE") or "paper"
LIVE_MODE = _ext_mode.lower() == "live"

# Wejscia jako pasywny limit na cenie z sygnalu czesto nie wypelniaja sie (cena
# z TV jest juz nieaktualna do czasu wykonania) i wisza do wygasniecia GTT bez
# zadnego bledu w logu. EXTENDED_ENTRY_AGGRESSION_PCT przesuwa cene wejscia o
# ten % od aktualnej mark price w strone przeciecia ksiazki, zeby zlecenie
# wypelnilo sie od razu (taker) zamiast czekac na traf.
ENTRY_AGGRESSION_PCT = float(os.getenv("EXTENDED_ENTRY_AGGRESSION_PCT", "0.2"))


def _check_keys() -> None:
    missing = []
    if not API_KEY:     missing.append("EXTENDED_API_KEY")
    if not PUBLIC_KEY:  missing.append("EXTENDED_STARK_PUBLIC")
    if not PRIVATE_KEY: missing.append("EXTENDED_STARK_PRIVATE")
    if not VAULT_RAW:   missing.append("EXTENDED_VAULT")
    if missing:
        print(f"[BLAD] Brak w .env: {', '.join(missing)}")
        if "EXTENDED_STARK_PRIVATE" in missing:
            print("  -> extended.exchange -> API Management -> skopiuj Stark Private Key")
            print("  -> dodaj: EXTENDED_STARK_PRIVATE=0x... do .env")
        sys.exit(1)
    try:
        int(VAULT_RAW)
    except ValueError:
        print(f"[BLAD] EXTENDED_VAULT musi byc liczba, masz: '{VAULT_RAW}'")
        sys.exit(1)


def _build_account():
    from x10.core.stark_account import StarkPerpetualAccount
    return StarkPerpetualAccount(
        vault=int(VAULT_RAW),
        private_key=PRIVATE_KEY,
        public_key=PUBLIC_KEY,
        api_key=API_KEY,
    )


def _build_client(account):
    from x10.clients.rest.rest_api_client import RestApiClient
    from x10.config import MAINNET_CONFIG
    return RestApiClient(MAINNET_CONFIG, account)


# ── Commands ──────────────────────────────────────────────────────────────────

async def _place_order(args: argparse.Namespace) -> None:
    from x10.models.order import OrderSide, OrderTpslType, OrderTriggerPriceType, OrderPriceType
    from x10.signing.order_object import OrderTpslTriggerParam, DEFAULT_TAKER_FEE

    market     = args.market.upper()
    side_str   = args.side.lower()
    price      = Decimal(str(args.price))
    sl_price   = Decimal(str(args.sl)) if args.sl else None
    tp_price   = Decimal(str(args.tp)) if args.tp else None
    reduce_only = args.reduce_only

    # Validate market and get step sizes before anything else
    spec = _get_market_spec(market)
    if spec is None:
        sys.exit(1)

    # Round amount + price(s) to market precision — Extended rejects orders that violate either
    amount = _round_amount(Decimal(str(args.amount)), spec)
    if amount < spec["min"]:
        print(f"[BLAD] Amount {amount} < minOrderSize {spec['min']} dla {market}")
        sys.exit(1)
    # Entry orders: chase the live mark price instead of resting on the (possibly
    # stale) signal price, so the order crosses the book and fills immediately.
    if not reduce_only:
        mark = _get_mark_price(market)
        if mark > 0:
            aggressive = mark * (1 + ENTRY_AGGRESSION_PCT / 100) if side_str == "long" \
                else mark * (1 - ENTRY_AGGRESSION_PCT / 100)
            price = Decimal(str(aggressive))
    price = _round_price(price, spec)
    if sl_price is not None:
        sl_price = _round_price(sl_price, spec)
    if tp_price is not None:
        tp_price = _round_price(tp_price, spec)

    side = OrderSide.BUY if side_str == "long" else OrderSide.SELL

    # Build SL/TP
    stop_loss  = None
    take_profit = None
    tp_sl_type  = None

    if sl_price is not None:
        stop_loss = OrderTpslTriggerParam(
            trigger_price=sl_price,
            trigger_price_type=OrderTriggerPriceType.MARK,
            price=sl_price,
            price_type=OrderPriceType.MARKET,
        )
        tp_sl_type = OrderTpslType.ORDER

    if tp_price is not None:
        take_profit = OrderTpslTriggerParam(
            trigger_price=tp_price,
            trigger_price_type=OrderTriggerPriceType.MARK,
            price=tp_price,
            price_type=OrderPriceType.MARKET,
        )
        tp_sl_type = OrderTpslType.ORDER

    # Risk preview
    risk_usd = None
    if sl_price is not None:
        risk_per_unit = abs(float(price) - float(sl_price))
        risk_usd = risk_per_unit * float(amount)

    print(f"\nExtended Order — {'LIVE' if LIVE_MODE else 'DRY-RUN'}")
    print(f"  Market:      {market}")
    print(f"  Side:        {'LONG' if side_str == 'long' else 'SHORT'}")
    print(f"  Amount:      {amount}")
    print(f"  Price:       ${float(price):,.2f}")
    if sl_price:
        print(f"  Stop Loss:   ${float(sl_price):,.2f}")
    if tp_price:
        print(f"  Take Profit: ${float(tp_price):,.2f}")
    if risk_usd is not None:
        print(f"  Max Risk:    ${risk_usd:.2f}")
    if reduce_only:
        print(f"  Reduce-only: YES")
    print()

    if not LIVE_MODE:
        print("DRY-RUN: zlecenie nie zostalo zlozone.")
        print("Ustaw EXTENDED_TRADING_MODE=live lub TRADING_MODE=live w .env zeby wykonac.")
        return

    account = _build_account()
    client  = _build_client(account)

    try:
        kwargs: dict = dict(
            market_name=market,
            amount_of_synthetic=amount,
            price=price,
            side=side,
            taker_fee=DEFAULT_TAKER_FEE,
            reduce_only=reduce_only,
        )
        if stop_loss:
            kwargs["stop_loss"]   = stop_loss
            kwargs["take_profit"] = take_profit  # None is OK
            kwargs["tp_sl_type"]  = tp_sl_type

        result = await client.place_order(**kwargs)
        order = result.data if hasattr(result, "data") else result
        print(f"OK Zlecenie zlozone:")
        print(f"  order_id:    {getattr(order, 'id', '?')}")
        print(f"  external_id: {getattr(order, 'external_id', '?')}")
        print(f"  status:      {getattr(order, 'status', '?')}")
    except Exception as e:
        print(f"[BLAD] {e}")
        raise
    finally:
        await client.close()


def _get_position_size(market: str) -> tuple[str | None, float]:
    """REST read — returns (side, size) for an open position, or (None, 0)."""
    import httpx, ssl, truststore
    _SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    headers = {"User-Agent": "trading-ai-bot/1.0"}
    if API_KEY:
        headers["X-Api-Key"] = API_KEY
    try:
        with httpx.Client(verify=_SSL, timeout=10, headers=headers) as c:
            r = c.get("https://api.starknet.extended.exchange/api/v1/user/positions")
            r.raise_for_status()
            body = r.json()
            positions = body.get("data", body) if isinstance(body, dict) else body
            if isinstance(positions, list):
                for p in positions:
                    mkt = (p.get("market") or p.get("symbol") or "").upper()
                    if mkt == market.upper():
                        side = (p.get("side") or "LONG").upper()
                        size = abs(float(p.get("size") or p.get("quantity") or 0))
                        return side, size
    except Exception as e:
        print(f"[WARN] get_position {market}: {e}")
    return None, 0.0


def _get_market_spec(market: str) -> dict | None:
    """Fetch market step sizes from Extended. Returns None if market not found."""
    import httpx, ssl, truststore
    _SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with httpx.Client(verify=_SSL, timeout=8) as c:
            r = c.get("https://api.starknet.extended.exchange/api/v1/info/markets")
            r.raise_for_status()
            body = r.json()
            mkts = body.get("data", body) if isinstance(body, dict) else body
            if isinstance(mkts, list):
                for m in mkts:
                    if (m.get("name") or "").upper() == market.upper():
                        cfg = m.get("tradingConfig", {})
                        return {
                            "step":            Decimal(str(cfg.get("minOrderSizeChange") or "1")),
                            "min":             Decimal(str(cfg.get("minOrderSize")        or "1")),
                            "price_step":      Decimal(str(cfg.get("minPriceChange")      or "0.0001")),
                            "asset_precision": int(m.get("assetPrecision") or 0),
                        }
                names = sorted(m.get("name", "") for m in mkts if m.get("name"))
                print(f"[BLAD] Market {market} not found on Extended.")
                print(f"  Dostepne rynki: {', '.join(names)}")
    except Exception as e:
        print(f"[WARN] get_market_spec {market}: {e}")
    return None


def _round_amount(raw_amount: Decimal, spec: dict) -> Decimal:
    """Round an order quantity down to the market's step/precision."""
    from decimal import ROUND_DOWN
    step = spec["step"]
    rounded = (raw_amount // step) * step
    if spec["asset_precision"] == 0:
        return Decimal(str(int(rounded)))
    quant = Decimal(10) ** -spec["asset_precision"]
    return rounded.quantize(quant, rounding=ROUND_DOWN)


def _round_price(raw_price: Decimal, spec: dict) -> Decimal:
    """Round a price to the nearest multiple of the market's price_step."""
    from decimal import ROUND_HALF_UP
    step = spec["price_step"]
    if step <= 0:
        return raw_price
    return (raw_price / step).to_integral_value(rounding=ROUND_HALF_UP) * step


def _get_mark_price(market: str) -> float:
    """REST read — returns current mark price for a market."""
    import httpx, ssl, truststore
    _SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with httpx.Client(verify=_SSL, timeout=8) as c:
            r = c.get("https://api.starknet.extended.exchange/api/v1/info/markets")
            r.raise_for_status()
            body = r.json()
            mkts = body.get("data", body) if isinstance(body, dict) else body
            if isinstance(mkts, list):
                for m in mkts:
                    if (m.get("name") or "").upper() == market.upper():
                        s = m.get("marketStats", {})
                        return float(s.get("markPrice") or s.get("lastPrice") or 0)
    except Exception as e:
        print(f"[WARN] get_mark_price {market}: {e}")
    return 0.0


async def _close_position(args: argparse.Namespace) -> None:
    """Close a percentage of the current position (default 100%) via reduce-only limit order."""
    from x10.models.order import OrderSide
    from x10.signing.order_object import DEFAULT_TAKER_FEE

    market = args.market.upper()
    pct    = float(getattr(args, "pct", 100))

    spec = _get_market_spec(market)
    if spec is None:
        sys.exit(1)

    pos_side, pos_size = _get_position_size(market)
    if pos_size <= 0:
        print(f"No open position for {market} — nothing to close.")
        return

    close_qty  = _round_amount(Decimal(str(pos_size * pct / 100.0)), spec)
    if close_qty <= 0:
        print(f"[BLAD] Closing amount rounds to 0 dla {market} (pos={pos_size}, pct={pct}).")
        return
    close_side = OrderSide.SELL if pos_side == "LONG" else OrderSide.BUY
    side_str   = "SELL" if pos_side == "LONG" else "BUY"

    # Aggressive limit price: 5% past market to guarantee fill as reduce-only
    mark = _get_mark_price(market)
    if mark <= 0:
        print("[BLAD] Nie mozna pobrac mark price — nie wiem po ile zamknac.")
        return
    raw_fill   = Decimal(str(mark * (0.95 if close_side == OrderSide.SELL else 1.05)))
    fill_price = _round_price(raw_fill, spec)

    print(f"\nExtended Close Position — {'LIVE' if LIVE_MODE else 'DRY-RUN'}")
    print(f"  Market:     {market}")
    print(f"  Position:   {pos_side}  {pos_size}")
    print(f"  Closing:    {pct:.0f}% → {close_qty}")
    print(f"  Order:      {side_str} {close_qty} reduce-only @ ~${float(fill_price):,.2f}")
    print()

    if not LIVE_MODE:
        print("DRY-RUN: pozycja nie zostala zamknieta.")
        print("Ustaw EXTENDED_TRADING_MODE=live w .env zeby wykonac.")
        return

    account = _build_account()
    client  = _build_client(account)
    try:
        result = await client.place_order(
            market_name=market,
            amount_of_synthetic=close_qty,
            price=fill_price,
            side=close_side,
            taker_fee=DEFAULT_TAKER_FEE,
            reduce_only=True,
        )
        order = result.data if hasattr(result, "data") else result
        print(f"OK Zamknieto {pct:.0f}% pozycji {market}:")
        print(f"  order_id: {getattr(order, 'id', '?')}")
        print(f"  status:   {getattr(order, 'status', '?')}")
    except Exception as e:
        print(f"[BLAD] {e}")
        raise
    finally:
        await client.close()


async def _cancel_by_id(args: argparse.Namespace) -> None:
    order_id = int(args.order_id)
    print(f"\nCancel order id={order_id}  mode={'LIVE' if LIVE_MODE else 'DRY-RUN'}")

    if not LIVE_MODE:
        print("DRY-RUN: anulowanie nie zostalo wyslane.")
        return

    account = _build_account()
    client  = _build_client(account)
    try:
        await client.orders.cancel_order(order_id=order_id)
        print(f"OK Zlecenie {order_id} anulowane.")
    except Exception as e:
        print(f"[BLAD] {e}")
        raise
    finally:
        await client.close()


async def _cancel_by_ext(args: argparse.Namespace) -> None:
    ext_id = args.external_id
    print(f"\nCancel order external_id={ext_id}  mode={'LIVE' if LIVE_MODE else 'DRY-RUN'}")

    if not LIVE_MODE:
        print("DRY-RUN: anulowanie nie zostalo wyslane.")
        return

    account = _build_account()
    client  = _build_client(account)
    try:
        await client.orders.cancel_order_by_external_id(ext_id)
        print(f"OK Zlecenie {ext_id} anulowane.")
    except Exception as e:
        print(f"[BLAD] {e}")
        raise
    finally:
        await client.close()


async def _cancel_all(args: argparse.Namespace) -> None:
    print(f"\nCancel ALL orders  mode={'LIVE' if LIVE_MODE else 'DRY-RUN'}")

    if not LIVE_MODE:
        print("DRY-RUN: mass cancel nie zostalo wyslane.")
        return

    account = _build_account()
    client  = _build_client(account)
    try:
        await client.orders.mass_cancel(cancel_all=True)
        print("OK Wszystkie zlecenia anulowane.")
    except Exception as e:
        print(f"[BLAD] {e}")
        raise
    finally:
        await client.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    _check_keys()

    p = argparse.ArgumentParser(description="Extended Exchange — skladanie zlecen")
    sub = p.add_subparsers(dest="cmd", required=True)

    # order <market> <long|short> <amount> <price> [--sl X] [--tp X]
    ord_p = sub.add_parser("order", help="Zloz zlecenie limit")
    ord_p.add_argument("market",  help="np. ETH-USD, BTC-USD, TECH100m-USD")
    ord_p.add_argument("side",    choices=["long", "short"])
    ord_p.add_argument("amount",  type=float, help="Ilosc syntetycznego aktywa")
    ord_p.add_argument("price",   type=float, help="Cena limit")
    ord_p.add_argument("--sl",    type=float, default=None, help="Stop Loss cena")
    ord_p.add_argument("--tp",    type=float, default=None, help="Take Profit cena")
    ord_p.add_argument("--reduce-only", action="store_true")
    ord_p.set_defaults(func=_place_order)

    # close <market> — zamknij cala pozycje
    cl_p = sub.add_parser("close", help="Zamknij cala pozycje (reduce-only market)")
    cl_p.add_argument("market", help="np. BTC-USD, ETH-USD")
    cl_p.set_defaults(func=_close_position, pct=100)

    # partial-close <market> <pct> — zamknij X% pozycji
    pc_p = sub.add_parser("partial-close", help="Zamknij X%% pozycji (reduce-only)")
    pc_p.add_argument("market", help="np. BTC-USD, ETH-USD")
    pc_p.add_argument("pct", type=float, help="Procent do zamkniecia, np. 40")
    pc_p.set_defaults(func=_close_position)

    # cancel-id <order_id>
    ci_p = sub.add_parser("cancel-id", help="Anuluj po numerycznym ID")
    ci_p.add_argument("order_id", help="Numeryczne ID zlecenia")
    ci_p.set_defaults(func=_cancel_by_id)

    # cancel-ext <external_id>
    ce_p = sub.add_parser("cancel-ext", help="Anuluj po external ID (string)")
    ce_p.add_argument("external_id", help="External string ID zlecenia")
    ce_p.set_defaults(func=_cancel_by_ext)

    # cancel-all
    ca_p = sub.add_parser("cancel-all", help="Anuluj WSZYSTKIE otwarte zlecenia")
    ca_p.set_defaults(func=_cancel_all)

    # markets — lista dostepnych rynkow
    sub.add_parser("markets", help="Lista dostepnych rynkow na Extended").set_defaults(func=None)

    args = p.parse_args()

    if args.cmd == "markets":
        import httpx, ssl, truststore
        _SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with httpx.Client(verify=_SSL, timeout=10) as c:
            r = c.get("https://api.starknet.extended.exchange/api/v1/info/markets")
            body = r.json()
            mkts = body.get("data", body) if isinstance(body, dict) else body
            print(f"\n{'Market':<22} {'MinOrder':<12} {'Step':<8} {'PriceStep':<12} {'Precision'}")
            print("-" * 65)
            for m in sorted(mkts, key=lambda x: x.get("name", "")):
                cfg = m.get("tradingConfig", {})
                print(f"{m.get('name',''):<22} {cfg.get('minOrderSize','?'):<12} {cfg.get('minOrderSizeChange','?'):<8} {cfg.get('minPriceChange','?'):<12} {m.get('assetPrecision','?')}")
        return

    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
