"""hl_scalp.py — HL xyz scalp execution engine.

Extends hl_executor with fast limit-entry / limit-exit scalping.
PATTERN: limit buy (maker) → limit sell at TP (maker) = 0.005% fee each way.

Usage:
    python scripts/hl_scalp.py status              # current positions + stats
    python scripts/hl_scalp.py trade GOLD long     # manual trade (paper)
    python scripts/hl_scalp.py stats               # scalping performance
    python scripts/hl_scalp.py live                # live signal-driven auto-trader
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import ssl
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from db import DB

# ── Reuse hl_executor building blocks ─────────────────────────────────────────
import hl_executor as he

_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
HL_API = "https://api.hyperliquid.xyz"
XYZ_DEX = "xyz"

# ── Config ────────────────────────────────────────────────────────────────────
_mode = (os.getenv("SCALP_MODE") or os.getenv("HL_TRADING_MODE") or os.getenv("TRADING_MODE", "paper")).lower()
PAPER_MODE = _mode != "live"

# Scalp parameters
DEFAULT_LEVERAGE = int(os.getenv("SCALP_LEVERAGE", "5"))
DEFAULT_SIZE_USD = float(os.getenv("SCALP_SIZE_USD", "25"))  # notional per scalp
TP_PCT = float(os.getenv("SCALP_TP_PCT", "0.40"))           # take profit %
SL_PCT = float(os.getenv("SCALP_SL_PCT", "0.20"))           # stop loss %
MAX_POSITIONS = int(os.getenv("SCALP_MAX_POS", "1"))         # max concurrent
MAX_TRADE_DAILY = int(os.getenv("SCALP_MAX_DAILY", "200"))    # max trades/day (high for stats)

TRADEABLE_XYZ = {"xyz:GOLD", "xyz:SILVER", "xyz:SP500", "xyz:CL"}


def _get_sz_decimals(coin: str) -> int:
    """Get szDecimals from AssetRegistry (live data from HL)."""
    try:
        he.REGISTRY.load()
        return int(he.REGISTRY.meta(coin).get("szDecimals", 4))
    except Exception:
        return 4


def _get_px_decimals(coin: str) -> int:
    """Estimated price decimals based on price level."""
    mids = get_mids([coin])
    px = mids.get(coin, 100)
    if px >= 1000:
        return 2
    elif px >= 100:
        return 3
    elif px >= 1:
        return 4
    return 5

_db = DB()
he._pending_tpsl = []  # live trades waiting for TP/SL placement


# ── Price helpers ─────────────────────────────────────────────────────────────

def get_mids(coins: list[str] | None = None) -> dict[str, float]:
    """Fetch mid prices for xyz instruments."""
    with httpx.Client(verify=_SSL, timeout=10) as c:
        r = c.post(f"{HL_API}/info", json={"type": "allMids", "dex": XYZ_DEX})
        raw = r.json()
    if coins:
        return {k: float(v) for k, v in raw.items() if k in coins and v}
    return {k: float(v) for k, v in raw.items() if v}


def get_l2(coin: str) -> dict:
    """Return L2 book snapshot for a coin."""
    with httpx.Client(verify=_SSL, timeout=10) as c:
        r = c.post(f"{HL_API}/info", json={"type": "l2Book", "coin": coin})
        return r.json()


def get_best_bid_ask(coin: str) -> tuple[float, float, float, float]:
    """Return (bid, ask, bid_sz, ask_sz)."""
    bk = get_l2(coin)
    levels = bk.get("levels", [[], []])
    bids = levels[0]
    asks = levels[1]
    bid = float(bids[0]["px"]) if bids else 0
    ask = float(asks[0]["px"]) if asks else 0
    bid_sz = float(bids[0]["sz"]) if bids else 0
    ask_sz = float(asks[0]["sz"]) if asks else 0
    return bid, ask, bid_sz, ask_sz


def round_price(coin: str, px: float) -> float:
    """Round to instrument's tick rules — detect from L2 if needed."""
    try:
        he.REGISTRY.load()
        decimals = int(he.REGISTRY.meta(coin).get("szDecimals", 4))
        # xyz tick size heuristic: GOLD/SP500 price ~1000+ → 0.1,
        # SILVER ~65 → 0.001, CL ~75 → 0.005
        if px >= 1000:
            tick = 0.1
        elif px >= 10:
            tick = 0.001
        else:
            tick = 0.0001
        return round(px / tick) * tick
    except Exception:
        return round(px, 2)


def round_size(coin: str, contracts: float) -> float:
    """Round size to instrument's szDecimals (live from HL)."""
    decimals = _get_sz_decimals(coin)
    return round(contracts, decimals)


def calc_contracts(coin: str, notional_usd: float, price: float) -> float:
    """Calculate how many contracts for a given notional."""
    if price <= 0:
        return 0
    return round_size(coin, notional_usd / price)


# ── Order placement ───────────────────────────────────────────────────────────

