"""research.py — Faza 0: raport edge dla liquidation-cascade fade.

Czyta data/liqscalp.db. Wykrywa KLASTRY likwidacji (kaskady), symuluje fade
(sell-kaskada -> long, buy-kaskada -> short) i mierzy odbicie ceny PO ODJECIU FEE
na kilku horyzontach czasowych. To jest bramka decyzyjna: dodatnia expectancy po
fee otwiera Faze 1 (paper). Ujemna = nie wdrazamy (i to tez wynik).

Klaster = seria likwidacji bez przerwy dluzszej niz GAP, dominujaca jedna strona.

Uzycie:
    python research.py
    python research.py --min-notional 50000 --min-count 5 --gap 20 --entry-delay 5
    python research.py --fee-bps 8        # zalozenie round-trip fee w bps (0.08%)
"""
from __future__ import annotations

import argparse
import bisect
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from store import Store

HORIZONS_S = [60, 120, 300, 600, 900]        # +1, +2, +5, +10, +15 min
HORIZONS_SHORT = [15, 30, 60, 120, 300]      # +15s..+5min (do testu szybkiego odbicia)
HORIZONS_LONG = [600, 900, 1800, 2700, 3600]  # +10..+60min (czy dluzszy hold pomaga)


def load_prices(conn) -> dict[str, tuple[list[int], list[float]]]:
    """Per symbol: (posortowane ts[], price[]) do szybkiego bisect."""
    out: dict[str, tuple[list, list]] = defaultdict(lambda: ([], []))
    for sym, ts, px in conn.execute(
            "SELECT symbol, ts, price FROM price_ticks ORDER BY symbol, ts"):
        out[sym][0].append(ts)
        out[sym][1].append(px)
    return out


def price_at(prices, sym, t_ms, tol_ms=10_000):
    """Cena w pierwszym ticku >= t_ms (w tolerancji). None jesli brak."""
    data = prices.get(sym)
    if not data or not data[0]:
        return None
    ts_list, px_list = data
    i = bisect.bisect_left(ts_list, t_ms)
    if i >= len(ts_list):
        return None
    if ts_list[i] - t_ms > tol_ms:
        return None
    return px_list[i]


def find_clusters(conn, symbol, gap_s, min_count, min_notional, dominance):
    """Zwraca klastry: dict(end_ts, side, count, notional, extreme_px)."""
    rows = conn.execute(
        "SELECT ts_event, side, size, price, notional FROM liq_events "
        "WHERE symbol=? ORDER BY ts_event", (symbol,)).fetchall()
    clusters = []
    cur = []
    gap_ms = gap_s * 1000

    def flush(group):
        if not group:
            return
        cnt = len(group)
        notional = sum(r[4] for r in group)
        sells = sum(1 for r in group if r[1] == "Sell")
        buys = cnt - sells
        dom_side = "Sell" if sells >= buys else "Buy"
        dom_frac = max(sells, buys) / cnt
        if cnt < min_count or notional < min_notional or dom_frac < dominance:
            return
        # extreme: sell-kaskada spycha w dol -> min; buy -> max
        prices = [r[3] for r in group]
        extreme = min(prices) if dom_side == "Sell" else max(prices)
        clusters.append({
            "start_ts": group[0][0], "end_ts": group[-1][0], "side": dom_side,
            "count": cnt, "notional": notional, "extreme": extreme,
        })

    for r in rows:
        if cur and r[0] - cur[-1][0] > gap_ms:
            flush(cur)
            cur = []
        cur.append(r)
    flush(cur)
    return clusters


