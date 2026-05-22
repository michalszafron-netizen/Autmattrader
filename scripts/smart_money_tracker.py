"""Smart Money Tracker — top HL traders, live position monitoring.

Pure Python, zero AI tokens. Direct HL public API + Telegram Bot API.

How it works:
  1. Every --interval seconds (default 3600 = 1h), fetch top N HL traders
  2. Fetch their current positions
  3. Compare to previous snapshot in SQLite
  4. Send Telegram alert when significant changes detected
  5. Save new snapshot, sleep, repeat

Alert triggers:
  - NEW position opened by a top trader (notional > MIN_NOTIONAL)
  - 3+ traders agree on same coin+direction (consensus move)
  - Top trader CLOSES a position (took profit or stopped out)
  - Large size increase (>25% position growth)

Usage:
    python scripts/smart_money_tracker.py              # one-shot (run once, no loop)
    python scripts/smart_money_tracker.py --daemon     # runs forever (1h interval)
    python scripts/smart_money_tracker.py --interval 1800  # 30min interval
    python scripts/smart_money_tracker.py --top 30     # watch top 30 traders
    python scripts/smart_money_tracker.py --dry-run    # no Telegram, just print
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
from decimal import Decimal
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

# Force UTF-8 on Windows (emoji support)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv(Path(__file__).parent.parent / ".env")

_SSL          = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
HL_API        = "https://api.hyperliquid.xyz"
HL_STATS      = "https://stats-data.hyperliquid.xyz/Mainnet"
TG_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID    = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
MIN_NOTIONAL  = 50_000   # USD — ignore positions below this
TOP_N_DEFAULT = 20


# ── HL API helpers ────────────────────────────────────────────────────────────

def _post(payload: dict) -> dict | list:
    with httpx.Client(verify=_SSL, timeout=15) as c:
        r = c.post(f"{HL_API}/info", json=payload)
        r.raise_for_status()
        return r.json()


def fetch_leaderboard(top_n: int = TOP_N_DEFAULT) -> list[dict]:
    """Top N traders by weekly PnL."""
    with httpx.Client(verify=_SSL, timeout=15) as c:
        r = c.get(f"{HL_STATS}/leaderboard", timeout=15)
        r.raise_for_status()
    rows = r.json().get("leaderboardRows", [])

    def weekly_pnl(row: dict) -> float:
        for p in row.get("windowPerformances", []):
            if p[0] == "week":
                try:
                    return float(p[1].get("pnl", 0))
                except Exception:
                    return 0.0
        return 0.0

    return sorted(rows, key=weekly_pnl, reverse=True)[:top_n]


def fetch_positions(wallet: str) -> list[dict]:
    """Open positions for one wallet."""
    try:
        state = _post({"type": "clearinghouseState", "user": wallet})
        positions = []
        for pos_wrap in state.get("assetPositions", []):
            pos = pos_wrap.get("position", {})
            try:
                szi = float(pos.get("szi", "0"))
                if szi == 0:
                    continue
                entry = float(pos.get("entryPx", "0"))
                notional = abs(szi) * entry
                if notional < MIN_NOTIONAL:
                    continue
                positions.append({
                    "coin":     pos.get("coin", "?"),
                    "side":     "LONG" if szi > 0 else "SHORT",
                    "size":     abs(szi),
                    "entry":    entry,
                    "notional": notional,
                    "upnl":     float(pos.get("unrealizedPnl", "0")),
                    "lev":      pos.get("leverage", {}).get("value", "?"),
                })
            except Exception:
                pass
        return positions
    except Exception:
        return []


def snapshot_all(traders: list[dict]) -> dict[str, list[dict]]:
    """Fetch positions for all top traders. Returns {wallet: [positions]}."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    wallets = [t.get("ethAddress", "") for t in traders if t.get("ethAddress")]
    result: dict[str, list[dict]] = {}

    def fetch_one(w: str) -> tuple[str, list[dict]]:
        return w, fetch_positions(w)

    with ThreadPoolExecutor(max_workers=10) as pool:
        for future in as_completed({pool.submit(fetch_one, w): w for w in wallets}):
            wallet, positions = future.result()
            if positions:
                result[wallet] = positions
    return result


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"\n[TELEGRAM DRY-RUN]\n{text}\n")
        return
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_USER_ID not set")
        return
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            c.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": text,
                      "parse_mode": "HTML"},
            )
    except Exception as e:
        print(f"[WARN] Telegram send failed: {e}")


