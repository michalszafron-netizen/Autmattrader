"""Copy Bot — wlasny copy-trading na Hyperliquid, BEZ Senpi (zero haraczu 0.05%).

Model: TARGET-POSITION RECONCILIATION (nie kopiowanie fillow!).
  Co tick:
    1. Pobierz pozycje tradera (HL public API)        -> stan zrodlowy
    2. Policz CEL = jego_pozycja * ratio * multiplier  -> ile POWINIENEM miec
    3. Pobierz MOJ stan (paper: wirtualny portfel w SQLite; live: realne pozycje)
    4. Reconcile: roznica cel vs stan -> akcje OPEN/ADD/REDUCE/CLOSE
    5. Wykonaj TYLKO roznice:
         paper -> symuluj (aktualizuj wirtualny portfel, drukuj, Telegram)
         live  -> hl_executor (LIMIT maker przy rynku = 0.015%, + obowiazkowy SL)

Dlaczego reconciliation a nie fille: gdy on uzbiera $1000 drabinka przez 20 fillow,
my RAZ wyrownujemy do celu. Zero problemu "100 mikro-fillow". Profesjonalny model.

Koszt: w live jako maker ~0.015%/strona. Zero Senpi. Egzekucja w naszych rekach.

TRYB: TRADING_MODE / HL_TRADING_MODE w .env. Domyslnie paper (dry-run).
  paper -> NIC nie wysyla na gielde. Wirtualny portfel + raport.
  live  -> realne zlecenia (jeszcze NIE zaimplementowane w tym pliku — Sesja 2).

Usage:
    python scripts/copy_bot.py                  # jednorazowy reconcile (paper)
    python scripts/copy_bot.py --daemon         # petla co --interval sekund
    python scripts/copy_bot.py --interval 60
    python scripts/copy_bot.py --reset          # wyczysc wirtualny portfel (start od zera)
    python scripts/copy_bot.py --status         # pokaz wirtualny portfel + cel
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
LOG_PATH    = Path(__file__).parent.parent / "logs" / "copy_bot.log"

_mode = (os.getenv("HL_TRADING_MODE") or os.getenv("TRADING_MODE", "paper")).lower()
PAPER_MODE = _mode != "live"

# Reconcile thresholds
REBALANCE_THRESHOLD = 0.10   # zmieniaj pozycje dopiero gdy roznica > 10% (anti-noise)
DEFAULT_SL_PCT      = 8.0    # obowiazkowy SL: % od ceny wejscia (paper: tylko zapis)


def _log(msg: str) -> None:
    print(msg, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        _log(f"[ERROR] Brak configu: {CONFIG_PATH}")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def get_traders(cfg: dict) -> list[dict]:
    """Lista aktywnych traderow. Obsluguje nowy format 'traders' i stary single."""
    if cfg.get("traders"):
        return [t for t in cfg["traders"] if t.get("active", True)]
    # fallback: stary pojedynczy trader
    return [{"address": cfg["trader_address"], "label": cfg.get("trader_label", cfg["trader_address"])}]


def trader_capital(cfg: dict, t: dict) -> float:
    """Kapital dla danego tradera: jego 'capital_usd' nadpisuje globalny 'my_capital_usd'."""
    return float(t.get("capital_usd") or cfg["my_capital_usd"])


# ── HL public API ─────────────────────────────────────────────────────────────

def _post(payload: dict) -> dict | list:
    with httpx.Client(verify=_SSL, timeout=15) as c:
        r = c.post(HL_API, json=payload)
        r.raise_for_status()
        return r.json()


def fetch_trader(wallet: str) -> tuple[float, dict[str, dict]]:
    """(account_value, {coin: {side,size,entry,notional,lev}}) tradera.

    Rzuca wyjatek jesli API nie odpowiedzialo (blad sieci) — wtedy run_once
    pomija tick. Jesli API odpowiedzialo ale konto=0/pusto -> to REALNE wyjscie
    tradera (zwraca acct=0, pusty dict) i bot ZAMKNIE nasze pozycje.
    """
    def _parse(state: dict, pos: dict) -> float:
        a = float(state.get("marginSummary", {}).get("accountValue", "0"))
        for pw in state.get("assetPositions", []):
            p = pw.get("position", {})
            szi = float(p.get("szi", "0"))
            if szi == 0:
                continue
            coin = p.get("coin", "?")
            pos[coin] = {
                "coin": coin,
                "side": "LONG" if szi > 0 else "SHORT",
                "size": abs(szi),
                "entry": float(p.get("entryPx", "0")),
                "notional": float(p.get("positionValue", "0")),
                "lev": int(p.get("leverage", {}).get("value", 1)),
            }
        return a

    state = _post({"type": "clearinghouseState", "user": wallet})
    if not isinstance(state, dict) or "marginSummary" not in state:
        raise RuntimeError("HL API nie zwrocilo poprawnego stanu (blad sieci?)")
    pos: dict[str, dict] = {}
    acct = _parse(state, pos)
    # xyz dex (tokenizowane akcje) — osobny clearinghouseState. Trader moze trzymac
    # pozycje TYLKO tu (main = $0). Degradacja przy bledzie xyz, zeby nie zabic ticku.
    try:
        xyz_state = _post({"type": "clearinghouseState", "user": wallet, "dex": "xyz"})
        if isinstance(xyz_state, dict) and "marginSummary" in xyz_state:
            acct += _parse(xyz_state, pos)
    except Exception:
        pass
    return acct, pos


def fetch_mark_prices(coins: list[str]) -> dict[str, float]:
    """Aktualne mid prices z allMids (do liczenia rozmiaru i SL).

    Tokenizowane akcje (xyz:MU itd.) zyja na osobnym perp dex 'xyz' — glowny
    allMids ich NIE zwraca. Gdy wsrod coinow jest jakikolwiek 'xyz:', dociagamy
    tez mid'y z dex='xyz' i scalamy (klucze sa rozlaczne, wiec brak kolizji).
    """
    mids = _post({"type": "allMids"})
    if any(c.startswith("xyz:") for c in coins):
        try:
            xyz = _post({"type": "allMids", "dex": "xyz"})
            if isinstance(xyz, dict):
                mids = {**mids, **xyz}
        except Exception:
            pass  # brak xyz dex -> degraduj do samego glownego (pozycje xyz pominiete)
    out: dict[str, float] = {}
    for c in coins:
        v = mids.get(c)
        if v is not None:
            try:
                out[c] = float(v)
            except Exception:
                pass
    return out


# ── Wirtualny portfel (paper) w SQLite ────────────────────────────────────────

def _get_db():
    sys.path.insert(0, str(Path(__file__).parent))
    from db import DB
    db = DB()
    for sql in [
        """CREATE TABLE IF NOT EXISTS copybot_positions (
               trader   TEXT NOT NULL,
               coin     TEXT NOT NULL,
               side     TEXT NOT NULL,
               size     REAL NOT NULL,
               entry    REAL NOT NULL,
               notional REAL NOT NULL,
               lev      INTEGER,
               sl_price REAL,
               opened_ts TEXT,
               PRIMARY KEY (trader, coin)
           )""",
        """CREATE TABLE IF NOT EXISTS copybot_actions (
               id        INTEGER PRIMARY KEY AUTOINCREMENT,
               ts        TEXT NOT NULL,
               trader    TEXT,
               action    TEXT NOT NULL,
               coin      TEXT NOT NULL,
               side      TEXT,
               my_notional REAL,
               their_notional REAL,
               price     REAL,
               lev       INTEGER,
               sl_price  REAL,
               mode      TEXT,
               detail    TEXT
           )""",
        "CREATE INDEX IF NOT EXISTS idx_cba_ts ON copybot_actions(ts)",
        """CREATE TABLE IF NOT EXISTS copybot_pnl (
               id        INTEGER PRIMARY KEY AUTOINCREMENT,
               ts        TEXT NOT NULL,
               trader    TEXT NOT NULL,
               coin      TEXT NOT NULL,
               side      TEXT,
               entry     REAL,
               exit      REAL,
               size      REAL,
               realized  REAL,
               kind      TEXT
           )""",
        "CREATE INDEX IF NOT EXISTS idx_cbp_trader ON copybot_pnl(trader)",
    ]:
        db._sqlite.execute(sql)
    return db


def record_realized(db, ts, trader, coin, side, entry, exit_px, size, kind):
    """Zapisz zrealizowany PnL z zamkniecia/redukcji.
    LONG: (exit-entry)*size ; SHORT: (entry-exit)*size."""
    if side == "LONG":
        realized = (exit_px - entry) * size
    else:
        realized = (entry - exit_px) * size
    db._sqlite.execute(
        "INSERT INTO copybot_pnl (ts,trader,coin,side,entry,exit,size,realized,kind) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, trader, coin, side, entry, exit_px, size, realized, kind),
    )
    return realized


def load_my_positions(db, trader: str) -> dict[str, dict]:
    """Paper: wirtualny portfel danego tradera z SQLite."""
    rows = db._sqlite.query("SELECT * FROM copybot_positions WHERE trader=?", (trader,))
    return {r["coin"]: dict(r) for r in rows}


def upsert_my_position(db, trader, coin, side, size, entry, notional, lev, sl_price, ts):
    db._sqlite.execute(
        """INSERT INTO copybot_positions (trader,coin,side,size,entry,notional,lev,sl_price,opened_ts)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(trader,coin) DO UPDATE SET
             side=excluded.side, size=excluded.size, entry=excluded.entry,
             notional=excluded.notional, lev=excluded.lev, sl_price=excluded.sl_price""",
        (trader, coin, side, size, entry, notional, lev, sl_price, ts),
    )


def delete_my_position(db, trader, coin):
    db._sqlite.execute("DELETE FROM copybot_positions WHERE trader=? AND coin=?", (trader, coin))


def log_action(db, ts, trader, action, coin, side, my_notional, their_notional, price, lev, sl_price, detail=""):
    db._sqlite.execute(
        """INSERT INTO copybot_actions
           (ts,trader,action,coin,side,my_notional,their_notional,price,lev,sl_price,mode,detail)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ts, trader, action, coin, side, my_notional, their_notional, price, lev, sl_price,
         "paper" if PAPER_MODE else "live", detail),
    )


