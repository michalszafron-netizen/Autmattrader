"""ccxt_prices.py — Multi-exchange price fetcher using CCXT library.

Uses Binance by default (no API key needed for public market data).
Designed as the primary source for real-time crypto prices in Alpha Desk.

CCXT free tier covers everything we need:
  - fetch_ticker()   → current price + 24h change
  - fetch_tickers()  → multiple symbols at once
  - fetch_ohlcv()    → historical candles (for future analysis / arbitrage)
  - fetch_order_book() → orderbook depth

No API keys needed for public endpoints on Binance.

Usage:
    python scripts/ccxt_prices.py                       # default: BTC ETH SOL HYPE
    python scripts/ccxt_prices.py --coins BTC ETH SOL   # custom coins
    python scripts/ccxt_prices.py --brief               # one line per coin
    python scripts/ccxt_prices.py --json                # machine-readable JSON
    python scripts/ccxt_prices.py --exchange kraken     # different exchange
    python scripts/ccxt_prices.py --ohlcv BTC --tf 1h   # last 24 candles BTC/USDT

Future use cases:
    python scripts/ccxt_prices.py --arbitrage BTC       # compare BTC price across exchanges
    python scripts/ccxt_prices.py --funding             # funding rates (Binance futures)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import ccxt
except ImportError:
    print("ccxt not installed. Run: uv pip install ccxt --python .venv\\Scripts\\python.exe")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_COINS  = ['BTC', 'ETH', 'SOL', 'HYPE', 'LINK', 'AVAX']
QUOTE_CURRENCY = 'USDT'

# Exchange presets (all use public REST — no API key required)
EXCHANGE_PRESETS: dict[str, dict] = {
    'binance':     {'options': {'defaultType': 'spot'}},
    'binanceusdm': {'options': {'defaultType': 'future'}},  # USDT-M futures
    'hyperliquid': {'options': {'defaultType': 'swap'}},    # HL perps: BTC/USDC:USDC, HYPE/USDC:USDC
    # NOTE: HL xyz DEX (GOLD/SILVER/SP500/OIL) is NOT covered by CCXT — fetched via direct REST in server.py
    'kraken':      {},
    'okx':         {},
    'bybit':       {'options': {'defaultType': 'spot'}},
    'coinbase':    {},
}

# ── Exchange init ─────────────────────────────────────────────────────────────

def make_exchange(name: str) -> ccxt.Exchange:
    cfg = EXCHANGE_PRESETS.get(name, {})
    cls = getattr(ccxt, name, None)
    if cls is None:
        raise ValueError(f"Exchange '{name}' not supported by ccxt. "
                         f"Available: {', '.join(EXCHANGE_PRESETS.keys())}")
    return cls({**cfg, 'enableRateLimit': True})


# ── Price fetching ────────────────────────────────────────────────────────────

def fetch_prices(coins: list[str], exchange_name: str = 'binance') -> list[dict]:
    """Fetch current prices for the given coins from an exchange."""
    ex = make_exchange(exchange_name)
    symbols = [f'{c}/{QUOTE_CURRENCY}' for c in coins]

    # Batch fetch (one API call for all tickers on Binance)
    try:
        tickers = ex.fetch_tickers(symbols)
    except ccxt.BadSymbol:
        # Fallback: fetch one by one, skip unavailable
        tickers = {}
        for sym in symbols:
            try:
                t = ex.fetch_ticker(sym)
                tickers[sym] = t
            except Exception:
                pass

    results = []
    for coin, sym in zip(coins, symbols):
        t = tickers.get(sym, {})
        results.append({
            'coin':     coin,
            'symbol':   sym,
            'exchange': exchange_name,
            'price':    t.get('last') or t.get('close'),
            'bid':      t.get('bid'),
            'ask':      t.get('ask'),
            'pct_24h':  t.get('percentage'),       # 24h change %
            'vol_24h':  t.get('quoteVolume'),       # USDT volume 24h
            'high_24h': t.get('high'),
            'low_24h':  t.get('low'),
        })
    return results


def fetch_ohlcv(coin: str, timeframe: str = '1h', limit: int = 24,
                exchange_name: str = 'binance') -> list[dict]:
    """Fetch OHLCV candles — useful for trend analysis and future arbitrage."""
    ex = make_exchange(exchange_name)
    sym = f'{coin}/{QUOTE_CURRENCY}'
    raw = ex.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
    return [
        {'ts': ex.iso8601(r[0]), 'open': r[1], 'high': r[2],
         'low': r[3], 'close': r[4], 'volume': r[5]}
        for r in raw
    ]


# ── Display ───────────────────────────────────────────────────────────────────

def _fmt_price(p: float | None) -> str:
    if p is None:
        return '—'
    if p >= 1000:
        return f'{p:,.2f}'
    if p >= 1:
        return f'{p:.4f}'
    return f'{p:.6f}'


def _fmt_pct(p: float | None) -> str:
    if p is None:
        return '  —  '
    sign = '+' if p >= 0 else ''
    return f'{sign}{p:.2f}%'


def display_full(results: list[dict], exchange_name: str) -> None:
    print(f'\n  Prices via CCXT · {exchange_name.upper()}\n')
    print(f'  {"Coin":<8} {"Price":>12}  {"24h":>8}  {"24h Vol (M)":>12}')
    print('  ' + '─' * 48)
    for r in results:
        price  = _fmt_price(r['price'])
        pct    = _fmt_pct(r['pct_24h'])
        vol_m  = f'{r["vol_24h"]/1e6:.1f}M' if r.get('vol_24h') else '—'
        sym    = r['coin']
        print(f'  {sym:<8} {price:>12}  {pct:>8}  {vol_m:>12}')
    print()


def display_brief(results: list[dict]) -> None:
    parts = [
        f"{r['coin']}: {_fmt_price(r['price'])} ({_fmt_pct(r['pct_24h'])})"
        for r in results if r.get('price')
    ]
    print('Crypto: ' + '  |  '.join(parts))


def display_json(results: list[dict]) -> None:
    out = {r['coin']: {
        'price': r['price'],
        'pct_24h': r['pct_24h'],
        'vol_24h': r.get('vol_24h'),
    } for r in results}
    print(json.dumps(out, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description='CCXT price fetcher — Binance + more')
    p.add_argument('--coins',    nargs='+', default=DEFAULT_COINS,
                   help=f'Coins to fetch (default: {" ".join(DEFAULT_COINS)})')
    p.add_argument('--exchange', default='binance',
                   choices=list(EXCHANGE_PRESETS.keys()),
                   help='Exchange to use (default: binance)')
    p.add_argument('--brief',    action='store_true', help='One line output')
    p.add_argument('--json',     action='store_true', help='JSON output')
    p.add_argument('--ohlcv',    metavar='COIN',      help='Fetch OHLCV for a coin')
    p.add_argument('--tf',       default='1h',        help='Timeframe for OHLCV (default: 1h)')
    p.add_argument('--limit',    type=int, default=24, help='Number of OHLCV candles')
    args = p.parse_args()

    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    if args.ohlcv:
        candles = fetch_ohlcv(args.ohlcv.upper(), args.tf, args.limit, args.exchange)
        if args.json:
            print(json.dumps(candles, indent=2))
        else:
            print(f'\n  OHLCV {args.ohlcv.upper()}/USDT · {args.tf} · {args.exchange}\n')
            print(f'  {"Timestamp":<22} {"Open":>10} {"High":>10} {"Low":>10} {"Close":>10} {"Volume":>14}')
            print('  ' + '─' * 80)
            for c in candles:
                print(f'  {c["ts"]:<22} {c["open"]:>10.2f} {c["high"]:>10.2f} '
                      f'{c["low"]:>10.2f} {c["close"]:>10.2f} {c["volume"]:>14.2f}')
        return

    coins = [c.upper() for c in args.coins]
    results = fetch_prices(coins, args.exchange)

    if args.json:
        display_json(results)
    elif args.brief:
        display_brief(results)
    else:
        display_full(results, args.exchange)


if __name__ == '__main__':
    main()
