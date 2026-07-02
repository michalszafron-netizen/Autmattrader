"""collector.py — ScalpBot3 Faza 0 kolektor (samowystarczalny, VPS-ready).

Zbiera ROWNOLEGLE z timestampami ms:
  • Pyth Hermes  — szybka referencja: GOLD, SILVER, CL(WTI), SP500   (dla strategii A)
  • HL xyz       — allMids dex=xyz: xyz:GOLD/SILVER/SP500/CL          (dla strategii A)
  • HL perp      — allMids: BTC, ETH, SOL, HYPE                       (dla strategii B)
  • Extended     — mark + funding: BTC/ETH/SOL/HYPE                   (dla strategii B)

Zero importow ze scripts/ — dziala identycznie na Windows (test) i Linux VPS (produkcja).
Wynik -> data/scalpbot3.db (wlasna baza, nie dotyka db.py).

Uzycie:
    python collector.py                 # zbieraj (Ctrl+C konczy)
    python collector.py --resolve-only  # tylko rozwiaz Pyth id i wyjdz (diagnostyka)
    python collector.py --stats         # podglad zebranych danych + snapshot basis/spread
"""

from __future__ import annotations

import argparse
import ssl
import sys
import threading
import time
from datetime import datetime, timezone

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from store import Store, read_con, DB_PATH

# ── Endpointy (publiczne, bez auth) ──────────────────────────────────────────
HL_API   = "https://api.hyperliquid.xyz/info"
PYTH_API = "https://hermes.pyth.network"
EXT_API  = "https://api.starknet.extended.exchange"

# ── Mapy aktywow ─────────────────────────────────────────────────────────────
# Pyth: kanoniczny asset -> (query do katalogu, DOKLADNY symbol Pyth do dopasowania)
# Dokladne symbole zweryfikowane 2026-07-02 na hermes.pyth.network/v2/price_feeds.
# CL  = ciagly spot WTI (nie datowany futures WTIQ6 — ten ma baze/rollover).
# SP500 = E-mini S&P futures (poziom indeksu, ~24h, dokladnie to co sledzi HL xyz:SP500).
PYTH_QUERIES = {
    "GOLD":   ("XAU/USD", "Metal.XAU/USD"),
    "SILVER": ("XAG/USD", "Metal.XAG/USD"),
    "CL":     ("USOIL",   "Commodities.USOILSPOT"),
    # UWAGA: Pyth NIE ma czystego indeksu S&P ani E-mini futures w USD.
    # Jedyna sensowna referencja to SPY ETF (~1/10 poziomu indeksu, godziny US +.PRE/.ON/.POST).
    # Skala rozni sie x10 od HL xyz:SP500 — to OK: lag/edge liczymy na ZWROTACH %, nie cenie
    # bezwzglednej. SPY handluje w sesji US, czyli dokladnie gdy uderzaja CPI/NFP/FOMC (okno A).
    "SP500":  ("SPY",     "Equity.US.SPY/USD"),
}
# Aktywa gdzie skala Pyth != HL xyz (analiza tylko na zwrotach, nie na spreadzie bezwzglednym).
RETURNS_ONLY = {"SP500"}
# HL xyz: kanoniczny -> klucz w allMids(dex=xyz)
HL_XYZ = {"GOLD": "xyz:GOLD", "SILVER": "xyz:SILVER", "SP500": "xyz:SP500", "CL": "xyz:CL"}
# HL perp: kanoniczny -> klucz w allMids (crypto dla strategii B)
HL_PERP = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "HYPE": "HYPE"}
# Extended: kanoniczny -> prefix nazwy rynku (resolver dopasuje '<prefix>-...')
EXT_PREFIX = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "HYPE": "HYPE"}

# ── Cadencje (ms) ────────────────────────────────────────────────────────────
PYTH_MS = 250
HL_MS   = 300
EXT_MS  = 1000
HEARTBEAT_S = 30