def _ensure_leverage(coin: str, lev: int = DEFAULT_LEVERAGE) -> None:
    """Set leverage, silently skipping if already set or on error."""
    try:
        he._set_leverage(coin, lev)
    except Exception:
        pass


def place_limit_entry(coin: str, direction: str, contracts: float,
                      price: float, tif: str = "Gtc") -> tuple[int | None, str]:
    """Place a limit entry order. Returns (order_id, status_message).

    direction: 'long' or 'short'
    price: limit price (bid for long, ask for short)
    Returns (None, error_msg) on failure.
    """
    is_buy = direction == "long"
    side_str = "LONG" if is_buy else "SHORT"

    if contracts <= 0:
        return None, f"Invalid size {contracts}"

    notional = contracts * price
    if notional > he.MAX_ORDER_USDC:
        return None, f"Notional ${notional:.2f} > MAX_ORDER_USDC ${he.MAX_ORDER_USDC}"

    if PAPER_MODE:
        print(f"  [PAPER] {side_str} {contracts} {coin} @ ${price:.4f} "
              f"(notional ${notional:.2f})", flush=True)
        return 999999, "paper"

    _ensure_leverage(coin)
    signed = he._build_and_sign_order(coin, is_buy, contracts, price, tif=tif)

    statuses = signed.get("response", {}).get("data", {}).get("statuses", [])
    for s in statuses:
        if "resting" in s:
            oid = s["resting"]["oid"]
            return oid, f"resting OID {oid}"
        if "filled" in s:
            oid = s["filled"].get("oid", 0)
            avg_px = s["filled"].get("avgPx", price)
            return oid, f"filled @ ${avg_px} OID {oid} (taker)"
        if "error" in s:
            return None, f"error: {s['error']}"
    return None, f"unknown: {signed}"


def place_market_entry(coin: str, direction: str, contracts: float) -> tuple[int | None, str]:
    """Place a MARKET entry order using IoC (Immediate-or-Cancel). Returns (order_id, status_message).

    Dla skalpa wazniejsza jest natychmiastowa egzekucja niz ~$0.003
    oszczednosci na fee (maker 0.003% vs taker 0.009%).

    HL SDK nie ma typu 'market' — IoC z szerokim limitem dziala jak market.
    Uzywamy 0.5% slippage buffer jako limit price.
    """
    is_buy = direction == "long"
    side_str = "LONG" if is_buy else "SHORT"

    if contracts <= 0:
        return None, f"Invalid size {contracts}"

    mids = get_mids([coin])
    price = mids.get(coin, 0)
    if not price:
        return None, f"Cannot get price for {coin}"
    notional = contracts * price
    if notional > he.MAX_ORDER_USDC:
        return None, f"Notional ${notional:.2f} > MAX_ORDER_USDC ${he.MAX_ORDER_USDC}"

    if PAPER_MODE:
        print(f"  [PAPER] MARKET {side_str} {contracts} {coin} "
              f"(notional ${notional:.2f})", flush=True)
        return 999999, "paper"

    _ensure_leverage(coin)

    # IoC z slippage buffer: LONG = price * 1.005, SHORT = price * 0.995
    SLIPPAGE = 0.005  # 0.5%
    if is_buy:
        limit_price = round_price(coin, price * (1 + SLIPPAGE))
    else:
        limit_price = round_price(coin, price * (1 - SLIPPAGE))

    signed = he._build_and_sign_order(coin, is_buy, contracts, limit_price, tif="Ioc")

    statuses = signed.get("response", {}).get("data", {}).get("statuses", [])
    for s in statuses:
        if "filled" in s:
            oid = s["filled"].get("oid", 0)
            avg_px = s["filled"].get("avgPx", 0)
            return oid, f"filled @ ${avg_px} OID {oid} (market)"
        if "error" in s:
            return None, f"market error: {s['error']}"
    return None, f"market unknown: {signed}"


def place_hybrid_entry(coin: str, direction: str, contracts: float,
                       notional_usd: float = DEFAULT_SIZE_USD) -> tuple[int | None, str]:
    """Hybrid entry: próbuje LIMIT przy mid (maker fee 0.03%), 200ms timeout.
    Jeśli się nie wypełni → anuluje i wchodzi MARKET (taker fee 0.09%).
    """
    is_buy = direction == "long"
    mids = get_mids([coin])
    price = mids.get(coin, 0)
    if not price:
        return None, "Cannot get price"

    entry_price = round_price(coin, price)

    # Krok 1: spróbuj LIMIT przy mid (szansa na maker fee)
    oid, msg = place_limit_entry(coin, direction, contracts, entry_price, tif="Alo")
    if oid is None:
        # Limit failed outright → market
        return place_market_entry(coin, direction, contracts)

    # Krok 2: czekaj 200ms na wypełnienie
    import time as _time
    _time.sleep(0.2)

    positions = get_open_positions()
    has_pos = any(p["coin"] == coin and abs(p["entry"] - entry_price) / max(entry_price, 0.01) < 0.02
                  for p in positions)

    if has_pos:
        # Limit fill jako maker — sukces!
        return oid, f"filled as maker @ ${entry_price} OID {oid}"

    # Krok 3: limit nie wypełniony → anuluj + market
    try:
        he._cancel_order(coin, oid)
    except Exception:
        pass
    _time.sleep(0.05)
    return place_market_entry(coin, direction, contracts)


