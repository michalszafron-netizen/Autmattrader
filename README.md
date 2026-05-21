# trading-ai

Personal AI-augmented trading stack. Hyperliquid + Bybit + Alpaca, driven by Claude Code.

## Why this folder exists separately from `tradingview/`

- `C:\Users\markowyy\tradingview\` — research artifacts: Pine scripts, market reports, eksperymenty.
- `C:\Users\markowyy\trading-ai\` — production code: bot, agents, dashboard, deploy scripts.

Granica jest celowa. Bota można spakować i wysłać na VPS bez wlokania research'u.
TradingView MCP (78 narzędzi) jest dostępny w obu folderach przez user-scope config.

## Stack

| Warstwa | Tool | Status |
|---|---|---|
| Brain | Claude Code + OpenRouter (sonnet 4.6 / opus 4.7 / haiku 4.5) | TODO |
| Charts | TradingView MCP (78 tools, user-scope) | DONE — działa z tego folderu |
| Whales | Hyperliquid Whale Tracker skill | TODO |
| News | Firecrawl MCP (optional) | TODO |
| Execution: DEX perp | Hyperliquid (agent wallet, non-custodial) | TODO |
| Execution: CEX perp | Bybit International via CCXT | TODO |
| Execution: US stocks | Alpaca paper → live | TODO |
| Risk Guardian | Haiku 4.5 (separate agent, JSON contract) | TODO |
| Control plane | Telegram bot | TODO |
| Schedule | Claude Routines | TODO |
| Deploy | VPS (Ubuntu 24.04, systemd) | TODO |
| Dashboard | Vanilla HTML/JS served from VPS | TODO |

Explicitly **NOT** in stack: WEEX (no edge vs HL+Bybit, weak reputation), Interactive Brokers (no use case yet).

## Plan modułów

1. Setup workstation (venv, deps) — Python 3.12+, Node, Git ✅ already installed
2. Claude Code + OpenRouter — fallback aggregator
3. TradingView MCP → user scope ✅ done
4. Hyperliquid Whale Tracker — read-only, no keys
5. Firecrawl MCP — opcjonalne
6. Alpaca paper — US stocks via MCP
7. Hyperliquid SDK — Python, agent wallet only
8. Bybit via CCXT — fallback dla altów
9. Daily Alpha Brief — master prompt + slash command
10. Pine Script lab — generator + backtester przez TV MCP
11. TV webhook → ngrok → Flask → Hyperliquid execution
12. Risk Guardian — Haiku 4.5, approve/reject only
13. Telegram bot — human-in-the-loop
14. Claude Routines — scheduled daily brief + whale alerts
15. VPS — Ubuntu 24.04, systemd, journalctl
16. Live ops dashboard — HTML + vanilla JS

## Hard rules

- **Paper first.** Minimum 2 tygodnie clean paper logs przed go-live.
- **Agent wallets only.** Główny portfel HL nigdy nie dotyka kodu bota.
- **API keys with IP whitelist + NEVER withdraw permission.**
- **Daily kill switch:** strata >3% → flatten all, stop bot.
- **Heartbeat na Telegram:** cisza > 5 min = coś jest nie tak.
- **Human-in-the-loop dla live tradów dopóki paper nie dowiedzie inaczej.**

## Setup (zaktualizujemy gdy zaczniemy moduł 2)

```powershell
# Activate venv (assumed already created)
.venv\Scripts\activate

# Install deps (when requirements.txt exists)
pip install -r requirements.txt

# Copy env template
copy .env.example .env
# Edit .env with real values
```