# ── Reconciler — serce systemu ────────────────────────────────────────────────

def reconcile(trader_acct: float, trader_pos: dict[str, dict],
              my_pos: dict[str, dict], marks: dict[str, float],
              cfg: dict, capital: float | None = None) -> list[dict]:
    """Porownaj CEL (jego*ratio*mult) z MOIM stanem. Zwroc liste akcji."""
    cap = capital if capital is not None else cfg["my_capital_usd"]
    # trader_acct=0 -> trader wyszedl do zera; ratio=0, ponizsza petla po jego
    # pozycjach jest pusta, wiec lecimy prosto do sekcji CLOSE moich pozycji.
    ratio = cap / trader_acct if trader_acct > 0 else 0.0
    mult = cfg["multiplier"]
    min_notional = cfg["hl_min_notional_usd"]
    actions: list[dict] = []

    def target_notional(p):
        return p["notional"] * ratio * mult

    # 1. Pozycje ktore on MA — czy otworzyc/zmienic
    for coin, tp in trader_pos.items():
        tgt = target_notional(tp)
        mark = marks.get(coin, tp["entry"])
        mine = my_pos.get(coin)

        if tgt < min_notional:
            # cel ponizej minimum HL -> pomijamy (jego mikro-pozycja)
            if not mine:
                actions.append({"action": "SKIP", "coin": coin, "side": tp["side"],
                                "my_notional": tgt, "their_notional": tp["notional"],
                                "price": mark, "lev": tp["lev"],
                                "detail": f"cel ${tgt:.2f} < min ${min_notional}"})
            continue

        if not mine:
            # OPEN — nowa pozycja
            size = tgt / mark if mark > 0 else 0
            sl = _sl_price(tp["side"], mark, DEFAULT_SL_PCT)
            actions.append({"action": "OPEN", "coin": coin, "side": tp["side"],
                            "my_notional": tgt, "their_notional": tp["notional"],
                            "price": mark, "size": size, "lev": tp["lev"], "sl_price": sl})
        else:
            # juz mam — sprawdz czy trzeba ADD/REDUCE (lub FLIP kierunku)
            if mine["side"] != tp["side"]:
                # FLIP — on zmienil kierunek: zamknij + otworz przeciwnie
                actions.append({"action": "FLIP", "coin": coin, "side": tp["side"],
                                "my_notional": tgt, "their_notional": tp["notional"],
                                "price": mark, "size": tgt / mark if mark > 0 else 0,
                                "lev": tp["lev"], "sl_price": _sl_price(tp["side"], mark, DEFAULT_SL_PCT),
                                "detail": f"{mine['side']}->{tp['side']}"})
            else:
                cur = mine["notional"]
                if cur > 0:
                    chg = (tgt - cur) / cur
                    if chg > REBALANCE_THRESHOLD:
                        actions.append({"action": "ADD", "coin": coin, "side": tp["side"],
                                        "my_notional": tgt, "their_notional": tp["notional"],
                                        "price": mark, "lev": tp["lev"],
                                        "detail": f"+{chg*100:.0f}% (${cur:.0f}->${tgt:.0f})"})
                    elif chg < -REBALANCE_THRESHOLD:
                        actions.append({"action": "REDUCE", "coin": coin, "side": tp["side"],
                                        "my_notional": tgt, "their_notional": tp["notional"],
                                        "price": mark, "lev": tp["lev"],
                                        "detail": f"{chg*100:.0f}% (${cur:.0f}->${tgt:.0f})"})

    # 2. Pozycje ktore JA mam, a on juz NIE -> CLOSE
    for coin, mp in my_pos.items():
        if coin not in trader_pos:
            mark = marks.get(coin, mp["entry"])
            actions.append({"action": "CLOSE", "coin": coin, "side": mp["side"],
                            "my_notional": mp["notional"], "their_notional": 0,
                            "price": mark, "lev": mp.get("lev")})
    return actions