def simulate(clusters, prices, symbol, entry_delay_s, fee_bps,
             entry_mode="market", horizons=HORIZONS_S, follow=False, min_move_pct=0.0):
    """Dla kazdego klastra: return po fee na kazdym horyzoncie.

    entry_mode: 'market' = cena +delay po klastrze (realne); 'extreme' = knot kaskady.
    follow=False -> FADE (przeciw kaskadzie); follow=True -> MOMENTUM (z kaskada).
    min_move_pct: filtr SILY kaskady — ile % cena przejechala podczas klastra (intensywnosc).
    """
    out = []
    for cl in clusters:
        # filtr sily: ruch ceny podczas kaskady (start -> extreme)
        if min_move_pct > 0:
            p_start = price_at(prices, symbol, cl["start_ts"])
            if not p_start:
                continue
            move = abs(cl["extreme"] - p_start) / p_start * 100.0
            if move < min_move_pct:
                continue
        if entry_mode == "extreme":
            entry = cl["extreme"]
            entry_ts = cl["end_ts"]
        else:
            entry_ts = cl["end_ts"] + entry_delay_s * 1000
            entry = price_at(prices, symbol, entry_ts)
        if not entry:
            continue
        # FADE: sell-kaskada -> LONG (+1), buy -> SHORT (-1). FOLLOW = odwrotnie.
        fade_sign = 1.0 if cl["side"] == "Sell" else -1.0
        if follow:
            fade_sign = -fade_sign
        rec = {"side": cl["side"], "count": cl["count"], "notional": cl["notional"]}
        for h in horizons:
            fut = price_at(prices, symbol, entry_ts + h * 1000)
            if not fut:
                rec[h] = None
                continue
            gross = (fut - entry) / entry * 100.0 * fade_sign
            rec[h] = gross - fee_bps / 100.0    # net po round-trip fee
        out.append(rec)
    return out


