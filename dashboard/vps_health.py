#!/usr/bin/env python3
"""
VPS Health & Alerts API — lekki read-only HTTP server dla Alpha Desk.
Stdlib only, zero zależności. Bezpieczny: tylko odczyt SQLite.

Start (VPS):
  nohup python3 /trading-ai/dashboard/vps_health.py >> /trading-ai/logs/vps_health.log 2>&1 &

Cron (opcjonalnie — restart po reboocie):
  @reboot sleep 10 && nohup /trading-ai/.venv/bin/python /trading-ai/dashboard/vps_health.py >> /trading-ai/logs/vps_health.log 2>&1 &

Endpointy:
  GET /health   →  recency botów (dla kropelek w Bots panel)
  GET /alerts   →  najnowsze alerty (sm_alerts, listing_announcements, insider_signals)
"""
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

DB = Path('/trading-ai/data/trading.db')
PORT = 5008


# ── DB helpers ────────────────────────────────────────────────────────────────

def db_query(sql: str, params: tuple = ()):
    """Safe read-only SQLite query — returns [] on any error."""
    try:
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        rows = con.execute(sql, params).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _parse_ts(last_val) -> datetime | None:
    """Parse various timestamp formats to UTC-aware datetime."""
    try:
        ts_str = str(last_val).replace('Z', '+00:00').replace(' UTC', '+00:00')
        # Add missing seconds: "08:36+00:00" → "08:36:00+00:00"
        ts_str = re.sub(r'(\d{2}:\d{2})([+-]\d{2}:\d{2})$', r'\1:00\2', ts_str)
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def check_table(table: str, window_h: int = 25) -> dict:
    """Return health dict for a table based on MAX(ts) recency."""
    rows = db_query(f'SELECT MAX(ts) AS last FROM {table}')
    last_val = rows[0]['last'] if rows and rows[0] else None
    return _parse_health(last_val, window_h)


# ── Response builders ─────────────────────────────────────────────────────────

def check_listings_health() -> dict:
    """Check listings scanner health via scanner_runs heartbeat (written every scan)."""
    # Prefer scanner_runs (written every scan) over listing_announcements (only on finds)
    rows = db_query("SELECT MAX(ts) AS last FROM scanner_runs WHERE scanner='listings'")
    last_val = rows[0]['last'] if rows and rows[0] else None
    if not last_val:
        # Fall back to listing_announcements if scanner_runs table doesn't exist yet
        return check_table('listing_announcements', window_h=168)
    return _parse_health(last_val, window_h=2)  # active if ran within 2h


def _parse_health(last_val, window_h: int) -> dict:
    """Convert a timestamp to a health dict."""
    if not last_val:
        return {'active': False, 'last': None, 'ago': 'Brak danych w DB'}
    dt = _parse_ts(last_val)
    if dt is None:
        return {'active': False, 'last': str(last_val)[:16], 'ago': '?'}
    ago_s = (datetime.now(timezone.utc) - dt).total_seconds()
    if   ago_s < 60:    ago = f'{int(ago_s)}s temu'
    elif ago_s < 3600:  ago = f'{int(ago_s / 60)}m temu'
    elif ago_s < 86400: ago = f'{ago_s / 3600:.1f}h temu'
    else:               ago = f'{ago_s / 86400:.1f}d temu'
    return {'active': ago_s < window_h * 3600, 'last': str(last_val)[:16], 'ago': ago}


def check_kozaki_health() -> dict:
    """Check kozaki monitor health via scanner_runs heartbeat."""
    rows = db_query("SELECT MAX(ts) AS last FROM scanner_runs WHERE scanner='kozaki'")
    last_val = rows[0]['last'] if rows and rows[0] else None
    if not last_val:
        return check_table('kozaki_snapshots', window_h=25)
    return _parse_health(last_val, window_h=2)


def get_health() -> dict:
    return {
        'smart_money': check_table('sm_snapshots',     window_h=25),
        'volume':      check_table('volume_anomalies', window_h=168),
        'listings':    check_listings_health(),
        'insider':     check_table('insider_signals',  window_h=168),
        'kozaki':      check_kozaki_health(),
    }


def get_alerts() -> dict:
    return {
        'smart_money': db_query(
            'SELECT ts, alert_type, coin, side, wallet, notional, details '
            'FROM sm_alerts ORDER BY ts DESC LIMIT 300'
        ),
        # Historia alertów SM dla wykresu Activity — pełne okno 14 dni, ASC dla rysowania
        'smart_money_chart': db_query(
            'SELECT ts, alert_type, coin, side, wallet, notional, details '
            'FROM sm_alerts WHERE ts >= ? ORDER BY ts ASC LIMIT 5000',
            ((datetime.now(timezone.utc) - timedelta(days=14)).strftime('%Y-%m-%d %H:%M'),)
        ),
        'listings': db_query(
            'SELECT ts, ticker AS symbol, exchange, url AS announce_url, title, ann_type '
            'FROM listing_announcements ORDER BY ts DESC LIMIT 30'
        ),
        'insider': db_query(
            'SELECT ts, scout, ticker, direction, confidence, reason '
            'FROM insider_signals ORDER BY ts DESC LIMIT 30'
        ),
        'kozaki': db_query(
            'SELECT ts, alert_type, wallet, label, coin, side, notional, details '
            'FROM kozaki_alerts ORDER BY ts DESC LIMIT 50'
        ),
        # Aktualny snapshot SM — pozycje z ostatniego skanu (dla Whale Thermometru)
        'sm_snapshot': db_query(
            '''SELECT coin, side,
                      SUM(notional)          AS notional,
                      COUNT(DISTINCT wallet) AS wallet_count
               FROM sm_snapshots
               WHERE ts = (SELECT MAX(ts) FROM sm_snapshots)
               GROUP BY coin, side
               ORDER BY notional DESC'''
        ),
        # Aktualny snapshot Kozaki — top pozycje z ostatniego skanu
        'kozaki_snapshot': db_query(
            '''SELECT ks.wallet, ks.coin, ks.side, ks.notional, ks.entry, ks.lev, ks.upnl,
                      ka.label
               FROM kozaki_snapshots ks
               LEFT JOIN (
                   SELECT wallet, MAX(label) AS label FROM kozaki_alerts GROUP BY wallet
               ) ka ON ks.wallet = ka.wallet
               WHERE ks.ts = (SELECT MAX(ts) FROM kozaki_snapshots)
               ORDER BY ks.notional DESC LIMIT 20'''
        ),
    }


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # cichy access log

    def _send_json(self, data: dict):
        body = json.dumps(data, default=str).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/health':
            self._send_json(get_health())
        elif path == '/alerts':
            self._send_json(get_alerts())
        elif path == '/ping':
            self._send_json({'ok': True})
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'[VPS Health] port {PORT}  db={DB}', flush=True)
    server.serve_forever()
