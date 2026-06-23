"""_peek.py — szybki przeglad zebranych danych (likwidacje). Throwaway."""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from store import Store

s = Store()
c = s.conn

tot = c.execute("SELECT COUNT(*), MIN(ts_event), MAX(ts_event) FROM liq_events").fetchone()
n, t0, t1 = tot
price_n = c.execute("SELECT COUNT(*) FROM price_ticks").fetchone()[0]
hrs = (t1 - t0) / 3_600_000 if t0 else 0
print(f"=== ZEBRANE: {n} likwidacji | {price_n} tickow ceny | {hrs:.2f} h ===\n")

print("Per symbol (count, suma notional USD, sredni $/event):")
for row in c.execute(
    "SELECT symbol, COUNT(*), ROUND(SUM(notional)), ROUND(AVG(notional)) "
    "FROM liq_events GROUP BY symbol ORDER BY 3 DESC"):
    sym, cnt, tot_n, avg_n = row
    print(f"  {sym:14s} {cnt:5d}   ${tot_n or 0:>12,.0f}   avg ${avg_n or 0:>9,.0f}")

print("\nRozklad strony (S — surowe pole Bybit):")
for row in c.execute("SELECT side, COUNT(*) FROM liq_events GROUP BY side ORDER BY 2 DESC"):
    print(f"  S={row[0]!r:8s} {row[1]}")

print("\nTOP 8 najwiekszych pojedynczych likwidacji:")
for row in c.execute(
    "SELECT symbol, side, ROUND(notional), price FROM liq_events "
    "ORDER BY notional DESC LIMIT 8"):
    print(f"  {row[0]:12s} S={row[1]:5s} ${row[2]:>11,.0f} @ {row[3]}")

# Najwiekszy klaster: ile likwidacji w 60s oknie per symbol (bucket 60s)
print("\nNajgestsze 60s-okna (klastry — to material na fade):")
rows = c.execute(
    "SELECT symbol, (ts_event/60000) AS b, COUNT(*) cnt, ROUND(SUM(notional)) usd "
    "FROM liq_events GROUP BY symbol, b HAVING cnt>=3 ORDER BY cnt DESC LIMIT 8").fetchall()
if not rows:
    print("  (brak okna z >=3 likwidacjami — spokojnie na rynku)")
for sym, b, cnt, usd in rows:
    hhmm = time.strftime("%H:%M", time.gmtime(b*60))
    print(f"  {sym:12s} {hhmm} UTC: {cnt} likwidacji, ${usd or 0:,.0f}")

s.close()
