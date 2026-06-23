"""show_scalp_stats.py — SCALP-specific analytics.

Czego tu szukamy w paper mode:
  1. Ranking par — która para daje najwięcej sygnałów, która najwyższą WR
  2. Godziny — kiedy sygnały są najczęstsze/najlepsze
  3. Confidence — czy C=7 ma realnie lepszą WR niż C=5?
  4. Lag time — jak szybko laggard reaguje na drivera
  5. No-fill rate — ile sygnałów nie doczekało się egzekucji
  6. Win/loss breakdown per-pair

Usage:
    .venv/Scripts/python.exe scripts/show_scalp_stats.py
    .venv/Scripts/python.exe scripts/show_scalp_stats.py --all   (wszystkie dni)
    .venv/Scripts/python.exe scripts/show_scalp_stats.py --since 24h
"""

import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "scripts")
from db import DB


def fmt(s: float) -> str:
    if s >= 0:
        return f"${s:+.2f}"
    return f"-${abs(s):.2f}"


def main():
    db = DB()

    since = None
    if "--since" in sys.argv:
        idx = sys.argv.index("--since")
        if idx + 1 < len(sys.argv):
            since_raw = sys.argv[idx + 1]
            if since_raw.endswith("h"):
                hours = int(since_raw[:-1])
                since = datetime.now(timezone.utc) - timedelta(hours=hours)
            elif since_raw.endswith("d"):
                days = int(since_raw[:-1])
                since = datetime.now(timezone.utc) - timedelta(days=days)

    where = ""
    params = []
    if since:
        where = "WHERE ts_open >= ?"
        params = [since.isoformat()[:19]]

    print(f"\n{'=' * 55}")
    print(f"  SCALP BOT ANALYTICS   ({since or 'ALL TIME'})")
    print(f"{'=' * 55}\n")

    # ── 1. OVERVIEW ──
    rows = db._sqlite.query(
        f"""SELECT COUNT(*) as t,
                   COUNT(CASE WHEN status='closed' THEN 1 END) as closed,
                   COUNT(CASE WHEN exit_reason='no_fill' THEN 1 END) as no_fill,
                   ROUND(AVG(CASE WHEN status='closed' AND exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr_filled,
                   SUM(COALESCE(net_pnl,0)) as total_net,
                   ROUND(AVG(COALESCE(hold_seconds,0)),1) as avg_hold
            FROM scalp_trades {where}""",
        params,
    )
    ov = rows[0]
    print(f"  Trades:     {ov['t']}")
    print(f"  Closed:     {ov['closed']} (no_fill: {ov['no_fill']})")
    print(f"  WR (filled): {ov['wr_filled']}%")
    print(f"  Net PnL:    ${ov['total_net']:.2f}")
    print(f"  Avg hold:   {ov['avg_hold']}s\n")

    # ── 2. PER-INSTRUMENT ──
    rows = db._sqlite.query(
        f"""SELECT instrument,
                   COUNT(*) as t,
                   ROUND(AVG(CASE WHEN exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr_filled,
                   ROUND(SUM(COALESCE(net_pnl,0)),2) as net,
                   ROUND(AVG(CASE WHEN pnl_usd>0 THEN pnl_usd END),4) as avg_win,
                   ROUND(AVG(CASE WHEN pnl_usd<0 THEN pnl_usd END),4) as avg_loss,
                   ROUND(AVG(COALESCE(hold_seconds,0)),1) as avg_hold
            FROM scalp_trades {where}
            GROUP BY instrument ORDER BY t DESC""",
        params,
    )
    print("  ── PER INSTRUMENT ──")
    print(f"  {'Instrument':14s} {'Trades':>6} {'WR_filled':>9} {'Net PnL':>8} {'AvgWin':>7} {'AvgLoss':>8} {'Hold':>5}")
    print(f"  {'-'*58}")
    for r in rows:
        win_s = fmt(r["avg_win"]) if r["avg_win"] else "  N/A "
        loss_s = fmt(r["avg_loss"]) if r["avg_loss"] else "  N/A "
        print(f"  {r['instrument'].replace('xyz:',''):14s} {r['t']:>6} {r['wr_filled']:>8}%  {r['net']:>6.2f}  {win_s:>7} {loss_s:>8} {r['avg_hold']:>5}s")
    print()

    # ── 3. PER PAIR RANKING ──
    rows = db._sqlite.query(
        f"""SELECT driver, laggard, correlation_pair,
                   COUNT(*) as t,
                   COUNT(CASE WHEN exit_reason='no_fill' THEN 1 END) as no_fill,
                   ROUND(AVG(CASE WHEN exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr_filled,
                   ROUND(SUM(COALESCE(net_pnl,0)),2) as net
            FROM scalp_trades {where + ' AND ' if where else 'WHERE '} correlation_pair IS NOT NULL
            GROUP BY driver, laggard ORDER BY t DESC""",
        params,
    )
    print("  ── PAIR RANKING (najwięcej sygnałów) ──")
    print(f"  {'#':>2} {'Pair':<44s} {'Sig':>4} {'Empty':>5} {'WR':>7} {'Net':>7}")
    print(f"  {'-'*70}")
    for i, r in enumerate(rows, 1):
        d = r["driver"].replace("xyz:", "") if r["driver"] else "?"
        l = r["laggard"].replace("xyz:", "") if r["laggard"] else "?"
        pair = f"{d:>5s} → {l:<6s}"
        mut = (r["correlation_pair"] or "")[:30]
        label = f"{pair}  {mut}"
        print(f"  {i:>2}  {label:<44s} {r['t']:>4} {r['no_fill']:>5} {r['wr_filled']:>6}%  ${r['net']:>5.2f}")
    print()

    # ── 4. CONFIDENCE DISTRIBUTION ──
    rows = db._sqlite.query(
        f"""SELECT confidence,
                   COUNT(*) as t,
                   ROUND(AVG(CASE WHEN exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr_filled,
                   ROUND(AVG(COALESCE(net_pnl,0)),2) as avg_net
            FROM scalp_trades {where + ' AND ' if where else 'WHERE '} confidence IS NOT NULL
            GROUP BY confidence ORDER BY confidence DESC""",
        params,
    )
    if rows:
        print("  ── CONFIDENCE DISTRIBUTION ──")
        print(f"  {'C':>3} {'Trades':>7} {'WR_filled':>10} {'Avg Net':>8}")
        print(f"  {'-'*30}")
        for r in rows:
            print(f"  {r['confidence']:>3} {r['t']:>7} {r['wr_filled']:>8}%  ${r['avg_net']:>5.2f}")
        print()

    # ── 5. HOURLY HEATMAP ──
    rows = db._sqlite.query(
        f"""SELECT CAST(strftime('%H', ts_open) AS INTEGER) as hour,
                   COUNT(*) as t,
                   ROUND(AVG(CASE WHEN exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr,
                   ROUND(SUM(COALESCE(net_pnl,0)),2) as net
            FROM scalp_trades {where}
            GROUP BY hour ORDER BY hour""",
        params,
    )
    print("  ── HOURLY (UTC) ──")
    print(f"  {'Hour':>5} {'Trades':>7} {'WR':>7} {'Net':>7}")
    print(f"  {'-'*28}")
    for r in rows:
        bar = "#" * max(1, r["t"] // 3)
        print(f"  {r['hour']:2d}:00 {r['t']:>7} {r['wr']:>5}%  ${r['net']:>5.2f}  {bar}")
    print()

    # ── 6. LAG / HOLD TIME DISTRIBUTION ──
    rows = db._sqlite.query(
        f"""SELECT
                   ROUND(AVG(hold_seconds),2) as avg_hold,
                   ROUND(AVG(CASE WHEN pnl_usd>0 THEN hold_seconds END),2) as avg_hold_win,
                   ROUND(AVG(CASE WHEN pnl_usd<0 THEN hold_seconds END),2) as avg_hold_loss,
                   ROUND(MIN(hold_seconds),2) as min_hold,
                   ROUND(MAX(hold_seconds),2) as max_hold,
                   ROUND(AVG(CASE WHEN exit_reason='no_fill' THEN 1 ELSE 0 END)*100,1) as no_fill_pct
            FROM scalp_trades {where}""",
        params,
    )
    r = rows[0]
    print(
        f"  Hold time: avg {r['avg_hold']}s (wins {r['avg_hold_win']}s / losses {r['avg_hold_loss']}s)  range {r['min_hold']}-{r['max_hold']}s"
    )
    print(f"  No-fill rate: {r['no_fill_pct']}%")

    # ── 7. SESSION COMPARISON ──
    rows = db._sqlite.query(
        f"""SELECT CASE
                    WHEN CAST(strftime('%H', ts_open) AS INTEGER) BETWEEN 0 AND 6 THEN 'Asia'
                    WHEN CAST(strftime('%H', ts_open) AS INTEGER) BETWEEN 7 AND 12 THEN 'London'
                    WHEN CAST(strftime('%H', ts_open) AS INTEGER) BETWEEN 13 AND 20 THEN 'US'
                    ELSE 'Sydney'
                 END as session,
                 COUNT(*) as t,
                 ROUND(AVG(CASE WHEN exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr,
                 ROUND(SUM(COALESCE(net_pnl,0)),2) as net
          FROM scalp_trades {where}
          GROUP BY session ORDER BY t DESC""",
        params,
    )
    print("\n  ── BY SESSION ──")
    print(f"  {'Session':<10s} {'Trades':>7} {'WR':>7} {'Net':>7}")
    print(f"  {'-'*32}")
    for r in rows:
        print(f"  {r['session']:<10s} {r['t']:>7} {r['wr']:>5}%  ${r['net']:>5.2f}")

    # ── 8. DAILY TREND ──
    rows = db._sqlite.query(
        """SELECT strftime('%Y-%m-%d', ts_open) as day,
                  COUNT(*) as t,
                  ROUND(AVG(CASE WHEN exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr,
                  ROUND(SUM(COALESCE(net_pnl,0)),2) as net
           FROM scalp_trades
           GROUP BY day ORDER BY day DESC"""
    )
    print("\n  ── DAILY ──")
    for r in rows:
        print(f"  {r['day']}  {r['t']:3d} sig ({r['wr']:>5}% WR)  net ${r['net']:>5.2f}")

    # ── 9. SIDE BREAKDOWN ──
    rows = db._sqlite.query(
        f"""SELECT side, COUNT(*) as t,
                   ROUND(AVG(CASE WHEN exit_reason NOT IN ('no_fill') AND pnl_usd>0 THEN 1 ELSE 0 END)*100,1) as wr,
                   ROUND(SUM(COALESCE(net_pnl,0)),2) as net
            FROM scalp_trades {where}
            GROUP BY side""",
        params,
    )
    print("\n  ── SIDE ──")
    for r in rows:
        print(f"  {r['side']:5s}  {r['t']:3d} trades  WR {r['wr']:>5}%  net ${r['net']:>5.2f}")

    print()


if __name__ == "__main__":
    main()
