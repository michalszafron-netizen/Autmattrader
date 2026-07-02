"""store.py — samowystarczalna warstwa SQLite dla ScalpBot3 Fazy 0.

Zero importow ze scripts/ — dziala identycznie na Windows i Linux VPS.
Wlasna baza data/scalpbot3.db, NIE dotyka glownego db.py.

Schemat:
  ticks   — kazdy tick cenowy z dowolnego zrodla, timestamp ms (nasz zegar) + src_ts_ms (publish)
  funding — snapshot funding rate per zrodlo/aktywo (dla strategii B carry)
  meta    — rozwiazania Pyth id, info o runie
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "scalpbot3.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
  id        INTEGER PRIMARY KEY,
  ts_ms     INTEGER NOT NULL,   -- czas odbioru (nasz zegar), ms
  src_ts_ms INTEGER,            -- czas publikacji ze zrodla, ms (Pyth publish_time)
  source    TEXT NOT NULL,      -- 'pyth' | 'hl_xyz' | 'hl_perp' | 'extended'
  asset     TEXT NOT NULL,      -- kanoniczny: GOLD SILVER CL SP500 BTC ETH SOL HYPE
  symbol    TEXT NOT NULL,      -- surowy symbol na tym zrodle
  price     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticks_asset_ts ON ticks(asset, ts_ms);
CREATE INDEX IF NOT EXISTS idx_ticks_src_ts   ON ticks(source, ts_ms);

CREATE TABLE IF NOT EXISTS funding (
  id           INTEGER PRIMARY KEY,
  ts_ms        INTEGER NOT NULL,
  source       TEXT NOT NULL,
  asset        TEXT NOT NULL,
  symbol       TEXT NOT NULL,
  funding_rate REAL,
  mark         REAL,
  oracle       REAL
);
CREATE INDEX IF NOT EXISTS idx_funding_asset_ts ON funding(asset, ts_ms);

CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY,
  v TEXT
);
"""


def _connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.executescript(_SCHEMA)
    con.commit()
    return con


class Store:
    """Jeden watek zapisujacy, kolejka z pollerow. Unika problemow SQLite+watki."""

    def __init__(self, path: Path = DB_PATH, batch_ms: int = 500):
        self.path = path
        self.batch_ms = batch_ms
        self._q: "queue.Queue[tuple]" = queue.Queue(maxsize=100_000)
        self._con = _connect(path)
        self._stop = threading.Event()
        self._writer = threading.Thread(target=self._run, name="store-writer", daemon=True)
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        self._writer.start()

    # ── API dla pollerow ────────────────────────────────────────────────────
    def push_tick(self, source: str, asset: str, symbol: str, price: float,
                  ts_ms: int, src_ts_ms: int | None = None) -> None:
        self._q.put(("tick", ts_ms, src_ts_ms, source, asset, symbol, price))

    def push_funding(self, source: str, asset: str, symbol: str, ts_ms: int,
                     funding_rate: float | None, mark: float | None = None,
                     oracle: float | None = None) -> None:
        self._q.put(("funding", ts_ms, source, asset, symbol, funding_rate, mark, oracle))

    def set_meta(self, k: str, v) -> None:
        self._con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)",
                          (k, json.dumps(v) if not isinstance(v, str) else v))
        self._con.commit()

    # ── Writer loop ─────────────────────────────────────────────────────────
    def _run(self) -> None:
        ticks: list[tuple] = []
        fundings: list[tuple] = []
        last_flush = time.monotonic()
        while not self._stop.is_set() or not self._q.empty():
            try:
                item = self._q.get(timeout=0.2)
                if item[0] == "tick":
                    _, ts_ms, src_ts_ms, source, asset, symbol, price = item
                    ticks.append((ts_ms, src_ts_ms, source, asset, symbol, price))
                    with self._lock:
                        self._counts[source] = self._counts.get(source, 0) + 1
                else:
                    _, ts_ms, source, asset, symbol, fr, mark, oracle = item
                    fundings.append((ts_ms, source, asset, symbol, fr, mark, oracle))
            except queue.Empty:
                pass

            now = time.monotonic()
            if (now - last_flush) * 1000 >= self.batch_ms or len(ticks) >= 500:
                self._flush(ticks, fundings)
                ticks, fundings = [], []
                last_flush = now
        self._flush(ticks, fundings)

    def _flush(self, ticks: list[tuple], fundings: list[tuple]) -> None:
        if not ticks and not fundings:
            return
        try:
            if ticks:
                self._con.executemany(
                    "INSERT INTO ticks(ts_ms, src_ts_ms, source, asset, symbol, price) "
                    "VALUES (?,?,?,?,?,?)", ticks)
            if fundings:
                self._con.executemany(
                    "INSERT INTO funding(ts_ms, source, asset, symbol, funding_rate, mark, oracle) "
                    "VALUES (?,?,?,?,?,?,?)", fundings)
            self._con.commit()
        except Exception as e:  # nigdy nie zabijaj writera
            print(f"[store] flush error: {e}")

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def stop(self) -> None:
        self._stop.set()
        self._writer.join(timeout=5)
        try:
            self._con.close()
        except Exception:
            pass


# ── Narzedzia read-only (dla --stats / research) ─────────────────────────────

def read_con(path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con
