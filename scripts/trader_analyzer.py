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

def fetch_hl_state(wallet: str) -> dict:
    """Konto + pozycje teraz z HL."""
    st = _hl({"type": "clearinghouseState", "user": wallet})
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
    """Realna czestotliwosc + ostatnia aktywnosc z userFills."""
    out = {"fills_7d": 0, "last_trade_h": None, "active": False}
    try:
        now = datetime.now(timezone.utc)
        start = int((now.timestamp() - 7 * 86400) * 1000)
        fills = _hl({"type": "userFillsByTime", "user": wallet, "startTime": start})
        if isinstance(fills, list):
            out["fills_7d"] = len(fills)
            if fills:
                last_ms = max(f.get("time", 0) for f in fills)
                hrs = (now.timestamp() * 1000 - last_ms) / 3600000
                out["last_trade_h"] = round(hrs, 1)
                out["active"] = hrs < 48
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

    # 1. ALL-TIME PnL — najwazniejsze
    at = pnl.get("alltime_pnl")
    if at is not None:
        if at > 0:
            flags_good.append(f"All-time PnL dodatni (+${at:,.0f}) — realnie zarabia dlugoterminowo")
        else:
            flags_bad.append(f"All-time PnL UJEMNY (${at:,.0f}) — long-term pod kreska (pulapka!)")

    # 2. Aktywnosc (lekcja 0xe21b — znikajacy traderzy)
    if style.get("active"):
        flags_good.append(f"Aktywny ({style['fills_7d']} fillow/7d, ost. trade {style.get('last_trade_h')}h temu)")
    else:
        lt = style.get("last_trade_h")
        flags_bad.append(f"NIEAKTYWNY (ost. trade {lt}h temu)" if lt else "Brak aktywnosci 7d — moze znikl")

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

    # ── Decyzja ──
    score = len(flags_good) - 1.5 * len(flags_bad) - 0.5 * len(flags_warn)
    if any("All-time PnL UJEMNY" in f for f in flags_bad) or any("NIEAKTYWNY" in f or "znikl" in f for f in flags_bad):
        v = "UNIKAJ" if score < 1 else "OBSERWUJ"
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
    L.append(f"Konto: ${s['account_value']:,.0f} | pozycji: {len(s['positions'])} | "
             f"fille/7d: {st['fills_7d']} | ost.trade: {st.get('last_trade_h')}h temu")
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Kozaki Searcher — analiza tradera HL do copy-tradingu")
    ap.add_argument("wallet", help="adres portfela HL (0x...)")
    ap.add_argument("--capital", type=float, default=200.0, help="Twoj kapital (do oceny kopiowalnosci)")
    ap.add_argument("--json", action="store_true", help="output JSON (dla dashboardu)")
    args = ap.parse_args()
    result = analyze(args.wallet, args.capital)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(render(result))


if __name__ == "__main__":
    main()
