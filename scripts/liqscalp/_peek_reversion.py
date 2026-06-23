"""_peek_reversion.py — czy po klastrze likwidacji cena odbila? (pierwszy test edge). Throwaway."""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from store import Store

s = Store(); c = s.conn

def avg_price(sym, t_start_ms, t_end_ms):
    r = c.execute("SELECT AVG(price) FROM price_ticks WHERE symbol=? AND ts>=? AND ts<?",
                  (sym, t_start_ms, t_end_ms)).fetchone()
    return r[0]

# Znajdz sell-dominujace klastry (>=5 likwidacji w 60s, wiekszosc S=Sell = longi rekt)
clusters = c.execute(
    "SELECT symbol, (ts_event/60000) AS b, COUNT(*) cnt, "
    " SUM(CASE WHEN side='Sell' THEN 1 ELSE 0 END) sells, ROUND(SUM(notional)) usd "
    "FROM liq_events GROUP BY symbol, b HAVING cnt>=5 ORDER BY cnt DESC LIMIT 12").fetchall()

print("Test fade: klaster SELL (longi likwidowane, cena spychana w dol) -> czy odbila?")
print("Jesli fade LONG dziala, cena +N min PO klastrze > cena W klastrze.\n")
print(f"{'symbol':10s} {'czas':6s} {'liq':>3s} {'%sell':>5s} {'$notional':>11s}  "
      f"{'cena@klaster':>12s} {'+2min':>8s} {'+5min':>8s} {'+10min':>8s}")

for sym, b, cnt, sells, usd in clusters:
    base = b * 60000
    p0 = avg_price(sym, base, base + 60000)          # cena w minucie klastra
    p2 = avg_price(sym, base + 120000, base + 180000)
    p5 = avg_price(sym, base + 300000, base + 360000)
    p10 = avg_price(sym, base + 600000, base + 660000)
    if not p0:
        continue
    def pct(p):
        return f"{(p-p0)/p0*100:+.2f}%" if p else "  -  "
    pct_sell = int(sells / cnt * 100)
    hhmm = time.strftime("%H:%M", time.gmtime(base / 1000))
    print(f"{sym:10s} {hhmm:6s} {cnt:>3d} {pct_sell:>4d}% ${usd or 0:>10,.0f}  "
          f"{p0:>12,.2f} {pct(p2):>8s} {pct(p5):>8s} {pct(p10):>8s}")

print("\n(dodatni % = cena wzrosla po sell-kaskadzie = fade LONG by zarobil)")
s.close()
