"""trader_analyzer.py — Kozaki Searcher: wklej adres -> werdykt copy-trading.

Laczy dane Senpi MCP (przez HTTP, bez sesji Claude) + publiczne HL API w jedna analize:
  - track record (ROI, win rate, max DD, gain-to-pain, etykiety) — Senpi discovery
  - KRZYWA ALL-TIME PnL (klucz! ujawnia ukryte straty) — HL portfolio
  - pozycje teraz + dzwignie — HL clearinghouseState
  - styl handlu (czestotliwosc realnych zamkniec, mediana trzymania) — HL userFills

Werdykt: KOPIUJ / OBSERWUJ / UNIKAJ — wg lekcji wypracowanych w projekcie:
  - dodatni all-time PnL + niski REALNY drawdown + sensowna czestotliwosc = KOPIUJ
  - wysoki win rate sam w sobie = pulapka (bag-holder)
  - maxDrawdown z rankingu klamie (waskie okno) -> liczymy z krzywej all-time
  - averageTradesPerDay liczy fille, nie decyzje -> realne z userFills

Usage:
    python scripts/trader_analyzer.py 0x83b00972aafcc3d06d45b1b823079f9a414da46e
    python scripts/trader_analyzer.py 0x... --json        # output JSON (dla dashboardu)
    python scripts/trader_analyzer.py 0x... --capital 200 # sugerowany mnoznik dla kapitalu

Senpi token: SENPI_AUTH_TOKEN w .env. Dziala bez Senpi (degraduje do samego HL API).
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from datetime import datetime, timezone

import httpx
import truststore
from dotenv import load_dotenv
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv(Path(__file__).parent.parent / ".env")
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
HL_API = "https://api.hyperliquid.xyz/info"
SENPI_URL = "https://mcp.prod.senpi.ai/mcp"
SENPI_TOKEN = os.getenv("SENPI_AUTH_TOKEN", "")


# ── HL public API ─────────────────────────────────────────────────────────────

def _hl(payload: dict):
    with httpx.Client(verify=_SSL, timeout=20) as c:
        r = c.post(HL_API, json=payload)
        r.raise_for_status()
        return r.json()


# ── Senpi MCP (HTTP JSON-RPC, bez sesji Claude) ───────────────────────────────

def _senpi_call(tool: str, arguments: dict) -> dict | None:
    """Wolaj narzedzie Senpi MCP. Zwraca dict z danymi lub None gdy niedostepne."""
    if not SENPI_TOKEN:
        return None
    H = {"Authorization": f"Bearer {SENPI_TOKEN}",
         "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}

    def parse(r):
        ct = r.headers.get("content-type", "")
        if "event-stream" in ct:
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            return {}
        return r.json()

    try:
        with httpx.Client(verify=_SSL, timeout=30) as c:
            init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "analyzer", "version": "1.0"}}}
            r = c.post(SENPI_URL, json=init, headers=H)
            sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
            H2 = dict(H)
            if sid:
                H2["mcp-session-id"] = sid
            c.post(SENPI_URL, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=H2)
            call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments}}
            r = c.post(SENPI_URL, json=call, headers=H2)
            res = parse(r)
            if "result" in res:
                content = res["result"].get("content", [])
                if content and content[0].get("type") == "text":
                    return json.loads(content[0]["text"])
    except Exception:
        return None
    return None


# ── Zbieranie danych ──────────────────────────────────────────────────────────

def _parse_state(st: dict) -> tuple[float, list[dict]]:
    """Wyciagnij (account_value, pozycje) z jednego clearinghouseState."""
    if not isinstance(st, dict):
        return 0.0, []
    acct = float(st.get("marginSummary", {}).get("accountValue", "0"))
    positions = []
    for pw in st.get("assetPositions", []):
        p = pw.get("position", {})
        szi = float(p.get("szi", "0"))
        if szi == 0:
            continue
        positions.append({
            "coin": p.get("coin", "?"),
            "side": "LONG" if szi > 0 else "SHORT",
            "notional": float(p.get("positionValue", "0")),
            "lev": int(p.get("leverage", {}).get("value", 1)),
            "upnl": float(p.get("unrealizedPnl", "0")),
        })
    return acct, positions


def fetch_hl_state(wallet: str) -> dict:
    """Konto + pozycje teraz z HL — main perp dex ORAZ xyz dex (tokenizowane akcje).

    Traderzy moga trzymac pozycje na osobnym dex 'xyz' (xyz:MU itd.) — main
    clearinghouseState ich nie zwraca. Scalamy oba: konto = suma sald, pozycje laczone.
    Bez tego trader na akcjach pokazuje falszywe Konto $0 / 0 pozycji.
    """
    acct, positions = _parse_state(_hl({"type": "clearinghouseState", "user": wallet}))
    try:
        xyz_acct, xyz_pos = _parse_state(
            _hl({"type": "clearinghouseState", "user": wallet, "dex": "xyz"}))
        acct += xyz_acct
        positions += xyz_pos
    except Exception:
        pass  # brak xyz dex -> sam main
    positions.sort(key=lambda x: -x["notional"])
    return {"account_value": acct, "positions": positions}


def fetch_alltime_pnl(wallet: str) -> dict:
    """Krzywa all-time PnL — KLUCZ do wykrycia ukrytych strat."""
    out = {"alltime_pnl": None, "week_pnl": None, "peak": None, "trough": None}
    try:
        pf = _hl({"type": "portfolio", "user": wallet})
        for period, data in pf:
            pnlh = data.get("pnlHistory", [])
            if not pnlh:
                continue
            vals = [float(v) for _, v in pnlh]
            if period == "allTime":
                out["alltime_pnl"] = vals[-1]
                out["peak"] = max(vals)
                out["trough"] = min(vals)
            elif period == "week":
                out["week_pnl"] = vals[-1] - vals[0]
    except Exception:
        pass
    return out


def fetch_trade_style(wallet: str) -> dict:
    """Aktywnosc + czestotliwosc w oknie 30 dni (szerszy zakres niz dzisiejsze pozycje).

    Klucz: liczymy REALNE ZAMKNIECIA (closedPnl != 0 = decyzje), nie surowe fille
    (drabinki zawyzaja). Plus aktywne dni — czy handluje regularnie czy zrywami.
    """
    out = {"fills_7d": 0, "fills_30d": 0, "closes_30d": 0, "active_days_30d": 0,
           "last_trade_h": None, "active": False, "closes_per_week": 0.0,
           "roundtrips_30d": 0, "roundtrips_per_week": 0.0, "median_hold_h": None}
    try:
        now = datetime.now(timezone.utc)
        now_ms = now.timestamp() * 1000
        start30 = int(now_ms - 30 * 86400 * 1000)
        fills = _hl({"type": "userFillsByTime", "user": wallet, "startTime": start30})
        if isinstance(fills, list) and fills:
            out["fills_30d"] = len(fills)
            # fille z ostatnich 7d (do oceny "swiezosci")
            cutoff7 = now_ms - 7 * 86400 * 1000
            out["fills_7d"] = sum(1 for f in fills if f.get("time", 0) >= cutoff7)
            # realne zamkniecia = decyzje (closedPnl != 0)
            closes = [f for f in fills if abs(float(f.get("closedPnl", "0") or 0)) > 0]
            out["closes_30d"] = len(closes)
            out["closes_per_week"] = round(len(closes) / (30 / 7), 1)
            # aktywne dni (ile roznych dni handlowal — regularnosc vs zrywy)
            days = {datetime.fromtimestamp(f.get("time", 0) / 1000, timezone.utc).date()
                    for f in fills}
            out["active_days_30d"] = len(days)
            # ostatnia aktywnosc
            last_ms = max(f.get("time", 0) for f in fills)
            hrs = (now_ms - last_ms) / 3600000
            out["last_trade_h"] = round(hrs, 1)
            out["active"] = hrs < 48

            # PRAWDZIWE round-tripy + czas trzymania — KLUCZ do odroznienia
            # scalpingu (krotkie trzymanie) od drabinkowania (duzo czesciowych zamkniec,
            # dlugie trzymanie). Rekonstruujemy pozycje per coin z filli (side B/A).
            bycoin: dict[str, list] = {}
            for f in fills:
                bycoin.setdefault(f.get("coin", "?"), []).append(f)
            holds: list[float] = []
            roundtrips = 0
            for coin, fs in bycoin.items():
                fs = sorted(fs, key=lambda x: x.get("time", 0))
                pos = 0.0
                open_t = None
                for f in fs:
                    sz = float(f.get("sz", "0") or 0)
                    signed = sz if f.get("side") == "B" else -sz
                    prev = pos
                    if prev == 0 and signed != 0:
                        open_t = f.get("time")
                    pos = round(prev + signed, 8)
                    # pelne zamkniecie (pozycja do zera) lub flip kierunku = round-trip
                    if prev != 0 and (pos == 0 or (prev > 0) != (pos > 0)):
                        roundtrips += 1
                        if open_t:
                            holds.append((f.get("time", 0) - open_t) / 3600000)
                        open_t = f.get("time") if pos != 0 else None
            out["roundtrips_30d"] = roundtrips
            out["roundtrips_per_week"] = round(roundtrips / (30 / 7), 1)
            if holds:
                holds.sort()
                out["median_hold_h"] = round(holds[len(holds) // 2], 1)
    except Exception:
        pass
    return out


def fetch_senpi_track(wallet: str) -> dict | None:
    """Track record z Senpi discovery (ROI, win rate, gain-to-pain, etykiety)."""
    data = _senpi_call("discovery_get_top_traders",
                       {"time_frame": "MONTHLY", "addresses": [wallet], "limit": 1})
    if not data:
        return None
    traders = data.get("data", {}).get("traders", [])
    if not traders:
        return None
    t = traders[0]
    return {
        "roi": t.get("returnOnInvestment"),
        "win_rate": t.get("winRate"),
        "max_dd_ranking": t.get("maxDrawdown"),
        "gain_to_pain": t.get("gainToPainRatio"),
        "avg_trades_day": t.get("averageTradesPerDay"),
        "avg_lev": t.get("averageLeverageUsed"),
        "activity": t.get("activityLabel"),
        "consistency": t.get("tcsLabel"),
        "risk": t.get("riskLabel"),
    }


# ── Werdykt ────────────────────────────────────────────────────────────────────

def verdict(state, pnl, style, track, capital, min_notional=10.0) -> dict:
    """Zbuduj werdykt KOPIUJ/OBSERWUJ/UNIKAJ + uzasadnienie wg lekcji projektu."""
    flags_good, flags_bad, flags_warn = [], [], []
    n_positions = len(state["positions"])

    # 1. ALL-TIME PnL — najwazniejsze
    at = pnl.get("alltime_pnl")
    if at is not None:
        if at > 0:
            flags_good.append(f"All-time PnL dodatni (+${at:,.0f}) — realnie zarabia dlugoterminowo")
        else:
            flags_bad.append(f"All-time PnL UJEMNY (${at:,.0f}) — long-term pod kreska (pulapka!)")

    # 2. Aktywnosc + REGULARNOSC 30d (szerszy zakres — "2 pozycje dzis != martwy")
    closes30 = style.get("closes_30d", 0)
    days30 = style.get("active_days_30d", 0)
    last_h = style.get("last_trade_h")
    cpw = style.get("closes_per_week", 0)

    # 2a. SCALPING vs DRABINKOWANIE — kluczem jest CZAS TRZYMANIA, nie liczba zamkniec.
    # Scalper trzyma minuty (polling 60s nie wejdzie+wyjdzie w jego oknie).
    # Drabinkowicz/pozycyjny trzyma godziny-dni mimo wielu czesciowych zamkniec -> kopiowalny.
    # (Lekcja: 0x67a7 mial 235 "zamkniec"/tydz ALE mediana trzymania 40-77h = drabinkowanie, nie scalping.)
    mh = style.get("median_hold_h")              # mediana trzymania round-tripu (h)
    rtpw = style.get("roundtrips_per_week", 0)   # PRAWDZIWE round-tripy/tydz (nie czesciowe zamkniecia)
    is_scalper = mh is not None and mh < 1.0 and rtpw > 20
    if is_scalper:
        flags_bad.append(
            f"SCALPER — mediana trzymania {mh}h, {rtpw} round-tripow/tydz: "
            f"polling 60s nie wejdzie+wyjdzie w jego oknie; obserwuj, ale NIE kopiuj automatycznie")
    elif cpw > 50 and (mh is None or mh >= 1.0):
        hold_txt = f"mediana trzymania {mh}h" if mh is not None else "dlugie trzymanie (brak pelnych zamkniec w oknie)"
        flags_warn.append(
            f"Drabinkowanie: {cpw} czesciowych zamkniec/tydz, ale {hold_txt} — "
            f"skaluje pozycje, NIE scalpuje. Copy nadazy za kierunkiem.")
    elif rtpw > 20:
        flags_warn.append(
            f"Wysoka czestotliwosc: {rtpw} round-tripow/tydz — krotsze pozycje moga uciec przed polling cycle")

    if style.get("active"):
        flags_good.append(
            f"Aktywny: {closes30} zamkniec/30d (~{cpw}/tydz), "
            f"handlowal w {days30}/30 dni, ost. trade {last_h}h temu")
        if days30 >= 15:
            flags_good.append(f"Regularny — handluje wiekszosc dni ({days30}/30)")
        elif days30 <= 5 and closes30 > 0:
            flags_warn.append(f"Zrywami — aktywny tylko {days30}/30 dni (dlugie przerwy)")
    else:
        if last_h and last_h < 168:  # <7 dni
            flags_warn.append(f"Cisza od {last_h}h, ale {closes30} zamkniec/30d — moze robic przerwe")
        elif n_positions > 0:
            # Ma otwarte pozycje mimo dawnego filla — aktywnie trzyma i zarzadza ryzykiem.
            # SIZE INCREASE przez zmiane ceny / drabinkowanie nie zawsze tworzy nowy fill w API.
            flags_warn.append(
                f"Dawny fill ({last_h:.0f}h temu), ale trzyma {n_positions} otwart"
                f"{'a' if n_positions == 1 else 'e'} pozycj"
                f"{'e' if n_positions == 1 else 'e'} — aktywnie zarzadza, nie martwy")
        else:
            flags_bad.append(
                f"NIEAKTYWNY (ost. trade {last_h}h temu, brak pozycji)" if last_h
                else "Brak aktywnosci 30d i brak pozycji — moze znikl")

    # 3. Kopiowalnosc przy danym kapitale
    acct = state["account_value"]
    npos = len(state["positions"])
    if acct > 0 and npos:
        ratio = capital / acct
        copyable = sum(1 for p in state["positions"] if p["notional"] * ratio >= min_notional)
        pct = 100 * copyable // npos
        if pct >= 70:
            flags_good.append(f"Kopiowalny: {copyable}/{npos} pozycji ({pct}%) za ${capital:.0f}")
        elif pct >= 40:
            flags_warn.append(f"Czesciowo kopiowalny: {copyable}/{npos} ({pct}%) za ${capital:.0f} — rozwaz wiekszy kapital")
        else:
            flags_bad.append(f"Slabo kopiowalny: {copyable}/{npos} ({pct}%) za ${capital:.0f} — za male konto/za duzo pozycji")
    elif acct <= 0:
        flags_bad.append("Konto puste ($0) — nic do kopiowania teraz")

    # 4. Track record z Senpi (jesli dostepny)
    if track:
        wr = track.get("win_rate")
        g2p = track.get("gain_to_pain")
        if g2p and g2p >= 5:
            flags_good.append(f"Gain-to-Pain {g2p:.0f} (gladka krzywa zysku)")
        if wr and wr >= 90 and at is not None and at < 0:
            flags_warn.append(f"Win rate {wr:.0f}% ALE all-time ujemny = klasyczny bag-holder")
        if track.get("consistency") == "ELITE":
            flags_good.append("Senpi: ELITE consistency")

    # 5. Liczba pozycji (prostota = lepsza dla copy)
    if 1 <= npos <= 5:
        flags_good.append(f"Prosty portfel ({npos} poz) — latwy do wiernego kopiowania")
    elif npos > 15:
        flags_warn.append(f"Zlozony portfel ({npos} poz) — wymaga wiekszego kapitalu")

    # 6. SWIEZOSC pozycji — KLUCZ do copy (lekcja z paper tradingu).
    # Trader moze miec swietny track record, ale jesli teraz SIEDZI na starych winnerach
    # (pozycje gleboko w zysku), to ten zysk jest ZABLOKOWANY w jego starym entry.
    # Late copier wchodzi po cenie rynkowej -> nie zlapie tego ruchu, tylko przyszle.
    # Dowod: 0xa4be (WR93%, SOL-S +22%/BTC-S +15%) dal 0% win w naszym copy.
    # Miara: upnl/notional = jaki % ruchu trader JUZ zlapal (a my juz nie).
    deep_winners, fresh = [], []
    for p in state["positions"]:
        if p["notional"] <= 0:
            continue
        moved_pct = 100 * p["upnl"] / p["notional"]
        if moved_pct >= 8:
            deep_winners.append((p["coin"], moved_pct))
        elif abs(moved_pct) <= 3:
            fresh.append(p["coin"])
    # "stale_dominant" = co najmniej polowa pozycji to stare winnery
    stale_dominant = bool(deep_winners) and 2 * len(deep_winners) >= npos
    if deep_winners:
        names = ", ".join(f"{c} +{pct:.0f}%" for c, pct in deep_winners)
        flags_warn.append(
            f"Stare winnery: {names} (ruch juz zrobiony) — wchodzisz PO ruchu; "
            f"copy zlapie tylko PRZYSZLE ruchy, nie ten zablokowany zysk")
    if fresh and not stale_dominant:
        flags_good.append(
            f"Swieze pozycje ({', '.join(fresh)}) blisko entry — copy wejdzie w ta sama cene")

    # ── Decyzja ──
    score = len(flags_good) - 1.5 * len(flags_bad) - 0.5 * len(flags_warn)
    has_ujemny  = any("All-time PnL UJEMNY" in f for f in flags_bad)
    has_martwy  = any("NIEAKTYWNY" in f or "znikl" in f for f in flags_bad)

    if has_ujemny or has_martwy:
        v = "UNIKAJ" if score < 1 else "OBSERWUJ"
    elif is_scalper:
        # Scalper: nawet jesli zarabia — nie da sie wiernie kopiowac polling systemem.
        # Jesli all-time+ i aktywny: wart obserwacji jako inspiracja, ale nie auto-copy.
        v = "OBSERWUJ" if score >= 2 else "UNIKAJ"
    elif stale_dominant:
        # Track record moze byc swietny, ale teraz siedzi na starych winnerach —
        # late copier nie zlapie zablokowanego zysku. Max OBSERWUJ (czekaj na swieze entry).
        v = "OBSERWUJ" if score >= 1 else "UNIKAJ"
    elif score >= 3:
        v = "KOPIUJ"
    elif score >= 1:
        v = "OBSERWUJ"
    else:
        v = "UNIKAJ"

    return {"verdict": v, "good": flags_good, "bad": flags_bad, "warn": flags_warn}


# ── Analiza glowna ─────────────────────────────────────────────────────────────

def analyze(wallet: str, capital: float = 200.0) -> dict:
    wallet = wallet.strip().lower()
    if not (wallet.startswith("0x") and len(wallet) == 42):
        return {"error": f"Nieprawidlowy adres: {wallet!r} (oczekiwano 0x + 40 znakow hex)"}
    state = fetch_hl_state(wallet)
    pnl = fetch_alltime_pnl(wallet)
    style = fetch_trade_style(wallet)
    track = fetch_senpi_track(wallet)
    v = verdict(state, pnl, style, track, capital)
    return {
        "wallet": wallet,
        "short": f"{wallet[:6]}...{wallet[-4:]}",
        "capital": capital,
        "state": state,
        "pnl": pnl,
        "style": style,
        "track": track,
        "senpi_available": track is not None,
        **v,
    }


# ── Render tekstowy (CLI) ──────────────────────────────────────────────────────

_VERDICT_EMOJI = {"KOPIUJ": "🟢 KOPIUJ", "OBSERWUJ": "🟡 OBSERWUJ", "UNIKAJ": "🔴 UNIKAJ"}


def render(a: dict) -> str:
    if "error" in a:
        return f"BLAD: {a['error']}"
    L = []
    L.append("=" * 64)
    L.append(f"KOZAKI SEARCHER — {a['short']}  (kapital ${a['capital']:.0f})")
    L.append("=" * 64)
    L.append(f"\nWERDYKT: {_VERDICT_EMOJI.get(a['verdict'], a['verdict'])}\n")
    s, p, st, tr = a["state"], a["pnl"], a["style"], a["track"]
    L.append(f"Konto: ${s['account_value']:,.0f} | pozycji teraz: {len(s['positions'])} | "
             f"ost.trade: {st.get('last_trade_h')}h temu")
    L.append(f"30 dni: {st.get('closes_30d',0)} zamkniec (~{st.get('closes_per_week',0)}/tydz) | "
             f"handlowal w {st.get('active_days_30d',0)}/30 dni | fille/7d: {st['fills_7d']}")
    if p.get("alltime_pnl") is not None:
        L.append(f"All-time PnL: ${p['alltime_pnl']:+,.0f} (szczyt ${p.get('peak',0):+,.0f} / "
                 f"dno ${p.get('trough',0):+,.0f}) | tydzien: ${p.get('week_pnl') or 0:+,.0f}")
    if tr:
        L.append(f"Senpi: ROI {tr.get('roi',0):.1f} | WR {tr.get('win_rate',0):.0f}% | "
                 f"G2P {tr.get('gain_to_pain',0):.0f} | {tr.get('activity')}/{tr.get('consistency')}/{tr.get('risk')}")
    else:
        L.append("Senpi: (niedostepny — analiza z samego HL API)")
    if s["positions"]:
        L.append("\nPozycje teraz:")
        for pos in s["positions"][:8]:
            L.append(f"  {pos['coin']:8} {pos['side']:5} ${pos['notional']:>12,.0f} {pos['lev']}x  uPnL ${pos['upnl']:+,.0f}")
    L.append("")
    for f in a["good"]:
        L.append(f"  ✅ {f}")
    for f in a["warn"]:
        L.append(f"  ⚠️  {f}")
    for f in a["bad"]:
        L.append(f"  ❌ {f}")
    L.append("=" * 64)
    return "\n".join(L)


def to_markdown(a: dict) -> str:
    """Raport MD do zapisu w reports/research/kozaki/."""
    if "error" in a:
        return f"# Kozaki Searcher — BLAD\n\n{a['error']}\n"
    s, p, st, tr = a["state"], a["pnl"], a["style"], a["track"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# 🔎 Kozaki Searcher — {a['short']}", "",
         f"**Werdykt: {a['verdict']}** · kapital ${a['capital']:.0f} · {now}", "",
         f"- Adres: `{a['wallet']}`",
         f"- Konto: ${s['account_value']:,.0f} | pozycji teraz: {len(s['positions'])} | ost.trade: {st.get('last_trade_h')}h temu",
         f"- 30 dni: {st.get('closes_30d',0)} zamkniec (~{st.get('closes_per_week',0)}/tydz), handlowal w {st.get('active_days_30d',0)}/30 dni"]
    if p.get("alltime_pnl") is not None:
        L.append(f"- All-time PnL: ${p['alltime_pnl']:+,.0f} (szczyt ${p.get('peak',0):+,.0f} / dno ${p.get('trough',0):+,.0f}) | tydzien ${p.get('week_pnl') or 0:+,.0f}")
    if tr:
        L.append(f"- Senpi: ROI {tr.get('roi',0):.1f} · WR {tr.get('win_rate',0):.0f}% · G2P {tr.get('gain_to_pain',0):.0f} · {tr.get('activity')}/{tr.get('consistency')}/{tr.get('risk')}")
    L += ["", "## Sygnaly", ""]
    for f in a["good"]: L.append(f"- ✅ {f}")
    for f in a["warn"]: L.append(f"- ⚠️ {f}")
    for f in a["bad"]:  L.append(f"- ❌ {f}")
    if s["positions"]:
        L += ["", "## Pozycje teraz", "", "| Coin | Strona | Notional | Lev | uPnL |", "|---|---|---|---|---|"]
        for pos in s["positions"][:12]:
            L.append(f"| {pos['coin']} | {pos['side']} | ${pos['notional']:,.0f} | {pos['lev']}x | ${pos['upnl']:+,.0f} |")
    return "\n".join(L) + "\n"


def save_report(a: dict) -> str | None:
    """Zapisz raport MD do reports/research/kozaki/. Zwraca nazwe pliku."""
    if "error" in a:
        return None
    d = Path(__file__).parent.parent / "reports" / "research" / "kozaki"
    d.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fname = f"{a['short'].replace('...','-')}_{a['verdict']}_{date}.md"
    (d / fname).write_text(to_markdown(a), encoding="utf-8")
    return fname


def main() -> None:
    ap = argparse.ArgumentParser(description="Kozaki Searcher — analiza tradera HL do copy-tradingu")
    ap.add_argument("wallet", help="adres portfela HL (0x...)")
    ap.add_argument("--capital", type=float, default=200.0, help="Twoj kapital (do oceny kopiowalnosci)")
    ap.add_argument("--json", action="store_true", help="output JSON (dla dashboardu)")
    ap.add_argument("--save", action="store_true", help="zapisz raport MD do reports/research/kozaki/")
    args = ap.parse_args()
    result = analyze(args.wallet, args.capital)
    if args.save:
        fname = save_report(result)
        if fname:
            result["saved_file"] = fname
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(render(result))
        if result.get("saved_file"):
            print(f"\n[zapisano] reports/research/kozaki/{result['saved_file']}")


if __name__ == "__main__":
    main()