def _sl_price(side: str, entry: float, sl_pct: float) -> float:
    """Obowiazkowy SL: % ponizej (long) / powyzej (short) ceny wejscia."""
    if side == "LONG":
        return round(entry * (1 - sl_pct / 100), 6)
    return round(entry * (1 + sl_pct / 100), 6)


# ── Wykonanie (paper) ─────────────────────────────────────────────────────────

def apply_paper(db, trader: str, actions: list[dict], ts: str) -> None:
    """Symuluj wykonanie dla jednego tradera: aktualizuj jego wirtualny portfel + zaloguj."""
    for a in actions:
        act = a["action"]
        if act == "SKIP":
            # SKIP NIE jest logowany do bazy — to ~16 wpisow/tick, puchlo do 87k+ wierszy.
            # Pomijane pozycje sa nieistotne dla analizy; jesli trzeba je policzyc,
            # robimy to na zywo w reconcile, nie w trwalym logu.
            continue
        size = a.get("size", a["my_notional"] / a["price"] if a["price"] > 0 else 0)
        sl = a.get("sl_price")
        if act in ("OPEN", "FLIP"):
            upsert_my_position(db, trader, a["coin"], a["side"], size, a["price"],
                               a["my_notional"], a.get("lev"), sl, ts)
        elif act in ("ADD", "REDUCE"):
            existing = load_my_positions(db, trader).get(a["coin"], {})
            entry = existing.get("entry", a["price"])
            old_size = float(existing.get("size", 0) or 0)
            new_size = a["my_notional"] / a["price"] if a["price"] > 0 else 0
            # REDUCE: zamykamy czesc pozycji -> realizujemy PnL na zmniejszonym kawalku
            if act == "REDUCE" and old_size > new_size > 0 and entry:
                closed_chunk = old_size - new_size
                record_realized(db, ts, trader, a["coin"], a["side"],
                                entry, a["price"], closed_chunk, "REDUCE")
            upsert_my_position(db, trader, a["coin"], a["side"], new_size, entry,
                               a["my_notional"], a.get("lev"), existing.get("sl_price", sl), ts)
        elif act == "CLOSE":
            # CLOSE: cala pozycja -> realizujemy PnL na calym rozmiarze
            existing = load_my_positions(db, trader).get(a["coin"], {})
            entry = float(existing.get("entry", a["price"]) or a["price"])
            csize = float(existing.get("size", 0) or 0)
            if csize > 0 and entry:
                record_realized(db, ts, trader, a["coin"], a["side"],
                                entry, a["price"], csize, "CLOSE")
            delete_my_position(db, trader, a["coin"])
        log_action(db, ts, trader, act, a["coin"], a["side"], a["my_notional"],
                   a["their_notional"], a["price"], a.get("lev"), sl, a.get("detail", ""))