def place_tp_limit(coin: str, direction: str, contracts: float,
                   entry_price: float, tp_pct: float = TP_PCT) -> tuple[int | None, str]:
    """Place a limit take-profit order. ALWAYS reduce_only=True."""
    is_buy = direction == "long"
    if is_buy:
        # Long → sell for TP (higher price)
        tp_price = round_price(coin, entry_price * (1 + tp_pct / 100))
        reduce_buy = False
    else:
        # Short → buy back for TP (lower price)
        tp_price = round_price(coin, entry_price * (1 - tp_pct / 100))
        reduce_buy = True

    if PAPER_MODE:
        print(f"  [PAPER] TP {direction} {contracts} {coin} @ ${tp_price:.4f}", flush=True)
        return 999998, "paper"

    signed = he._build_and_sign_order(coin, reduce_buy, contracts, tp_price,
                                      tif="Gtc", reduce_only=True)
    statuses = signed.get("response", {}).get("data", {}).get("statuses", [])
    for s in statuses:
        if "resting" in s:
            return s["resting"]["oid"], f"TP resting OID {s['resting']['oid']}"
        if "filled" in s:
            return None, f"TP filled immediately — {s['filled']}"
        if "error" in s:
            return None, f"TP error: {s['error']}"
    return None, f"TP unknown: {signed}"


def place_sl_trigger(coin: str, direction: str, contracts: float,
                     entry_price: float, sl_pct: float = SL_PCT) -> tuple[int | None, str]:
    """Place a stop-market SL order. reduce_only=True."""
    is_buy = direction == "long"
    if is_buy:
        sl_price = round_price(coin, entry_price * (1 - sl_pct / 100))
        reduce_buy = False  # sell to stop out
    else:
        sl_price = round_price(coin, entry_price * (1 + sl_pct / 100))
        reduce_buy = True   # buy to stop out

    if PAPER_MODE:
        print(f"  [PAPER] SL {direction} {contracts} {coin} @ ${sl_price:.4f}", flush=True)
        return 999997, "paper"

    signed = he._build_and_sign_sl_order(coin, reduce_buy, contracts, sl_price, tpsl="sl")
    statuses = signed.get("response", {}).get("data", {}).get("statuses", [])
    for s in statuses:
        if "resting" in s:
            return s["resting"]["oid"], f"SL resting OID {s['resting']['oid']}"
        if "filled" in s:
            return None, f"SL filled immediately — {s['filled']}"
        if "error" in s:
            return None, f"SL error: {s['error']}"
    return None, f"SL unknown: {signed}"


# ── Trade lifecycle ───────────────────────────────────────────────────────────

