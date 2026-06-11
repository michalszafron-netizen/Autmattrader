#!/usr/bin/env python3
"""Eliksir V2 — fast optimization on 12,347 BTC 1H bars (focused grid)"""
import json, numpy as np, time

with open('scripts/btc_1h_data.json') as f: raw = json.load(f)
n = len(raw)
closes = np.array([b["c"] for b in raw], dtype=np.float64)
highs = np.array([b["h"] for b in raw], dtype=np.float64)
lows = np.array([b["l"] for b in raw], dtype=np.float64)
print(f"Data: {n} bars, ${min(lows):.0f}-${max(highs):.0f}", flush=True)
t0 = time.time()

# Pre-compute ALL indicators
def rma(v, L):
    r = np.full_like(v, np.nan); a = 1.0/L
    for i in range(L, len(v)):
        r[i] = a*v[i] + (1-a)*(r[i-1] if not np.isnan(r[i-1]) else np.mean(v[i-L+1:i+1]))
    return r
def sma(v, L):
    r = np.full_like(v, np.nan)
    for i in range(L-1, len(v)): r[i] = np.mean(v[i-L+1:i+1])
    return r

print("Pre-computing...", flush=True)
# RSI
d = np.diff(closes); g = np.where(d>0,d,0); lo = np.where(d<0,-d,0)
def rsi_pre(L):
    ag = np.full(n, np.nan); al = np.full(n, np.nan)
    if L >= n: return np.full(n, np.nan)
    ag[L] = np.mean(g[:L]); al[L] = np.mean(lo[:L])
    for i in range(L+1, n):
        ag[i] = (ag[i-1]*(L-1)+g[i-1])/L; al[i] = (al[i-1]*(L-1)+lo[i-1])/L
    r = np.full(n, np.nan); rs = np.where(al==0,100,ag/al); r[L:] = 100-(100/(1+rs[L:])); return r

rsi7 = rsi_pre(7); rsi14 = rsi_pre(14)
atr10 = rma(np.maximum(highs[1:]-lows[1:], np.maximum(abs(highs[1:]-closes[:-1]), abs(lows[1:]-closes[:-1]))), 10)
atr14 = rma(np.maximum(highs[1:]-lows[1:], np.maximum(abs(highs[1:]-closes[:-1]), abs(lows[1:]-closes[:-1]))), 14)
ma10 = sma(closes, 10); ma20 = sma(closes, 20); ma30 = sma(closes, 30); ma50 = sma(closes, 50); ma100 = sma(closes, 100)

# MACD
ema8 = rma(closes, 8); ema18 = rma(closes, 18); ema12 = rma(closes, 12); ema26 = rma(closes, 26)
macd_8_18 = ema8 - ema18; macd_sig_8_18 = rma(macd_8_18, 7); macd_h_8_18 = macd_8_18 - macd_sig_8_18
macd_12_26 = ema12 - ema26; macd_sig_12_26 = rma(macd_12_26, 9); macd_h_12_26 = macd_12_26 - macd_sig_12_26

# Mom
mom3 = np.full(n, np.nan); mom7 = np.full(n, np.nan)
for i in range(3, n): mom3[i] = (closes[i]-closes[i-3])/closes[i-3]*100
for i in range(7, n): mom7[i] = (closes[i]-closes[i-7])/closes[i-7]*100

# ATR arrays with proper alignment
def fix_atr(a, n):
    r = np.full(n, np.nan); r[1:] = a; return r
atr10 = fix_atr(atr10, n); atr14 = fix_atr(atr14, n)

W = 500
print(f"Pre-compute: {time.time()-t0:.1f}s", flush=True)