# ── Telegram ──────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    if abs(v) >= 1_000_000: return f"${v/1e6:.2f}M"
    if abs(v) >= 1_000:     return f"${v/1e3:.1f}K"
    return f"${v:.2f}"


def send_telegram(text: str) -> None:
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            c.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                   json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        _log(f"[WARN] Telegram: {e}")


_EMOJI = {"OPEN": "🟢", "ADD": "📈", "REDUCE": "📉", "CLOSE": "✅", "FLIP": "🔄", "SKIP": "⚪"}


def report_actions(actions: list[dict], cfg: dict, label: str, acct: float, ratio: float, ts: str, capital: float | None = None) -> str:
    mode = "PAPER" if PAPER_MODE else "LIVE"
    cap = capital if capital is not None else cfg["my_capital_usd"]
    scale = f"1:{1/ratio:,.0f}" if ratio else "— (trader wyszedl do zera)"
    head = (f"🤖 <b>Copy Bot [{mode}]</b> — {ts}\n"
            f"<code>{label}</code>\n"
            f"<code>Kapital ${cap:.0f} | mult {cfg['multiplier']}x | "
            f"konto {_fmt(acct)} | skala {scale}</code>")
    real = [a for a in actions if a["action"] != "SKIP"]
    skip = [a for a in actions if a["action"] == "SKIP"]
    parts = [head, ""]
    if real:
        parts.append(f"⚡ <b>Akcje ({len(real)}):</b>")
        for a in real:
            e = _EMOJI.get(a["action"], "•")
            d = f" {a['detail']}" if a.get("detail") else ""
            sl = f" SL@{a['sl_price']:.4f}" if a.get("sl_price") else ""
            parts.append(f"  {e} <b>{a['action']} {a['coin']}</b> {a['side']}{d} — "
                         f"{_fmt(a['my_notional'])}{sl}")
    if skip:
        parts.append(f"\n⚪ <i>Pominiete (cel < min): {len(skip)}</i>")
    if not real and not skip:
        parts.append("✓ <i>Portfel zsynchronizowany — brak akcji.</i>")
    return "\n".join(parts)