def execute_scalp(coin: str, direction: str,
                  notional_usd: float = DEFAULT_SIZE_USD,
                  leverage: int = DEFAULT_LEVERAGE,
                  tp_pct: float = TP_PCT,
                  sl_pct: float = SL_PCT,
                  correlation_pair: str | None = None,
                  confidence: int | None = None,
                  driver: str | None = None,
                  driver_mom: float | None = None,
                  laggard_mom: float | None = None) -> dict:
    """Execute a complete scalp: limit entry → TP/SL → track.

    Returns trade dict with result.
    """
    if coin not in TRADEABLE_XYZ:
        return {"error": f"{coin} not in tradeable set"}

    # Get current price
    mids = get_mids([coin])
    price = mids.get(coin, 0)
    if not price:
        return {"error": f"Cannot get price for {coin}"}

    # Market entry: uzywamy mid price, natychmiastowa egzekucja
    entry_price = round_price(coin, price)

    contracts = calc_contracts(coin, notional_usd, entry_price)
    if contracts <= 0:
        return {"error": f"Contracts too small ({contracts})"}

    actual_notional = contracts * entry_price

    print(f"\n{'='*50}", flush=True)
    print(f"SCALP: {direction.upper()} {coin}", flush=True)
    print(f"  Entry:   ${entry_price:.4f} (hybrid, maker→market)", flush=True)
    print(f"  Size:    {contracts} contracts (~${actual_notional:.2f})", flush=True)
    print(f"  Leverage: {leverage}x", flush=True)
    print(f"  TP:      {tp_pct:+.2f}%", flush=True)
    print(f"  SL:      {sl_pct:+.2f}%", flush=True)
    print(f"  Mode:    {'PAPER' if PAPER_MODE else 'LIVE'}", flush=True)
    print(f"  Pair:    {correlation_pair or 'manual'}", flush=True)

    # Save to DB immediately
    trade = {
        "instrument": coin,
        "side": direction.upper(),
        "entry_price": entry_price,
        "size_contracts": contracts,
        "notional_usd": actual_notional,
        "leverage": leverage,
        "correlation_pair": correlation_pair,
        "confidence": confidence,
        "driver": driver,
        "laggard": coin,
        "driver_mom_5s": driver_mom,
        "laggard_mom_5s": laggard_mom,
    }
    trade_id = _db.save_scalp_trade(trade)

    # Place hybrid entry (limit mid 200ms, fallback market)
    oid, msg = place_hybrid_entry(coin, direction, contracts)
    if oid is None:
        _db.close_scalp_trade(trade_id, entry_price, 0, 0, exit_reason=msg)
        return {"error": f"Entry failed: {msg}", "trade_id": trade_id}

    print(f"  → Entry: {msg}", flush=True)

    # TP/SL: kładziemy OD RAZU po fillu (pozycja juz istnieje)
    if PAPER_MODE:
        tp_oid, tp_msg = place_tp_limit(coin, direction, contracts, entry_price, tp_pct)
        sl_oid, sl_msg = place_sl_trigger(coin, direction, contracts, entry_price, sl_pct)
        print(f"  → TP:    {tp_msg}", flush=True)
        print(f"  → SL:    {sl_msg}", flush=True)
    else:
        # Zaktualizuj DB z realnej ceny entry z HL fill
        wallet = os.getenv("HL_MAIN_WALLET_ADDRESS", "")
        _update_entry_from_fills(trade_id, coin, wallet)

        tp_oid, tp_msg = place_tp_limit(coin, direction, contracts, entry_price, tp_pct)
        sl_oid, sl_msg = place_sl_trigger(coin, direction, contracts, entry_price, sl_pct)
        print(f"  → TP:    {tp_msg}", flush=True)
        print(f"  → SL:    {sl_msg}", flush=True)

        # Jeśli reduce-only rejected (bardzo rzadkie z market entry), szybki retry
        if "error" in str(tp_msg).lower() or "error" in str(sl_msg).lower():
            print(f"  ⏳ TP/SL deferred (retry co ~1s w live_loop)", flush=True)
            he._pending_tpsl.append({
                "trade_id": trade_id, "coin": coin, "direction": direction,
                "contracts": contracts, "entry_price": entry_price,
                "tp_pct": tp_pct, "sl_pct": sl_pct,
            })

    if PAPER_MODE:
        # Simulate fill for paper
        _simulate_paper_fill(trade_id, coin, direction, entry_price, contracts,
                             actual_notional, leverage, tp_pct, sl_pct)

    return {
        "trade_id": trade_id,
        "status": "open",
        "instrument": coin,
        "direction": direction,
        "entry_price": entry_price,
        "contracts": contracts,
        "notional": actual_notional,
        "entry_oid": oid,
    }


def _simulate_paper_fill(trade_id: int, coin: str, direction: str,
                         entry_price: float, contracts: float,
                         notional: float, leverage: int,
                         tp_pct: float, sl_pct: float) -> None:
    """Simulate scalp result in paper mode — REALISTYCZNY model.

    Zamiast 100% TP: losuje czy entry się wypełnił, czy SL trafił,
    czy zszedł slippage. To daje realne ~65-75% WR zamiast 100%.
    """
    import random
    random.seed()

    is_long = direction == "long"
    MAKER_FEE = 0.00003       # 0.003%
    SLIPPAGE_TP = 0.0001      # 0.01% slippage na TP (nie zawsze idealny exit)
    ENTRY_FILL_RATE = 0.70    # 70% szansy że limit entry faktycznie dostanie fill
    SL_HIT_RATE = 0.15        # 15% szans że SL trafi zamiast TP (market noise)

    # ── Krok 1: czy limit entry w ogóle się wypełnił? ──
    if random.random() > ENTRY_FILL_RATE:
        entry_fee = notional * MAKER_FEE
        _db.close_scalp_trade(
            trade_id, entry_price, 0, 0,
            entry_fee=round(entry_fee, 4), exit_fee=0,
            exit_reason="no_fill",
        )
        print(f"\n  [PAPER] ❌ Limit nie wypełniony (fill_rate={ENTRY_FILL_RATE*100:.0f}%)", flush=True)
        print(f"  [PAPER] Fee: ${entry_fee:.4f}", flush=True)
        print(f"{'='*50}\n", flush=True)
        return

    # ── Krok 2: spread cost (nie zawsze łapiemy idealny bid) ──
    spread_cost = entry_price * 0.0001  # 0.01% na wejściu (połowa spreadu)
    if is_long:
        real_entry = entry_price + spread_cost
    else:
        real_entry = entry_price - spread_cost

    entry_fee = real_entry * contracts * MAKER_FEE

    # ── Krok 3: TP vs SL (losujemy czy SL trafi) ──
    sl_hit = random.random() < SL_HIT_RATE

    if is_long:
        tp_raw = real_entry * (1 + tp_pct / 100)
        sl_raw = real_entry * (1 - sl_pct / 100)
        if sl_hit:
            exit_price = sl_raw
            pnl_usd = (sl_raw - real_entry) * contracts * leverage
            exit_reason = "paper_sl"
        else:
            # Slippage na TP
            tp_slipped = tp_raw * (1 - SLIPPAGE_TP)
            exit_price = tp_slipped
            pnl_usd = (tp_slipped - real_entry) * contracts * leverage
            exit_reason = "paper_tp"
    else:
        tp_raw = real_entry * (1 - tp_pct / 100)
        sl_raw = real_entry * (1 + sl_pct / 100)
        if sl_hit:
            exit_price = sl_raw
            pnl_usd = (real_entry - sl_raw) * contracts * leverage
            exit_reason = "paper_sl"
        else:
            tp_slipped = tp_raw * (1 + SLIPPAGE_TP)
            exit_price = tp_slipped
            pnl_usd = (real_entry - tp_slipped) * contracts * leverage
            exit_reason = "paper_tp"

    exit_fee = exit_price * contracts * MAKER_FEE
    pnl_pct = (pnl_usd / (real_entry * contracts)) * 100

    _db.close_scalp_trade(
        trade_id, round(exit_price, 4), round(pnl_usd, 2), round(pnl_pct, 2),
        entry_fee=round(entry_fee, 4), exit_fee=round(exit_fee, 4),
        exit_reason=exit_reason,
    )

    result_icon = "🟢" if pnl_usd > 0 else "🔴"
    print(f"\n  [PAPER RESULT] {result_icon} {exit_reason}: ${pnl_usd:.2f} ({pnl_pct:.2f}%)", flush=True)
    print(f"  [PAPER FEES]   entry ${entry_fee:.4f} + exit ${exit_fee:.4f} = ${entry_fee+exit_fee:.4f}", flush=True)
    print(f"  [PAPER NET]    ${pnl_usd - entry_fee - exit_fee:.2f}", flush=True)
    print(f"{'='*50}\n", flush=True)


