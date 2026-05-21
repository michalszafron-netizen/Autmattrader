"""Unified database layer — SQLite local + PocketBase VPS dual-write.

SQLite is always active (local file).
PocketBase is activated when POCKETBASE_URL is set in .env.
Dual-write: data goes to both simultaneously when both are configured.

Usage:
  from db import DB
  db = DB()
  db.save_trending(tokens_list)
  db.save_x_sentiment(results_list)
  db.save_whale_snapshot(coin, data)
  db.save_daily_brief(content)
  db.save_token_research(ticker, ca, data)
  db.save_trade_alert(data)
  db.save_econ_event(data)
  db.save_telegram_query(user_id, query, response)

  # Query examples
  db.get_trending(days=7)       # last 7 days
  db.get_token_history(ticker)  # all research entries for a token
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ── Env setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
_ENV = _ROOT / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

DB_PATH = Path(os.getenv("SQLITE_PATH", str(_ROOT / "data" / "trading.db")))
POCKETBASE_URL = os.getenv("POCKETBASE_URL", "").rstrip("/")


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_briefs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    source      TEXT    DEFAULT 'daily-alpha'
);

CREATE TABLE IF NOT EXISTS trending_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    date            TEXT    NOT NULL,
    rank            INTEGER,
    ticker          TEXT    NOT NULL,
    name            TEXT,
    chain           TEXT,
    contract        TEXT,
    buzz_score      INTEGER,
    sentiment       TEXT,
    risk            TEXT,
    mentions_24h    INTEGER,
    top_post_likes  INTEGER,
    top_post_rts    INTEGER,
    top_post_author TEXT,
    engagement_trend TEXT,
    is_verified     INTEGER DEFAULT 0,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_trending_ticker ON trending_tokens(ticker);
CREATE INDEX IF NOT EXISTS idx_trending_date   ON trending_tokens(date);

CREATE TABLE IF NOT EXISTS whale_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    date        TEXT NOT NULL,
    coin        TEXT NOT NULL,
    window      TEXT NOT NULL,
    long_count  INTEGER,
    short_count INTEGER,
    net_usd     REAL,
    consensus   REAL,
    raw_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_whale_coin ON whale_snapshots(coin);

CREATE TABLE IF NOT EXISTS cot_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    date            TEXT NOT NULL,
    asset           TEXT NOT NULL,
    net_long        INTEGER,
    net_long_chg    INTEGER,
    commercials_net INTEGER,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_cot_asset ON cot_snapshots(asset);

CREATE TABLE IF NOT EXISTS x_sentiment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    date        TEXT NOT NULL,
    coin        TEXT NOT NULL,
    sentiment   TEXT,
    score       INTEGER,
    summary     TEXT,
    raw_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_xsent_coin ON x_sentiment(coin);

CREATE TABLE IF NOT EXISTS econ_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    event_date  TEXT NOT NULL,
    event_time  TEXT,
    name        TEXT NOT NULL,
    country     TEXT,
    importance  TEXT,
    actual      TEXT,
    forecast    TEXT,
    previous    TEXT,
    impact_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_econ_date ON econ_events(event_date);

CREATE TABLE IF NOT EXISTS token_research (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    date        TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    contract    TEXT,
    chain       TEXT,
    name        TEXT,
    price_usd   REAL,
    mcap_usd    REAL,
    rug_score   TEXT,
    verdict     TEXT,
    summary     TEXT,
    raw_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_token_ticker   ON token_research(ticker);
CREATE INDEX IF NOT EXISTS idx_token_contract ON token_research(contract);

CREATE TABLE IF NOT EXISTS trade_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    date        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    entry       REAL,
    sl          REAL,
    tp1         REAL,
    tp2         REAL,
    tp3         REAL,
    size_usd    REAL,
    venue       TEXT,
    strategy    TEXT,
    status      TEXT DEFAULT 'open',
    raw_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_symbol ON trade_alerts(symbol);

CREATE TABLE IF NOT EXISTS positions_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open         TEXT NOT NULL,
    ts_close        TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    entry           REAL,
    exit_price      REAL,
    size_usd        REAL,
    pnl_usd         REAL,
    pnl_pct         REAL,
    venue           TEXT,
    strategy        TEXT,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_pos_symbol ON positions_history(symbol);

CREATE TABLE IF NOT EXISTS oi_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    coin            TEXT NOT NULL,
    oi_binance      REAL DEFAULT 0,
    oi_bybit        REAL DEFAULT 0,
    oi_extended     REAL DEFAULT 0,
    oi_total        REAL DEFAULT 0,
    mark_price      REAL,
    funding_rate    REAL,
    UNIQUE(ts, coin)
);
CREATE INDEX IF NOT EXISTS idx_oi_coin ON oi_snapshots(coin);
CREATE INDEX IF NOT EXISTS idx_oi_ts   ON oi_snapshots(ts);

CREATE TABLE IF NOT EXISTS telegram_queries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    user_id     TEXT,
    query       TEXT NOT NULL,
    response    TEXT,
    latency_ms  INTEGER
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── SQLite backend ────────────────────────────────────────────────────────────
class _SQLite:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


# ── PocketBase REST backend ────────────────────────────────────────────────────
class _PocketBase:
    """Thin REST client for PocketBase collections API."""

    def __init__(self, url: str):
        self.url = url
        self._token: str | None = None

    def _auth(self) -> str:
        if self._token:
            return self._token
        import urllib.request
        pb_email = os.getenv("POCKETBASE_EMAIL", "")
        pb_pass  = os.getenv("POCKETBASE_PASSWORD", "")
        if not pb_email or not pb_pass:
            return ""
        payload = json.dumps({"identity": pb_email, "password": pb_pass}).encode()
        req = urllib.request.Request(
            f"{self.url}/api/admins/auth-with-password",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                self._token = data.get("token", "")
                return self._token
        except Exception:
            return ""

    def create(self, collection: str, record: dict) -> bool:
        import urllib.request
        token = self._auth()
        payload = json.dumps(record).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = token
        req = urllib.request.Request(
            f"{self.url}/api/collections/{collection}/records",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception as e:
            print(f"[DB] PocketBase write failed ({collection}): {e}")
            return False


# ── Main DB interface ─────────────────────────────────────────────────────────
class DB:
    def __init__(self):
        self._sqlite = _SQLite(DB_PATH)
        self._pb = _PocketBase(POCKETBASE_URL) if POCKETBASE_URL else None
        self._pb_ok = bool(POCKETBASE_URL)

    def _pb_write(self, collection: str, record: dict):
        if self._pb and self._pb_ok:
            self._pb.create(collection, record)

    # ── Trending tokens ──────────────────────────────────────────────────────
    def save_trending(self, tokens: list[dict]) -> None:
        ts = _now()
        date = _today()
        for t in tokens:
            self._sqlite.execute(
                """INSERT INTO trending_tokens
                   (ts, date, rank, ticker, name, chain, contract, buzz_score,
                    sentiment, risk, mentions_24h, top_post_likes, top_post_rts,
                    top_post_author, engagement_trend, is_verified, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts, date,
                    t.get("rank"),
                    t.get("ticker", ""),
                    t.get("name", ""),
                    t.get("chain", ""),
                    t.get("contract", ""),
                    t.get("buzz_score"),
                    t.get("sentiment", ""),
                    t.get("risk", ""),
                    t.get("mentions_24h"),
                    t.get("top_post_likes"),
                    t.get("top_post_rts"),
                    t.get("top_post_author", ""),
                    t.get("engagement_trend", ""),
                    1 if t.get("is_verified") else 0,
                    json.dumps(t),
                ),
            )
            self._pb_write("trending_tokens", {"ts": ts, "date": date, **t})

    def get_trending(self, days: int = 7, ticker: str | None = None) -> list[dict]:
        cutoff = datetime.now(timezone.utc).strftime(f"%Y-%m-%d")
        if ticker:
            return self._sqlite.query(
                "SELECT * FROM trending_tokens WHERE ticker=? ORDER BY ts DESC",
                (ticker.upper(),),
            )
        return self._sqlite.query(
            f"""SELECT date, ticker, chain, buzz_score, sentiment, risk,
                       mentions_24h, top_post_likes, engagement_trend, is_verified
                FROM trending_tokens
                WHERE date >= date('now', '-{days} days')
                ORDER BY ts DESC""",
        )

    # ── X Sentiment ──────────────────────────────────────────────────────────
    def save_x_sentiment(self, results: list[dict]) -> None:
        ts = _now()
        date = _today()
        for r in results:
            self._sqlite.execute(
                """INSERT INTO x_sentiment (ts, date, coin, sentiment, score, summary, raw_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    ts, date,
                    r.get("coin", r.get("ticker", "")),
                    r.get("sentiment", ""),
                    r.get("score"),
                    r.get("summary", ""),
                    json.dumps(r),
                ),
            )
            self._pb_write("x_sentiment", {"ts": ts, "date": date, **r})

    # ── Whale snapshots ──────────────────────────────────────────────────────
    def save_whale_snapshot(self, coin: str, window: str, data: dict) -> None:
        ts = _now()
        date = _today()
        self._sqlite.execute(
            """INSERT INTO whale_snapshots
               (ts, date, coin, window, long_count, short_count, net_usd, consensus, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                ts, date, coin, window,
                data.get("long_count"),
                data.get("short_count"),
                data.get("net_usd"),
                data.get("consensus"),
                json.dumps(data),
            ),
        )
        self._pb_write("whale_snapshots", {"ts": ts, "date": date, "coin": coin, "window": window, **data})

    # ── COT snapshots ────────────────────────────────────────────────────────
    def save_cot_snapshot(self, asset: str, data: dict) -> None:
        ts = _now()
        date = _today()
        self._sqlite.execute(
            """INSERT INTO cot_snapshots
               (ts, date, asset, net_long, net_long_chg, commercials_net, raw_json)
               VALUES (?,?,?,?,?,?,?)""",
            (
                ts, date, asset,
                data.get("net_long"),
                data.get("net_long_chg"),
                data.get("commercials_net"),
                json.dumps(data),
            ),
        )
        self._pb_write("cot_snapshots", {"ts": ts, "date": date, "asset": asset, **data})

    # ── Daily brief ──────────────────────────────────────────────────────────
    def save_daily_brief(self, content: str, source: str = "daily-alpha") -> None:
        ts = _now()
        date = _today()
        self._sqlite.execute(
            "INSERT INTO daily_briefs (ts, date, content, source) VALUES (?,?,?,?)",
            (ts, date, content, source),
        )
        self._pb_write("daily_briefs", {"ts": ts, "date": date, "content": content, "source": source})

    def get_daily_briefs(self, days: int = 30) -> list[dict]:
        return self._sqlite.query(
            f"SELECT ts, date, source, content FROM daily_briefs "
            f"WHERE date >= date('now', '-{days} days') ORDER BY ts DESC"
        )

    def get_context_for_daily_brief(self, days: int = 5) -> str:
        """Compact context string for injecting into daily-alpha prompt.

        Returns a block of text describing what was noted in recent briefs
        so Claude doesn't repeat unchanged observations.
        """
        briefs = self.get_daily_briefs(days=days)
        if not briefs:
            return ""
        lines = ["=== CONTEXT FROM PREVIOUS DAILY BRIEFS ===",
                 "Use this to AVOID repeating unchanged observations.",
                 "Only mention a point again if something materially changed.",
                 ""]
        for b in briefs[:5]:  # max 5 recent briefs
            date = b.get("date", "?")
            # Truncate long briefs to first 800 chars for context window efficiency
            content = b.get("content", "")[:800]
            lines.append(f"--- {date} ---")
            lines.append(content)
            lines.append("")
        lines.append("=== END CONTEXT ===")
        return "\n".join(lines)

    def get_trending_context(self, days: int = 7) -> str:
        """Compact context string describing recent trending history.

        Injected into Grok's trending prompt so it can say
        'this token appeared 3 days in a row' vs treating it as new.
        """
        rows = self.trending_compare(days=days)
        if not rows:
            return ""
        lines = ["Previously seen trending tokens (last 7 days):"]
        for r in rows:
            ticker = r.get("ticker", "")
            chain = r.get("chain", "")
            n = r.get("appearances", 1)
            first = r.get("first_seen", "")
            last = r.get("last_seen", "")
            buzz_max = r.get("max_buzz", "?")
            likes = r.get("peak_likes", 0)
            sents = r.get("sentiments", "")
            verified = "*verified*" if r.get("verified_count", 0) > 0 else ""
            if first == last:
                seen_str = f"seen once ({first})"
            else:
                seen_str = f"seen {n}x from {first} to {last}"
            lines.append(
                f"  ${ticker} ({chain}): {seen_str}, max buzz {buzz_max}/10, "
                f"peak likes {likes}, sentiment: {sents} {verified}"
            )
        lines.append("")
        lines.append("For tokens already in this list:")
        lines.append("- Note if momentum is CONTINUING or FADING compared to before")
        lines.append("- Flag tokens appearing 3+ days as 'sustained' vs one-day wonders")
        return "\n".join(lines)

    # ── Econ events ──────────────────────────────────────────────────────────
    def save_econ_event(self, event: dict) -> None:
        ts = _now()
        self._sqlite.execute(
            """INSERT INTO econ_events
               (ts, event_date, event_time, name, country, importance,
                actual, forecast, previous, impact_note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                ts,
                event.get("date", ""),
                event.get("time", ""),
                event.get("name", ""),
                event.get("country", ""),
                event.get("importance", ""),
                event.get("actual"),
                event.get("forecast"),
                event.get("previous"),
                event.get("impact_note", ""),
            ),
        )
        self._pb_write("econ_events", {"ts": ts, **event})

    # ── Token research ───────────────────────────────────────────────────────
    def save_token_research(self, ticker: str, contract: str | None, data: dict) -> None:
        ts = _now()
        date = _today()
        self._sqlite.execute(
            """INSERT INTO token_research
               (ts, date, ticker, contract, chain, name, price_usd, mcap_usd,
                rug_score, verdict, summary, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ts, date,
                ticker,
                contract or "",
                data.get("chain", ""),
                data.get("name", ""),
                data.get("price_usd"),
                data.get("mcap_usd"),
                data.get("rug_score", ""),
                data.get("verdict", ""),
                data.get("summary", ""),
                json.dumps(data),
            ),
        )
        self._pb_write("token_research", {"ts": ts, "date": date, "ticker": ticker, "contract": contract or "", **data})

    def get_token_history(self, ticker: str) -> list[dict]:
        return self._sqlite.query(
            "SELECT ts, date, price_usd, mcap_usd, rug_score, verdict, summary "
            "FROM token_research WHERE ticker=? ORDER BY ts DESC",
            (ticker.upper(),),
        )

    def trending_compare(self, days: int = 7) -> list[dict]:
        """Per-ticker summary: first seen, last seen, buzz range, trend direction."""
        return self._sqlite.query(
            f"""
            SELECT
                ticker,
                chain,
                COUNT(*)            AS appearances,
                MIN(date)           AS first_seen,
                MAX(date)           AS last_seen,
                MAX(buzz_score)     AS max_buzz,
                MIN(buzz_score)     AS min_buzz,
                GROUP_CONCAT(DISTINCT sentiment) AS sentiments,
                SUM(is_verified)    AS verified_count,
                MAX(top_post_likes) AS peak_likes
            FROM trending_tokens
            WHERE date >= date('now', '-{days} days')
            GROUP BY ticker, chain
            ORDER BY appearances DESC, max_buzz DESC
            """
        )

    # ── Trade alerts ─────────────────────────────────────────────────────────
    def save_trade_alert(self, alert: dict) -> None:
        ts = _now()
        date = _today()
        self._sqlite.execute(
            """INSERT INTO trade_alerts
               (ts, date, symbol, side, entry, sl, tp1, tp2, tp3,
                size_usd, venue, strategy, status, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ts, date,
                alert.get("symbol", ""),
                alert.get("side", ""),
                alert.get("entry"),
                alert.get("sl"),
                alert.get("tp1"),
                alert.get("tp2"),
                alert.get("tp3"),
                alert.get("size_usd"),
                alert.get("venue", ""),
                alert.get("strategy", ""),
                alert.get("status", "open"),
                json.dumps(alert),
            ),
        )
        self._pb_write("trade_alerts", {"ts": ts, "date": date, **alert})

    # ── Positions history ────────────────────────────────────────────────────
    def save_position(self, position: dict) -> None:
        self._sqlite.execute(
            """INSERT INTO positions_history
               (ts_open, ts_close, symbol, side, entry, exit_price, size_usd,
                pnl_usd, pnl_pct, venue, strategy, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                position.get("ts_open", _now()),
                position.get("ts_close"),
                position.get("symbol", ""),
                position.get("side", ""),
                position.get("entry"),
                position.get("exit_price"),
                position.get("size_usd"),
                position.get("pnl_usd"),
                position.get("pnl_pct"),
                position.get("venue", ""),
                position.get("strategy", ""),
                json.dumps(position),
            ),
        )
        self._pb_write("positions_history", position)

    # ── Telegram queries ─────────────────────────────────────────────────────
    def save_telegram_query(
        self,
        query: str,
        response: str = "",
        user_id: str = "",
        latency_ms: int | None = None,
    ) -> None:
        ts = _now()
        self._sqlite.execute(
            "INSERT INTO telegram_queries (ts, user_id, query, response, latency_ms) VALUES (?,?,?,?,?)",
            (ts, user_id, query, response, latency_ms),
        )
        self._pb_write("telegram_queries", {"ts": ts, "user_id": user_id, "query": query})

    # ── Stats / diagnostics ──────────────────────────────────────────────────
    def stats(self) -> dict:
        tables = [
            "daily_briefs", "trending_tokens", "whale_snapshots",
            "cot_snapshots", "x_sentiment", "econ_events",
            "token_research", "trade_alerts", "positions_history",
            "oi_snapshots", "telegram_queries",
        ]
        counts = {}
        for t in tables:
            row = self._sqlite.query(f"SELECT COUNT(*) AS n FROM {t}")
            counts[t] = row[0]["n"] if row else 0
        return {
            "sqlite_path": str(DB_PATH),
            "pocketbase": POCKETBASE_URL or "not configured",
            "tables": counts,
        }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    db = DB()

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        s = db.stats()
        print(f"\nSQLite: {s['sqlite_path']}")
        print(f"PocketBase: {s['pocketbase']}\n")
        print(f"{'Table':<25} {'Rows':>6}")
        print("-" * 33)
        for table, n in s["tables"].items():
            print(f"  {table:<23} {n:>6}")
        print()
    elif len(sys.argv) > 1 and sys.argv[1] == "trending":
        rows = db.get_trending(days=7)
        if not rows:
            print("No trending data yet.")
        else:
            print(f"\nLast 7 days — {len(rows)} entries\n")
            for r in rows[:20]:
                verified = "[V]" if r.get("is_verified") else "   "
                print(f"  {r['date']}  {verified}  {r['ticker']:<12} {r['chain']:<10} "
                      f"buzz={r.get('buzz_score','?')}  {r.get('sentiment','')}")
    elif len(sys.argv) > 1 and sys.argv[1] == "compare":
        rows = db.trending_compare(days=7)
        if not rows:
            print("No trending data yet. Run 'python scripts/x_sentiment.py trending' first.")
        else:
            print(f"\nTrending token history — last 7 days\n")
            print(f"  {'Ticker':<12} {'Chain':<10} {'Seen':>4}  {'First':>10}  {'Last':>10}  {'Buzz':>4}  {'Likes':>6}  Sentiments")
            print("  " + "-" * 80)
            for r in rows:
                v = "*" if r.get("verified_count", 0) > 0 else " "
                print(f"  {r['ticker']:<12} {r.get('chain',''):<10} {r['appearances']:>4}{v} "
                      f" {r['first_seen']:>10}  {r['last_seen']:>10}  {r.get('max_buzz','?'):>4}  "
                      f"{r.get('peak_likes',0):>6}  {r.get('sentiments','')}")
    elif len(sys.argv) > 1 and sys.argv[1] == "context-daily":
        ctx = db.get_context_for_daily_brief()
        if not ctx:
            print("No daily briefs in DB yet.")
        else:
            print(ctx)
    elif len(sys.argv) > 1 and sys.argv[1] == "context-trending":
        ctx = db.get_trending_context()
        if not ctx:
            print("No trending history in DB yet.")
        else:
            print(ctx)
    else:
        print("Usage:")
        print("  python scripts/db.py stats             — row counts per table")
        print("  python scripts/db.py trending          — last 7 days trending tokens (raw)")
        print("  python scripts/db.py compare           — per-ticker history + appearances")
        print("  python scripts/db.py context-daily     — context block for daily-alpha prompt")
        print("  python scripts/db.py context-trending  — history block for trending prompt")
        print()
        s = db.stats()
        print(f"SQLite: {s['sqlite_path']}")
        print(f"PocketBase: {s['pocketbase']}")
        print("Database initialized OK.")
