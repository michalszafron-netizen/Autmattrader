"""Shadow Copy Tracker — paper observation of a single Hyperliquid trader.

Symuluje MIRROR copy-trading BEZ realnych pieniedzy. Sledzi POZYCJE wybranego
tradera (nie surowe fille!) przez publiczne API Hyperliquid (DARMOWE, bez klucza,
bez Senpi, bez Anthropic) i zapisuje "co zrobilby Twoj mirror" do SQLite.

DLACZEGO POZYCJE A NIE FILLE (kluczowa lekcja):
  Prawdziwy mirror (Senpi) NIE powtarza 20 drabinkowych fillow tradera. Widzi
  "trader MA teraz pozycje ENA $59k" i otwiera Twoja proporcjonalna ENA JEDNYM
  zleceniem. Te 20 fillow to jego wykonanie — Ciebie nie obchodzi. Liczy sie
  tylko czy Twoja ZAGREGOWANA pozycja przekracza minimum HL.
  Stary model (per-fill) falszywie raportowal "0% kopiowalnych" bo skalowal
  groszowe fille. Ten model mierzy to co mirror naprawde robi.

Wykrywane zdarzenia (diff snapshotow pozycji, jak kozaki_monitor):
  OPEN   — trader otworzyl nowa pozycje  -> mirror otwiera proporcjonalna
  CLOSE  — trader zamknal pozycje        -> mirror zamyka
  ADD    — trader zwiekszyl o >10%        -> mirror dokłada
  REDUCE — trader zmniejszyl o >10%       -> mirror redukuje

Skalowanie:
  ratio = my_capital / trader_account_value
  my_notional = their_position_notional * ratio * multiplier
  Jesli my_notional < hl_min_notional (~$10) -> SKIPPED (mirror by nie otworzyl).

Koszt: $0. Tylko publiczne HL API. Zero LLM, zero Senpi.

Usage:
    python scripts/shadow_copy_tracker.py              # jednorazowy run
    python scripts/shadow_copy_tracker.py --daemon     # petla co --interval sekund
    python scripts/shadow_copy_tracker.py --interval 60      # 60s (domyslnie)
    python scripts/shadow_copy_tracker.py --dry-run    # bez Telegrama, bez DB
    python scripts/shadow_copy_tracker.py --report     # podsumowanie z DB (po 2-3 dniach)
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
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
HL_API     = "https://api.hyperliquid.xyz/info"
TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")

CONFIG_PATH = Path(__file__).parent.parent / "config" / "copy_trader.json"
LOG_PATH    = Path(__file__).parent.parent / "logs" / "shadow_copy.log"
ADD_REDUCE_THRESHOLD = 0.10   # 10% zmiana rozmiaru = ADD/REDUCE


def _log(msg: str) -> None:
    """Wypisz na stdout I dopisz do pliku logu (dla trybu background bez konsoli)."""
    print(msg, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] Config nie znaleziony: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


# ── HL public API (darmowe, bez auth) ─────────────────────────────────────────

def _post(payload: dict) -> dict | list:
    with httpx.Client(verify=_SSL, timeout=15) as c:
        r = c.post(HL_API, json=payload)
        r.raise_for_status()
        return r.json()


def fetch_state(wallet: str) -> dict:
    """Pelny stan konta tradera (pozycje + wartosc konta)."""
    try:
        return _post({"type": "clearinghouseState", "user": wallet})
    except Exception as e:
        print(f"[WARN] state: {e}")
        return {}


def parse_positions(state: dict) -> tuple[float, dict[str, dict]]:
    """Zwraca (account_value, {coin: {side,size,entry,notional,upnl,lev}})."""
    acct = float(state.get("marginSummary", {}).get("accountValue", "0"))
    positions: dict[str, dict] = {}
    for pw in state.get("assetPositions", []):
        pos = pw.get("position", {})
        try:
            szi = float(pos.get("szi", "0"))
            if szi == 0:
                continue
            coin = pos.get("coin", "?")
            positions[coin] = {
                "coin": coin,
                "side": "LONG" if szi > 0 else "SHORT",
                "size": abs(szi),
                "entry": float(pos.get("entryPx", "0")),
                "notional": float(pos.get("positionValue", "0")),
                "upnl": float(pos.get("unrealizedPnl", "0")),
                "lev": str(pos.get("leverage", {}).get("value", "?")),
            }
        except Exception:
            pass
    return acct, positions


# ── SQLite ────────────────────────────────────────────────────────────────────

def _get_db():
    sys.path.insert(0, str(Path(__file__).parent))
    from db import DB
    db = DB()
    for sql in [
        """CREATE TABLE IF NOT EXISTS shadow_positions (
               id        INTEGER PRIMARY KEY AUTOINCREMENT,
               ts        TEXT NOT NULL,
               trader    TEXT NOT NULL,
               coin      TEXT NOT NULL,
               side      TEXT NOT NULL,
               size      REAL,
               entry     REAL,
               notional  REAL,
               upnl      REAL,
               lev       TEXT
           )""",
        "CREATE INDEX IF NOT EXISTS idx_shpos_ts ON shadow_positions(ts)",
        """CREATE TABLE IF NOT EXISTS shadow_events (
               id            INTEGER PRIMARY KEY AUTOINCREMENT,
               ts            TEXT NOT NULL,
               trader        TEXT NOT NULL,
               event         TEXT NOT NULL,
               coin          TEXT NOT NULL,
               side          TEXT,
               their_notional REAL,
               my_notional   REAL,
               lev           TEXT,
               status        TEXT NOT NULL,
               ratio         REAL,
               detail        TEXT
           )""",
        "CREATE INDEX IF NOT EXISTS idx_shev_ts ON shadow_events(ts)",
    ]:
        db._sqlite.execute(sql)
    return db


def load_prev_positions(db, trader: str) -> dict[str, dict]:
    rows = db._sqlite.query(
        """SELECT coin, side, size, entry, notional, upnl, lev
           FROM shadow_positions
           WHERE trader = ? AND ts = (
               SELECT MAX(ts) FROM shadow_positions WHERE trader = ?)""",
        (trader, trader),
    )
    return {r["coin"]: dict(r) for r in rows}


def save_positions(db, ts: str, trader: str, positions: dict[str, dict]) -> None:
    for p in positions.values():
        db._sqlite.execute(
            "INSERT INTO shadow_positions (ts,trader,coin,side,size,entry,notional,upnl,lev) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, trader, p["coin"], p["side"], p["size"], p["entry"],
             p["notional"], p["upnl"], p["lev"]),
        )


def save_event(db, ts: str, trader: str, ev: dict) -> None:
    db._sqlite.execute(
        "INSERT INTO shadow_events "
        "(ts,trader,event,coin,side,their_notional,my_notional,lev,status,ratio,detail) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ts, trader, ev["event"], ev["coin"], ev.get("side"),
         ev.get("their_notional"), ev.get("my_notional"), ev.get("lev"),
         ev["status"], ev.get("ratio"), ev.get("detail", "")),
    )


def save_heartbeat(db, ts: str) -> None:
    try:
        db._sqlite.execute(
            "INSERT OR REPLACE INTO scanner_runs (scanner, last_run, status) VALUES (?,?,?)",
            ("shadow_copy", ts, "ok"),
        )
    except Exception:
        pass


# ── Diff: wykrywanie zdarzen na poziomie POZYCJI ──────────────────────────────

def detect_events(prev: dict[str, dict], curr: dict[str, dict],
                  ratio: float, cfg: dict) -> list[dict]:
    events: list[dict] = []
    mult = cfg["multiplier"]
    min_notional = cfg["hl_min_notional_usd"]

    def mk(event, p, detail=""):
        my_notional = p["notional"] * ratio * mult
        return {
            "event": event, "coin": p["coin"], "side": p["side"],
            "their_notional": p["notional"], "my_notional": my_notional,
            "lev": p["lev"], "ratio": ratio, "detail": detail,
            "status": "COPIED" if my_notional >= min_notional else "SKIPPED",
        }

    # OPEN: w curr, nie ma w prev
    for coin, p in curr.items():
        if coin not in prev:
            events.append(mk("OPEN", p))

    # CLOSE: bylo w prev, nie ma w curr
    for coin, p in prev.items():
        if coin not in curr:
            events.append(mk("CLOSE", p))

    # ADD / REDUCE: jest w obu, zmiana rozmiaru > prog
    for coin, p in curr.items():
        if coin in prev:
            old_sz = float(prev[coin]["size"] or 0)
            new_sz = p["size"]
            if old_sz > 0:
                chg = (new_sz - old_sz) / old_sz
                if chg > ADD_REDUCE_THRESHOLD:
                    events.append(mk("ADD", p, f"+{chg*100:.0f}%"))
                elif chg < -ADD_REDUCE_THRESHOLD:
                    events.append(mk("REDUCE", p, f"{chg*100:.0f}%"))
    return events


# ── Telegram ───────────────────────────────────────────────────────────────────

def _fmt_usd(v: float) -> str:
    if abs(v) >= 1_000_000: return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:     return f"${v/1_000:.1f}K"
    return f"${v:.2f}"


def send_telegram(text: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"\n[TELEGRAM DRY-RUN]\n{text}\n")
        return
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[WARN] brak TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_USER_ID")
        return
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            c.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                   json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        print(f"[WARN] Telegram: {e}")


_EV_EMOJI = {"OPEN": "🟢", "CLOSE": "✅", "ADD": "📈", "REDUCE": "📉"}


def format_msg(events: list[dict], curr: dict[str, dict], cfg: dict,
               acct: float, ratio: float, ts: str, baseline: bool = False) -> str:
    head = (
        f"👤 <b>Shadow Copy</b> — {ts}\n"
        f"<code>{cfg['trader_label']}</code>\n"
        f"<code>Kapital: ${cfg['my_capital_usd']:.0f} | mnoznik {cfg['multiplier']}x | "
        f"konto {_fmt_usd(acct)} | skala 1:{(1/ratio):,.0f}</code>"
    )
    if baseline:
        parts = [head, "", "📋 <i>Snapshot bazowy — jego obecne pozycje:</i>", ""]
        for p in sorted(curr.values(), key=lambda x: -x["notional"]):
            my = p["notional"] * ratio * cfg["multiplier"]
            ok = "✅" if my >= cfg["hl_min_notional_usd"] else "⚪"
            emoji = "🟢" if p["side"] == "LONG" else "🔴"
            parts.append(f"  {emoji} <b>{p['coin']}</b> {p['side']} {p['lev']}x — "
                         f"Ty: {_fmt_usd(my)} {ok} (on: {_fmt_usd(p['notional'])})")
        parts.append("")
        parts.append("<i>Od nastepnego skanu: alerty o zmianach (OPEN/CLOSE/ADD/REDUCE).</i>")
        return "\n".join(parts)

    copied = [e for e in events if e["status"] == "COPIED"]
    skipped = [e for e in events if e["status"] == "SKIPPED"]
    parts = [head, ""]
    if copied:
        parts.append(f"📥 <b>Twoj mirror zrobilby ({len(copied)}):</b>")
        for e in copied:
            emoji = _EV_EMOJI.get(e["event"], "•")
            d = f" {e['detail']}" if e.get("detail") else ""
            parts.append(f"  {emoji} <b>{e['event']} {e['coin']}</b> {e['side']}{d} — "
                         f"Ty: {_fmt_usd(e['my_notional'])} (on: {_fmt_usd(e['their_notional'])})")
    if skipped:
        parts.append("")
        parts.append(f"⚪ <i>Pominiete (poz. ponizej ${cfg['hl_min_notional_usd']:.0f}): {len(skipped)}</i>")
        for e in skipped[:5]:
            parts.append(f"  · {e['event']} {e['coin']} — bylby {_fmt_usd(e['my_notional'])}")
    if not events:
        parts.append("✓ <i>Brak zmian pozycji w tym oknie.</i>")
    return "\n".join(parts)


# ── Run ─────────────────────────────────────────────────────────────────────

def run_once(dry_run: bool = False) -> None:
    cfg = load_config()
    trader = cfg["trader_address"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    state = fetch_state(trader)
    acct, curr = parse_positions(state)
    if acct <= 0:
        print(f"[{ts}] Brak wartosci konta — pomijam.")
        return
    ratio = cfg["my_capital_usd"] / acct

    if dry_run:
        msg = format_msg([], curr, cfg, acct, ratio, ts, baseline=True)
        send_telegram(msg, dry_run=True)
        print(f"[{ts}] DRY-RUN: {len(curr)} pozycji teraz.")
        return

    db = _get_db()
    prev = load_prev_positions(db, trader)
    baseline = not bool(prev)

    if baseline:
        save_positions(db, ts, trader, curr)
        save_heartbeat(db, ts)
        send_telegram(format_msg([], curr, cfg, acct, ratio, ts, baseline=True), dry_run=dry_run)
        _log(f"[{ts}] Baseline zapisany ({len(curr)} pozycji). Alerty od nastepnego skanu.")
        return

    events = detect_events(prev, curr, ratio, cfg)
    for ev in events:
        save_event(db, ts, trader, ev)
    save_positions(db, ts, trader, curr)
    save_heartbeat(db, ts)

    if events:
        send_telegram(format_msg(events, curr, cfg, acct, ratio, ts), dry_run=dry_run)
    _log(f"[{ts}] Zdarzen: {len(events)} (pozycji teraz: {len(curr)}).")


def cmd_report() -> None:
    cfg = load_config()
    db = _get_db()
    trader = cfg["trader_address"]
    rows = db._sqlite.query(
        "SELECT * FROM shadow_events WHERE trader = ? ORDER BY id", (trader,)
    )
    runs = db._sqlite.query(
        "SELECT MIN(ts) AS first, MAX(ts) AS last, COUNT(DISTINCT ts) AS scans "
        "FROM shadow_positions WHERE trader = ?", (trader,)
    )
    print(f"\n{'='*62}")
    print(f"SHADOW COPY REPORT — {cfg['trader_label']}")
    print(f"{'='*62}")
    if runs and runs[0]["first"]:
        print(f"Okres:  {runs[0]['first']} -> {runs[0]['last']}  ({runs[0]['scans']} skanow)")
    if not rows:
        print("Zdarzen: 0 — jeszcze nie wykryto zmian pozycji (trader nic nie ruszyl,")
        print("albo dopiero baseline). Daj wiecej czasu.")
        print(f"{'='*62}\n")
        return
    by_event: dict[str, int] = {}
    copied = [r for r in rows if r["status"] == "COPIED"]
    skipped = [r for r in rows if r["status"] == "SKIPPED"]
    for r in rows:
        by_event[r["event"]] = by_event.get(r["event"], 0) + 1
    coins: dict[str, int] = {}
    for r in rows:
        coins[r["coin"]] = coins.get(r["coin"], 0) + 1
    print(f"Zdarzen lacznie:     {len(rows)}")
    print(f"  wg typu:           {', '.join(f'{k}({v})' for k,v in sorted(by_event.items()))}")
    print(f"  KOPIOWALNE:        {len(copied)}  ({100*len(copied)//max(len(rows),1)}%)")
    print(f"  POMINIETE:         {len(skipped)}  ({100*len(skipped)//max(len(rows),1)}%)")
    print(f"Aktywa:              {', '.join(f'{k}({v})' for k,v in sorted(coins.items(), key=lambda x:-x[1])[:10])}")

    # ── Analiza oplat: taker (mirror z rynku) vs maker (gdyby limit) ──
    TAKER, MAKER = 0.00045, 0.00015
    notional_copied = sum(float(r["my_notional"] or 0) for r in copied)
    fee_taker = notional_copied * TAKER
    fee_maker = notional_copied * MAKER
    # groźne pominiecia: CLOSE/REDUCE ktore odpadly (ryzyko wiszacej pozycji)
    risky = [r for r in skipped if r["event"] in ("CLOSE", "REDUCE")]
    print(f"{'-'*62}")
    print(f"OPLATY (na skopiowanych zdarzeniach, notional ${notional_copied:,.0f}):")
    print(f"  jako TAKER (rynek, 0.045%):   ${fee_taker:,.2f}")
    print(f"  jako MAKER (limit,  0.015%):  ${fee_maker:,.2f}")
    print(f"  podatek takera (roznica):     ${fee_taker - fee_maker:,.2f}")
    print(f"{'-'*62}")
    print(f"RYZYKO: pominiete wyjscia (CLOSE/REDUCE): {len(risky)}")
    if risky:
        for r in risky[:8]:
            print(f"  ⚠️  {r['event']} {r['coin']} — on ${r['their_notional'] or 0:.0f}, "
                  f"Ty bylby ${r['my_notional'] or 0:.2f} (ponizej min)")
        print("  (grozne tylko jesli mirror WCZESNIEJ otworzyl te pozycje)")
    print(f"{'='*62}")
    print("Kazde zdarzenie = jedna decyzja tradera (OPEN/CLOSE/ADD/REDUCE),")
    print("nie surowy fill. To odzwierciedla co mirror faktycznie by zrobil.")
    print("Win rate / profit factor tradera: z discovery_get_trader_history (Senpi).\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Shadow Copy Tracker — paper mirror (HL public API)")
    p.add_argument("--interval", type=int, default=60, help="Interwal w sekundach (domyslnie 60)")
    p.add_argument("--daemon", action="store_true", help="Petla ciagla")
    p.add_argument("--dry-run", action="store_true", help="Bez Telegrama, bez DB")
    p.add_argument("--report", action="store_true", help="Podsumowanie z DB i wyjscie")
    args = p.parse_args()

    if args.report:
        cmd_report()
        return

    if args.daemon:
        cfg = load_config()
        print(f"Shadow Copy daemon — trader {cfg['trader_address'][:10]}..., "
              f"interval {args.interval}s, {'DRY-RUN' if args.dry_run else 'LIVE'}")
        while True:
            try:
                run_once(dry_run=args.dry_run)
            except Exception as e:
                print(f"[ERROR] tick: {e}")
            time.sleep(args.interval)
    else:
        run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
