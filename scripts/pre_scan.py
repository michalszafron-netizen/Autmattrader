#!/usr/bin/env python3
"""
pre_scan.py — Market pre-scan for trading decisions.
Sources: calendar, fear&greed, macro quotes, news, Bybit perps (ALL coins), OI, smart money.
Outputs: ranked setups with recommendation.
"""

import subprocess, json, re, sys, time, os
from pathlib import Path
from datetime import datetime, timezone

BASE = str(Path("C:/Users/krypt/trading-ai"))
BASH_BASE = BASE.replace('\\', '/')
SCRIPTS = Path(BASE) / "scripts"
PY = str(Path(BASE) / ".venv" / "Scripts" / "python.exe")


def run_script(name, args=None, timeout=15):
    cmd = [PY, str(SCRIPTS / name)]
    if args:
        cmd.extend(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"
    except Exception as e:
        return f"[ERROR] {e}"


def run_bybit_mcp(method, params):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": method, "arguments": params}
    })
    cmd = f"cd {BASH_BASE} && source <(grep BYBIT .env | sed 's/^/export /') && echo '{payload}' | node bybit-mcp/dist/index.js 2>/dev/null"
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        txt = data["result"]["content"][0]["text"]
        return json.loads(txt)
    except Exception as e:
        return {"error": str(e)}


def extract_fng(text):
    m = re.search(r'(\d+)/100', text)
    return int(m.group(1)) if m else None


def extract_quotes(text):
    q = {}
    for line in text.split('\n'):
        m = re.search(r'(\w[\w\s]+):\s*\$?([\d,.]+)', line)
        if m and m.group(1).strip() not in ('Metals', 'Energy', 'Indices', 'Agri', 'Stocks'):
            q[m.group(1).strip()] = float(m.group(2).replace(',', ''))
    return q


def extract_oi(text):
    oi = {}
    for m in re.finditer(r'(\w+):\s*\$?([\d.]+)([BMK])', text):
        mult = {"B": 1e9, "M": 1e6, "K": 1e3}.get(m.group(3), 1)
        oi[m.group(1)] = float(m.group(2)) * mult
    return oi


def extract_calendar(text):
    events = []
    for line in text.split('\n'):
        if 'waznych' in line.lower() or 'ważnych' in line.lower():
            events.append(("Brak ważnych danych", "low"))
        elif re.match(r'^\d', line.strip()):
            events.append((line.strip(), "event"))
    return events


def fmt_price(p, symbol=""):
    """Smart price formatting: more decimals for sub-$1 coins."""
    if symbol in ("DOGE", "PEPE", "BONK", "SHIB", "1000PEPE"):
        return f"{p:.6f}"
    if p < 1: return f"{p:.6f}"
    if p < 10: return f"{p:.4f}"
    if p < 100: return f"{p:.2f}"
    return f"{p:.2f}"