# ── Monitoring ────────────────────────────────────────────────────────────────

def get_open_positions() -> list[dict]:
    """Get current HL perp positions across all coins."""
    wallet = os.getenv("HL_MAIN_WALLET_ADDRESS", "")
    state = he._post({"type": "clearinghouseState", "user": wallet, "dex": XYZ_DEX})
    positions = state.get("assetPositions", [])
    result = []
    for p in positions:
        pos = p.get("position", {})
        szi = Decimal(pos.get("szi", "0"))
        if szi == 0:
            continue
        result.append({
            "coin": pos.get("coin", "?"),
            "side": "LONG" if szi > 0 else "SHORT",
            "size": float(szi),
            "entry": float(pos.get("entryPx", 0)),
            "upnl": float(pos.get("unrealizedPnl", 0)),
            "leverage": pos.get("leverage", {}).get("value", "?"),
        })
    return result


def get_open_orders() -> list[dict]:
    """Get current resting (non-filled) orders on HL xyz DEX."""
    wallet = os.getenv("HL_MAIN_WALLET_ADDRESS", "")
    try:
        state = he._post({"type": "frontendOpenOrders", "user": wallet})
        orders = state if isinstance(state, list) else state.get("orders", [])
        result = []
        for o in orders:
            oid = o.get("oid", 0)
            coin = o.get("coin", "?")
            szi = float(o.get("sz", 0))
            px = float(o.get("limitPx", 0))
            side = "BUY" if szi > 0 else "SELL"
            reduce = o.get("reduceOnly", False)
            result.append({
                "oid": oid, "coin": coin, "side": side,
                "size": abs(szi), "price": px,
                "reduce_only": reduce,
            })
        return result
    except Exception as e:
        print(f"  [WARN] get_open_orders: {e}", flush=True)
        return []


# ── Fill tracking ─────────────────────────────────────────────────────────────

TAKER_FEE_RATE = 0.0009    # 0.09% taker (market entry) — potwierdzone z HL fill data
MAKER_FEE_RATE = 0.0003    # 0.03% maker (limit TP/SL) — potwierdzone z HL fill data


def _get_user_fills_since(wallet: str, since_ms: int) -> list[dict]:
    """Fetch fills from HL userFillsByTime endpoint.

    Returns raw fill dicts from HL API, each containing:
    - coin, px, sz, side (A=ask/sell, B=bid/buy)
    - dir (e.g. 'Open Long', 'Close Long', 'Open Short', 'Close Short')
    - closedPnl (realized PnL for that fill)
    - fee, oid, hash, time (ms)
    """
    try:
        raw = he._post({
            "type": "userFillsByTime",
            "user": wallet,
            "startTime": since_ms,
        })
        if isinstance(raw, list):
            return raw
        return []
    except Exception as e:
        print(f"  [WARN] _get_user_fills_since: {e}", flush=True)
        return []


