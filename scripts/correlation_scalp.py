"""correlation_scalp.py — Cross-market correlation engine for HL xyz scalping.

Reads ring buffer from xyz_scanner, detects correlation lags,
emits scalp signals.

Usage:
    python scripts/correlation_scalp.py              # single scan, print signals
    python scripts/correlation_scalp.py --daemon     # continuous loop
    python scripts/correlation_scalp.py --once       # one-shot JSON
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
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
from xyz_scanner import TRADEABLE, SIGNAL, WATCH, snapshot, get_buffer, latest, momentum

# ── Correlation pairs ─────────────────────────────────────────────────────────
# Each pair defines:
#   driver    — instrument that moves FIRST (we watch this)
#   laggard   — instrument that moves SECOND (we scalp this)
#   direction — "same" (both up/down) or "inverse" (opposite)
#   corr      — expected correlation strength (0.0-1.0)
#   min_move  — minimum driver move in % to trigger signal

CORRELATIONS = [
    # ── DXY → GOLD (inverse, strongest) ──
    {"driver": "xyz:DXY", "laggard": "xyz:GOLD", "direction": "inverse",
     "corr": 0.80, "min_move": 0.02, "min_lag": 1.0, "max_lag": 5.0,
     "note": "DXY up → Gold down (inverse -0.8)"},

    # ── DXY → SILVER (inverse, strong) ──
    {"driver": "xyz:DXY", "laggard": "xyz:SILVER", "direction": "inverse",
     "corr": 0.70, "min_move": 0.02, "min_lag": 1.0, "max_lag": 5.0,
     "note": "DXY up → Silver down"},

    # ── SP500 → SILVER (same direction) ──
    {"driver": "xyz:SP500", "laggard": "xyz:SILVER", "direction": "same",
     "corr": 0.60, "min_move": 0.03, "min_lag": 2.0, "max_lag": 10.0,
     "note": "SP500 up → Silver up (industrial demand)"},

    # ── SP500 → CL (same direction) ──
    {"driver": "xyz:SP500", "laggard": "xyz:CL", "direction": "same",
     "corr": 0.40, "min_move": 0.04, "min_lag": 3.0, "max_lag": 15.0,
     "note": "SP500 up → Oil up (economic activity)"},

    # ── VIX → SP500 (inverse, fast) ──
    {"driver": "xyz:VIX", "laggard": "xyz:SP500", "direction": "inverse",
     "corr": 0.80, "min_move": 0.05, "min_lag": 0.5, "max_lag": 3.0,
     "note": "VIX up → SP500 down (fear indicator)"},

    # ── EUR → DXY → GOLD (double correlation chain) ──
    # EUR up → DXY down → GOLD up
    {"driver": "xyz:EUR", "laggard": "xyz:GOLD", "direction": "same",
     "corr": 0.60, "min_move": 0.015, "min_lag": 2.0, "max_lag": 8.0,
     "note": "EUR up → DXY down → Gold up (double chain)"},

    # ── CL (Oil) → GOLD (inflation hedge) ──
    {"driver": "xyz:CL", "laggard": "xyz:GOLD", "direction": "same",
     "corr": 0.50, "min_move": 0.05, "min_lag": 3.0, "max_lag": 10.0,
     "note": "Oil up → Gold up (inflation hedge)"},

    # ── EUR → SILVER (EUR aktywny 24/5, SILVER laggard) ──
    {"driver": "xyz:EUR", "laggard": "xyz:SILVER", "direction": "same",
     "corr": 0.55, "min_move": 0.015, "min_lag": 2.0, "max_lag": 8.0,
     "note": "EUR up → Silver up (weak USD)"},

    # ── CL (Oil) → SILVER (commodity bloc) ──
    {"driver": "xyz:CL", "laggard": "xyz:SILVER", "direction": "same",
     "corr": 0.45, "min_move": 0.05, "min_lag": 3.0, "max_lag": 10.0,
     "note": "Oil up → Silver up (commodities rally)"},
]


def evaluate_pairs() -> list[dict]:
    """Evaluate all correlation pairs. Return list of signals.

    Returns:
        Each signal: {
            "timestamp": float,
            "driver": str,
            "laggard": str,
            "direction": "long" | "short",
            "laggard_price": float,
            "driver_momentum_3s": float,
            "laggard_momentum_3s": float,
            "confidence": int,   # 1-10
            "pair_note": str,
        }
    """
    signals = []
    now = time.time()

    for pair in CORRELATIONS:
        d = pair["driver"]
        l = pair["laggard"]

        d_price = latest(d)
        l_price = latest(l)
        if not d_price or not l_price:
            continue

        # Momentum over 3 seconds (fast signal)
        d_mom_3s = momentum(d, 3) or 0
        l_mom_3s = momentum(l, 3) or 0
        d_mom_5s = momentum(d, 5) or 0
        l_mom_5s = momentum(l, 5) or 0

        # Also check 10s momentum for trend confirmation
        d_mom_10s = momentum(d, 10) or 0

        # Has driver moved enough?
        if abs(d_mom_5s) < pair["min_move"]:
            continue

        # Direction check: is the driver moving in the "right" direction
        # relative to the expected correlation?
        driver_direction = "up" if d_mom_5s > 0 else "down"

        # What should the laggard do based on correlation?
        if pair["direction"] == "same":
            expected_direction = driver_direction
        else:  # inverse
            expected_direction = "down" if driver_direction == "up" else "up"

        # Is the laggard moving the opposite direction (hasn't caught up)?
        laggard_direction = "up" if l_mom_5s > 0 else "down"

        # Signal condition:
        # 1. Driver moved enough AND
        # 2. Laggard hasn't moved significantly OR is going the WRONG way
        laggard_has_moved = abs(l_mom_5s) > pair["min_move"] * 0.3

        if abs(d_mom_5s) < pair["min_move"]:
            continue

        # If laggard has already moved in the expected direction — too late
        if laggard_has_moved and laggard_direction == expected_direction:
            continue

        # ── Confidence calculation ──
        confidence = 5  # base confidence

        # +1 if driver momentum is strong (consistent over 3s, 5s, 10s)
        if d_mom_3s and d_mom_5s and d_mom_10s:
            same_sign = (d_mom_3s > 0) == (d_mom_5s > 0) == (d_mom_10s > 0)
            if same_sign:
                confidence += 1

        # +1 if driver move is strong (> 2x min_move)
        if abs(d_mom_5s) >= pair["min_move"] * 2:
            confidence += 1

        # +1 if laggard is NOT moving (waiting to catch up = clean signal)
        if not laggard_has_moved:
            confidence += 1

        # +1 if correlation strength is high
        if pair["corr"] >= 0.70:
            confidence += 1

        # -1 if recent volatility is high (noise risk)
        # Skip this for now, could add later

        confidence = max(1, min(10, confidence))

        # Direction of the scalp trade
        if expected_direction == "up":
            scalp_direction = "long"
        else:
            scalp_direction = "short"

        # ── Build signal ──
        driver_label = "↑" if driver_direction == "up" else "↓"
        laggard_label = "↑" if expected_direction == "up" else "↓"
        dynamic_note = f"{pair['driver'].replace('xyz:','')} {driver_label} → {pair['laggard'].replace('xyz:','')} {laggard_label}"

        signals.append({
            "timestamp": now,
            "driver": d,
            "laggard": l,
            "direction": scalp_direction,
            "laggard_price": l_price,
            "driver_price": d_price,
            "driver_mom_3s": round(d_mom_3s, 4),
            "laggard_mom_3s": round(l_mom_3s, 4),
            "driver_mom_5s": round(d_mom_5s, 4),
            "laggard_mom_5s": round(l_mom_5s, 4),
            "driver_mom_10s": round(d_mom_10s, 4),
            "confidence": confidence,
            "pair_note": dynamic_note,
        })

    return signals


def analyze_order_book(coin: str) -> dict | None:
    """Check L2 book for best bid/ask on a tradeable instrument.
    Skip if instrument is signal-only (no book liquidity)."""
    if coin not in TRADEABLE:
        return None
    try:
        with httpx.Client(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=5) as c:
            r = c.post("https://api.hyperliquid.xyz/info",
                       json={"type": "l2Book", "coin": coin})
            bk = r.json()
            levels = bk.get("levels", [[], []])
            bids = levels[0]
            asks = levels[1]
            if bids and asks:
                return {
                    "bid": float(bids[0]["px"]),
                    "ask": float(asks[0]["px"]),
                    "bid_sz": float(bids[0]["sz"]),
                    "ask_sz": float(asks[0]["sz"]),
                    "spread_pct": round((float(asks[0]["px"]) - float(bids[0]["px"]))
                                        / float(bids[0]["px"]) * 100, 4),
                    "mid": (float(bids[0]["px"]) + float(asks[0]["px"])) / 2,
                }
    except Exception:
        pass
    return None


def display_signals(signals: list[dict]) -> None:
    """Pretty-print signals."""
    if not signals:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] No signals.")
        return

    for s in sorted(signals, key=lambda x: -x["confidence"]):
        arrow = "📈 LONG" if s["direction"] == "long" else "📉 SHORT"
        laggard = s["laggard"].replace("xyz:", "")
        driver = s["driver"].replace("xyz:", "")
        px = f"${s['laggard_price']:.2f}" if s['laggard_price'] > 100 else f"${s['laggard_price']:.4f}"
        conf = "█" * s["confidence"] + "░" * (10 - s["confidence"])
        print(
            f"[{datetime.now(timezone.utc).strftime('%H:%M:%S.%f')[:12]}] "
            f"{arrow} {laggard:8s} @ {px:<12s} "
            f"| {driver} {s['driver_mom_5s']:+.3f}% → lag {s['laggard_mom_5s']:+.3f}% "
            f"| C={conf} ({s['confidence']}/10) "
            f"| {s['pair_note']}", flush=True
        )


# ── Main ─────────────────────────────────────────────────────────────────────

def run_daemon(interval: float = 1.0) -> None:
    """Continuous evaluation loop."""
    _last_print = 0
    while True:
        try:
            signals = evaluate_pairs()

            # Only print when there are signals or every 30s
            if signals:
                display_signals(signals)
                _last_print = time.time()
            elif time.time() - _last_print > 30:
                display_signals([])
                _last_print = time.time()

        except Exception as e:
            print(f"[ERROR] {e}", flush=True)

        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Correlation scalp signal engine")
    parser.add_argument("--daemon", action="store_true", help="continuous loop")
    parser.add_argument("--once", action="store_true", help="JSON output")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="check interval (s)")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(interval=args.interval)
        return

    signals = evaluate_pairs()
    if args.once:
        print(json.dumps(signals, indent=2, default=str))
        return

    display_signals(signals)


if __name__ == "__main__":
    main()