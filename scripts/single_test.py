#!/usr/bin/env python3
"""Single backtest of Eliksir V2 Set #1 — no trade cap"""
import json, numpy as np

with open('scripts/btc_1h_data.json') as f: raw = json.load(f)
n = len(raw)
closes = np.array([b["c"] for b in raw])
highs = np.array([b["h"] for b in raw])
lows = np.array([b["l"] for b in raw])

print(f"Data: {n} bars", flush=True)

def rma(v, L):
    r = np.full_like(v, np.nan); a = 1.0/L
    for i in range(L, len(v)):
        r[i] = a*v[i] + (1-a)*(r[i-1] if not np.isnan(r[i-1]) else np.mean(v[i-L+1:i+1]))
    return r

def sma(v, L):
    r = np.full_like(v, np.nan)
    for i in range(L-1, len(v)): r[i] = np.mean(v[i-L+1:i+1])
    return r

# Set #1 params
th, sl, tp = 2, 0.3, 3.0
rl, mf, ms = 7, 10, 30
macd_f, macd_s, macd_sig = 8, 18, 7
ml, al = 7, 14

atr_v = rma(np.maximum(highs[1:]-lows[1:], np.maximum(abs(highs[1:]-closes[:-1]), abs(lows[1:]-closes[:-1]))), al)
atr_v2 = np.full(n, np.nan); atr_v2[1:] = atr_v; atr_v = atr_v2

d = np.diff(closes); g = np.where(d>0,d,0); lo = np.where(d<0,-d,0)
ag = np.full(n, np.nan); al_ = np.full(n, np.nan)
ag[rl] = np.mean(g[:rl]); al_[rl] = np.mean(lo[:rl])
for i in range(rl+1, n):
    ag[i] = (ag[i-1]*(rl-1)+g[i-1])/rl; al_[i] = (al_[i-1]*(rl-1)+lo[i-1])/rl
rs = np.where(al_==0,100,ag/al_); rsi = np.full(n, np.nan); rsi[rl:] = 100-(100/(1+rs[rl:]))

ma_f = sma(closes, mf); ma_s = sma(closes, ms)
ef = rma(closes, macd_f); es = rma(closes, macd_s)
macd_l = ef - es; macd_sig_v = rma(macd_l, macd_sig); macd_h = macd_l - macd_sig_v

mom = np.full(n, np.nan)
for i in range(ml, n): mom[i] = (closes[i]-closes[i-ml])/closes[i-ml]*100

W = 500; pos = 0; entry = 0.0; trades = []
for i in range(W, n):
    if np.isnan(rsi[i]) or np.isnan(ma_f[i]) or np.isnan(atr_v[i]): continue
    b, r = 0, 0
    if rsi[i] < 30: b += 2
    elif rsi[i] > 70: r += 2
    elif rsi[i] < 40: b += 1
    elif rsi[i] > 60: r += 1
    if not np.isnan(ma_f[i]) and not np.isnan(ma_s[i]):
        if ma_f[i] > ma_s[i] and closes[i] > ma_f[i]: b += 2
        elif ma_f[i] < ma_s[i] and closes[i] < ma_f[i]: r += 2
    if not np.isnan(macd_l[i]) and not np.isnan(macd_h[i]):
        if macd_l[i] > macd_sig_v[i] and macd_h[i] > 0: b += 1
        elif macd_l[i] < macd_sig_v[i] and macd_h[i] < 0: r += 1
        if macd_h[i] > macd_h[i-1] and macd_h[i] > 0: b += 1
        elif macd_h[i] < macd_h[i-1] and macd_h[i] < 0: r += 1
    if not np.isnan(mom[i]):
        if mom[i] > 0.5: b += 1
        elif mom[i] < -0.5: r += 1
    net = b - r
    if pos == 0:
        if net >= th: pos, entry = 1, closes[i]
        elif net <= -th: pos, entry = -1, closes[i]
    elif pos == 1:
        sp = entry - atr_v[i]*sl; tpv = entry + atr_v[i]*tp
        hs = closes[i] <= sp; ht = closes[i] >= tpv
        if hs or ht or (not np.isnan(rsi[i]) and rsi[i] > 78) or net <= -1:
            ep = sp if hs else (tpv if ht else closes[i]); trades.append((ep-entry)/entry*100); pos = 0
    elif pos == -1:
        sp = entry + atr_v[i]*sl; tpv = entry - atr_v[i]*tp
        hs = closes[i] >= sp; ht = closes[i] <= tpv
        if hs or ht or (not np.isnan(rsi[i]) and rsi[i] < 22) or net >= 1:
            ep = sp if hs else (tpv if ht else closes[i]); trades.append((entry-ep)/entry*100); pos = 0

nt = len(trades)
wins = [t for t in trades if t > 0]; losses = [t for t in trades if t <= 0]
pf = (sum(wins) if wins else 0) / (abs(sum(losses)) if losses else 1)
wr = len(wins)/nt*100
print(f"\n=== ELIKSIR V2 — SET #1 (NO CAP) ===")
print(f"Data: {n} bars BTC 1H, ${min(closes):.0f}-${max(closes):.0f}")
print(f"Period: Jan 2025 - May 2026")
print(f"{'='*40}")
print(f"Total Trades: {nt}")
print(f"Wins: {len(wins)} ({wr:.1f}%) | Losses: {len(losses)} ({100-wr:.1f}%)")
print(f"Profit Factor: {pf:.4f}")
print(f"Total PnL: {sum(trades):.2f}%")
print(f"Avg Win: {np.mean(wins) if wins else 0:.2f}%")
print(f"Avg Loss: {np.mean(losses) if losses else 0:.2f}%")

max_cw = 0; max_cl = 0; cw = 0; cl = 0
for t in trades:
    if t > 0: cw += 1; cl = 0; max_cw = max(max_cw, cw)
    else: cl += 1; cw = 0; max_cl = max(max_cl, cl)
print(f"Max Consecutive Wins: {max_cw}")
print(f"Max Consecutive Losses: {max_cl}")

# Monthly breakdown
from datetime import datetime
monthly = {}
for i in range(W, n):
    if pos == 0:
        if net >= th:
            pass

print(f"\nParams: th={th} SL={sl} TP={tp} RSI={rl} MA({mf},{ms}) MACD({macd_f},{macd_s},{macd_sig}) mom={ml} ATR={al}")