def _ssl_ctx():
    """truststore na Windows (CA store), certifi default na Linux VPS."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return True  # httpx uzyje domyslnego certifi


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── Pyth: rozwiaz feed id po symbolu ─────────────────────────────────────────

def resolve_pyth_ids(client: httpx.Client) -> dict[str, dict]:
    """Zwraca {asset: {'id':..., 'symbol':..., 'query':...}} — rozwiazane runtime.

    Robimy to dynamicznie zeby nie zgadywac hex-idow. Kazde rozwiazanie logujemy
    i zapisujemy do meta — pierwszy run = weryfikacja, ze trafilismy w te aktywa.
    """
    out: dict[str, dict] = {}
    for asset, (query, exact) in PYTH_QUERIES.items():
        try:
            r = client.get(f"{PYTH_API}/v2/price_feeds", params={"query": query})
            r.raise_for_status()
            feeds = r.json()
        except Exception as e:
            print(f"[pyth] resolve '{query}' error: {e}")
            continue
        match = next((f for f in feeds
                      if (f.get("attributes", {}).get("symbol") or "") == exact), None)
        if match:
            fid = match["id"]
            print(f"[pyth] {asset:6s} -> {exact:24s} id={fid[:14]}…")
            out[asset] = {"id": fid, "symbol": exact, "query": query}
        else:
            avail = [f.get("attributes", {}).get("symbol") for f in feeds][:8]
            print(f"[pyth] {asset:6s} -> BRAK dokladnego '{exact}' (dostepne: {avail})")
    return out


# ── Pollery ──────────────────────────────────────────────────────────────────

class Poller(threading.Thread):
    def __init__(self, name: str, stop: threading.Event):
        super().__init__(name=name, daemon=True)
        self.stop = stop
        self.client = httpx.Client(verify=_ssl_ctx(), timeout=10,
                                   headers={"User-Agent": "scalpbot3-collector"})
        self.err_streak = 0

    def _sleep(self, ms: int):
        self.stop.wait(ms / 1000)

    def _backoff(self):
        self.err_streak += 1
        self.stop.wait(min(self.err_streak, 10))  # do 10s

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass


class PythPoller(Poller):
    def __init__(self, stop, store: Store, ids: dict[str, dict]):
        super().__init__("pyth", stop)
        self.store = store
        self.ids = ids
        self.id2asset = {v["id"]: a for a, v in ids.items()}
        self.id2sym = {v["id"]: v["symbol"] for a, v in ids.items()}

    def run(self):
        if not self.ids:
            print("[pyth] brak rozwiazanych idow — poller nieaktywny")
            return
        params = [("ids[]", v["id"]) for v in self.ids.values()] + [("parsed", "true")]
        url = f"{PYTH_API}/v2/updates/price/latest"
        while not self.stop.is_set():
            try:
                r = self.client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
                ts = _now_ms()
                for p in data.get("parsed", []):
                    fid = "0x" + p["id"] if not p["id"].startswith("0x") else p["id"]
                    asset = self.id2asset.get(fid) or self.id2asset.get(p["id"])
                    if not asset:
                        continue
                    pr = p.get("price", {})
                    px = float(pr["price"]) * (10 ** int(pr["expo"]))
                    src_ts = int(pr.get("publish_time", 0)) * 1000 or None
                    self.store.push_tick("pyth", asset, self.id2sym.get(fid, asset), px, ts, src_ts)
                self.err_streak = 0
                self._sleep(PYTH_MS)
            except Exception as e:
                if self.err_streak == 0:
                    print(f"[pyth] error: {e}")
                self._backoff()
        self.close()


class HLPoller(Poller):
    """Jeden poller na dwa strzaly: allMids(dex=xyz) + allMids() crypto."""
    def __init__(self, stop, store: Store):
        super().__init__("hl", stop)
        self.store = store

    def run(self):
        while not self.stop.is_set():
            try:
                ts = _now_ms()
                # xyz TradFi
                rx = self.client.post(HL_API, json={"type": "allMids", "dex": "xyz"})
                rx.raise_for_status()
                mx = rx.json()
                for asset, key in HL_XYZ.items():
                    v = mx.get(key)
                    if v:
                        self.store.push_tick("hl_xyz", asset, key, float(v), ts)
                # crypto perp
                ts2 = _now_ms()
                rc = self.client.post(HL_API, json={"type": "allMids"})
                rc.raise_for_status()
                mc = rc.json()
                for asset, key in HL_PERP.items():
                    v = mc.get(key)
                    if v:
                        self.store.push_tick("hl_perp", asset, key, float(v), ts2)
                self.err_streak = 0
                self._sleep(HL_MS)
            except Exception as e:
                if self.err_streak == 0:
                    print(f"[hl] error: {e}")
                self._backoff()
        self.close()


class ExtendedPoller(Poller):
    def __init__(self, stop, store: Store):
        super().__init__("extended", stop)
        self.store = store
        self.market_map: dict[str, str] = {}  # asset -> market name

    def _resolve_markets(self):
        try:
            r = self.client.get(f"{EXT_API}/api/v1/info/markets")
            r.raise_for_status()
            data = r.json()
            markets = data if isinstance(data, list) else data.get("data", data.get("markets", []))
            for asset, prefix in EXT_PREFIX.items():
                m = next((mm for mm in markets
                          if str(mm.get("name", "")).upper().startswith(prefix.upper() + "-")), None)
                if m:
                    self.market_map[asset] = m["name"]
            print(f"[extended] rynki: {self.market_map}")
        except Exception as e:
            print(f"[extended] resolve markets error: {e}")

    def run(self):
        self._resolve_markets()
        while not self.stop.is_set():
            try:
                r = self.client.get(f"{EXT_API}/api/v1/info/markets")
                r.raise_for_status()
                data = r.json()
                markets = data if isinstance(data, list) else data.get("data", data.get("markets", []))
                by_name = {str(m.get("name", "")): m for m in markets}
                ts = _now_ms()
                for asset, name in self.market_map.items():
                    m = by_name.get(name)
                    if not m:
                        continue
                    s = m.get("marketStats", {}) or {}
                    mark = s.get("markPrice") or m.get("markPrice")
                    fr = s.get("fundingRate") or m.get("fundingRate")
                    idx = s.get("indexPrice") or m.get("indexPrice")
                    if mark:
                        self.store.push_tick("extended", asset, name, float(mark), ts)
                    self.store.push_funding("extended", asset, name, ts,
                                            float(fr) if fr not in (None, "") else None,
                                            float(mark) if mark else None,
                                            float(idx) if idx else None)
                self.err_streak = 0
                self._sleep(EXT_MS)
            except Exception as e:
                if self.err_streak == 0:
                    print(f"[extended] error: {e}")
                self._backoff()
        self.close()


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def heartbeat_loop(stop: threading.Event, store: Store, t0: float):
    while not stop.is_set():
        stop.wait(HEARTBEAT_S)
        if stop.is_set():
            break
        c = store.counts()
        mins = (time.time() - t0) / 60
        total = sum(c.values())
        parts = " ".join(f"{k}={v}" for k, v in sorted(c.items()))
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{now}Z] +{mins:5.1f}min  total={total}  {parts}")


# ── Main collect ────────────────────────────────────────────────────────────

def collect(resolve_only: bool = False):
    print(f"ScalpBot3 collector — DB: {DB_PATH}")
    print(f"SSL: {'truststore' if _ssl_ctx() is not True else 'certifi(default)'}")

    with httpx.Client(verify=_ssl_ctx(), timeout=15,
                      headers={"User-Agent": "scalpbot3-collector"}) as c:
        pyth_ids = resolve_pyth_ids(c)

    if resolve_only:
        print("\n--resolve-only: koniec (nic nie zbieram).")
        return

    store = Store()
    store.start()
    store.set_meta("pyth_ids", {a: v["id"] for a, v in pyth_ids.items()})
    store.set_meta("started_utc", datetime.now(timezone.utc).isoformat())

    stop = threading.Event()
    pollers = [
        PythPoller(stop, store, pyth_ids),
        HLPoller(stop, store),
        ExtendedPoller(stop, store),
    ]
    t0 = time.time()
    hb = threading.Thread(target=heartbeat_loop, args=(stop, store, t0), daemon=True)

    for p in pollers:
        p.start()
    hb.start()

    print("\nZbieram. Ctrl+C konczy.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nZatrzymuje…")
        stop.set()
        for p in pollers:
            p.join(timeout=3)
        store.stop()
        c = store.counts()
        print(f"Zapisano: total={sum(c.values())}  {dict(c)}")
        print(f"DB: {DB_PATH}")


# ── Stats ─────────────────────────────────────────────────────────────────────

def show_stats():
    con = read_con()
    cur = con.cursor()
    print(f"DB: {DB_PATH}\n")

    row = cur.execute("SELECT COUNT(*), MIN(ts_ms), MAX(ts_ms) FROM ticks").fetchone()
    n, tmin, tmax = row
    if not n:
        print("Brak danych. Odpal: python collector.py")
        return
    span_h = (tmax - tmin) / 3_600_000
    print(f"Ticks: {n:,}  |  okno: {span_h:.2f} h  "
          f"({datetime.utcfromtimestamp(tmin/1000):%Y-%m-%d %H:%M} → "
          f"{datetime.utcfromtimestamp(tmax/1000):%H:%M} UTC)\n")

    print("Per source × asset (liczba tickow, ostatnia cena):")
    rows = cur.execute("""
        SELECT source, asset, COUNT(*) n,
               (SELECT price FROM ticks t2 WHERE t2.source=t.source AND t2.asset=t.asset
                ORDER BY ts_ms DESC LIMIT 1) last
        FROM ticks t GROUP BY source, asset ORDER BY source, asset""").fetchall()
    for r in rows:
        print(f"  {r['source']:9s} {r['asset']:6s}  n={r['n']:>7,}  last={r['last']:.5f}")

    # snapshot spread A (Pyth vs HL xyz) — ostatnie ceny
    print("\nStrategia A — spread Pyth vs HL xyz (ostatnie ceny, bps):")
    for asset in PYTH_QUERIES:
        pyth = cur.execute("SELECT price FROM ticks WHERE source='pyth' AND asset=? "
                           "ORDER BY ts_ms DESC LIMIT 1", (asset,)).fetchone()
        hlx = cur.execute("SELECT price FROM ticks WHERE source='hl_xyz' AND asset=? "
                          "ORDER BY ts_ms DESC LIMIT 1", (asset,)).fetchone()
        if pyth and hlx and pyth["price"]:
            if asset in RETURNS_ONLY:
                ratio = hlx["price"] / pyth["price"]
                print(f"  {asset:6s}  pyth={pyth['price']:.4f}  hl_xyz={hlx['price']:.4f}  "
                      f"(skala x{ratio:.1f} — edge liczony na zwrotach %, nie bps)")
            else:
                bps = (hlx["price"] - pyth["price"]) / pyth["price"] * 10000
                print(f"  {asset:6s}  pyth={pyth['price']:.4f}  hl_xyz={hlx['price']:.4f}  "
                      f"spread={bps:+.2f} bps")
        else:
            print(f"  {asset:6s}  (brak pary)")

    # snapshot basis B (HL perp vs Extended)
    print("\nStrategia B — basis HL perp vs Extended (ostatnie ceny, bps):")
    for asset in HL_PERP:
        hl = cur.execute("SELECT price FROM ticks WHERE source='hl_perp' AND asset=? "
                         "ORDER BY ts_ms DESC LIMIT 1", (asset,)).fetchone()
        ext = cur.execute("SELECT price FROM ticks WHERE source='extended' AND asset=? "
                          "ORDER BY ts_ms DESC LIMIT 1", (asset,)).fetchone()
        if hl and ext and hl["price"]:
            bps = (ext["price"] - hl["price"]) / hl["price"] * 10000
            print(f"  {asset:6s}  hl={hl['price']:.4f}  ext={ext['price']:.4f}  "
                  f"basis={bps:+.2f} bps")
        else:
            print(f"  {asset:6s}  (brak pary)")

    fn = cur.execute("SELECT COUNT(*) FROM funding").fetchone()[0]
    print(f"\nFunding snapshots: {fn:,}")
    con.close()


def main():
    ap = argparse.ArgumentParser(description="ScalpBot3 Faza 0 collector")
    ap.add_argument("--resolve-only", action="store_true", help="tylko rozwiaz Pyth id i wyjdz")
    ap.add_argument("--stats", action="store_true", help="podglad zebranych danych")
    args = ap.parse_args()

    if args.stats:
        show_stats()
    else:
        collect(resolve_only=args.resolve_only)


if __name__ == "__main__":
    main()