def extract_news_v2(text):
    headlines = []
    for m in re.finditer(r'"headline"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
        hl = m.group(1).replace('\n', ' ').replace('\r', '').replace('  ', ' ').strip()
        headlines.append(hl)
    return headlines[:3]


def compute_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = 0, 0
    for i in range(-period, 0):
        diff = prices[i] - prices[i-1]
        if diff > 0: gains += diff
        else: losses -= diff
    avg_g = gains / period
    avg_l = losses / period
    if avg_l == 0: return 100
    return 100 - (100 / (1 + avg_g / avg_l))


def get_bybit_signal(symbol):
    data = run_bybit_mcp("getMarketKline", {
        "category": "linear", "symbol": symbol,
        "interval": "15", "limit": 50
    })
    if "error" in data:
        return None

    prices = []
    vols = []
    try:
        for item in data.get("result", {}).get("list", []):
            if len(item) >= 7:
                prices.append(float(item[4]))
                vols.append(float(item[6]))
        prices.reverse()
        vols.reverse()
    except:
        return None
    if len(prices) < 20:
        return None

    cur = prices[-1]
    rsi = compute_rsi(prices)
    sma20 = sum(prices[-20:]) / 20
    var20 = sum((p - sma20)**2 for p in prices[-20:]) / 20
    bb_low = sma20 - 2 * var20**0.5
    bb_high = sma20 + 2 * var20**0.5

    avg_vol = sum(vols[-10:]) / 10 if len(vols) >= 10 else 1
    vol_spike = vols[-1] / avg_vol if avg_vol > 0 else 1
    sup_24h = min(prices[-96:]) if len(prices) >= 96 else min(prices)
    res_24h = max(prices[-96:]) if len(prices) >= 96 else max(prices)

    signal = 0
    reasons = []

    if rsi < 30: signal += 3; reasons.append(f"RSI {rsi:.0f} oversold")
    elif rsi > 70: signal -= 3; reasons.append(f"RSI {rsi:.0f} overbought")
    elif rsi < 40: signal += 1; reasons.append(f"RSI {rsi:.0f} low")

    h14, l14 = max(prices[-14:]), min(prices[-14:])
    if h14 != l14:
        pos = (cur - l14) / (h14 - l14)
        if pos < 0.25: signal += 2; reasons.append("Near support")
        elif pos > 0.75: signal -= 1; reasons.append("Near resistance")

    if vol_spike > 2.5:
        signal += 2 if signal > 0 else -1
        reasons.append(f"Vol {vol_spike:.1f}x")

    if cur < bb_low: signal += 2; reasons.append("Below BB")
    elif cur > bb_high: signal -= 1; reasons.append("Above BB")

    trend = "bullish" if prices[-1] > prices[-20] else "bearish"
    signal += 1 if trend == "bullish" else -1

    return {
        "symbol": symbol, "price": round(cur, 2), "rsi": round(rsi, 1),
        "signal": signal, "trend": trend, "vol_spike": round(vol_spike, 1),
        "support": round(sup_24h, 2), "resistance": round(res_24h, 2),
        "bb_lower": round(bb_low, 2), "bb_upper": round(bb_high, 2),
        "reasons": reasons[:2]
    }


# ===================== MAIN =====================
t0 = time.time()

print("╔══════════════════════════════════════════╗")
print("║   PRE-SCAN — Market Intelligence Scan    ║")
print(f"║   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'):34s}║")
print("╚══════════════════════════════════════════╝\n")

# ━━━ LAYER 1: MACRO ━━━
print("┏━ MACRO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")

t = run_script("fear_greed.py", ["--brief"], timeout=8)
fng = extract_fng(t)
label = "Extreme Fear" if fng and fng <= 25 else "Fear" if fng <= 45 else "Neutral" if fng <= 55 else "Greed" if fng <= 75 else "Extreme Greed"
print(f"┃ Fear/Greed:  {fng}/100 — {label}")

t = run_script("quotes.py", ["--brief"], timeout=10)
q = extract_quotes(t)
for k in ["Gold", "Silver", "S&P 500", "VIX", "DXY", "US Oil", "NVDA"]:
    if k in q: print(f"┃ {k:12s}: ${q[k]:>9,.2f}")

t = run_script("econ_calendar.py", ["--upcoming"], timeout=8)
ev = extract_calendar(t)
if ev: print(f"┃ Calendar:    {'🟢' if ev[0][1]=='low' else '🔴'} {ev[0][0]}")

# News
news_raw = run_script("macro_news.py", ["--source", "coindesk"], timeout=15)
news_h = extract_news_v2(news_raw)
if not news_h:
    news_raw = run_script("macro_news.py", ["--source", "theblock"], timeout=8)
    news_h = extract_news_v2(news_raw)
for n in news_h[:2]:
    print(f"┃ News:        {n[:65]}")

print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n")

# ━━━ LAYER 2: HOT COINS ━━━
print("┏━ HOT COINS ━━━━━━━━━━━━━━━━━━━━━━━━━┓")

# Fetch all Bybit perps, find the ones with momentum
tickers_data = run_bybit_mcp("getTickers", {"category": "linear"})
hot = {}

if "error" not in tickers_data:
    for t in tickers_data.get("result", {}).get("list", []):
        sym = t.get("symbol", "")
        if not sym or not sym.endswith("USDT"):
            continue
        vol = float(t.get("turnover24h", 0) or 0)
        chg = float(t.get("price24hPcnt", 0) or 0) * 100
        if vol > 3e6:  # min $3M volume
            key = sym.replace("USDT", "")
            hot[key] = {
                "symbol": sym, "price": float(t.get("lastPrice", 0)),
                "chg24h": round(chg, 1), "vol24h": vol, "abs_chg": round(abs(chg), 1)
            }

if not hot:
    print("┃ (MCP failed — using fallback)")
    for s in ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "SUI"]:
        hot[s] = {"symbol": s + "USDT", "chg24h": 0, "vol24h": 1e7, "price": 0, "abs_chg": 0}

# Rank by momentum (volume × |change|)
ranked_hot = sorted(hot.values(), key=lambda x: x["vol24h"] * x["abs_chg"], reverse=True)[:12]

# Always ensure BTC, ETH, SOL in top
for s in ["BTC", "ETH", "SOL"]:
    if s in hot:
        ranked_hot.insert(0, ranked_hot.pop(ranked_hot.index(hot[s])))

