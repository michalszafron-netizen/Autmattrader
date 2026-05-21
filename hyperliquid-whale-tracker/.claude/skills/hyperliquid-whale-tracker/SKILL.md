---
name: hyperliquid-whale-tracker
description: >
  Hyperliquid whale intelligence skill. Scans 33,000+ wallets on the Hyperliquid leaderboard to find the most profitable traders and the biggest losers, then shows what they're long and short on. Use this skill whenever the user asks about Hyperliquid whales, top traders, smart money, what wallets are doing, who's long or short, rekt traders, whale positions, trade ideas from on-chain data, or anything related to tracking Hyperliquid positions. Triggers on: "what are whales doing", "top traders", "smart money", "who's long", "who's short", "scan hyperliquid", "whale scan", "rekt traders", "hyperliquid wallets", "what should I trade", "give me a trade idea", "what are top traders buying".
---

# Hyperliquid Whale Tracker

You scan Hyperliquid's public leaderboard and wallet positions to show what the best and worst traders are doing right now. No API keys needed. Everything is free and public.

## Setup (First Time Only)

```bash
pip3 install requests
```

## The Script

One script does everything:
```
$SKILL_DIR/scripts/whale_scanner.py
```

## Commands

### Scan top traders (most profitable)
```bash
python3 $SKILL_DIR/scripts/whale_scanner.py top 20
```
Returns the top 20 leaderboard wallets (by all-time PnL) that have open positions, with every position listed.

### Scan rekt traders (actively losing money)
```bash
python3 $SKILL_DIR/scripts/whale_scanner.py rekt 20
```
Returns 20 wallets with the worst monthly PnL that still have $1k+ accounts and open positions. These are traders actively losing money right now.

### Scan both (the full picture)
```bash
python3 $SKILL_DIR/scripts/whale_scanner.py both 20
```
Returns top AND rekt wallets with full analysis. This is the default command for most questions.

### Check a specific wallet
```bash
python3 $SKILL_DIR/scripts/whale_scanner.py wallet 0x1234...
```

## How to Read the Output

The JSON output has `top_traders` and `rekt_traders` sections. Each contains:

- **wallets**: list of wallets with address, PnL (daily/weekly/monthly/all-time), and all open positions (coin, direction, size, leverage, unrealized PnL)
- **analysis**: aggregated coin breakdown showing how many traders are LONG vs SHORT on each coin, with percentages

## Presenting Results to the User

After running the scan, give a clean plain-English summary. Focus on:

1. **The headline** -- "X out of 20 top traders are long ETH, Y are short"
2. **Strong consensus coins** -- where 70%+ of top traders agree on direction
3. **Contrarian signals** -- where top and rekt traders are doing the OPPOSITE (most valuable insight)
4. **100% agreement** -- any coin where ALL top traders are long or ALL are short
5. **Size matters** -- mention when a trader has an unusually large position

### Example Summary Format

```
SMART MONEY (Top 20 by all-time PnL):
  SOL: 10 long, 2 short (83% bullish)
  BTC: 9 long, 4 short (69% bullish)
  ETH: 7 long, 10 short (59% bearish)

REKT MONEY (Worst monthly PnL, still active):
  SOL: 3 long, 12 short (80% bearish)
  BTC: 5 long, 8 short (62% bearish)
  ETH: 11 long, 4 short (73% bullish)

CONTRARIAN SIGNALS (smart money vs rekt money disagree):
  SOL -- Smart money 83% long, rekt money 80% short. Strong bull signal.
  ETH -- Smart money 59% short, rekt money 73% long. Lean bearish.
```

## Answering Common Questions

| User asks | What to do |
|-----------|-----------|
| "What are whales doing?" | Run `both 20`, summarize top traders |
| "Should I long or short ETH?" | Run `both 20`, compare top vs rekt on ETH |
| "Who should I follow?" | Run `top 20`, show wallets with highest PnL |
| "Give me a trade idea" | Run `both 20`, find strongest contrarian signal |
| "What's the riskiest trade?" | Run `both 20`, find where top AND rekt agree (crowded = risky) |
| "Check this wallet: 0x..." | Run `wallet 0x...`, show their positions |

## Important Notes

- The leaderboard has ~33,000 wallets. Many top wallets use vaults/sub-accounts so their main address may show no positions. The script automatically scans extra wallets to find ones with real positions.
- Data is real-time from Hyperliquid's public API. No API key needed.
- This is read-only analysis. The script never places trades.
- Always remind the user this is data, not financial advice.
