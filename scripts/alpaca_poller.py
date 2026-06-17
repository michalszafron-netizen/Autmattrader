"""Alpaca Order Fill Poller — uruchamiany co 1h przez cron na VPS.

Dla każdego otwartego bracket-entry z alerts.jsonl odpytuje Alpaca API
o status zleceń i dopisuje zdarzenia tp_hit / sl_hit / closed.

Cron (VPS): 0 * * * * /trading-ai/.venv/bin/python /trading-ai/scripts/alpaca_poller.py >> /trading-ai/logs/alpaca_poller.log 2>&1
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT        = Path(__file__).parent.parent
ALERTS_FILE = ROOT / "alerts.jsonl"
load_dotenv(ROOT / ".env")

ALPACA_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_API_SECRET", "")
BASE_URL      = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

if not ALPACA_KEY or not ALPACA_SECRET:
    print("ERROR: ALPACA_API_KEY / ALPACA_API_SECRET not set", flush=True)
    sys.exit(1)


def alpaca_get(path: str) -> list | dict:
    import urllib.request
    url = BASE_URL.rstrip("/") + path
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID":     ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def load_tracked_entries() -> list[dict]:
    """Load executed entry alerts that have alpaca_order_id and no fill_event yet."""
    if not ALERTS_FILE.exists():
        return []

    lines = ALERTS_FILE.read_text(encoding="utf-8").splitlines()
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except Exception:
            pass

    # IDs already resolved by a fill_event
    resolved = {r["parent_order_id"] for r in records
                if r.get("fill_event") and r.get("parent_order_id")}

    entries = []
    for r in records:
        oid = r.get("alpaca_order_id") or r.get("order_id")
        if not oid:
            continue
        if r.get("status") not in ("executed",):
            continue
        if r.get("fill_event"):
            continue
        # Only entry sides (not close signals)
        side = (r.get("side") or "").lower()
        if side not in ("buy", "long", "sell", "short"):
            continue
        if oid in resolved:
            continue
        entries.append(r)

    return entries


def log_fill_event(parent_order_id: str, fill_type: str, filled_price: float,
                   qty: float, symbol: str, filled_at: str, leg_order_id: str) -> None:
    record = {
        "received_at":     datetime.now(timezone.utc).isoformat(),
        "fill_event":      True,
        "fill_type":       fill_type,        # tp_hit | sl_hit | closed
        "parent_order_id": parent_order_id,
        "symbol":          symbol,
        "filled_price":    filled_price,
        "qty":             qty,
        "filled_at":       filled_at,
        "order_id":        leg_order_id,
    }
    with open(ALERTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    print(f"[poller] {fill_type}: {symbol} @ {filled_price} (qty={qty})", flush=True)


def check_bracket_order(entry: dict) -> bool:
    """Fetch bracket order from Alpaca, check if TP or SL leg filled. Returns True if resolved."""
    oid    = entry.get("alpaca_order_id") or entry.get("order_id")
    symbol = (entry.get("symbol") or "").upper()

    try:
        order = alpaca_get(f"/v2/orders/{oid}")
    except Exception as e:
        print(f"[poller] ERROR fetching order {oid[:8]}...: {e}", flush=True)
        return False

    status = order.get("status", "")
    legs   = order.get("legs") or []

    # Check if any leg is filled
    for leg in legs:
        leg_status = leg.get("status", "")
        if leg_status != "filled":
            continue

        filled_price = float(leg.get("filled_avg_price") or 0)
        qty          = float(leg.get("filled_qty") or leg.get("qty") or 0)
        filled_at    = leg.get("filled_at") or leg.get("updated_at") or ""
        leg_type     = leg.get("order_type", "").lower()
        leg_side     = leg.get("side", "").lower()
        entry_side   = (entry.get("side") or "").lower()

        # TP leg: limit order on opposite side to entry
        if leg_type in ("limit", "take_profit") and leg_side != entry_side:
            log_fill_event(oid, "tp_hit", filled_price, qty, symbol, filled_at, leg.get("id",""))
            return True
        # SL leg: stop or stop_limit on opposite side to entry
        if leg_type in ("stop", "stop_limit", "trailing_stop") and leg_side != entry_side:
            log_fill_event(oid, "sl_hit", filled_price, qty, symbol, filled_at, leg.get("id",""))
            return True

    # If parent itself is closed with no legs (direct fill or manual close)
    if status in ("filled", "closed") and not legs:
        filled_price = float(order.get("filled_avg_price") or 0)
        qty          = float(order.get("filled_qty") or order.get("qty") or 0)
        filled_at    = order.get("filled_at") or ""
        log_fill_event(oid, "closed", filled_price, qty, symbol, filled_at, oid)
        return True

    return False


def main():
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[poller] {ts} — Alpaca fill check started", flush=True)

    entries = load_tracked_entries()
    if not entries:
        print("[poller] No open tracked Alpaca orders. Done.", flush=True)
        return

    print(f"[poller] Checking {len(entries)} open order(s)...", flush=True)
    resolved = 0
    for entry in entries:
        oid = entry.get("alpaca_order_id") or entry.get("order_id","")
        print(f"[poller]   {entry.get('symbol','')} {entry.get('side','')} OID={oid[:8]}...", flush=True)
        if check_bracket_order(entry):
            resolved += 1

    print(f"[poller] Done. Resolved {resolved}/{len(entries)} order(s).", flush=True)


if __name__ == "__main__":
    main()
