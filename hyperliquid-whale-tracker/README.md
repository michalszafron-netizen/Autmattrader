# Hyperliquid Whale Tracker

A Claude Code skill that scans 33,000+ Hyperliquid wallets to show you what the smartest traders are buying -- and what the biggest losers are doing wrong.

Ask Claude things like:
- "What are the top Hyperliquid whales doing right now?"
- "Are smart money traders long or short on ETH?"
- "Give me a trade idea based on whale positions"
- "What are the most rekt traders positioned in?"

No API keys. No paid services. 100% free public Hyperliquid data.

## How It Works

1. Pulls the full Hyperliquid leaderboard (~33,000 traders)
2. Finds the most profitable wallets with open positions
3. Finds the worst-performing active wallets (by monthly PnL)
4. Queries each wallet's live positions (long/short, size, leverage, PnL)
5. Aggregates everything into a smart money vs rekt money breakdown

## Install

### Option 1: Clone into your project

```bash
git clone https://github.com/YOUR_USERNAME/hyperliquid-whale-tracker.git
cd hyperliquid-whale-tracker
pip install requests
```

Then copy the `.claude/` folder into your project root:

```bash
cp -r .claude/ /path/to/your/project/.claude/
```

### Option 2: Add directly to any Claude Code project

Copy the skill folder into your project's `.claude/skills/` directory:

```bash
mkdir -p your-project/.claude/skills/
cp -r .claude/skills/hyperliquid-whale-tracker your-project/.claude/skills/
```

Install the dependency:

```bash
pip install requests
```

That's it. Claude Code will automatically detect and use the skill.

## Usage

### With Claude Code (recommended)

Just ask Claude naturally:

```
> What are the top Hyperliquid whales doing right now?
> Should I long or short SOL based on whale positions?
> Check wallet 0x023a3d058020fb76cca98f01b3c48c8938a22355
```

### Standalone (command line)

```bash
# Top 20 most profitable traders + their positions
python3 .claude/skills/hyperliquid-whale-tracker/scripts/whale_scanner.py top 20

# 20 worst-performing active traders + their positions
python3 .claude/skills/hyperliquid-whale-tracker/scripts/whale_scanner.py rekt 20

# Both top and rekt side by side (full analysis)
python3 .claude/skills/hyperliquid-whale-tracker/scripts/whale_scanner.py both 20

# Check a specific wallet
python3 .claude/skills/hyperliquid-whale-tracker/scripts/whale_scanner.py wallet 0x...
```

## What You Get

### Smart Money vs Rekt Money Breakdown

```
SMART MONEY (Top 20 by all-time PnL):
  SOL: 10 long, 2 short (83% bullish)
  BTC: 9 long, 4 short (69% bullish)
  ETH: 7 long, 10 short (59% bearish)

REKT MONEY (Worst monthly PnL, still active):
  SOL: 3 long, 12 short (80% bearish)
  BTC: 5 long, 8 short (62% bearish)
  ETH: 11 long, 4 short (73% bullish)

CONTRARIAN SIGNALS:
  SOL -- Smart money 83% long, rekt 80% short = Strong bull signal
```

### Per-Wallet Details

Each wallet shows: address, display name, PnL (daily/weekly/monthly/all-time), account value, and every open position with coin, direction, size, entry price, leverage, and unrealized PnL.

## Data Sources

All data comes from Hyperliquid's free public APIs:

- **Leaderboard**: `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`
- **Wallet positions**: `https://api.hyperliquid.xyz/info` (clearinghouseState)

No API keys required. No rate limits hit at normal usage.

## Requirements

- Python 3.8+
- `requests` library
- Claude Code (for skill integration)

## License

MIT

## Disclaimer

This tool provides data analysis only. It does not place trades or provide financial advice. Past performance of tracked wallets does not guarantee future results. Always do your own research.