def agg(records, horizon):
    vals = [r[horizon] for r in records if r.get(horizon) is not None]
    if not vals:
        return None
    n = len(vals)
    wins = sum(1 for v in vals if v > 0)
    mean = sum(vals) / n
    s = sorted(vals)
    median = s[n // 2]
    return {"n": n, "win": wins / n * 100, "mean": mean, "median": median,
            "sum": sum(vals)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, default=20, help="max przerwa w klastrze (s)")
    ap.add_argument("--min-count", type=int, default=5, help="min likwidacji w klastrze")
    ap.add_argument("--min-notional", type=float, default=50_000, help="min $ klastra")
    ap.add_argument("--dominance", type=float, default=0.70, help="min udzial dominujacej strony")
    ap.add_argument("--entry-delay", type=float, default=5, help="opoznienie wejscia po klastrze (s)")
    ap.add_argument("--fee-bps", type=float, default=8, help="round-trip fee w bps (8=0.08%)")
    ap.add_argument("--entry", choices=["market", "extreme"], default="market",
                    help="market=realne wejscie +delay; extreme=knot kaskady (gorna granica edge)")
    ap.add_argument("--short", action="store_true", help="krotsze horyzonty (15s..5min)")
    ap.add_argument("--long", action="store_true", help="dluzsze horyzonty (10..60min)")
    ap.add_argument("--follow", action="store_true", help="MOMENTUM (z kaskada) zamiast fade")
    ap.add_argument("--only", type=str, default="", help="tylko te symbole (CSV)")
    ap.add_argument("--exclude", type=str, default="", help="pomin te symbole (CSV)")
    ap.add_argument("--min-move-pct", type=float, default=0.0, help="min ruch ceny w kaskadzie (%)")
    args = ap.parse_args()

    horizons = HORIZONS_SHORT if args.short else (HORIZONS_LONG if args.long else HORIZONS_S)
    s = Store()
    conn = s.conn
    prices = load_prices(conn)
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM liq_events").fetchall()]
    only = {x.strip().upper() for x in args.only.split(",") if x.strip()}
    excl = {x.strip().upper() for x in args.exclude.split(",") if x.strip()}
    if only:
        symbols = [s_ for s_ in symbols if s_ in only]
    if excl:
        symbols = [s_ for s_ in symbols if s_ not in excl]

    print(f"=== LIQSCALP FAZA 0 — RAPORT EDGE ===")
    print(f"params: gap={args.gap}s min_count={args.min_count} "
          f"min_notional=${args.min_notional:,.0f} dominance={args.dominance} "
          f"entry={args.entry} entry_delay={args.entry_delay}s fee={args.fee_bps}bps\n")

    all_recs = []
    per_symbol = {}
    for sym in symbols:
        cl = find_clusters(conn, sym, args.gap, args.min_count,
                           args.min_notional, args.dominance)
        recs = simulate(cl, prices, sym, args.entry_delay, args.fee_bps,
                        entry_mode=args.entry, horizons=horizons, follow=args.follow,
                        min_move_pct=args.min_move_pct)
        if recs:
            per_symbol[sym] = recs
            all_recs.extend(recs)

    if not all_recs:
        print("Brak klastrow spelniajacych progi. Zluzuj --min-notional/--min-count.")
        s.close()
        return

    # 1) Edge ogolny per horyzont (NET po fee)
    print("OGOLEM (wszystkie aktywa, NET po fee):")
    print(f"  {'horyzont':>8s} {'N':>5s} {'win%':>6s} {'mean%':>8s} {'median%':>8s} {'sum%':>8s}")
    best_h, best_mean = None, -1e9
    for h in horizons:
        a = agg(all_recs, h)
        if not a:
            continue
        print(f"  +{h//60:>3d}min {a['n']:>6d} {a['win']:>5.1f}% "
              f"{a['mean']:>+7.3f}% {a['median']:>+7.3f}% {a['sum']:>+7.2f}%")
        if a["mean"] > best_mean:
            best_mean, best_h = a["mean"], h

    # 2) Per aktyw na najlepszym horyzoncie
    print(f"\nPER AKTYW (horyzont +{best_h//60}min, NET po fee):")
    print(f"  {'symbol':12s} {'N':>5s} {'win%':>6s} {'mean%':>8s} {'sum%':>8s}")
    for sym, recs in sorted(per_symbol.items(),
                            key=lambda kv: -(agg(kv[1], best_h) or {"mean": -9})["mean"]):
        a = agg(recs, best_h)
        if not a:
            continue
        print(f"  {sym:12s} {a['n']:>6d} {a['win']:>5.1f}% {a['mean']:>+7.3f}% {a['sum']:>+7.2f}%")

    # 3) Per strona (long-fade vs short-fade)
    print(f"\nPER STRONA KASKADY (horyzont +{best_h//60}min, NET po fee):")
    if args.follow:
        side_labels = [("Sell", "sell-kaskada -> momentum SHORT"),
                       ("Buy", "buy-kaskada -> momentum LONG")]
    else:
        side_labels = [("Sell", "sell-kaskada -> fade LONG"),
                       ("Buy", "buy-kaskada -> fade SHORT")]
    for side, label in side_labels:
        sub = [r for r in all_recs if r["side"] == side]
        a = agg(sub, best_h)
        if a:
            print(f"  {label:30s} N={a['n']:>4d} win={a['win']:>5.1f}% mean={a['mean']:>+.3f}%")

    # 4) Sweep progu notional (krzywa edge)
    print(f"\nKRZYWA EDGE — prog notional (horyzont +{best_h//60}min):")
    print(f"  {'min_notional':>13s} {'klastry':>8s} {'win%':>6s} {'mean net%':>10s}")
    for thr in [10_000, 25_000, 50_000, 100_000, 250_000, 500_000]:
        recs2 = []
        for sym in symbols:
            cl = find_clusters(conn, sym, args.gap, args.min_count, thr, args.dominance)
            recs2.extend(simulate(cl, prices, sym, args.entry_delay, args.fee_bps,
                                  entry_mode=args.entry, horizons=horizons, follow=args.follow,
                                  min_move_pct=args.min_move_pct))
        a = agg(recs2, best_h)
        if a:
            print(f"  ${thr:>11,.0f} {a['n']:>8d} {a['win']:>5.1f}% {a['mean']:>+9.3f}%")

    # 5) Werdykt
    a = agg(all_recs, best_h)
    print(f"\n=== WERDYKT (najlepszy horyzont +{best_h//60}min) ===")
    verdict = "DODATNI" if a["mean"] > 0 else "UJEMNY"
    print(f"  mean net {a['mean']:+.3f}%/trade | win {a['win']:.1f}% | N={a['n']} -> edge {verdict}")
    s.close()


if __name__ == "__main__":
    main()
