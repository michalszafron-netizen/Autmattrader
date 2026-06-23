"""xyz_scanner.py — HL xyz tick collector for correlation scalping.

Polls HL allMids every ~350ms, stores in ring buffer + SQLite.
Two tiers:
  TRADEABLE  — instruments we can actually trade (have order book)
  SIGNAL     — instruments used for correlation signals only

Usage:
    python scripts/xyz_scanner.py              # interactive loop, prints ticks
    python scripts/xyz_scanner.py --daemon     # runs forever (for Telegram cron)
    python scripts/xyz_scanner.py --once       # single snapshot
    python scripts/xyz_scanner.py --dump       # dump ring buffer as JSON
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import ssl
import sys
import time
from collections import defaultdict, deque
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

# ── SSL ───────────────────────────────────────────────────────────────────────
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
HL_API = "https://api.hyperliquid.xyz"
XYZ_DEX = "xyz"

# ── Instrument catalogue ──────────────────────────────────────────────────────
# Tradeable = we can long/short = has L2 book liquidity
# Signal   = price moves predict tradeable instruments

TRADEABLE = {
    "xyz:GOLD",     # tight spread 0.0024%
    "xyz:SILVER",   # tight spread 0.0015%
    "xyz:SP500",    # tight spread 0.0013%
    "xyz:CL",       # Crude Oil, tight spread 0.0014%
}

SIGNAL = {
    "xyz:DXY",      # Dollar index — inverse gold correlation (no book, but price is live)
    "xyz:VIX",      # Fear index — inverse SP500 (no book, but price is live)
    "xyz:EUR",      # EUR/USD — drives DXY which drives gold
}

WATCH = sorted(TRADEABLE | SIGNAL)  # 7 instruments

# ── Ring buffer ────────────────────────────────────────────────────────────────
# Per-instrument deque of (timestamp, price) tuples
# 3000 entries at 350ms = ~17.5 minutes of history
RING_SIZE = 3000
_ring: dict[str, deque] = defaultdict(lambda: deque(maxlen=RING_SIZE))
_last_save = time.monotonic()

# For change detection
_prev: dict[str, float] = {}

# ── DB path ────────────────────────────────────────────────────────────────────
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from db import DB
    _db = DB()
except Exception:
    _db = None


# ── Core fetch ─────────────────────────────────────────────────────────────────

def fetch_mids(client: httpx.Client | None = None) -> dict[str, float]:
    """Single call — returns ALL xyz mid prices as {coin: price}."""
    if client is None:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            r = c.post(f"{HL_API}/info", json={"type": "allMids", "dex": XYZ_DEX})
            r.raise_for_status()
            raw = r.json()
    else:
        r = client.post(f"{HL_API}/info", json={"type": "allMids", "dex": XYZ_DEX})
        r.raise_for_status()
        raw = r.json()
    return {k: float(v) for k, v in raw.items() if k in WATCH and v}


def snapshot(client: httpx.Client | None = None) -> dict[str, dict]:
    """Return current prices + change since last read for all WATCH instruments."""
    prices = fetch_mids(client)
    result = {}
    now = time.time()
    for coin in WATCH:
        px = prices.get(coin)
        if px is None or px == 0:
            continue
        prev = _prev.get(coin)
        change = px - prev if prev else 0.0
        change_pct = (change / prev * 100) if prev and prev != 0 else 0.0
        _prev[coin] = px
        _ring[coin].append((now, px))
        result[coin] = {"price": px, "change": change, "change_pct": change_pct}
    return result


# ── Ring buffer queries ────────────────────────────────────────────────────────

def get_buffer(coin: str, seconds: float = 60) -> list[tuple[float, float]]:
    """Return ring buffer entries for a coin within the last N seconds.
    Makes a copy to avoid 'deque mutated during iteration' race with scanner thread.
    """
    cutoff = time.time() - seconds
    items = list(_ring.get(coin, []))  # copy before iterating (thread-safe)
    return [(t, p) for t, p in items if t >= cutoff]


def latest(coin: str) -> float | None:
    """Most recent price for a coin."""
    buf = _ring.get(coin, [])
    return buf[-1][1] if buf else None


def momentum(coin: str, window_s: float = 5) -> float | None:
    """Price change over N seconds as percentage."""
    buf = get_buffer(coin, window_s)
    if len(buf) < 5:
        return None
    oldest = buf[0][1]
    newest = buf[-1][1]
    return (newest - oldest) / oldest * 100 if oldest != 0 else 0.0


# ── Bulk save to SQLite ────────────────────────────────────────────────────────

def _save_ticks() -> None:
    """Bulk save all buffered ticks since last save to SQLite."""
    global _last_save
    _last_save = time.monotonic()  # always update, even on error
    if _db is None:
        return

    try:
        now = int(time.time() * 1000)
        rows = []
        for coin in WATCH:
            buf = _ring.get(coin, [])
            if not buf:
                continue
            # deque does NOT support slicing — convert to list
            recent = list(buf)[-20:] if len(buf) > 20 else list(buf)
            last_px = buf[-1][1]
            avg_px = sum(p for _, p in recent) / len(recent) if recent else 0
            prices = [p for _, p in recent]
            min_px = min(prices) if prices else 0
            max_px = max(prices) if prices else 0
            rows.append({
                "ts": now,
                "coin": coin,
                "price": last_px,
                "avg_20": round(avg_px, 6),
                "min_20": min_px,
                "max_20": max_px,
                "tick_count": min(len(buf), 100),
            })
        if rows:
            _db.save_xyz_ticks(rows)
    except Exception:
        pass  # silent — don't crash the scanner loop


# ── Display ────────────────────────────────────────────────────────────────────

def display(snap: dict[str, dict]) -> None:
    """Pretty-print current snapshot — one line per instrument, no column drift."""
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")[:8]
    lines = [f"[{now}]"]
    for coin in WATCH:
        d = snap.get(coin)
        if d is None:
            continue
        px = d["price"]
        change = d.get("change_pct", 0)
        if abs(change) < 0.001:
            sym = "·"
        elif change > 0:
            sym = "↑"
        else:
            sym = "↓"
        tag = "T" if coin in TRADEABLE else "S"
        lines.append(f"  {tag} {coin[4:]:8s} ${px:<10.4f} {sym}{change:+.4f}%")
    print("\n".join(lines), flush=True)


# ── Main loop ──────────────────────────────────────────────────────────────────

_running = True


def _handle_signal(signum, frame) -> None:
    global _running
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def run_loop(daemon: bool = False, interval: float = 0.35) -> None:
    """Main polling loop. Default 350ms tick interval."""
    global _running
    _running = True

    _save_ticks()  # ensure DB table exists

    with httpx.Client(verify=_SSL, timeout=10) as client:
        while _running:
            t0 = time.monotonic()

            try:
                snap = snapshot(client)
                if not daemon:
                    display(snap)

                # Bulk save every 10 seconds
                if time.monotonic() - _last_save >= 10:
                    _save_ticks()

            except Exception as e:
                print(f"[ERROR] {e}", flush=True)

            elapsed = time.monotonic() - t0
            sleep = max(0.01, interval - elapsed)
            if daemon:
                # In daemon mode, use longer sleep for less noise
                time.sleep(sleep)
            else:
                time.sleep(sleep)

    # Final save on exit
    _save_ticks()
    print("\n[scanner stopped]", flush=True)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="xyz tick scanner")
    parser.add_argument("--daemon", action="store_true", help="run forever")
    parser.add_argument("--once", action="store_true", help="single snapshot")
    parser.add_argument("--dump", action="store_true", help="dump ring buffer as JSON")
    parser.add_argument("--interval", type=float, default=0.35, help="poll interval (s)")
    args = parser.parse_args()

    if args.once:
        snap = snapshot()
        print(json.dumps(snap, indent=2, default=str))
        return

    if args.dump:
        out = {}
        for coin in WATCH:
            out[coin] = [{"t": t, "p": p} for t, p in _ring.get(coin, [])]
        print(json.dumps(out, indent=2, default=str))
        return

    run_loop(daemon=args.daemon, interval=args.interval)


if __name__ == "__main__":
    main()