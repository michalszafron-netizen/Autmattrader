"""research_lag.py — WERDYKT strategii A (Event-Lag Sniper).

Czyta data/scalpbot3.db i odpowiada na jedno pytanie: czy HL xyz LAGUJE za Pyth
na tyle, zeby dalo sie na tym zarobic PO KOSZTACH? Stdlib-only (dziala na VPS bez pip).

Trzy analizy per aktywo (GOLD, SILVER, CL, SP500):
  1. Lead-lag cross-correlation — o ile xyz spoznia sie za Pyth (rdzen edge'u).
  2. Rozklad spreadu — czy to trwala baza (nieedge) czy oscylacja (edge).
  3. Event study — gdy Pyth skacze, ile xyz "dogania" i jak szybko + expectancy po fee.

Uzycie:
    python research_lag.py                 # wszystkie aktywa, siatka 500ms
    python research_lag.py --asset CL       # jedno aktywo
    python research_lag.py --grid-ms 250 --jump-bps 8 --fee-bps 3.5
"""

from __future__ import annotations

import argparse
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from store import read_con, DB_PATH

PYTH_ASSETS = ["GOLD", "SILVER", "CL", "SP500"]
RETURNS_ONLY = {"SP500"}  # skala Pyth != xyz -> tylko zwroty


def _db_has_data() -> bool:
    """True jesli baza istnieje, ma tabele ticks i przynajmniej 1 wiersz."""
    if not DB_PATH.exists():
        return False
    try:
        con = read_con()
        t = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ticks'").fetchone()
        if not t:
            con.close()
            return False
        n = con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        con.close()
        return n > 0
    except Exception:
        return False


def load_series(con, source: str, asset: str) -> list[tuple[int, float]]:
    rows = con.execute(
        "SELECT ts_ms, price FROM ticks WHERE source=? AND asset=? ORDER BY ts_ms",
        (source, asset)).fetchall()
    return [(r["ts_ms"], r["price"]) for r in rows]


def resample(series: list[tuple[int, float]], grid_ms: int) -> list[tuple[int, float]]:
    """Last-value forward-fill na rownej siatce grid_ms."""
    if not series:
        return []
    t0 = series[0][0] - (series[0][0] % grid_ms)
    t_end = series[-1][0]
    out, i, last = [], 0, series[0][1]
    t = t0
    while t <= t_end:
        while i < len(series) and series[i][0] <= t:
            last = series[i][1]
            i += 1
        out.append((t, last))
        t += grid_ms
    return out


def returns(grid: list[tuple[int, float]]) -> list[float]:
    r = []
    for k in range(1, len(grid)):
        p0, p1 = grid[k - 1][1], grid[k][1]
        r.append((p1 - p0) / p0 if p0 else 0.0)
    return r


