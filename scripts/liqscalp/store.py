"""store.py — izolowana warstwa zapisu dla bota liquidation-scalp (Faza 0).

Wlasna baza SQLite (data/liqscalp.db) — NIE dotyka glownego db.py.
Dwie tabele:
  liq_events  — kazde zdarzenie likwidacji z Bybit allLiquidation.{symbol}
  price_ticks — cena (lastPrice z tickers.{symbol}), throttlowana do ~1/s/symbol

Uzywane przez collector.py (zapis) i research.py (odczyt, Faza 0 analiza edge).
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parents[2] / "data" / "liqscalp.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS liq_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_event  INTEGER NOT NULL,   -- czas zdarzenia z Bybit (ms)
    ts_recv   INTEGER NOT NULL,   -- czas odbioru u nas (ms)
    symbol    TEXT    NOT NULL,
    side      TEXT,               -- surowe S z Bybit (strona zlecenia likwidacji)
    size      REAL,               -- v (rozmiar w kontraktach/coinach)
    price     REAL,               -- p (cena egzekucji likwidacji)
    notional  REAL,               -- size * price (USD)
    raw       TEXT                -- pelny JSON eventu (na wszelki wypadek)
);
CREATE INDEX IF NOT EXISTS idx_liq_sym_ts ON liq_events(symbol, ts_event);

CREATE TABLE IF NOT EXISTS price_ticks (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      INTEGER NOT NULL,     -- ms
    symbol  TEXT    NOT NULL,
    price   REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_sym_ts ON price_ticks(symbol, ts);

CREATE TABLE IF NOT EXISTS collector_meta (
    k TEXT PRIMARY KEY,
    v TEXT
);

CREATE TABLE IF NOT EXISTS scalp_trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open       INTEGER NOT NULL,   -- ms
    ts_close      INTEGER,
    mode          TEXT,               -- paper | live
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL,      -- long | short
    qty           REAL,
    entry         REAL,
    sl            REAL,
    tp            REAL,
    exit          REAL,
    risk_usd      REAL,
    leverage      INTEGER,
    pnl_usd       REAL,
    exit_reason   TEXT,               -- tp | sl | manual | timeout
    signal_json   TEXT,               -- sygnal ktory wywolal trade
    status        TEXT DEFAULT 'open' -- open | closed
);
CREATE INDEX IF NOT EXISTS idx_trades_status ON scalp_trades(status);
"""


class Store:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ── zapis ────────────────────────────────────────────────────────────────
    def insert_liqs(self, rows: list[tuple]) -> None:
        """rows: (ts_event, ts_recv, symbol, side, size, price, notional, raw)"""
        if not rows:
            return
        self.conn.executemany(
            "INSERT INTO liq_events (ts_event,ts_recv,symbol,side,size,price,notional,raw)"
            " VALUES (?,?,?,?,?,?,?,?)", rows)

    def insert_prices(self, rows: list[tuple]) -> None:
        """rows: (ts, symbol, price)"""
        if not rows:
            return
        self.conn.executemany(
            "INSERT INTO price_ticks (ts,symbol,price) VALUES (?,?,?)", rows)

    def commit(self) -> None:
        self.conn.commit()

    # ── trade'y (paper/live) ──────────────────────────────────────────────────
    def open_trade(self, t: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO scalp_trades (ts_open,mode,symbol,side,qty,entry,sl,tp,"
            "risk_usd,leverage,signal_json,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,'open')",
            (t["ts_open"], t["mode"], t["symbol"], t["side"], t["qty"], t["entry"],
             t["sl"], t["tp"], t.get("risk_usd"), t.get("leverage"),
             t.get("signal_json")))
        self.conn.commit()
        return int(cur.lastrowid)

    def close_trade(self, trade_id: int, ts_close: int, exit_px: float,
                    pnl_usd: float, reason: str) -> None:
        self.conn.execute(
            "UPDATE scalp_trades SET ts_close=?,exit=?,pnl_usd=?,exit_reason=?,"
            "status='closed' WHERE id=?",
            (ts_close, exit_px, pnl_usd, reason, trade_id))
        self.conn.commit()

    def open_trades_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM scalp_trades WHERE status='open'").fetchone()[0]

    def trades_today(self) -> int:
        import time as _t
        midnight = int((_t.time() // 86400) * 86400 * 1000)
        return self.conn.execute(
            "SELECT COUNT(*) FROM scalp_trades WHERE ts_open>=?", (midnight,)).fetchone()[0]

    def set_meta(self, k: str, v: str) -> None:
        self.conn.execute("INSERT INTO collector_meta(k,v) VALUES(?,?) "
                          "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
        self.conn.commit()

    # ── statystyki ───────────────────────────────────────────────────────────
    def summary(self) -> dict:
        c = self.conn
        out: dict = {}
        out["liq_total"] = c.execute("SELECT COUNT(*) FROM liq_events").fetchone()[0]
        out["price_total"] = c.execute("SELECT COUNT(*) FROM price_ticks").fetchone()[0]
        out["per_symbol"] = c.execute(
            "SELECT symbol, COUNT(*), ROUND(SUM(notional),0) FROM liq_events "
            "GROUP BY symbol ORDER BY 2 DESC").fetchall()
        span = c.execute("SELECT MIN(ts_event), MAX(ts_event) FROM liq_events").fetchone()
        out["liq_span_ms"] = span
        pspan = c.execute("SELECT MIN(ts), MAX(ts) FROM price_ticks").fetchone()
        out["price_span_ms"] = pspan
        return out

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()


def _fmt_span(span: tuple) -> str:
    if not span or span[0] is None:
        return "brak danych"
    hrs = (span[1] - span[0]) / 3_600_000
    return f"{hrs:.2f} h"


if __name__ == "__main__":
    # szybki podglad: python store.py
    s = Store()
    summ = s.summary()
    print(f"DB: {s.path}")
    print(f"Likwidacje: {summ['liq_total']}  |  ticki ceny: {summ['price_total']}")
    print(f"Zakres likwidacji: {_fmt_span(summ['liq_span_ms'])}")
    print("Per symbol (count, suma notional USD):")
    for sym, cnt, notional in summ["per_symbol"]:
        print(f"  {sym:14s} {cnt:6d}  ${notional or 0:,.0f}")
    s.close()
