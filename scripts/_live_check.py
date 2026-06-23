import sys; sys.path.insert(0, 'scripts')
from db import DB
db = DB()
rows = db._sqlite.query("""
    SELECT id, ts_open, side, entry_price, exit_price,
           pnl_usd, net_pnl, exit_reason, hold_seconds
    FROM scalp_trades
    WHERE instrument='xyz:GOLD' AND ts_open >= '2026-06-19T15:00'
    ORDER BY ts_open
""")
print(f"{'#':>3} {'Czas':<21} {'Side':<6} {'Entry':>8} {'Exit':>8} {'PnL':>6} {'Net':>6} {'Reason':<12} {'Hold':>5}")
print('-' * 80)
for r in rows:
    print(f"{r['id']:>3} {r['ts_open'][:19]:<21} {r['side']:<6} {r['entry_price']:>8.1f} "
          f"{str(r['exit_price'] or '-'):>8} {str(r['pnl_usd'] or ''):>6} "
          f"{str(r['net_pnl'] or ''):>6} {str(r['exit_reason'] or 'open'):<12} "
          f"{str(r['hold_seconds'] or '-'):>5}")