def _corr(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 10:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va == 0 or vb == 0:
        return 0.0
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / (va ** 0.5 * vb ** 0.5)


def cross_corr(pyth_ret: list[float], xyz_ret: list[float], max_lag: int) -> list[tuple[int, float]]:
    """corr(pyth[t], xyz[t+lag]). lag>0 => xyz podaza za Pyth (LAG = edge)."""
    out = []
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = pyth_ret[:len(pyth_ret) - lag], xyz_ret[lag:]
        else:
            a, b = pyth_ret[-lag:], xyz_ret[:len(xyz_ret) + lag]
        out.append((lag, _corr(a, b)))
    return out


def spread_stats(con, asset: str) -> dict | None:
    """Rozklad spreadu (hl_xyz - pyth)/pyth w bps po najblizszym match czasowym."""
    pyth = load_series(con, "pyth", asset)
    xyz = load_series(con, "hl_xyz", asset)
    if not pyth or not xyz:
        return None
    # dla kazdego xyz tick znajdz najblizszy wczesniejszy pyth (merge marsz)
    spreads = []
    j = 0
    for t, px in xyz:
        while j + 1 < len(pyth) and pyth[j + 1][0] <= t:
            j += 1
        pp = pyth[j][1]
        if pp:
            spreads.append((px - pp) / pp * 10000)
    if len(spreads) < 10:
        return None
    mean = statistics.mean(spreads)
    sd = statistics.pstdev(spreads)
    return {"mean_bps": mean, "sd_bps": sd,
            "min": min(spreads), "max": max(spreads), "n": len(spreads),
            "abs_p90": sorted(abs(s) for s in spreads)[int(len(spreads) * 0.9)]}


def event_study(pyth_grid, xyz_grid, grid_ms, jump_bps, horizon_s, fee_bps):
    """Gdy |pyth_ret| przekroczy jump_bps w 1 kroku, mierz nastepny ruch xyz."""
    horizon_steps = max(1, int(horizon_s * 1000 / grid_ms))
    pr = returns(pyth_grid)
    events = []
    for k in range(1, len(pr) - horizon_steps):
        move = pr[k] * 10000  # bps
        if abs(move) < jump_bps:
            continue
        direction = 1 if move > 0 else -1
        # xyz od momentu k do k+horizon
        x0 = xyz_grid[k][1]
        x_end = xyz_grid[min(k + horizon_steps, len(xyz_grid) - 1)][1]
        xyz_follow_bps = (x_end - x0) / x0 * 10000 * direction  # dodatnie = xyz podazyl za Pyth
        events.append(xyz_follow_bps)
    if not events:
        return None
    wins = sum(1 for e in events if e > 0)
    # expectancy: wchodzimy w kierunku ruchu Pyth, lapiemy xyz_follow, placimy fee (round-trip taker)
    net = [e - fee_bps for e in events]
    return {"n": len(events), "win_rate": wins / len(events),
            "median_follow_bps": statistics.median(events),
            "mean_net_bps": statistics.mean(net),
            "median_net_bps": statistics.median(net)}


def analyze(asset: str, grid_ms: int, jump_bps: float, horizon_s: float, fee_bps: float):
    con = read_con()
    pyth = load_series(con, "pyth", asset)
    xyz = load_series(con, "hl_xyz", asset)
    print(f"\n{'='*62}\n{asset}  (pyth n={len(pyth):,}  hl_xyz n={len(xyz):,})")
    if len(pyth) < 50 or len(xyz) < 50:
        print("  za malo danych — zbieraj dluzej.")
        con.close()
        return
    pg = resample(pyth, grid_ms)
    xg = resample(xyz, grid_ms)
    n = min(len(pg), len(xg))
    pg, xg = pg[:n], xg[:n]
    pr, xr = returns(pg), returns(xg)

    # 1. lead-lag
    max_lag = max(4, int(3000 / grid_ms))  # ~3s w kazda strone
    cc = cross_corr(pr, xr, max_lag)
    peak_lag, peak_corr = max(cc, key=lambda x: x[1])
    print(f"  [1] Lead-lag (siatka {grid_ms}ms, ±{max_lag} krokow):")
    print(f"      peak corr={peak_corr:+.3f} przy lag={peak_lag} "
          f"({peak_lag*grid_ms:+d}ms => xyz {'PODAZA za Pyth' if peak_lag>0 else 'rowno/wyprzedza'})")
    zero_corr = next(c for l, c in cc if l == 0)
    print(f"      corr@lag0={zero_corr:+.3f}")

    # 2. spread
    if asset not in RETURNS_ONLY:
        ss = spread_stats(con, asset)
        if ss:
            print(f"  [2] Spread bps: mean={ss['mean_bps']:+.2f}  sd={ss['sd_bps']:.2f}  "
                  f"|p90|={ss['abs_p90']:.2f}  [{ss['min']:+.1f}..{ss['max']:+.1f}]")
            trwala = abs(ss['mean_bps']) > 2 * ss['sd_bps']
            print(f"      -> {'TRWALA BAZA (mean≫sd) — malo miejsca na fade' if trwala else 'OSCYLUJE wokol sredniej — potencjal fade'}")
    else:
        print(f"  [2] Spread: pominiety (skala x10, SP500 = tylko zwroty)")

    # 3. event study
    es = event_study(pg, xg, grid_ms, jump_bps, horizon_s, fee_bps)
    if es:
        print(f"  [3] Event study (skok Pyth ≥{jump_bps}bps, horyzont {horizon_s}s, fee {fee_bps}bps rt):")
        print(f"      events={es['n']}  xyz-podaza win={es['win_rate']*100:.0f}%  "
              f"median follow={es['median_follow_bps']:+.1f}bps")
        print(f"      NET po fee: mean={es['mean_net_bps']:+.2f}bps  median={es['median_net_bps']:+.2f}bps")
        v = es['median_net_bps']
        verdict = "EDGE" if v > 1 else ("GRANICZNY" if v > -1 else "BRAK")
        print(f"      => WERDYKT event: {verdict}")
    else:
        print(f"  [3] Event study: brak skokow ≥{jump_bps}bps (zbieraj dluzej / obniz --jump-bps)")
    con.close()


def main():
    ap = argparse.ArgumentParser(description="Werdykt strategii A (event-lag)")
    ap.add_argument("--asset", choices=PYTH_ASSETS, help="jedno aktywo (domyslnie wszystkie)")
    ap.add_argument("--grid-ms", type=int, default=500, help="siatka resamplingu (ms)")
    ap.add_argument("--jump-bps", type=float, default=8.0, help="prog skoku Pyth do event study")
    ap.add_argument("--horizon-s", type=float, default=5.0, help="horyzont pomiaru po skoku (s)")
    ap.add_argument("--fee-bps", type=float, default=3.5, help="koszt round-trip (taker HL crypto ~3.5, xyz maker ~0.6)")
    args = ap.parse_args()

    print(f"DB: {DB_PATH}")
    if not _db_has_data():
        print("\n⚠️  Brak danych do analizy — tabela 'ticks' nie istnieje lub jest pusta.")
        print("    Kolejnosc jest: NAJPIERW zbierasz, POTEM analizujesz.")
        print("    Odpal kolektor i zostaw go zbierajacego:")
        print("        python collector.py            (lub run_collector.bat)")
        print("    Podglad ile juz zebrano:")
        print("        python collector.py --stats")
        print("    Werdykt (tu) uruchom po min. dobie danych, najlepiej po tygodniu + evencie makro.")
        return
    assets = [args.asset] if args.asset else PYTH_ASSETS
    for a in assets:
        analyze(a, args.grid_ms, args.jump_bps, args.horizon_s, args.fee_bps)
    print(f"\n{'='*62}")
    print("Przypomnienie: 1 dzien danych = wstepny sygnal. Werdykt = min. tydzien + 1 duzy event makro.")


if __name__ == "__main__":
    main()