# ── Run ───────────────────────────────────────────────────────────────────────

def run_once(verbose: bool = True) -> None:
    cfg = load_config()
    traders = get_traders(cfg)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db = _get_db()

    for t in traders:
        addr, label = t["address"], t.get("label", t["address"])
        try:
            acct, tpos = fetch_trader(addr)
        except Exception as e:
            _log(f"[{ts}] [{label[:18]}] Blad API ({e}) — pomijam (nie ruszam pozycji).")
            continue

        cap = trader_capital(cfg, t)
        ratio = cap / acct if acct > 0 else 0.0
        mypos = load_my_positions(db, addr)
        coins = list(set(list(tpos) + list(mypos)))
        marks = fetch_mark_prices(coins)

        actions = reconcile(acct, tpos, mypos, marks, cfg, capital=cap)
        apply_paper(db, addr, actions, ts)

        real = [a for a in actions if a["action"] != "SKIP"]
        if real:
            msg = report_actions(actions, cfg, label, acct, ratio, ts, capital=cap)
            send_telegram(msg)
            _log(msg.replace("<b>","").replace("</b>","").replace("<code>","")
                    .replace("</code>","").replace("<i>","").replace("</i>",""))
        _log(f"[{ts}] [{label[:18]}] akcji:{len(real)} skip:{len(actions)-len(real)} "
             f"portfel:{len(load_my_positions(db, addr))}")


def cmd_status() -> None:
    cfg = load_config()
    db = _get_db()
    traders = get_traders(cfg)
    print(f"\n{'='*64}\nCOPY BOT STATUS [{'PAPER' if PAPER_MODE else 'LIVE'}] — "
          f"{len(traders)} traderow | kapital ${cfg['my_capital_usd']} | mult {cfg['multiplier']}x")
    for t in traders:
        addr, label = t["address"], t.get("label", t["address"])
        mypos = load_my_positions(db, addr)
        try:
            acct, tpos = fetch_trader(addr)
        except Exception as e:
            acct, tpos = 0.0, {}; print(f"\n[{label}] blad API: {e}")
        cap = trader_capital(cfg, t)
        ratio = cap / acct if acct else 0
        scale = f"1:{1/ratio:,.0f}" if ratio else "— (na zero)"
        print(f"\n{'-'*64}\n{label}")
        print(f"  kapital ${cap:.0f} | konto {_fmt(acct)} | skala {scale}")
        print(f"  MOJ PORTFEL ({len(mypos)}): " + (
            ", ".join(f"{c} {p['side']} {_fmt(p['notional'])}" for c, p in mypos.items()) or "(pusty)"))
        if tpos:
            tgt_lines = []
            for c, p in sorted(tpos.items(), key=lambda x:-x[1]['notional'])[:6]:
                tgt = p['notional']*ratio*cfg['multiplier']
                ok = "OK" if tgt >= cfg['hl_min_notional_usd'] else "<min"
                tgt_lines.append(f"{c} {p['side']} ->{_fmt(tgt)}[{ok}]")
            print(f"  ON TRZYMA: " + ", ".join(tgt_lines))
    print(f"{'='*64}\n")