def _update_entry_from_fills(trade_id: int, coin: str, wallet: str) -> None:
    """Query HL fills after market entry and update DB with real entry data."""
    import time as _time
    now_ms = int(_time.time() * 1000)
    fills = _get_user_fills_since(wallet, now_ms - 10_000)  # last 10s
    # Find first fill that opened a position in this coin
    for f in fills:
        if f.get("coin") == coin and "Open" in str(f.get("dir", "")):
            real_px = float(f["px"])
            real_fee = float(f["fee"])
            real_sz = float(f["sz"])
            _db._sqlite.execute(
                "UPDATE scalp_trades SET entry_price=?, entry_fee=?, "
                "size_contracts=? WHERE id=?",
                (round(real_px, 4), round(real_fee, 6), real_sz, trade_id),
            )
            print(f"  [FILL] Entry update #{trade_id}: ${real_px} sz={real_sz} fee=${real_fee:.6f}",
                  flush=True)
            return
    # If fills not yet indexed, try once more after short delay
    _time.sleep(0.5)
    fills = _get_user_fills_since(wallet, now_ms - 10_000)
    for f in fills:
        if f.get("coin") == coin:
            # Broader match: any fill matching our coin in the right direction
            real_px = float(f["px"])
            real_fee = float(f["fee"])
            _db._sqlite.execute(
                "UPDATE scalp_trades SET entry_price=?, entry_fee=? WHERE id=?",
                (round(real_px, 4), round(real_fee, 6), trade_id),
            )
            print(f"  [FILL] Entry update #{trade_id} (delayed): ${real_px} fee=${real_fee:.6f}",
                  flush=True)
            return
    print(f"  [FILL] No entry fill found for #{trade_id} yet", flush=True)


def _close_trade_from_fills(trade_id: int, coin: str, wallet: str,
                            side: str, entry_price: float) -> None:
    """Query HL fills and close the DB trade with real PnL from exchange."""
    import time as _time
    # Get ts_open from DB for the start time
    t_open = _db._sqlite.query(
        "SELECT ts_open FROM scalp_trades WHERE id=?", (trade_id,)
    )
    if not t_open:
        return
    try:
        t0 = t_open[0]["ts_open"]
        if t0:
            dt = __import__("datetime", fromlist=["datetime"]).datetime
            ts_ms = int(dt.fromisoformat(t0).timestamp() * 1000)
        else:
            ts_ms = int(_time.time() * 1000) - 3600_000  # fallback: 1h ago
    except Exception:
        ts_ms = int(_time.time() * 1000) - 3600_000

    fills = _get_user_fills_since(wallet, ts_ms)
    # Find close fill: dir='Close Long' or 'Close Short', matching our coin+side
    close_dir = f"Close {side.title()}"  # "Close Long" or "Close Short"
    for f in fills:
        if f.get("coin") == coin and f.get("dir") == close_dir:
            exit_px = float(f["px"])
            closed_pnl = float(f.get("closedPnl", 0))
            exit_fee = float(f.get("fee", 0))
            fill_time_ms = f.get("time", 0)
            # Convert fill timestamp (ms) to ISO datetime
            if fill_time_ms:
                dt_close = __import__("datetime", fromlist=["datetime"]).datetime.fromtimestamp(
                    fill_time_ms / 1000, tz=__import__("datetime", fromlist=["timezone"]).timezone.utc
                ).isoformat()[:19]
            else:
                dt_close = None
            pnl_pct = (closed_pnl / (entry_price * float(f["sz"]))) * 100 if entry_price else 0
            _db.close_scalp_trade(
                trade_id, exit_px, closed_pnl, round(pnl_pct, 2),
                exit_fee=round(exit_fee, 6),
                exit_reason="filled_tp" if closed_pnl > 0 else "live_sl",
                ts_close=dt_close,
            )
            print(f"  [FILL] #{trade_id} closed: ${exit_px} PnL=${closed_pnl:.2f} "
                  f"({pnl_pct:+.2f}%) fee=${exit_fee:.6f}", flush=True)
            return

    # No close fill found yet — mark as hl_closed anyway (will retry next iter)
    print(f"  [FILL] No close fill for #{trade_id} yet (still indexing?), marking hl_closed",
          flush=True)
    _db.close_scalp_trade(trade_id, 0, 0, 0, exit_reason="hl_closed")


# ── Live auto-trader ──────────────────────────────────────────────────────────