# Analyze top 12
signals = []
for c in ranked_hot:
    s = get_bybit_signal(c["symbol"])
    if s:
        s["change_24h"] = c["chg24h"]
        s["volume_24h"] = c["vol24h"]
        signals.append(s)

# Simple ranking: signal + 24h%, tie-break by volume
for s in signals:
    s["_score"] = s["signal"] + min(s["change_24h"], 5) - max(s["change_24h"], -5) * 0.5
    s["_score"] += min(s["volume_24h"] / 1e8, 3)  # volume bonus cap at 3
signals.sort(key=lambda x: x["_score"], reverse=True)

for s in signals[:5]:
    coin = s["symbol"].replace("USDT", "")
    dir_ = "LONG" if s["signal"] > 0 else "SHORT"
    icon = "🟢" if s["signal"] > 2 else "🟡" if s["signal"] > -2 else "🔴"
    vol_label = f"${s['volume_24h']/1e6:.0f}M" if s['volume_24h'] >= 1e6 else f"${s['volume_24h']/1e3:.0f}K"
    print(f"┃ {icon} {coin:6s} @ ${fmt_price(s['price'], coin):>8s} | {dir_:5s} | "
          f"RSI {s['rsi']:<4.1f} | 24h {s['change_24h']:>+.1f}% | {vol_label}")
    if s["reasons"]:
        print(f"┃   └ {', '.join(s['reasons'])}")

print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n")

# ━━━ LAYER 3: OPEN INTEREST ━━━
print("┏━ OPEN INTEREST ━━━━━━━━━━━━━━━━━━━━━━┓")
oi_text = run_script("oi_tracker.py", ["--brief"], timeout=20)
oi = extract_oi(oi_text)
for coin, val in sorted(oi.items(), key=lambda x: x[1], reverse=True)[:6]:
    label = f"{val/1e9:.2f}B" if val >= 1e9 else f"{val/1e6:.0f}M"
    print(f"┃ {coin:5s}: {label:>10s}")
print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n")

# ━━━ LAYER 4: RECOMMENDATION ━━━
print("┏━ RECOMMENDATION ━━━━━━━━━━━━━━━━━━━━┓")
if signals:
    best = signals[0]
    coin = best["symbol"].replace("USDT", "")
    rec = "LONG" if best["signal"] > 0 else "SHORT"
    conf = "STRONG" if abs(best["signal"]) > 5 else "MODERATE" if abs(best["signal"]) > 2 else "WEAK"
    entry = best["price"]
    sl = best["support"] if rec == "LONG" else best["resistance"]
    tp = best["resistance"] if rec == "LONG" else best["support"]
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0

    # Skip coin if range too tight (DOGE etc in consolidation)
    if risk / entry < 0.001 and len(signals) > 1:
        # Show next coin that has meaningful range
        for alt in signals[1:]:
            alt_entry = alt["price"]
            alt_sl = alt["support"] if rec == "LONG" else alt["resistance"]
            alt_tp = alt["resistance"] if rec == "LONG" else alt["support"]
            alt_risk = abs(alt_entry - alt_sl)
            if alt_risk / alt_entry >= 0.001:
                best = alt
                coin = best["symbol"].replace("USDT", "")
                entry, sl, tp = alt_entry, alt_sl, alt_tp
                risk, reward = abs(entry - sl), abs(tp - entry)
                rr = round(reward / risk, 2) if risk > 0 else 0
                rec = "LONG" if best["signal"] > 0 else "SHORT"
                conf = "STRONG" if abs(best["signal"]) > 5 else "MODERATE" if abs(best["signal"]) > 2 else "WEAK"
                break

    print(f"┃ 🎯 {coin} {rec} ({conf})")
    print(f"┃   Entry ${fmt_price(entry, coin):>8s} | SL ${fmt_price(sl, coin):>8s} | TP ${fmt_price(tp, coin):>8s}")
    print(f"┃   R:R {rr} | Signal {best['signal']:+.0f}/10")
    print(f"┃   RSI {best['rsi']} | Vol ${best.get('volume_24h',0)/1e6:.1f}M")
    if len(signals) > 1:
        print(f"┃")
        print(f"┃   Also:")
        for alt in signals[1:4]:
            ac = alt["symbol"].replace("USDT", "")
            ad = "LONG" if alt["signal"] > 0 else "SHORT"
            print(f"┃     {ac:6s} {ad:5s} ({alt.get('change_24h',0):>+.1f}% | RSI {alt['rsi']})")
else:
    print(f"┃   No signals — market flat or MCP error")

print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
print(f"Scan: {time.time()-t0:.1f}s")