def cmd_report() -> None:
    """Ranking traderow wg PnL: zrealizowany (z bazy) + niezrealizowany (otwarte vs ceny teraz)."""
    cfg = load_config()
    db = _get_db()
    traders = get_traders(cfg)
    print(f"\n{'='*66}")
    print(f"COPY BOT — RANKING PnL [{'PAPER' if PAPER_MODE else 'LIVE'}] | "
          f"kapital ${cfg['my_capital_usd']}/trader | mult {cfg['multiplier']}x")
    okres = db._sqlite.query("SELECT MIN(ts) a, MAX(ts) b FROM copybot_actions")
    if okres and okres[0]["a"]:
        print(f"Okres: {okres[0]['a']} -> {okres[0]['b']}")
    print('='*66)

    ranking = []
    for t in traders:
        addr, label = t["address"], t.get("label", t["address"])
        # zrealizowany PnL z bazy
        rz = db._sqlite.query(
            "SELECT COALESCE(SUM(realized),0) s, COUNT(*) n, "
            "SUM(CASE WHEN realized>0 THEN 1 ELSE 0 END) w "
            "FROM copybot_pnl WHERE trader=?", (addr,))
        realized = rz[0]["s"] or 0.0
        closed_n = rz[0]["n"] or 0
        wins = rz[0]["w"] or 0
        # niezrealizowany z otwartych pozycji vs aktualne ceny
        mypos = load_my_positions(db, addr)
        unreal = 0.0
        if mypos:
            marks = fetch_mark_prices(list(mypos))
            for c, p in mypos.items():
                mk = marks.get(c, p["entry"])
                sz = float(p["size"] or 0)
                if p["side"] == "LONG":
                    unreal += (mk - p["entry"]) * sz
                else:
                    unreal += (p["entry"] - mk) * sz
        cap = trader_capital(cfg, t)
        total = realized + unreal
        # %: porownujemy wynik do kapitala TEGO tradera (rozne kwoty -> uczciwe %)
        pct = 100*total/cap if cap else 0
        total_pct = total / cap if cap else 0  # do sortowania wg % (sprawiedliwie)
        wr = f"{100*wins//closed_n}%" if closed_n else "—"
        ranking.append((total_pct, total, pct, realized, unreal, closed_n, wr, len(mypos), cap, label))

    ranking.sort(reverse=True)
    for i, (total_pct, total, pct, realized, unreal, closed_n, wr, nopen, cap, label) in enumerate(ranking, 1):
        medal = ["🥇","🥈","🥉"][i-1] if i <= 3 else f"{i}."
        sign = "+" if total >= 0 else ""
        print(f"\n{medal} {label}")
        print(f"   PnL CALKOWITY: {sign}${total:,.2f}  (na kapitale ${cap:.0f} = "
              f"{sign}{pct:.1f}%)")
        print(f"   zrealizowany: ${realized:+,.2f} ({closed_n} zamkniec, win {wr}) | "
              f"niezrealizowany (otwarte {nopen}): ${unreal:+,.2f}")
    print(f"\n{'='*66}")
    print("UWAGA: PnL paper, BEZ oplat i poslizgu. Pokazuje rzad wielkosci i ktory")
    print("trader wygrywa wzglednie. Realny wynik bedzie nizszy o ~0.09%/round-trip.")
    print('='*66 + "\n")


def cmd_reset() -> None:
    db = _get_db()
    db._sqlite.execute("DELETE FROM copybot_positions")
    db._sqlite.execute("DELETE FROM copybot_actions")
    db._sqlite.execute("DELETE FROM copybot_pnl")
    print("[copy_bot] Wszystkie wirtualne portfele + PnL wyczyszczone (start od zera).")


def main() -> None:
    p = argparse.ArgumentParser(description="Copy Bot — wlasny copy-trading HL (bez Senpi)")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()

    if not PAPER_MODE:
        print("[copy_bot] ⚠️  LIVE MODE wykryty, ale egzekucja live NIE jest jeszcze")
        print("           zaimplementowana w tym pliku (Sesja 2). Ustaw TRADING_MODE=paper.")
        sys.exit(1)

    if args.status:
        cmd_status(); return
    if args.report:
        cmd_report(); return
    if args.reset:
        cmd_reset(); return

    if args.daemon:
        cfg = load_config()
        _log(f"Copy Bot daemon [PAPER] — {cfg['trader_address'][:10]}..., interval {args.interval}s")
        while True:
            try:
                run_once(verbose=False)
            except Exception as e:
                _log(f"[ERROR] tick: {e}")
            time.sleep(args.interval)
    else:
        run_once(verbose=True)


if __name__ == "__main__":
    main()