def live_loop() -> None:
    """Continuous signal-driven auto-trader.

    Runs scanner in background thread (fills ring buffer),
    then evaluates correlation pairs every 1s.
    On a signal with confidence >= 7, executes a scalp.
    """
    import threading
    from correlation_scalp import evaluate_pairs

    # Start scanner in background thread
    _scanner_stop = threading.Event()

    def _scanner_thread():
        from xyz_scanner import snapshot as sc_snapshot
        import httpx, ssl, truststore
        _ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with httpx.Client(verify=_ssl_ctx, timeout=10) as client:
            # Warm up: fill buffer with ~5s of data before starting signals
            for _ in range(20):
                if _scanner_stop.is_set():
                    return
                sc_snapshot(client)
                time.sleep(0.25)
            # Continuous scan
            while not _scanner_stop.is_set():
                sc_snapshot(client)
                time.sleep(0.25)

    t = threading.Thread(target=_scanner_thread, daemon=True)
    t.start()
    time.sleep(2)  # let scanner warm up before first signal check

    running = True
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    print(f"\n{'='*55}", flush=True)
    print(f"  HL XYZ SCALP — LIVE AUTO-TRADER", flush=True)
    print(f"  Mode: {'PAPER' if PAPER_MODE else 'LIVE 🔴'}", flush=True)
    print(f"  Instruments: {', '.join(sorted(TRADEABLE_XYZ))}", flush=True)
    print(f"  Size: ${DEFAULT_SIZE_USD} | Lev: {DEFAULT_LEVERAGE}x", flush=True)
    print(f"  TP: {TP_PCT}% | SL: {SL_PCT}%", flush=True)
    print(f"  Max positions: {MAX_POSITIONS} | Max trades/day: {MAX_TRADE_DAILY}", flush=True)
    print(f"{'='*55}\n", flush=True)

    # ── Cooldown tracking ──
    _pair_executed: dict[str, float] = {}      # stable_key → timestamp
    _pair_direction: dict[str, str] = {}       # stable_key → last direction (long/short)
    _last_print_key: str = ""
    _repeat_count = 0
    COOLDOWN_SAME_DIR  = 300  # 5 min — ten sam kierunek, nie wchodź ponownie
    COOLDOWN_REVERSAL  = 120  # 2 min — zmiana kierunku (reversal trade)

    # ── Retry pending TP/SL every iteration (priority, przed sygnałami) ──
    def _retry_pending_tpsl() -> None:
        """Sprawdza pending TP/SL i próbuje złożyć jeśli pozycja już na HL."""
        if PAPER_MODE or not he._pending_tpsl:
            return
        try:
            positions = get_open_positions()
            retry_list = list(he._pending_tpsl)
            he._pending_tpsl = []
            for pend in retry_list:
                has_pos = any(p["coin"] == pend["coin"] for p in positions)
                if has_pos:
                    tp_oid, tp_msg = place_tp_limit(
                        pend["coin"], pend["direction"],
                        pend["contracts"], pend["entry_price"], pend["tp_pct"])
                    sl_oid, sl_msg = place_sl_trigger(
                        pend["coin"], pend["direction"],
                        pend["contracts"], pend["entry_price"], pend["sl_pct"])
                    ok = ("error" not in str(tp_msg).lower() and "error" not in str(sl_msg).lower())
                    if ok:
                        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                              f"✅ TP/SL placed (deferred) for trade #{pend['trade_id']}", flush=True)
                    else:
                        # One failed again — retry next iteration
                        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                              f"⚠️ TP/SL retry failed (#{pend['trade_id']}): "
                              f"TP={str(tp_msg)[:40]} SL={str(sl_msg)[:40]}", flush=True)
                        he._pending_tpsl.append(pend)
                else:
                    he._pending_tpsl.append(pend)
        except Exception:
            # Jeśli coś padło, dodaj z powrotem — nie trać pend
            he._pending_tpsl.extend(retry_list)

    while running:
        try:
            _retry_pending_tpsl()

            signals = evaluate_pairs()
            tradable_signals = [
                s for s in signals
                if s["laggard"] in TRADEABLE_XYZ
            ]

            if tradable_signals:
                tradable_signals.sort(key=lambda s: -s["confidence"])
                best = tradable_signals[0]

                if best["confidence"] < 8:
                    time.sleep(1)
                    continue

                coin = best["laggard"]
                stable = f"{best['driver']}|{coin}"   # e.g. "xyz:CL|xyz:GOLD"
                now_t = time.time()

                # ── Step 1: Cooldown check (time-based, beats direction flips) ──
                if stable in _pair_executed:
                    last_dir = _pair_direction.get(stable, "")
                    same_dir = (best["direction"] == last_dir)
                    cooldown = COOLDOWN_SAME_DIR if same_dir else COOLDOWN_REVERSAL
                    expires = _pair_executed[stable] + cooldown
                    if now_t < expires:
                        if stable != _last_print_key:
                            _last_print_key = stable
                            _repeat_count = 0
                        _repeat_count += 1
                        dir_label = "↔ ten sam kier." if same_dir else "↕ reversal"
                        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                              f"⌛ Cooldown ({dir_label}) {stable} — jeszcze {expires-now_t:.0f}s "
                              f"(x{_repeat_count}) [{best['pair_note']}]", flush=True)
                        time.sleep(1)
                        continue

                # ── Step 2: Cooldown expired → proceed ──
                _last_print_key = ""
                _repeat_count = 0
                # ── Poll open positions for live trades ──
                open_positions = []
                has_position = False
                if not PAPER_MODE:
                    try:
                        open_positions = get_open_positions()
                        # Check if any DB-open trades need closing
                        db_open = _db._sqlite.query(
                            "SELECT id, instrument, entry_price FROM scalp_trades "
                            "WHERE status='open' AND exit_reason IS NULL"
                        )
                        # Also retry hl_closed trades that have no PnL yet (fills might not have been indexed)
                        db_retry = _db._sqlite.query(
                            "SELECT id, instrument, entry_price FROM scalp_trades "
                            "WHERE status='closed' AND exit_reason='hl_closed' "
                            "AND COALESCE(pnl_usd,0)=0"
                        )
                        db_open.extend(db_retry)
                        for t in db_open:
                            still_has = any(
                                p["coin"] == t["instrument"] for p in open_positions
                            )
                            if not still_has:
                                # Pobierz realne dane exit z HL fill
                                coin_name = t["instrument"]
                                side_q = _db._sqlite.query(
                                    "SELECT side FROM scalp_trades WHERE id=?",
                                    (t["id"],)
                                )
                                side_str = side_q[0]["side"].lower() if side_q else "long"
                                entry = t.get("entry_price", 0) or 0
                                _close_trade_from_fills(
                                    t["id"], coin_name, wallet,
                                    side_str, entry,
                                )

                        has_position = len(open_positions) >= MAX_POSITIONS

                    except Exception:
                        pass

                    if has_position:
                        for p in open_positions:
                            icon = "🟢" if p["upnl"] >= 0 else "🔴"
                            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                                  f"⏳ POS: {icon} {p['side']} {p['coin']} "
                                  f"@ ${p['entry']:.2f} uPnL ${p['upnl']:.2f}", flush=True)
                        time.sleep(2)
                        continue

                # ── Check daily trade count ──
                stats = _db.get_scalp_stats()
                total = stats.get("total_trades", 0) or 0
                if total >= MAX_TRADE_DAILY:
                    print(f"[LIMIT] {total} trades today — max {MAX_TRADE_DAILY}", flush=True)
                    time.sleep(10)
                    continue

                # ── Execute ──
                print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] "
                      f"[SIGNAL] C={best['confidence']}/10 — {best['pair_note']}", flush=True)
                result = execute_scalp(
                    coin, best["direction"],
                    correlation_pair=best["pair_note"],
                    confidence=best["confidence"],
                    driver=best["driver"],
                    driver_mom=best.get("driver_mom_5s"),
                    laggard_mom=best.get("laggard_mom_5s"),
                )
                if "error" not in result:
                    _pair_executed[stable] = now_t  # start cooldown
                    _pair_direction[stable] = best["direction"]  # remember direction
                else:
                    print(f"  [SKIP] {result['error']}", flush=True)

            elif _repeat_count > 0:
                _last_print_key = ""
                _repeat_count = 0

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            import traceback
            traceback.print_exc()

        time.sleep(0.5)

    print("\n[stopped]", flush=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_status() -> None:
    """Show current HL positions + scalping stats."""
    positions = get_open_positions()
    stats = _db.get_scalp_stats()

    print(f"\n{'='*45}", flush=True)
    print(f"  SCALP STATUS", flush=True)
    print(f"  Mode: {'PAPER' if PAPER_MODE else 'LIVE'}", flush=True)
    print(f"{'='*45}", flush=True)

    print(f"\n📊 Open positions:")
    if not positions:
        print("  (none)", flush=True)
    else:
        for p in positions:
            uc = "🟢" if p["upnl"] >= 0 else "🔴"
            print(f"  {uc} {p['side']} {p['coin']} | {p['size']} @ ${p['entry']:.2f} "
                  f"| uPnL ${p['upnl']:.2f}", flush=True)

    print(f"\n📈 Scalping stats:", flush=True)
    t = stats.get("total_trades", 0)
    w = stats.get("wins", 0)
    l = stats.get("losses", 0)
    wr = stats.get("win_rate", 0)
    pnl = stats.get("total_pnl", 0)
    avg = stats.get("avg_pnl", 0)
    hold = stats.get("avg_hold_s", 0)
    fee = stats.get("avg_fee", 0)
    print(f"  Trades: {t} | W: {w} | L: {l} | WR: {wr}%", flush=True)
    print(f"  PnL: ${pnl} | Avg: ${avg:.2f}/trade | Avg hold: {hold:.0f}s", flush=True)
    print(f"  Avg fee: ${fee:.4f}/trade", flush=True)
    print(flush=True)


def cmd_trade(coin: str, direction: str) -> None:
    """Manual single scalp trade."""
    full_name = f"xyz:{coin.upper()}" if not coin.startswith("xyz:") else coin.upper()
    if full_name not in TRADEABLE_XYZ:
        available = ", ".join(sorted(TRADEABLE_XYZ))
        print(f"Unsupported. Tradeable: {available}")
        sys.exit(1)

    execute_scalp(full_name, direction)


def cmd_stats() -> None:
    """Detailed scalping analytics."""
    stats = _db.get_scalp_stats()
    print(json.dumps(stats, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="HL xyz scalp executor")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="current positions + stats")
    sub.add_parser("stats", help="detailed scalping stats")

    trade_p = sub.add_parser("trade", help="manual scalp trade")
    trade_p.add_argument("coin", help="e.g. GOLD, SILVER, SP500, CL")
    trade_p.add_argument("direction", choices=["long", "short"])

    sub.add_parser("live", help="signal-driven auto-trader")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "trade":
        cmd_trade(args.coin, args.direction)
    elif args.command == "live":
        live_loop()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()