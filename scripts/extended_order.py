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
    amount     = Decimal(str(args.amount))
    price      = Decimal(str(args.price))
    sl_price   = Decimal(str(args.sl)) if args.sl else None
    tp_price   = Decimal(str(args.tp)) if args.tp else None
    reduce_only = args.reduce_only

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

    args = p.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
