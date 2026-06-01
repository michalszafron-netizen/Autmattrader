"""Kozaki Monitor — elite Hyperliquid wallet tracker.

Śledzi top portfele z config/kozaki_watchlist.json.
Co --interval sekund:
  1. Pobiera aktualne pozycje wszystkich kozaków
  2. Porównuje z poprzednim snapshotem w SQLite
  3. Wykrywa zmiany: nowe pozycje, zamknięcia, dokupki (+25%), klastry (3+)
  4. Wysyła Telegram nawet jeśli brak zmian ("Brak zmian" heartbeat)
  5. Zapisuje snapshot + alerty do SQLite

Typy alertów:
  NEW_POSITION    — kozak otworzył nową pozycję
  CLOSED_POSITION — kozak zamknął pozycję
  SIZE_INCREASE   — kozak dodał >25% do istniejącej pozycji
  CLUSTER         — 3+ kozaków ma ten sam coin+side naraz

Usage:
    python scripts/kozaki_monitor.py              # jednorazowy run
    python scripts/kozaki_monitor.py --daemon     # pętla co --interval sekund
    python scripts/kozaki_monitor.py --interval 1800  # 30-minutowy interwał
    python scripts/kozaki_monitor.py --dry-run    # bez Telegrama i zapisu DB
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv(Path(__file__).parent.parent / ".env")

_SSL       = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
HL_API     = "https://api.hyperliquid.xyz"
TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")

WATCHLIST_PATH = Path(__file__).parent.parent / "config" / "kozaki_watchlist.json"
MIN_NOTIONAL   = 10_000   # USD — niższy próg niż SM tracker (kozacy grają różnie)


# ── Watchlist loader ──────────────────────────────────────────────────────────

def load_kozaks() -> list[dict]:
    """Ładuje wszystkie wallets z kozaki_watchlist.json."""
    if not WATCHLIST_PATH.exists():
        print(f"[ERROR] Watchlist nie znaleziona: {WATCHLIST_PATH}", file=sys.stderr)
        return []

    raw = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
    kozaks: list[dict] = []

    for entry in raw.get("leaderboard_4h", []):
        addr = entry.get("address", "")
        if not addr:
            continue
        note = entry.get("note", "")
        label = (note.split("—")[0].strip()[:40] if note
                 else ", ".join(entry.get("top_markets", [])[:2]) or "Leaderboard")
        kozaks.append({
            "address":     addr,
            "label":       label,
            "source":      "leaderboard",
            "roi_pct":     entry.get("pnl_pct", 0),
            "top_markets": entry.get("top_markets", []),
        })

    for entry in raw.get("discovery_monthly_elite", []):
        addr = entry.get("address", "")
        if not addr:
            continue
        note = entry.get("note", "")
        label = note.split("—")[0].strip()[:40] if note else "Discovery Elite"
        kozaks.append({
            "address":     addr,
            "label":       label,
            "source":      "discovery",
            "roi_pct":     entry.get("roi_pct", 0),
            "top_markets": [],
        })

    return kozaks


# ── HL API ────────────────────────────────────────────────────────────────────

def _post(payload: dict) -> dict:
    with httpx.Client(verify=_SSL, timeout=15) as c:
        r = c.post(f"{HL_API}/info", json=payload)
        r.raise_for_status()
        return r.json()


def fetch_positions(wallet: str) -> list[dict]:
    """Pobiera otwarte pozycje dla jednego walleta."""
    try:
        state = _post({"type": "clearinghouseState", "user": wallet})
        positions = []
        for pw in state.get("assetPositions", []):
            pos = pw.get("position", {})
            try:
                szi   = float(pos.get("szi", "0"))
                entry = float(pos.get("entryPx", "0"))
                if szi == 0 or entry == 0:
                    continue
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


def snapshot_all(kozaks: list[dict]) -> dict[str, list[dict]]:
    """Pobiera pozycje wszystkich kozaków równolegle. Zwraca {wallet: [positions]}."""
    # Inicjuj wszystkie wallets jako puste — nawet jeśli brak pozycji
    result: dict[str, list[dict]] = {k["address"]: [] for k in kozaks}

    def fetch_one(addr: str) -> tuple[str, list[dict]]:
        return addr, fetch_positions(addr)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_one, k["address"]): k["address"] for k in kozaks}
        for future in as_completed(futures):
            try:
                wallet, positions = future.result()
                result[wallet] = positions
            except Exception as e:
                addr = futures[future]
                print(f"[WARN] Błąd pobierania {addr[:12]}…: {e}")
    return result


# ── SQLite ────────────────────────────────────────────────────────────────────

def _get_db():
    sys.path.insert(0, str(Path(__file__).parent))
    from db import DB
    db = DB()
    for sql in [
        """CREATE TABLE IF NOT EXISTS kozaki_snapshots (
               id        INTEGER PRIMARY KEY AUTOINCREMENT,
               ts        TEXT NOT NULL,
               wallet    TEXT NOT NULL,
               coin      TEXT NOT NULL,
               side      TEXT NOT NULL,
               size      REAL,
               entry     REAL,
               notional  REAL,
               upnl      REAL,
               lev       TEXT
           )""",
        "CREATE INDEX IF NOT EXISTS idx_kozaki_snap_ts ON kozaki_snapshots(ts)",
        """CREATE TABLE IF NOT EXISTS kozaki_alerts (
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               ts          TEXT NOT NULL,
               alert_type  TEXT NOT NULL,
               wallet      TEXT,
               label       TEXT,
               coin        TEXT,
               side        TEXT,
               notional    REAL,
               details     TEXT
           )""",
        "CREATE INDEX IF NOT EXISTS idx_kozaki_alert_ts ON kozaki_alerts(ts)",
    ]:
        db._sqlite.execute(sql)
    return db


def save_snapshot(db, ts: str, snapshot: dict[str, list[dict]]) -> None:
    for wallet, positions in snapshot.items():
        for pos in positions:
            db._sqlite.execute(
                "INSERT INTO kozaki_snapshots "
                "(ts,wallet,coin,side,size,entry,notional,upnl,lev) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, wallet, pos["coin"], pos["side"], pos["size"],
                 pos["entry"], pos["notional"], pos["upnl"], str(pos["lev"])),
            )


def load_prev_snapshot(db) -> dict[str, list[dict]]:
    rows = db._sqlite.query(
        """SELECT wallet, coin, side, size, entry, notional, upnl, lev
           FROM kozaki_snapshots
           WHERE ts = (SELECT MAX(ts) FROM kozaki_snapshots)"""
    )
    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        result[r["wallet"]].append(dict(r))
    return dict(result)


def save_alert(db, ts: str, alert: dict) -> None:
    extra = {k: v for k, v in alert.items()
             if k not in ("type", "wallet", "label", "coin", "side", "notional")}
    db._sqlite.execute(
        "INSERT INTO kozaki_alerts "
        "(ts,alert_type,wallet,label,coin,side,notional,details) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (ts, alert["type"], alert.get("wallet"), alert.get("label"),
         alert.get("coin"), alert.get("side"), alert.get("notional"),
         json.dumps(extra)),
    )


def save_heartbeat(db, ts: str) -> None:
    """Zapisz czas ostatniego uruchomienia do scanner_runs (dla health API)."""
    try:
        db._sqlite.execute(
            "INSERT OR REPLACE INTO scanner_runs (scanner, last_run, status) "
            "VALUES (?, ?, ?)",
            ("kozaki", ts, "ok"),
        )
    except Exception:
        # Tabela może jeszcze nie istnieć — tworzy ją listings_scanner przy starcie
        pass


# ── Change detection ──────────────────────────────────────────────────────────

def _pos_key(pos: dict) -> str:
    return f"{pos['coin']}:{pos['side']}"


def detect_changes(
    prev: dict[str, list[dict]],
    curr: dict[str, list[dict]],
    kozaks: list[dict],
) -> list[dict]:
    alerts: list[dict] = []
    wallet_meta = {k["address"]: k for k in kozaks}

    # Cluster state dla curr
    curr_bias: dict[str, dict] = defaultdict(
        lambda: {"long": 0, "short": 0, "notional": 0.0,
                 "wallets_long": [], "wallets_short": []}
    )
    for wallet, positions in curr.items():
        for pos in positions:
            key = "long" if pos["side"] == "LONG" else "short"
            curr_bias[pos["coin"]][key] += 1
            curr_bias[pos["coin"]]["notional"] += pos["notional"]
            curr_bias[pos["coin"]][f"wallets_{key}"].append(wallet)

    prev_bias: dict[str, dict] = defaultdict(lambda: {"long": 0, "short": 0})
    for wallet, positions in prev.items():
        for pos in positions:
            key = "long" if pos["side"] == "LONG" else "short"
            prev_bias[pos["coin"]][key] += 1

    # Zmiany per-wallet
    for wallet, curr_positions in curr.items():
        prev_positions = prev.get(wallet, [])
        prev_map = {_pos_key(p): p for p in prev_positions}
        curr_map = {_pos_key(p): p for p in curr_positions}
        meta  = wallet_meta.get(wallet, {})
        label = meta.get("label", wallet)

        # NOWE pozycje
        for key, pos in curr_map.items():
            if key not in prev_map:
                alerts.append({
                    "type":    "NEW_POSITION",
                    "wallet":  wallet,      # pełny adres
                    "label":   label,
                    "coin":    pos["coin"],
                    "side":    pos["side"],
                    "notional": pos["notional"],
                    "entry":   pos["entry"],
                    "lev":     pos["lev"],
                })

        # ZAMKNIĘTE
        for key, pos in prev_map.items():
            if key not in curr_map:
                alerts.append({
                    "type":    "CLOSED_POSITION",
                    "wallet":  wallet,
                    "label":   label,
                    "coin":    pos["coin"],
                    "side":    pos["side"],
                    "notional": pos["notional"],
                })

        # DOKUPKA > 25%
        for key, pos in curr_map.items():
            if key in prev_map:
                old = prev_map[key]["size"]
                new = pos["size"]
                if old > 0 and (new - old) / old > 0.25:
                    alerts.append({
                        "type":       "SIZE_INCREASE",
                        "wallet":     wallet,
                        "label":      label,
                        "coin":       pos["coin"],
                        "side":       pos["side"],
                        "notional":   pos["notional"],
                        "change_pct": (new - old) / old * 100,
                    })

    # KLASTER: 3+ kozaków ten sam coin+kierunek (nowy lub rosnący)
    for coin, bias in curr_bias.items():
        for direction in ("long", "short"):
            count      = bias[direction]
            prev_count = prev_bias[coin][direction]
            if count >= 3 and count > prev_count:
                wallets = bias[f"wallets_{direction}"]
                alerts.append({
                    "type":    "CLUSTER",
                    "coin":    coin,
                    "side":    direction.upper(),
                    "count":   count,
                    "notional": bias["notional"],
                    "wallets": wallets,   # lista pełnych adresów
                })

    return alerts


# ── Formatowanie wiadomości Telegram ─────────────────────────────────────────

def _fmt_usd(v: float) -> str:
    if abs(v) >= 1_000_000: return f"${v / 1_000_000:.2f}M"
    if abs(v) >= 1_000:     return f"${v / 1_000:.0f}K"
    return f"${v:.0f}"


def send_telegram(text: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"\n[TELEGRAM DRY-RUN]\n{text}\n")
        return
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN lub TELEGRAM_ALLOWED_USER_ID nie ustawione")
        return
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            c.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            )
    except Exception as e:
        print(f"[WARN] Telegram błąd: {e}")


def format_message(
    alerts: list[dict],
    curr: dict[str, list[dict]],
    kozaks: list[dict],
    ts: str,
    is_baseline: bool = False,
) -> str:
    """Formatuje wiadomość Telegram. Zawsze zwraca non-None."""

    active    = sum(1 for v in curr.values() if v)
    total_pos = sum(len(v) for v in curr.values())
    wallet_meta = {k["address"]: k for k in kozaks}

    header = (
        f"🦅 <b>Kozaki Monitor</b> — {ts}\n"
        f"<code>Portfele: {len(kozaks)} | Aktywne: {active} | Pozycje: {total_pos}</code>"
    )

    if is_baseline:
        return (
            f"{header}\n\n"
            f"📋 <i>Pierwsze uruchomienie — snapshot bazowy zapisany.\n"
            f"Alerty będą wysyłane od następnego skanu.</i>"
        )

    new_pos    = [a for a in alerts if a["type"] == "NEW_POSITION"]
    closed_pos = [a for a in alerts if a["type"] == "CLOSED_POSITION"]
    size_inc   = [a for a in alerts if a["type"] == "SIZE_INCREASE"]
    clusters   = [a for a in alerts if a["type"] == "CLUSTER"]
    has_changes = bool(new_pos or closed_pos or size_inc or clusters)

    parts: list[str] = [header, ""]

    # ── KLASTRY (najważniejsze — na górze) ──
    if clusters:
        parts.append("⚡ <b>KLASTER — kozacy grają razem:</b>")
        for a in clusters[:3]:
            emoji = "🟢" if a["side"] == "LONG" else "🔴"
            parts.append(
                f"  {emoji} <b>{a['coin']}</b> {a['side']} — "
                f"{a['count']} portfeli, {_fmt_usd(a['notional'])} łącznie"
            )
            for w in a.get("wallets", [])[:4]:
                lbl = wallet_meta.get(w, {}).get("label", "")
                lbl_str = f" — <i>{lbl}</i>" if lbl else ""
                parts.append(f"  └ <code>{w}</code>{lbl_str}")
        parts.append("")

    # ── NOWE POZYCJE ──
    if new_pos:
        parts.append(f"🆕 <b>NOWE POZYCJE ({len(new_pos)}):</b>")
        for a in sorted(new_pos, key=lambda x: -x["notional"])[:6]:
            emoji = "🟢" if a["side"] == "LONG" else "🔴"
            lev   = f" ({a['lev']}x)" if a.get("lev") not in (None, "?") else ""
            parts.append(
                f"  {emoji} <b>{a['coin']}</b> {a['side']} "
                f"{_fmt_usd(a['notional'])} @ ${a.get('entry', 0):,.2f}{lev}"
            )
            parts.append(f"  └ <code>{a['wallet']}</code>")
            if a.get("label"):
                parts.append(f"     <i>{a['label']}</i>")
        parts.append("")

    # ── DOKUPKI ──
    if size_inc:
        parts.append(f"📈 <b>DOKUPUJE ({len(size_inc)}):</b>")
        for a in sorted(size_inc, key=lambda x: -x["notional"])[:4]:
            emoji = "🟢" if a["side"] == "LONG" else "🔴"
            parts.append(
                f"  {emoji} <b>{a['coin']}</b> {a['side']} "
                f"+{a['change_pct']:.0f}% → {_fmt_usd(a['notional'])}"
            )
            parts.append(f"  └ <code>{a['wallet']}</code>")
            if a.get("label"):
                parts.append(f"     <i>{a['label']}</i>")
        parts.append("")

    # ── ZAMKNIĘTE ──
    if closed_pos:
        parts.append(f"✅ <b>ZAMKNIĘTE ({len(closed_pos)}):</b>")
        for a in sorted(closed_pos, key=lambda x: -x["notional"])[:4]:
            emoji = "🟢" if a["side"] == "LONG" else "🔴"
            parts.append(
                f"  {emoji} <b>{a['coin']}</b> {a['side']} {_fmt_usd(a['notional'])}"
            )
            parts.append(f"  └ <code>{a['wallet']}</code>")
            if a.get("label"):
                parts.append(f"     <i>{a['label']}</i>")
        parts.append("")

    # ── BRAK ZMIAN — heartbeat z top pozycjami ──
    if not has_changes:
        parts.append("✓ <i>Brak zmian w tym oknie.</i>")
        parts.append("")

        # Top 5 aktywnych pozycji jako migawka
        all_pos: list[dict] = []
        for wallet, positions in curr.items():
            for pos in positions:
                lbl = wallet_meta.get(wallet, {}).get("label", "")
                all_pos.append({**pos, "wallet": wallet, "label": lbl})
        top5 = sorted(all_pos, key=lambda x: -x["notional"])[:5]

        if top5:
            parts.append("📊 <b>Największe aktywne pozycje:</b>")
            for pos in top5:
                emoji = "🟢" if pos["side"] == "LONG" else "🔴"
                parts.append(
                    f"  {emoji} <b>{pos['coin']}</b> {pos['side']} "
                    f"{_fmt_usd(pos['notional'])}"
                )
                parts.append(f"  └ <code>{pos['wallet']}</code>")
                if pos.get("label"):
                    parts.append(f"     <i>{pos['label']}</i>")

    return "\n".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────────

def run_once(dry_run: bool = False) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{ts}] Ładuję kozak watchlist...", end=" ", flush=True)

    kozaks = load_kozaks()
    if not kozaks:
        print("BRAK WATCHLISTY — nic do monitorowania.")
        return
    print(f"{len(kozaks)} kozaków.", end=" ", flush=True)

    print("Pobieranie pozycji...", end=" ", flush=True)
    curr = snapshot_all(kozaks)
    active    = sum(1 for v in curr.values() if v)
    total_pos = sum(len(v) for v in curr.values())
    print(f"ok ({active}/{len(kozaks)} aktywnych, {total_pos} pozycji)")

    if dry_run:
        # Dry-run: pokaż snapshot bez porównania
        msg = format_message([], curr, kozaks, ts, is_baseline=False)
        send_telegram(msg, dry_run=True)
        return

    db   = _get_db()
    prev = load_prev_snapshot(db)

    is_baseline = not bool(prev)
    if is_baseline:
        save_snapshot(db, ts, curr)
        save_heartbeat(db, ts)
        msg = format_message([], curr, kozaks, ts, is_baseline=True)
        send_telegram(msg, dry_run=dry_run)
        print(f"[{ts}] Baseline zapisany. Alerty od następnego skanu.")
        return

    alerts = detect_changes(prev, curr, kozaks)
    msg    = format_message(alerts, curr, kozaks, ts)
    send_telegram(msg, dry_run=dry_run)

    for a in alerts:
        save_alert(db, ts, a)

    save_snapshot(db, ts, curr)
    save_heartbeat(db, ts)
    print(f"[{ts}] Snapshot zapisany. Alerty: {len(alerts)}")


def main() -> None:
    p = argparse.ArgumentParser(description="Kozaki Monitor — elite HL wallet tracker")
    p.add_argument("--interval", type=int, default=3600,
                   help="Interwał w sekundach (domyślnie: 3600 = 1h)")
    p.add_argument("--daemon",  action="store_true",
                   help="Uruchom w pętli ciągłej")
    p.add_argument("--dry-run", action="store_true",
                   help="Bez Telegrama i bez zapisu DB")
    args = p.parse_args()

    if args.daemon:
        print(f"Kozaki Monitor daemon (interval: {args.interval}s, "
              f"watchlist: {WATCHLIST_PATH.name})")
        print(f"Telegram: {'DRY-RUN' if args.dry_run else 'LIVE'}")
        while True:
            run_once(dry_run=args.dry_run)
            print(f"Sleeping {args.interval}s ({args.interval // 60} min)...")
            time.sleep(args.interval)
    else:
        run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