def run(rl, mf, ms, macd_choice, ml, th, sl, tp, al):
    if macd_choice == 0:
        macd_l, macd_sig_v, macd_h = macd_8_18, macd_sig_8_18, macd_h_8_18
    else:
        macd_l, macd_sig_v, macd_h = macd_12_26, macd_sig_12_26, macd_h_12_26
    
    rsi_v = rsi7 if rl == 7 else rsi14
    atr_v = atr10 if al == 10 else atr14
    mom_v = mom3 if ml == 3 else mom7
    
    if mf == 10: ma_f = ma10
    elif mf == 20: ma_f = ma20
    else: ma_f = ma30
    if ms == 30: ma_s = ma30
    elif ms == 50: ma_s = ma50
    else: ma_s = ma100
    
    pos = 0; entry = 0.0; trades = []; hn = 0
    
    for i in range(W, n):
        if np.isnan(rsi_v[i]) or np.isnan(ma_f[i]) or np.isnan(atr_v[i]): continue
        b = 0; r = 0
        
        if rsi_v[i] < 30: b += 2
        elif rsi_v[i] > 70: r += 2
        elif rsi_v[i] < 40: b += 1
        elif rsi_v[i] > 60: r += 1
        
        if not np.isnan(ma_f[i]) and not np.isnan(ma_s[i]):
            if ma_f[i] > ma_s[i] and closes[i] > ma_f[i]: b += 2
            elif ma_f[i] < ma_s[i] and closes[i] < ma_f[i]: r += 2
        
        if not np.isnan(macd_l[i]) and not np.isnan(macd_h[i]):
            if macd_l[i] > macd_sig_v[i] and macd_h[i] > 0: b += 1
            elif macd_l[i] < macd_sig_v[i] and macd_h[i] < 0: r += 1
            if macd_h[i] > macd_h[i-1] and macd_h[i] > 0: b += 1
            elif macd_h[i] < macd_h[i-1] and macd_h[i] < 0: r += 1
        
        if not np.isnan(mom_v[i]):
            if mom_v[i] > 0.5: b += 1
            elif mom_v[i] < -0.5: r += 1
        
        net = b - r
        
        if pos == 0:
            if net >= th: pos, entry = 1, closes[i]
            elif net <= -th: pos, entry = -1, closes[i]
        elif pos == 1:
            sp = entry - atr_v[i]*sl; tpv = entry + atr_v[i]*tp
            hs = closes[i] <= sp; ht = closes[i] >= tpv
            if hs or ht or (not np.isnan(rsi_v[i]) and rsi_v[i] > 78) or net <= -1:
                ep = sp if hs else (tpv if ht else closes[i])
                trades.append((ep-entry)/entry*100); pos = 0; hn += 1
        elif pos == -1:
            sp = entry + atr_v[i]*sl; tpv = entry - atr_v[i]*tp
            hs = closes[i] >= sp; ht = closes[i] <= tpv
            if hs or ht or (not np.isnan(rsi_v[i]) and rsi_v[i] < 22) or net >= 1:
                ep = sp if hs else (tpv if ht else closes[i])
                trades.append((entry-ep)/entry*100); pos = 0; hn += 1
        
        if hn >= 500: break  # Safety: cap trades
    
    nt = len(trades)
    if nt < 150: return None
    wins = [t for t in trades if t > 0]; losses = [t for t in trades if t <= 0]
    pf = (sum(wins) if wins else 0) / (abs(sum(losses)) if losses else 1)
    return {'pf': pf, 'n': nt, 'wr': len(wins)/nt*100, 'total': sum(trades)}

results = []; total = 0
print("Running grid...", flush=True)
for rl in [7, 14]:
    for mf in [10, 20, 30]:
        for ms in [30, 50, 100]:
            if mf >= ms: continue
            for macd_c in [0, 1]:
                for ml in [3, 7]:
                    for th in [1, 2]:
                        for sl in [0.3, 0.5, 0.8]:
                            for tp in [1.5, 2.0, 3.0]:
                                if tp <= sl: continue
                                for al in [10, 14]:
                                    r = run(rl, mf, ms, macd_c, ml, th, sl, tp, al)
                                    total += 1
                                    if r: results.append((r['pf'], r['n'], r['wr'], r['total'],
                                        {'th':th,'sl':sl,'tp':tp,'rl':rl,'mf':mf,'ms':ms,
                                         'macd':macd_c,'ml':ml,'al':al}))
    print(f"  rl={rl}: {total} tested, {len(results)} valid ({time.time()-t0:.0f}s)", flush=True)

results.sort(key=lambda x: (x[0], x[1]), reverse=True)
macd_names = {0: "MACD(8,18,7)", 1: "MACD(12,26,9)"}
print(f"\n{'='*95}")
print(f"Total: {total} | Valid (>=150 trades): {len(results)} | Time: {time.time()-t0:.0f}s")
print(f"{'='*95}")
print(f"{'':>2} {'PF':>8} {'Trades':>7} {'WR':>6} {'PnL%':>8} | Params")
print(f"{'='*95}")
for i, (pf, n, wr, tp, p) in enumerate(results[:10]):
    print(f"#{i+1:>1}  {pf:>8.4f} {n:>7} {wr:>5.1f}% {tp:>8.2f}% | "
          f"th={p['th']} SL={p['sl']} TP={p['tp']} ATR={p['al']} "
          f"RSI={p['rl']} MA({p['mf']},{p['ms']}) "
          f"{macd_names[p['macd']]} mom={p['ml']}", flush=True)

if results:
    print(f"\n{'='*50}")
    print(f"Best PF: {results[0][0]:.4f} | Trades: {results[0][1]} | WR: {results[0][2]:.1f}%")
    print(f"Avg PF top 10: {np.mean([r[0] for r in results[:10]]):.4f}")
    print(f"Avg trades top 10: {np.mean([r[1] for r in results[:10]]):.0f}")