# ── SQLite snapshot storage ───────────────────────────────────────────────────

def _get_db():
    sys.path.insert(0, str(Path(__file__).parent))
    from db import DB
    db = DB()
    db._sqlite.execute("""
        CREATE TABLE IF NOT EXISTS sm_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            wallet      TEXT NOT NULL,
            coin        TEXT NOT NULL,
            side        TEXT NOT NULL,
            size        REAL,
            entry       REAL,
            notional    REAL,
            upnl        REAL,
            lev         TEXT
        )""")
    db._sqlite.execute("""
        CREATE TABLE IF NOT EXISTS sm_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            alert_type  TEXT NOT NULL,
            coin        TEXT,
            side        TEXT,
            wallet      TEXT,
            notional    REAL,
            details     TEXT
        )""")
    db._sqlite.execute(
        "CREATE INDEX IF NOT EXISTS idx_sm_snap_ts ON sm_snapshots(ts)")
    return db


def save_snapshot(db, ts: str, snapshot: dict[str, list[dict]]) -> None:
    for wallet, positions in snapshot.items():
        for pos in positions:
            db._sqlite.execute(
                """INSERT INTO sm_snapshots
                   (ts, wallet, coin, side, size, entry, notional, upnl, lev)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ts, wallet, pos["coin"], pos["side"], pos["size"],
                 pos["entry"], pos["notional"], pos["upnl"], str(pos["lev"])),
            )


def load_prev_snapshot(db) -> dict[str, list[dict]]:
    """Load the most recent previous snapshot."""
    rows = db._sqlite.query(
        """SELECT wallet, coin, side, size, entry, notional, upnl, lev
           FROM sm_snapshots
           WHERE ts = (SELECT MAX(ts) FROM sm_snapshots)"""
    )
    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        result[r["wallet"]].append(dict(r))
    return dict(result)


def save_alert(db, ts: str, alert_type: str, **kwargs) -> None:
    db._sqlite.execute(
        """INSERT INTO sm_alerts (ts, alert_type, coin, side, wallet, notional, details)
           VALUES (?,?,?,?,?,?,?)""",
        (ts, alert_type,
         kwargs.get("coin"), kwargs.get("side"), kwargs.get("wallet"),
         kwargs.get("notional"), json.dumps(kwargs.get("details", {}))),
    )


# ── Change detection ──────────────────────────────────────────────────────────

def _pos_key(pos: dict) -> str:
    return f"{pos['coin']}:{pos['side']}"


def detect_changes(
    prev: dict[str, list[dict]],
    curr: dict[str, list[dict]],
    traders: list[dict],
) -> list[dict]:
    """Returns list of alert dicts."""
    alerts = []

    # Build wallet → display_name map
    wallet_name: dict[str, str] = {}
    for t in traders:
        w = t.get("ethAddress", "")
        wallet_name[w] = w[:10] + "…"

    # Per-coin consensus tracker (current)
    coin_bias: dict[str, dict] = defaultdict(lambda: {"long": 0, "short": 0, "notional": 0.0})
    for wallet, positions in curr.items():
        for pos in positions:
            side_key = "long" if pos["side"] == "LONG" else "short"
            coin_bias[pos["coin"]][side_key] += 1
            coin_bias[pos["coin"]]["notional"] += pos["notional"]

    # Check each wallet for changes
    for wallet, curr_positions in curr.items():
        prev_positions = prev.get(wallet, [])
        prev_keys = {_pos_key(p): p for p in prev_positions}
        curr_keys = {_pos_key(p): p for p in curr_positions}

        name = wallet_name.get(wallet, wallet[:10])

        # NEW positions
        for key, pos in curr_keys.items():
            if key not in prev_keys:
                alerts.append({
                    "type":     "NEW_POSITION",
                    "wallet":   name,
                    "coin":     pos["coin"],
                    "side":     pos["side"],
                    "notional": pos["notional"],
                    "entry":    pos["entry"],
                    "lev":      pos["lev"],
                })

        # CLOSED positions
        for key, pos in prev_keys.items():
            if key not in curr_keys:
                alerts.append({
                    "type":     "CLOSED_POSITION",
                    "wallet":   name,
                    "coin":     pos["coin"],
                    "side":     pos["side"],
                    "notional": pos["notional"],
                })

        # SIZE INCREASE >25%
        for key, pos in curr_keys.items():
            if key in prev_keys:
                old_size = prev_keys[key]["size"]
                new_size = pos["size"]
                if old_size > 0 and (new_size - old_size) / old_size > 0.25:
                    alerts.append({
                        "type":     "SIZE_INCREASE",
                        "wallet":   name,
                        "coin":     pos["coin"],
                        "side":     pos["side"],
                        "notional": pos["notional"],
                        "change_pct": (new_size - old_size) / old_size * 100,
                    })

    # CONSENSUS MOVE: 3+ traders same direction on same coin
    for coin, bias in coin_bias.items():
        for direction in ("long", "short"):
            count = bias[direction]
            if count >= 3:
                prev_count = sum(
                    1 for positions in prev.values()
                    for p in positions
                    if p["coin"] == coin and
                    p["side"] == ("LONG" if direction == "long" else "SHORT")
                )
                if count > prev_count:
                    alerts.append({
                        "type":     "CONSENSUS_MOVE",
                        "coin":     coin,
                        "side":     direction.upper(),
                        "count":    count,
                        "notional": bias["notional"],
                    })

    return alerts


# ── Alert formatting ──────────────────────────────────────────────────────────

def _fmt_usd(v: float) -> str:
    if abs(v) >= 1e6: return f"${v/1e6:.2f}M"
    if abs(v) >= 1e3: return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def format_alerts(alerts: list[dict], ts: str) -> str | None:
    if not alerts:
        return None

    # Group and prioritize
    consensus  = [a for a in alerts if a["type"] == "CONSENSUS_MOVE"]
    new_pos    = [a for a in alerts if a["type"] == "NEW_POSITION"]
    closed_pos = [a for a in alerts if a["type"] == "CLOSED_POSITION"]
    size_inc   = [a for a in alerts if a["type"] == "SIZE_INCREASE"]

    lines = [f"🐋 <b>Smart Money Alert</b> — {ts}\n"]

    if consensus:
        lines.append("📊 <b>CONSENSUS MOVE:</b>")
        for a in consensus[:3]:
            side_emoji = "🟢" if a["side"] == "LONG" else "🔴"
            lines.append(
                f"  {side_emoji} {a['coin']} — {a['count']} top traderów "
                f"<b>{a['side']}</b> ({_fmt_usd(a['notional'])} łącznie)"
            )
        lines.append("")

    if new_pos:
        lines.append("🆕 <b>NOWE POZYCJE:</b>")
        for a in sorted(new_pos, key=lambda x: -x["notional"])[:5]:
            side_emoji = "🟢" if a["side"] == "LONG" else "🔴"
            lines.append(
                f"  {side_emoji} {a['wallet']} → {a['coin']} "
                f"<b>{a['side']}</b> {_fmt_usd(a['notional'])} @ ${a['entry']:,.2f}"
                + (f" ({a['lev']}x)" if a['lev'] != "?" else "")
            )
        lines.append("")

    if size_inc:
        lines.append("📈 <b>DOKUPUJE:</b>")
        for a in sorted(size_inc, key=lambda x: -x["notional"])[:3]:
            lines.append(
                f"  {a['wallet']} dodał +{a['change_pct']:.0f}% "
                f"do {a['coin']} {a['side']} → {_fmt_usd(a['notional'])}"
            )
        lines.append("")

    if closed_pos:
        lines.append("✅ <b>ZAMKNIĘTE:</b>")
        for a in sorted(closed_pos, key=lambda x: -x["notional"])[:3]:
            lines.append(
                f"  {a['wallet']} zamknął {a['coin']} {a['side']} "
                f"({_fmt_usd(a['notional'])})"
            )

    if len(lines) <= 1:
        return None  # nothing worth sending

    return "\n".join(lines)


# ── Heartbeat (hourly summary even when no changes) ───────────────────────────

def format_heartbeat(snapshot: dict[str, list[dict]], ts: str) -> str:
    """Brief summary sent every run even if no alerts."""
    coin_bias: dict[str, dict] = defaultdict(lambda: {"long": 0, "short": 0, "notional": 0.0})
    total_wallets = len(snapshot)
    total_positions = sum(len(v) for v in snapshot.values())

    for positions in snapshot.values():
        for pos in positions:
            side_key = "long" if pos["side"] == "LONG" else "short"
            coin_bias[pos["coin"]][side_key] += 1
            coin_bias[pos["coin"]]["notional"] += pos["notional"]

    # Top 3 by notional
    top_coins = sorted(
        [(coin, data) for coin, data in coin_bias.items()],
        key=lambda x: -x[1]["notional"]
    )[:4]

    lines = [f"📊 <b>Smart Money Hourly</b> — {ts}",
             f"Traderzy z pozycjami: {total_wallets} | Pozycje: {total_positions}\n"]

    for coin, data in top_coins:
        l, s = data["long"], data["short"]
        bias = "LONG" if l > s else ("SHORT" if s > l else "MIXED")
        emoji = "🟢" if bias == "LONG" else "🔴" if bias == "SHORT" else "🟡"
        lines.append(f"  {emoji} {coin}: {l}L / {s}S — {bias} ({_fmt_usd(data['notional'])})")

    return "\n".join(lines)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_once(top_n: int, dry_run: bool, send_heartbeat: bool = True) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{ts}] Fetching top {top_n} traders...", end=" ", flush=True)

    try:
        traders = fetch_leaderboard(top_n)
        print(f"{len(traders)} found. Fetching positions...", end=" ", flush=True)
        curr_snapshot = snapshot_all(traders)
        print(f"done ({sum(len(v) for v in curr_snapshot.values())} positions across {len(curr_snapshot)} wallets)")

        db = _get_db()
        prev_snapshot = load_prev_snapshot(db)

        alerts = detect_changes(prev_snapshot, curr_snapshot, traders)

        alert_msg = format_alerts(alerts, ts)
        if alert_msg:
            print(f"[{ts}] Sending {len(alerts)} alert(s)...")
            send_telegram(alert_msg, dry_run=dry_run)
            for a in alerts:
                save_alert(db, ts, a["type"], **a)
        elif send_heartbeat and prev_snapshot:
            hb = format_heartbeat(curr_snapshot, ts)
            send_telegram(hb, dry_run=dry_run)

        save_snapshot(db, ts, curr_snapshot)
        print(f"[{ts}] Snapshot saved. Alerts: {len(alerts)}")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback; traceback.print_exc()


def main() -> None:
    p = argparse.ArgumentParser(description="Smart Money Tracker — HL top traders")
    p.add_argument("--interval",  type=int, default=3600,
                   help="Poll interval in seconds (default: 3600 = 1h)")
    p.add_argument("--top",       type=int, default=TOP_N_DEFAULT,
                   help=f"Number of top traders to watch (default: {TOP_N_DEFAULT})")
    p.add_argument("--daemon",    action="store_true",
                   help="Run forever (loop every --interval seconds)")
    p.add_argument("--dry-run",   action="store_true",
                   help="Print alerts to stdout, do not send Telegram")
    p.add_argument("--no-heartbeat", action="store_true",
                   help="Only send alerts when changes detected, skip hourly summary")
    args = p.parse_args()

    if args.daemon:
        print(f"Starting Smart Money Tracker daemon (interval: {args.interval}s, top: {args.top})")
        print(f"Telegram: {'DRY-RUN' if args.dry_run else 'LIVE'}")
        while True:
            run_once(args.top, args.dry_run, send_heartbeat=not args.no_heartbeat)
            print(f"Sleeping {args.interval}s ({args.interval//60} min)...")
            time.sleep(args.interval)
    else:
        run_once(args.top, args.dry_run, send_heartbeat=not args.no_heartbeat)


if __name__ == "__main__":
    main()
