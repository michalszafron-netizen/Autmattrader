"""
Alpha Desk — Trading Dashboard Backend
Flask REST API on port 5007
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import re
import shutil
import ssl

import httpx
import truststore
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

try:
    import ccxt as _ccxt
    _CCXT_OK = True
except ImportError:
    _ccxt = None  # type: ignore
    _CCXT_OK = False

# Strip ANSI / VT100 escape codes from script output
_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Truststore SSL context (Windows cert store) — same as project scripts use
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

ROOT   = Path(__file__).parent.parent
PY     = str(ROOT / '.venv' / 'Scripts' / 'python.exe')
SCRIPTS = ROOT / 'scripts'
DB_PATH = ROOT / 'data' / 'trading.db'
ALERTS_FILE = ROOT / 'alerts.jsonl'

load_dotenv(ROOT / '.env')

# Scripts whose output is worth saving to history (exclude polling/ticker scripts)
SAVE_HISTORY = {
    'x_sentiment.py', 'token_dashboard.py', 'hl_whale_tracker.py',
    'smart_money_tracker.py', 'fear_greed.py', 'oi_tracker.py',
    'cot_tracker.py', 'blogwatcher.py', 'polymarket.py',
    'macro_news.py', 'econ_calendar.py',
}


def init_db() -> None:
    """Create analysis_history table if it doesn't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute('''CREATE TABLE IF NOT EXISTS analysis_history (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            ts    TEXT    DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%S\',\'now\')),
            script TEXT   NOT NULL,
            label  TEXT,
            output TEXT,
            ok     INTEGER DEFAULT 1
        )''')
        con.commit()
        con.close()
    except Exception:
        pass


def _save_history(script: str, label: str, output: str) -> None:
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            'INSERT INTO analysis_history (script, label, output) VALUES (?,?,?)',
            (script, label, output[:60000])
        )
        con.commit()
        con.close()
    except Exception:
        pass


init_db()

app = Flask(__name__, static_folder=str(Path(__file__).parent), static_url_path='')

# ── Helpers ───────────────────────────────────────────────────────────────────

def strip_ansi(text: str) -> str:
    """Remove ANSI/VT100 escape codes from text."""
    return _ANSI_RE.sub('', text or '')


def run_script(script: str, args: list[str] = [], timeout: int = 90) -> dict:
    """Run a script from the scripts/ directory and return stdout.

    Uses binary capture + explicit UTF-8 decode — avoids Windows cp1252 pipe
    encoding issues that garble box-drawing / Unicode chars from rich scripts.
    """
    cmd = [PY, str(SCRIPTS / script)] + args
    _env = {
        **os.environ,
        'PYTHONIOENCODING': 'utf-8',   # subprocess writes UTF-8
        'PYTHONUTF8':       '1',       # Python 3.7+ UTF-8 mode
        'FORCE_COLOR':      '0',
        'NO_COLOR':         '1',
        'TERM':             'dumb',    # hint rich: no fancy terminal
    }
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            cwd=str(ROOT), env=_env
            # NO text=True — capture raw bytes, decode explicitly below
        )
        # Explicit UTF-8 decode: most reliable on Windows regardless of console CP
        raw_out = r.stdout or r.stderr or b''
        raw_err = r.stderr or b''
        out = strip_ansi(raw_out.decode('utf-8', errors='replace'))
        err = strip_ansi(raw_err.decode('utf-8', errors='replace')) if r.returncode != 0 else ''
        return {'ok': r.returncode == 0, 'output': out, 'error': err}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'output': '', 'error': f'Timeout after {timeout}s'}
    except Exception as e:
        return {'ok': False, 'output': '', 'error': str(e)}


def find_claude_exe() -> str | None:
    """Locate the claude CLI executable on Windows."""
    # 1. Try PATH (works if profile is loaded in the shell)
    c = shutil.which('claude')
    if c:
        return c
    # 2. WinGet Links (typical install location)
    local_app = Path(os.environ.get('LOCALAPPDATA', ''))
    winget = local_app / 'Microsoft' / 'WinGet' / 'Links'
    for name in ['claude.exe', 'claude.cmd', 'claude']:
        p = winget / name
        if p.exists():
            return str(p)
    # 3. npm global fallback
    for base_key in ['APPDATA', 'LOCALAPPDATA']:
        base = Path(os.environ.get(base_key, ''))
        for name in ['claude.cmd', 'claude.exe']:
            p = base / 'npm' / name
            if p.exists():
                return str(p)
    return None


def db_query(sql: str, params: tuple = (), one: bool = False):
    """Safe SQLite query, returns [] on error."""
    if not DB_PATH.exists():
        return None if one else []
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        cur = con.execute(sql, params)
        rows = cur.fetchone() if one else cur.fetchall()
        con.close()
        return [dict(r) for r in rows] if not one and rows else (dict(rows) if one and rows else (None if one else []))
    except Exception:
        return None if one else []


def is_process_running(name: str) -> bool:
    """Check if a process is running by name (Windows tasklist)."""
    try:
        r = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {name}'],
                          capture_output=True, text=True, timeout=5)
        return name.lower() in r.stdout.lower()
    except Exception:
        return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Routes — Static ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(str(Path(__file__).parent), 'index.html')


# ── Routes — Status ───────────────────────────────────────────────────────────

@app.route('/api/status')
def status():
    """Bot process status check."""
    claude_running = is_process_running('claude.exe')
    # Check VPS webhook via HTTP (quick timeout)
    ngrok_ok = False
    try:
        import urllib.request
        req = urllib.request.urlopen(
            'https://gladiator-doorbell-handwoven.ngrok-free.dev/health',
            timeout=4)
        ngrok_ok = req.status == 200
    except Exception:
        pass

    return jsonify({
        'tgtrade': claude_running,
        'hermes': is_process_running('hermes.exe'),
        'ngrok': ngrok_ok,
        'ts': utc_now(),
    })


# ── Routes — Prices ───────────────────────────────────────────────────────────

@app.route('/api/prices')
def prices():
    """Live prices: quotes.py (TradFi) + 3-level crypto chain:
       CCXT/Binance → direct Binance REST → HL allMids fallback.
    """
    result = run_script('quotes.py', ['--brief'], timeout=20)

    crypto: dict[str, float] = {}
    _SYMS        = ['BTC', 'ETH', 'SOL', 'HYPE', 'LINK', 'AVAX']
    _BINANCE_SYMS = ['BTC', 'ETH', 'SOL', 'LINK', 'AVAX']  # HYPE not listed on Binance

    # ── Level 1: CCXT / Binance (if installed) ───────────────────────────────
    if _CCXT_OK:
        try:
            binance = _ccxt.binance({'enableRateLimit': True})
            pairs   = [f'{s}/USDT' for s in _BINANCE_SYMS]
            tickers = binance.fetch_tickers(pairs)
            for sym in _BINANCE_SYMS:
                t = tickers.get(f'{sym}/USDT', {})
                price = t.get('last') or t.get('close')
                if price:
                    crypto[sym] = round(float(price), 2)
        except Exception:
            pass

    # ── Level 2: Direct Binance REST — no CCXT needed, standard TLS ─────────
    # api.binance.com uses a public CA cert (works with httpx default certifi)
    missing_binance = [s for s in _BINANCE_SYMS if s not in crypto]
    if missing_binance:
        try:
            syms_param = json.dumps([f'{s}USDT' for s in missing_binance])
            with httpx.Client(timeout=8) as bn_client:
                r = bn_client.get(
                    'https://api.binance.com/api/v3/ticker/price',
                    params={'symbols': syms_param}
                )
                r.raise_for_status()
                for item in r.json():
                    sym = item['symbol'].replace('USDT', '')
                    if sym in missing_binance:
                        crypto[sym] = round(float(item['price']), 2)
        except Exception:
            pass

    # ── Level 3: HL allMids — for HYPE + any remaining crypto gaps ─────────
    still_missing = [s for s in _SYMS if s not in crypto]
    if still_missing:
        try:
            with httpx.Client(verify=_SSL, timeout=8) as client:
                r = client.post('https://api.hyperliquid.xyz/info',
                                json={'type': 'allMids'})
                r.raise_for_status()
                mids = r.json()
                for sym in still_missing:
                    if sym in mids:
                        crypto[sym] = round(float(mids[sym]), 2)
        except Exception:
            pass

    # ── TradFi: HL xyz DEX — Gold/Silver/Oil/SP500 (CCXT doesn't cover this) ─
    # HL xyz is a custom DEX for real-world assets — direct REST only.
    # Symbols: GOLD, SILVER, BRENTOIL, CL (US oil), SP500, VIX, DXY, etc.
    tradfi: dict[str, float] = {}
    _TRADFI_MAP = {          # HL xyz API key → our ticker key  (keys have "xyz:" prefix in response!)
        'xyz:GOLD':     'GOLD',
        'xyz:SILVER':   'SILVER',
        'xyz:BRENTOIL': 'OIL',
        'xyz:SP500':    'SP500',
    }
    try:
        with httpx.Client(verify=_SSL, timeout=8) as client:
            r = client.post('https://api.hyperliquid.xyz/info',
                            json={'type': 'allMids', 'dex': 'xyz'})
            r.raise_for_status()
            mids = r.json()
            for hl_sym, our_key in _TRADFI_MAP.items():
                if hl_sym in mids:
                    tradfi[our_key] = round(float(mids[hl_sym]), 2)
    except Exception:
        pass

    return jsonify({
        'ok':     result['ok'],
        'output': result['output'],
        'error':  result.get('error', ''),
        'crypto': crypto,
        'tradfi': tradfi,
    })


# ── Routes — Positions ────────────────────────────────────────────────────────

@app.route('/api/positions')
def positions():
    """Fetch all positions from 4 venues."""
    result = run_script('fetch_positions.py', [], timeout=60)
    return jsonify({'ok': result['ok'], 'output': result['output'], 'error': result['error']})


# ── Routes — Fear & Greed ─────────────────────────────────────────────────────

@app.route('/api/fear_greed')
def fear_greed():
    """Fear & Greed from script + history from DB."""
    result = run_script('fear_greed.py', ['--days', '14'], timeout=20)
    history = db_query(
        "SELECT ts, value, label FROM fear_greed_history ORDER BY ts DESC LIMIT 14"
    )
    return jsonify({'ok': result['ok'], 'output': result['output'], 'history': history or []})


# ── Routes — Alerts ───────────────────────────────────────────────────────────

_VPS_API = 'http://92.112.181.37:5008'


def _fetch_vps(endpoint: str, timeout: float = 2.5) -> dict:
    """Try fetching JSON from VPS health API. Returns {} on any failure."""
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f'{_VPS_API}{endpoint}')
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


@app.route('/api/alerts')
def alerts():
    """Recent alerts: smart money, volume anomalies, listings, insider.
    Prefers VPS data (fresher) — falls back to local DB if VPS unreachable.
    """
    vps = _fetch_vps('/alerts')

    sm = vps.get('smart_money') or db_query(
        "SELECT ts, alert_type, coin, side, wallet, notional, details FROM sm_alerts "
        "ORDER BY ts DESC LIMIT 20"
    ) or []
    vol = db_query(
        "SELECT ts, symbol, exchange, volume_usd, ratio, direction FROM volume_anomalies "
        "ORDER BY ts DESC LIMIT 20"
    ) or []
    listings = vps.get('listings') or db_query(
        "SELECT ts, ticker AS symbol, exchange, url AS announce_url, title, ann_type "
        "FROM listing_announcements ORDER BY ts DESC LIMIT 20"
    ) or []
    insider = vps.get('insider') or db_query(
        "SELECT ts, scout, ticker, direction, confidence, reason FROM insider_signals "
        "ORDER BY ts DESC LIMIT 20"
    ) or []
    kozaki = vps.get('kozaki') or db_query(
        "SELECT ts, alert_type, wallet, label, coin, side, notional, details "
        "FROM kozaki_alerts ORDER BY ts DESC LIMIT 30"
    ) or []

    # TV webhook signals from local alerts.jsonl
    tv_alerts = []
    if ALERTS_FILE.exists():
        try:
            lines = ALERTS_FILE.read_text(encoding='utf-8').splitlines()
            for line in lines[-20:]:
                tv_alerts.append(json.loads(line))
        except Exception:
            pass

    return jsonify({'smart_money': sm, 'volume': vol, 'listings': listings,
                    'tv_alerts': tv_alerts, 'insider': insider, 'kozaki': kozaki})


# ── Routes — Reports ─────────────────────────────────────────────────────────

@app.route('/api/reports')
def reports():
    """Daily briefs history from DB."""
    rows = db_query(
        "SELECT id, ts, date, source, substr(content,1,300) as preview "
        "FROM daily_briefs ORDER BY ts DESC LIMIT 30"
    ) or []
    return jsonify({'reports': rows})


@app.route('/api/reports/<int:report_id>')
def report_detail(report_id: int):
    """Full content of a single report."""
    row = db_query("SELECT * FROM daily_briefs WHERE id=?", (report_id,), one=True)
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(row)


# ── Routes — OI ──────────────────────────────────────────────────────────────

@app.route('/api/oi')
def oi():
    """OI snapshot from script."""
    result = run_script('oi_tracker.py', ['--brief'], timeout=30)
    # Last few snapshots from DB
    history = db_query(
        "SELECT ts, coin, oi_total, mark_price, funding_rate "
        "FROM oi_snapshots WHERE ts > datetime('now','-24 hours') "
        "ORDER BY ts DESC LIMIT 50"
    ) or []
    return jsonify({'ok': result['ok'], 'output': result['output'], 'history': history})


# ── Routes — Edge Journal ────────────────────────────────────────────────────

@app.route('/api/edge')
def edge():
    """Edge observations from DB."""
    rows = db_query(
        "SELECT id, ts, assets, hypothesis, status, verdict, confidence, pnl_usd "
        "FROM edge_observations ORDER BY ts DESC LIMIT 20"
    ) or []
    return jsonify({'observations': rows})


# ── Routes — Run Script ──────────────────────────────────────────────────────

@app.route('/api/run', methods=['POST'])
def run():
    """Execute a script and return output."""
    data = request.get_json(force=True) or {}
    script = data.get('script', '').strip()
    args   = data.get('args', [])

    ALLOWED = {
        'fetch_positions.py', 'quotes.py', 'fear_greed.py', 'oi_tracker.py',
        'hl_whale_tracker.py', 'smart_money_tracker.py', 'listings_scanner.py',
        'volume_scanner.py', 'macro_news.py', 'econ_calendar.py', 'cot_tracker.py',
        'x_sentiment.py', 'polymarket.py', 'token_dashboard.py', 'blogwatcher.py',
        'edge_journal.py', 'hermes.py', 'ccxt_prices.py',
    }

    if not script or script not in ALLOWED:
        return jsonify({'ok': False, 'error': f'Script not allowed: {script}'}), 400

    if not isinstance(args, list):
        args = []

    # Per-script timeout overrides (slow API-heavy scripts)
    TIMEOUTS = {
        'x_sentiment.py':       300,   # Grok API + live X search = 2-3 min
        'blogwatcher.py':       240,
        'cot_tracker.py':       180,
        'hl_whale_tracker.py':  180,
        'smart_money_tracker.py': 180,
    }
    timeout = TIMEOUTS.get(script, 120)

    result = run_script(script, [str(a) for a in args], timeout=timeout)

    # Auto-save meaningful analysis results to history
    if result['ok'] and result.get('output') and script in SAVE_HISTORY:
        label_parts = [script.replace('.py', '')] + [str(a) for a in args[:2]]
        _save_history(script, ' '.join(label_parts), result['output'])

    return jsonify(result)


# ── Routes — Analysis History ─────────────────────────────────────────────────

@app.route('/api/history')
def history_list():
    """List recent saved analysis runs. Optional ?script= filter."""
    script_filter = request.args.get('script', '').strip()
    if script_filter:
        rows = db_query(
            "SELECT id, ts, script, label, substr(output,1,400) as preview "
            "FROM analysis_history WHERE script=? ORDER BY ts DESC LIMIT 100",
            (script_filter,)
        ) or []
    else:
        rows = db_query(
            "SELECT id, ts, script, label, substr(output,1,400) as preview "
            "FROM analysis_history ORDER BY ts DESC LIMIT 100"
        ) or []
    return jsonify({'history': rows})


@app.route('/api/history/<int:item_id>', methods=['GET', 'DELETE'])
def history_item(item_id: int):
    """Get full content or delete a history entry."""
    if request.method == 'DELETE':
        if not DB_PATH.exists():
            return jsonify({'ok': False}), 500
        try:
            con = sqlite3.connect(DB_PATH)
            con.execute('DELETE FROM analysis_history WHERE id=?', (item_id,))
            con.commit()
            con.close()
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)}), 500
    row = db_query('SELECT * FROM analysis_history WHERE id=?', (item_id,), one=True)
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(row)


# ── Routes — Claude Run (one-shot, --print mode) ─────────────────────────────

@app.route('/api/claude_run', methods=['POST'])
def claude_run():
    """Execute a prompt via `claude --print` (uses local Pro subscription, no API credits)."""
    data   = request.get_json(force=True) or {}
    prompt = data.get('prompt', '').strip()
    if not prompt:
        return jsonify({'ok': False, 'error': 'No prompt'}), 400

    claude = find_claude_exe()
    if not claude:
        return jsonify({
            'ok': False,
            'error': 'claude not found in PATH. Upewnij się że tgtrade był uruchamiany przynajmniej raz w tej sesji PS.'
        }), 500

    cmd = [claude, '--dangerously-skip-permissions', '--print', prompt]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=720,   # 12 min — multi-step workflows need time
            cwd=str(ROOT), encoding='utf-8', errors='replace',
            env={**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8',
                 'FORCE_COLOR': '0', 'NO_COLOR': '1'},
        )
        out = strip_ansi(r.stdout or r.stderr or '(brak wyjścia)')
        # Auto-save substantial claude outputs to history — label by prompt content
        # Note: save regardless of returncode — Claude CLI sometimes exits with code 1
        # even on successful runs (warnings, tool errors), but still produces full output
        if out and len(out) > 300:
            p_lower = prompt.lower()
            if any(k in p_lower for k in ['whale', 'snapshot', 'flip detector',
                                           'flip signal', 'conviction', 'liquidation',
                                           'rekt money', 'smart money', 'smart_money']):
                if 'flip' in p_lower and ('detector' in p_lower or 'signal' in p_lower):
                    sk, lp = 'whale_analysis', 'Flip Detector'
                elif 'conviction' in p_lower:
                    sk, lp = 'whale_analysis', 'Conviction Add'
                elif 'liquidation' in p_lower or 'rekt' in p_lower:
                    sk, lp = 'whale_analysis', 'Liquidation Hunt'
                else:
                    sk, lp = 'whale_analysis', 'Whale Snapshot'
            elif any(k in p_lower for k in ['daily brief', 'porann', 'morning',
                                             'fetch_positions', 'blogwatcher']):
                sk, lp = 'daily_brief', 'Daily Brief'
            else:
                sk, lp = 'daily_brief', 'Claude Response'
            _save_history(sk, lp + ' ' + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'), out)
        return jsonify({'ok': r.returncode == 0, 'output': out,
                        'error': strip_ansi(r.stderr) if r.returncode != 0 else ''})
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Timeout 12 min — workflow zbyt długi. Użyj /daily-alpha przez tgtrade/Telegram dla pełnego raportu.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ── Routes — Telegram Bridge ─────────────────────────────────────────────────

@app.route('/api/telegram_send', methods=['POST'])
def telegram_send():
    """Send a message to the user's Telegram chat via the bot (bot→user push)."""
    data = request.get_json(force=True) or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'No text provided'}), 400

    tg_env    = Path.home() / '.claude' / 'channels' / 'telegram' / '.env'
    tg_access = Path.home() / '.claude' / 'channels' / 'telegram' / 'access.json'
    bot_token = ''
    chat_id   = ''

    if tg_env.exists():
        for line in tg_env.read_text(encoding='utf-8').splitlines():
            if line.startswith('TELEGRAM_BOT_TOKEN='):
                bot_token = line.split('=', 1)[1].strip()

    if tg_access.exists():
        try:
            access = json.loads(tg_access.read_text(encoding='utf-8'))
            allow_from = access.get('allowFrom', [])
            if allow_from:
                chat_id = str(allow_from[0])
        except Exception:
            pass

    if not bot_token or not chat_id:
        return jsonify({'ok': False, 'error': 'Telegram not configured'}), 500

    import urllib.request as urllib_req
    url     = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    payload = json.dumps({'chat_id': chat_id, 'text': text,
                          'parse_mode': 'HTML'}).encode('utf-8')
    req = urllib_req.Request(url, data=payload,
                             headers={'Content-Type': 'application/json'})
    try:
        urllib_req.urlopen(req, timeout=10)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ── Routes — Positions JSON ───────────────────────────────────────────────────

@app.route('/api/positions_json')
def positions_json_route():
    """Fetch positions as structured JSON using fetch_positions.py --json."""
    result = run_script('fetch_positions.py', ['--json'], timeout=60)
    if result['ok'] and result['output']:
        try:
            positions = json.loads(result['output'])
            # Also try reading cached positions.json if script failed
            return jsonify({'ok': True, 'positions': positions})
        except Exception:
            pass
    # Fallback: try reading positions.json directly
    pos_file = ROOT / 'positions.json'
    if pos_file.exists():
        try:
            positions = json.loads(pos_file.read_text(encoding='utf-8'))
            return jsonify({'ok': True, 'positions': positions, 'cached': True})
        except Exception:
            pass
    return jsonify({'ok': False, 'positions': [],
                    'error': result.get('error', 'Parse error'),
                    'raw': result.get('output', '')})


# ── Routes — Extended Health ──────────────────────────────────────────────────

@app.route('/api/health_extended')
def health_extended():
    """Daemon health via DB recency — shows when each daemon last wrote data."""
    from datetime import datetime, timezone
    import time as _time

    def check_table(table: str, ts_col: str = 'ts', window_h: int = 4) -> dict:
        rows = db_query(f'SELECT MAX({ts_col}) as last FROM {table}')
        last_val = rows[0]['last'] if rows and rows[0] else None
        if not last_val:
            return {'active': False, 'last': None, 'ago': 'Brak danych w DB'}
        try:
            if isinstance(last_val, (int, float)):
                dt = datetime.fromtimestamp(float(last_val), timezone.utc)
            else:
                # Normalize timestamp: handle "2026-06-01 08:36 UTC" and "Z" suffixes
                ts_str = str(last_val).replace('Z', '+00:00').replace(' UTC', '+00:00')
                # Add missing seconds if needed: "08:36+00:00" → "08:36:00+00:00"
                ts_str = re.sub(r'(\d{2}:\d{2})([+-]\d{2}:\d{2})$', r'\1:00\2', ts_str)
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            ago_s = (datetime.now(timezone.utc) - dt).total_seconds()
            if   ago_s < 60:    ago = f'{int(ago_s)}s temu'
            elif ago_s < 3600:  ago = f'{int(ago_s/60)}m temu'
            elif ago_s < 86400: ago = f'{ago_s/3600:.1f}h temu'
            else:               ago = f'{ago_s/86400:.1f}d temu'
            return {'active': ago_s < window_h * 3600,
                    'last': str(last_val)[:16], 'ago': ago}
        except Exception:
            return {'active': False, 'last': str(last_val), 'ago': '?'}

    # Prefer VPS data (fresher) over local Windows DB
    vps = _fetch_vps('/health')
    return jsonify({
        'smart_money': vps.get('smart_money') or check_table('sm_snapshots',           window_h=25),
        'volume':      vps.get('volume')      or check_table('volume_anomalies',       window_h=168),
        'listings':    vps.get('listings')    or check_table('listing_announcements',  window_h=168),
        'insider':     vps.get('insider')     or check_table('insider_signals',        window_h=168),
        'kozaki':      vps.get('kozaki')      or check_table('kozaki_snapshots',       window_h=25),
        'ts': utc_now(),
    })


# ── Routes — Strategies ──────────────────────────────────────────────────────

@app.route('/api/strategies')
def strategies():
    """Strategy registry + recent TV webhook signals."""
    tv_alerts = []
    if ALERTS_FILE.exists():
        try:
            lines = ALERTS_FILE.read_text(encoding='utf-8').splitlines()
            for line in lines[-50:]:
                tv_alerts.append(json.loads(line))
            tv_alerts.reverse()
        except Exception:
            pass

    strategies_list = [
        {
            'name': 'ZL-Volatility v1',
            'key': 'zl-volatility-v1',
            'venue': 'Alpaca',
            'mode': 'paper',
            'symbols': 'US Stocks',
            'timeframe': '15m',
            'status': 'active',
            'webhook_url': 'https://gladiator-doorbell-handwoven.ngrok-free.dev/tv',
        }
    ]
    return jsonify({'strategies': strategies_list, 'tv_alerts': tv_alerts})


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=5007)
    args = p.parse_args()
    print(f'\n  === ALPHA DESK === port {args.port} ===')
    print(f'  http://localhost:{args.port}')
    print(f'  ====================================\n')
    app.run(host='0.0.0.0', port=args.port, debug=False)
