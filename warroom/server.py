"""War Room — Trading Command Center Backend
Flask REST API on port 5009
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / '.venv' / 'Scripts' / 'python.exe')
SCRIPTS = ROOT / 'scripts'
DATA = ROOT / 'data'
DB_PATH = DATA / 'trading.db'
POSITIONS_JSON = ROOT / 'positions.json'
ALERTS_FILE = ROOT / 'alerts.jsonl'

load_dotenv(ROOT / '.env')

app = Flask(__name__, static_folder=str(Path(__file__).parent), static_url_path='')

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text or '')

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def run_script(script: str, args: list[str] | None = None, timeout: int = 60) -> dict:
    args = args or []
    cmd = [PY, str(SCRIPTS / script)] + args
    _env = {
        **os.environ,
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONUTF8': '1',
        'FORCE_COLOR': '0',
        'NO_COLOR': '1',
        'TERM': 'dumb',
    }
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=str(ROOT), env=_env)
        raw = r.stdout or r.stderr or b''
        out = strip_ansi(raw.decode('utf-8', errors='replace'))
        err = strip_ansi(r.stderr.decode('utf-8', errors='replace')) if r.returncode != 0 else ''
        return {'ok': r.returncode == 0, 'output': out, 'error': err}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'output': '', 'error': f'Timeout after {timeout}s'}
    except Exception as e:
        return {'ok': False, 'output': '', 'error': str(e)}


# ── Parsers ─────────────────────────────────────────────────────────────

def parse_fear_greed(text: str) -> dict:
    """Fear & Greed: 12/100 — Extreme Fear | Trend 5d: 11→12→12→12→12 → (stabilny)"""
    m = re.search(r'(\d+)/100\s*[—\-]\s*(.+?)(?:\s*\||$)', text)
    trend = re.findall(r'(\d+)→', text)
    return {
        'score': int(m.group(1)) if m else 50,
        'label': m.group(2).strip() if m else 'Unknown',
        'trend_5d': [int(x) for x in trend] if trend else [],
        'trend_text': (text.split('→')[ -1] if '→' in text else '').strip(' ()'),
    }

def parse_oi(text: str) -> list[dict]:
    """OI aggregate: BTC: $9.90B | ETH: $5.25B | SOL: $1.20B"""
    results = []
    for m in re.finditer(r'(\w+):\s*\$?([\d.]+)([BMK])', text):
        val = float(m.group(2))
        unit = m.group(3)
        if unit == 'B':
            val = val
        elif unit == 'M':
            val = val / 1000.0
        elif unit == 'K':
            val = val / 1_000_000.0
        results.append({'symbol': m.group(1), 'oi_b': val})
    return results

def parse_quotes(text: str) -> dict:
    """Parse quotes output into structured data"""
    data = {}
    for m in re.finditer(r'(\w+(?:\s+\w+)*):\s*\$?([\d,.]+)', text):
        key = m.group(1).strip()
        val = float(m.group(2).replace(',', ''))
        data[key] = val
    return data

def parse_token_dashboard(text: str) -> list[dict]:
    """Parse token_dashboard.py output per token"""
    tokens = []
    blocks = text.split('╭')
    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split('\n')
        symbol_m = re.match(r'.*?(\w{2,10})\s+\$?([\d,.]+)', lines[0])
        if not symbol_m:
            continue
        symbol = symbol_m.group(1)
        price = float(symbol_m.group(2).replace(',', ''))
        entry = {'symbol': symbol, 'price': price}

        for line in lines:
            if '1D:' in line:
                chg = re.findall(r'([+-]?[\d.]+)%', line)
                if len(chg) >= 3:
                    entry['change_1d'] = float(chg[0])
                    entry['change_7d'] = float(chg[1])
                    entry['change_30d'] = float(chg[2])
            if 'Smart Money:' in line:
                sm = re.findall(r'(\d+)%', line)
                if len(sm) >= 2:
                    entry['sm_long_pct'] = int(sm[0])
                    entry['sm_short_pct'] = int(sm[1])
            if 'OI:' in line:
                oi_m = re.search(r'OI:\s*\$?([\d.]+)([BMK])', line)
                if oi_m:
                    entry['oi'] = float(oi_m.group(1))
            if 'Funding:' in line:
                f_m = re.search(r'([+-]?[\d.]+%)', line)
                if f_m:
                    entry['funding'] = f_m.group(1)
            if 'Sentiment:' in line:
                s_m = re.search(r'(\d+)/100', line)
                if s_m:
                    entry['sentiment'] = int(s_m.group(1))
            if 'Composite:' in line:
                c_m = re.search(r'([\d.]+)/10', line)
                if c_m:
                    entry['composite'] = float(c_m.group(1))
                direction_m = re.search(r'[—\-]\s*(.+)$', line)
                if direction_m:
                    entry['composite_label'] = direction_m.group(1).strip()

        tokens.append(entry)
    return tokens

def parse_whales(text: str) -> dict:
    """Parse whale tracker output — extract wallet counts for richer data"""
    result = {'positions': [], 'bias_summary': {}}
    lines = text.split('\n')
    in_table = False
    for line in lines:
        if 'Coin' in line and 'Long $' in line:
            in_table = True
            continue
        if in_table and ('└' in line or '┕' in line):
            in_table = False
            continue
        if in_table:
            cells = re.findall(r'[│┃]\s*([^│┃]+?)\s*(?=[│┃]|$)', '│' + line)
            # Filter out continuation lines (cells[0] seems empty or coin is on prev line)
            if len(cells) >= 7 and cells[0].strip():
                coin = cells[0].strip()
                long_s = cells[1].strip()
                short_s = cells[2].strip()
                net_s = cells[3].strip()
                bias = cells[6].strip()
                # Extract wallet counts
                long_w = 0
                short_w = 0
                try:
                    # The 5th cell (index 4) is Long wallets, 6th (index 5) is Short wallets
                    if len(cells) >= 6:
                        lw_str = re.sub(r'[^\d]', '', cells[4].strip())
                        sw_str = re.sub(r'[^\d]', '', cells[5].strip())
                        if lw_str: long_w = int(lw_str)
                        if sw_str: short_w = int(sw_str)
                except (ValueError, IndexError):
                    pass
                result['positions'].append({
                    'coin': coin,
                    'long_str': long_s,
                    'short_str': short_s,
                    'net_str': net_s,
                    'bias': bias,
                    'long_wallets': long_w,
                    'short_wallets': short_w,
                    'total_wallets': long_w + short_w,
                })
    # Count bullish vs bearish using wallet counts
    total_long_w = sum(p.get('long_wallets', 0) for p in result['positions'])
    total_short_w = sum(p.get('short_wallets', 0) for p in result['positions'])
    total_w = total_long_w + total_short_w
    result['bias_summary'] = {
        'bullish_wallets': total_long_w,
        'bearish_wallets': total_short_w,
        'bull_ratio': round(total_long_w / total_w * 100, 0) if total_w > 0 else 50,
        'total_coins': len(result['positions']),
        'window': 'week',
        'top_traders': 20,
    }
    return result

def parse_econ_calendar(text: str) -> list[dict]:
    """Parse econ_calendar output (Polish labels)"""
    events = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or not line.startswith('•'):
            continue
        m = re.match(r'•\s*(.+?UTC).*?\[(.+?)\]\s*(.+?)\s*\(est:\s*(.+?)\)', line)
        if not m:
            # Try without estimate
            m = re.match(r'•\s*(.+?UTC).*?\[(.+?)\]\s*(.+?)$', line)
        if not m:
            continue
        raw_impact = m.group(2).strip().upper()
        impact_map = {'WYSOKI': 'HIGH', 'SREDNI': 'MEDIUM', 'NISKI': 'LOW', 'HIGH': 'HIGH', 'MEDIUM': 'MEDIUM', 'LOW': 'LOW'}
        impact = impact_map.get(raw_impact, raw_impact)
        events.append({
            'time': m.group(1).strip(),
            'impact': impact,
            'event': m.group(3).strip(),
            'estimate': m.group(4).strip() if len(m.groups()) >= 4 and m.group(4) else '',
        })
    return events

def parse_macro_news(text: str) -> list[dict]:
    """Parse macro news output — extract JSON headlines from the table, strip border chars"""
    articles = []
    for m in re.finditer(r'"headline"\s*:\s*"([^"]+)', text):
        headline = m.group(1)
        # Clean up: remove table border chars, newlines, extra spaces
        headline = re.sub(r'[│┃║]', '', headline)
        headline = re.sub(r'\s+', ' ', headline).strip()
        if not headline or len(headline) < 10:
            continue
        # Find tag nearby
        tag_m = re.search(r'"tag"\s*:\s*"([^"]+)"', text[m.start():m.start()+300])
        tag = tag_m.group(1) if tag_m else 'neutral'
        articles.append({'title': headline, 'tag': tag, 'source': 'CoinDesk'})
    seen = set()
    unique = []
    for a in articles:
        if a['title'] not in seen:
            seen.add(a['title'])
            unique.append(a)
    return unique[:15]


def get_whale_bias_for_coin(whales: dict, coin: str) -> dict:
    """Get whale bias specifically for one coin"""
    for pos in whales.get('positions', []):
        if pos['coin'].upper() == coin.upper():
            is_long = 'LONG' in pos['bias'] and 'SHORT' not in pos['bias']
            return {
                'coin': pos['coin'],
                'bias': 'LONG' if is_long else 'SHORT',
                'long_pct': 100 if is_long else 0,
                'short_pct': 0 if is_long else 100,
                'net': pos.get('net_str', ''),
            }
    return {'coin': coin, 'bias': 'NEUTRAL', 'long_pct': 50, 'short_pct': 50, 'net': '—'}


# ── API Routes ──────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(str(Path(__file__).parent), 'index.html')

@app.route('/api/overview')
def api_overview():
    """Aggregate overview: BTI, positions summary, market pulse"""
    # Positions
    positions = []
    if POSITIONS_JSON.exists():
        try:
            with open(POSITIONS_JSON) as f:
                positions = json.load(f)
        except Exception:
            pass

    pos_summary = {
        'total': len(positions),
        'upnl': sum(p.get('upnl_usd', 0) for p in positions),
        'exchanges': list(set(p.get('venue', '?') for p in positions)),
    }

    # Fear & Greed
    fg_text = run_script('fear_greed.py', ['--brief'], timeout=20).get('output', '')
    fg = parse_fear_greed(fg_text)

    # OI
    oi_text = run_script('oi_tracker.py', ['--brief'], timeout=25).get('output', '')
    oi = parse_oi(oi_text)

    # Quotes
    q_text = run_script('quotes.py', ['--brief'], timeout=20).get('output', '')
    quotes = parse_quotes(q_text)

    # Token Dashboard (for BTI)
    td_text = run_script('token_dashboard.py', timeout=30).get('output', '')
    tokens = parse_token_dashboard(td_text)

    # Whales
    wh_text = run_script('hl_whale_tracker.py', ['whales', '--top', '20', '--window', 'week'], timeout=30).get('output', '')
    whales = parse_whales(wh_text)

    # Econ calendar
    ec_text = run_script('econ_calendar.py', ['--upcoming'], timeout=20).get('output', '')
    econ = parse_econ_calendar(ec_text)

    # News
    news_text = run_script('macro_news.py', ['--source', 'coindesk'], timeout=45).get('output', '')
    # If the output is usage/help text (script failed), skip
    if 'usage:' in news_text.lower() or not news_text.strip():
        news = []
    else:
        news = parse_macro_news(news_text)

    # BTI Calculation
    bti = calculate_bti(fg, tokens, whales, oi)

    # Per-coin whale breakdown for the interactive thermometer
    whale_coins = {}
    for p in whales.get('positions', []):
        whale_coins[p['coin']] = get_whale_bias_for_coin(whales, p['coin'])
    # Add key coins that might not be in whale positions
    for sym in ['BTC', 'ETH', 'SOL', 'HYPE', 'LINK']:
        if sym not in whale_coins and any(t.get('symbol') == sym for t in tokens):
            whale_coins[sym] = get_whale_bias_for_coin(whales, sym)

    return jsonify({
        'timestamp': utc_now(),
        'bti': bti,
        'positions': pos_summary,
        'positions_detail': positions,
        'fear_greed': fg,
        'oi': oi,
        'quotes': quotes,
        'tokens': tokens,
        'whales': whales,
        'whale_coins': whale_coins,
        'econ_calendar': econ,
        'news': news[:10],
    })

@app.route('/api/opportunities')
def api_opportunities():
    """Opportunity in Time — scored setups from confluence signals"""
    td_text = run_script('token_dashboard.py', timeout=30).get('output', '')
    tokens = parse_token_dashboard(td_text)

    wh_text = run_script('hl_whale_tracker.py', ['whales', '--top', '20', '--window', 'week'], timeout=30).get('output', '')
    whales = parse_whales(wh_text)

    fg_text = run_script('fear_greed.py', ['--brief'], timeout=20).get('output', '')
    fg = parse_fear_greed(fg_text)

    opportunities = []
    for token in tokens:
        signals = []
        score = 50  # baseline

        # Signal 1: Whale bias
        for wp in whales.get('positions', []):
            if wp['coin'].upper() == token['symbol']:
                if 'LONG' in wp['bias'] and 'SHORT' not in wp['bias']:
                    signals.append('🐋 Whale LONG')
                    score += 12
                elif 'SHORT' in wp['bias']:
                    signals.append('🐻 Whale SHORT')
                    score -= 10
                break

        # Signal 2: Composite score
        comp = token.get('composite', 5)
        if comp is not None:
            if comp <= 3:
                signals.append('📉 Oversold (composite)')
                score += 10
            elif comp >= 8:
                signals.append('📈 Overbought (composite)')
                score -= 8

        # Signal 3: Sentiment extreme
        sent = token.get('sentiment')
        if sent is not None:
            if sent <= 20:
                signals.append('😱 Extreme Fear')
                score += 8
            elif sent >= 80:
                signals.append('🤑 Extreme Greed')
                score -= 5

        # Signal 4: Smart money divergence
        sm_long = token.get('sm_long_pct', 50)
        sm_short = token.get('sm_short_pct', 50)
        if sm_long is not None and sm_short is not None:
            if sm_short > 70:
                signals.append(f'⚡ SM {sm_short}% SHORT')
                score -= 7
            elif sm_long > 70:
                signals.append(f'⚡ SM {sm_long}% LONG')
                score += 7

        # Signal 5: Price change velocity
        chg = token.get('change_1d', 0)
        if chg is not None:
            if chg < -5:
                signals.append('💥 Dump -5%+ (bounce?)')
                score += 9
            elif chg > 5:
                signals.append('🚀 Pump +5%+ (fade?)')
                score -= 6

        direction = 'LONG' if score > 50 else 'SHORT' if score < 50 else 'NEUTRAL'
        confidence = abs(score - 50) * 2  # 0-100

        opportunities.append({
            'symbol': token['symbol'],
            'price': token.get('price', 0),
            'direction': direction,
            'confidence': min(confidence, 99),
            'score': score,
            'signals': signals,
            'change_1d': token.get('change_1d', 0),
            'composite': token.get('composite', 5),
        })

    # Sort by confidence descending
    opportunities.sort(key=lambda x: x['confidence'], reverse=True)

    return jsonify({
        'timestamp': utc_now(),
        'opportunities': opportunities,
        'market_bias': {
            'fear_greed': fg.get('score', 50),
            'fear_label': fg.get('label', ''),
            'whale_bull_ratio': whales.get('bias_summary', {}).get('bull_ratio', 50),
        }
    })

@app.route('/api/positions')
def api_positions():
    """Detailed positions"""
    positions = []
    if POSITIONS_JSON.exists():
        try:
            with open(POSITIONS_JSON) as f:
                positions = json.load(f)
        except Exception:
            pass

    # Get history for delta
    delta_info = None
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.execute(
                "SELECT output FROM analysis_history WHERE script='fetch_positions.py' ORDER BY id DESC LIMIT 2"
            )
            rows = cur.fetchall()
            con.close()
            if len(rows) >= 2:
                old = json.loads(rows[1][0]) if rows[1][0].startswith('[') else []
                new = positions
                if old and new:
                    old_upnl = sum(p.get('upnl_usd', 0) for p in (old if isinstance(old, list) else []))
                    new_upnl = sum(p.get('upnl_usd', 0) for p in (new if isinstance(new, list) else []))
                    delta_info = round(new_upnl - old_upnl, 2)
        except Exception:
            pass

    return jsonify({
        'timestamp': utc_now(),
        'positions': positions,
        'total_upnl': sum(p.get('upnl_usd', 0) for p in positions),
        'delta_upnl': delta_info,
    })

@app.route('/api/refresh/<script_name>', methods=['POST'])
def api_refresh(script_name: str):
    """Run a script on demand"""
    script_map = {
        'positions': ('fetch_positions.py', ['--no-solana']),
        'whales': ('hl_whale_tracker.py', ['whales', '--top', '10', '--window', 'day']),
        'market': ('token_dashboard.py', []),
        'news': ('macro_news.py', ['--source', 'coindesk']),
    }
    if script_name not in script_map:
        return jsonify({'ok': False, 'error': f'Unknown script: {script_name}'}), 400
    script, args = script_map[script_name]
    result = run_script(script, args, timeout=45)
    return jsonify({'ok': result['ok'], 'output': result['output'][:2000], 'error': result['error']})

@app.route('/api/daemons')
def api_daemons():
    """Check running daemon status"""
    daemons = ['volume_scanner.py', 'smart_money_tracker.py', 'listings_scanner.py']
    statuses = []
    for d in daemons:
        try:
            r = subprocess.run(
                ['tasklist', '/FI', f'IMAGENAME eq python.exe', '/FO', 'CSV'],
                capture_output=True, timeout=5
            )
            out = r.stdout.decode('utf-8', errors='replace').lower()
            running = d.lower().replace('.py', '') in out
        except Exception:
            running = False

        # Last output from history
        last_run = '—'
        if DB_PATH.exists():
            try:
                con = sqlite3.connect(DB_PATH)
                cur = con.execute(
                    "SELECT ts FROM analysis_history WHERE script=? ORDER BY id DESC LIMIT 1",
                    (d,)
                )
                row = cur.fetchone()
                con.close()
                if row:
                    last_run = row[0]
            except Exception:
                pass

        statuses.append({
            'name': d.replace('.py', ''),
            'running': running,
            'last_run': last_run,
            'status': 'active' if running else 'stopped',
        })
    return jsonify({'daemons': statuses, 'timestamp': utc_now()})

@app.route('/api/costs')
def api_costs():
    """AI cost tracking"""
    result = run_script('cost_tracker.py', timeout=30)
    return jsonify({
        'output': result.get('output', '')[:3000],
        'ok': result['ok'],
        'timestamp': utc_now(),
    })

@app.route('/api/activity')
def api_activity():
    """Recent activity log"""
    limit = request.args.get('limit', 50, type=int)
    activities = []
    if DB_PATH.exists():
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.execute(
                "SELECT ts, script, label, ok, substr(output,1,200) as preview "
                "FROM analysis_history ORDER BY id DESC LIMIT ?", (limit,)
            )
            for row in cur.fetchall():
                activities.append({
                    'ts': row[0],
                    'script': row[1],
                    'label': row[2],
                    'ok': bool(row[3]),
                    'preview': row[4],
                })
            con.close()
        except Exception:
            pass
    return jsonify({'activities': activities, 'timestamp': utc_now()})


# ── BTI Calculation ─────────────────────────────────────────────────────

def calculate_bti(fg: dict, tokens: list[dict], whales: dict, oi: list[dict]) -> dict:
    """Bitcoin Trend Index — synthetic 0-100 score"""
    scores = []
    components = {}

    # 1. Fear & Greed (weight 30%)
    fg_score = fg.get('score', 50)
    fg_norm = fg_score  # already 0-100
    scores.append(fg_norm * 0.30)
    components['fear_greed'] = {'score': fg_norm, 'weight': 30, 'label': fg.get('label', '')}

    # 2. Bitcoin specific data from tokens
    btc_token = next((t for t in tokens if t.get('symbol') == 'BTC'), None)
    bti_btc = 50
    if btc_token:
        # Sentiment (30%)
        sent = btc_token.get('sentiment', 50)
        # Composite inverted (low composite = bullish opportunity = high BTI)
        comp = btc_token.get('composite', 5)
        comp_inv = (10 - comp) * 10  # 1→90, 10→0
        # Smart money: more short = lower score
        sm_short = btc_token.get('sm_short_pct', 50)
        sm_factor = 100 - sm_short
        bti_btc = int(sent * 0.4 + comp_inv * 0.3 + sm_factor * 0.3)
        scores.append(bti_btc * 0.35)
        components['btc_sentiment'] = {'score': sent, 'weight': 14, 'label': 'BTC Sentiment'}
        components['btc_composite'] = {'score': int(comp_inv), 'weight': 10.5, 'label': 'BTC Composite'}
        components['btc_smart_money'] = {'score': int(sm_factor), 'weight': 10.5, 'label': 'Smart Money Bias'}

    # 3. Whale consensus (weight 20%)
    bull_ratio = whales.get('bias_summary', {}).get('bull_ratio', 50)
    scores.append(bull_ratio * 0.20)
    components['whale_consensus'] = {'score': bull_ratio, 'weight': 20, 'label': 'Whale Consensus'}

    # 4. OI momentum (weight 15%) — higher OI growth = more activity
    btc_oi = next((o for o in oi if o.get('symbol') == 'BTC'), None)
    oi_score = 50
    if btc_oi:
        oi_val = btc_oi.get('oi_b', 0)
        # Compare to historical average — simplified: just use as proxy
        oi_score = min(90, max(10, int(oi_val * 10)))  # rough scaling
    scores.append(oi_score * 0.15)
    components['oi_momentum'] = {'score': oi_score, 'weight': 15, 'label': 'OI Momentum'}

    total = sum(scores)
    bti = int(min(99, max(1, total)))

    # Label
    if bti >= 70:
        label = '🟢 BULLISH'
        desc = 'Momentum sprzyja bykom. Szukaj okazji LONG.'
    elif bti >= 55:
        label = '🔵 LEKKO BYCZO'
        desc = 'Przewaga byków, ale bez przesadnego entuzjazmu.'
    elif bti >= 45:
        label = '🟡 MIXED'
        desc = 'Rynek niezdecydowany. Czekaj na wyraźny sygnał.'
    elif bti >= 30:
        label = '🟠 LEKKO NIEDŹWIEDZIO'
        desc = 'Przewaga niedźwiedzi. Ostrożność wskazana.'
    else:
        label = '🔴 BEARISH'
        desc = 'Mocna presja podaży. Rozważ SHORT lub stay cash.'

    return {
        'score': bti,
        'label': label,
        'description': desc,
        'components': components,
        'timestamp': utc_now(),
    }


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5009))
    print(f'⚡ WAR ROOM — Trading Command Center')
    print(f'   http://127.0.0.1:{port}')
    app.run(host='127.0.0.1', port=port, debug=False)
