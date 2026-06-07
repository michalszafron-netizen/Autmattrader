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
    """Create all required tables if they don't exist."""
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
        con.execute('''CREATE TABLE IF NOT EXISTS user_watchlist (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            address    TEXT    NOT NULL UNIQUE,
            label      TEXT,
            comment    TEXT,
            source     TEXT,
            added_at   TEXT    DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%SZ\',\'now\')),
            tags       TEXT    DEFAULT \'[]\'
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_watchlist_addr ON user_watchlist(address)')
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

def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


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

    vps_api_ok = is_port_open('92.112.181.37', 5008, timeout=2.0)

    return jsonify({
        'tgtrade':  claude_running,
        'hermes':   is_process_running('hermes.exe'),
        'ngrok':    ngrok_ok,
        'tvhook':   is_port_open('127.0.0.1', 5005),
        'vps_api':  vps_api_ok,
        'ts':       utc_now(),
    })


@app.route('/api/webhook/start', methods=['POST'])
def webhook_start():
    """Start tv_webhook.py in a new console window (Windows only)."""
    if is_port_open('127.0.0.1', 5005):
        return jsonify({'ok': True, 'msg': 'tv_webhook.py already running on port 5005'})
    script = SCRIPTS / 'tv_webhook.py'
    if not script.exists():
        return jsonify({'ok': False, 'error': 'tv_webhook.py not found'}), 404
    try:
        import subprocess as _sp
        _sp.Popen(
            [PY, str(script)],
            cwd=str(ROOT),
            creationflags=_sp.CREATE_NEW_CONSOLE,  # opens visible console window
        )
        return jsonify({'ok': True, 'msg': 'tv_webhook.py uruchomiony — okno konsoli powinno się otworzyć'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


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
        "SELECT ts, value, classification AS label FROM fear_greed_history ORDER BY ts DESC LIMIT 14"
    )
    return jsonify({'ok': result['ok'], 'output': result['output'], 'history': history or []})


# ── Routes — Econ Calendar ───────────────────────────────────────────────────

@app.route('/api/econ')
def econ():
    """Economic calendar for today — structured JSON, all events (past + future)."""
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS))
    try:
        from datetime import datetime, timezone as _tz
        today = datetime.now(_tz.utc).strftime('%Y-%m-%d')

        # Import calendar helpers from econ_calendar.py
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'econ_calendar', str(SCRIPTS / 'econ_calendar.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        raw = mod.fetch_calendar(today, today)

        # Tylko kraje mające realny wpływ na instrumenty finansowe
        important_countries = {'US', 'EU', 'DE', 'FR', 'GB'}
        now_ts = datetime.now(_tz.utc).timestamp()

        events = []
        for e in raw:
            country = e.get('country', '')
            # Pokazuj tylko wybrane kraje; LUB globalnie krytyczne eventy (np. IMF, G7)
            if country not in important_countries:
                continue
            label, color, style = mod.get_importance(e)
            tip = mod.get_event_tip(e)

            try:
                dt = datetime.fromisoformat(e['time'].replace('Z', '+00:00'))
                ts = dt.timestamp()
                time_utc  = dt.strftime('%d.%m  %H:%M UTC')
                date_only = dt.strftime('%Y-%m-%d')
                # Czas polski: CEST (UTC+2) od ostatniej niedzieli marca do ostatniej niedzieli października
                from datetime import timedelta as _td
                _month = dt.month
                _pl_offset = 2 if 3 < _month < 10 or (_month == 3 and dt.day >= 25) or (_month == 10 and dt.day < 25) else 1
                dt_pl    = dt + _td(hours=_pl_offset)
                time_pl  = dt_pl.strftime('%H:%M')   # tylko godzina — data ta sama co UTC
            except Exception:
                ts = 0
                time_utc  = e.get('time', '')
                date_only = today
                time_pl   = ''

            actual  = e.get('actual')
            est     = e.get('estimate')
            prev    = e.get('previous') or e.get('prev')
            past    = bool(actual is not None and str(actual).strip() not in ('', 'null', 'None'))

            # Rozszerzone opisy wydarzeń
            EXTENDED_TIPS = {
                'nonfarm':        'Liczba nowych miejsc pracy poza rolnictwem w USA. Najważniejszy miesięczny raport rynku pracy. >200k = dobra gospodarka = Fed nie tnie stóp = presja na BTC/Złoto. <100k = słabość = Fed może poluzować = wzrostowe dla BTC.',
                'cpi':            'Wskaźnik cen konsumpcyjnych — główna miara inflacji w USA. Wyższy od oczekiwań = Fed ostrzejszy = dolar silniejszy = presja na BTC i akcje. Niższy = gołębi Fed = BTC i Złoto zyskują.',
                'pce':            'Ulubiony wskaźnik inflacji Fed (Personal Consumption Expenditures). Podobny efekt jak CPI ale Fed przywiązuje do niego większą wagę przy decyzjach o stopach.',
                'fomc':           'Posiedzenie Fed — decyzja o poziomie stóp procentowych w USA. Najważniejszy event miesiąca. Podwyżka = droższy kredyt = presja na ryzykowne aktywa. Obniżka = taniość pieniądza = wzrostowe dla BTC, akcji, Złota.',
                'fed ':           'Wypowiedź przedstawiciela Fed. Rynek szuka sygnałów: "jastrzębi" (stopy w górę) vs "gołębi" (stopy w dół). Powell mówi = rynki drżą.',
                'powell':         'Przemówienie Jerome Powella — przewodniczącego Fed. Każde słowo porusza rynki. Jastrzębi ton = dolary mocniejszy = BTC w dół. Gołębi ton = odwrotnie.',
                'gdp':            'PKB USA — tempo wzrostu całej gospodarki. Wyższy od oczekiwań = silna gospodarka = Fed nie śpieszy się z cięciami = słabość BTC. Niższy = ryzyko recesji = Fed tnie = potencjalnie wzrostowe.',
                'jobless':        'Tygodniowe wnioski o zasiłek dla bezrobotnych. Więcej wniosków = rynek pracy się ochładza = Fed może ciąć stopy. Mniej = zatrudnienie silne = Fed bez pośpiechu.',
                'pmi':            'Purchasing Managers Index — "temperatura" gospodarki mierzona przez menadżerów zakupów. >50 = ekspansja, <50 = kontrakcja. Silne PMI = dobra gospodarka = Fed nie tnie.',
                'ism ':           'ISM Manufacturing/Services — podobny do PMI, szeroko obserwowany przez rynek. Kluczowy dla oceny kondycji przemysłu i usług USA.',
                'retail sales':   'Sprzedaż detaliczna = wydatki konsumentów w USA. Silna sprzedaż = dobra gospodarka = inflacja może trwać = Fed ostrzejszy. Słaba = konsumenci oszczędzają = wolniejszy wzrost.',
                'ppi':            'Inflacja u producentów. Zwykle wyprzedza CPI o 1-2 miesiące. Wzrost PPI = producenci przeniosą koszty na konsumentów = CPI pójdzie w górę.',
                'building':       'Liczba nowych pozwoleń budowlanych. Wskaźnik siły rynku nieruchomości i ogólnej aktywności gospodarczej.',
                'housing':        'Dane z rynku nieruchomości (sprzedaż, ceny). Ważny dla oceny kondycji gospodarki i popytu kredytowego.',
                'durable goods':  'Zamówienia na dobra trwałe (maszyny, samoloty, sprzęt). Miara inwestycji przemysłowych — silne zamówienia = firmy inwestują = dobra kondycja.',
                'consumer confidence': 'Indeks zaufania konsumentów. Wysokie zaufanie = konsumenci skłonni wydawać = inflacja może trwać. Niskie = ostrożność wydatków = ochłodzenie gospodarcze.',
                'trade balance':  'Bilans handlowy USA (eksport minus import). Duży deficyt = więcej dolarów wypływa za granicę. Wpływ na kursy walutowe i DXY.',
            }
            extended_tip = tip
            name_lower = (e.get('event') or '').lower()
            for kw, ext in EXTENDED_TIPS.items():
                if kw.strip() in name_lower:
                    extended_tip = ext
                    break

            events.append({
                'time_utc':   time_utc,
                'time_pl':    time_pl,
                'date':       date_only,
                'ts':         ts,
                'name':       e.get('event', ''),
                'country':    country,
                'importance': label,
                'color':      color,
                'tip':        extended_tip,
                'actual':     str(actual) if actual is not None else None,
                'estimate':   str(est)    if est    is not None else None,
                'prev':       str(prev)   if prev   is not None else None,
                'past':       past,
            })

        events.sort(key=lambda x: x['ts'])
        return jsonify({'ok': True, 'events': events, 'date': today})
    except Exception as ex:
        return jsonify({'ok': False, 'events': [], 'error': str(ex)})


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


@app.route('/api/watchlist', methods=['GET'])
def watchlist_get():
    """Return all user-tracked wallets."""
    rows = db_query(
        "SELECT id, address, label, comment, source, added_at, tags FROM user_watchlist ORDER BY added_at DESC"
    ) or []
    return jsonify(rows)


@app.route('/api/watchlist', methods=['POST'])
def watchlist_add():
    """Add or update a wallet in the personal watchlist."""
    data = request.get_json(force=True, silent=True) or {}
    address = (data.get('address') or '').strip().lower()
    if not address:
        return jsonify({'ok': False, 'error': 'address required'}), 400
    label   = (data.get('label')   or '').strip()[:120]
    comment = (data.get('comment') or '').strip()[:1000]
    source  = (data.get('source')  or 'manual').strip()[:40]
    tags    = json.dumps(data.get('tags') or [])
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            """INSERT INTO user_watchlist (address, label, comment, source, tags)
               VALUES (?,?,?,?,?)
               ON CONFLICT(address) DO UPDATE SET
                 label=excluded.label, comment=excluded.comment,
                 source=excluded.source, tags=excluded.tags""",
            (address, label, comment, source, tags),
        )
        con.commit()
        con.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/watchlist/full')
def watchlist_full():
    """Watchlista + aktualne pozycje z kozaki_snapshots dla każdego adresu."""
    entries = db_query(
        "SELECT id, address, label, comment, source, added_at, tags FROM user_watchlist ORDER BY added_at DESC"
    ) or []
    if not entries:
        return jsonify([])

    # Pobierz najnowsze pozycje dla adresów z watchlisty
    addrs = [str(e.get('address', '')).lower() for e in entries if e.get('address')]
    if addrs:
        ph = ','.join('?' * len(addrs))
        positions = db_query(
            f"""SELECT LOWER(ks.wallet) AS wallet, ks.coin, ks.side, ks.notional, ks.entry, ks.lev, ks.upnl,
                       COALESCE(ka.label,'') AS kz_label
                FROM kozaki_snapshots ks
                LEFT JOIN (SELECT wallet, MAX(label) AS label FROM kozaki_alerts GROUP BY wallet) ka
                          ON LOWER(ka.wallet) = LOWER(ks.wallet)
                WHERE ks.ts = (SELECT MAX(ts) FROM kozaki_snapshots)
                  AND LOWER(ks.wallet) IN ({ph})
                ORDER BY ks.notional DESC""",
            tuple(addrs)
        ) or []
    else:
        positions = []

    pos_by_wallet: dict = {}
    for p in positions:
        w = (p.get('wallet') or '').lower()
        pos_by_wallet.setdefault(w, []).append(dict(p))

    result = []
    for e in entries:
        row = dict(e)
        addr = (row.get('address') or '').lower()
        row['positions'] = pos_by_wallet.get(addr, [])
        try:
            row['tags'] = json.loads(row.get('tags') or '[]')
        except Exception:
            row['tags'] = []
        result.append(row)
    return jsonify(result)


@app.route('/api/watchlist/<path:address>', methods=['DELETE'])
def watchlist_delete(address: str):
    """Remove a wallet from the personal watchlist."""
    address = address.strip().lower()
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM user_watchlist WHERE address = ?", (address,))
        con.commit()
        con.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/alerts')
def alerts():
    """Recent alerts: smart money, volume anomalies, listings, insider.
    Prefers VPS data (fresher) — falls back to local DB if VPS unreachable.
    """
    vps = _fetch_vps('/alerts')

    sm = vps.get('smart_money') or db_query(
        "SELECT ts, alert_type, coin, side, wallet, notional, details FROM sm_alerts "
        "ORDER BY ts DESC LIMIT 300"
    ) or []
    vol = db_query(
        "SELECT ts, symbol, exchange, volume_usd, ratio, direction FROM volume_anomalies "
        "ORDER BY ts DESC LIMIT 30"
    ) or []
    listings = vps.get('listings') or db_query(
        "SELECT ts, ticker AS symbol, exchange, url AS announce_url, title, ann_type "
        "FROM listing_announcements ORDER BY ts DESC LIMIT 30"
    ) or []
    insider = vps.get('insider') or db_query(
        "SELECT ts, scout, ticker, direction, confidence, reason FROM insider_signals "
        "ORDER BY ts DESC LIMIT 30"
    ) or []
    kozaki = vps.get('kozaki') or db_query(
        "SELECT ts, alert_type, wallet, label, coin, side, notional, details "
        "FROM kozaki_alerts ORDER BY ts DESC LIMIT 50"
    ) or []

    # Kozaki snapshot — top aktywne pozycje z ostatniego skanu (jak heartbeat w Telegramie)
    kozaki_snapshot = vps.get('kozaki_snapshot') or db_query(
        """SELECT ks.wallet, ks.coin, ks.side, ks.notional, ks.entry, ks.lev, ks.upnl,
                  ka.label
           FROM kozaki_snapshots ks
           LEFT JOIN (
               SELECT wallet, MAX(label) AS label FROM kozaki_alerts GROUP BY wallet
           ) ka ON ks.wallet = ka.wallet
           WHERE ks.ts = (SELECT MAX(ts) FROM kozaki_snapshots)
           ORDER BY ks.notional DESC LIMIT 20"""
    ) or []

    # TV webhook signals from local alerts.jsonl
    tv_alerts = []
    if ALERTS_FILE.exists():
        try:
            lines = ALERTS_FILE.read_text(encoding='utf-8').splitlines()
            for line in lines[-30:]:
                tv_alerts.append(json.loads(line))
        except Exception:
            pass

    # SM Snapshot — aktualne pozycje ze OSTATNIEGO skanu (nie zdarzenia, ale stan bieżący)
    # Grupowane po coin+side, sumy notional i liczba portfeli → dane dla Whale Thermometru
    sm_snapshot = vps.get('sm_snapshot') or db_query(
        """SELECT coin, side,
                  SUM(notional)        AS notional,
                  COUNT(DISTINCT wallet) AS wallet_count
           FROM sm_snapshots
           WHERE ts = (SELECT MAX(ts) FROM sm_snapshots)
           GROUP BY coin, side
           ORDER BY notional DESC"""
    ) or []

    return jsonify({'smart_money': sm, 'volume': vol, 'listings': listings,
                    'tv_alerts': tv_alerts, 'insider': insider,
                    'kozaki': kozaki, 'kozaki_snapshot': kozaki_snapshot,
                    'sm_snapshot': sm_snapshot})


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
        },
        {
            'name': 'IMBUS v1',
            'key': 'imbus-v1',
            'venue': 'Extended',
            'mode': 'paper',
            'symbols': 'Crypto Perp',
            'timeframe': '15m',
            'status': 'active',
            'webhook_url': 'https://gladiator-doorbell-handwoven.ngrok-free.dev/tv',
        },
    ]
    return jsonify({'strategies': strategies_list, 'tv_alerts': tv_alerts})


@app.route('/api/strategies/signals/clear', methods=['DELETE'])
def clear_strategy_signals():
    """Permanently delete entries from alerts.jsonl.
    ?strategy=zl-volatility-v1  → removes that strategy + legacy (no-strategy) entries.
    ?symbol=RGTI                → combined with strategy, or alone, to filter by symbol.
    No param                    → clears the whole file.
    """
    strategy = request.args.get('strategy', '').strip().lower()
    symbol   = request.args.get('symbol',   '').strip().upper()
    if not ALERTS_FILE.exists():
        return jsonify({'ok': True, 'cleared': 0})
    try:
        lines = [l for l in ALERTS_FILE.read_text(encoding='utf-8').splitlines() if l.strip()]
        if strategy or symbol:
            kept, cleared = [], 0
            for line in lines:
                try:
                    d          = json.loads(line)
                    sig_strat  = d.get('strategy', '').lower()
                    sig_symbol = d.get('symbol',   '').upper()
                    # Match strategy: explicit match OR legacy entry (no strategy field)
                    strat_ok = not strategy or sig_strat == strategy or not sig_strat
                    # Match symbol: exact match or no filter
                    sym_ok   = not symbol or sig_symbol == symbol
                    if strat_ok and sym_ok:
                        cleared += 1
                    else:
                        kept.append(line)
                except Exception:
                    kept.append(line)  # keep unparseable lines
        else:
            kept, cleared = [], len(lines)
        ALERTS_FILE.write_text('\n'.join(kept) + ('\n' if kept else ''), encoding='utf-8')
        return jsonify({'ok': True, 'cleared': cleared})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/research/run', methods=['POST'])
def research_run():
    """Run token_research.py or stock_research.py; return stdout + new .md file content."""
    data   = request.get_json(force=True) or {}
    script = data.get('script', '').strip()
    args   = [str(a) for a in (data.get('args') or [])]

    if script not in {'token_research.py', 'stock_research.py'}:
        return jsonify({'ok': False, 'error': 'Not allowed'}), 400

    research_dir = ROOT / 'reports' / 'research'
    research_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot existing files before run
    before = {}
    for f in research_dir.rglob('*.md'):
        try:
            before[str(f)] = f.stat().st_mtime
        except Exception:
            pass

    result = run_script(script, args, timeout=360)

    # Find newly created or updated .md files
    markdown = ''
    new_file = ''
    try:
        after = {}
        for f in research_dir.rglob('*.md'):
            try:
                after[str(f)] = f.stat().st_mtime
            except Exception:
                pass
        new_files = [f for f in after if f not in before or after[f] > before.get(f, 0)]
        if new_files:
            newest = max(new_files, key=lambda p: after[p])
            markdown = Path(newest).read_text(encoding='utf-8', errors='replace')
            new_file = Path(newest).name
    except Exception:
        pass

    return jsonify({
        'ok':       result['ok'],
        'output':   result.get('output', ''),
        'error':    result.get('error', ''),
        'markdown': markdown,
        'file':     new_file,
    })


@app.route('/api/research/claude', methods=['POST'])
def research_claude():
    """Deep token research via Claude — the SAME engine as TG Trade.

    Runs `claude --print` in the project dir so Claude has the full CLAUDE.md
    rules + web search + MCP tools (CoinGecko 404s on new tokens; Claude works
    around it by reading many sources). Detects the newly saved .md in
    reports/research/, writes a DB row for the history verdict badge, and
    returns the markdown. Unifies dashboard research with TG Trade quality.
    """
    data  = request.get_json(force=True) or {}
    query = (data.get('query') or '').strip()
    chain = (data.get('chain') or 'eth').strip()
    no_x  = bool(data.get('no_x'))
    if not query:
        return jsonify({'ok': False, 'error': 'Brak zapytania'}), 400

    claude = find_claude_exe()
    if not claude:
        return jsonify({'ok': False, 'error': 'claude not found w PATH — uruchom dashboard z sesji PS gdzie tgtrade działał choć raz.'}), 500

    today  = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    x_note = 'Pomiń sentyment z X/Twitter (oszczędzaj kredyty).' if no_x else 'Dołącz sentyment z X jeśli się da.'
    prompt = (
        f"Zrób GŁĘBOKI research tokena: {query} (sieć: {chain}). "
        f"Postępuj zgodnie z zasadami z CLAUDE.md (język edukacyjny, kontrakty, strefy UTC+CEST). "
        f"Zbierz dane z wielu źródeł (CoinGecko, CoinMarketCap, DexScreener, Etherscan/BscScan, "
        f"strona projektu, on-chain). Pokryj: kontrakty na wszystkich sieciach, dane rynkowe, "
        f"podaż/tokenomikę, zespół i inwestorów, on-chain/holderów, ryzyka, werdykt. {x_note} "
        f"Stosuj się do sekcji 'Research tokenów — auto-zapis' z CLAUDE.md: ZAPISZ plik do "
        f"reports/research/<TICKER>_{chain}_<ca[:10]>_{today}.md ORAZ wpis do DB, "
        f"a na końcu wyświetl pełny raport w odpowiedzi."
    )

    research_dir = ROOT / 'reports' / 'research'
    research_dir.mkdir(parents=True, exist_ok=True)
    before = {}
    for f in research_dir.rglob('*.md'):
        try:
            before[str(f)] = f.stat().st_mtime
        except Exception:
            pass

    cmd = [claude, '--dangerously-skip-permissions', '--print', prompt]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=720,
            cwd=str(ROOT), encoding='utf-8', errors='replace',
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8',
                 'FORCE_COLOR': '0', 'NO_COLOR': '1'},
        )
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Timeout 12 min — dla bardzo dużych raportów użyj TG Trade.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

    out = strip_ansi(r.stdout or r.stderr or '')

    # Detect the newly written / updated report
    markdown, new_file = '', ''
    try:
        after = {}
        for f in research_dir.rglob('*.md'):
            try:
                after[str(f)] = f.stat().st_mtime
            except Exception:
                pass
        new_files = [f for f in after if f not in before or after[f] > before.get(f, 0)]
        if new_files:
            newest   = max(new_files, key=lambda p: after[p])
            markdown = Path(newest).read_text(encoding='utf-8', errors='replace')
            new_file = Path(newest).name
    except Exception:
        pass

    # Write a DB row so the history list shows the verdict badge + name
    if markdown:
        try:
            sys.path.insert(0, str(ROOT))
            from scripts.db import DB
            parts  = Path(new_file).stem.split('_')
            ticker = parts[0] if parts else query.upper()
            ch     = parts[1] if len(parts) > 1 else chain
            mca    = re.search(r'0x[0-9a-fA-F]{40}', markdown)
            verm   = re.search(r'Werdykt:\**\s*`?\s*([^\s`<]+)', markdown)
            namem  = re.search(r'#\s*RESEARCH:\s*(.+?)\s*[\(—\-]', markdown)
            DB().save_token_research(ticker, mca.group(0) if mca else '', {
                'chain':   ch,
                'name':    namem.group(1).strip() if namem else '',
                'verdict': verm.group(1).strip() if verm else '',
                'summary': markdown[:500],
            })
        except Exception:
            pass

    return jsonify({
        'ok':       bool(markdown) or r.returncode == 0,
        'output':   out,
        'error':    strip_ansi(r.stderr) if (r.returncode != 0 and not markdown) else '',
        'markdown': markdown,
        'file':     new_file,
    })


@app.route('/api/research/history')
def research_history():
    """List all token + stock research reports from the filesystem."""
    research_dir = ROOT / 'reports' / 'research'
    tokens, stocks = [], []

    if research_dir.exists():
        # Token reports: *.md directly in research_dir
        for f in sorted(research_dir.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True)[:60]:
            parts = f.stem.split('_')
            tokens.append({
                'filename': f.name,
                'ticker':   parts[0] if parts else '?',
                'chain':    parts[1] if len(parts) > 1 else '?',
                'date':     parts[-1] if parts else '?',
                'mtime':    f.stat().st_mtime,
            })
        # Stock reports: reports/research/stocks/*.md
        stocks_dir = research_dir / 'stocks'
        if stocks_dir.exists():
            for f in sorted(stocks_dir.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True)[:60]:
                parts = f.stem.split('_')
                stocks.append({
                    'filename': f.name,
                    'ticker':   parts[0] if parts else '?',
                    'exch':     parts[1] if len(parts) > 1 else '',
                    'date':     parts[-1] if parts else '?',
                    'mtime':    f.stat().st_mtime,
                })

    # Enrich tokens with DB verdict/name
    db_map = {}
    try:
        rows = db_query('SELECT ticker, chain, verdict, name FROM token_research ORDER BY ts DESC') or []
        for r in rows:
            k = f"{r['ticker']}_{r['chain']}"
            if k not in db_map:
                db_map[k] = r
    except Exception:
        pass
    for t in tokens:
        meta = db_map.get(f"{t['ticker']}_{t['chain']}", {})
        t['verdict'] = meta.get('verdict', '')
        t['name']    = meta.get('name', '')

    return jsonify({'tokens': tokens, 'stocks': stocks})


@app.route('/api/research/file')
def research_file():
    """Read a research .md file. ?f=filename&dir=stocks|''"""
    fname  = request.args.get('f', '').strip()
    subdir = request.args.get('dir', '').strip()

    if not fname or '..' in fname or fname.startswith('/') or '\\' in fname:
        return jsonify({'error': 'Bad filename'}), 400
    if not fname.endswith('.md'):
        return jsonify({'error': 'Only .md files'}), 400

    base = ROOT / 'reports' / 'research'
    filepath = (base / 'stocks' / fname) if subdir == 'stocks' else (base / fname)
    if not filepath.exists():
        return jsonify({'error': 'Not found'}), 404

    content = filepath.read_text(encoding='utf-8', errors='replace')
    return jsonify({'content': content, 'filename': fname})


@app.route('/api/costs')
def costs():
    """API cost tracking: totals + daily breakdown + recent calls."""
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.cost_tracker import get_totals, get_summary, get_recent
        days = int(request.args.get('days', 30))
        limit = int(request.args.get('limit', 60))
        return jsonify({
            'totals':  get_totals(),
            'summary': get_summary(days=days),
            'recent':  get_recent(limit=limit),
        })
    except Exception as e:
        return jsonify({'error': str(e), 'totals': {}, 'summary': [], 'recent': []})


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
