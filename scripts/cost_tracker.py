"""cost_tracker.py — Centralne logowanie kosztów API do SQLite.

Używaj w każdym skrypcie który woła zewnętrzne API:

    from scripts.cost_tracker import log_cost
    cost = log_cost("grok", "grok-4.3", resp_json, script="x_sentiment", operation="query_live BTC")

Tabela api_costs w data/trading.db:
  ts, service, model, script, operation, input_tokens, output_tokens, cost_usd, details
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ── Pricing (per token) ────────────────────────────────────────────────────
PRICING: dict[str, dict[str, float]] = {
    # xAI / Grok
    "grok-4.3":           {"input": 1.25  / 1_000_000, "output": 2.50  / 1_000_000},
    "grok-4":             {"input": 1.25  / 1_000_000, "output": 2.50  / 1_000_000},
    "grok-3":             {"input": 3.00  / 1_000_000, "output": 15.00 / 1_000_000},
    "grok-3-mini":        {"input": 0.30  / 1_000_000, "output": 0.50  / 1_000_000},
    "grok-3-mini-fast":   {"input": 0.30  / 1_000_000, "output": 0.50  / 1_000_000},
    # DeepSeek
    "deepseek-chat":      {"input": 0.07  / 1_000_000, "output": 1.10  / 1_000_000},
    "deepseek-reasoner":  {"input": 0.55  / 1_000_000, "output": 2.19  / 1_000_000},
    # Firecrawl — per-credit model (1 credit ≈ 1 page scrape)
    "firecrawl":          {"credit": 1.0 / 1000},  # $1 / 1000 credits (estimate)
}

DB_PATH = Path(__file__).parent.parent / "data" / "trading.db"


def _init_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_costs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            service       TEXT    NOT NULL,
            model         TEXT    DEFAULT '',
            script        TEXT    DEFAULT '',
            operation     TEXT    DEFAULT '',
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd      REAL    DEFAULT 0,
            details       TEXT    DEFAULT ''
        )
    """)
    conn.commit()


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING.get(model, {})
    return p.get("input", 0.0) * input_tokens + p.get("output", 0.0) * output_tokens


def log_cost(
    service: str,
    model: str,
    resp_json: dict | None = None,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    script: str = "",
    operation: str = "",
    details: str = "",
    credits: int = 0,
) -> float:
    """Log an API call cost to the DB. Returns cost in USD.

    Pass either:
    - resp_json — raw API response JSON (tokens extracted automatically)
    - input_tokens / output_tokens — explicit token counts
    - credits — for Firecrawl (credits used)
    """
    # Extract tokens from common API response formats
    if resp_json:
        usage = resp_json.get("usage") or {}
        # OpenAI-compatible (chat completions)
        input_tokens  = input_tokens  or usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
        output_tokens = output_tokens or usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
        # xAI Responses API
        if not input_tokens and not output_tokens:
            input_tokens  = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

    # Firecrawl credit model
    if service == "firecrawl" and credits:
        cost_usd = PRICING["firecrawl"]["credit"] * credits
    else:
        cost_usd = _calc_cost(model, input_tokens, output_tokens)

    try:
        with sqlite3.connect(DB_PATH) as conn:
            _init_table(conn)
            conn.execute(
                """INSERT INTO api_costs
                   (service, model, script, operation, input_tokens, output_tokens, cost_usd, details)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (service, model, script, operation,
                 input_tokens, output_tokens, round(cost_usd, 8),
                 details[:500] if details else ""),
            )
            conn.commit()
    except Exception as e:
        # Never crash the caller due to cost logging failure
        print(f"[cost_tracker] DB error: {e}")

    return cost_usd


def log_firecrawl(script: str, credits_used: int, operation: str = "", details: str = "") -> float:
    """Shorthand for Firecrawl credit logging."""
    return log_cost("firecrawl", "firecrawl", credits=credits_used,
                    script=script, operation=operation, details=details)


def get_summary(days: int = 30) -> list[dict]:
    """Return daily cost totals grouped by service for last N days."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            _init_table(conn)
            rows = conn.execute("""
                SELECT
                    substr(ts,1,10)          AS date,
                    service,
                    script,
                    COUNT(*)                 AS calls,
                    SUM(input_tokens)        AS in_tok,
                    SUM(output_tokens)       AS out_tok,
                    ROUND(SUM(cost_usd), 6)  AS cost
                FROM api_costs
                WHERE ts >= datetime('now', ?)
                GROUP BY date, service, script
                ORDER BY date DESC, cost DESC
            """, (f"-{days} days",)).fetchall()
        return [
            {"date": r[0], "service": r[1], "script": r[2],
             "calls": r[3], "in_tok": r[4], "out_tok": r[5], "cost": r[6]}
            for r in rows
        ]
    except Exception:
        return []


def get_recent(limit: int = 50) -> list[dict]:
    """Return recent individual API calls."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            _init_table(conn)
            rows = conn.execute("""
                SELECT ts, service, model, script, operation,
                       input_tokens, output_tokens, cost_usd
                FROM api_costs
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [
            {"ts": r[0], "service": r[1], "model": r[2], "script": r[3],
             "operation": r[4], "in_tok": r[5], "out_tok": r[6], "cost": r[7]}
            for r in rows
        ]
    except Exception:
        return []


def get_totals() -> dict:
    """Return aggregated cost totals: today, 7d, 30d, all-time."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            _init_table(conn)
            def q(where):
                row = conn.execute(
                    f"SELECT ROUND(SUM(cost_usd),4), COUNT(*), "
                    f"SUM(input_tokens), SUM(output_tokens) "
                    f"FROM api_costs WHERE {where}"
                ).fetchone()
                return {"cost": row[0] or 0, "calls": row[1] or 0,
                        "in_tok": row[2] or 0, "out_tok": row[3] or 0}
            return {
                "today":    q("date(ts) = date('now')"),
                "week":     q("ts >= datetime('now','-7 days')"),
                "month":    q("ts >= datetime('now','-30 days')"),
                "alltime":  q("1=1"),
            }
    except Exception:
        return {"today": {}, "week": {}, "month": {}, "alltime": {}}
