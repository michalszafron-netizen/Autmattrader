# trading-ai — Personal AI Trading Stack

AI-augmented trading stack. Hyperliquid + Extended Exchange + Alpaca + Solana, driven by Claude Code + Hermes + Telegram.

---

## 🧠 DWA MÓZGI, DWA KANAŁY TELEGRAM — jak to działa

To jest najważniejsza rzecz do zrozumienia w całym projekcie:

```
┌─────────────────────────────────────────────────────────────────┐
│  BOT 1: CLAUDE CODE  (@Twój_główny_bot)                         │
│  Token: 8900931551:AAEhUreBmDoe...                              │
│  Uruchomienie: tgtrade                                          │
│                                                                 │
│  DO CZEGO:                                                      │
│  ✅ /daily-alpha — pełna analiza rynku (najważniejsza komenda)  │
│  ✅ /raport — rysowanie poziomów na TradingView                 │
│  ✅ Analiza tokenów, whale scan, COT, sentiment                 │
│  ✅ Składanie zleceń na HL / Extended (z Twoją zgodą)          │
│  ✅ Swappy na Solana przez Jupiter                              │
│  ✅ Wszystko co wymaga zaawansowanego rozumowania               │
│  ✅ Wszystkie skrypty z folderu trading-ai/scripts/             │
│                                                                 │
│  KIEDY DZIAŁA: tylko gdy uruchomisz tgtrade w PowerShell        │
│  MODEL: Claude Sonnet 4.6 (Anthropic)                           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  BOT 2: HERMES  (@markowyy_hermes_bot lub jak nazwałeś)         │
│  Token: 8449812336:AAGW2_I6s8k0O3z...                          │
│  Uruchomienie: automatycznie (Scheduled Task przy starcie PC)   │
│                                                                 │
│  DO CZEGO:                                                      │
│  ✅ Pamięć długoterminowa — pamięta WSZYSTKO między sesjami     │
│  ✅ Trade journal — zapisuje wzorce w Twoich transakcjach       │
│  ✅ Skill generation — uczy się nowych umiejętności sam         │
│  ✅ Szybkie pytania gdy Claude Code nie jest uruchomiony        │
│  ✅ Automatyczne zadania cron (przyszłość)                      │
│  ✅ Działanie 24/7 bez potrzeby ręcznego uruchamiania           │
│                                                                 │
│  KIEDY DZIAŁA: zawsze (nawet gdy śpisz, bez tgtrade)            │
│  MODEL: DeepSeek V4 Flash (bezpośrednio, ~$0.14/1M tokenów)    │
└─────────────────────────────────────────────────────────────────┘
```

### Kiedy używać którego?

| Sytuacja | Którego bota? |
|---|---|
| Chcę daily alpha brief | **Claude** (`tgtrade` → `/daily-alpha`) |
| Chcę narysować poziomy na TV | **Claude** (`tgtrade` → `/raport BTC`) |
| Chcę złożyć zlecenie | **Claude** (ma dostęp do skryptów) |
| Chcę zrobić swap na Solana | **Claude** |
| Mam szybkie pytanie o rynek (w środku nocy) | **Hermes** (działa 24/7) |
| Chcę wiedzieć co robiłem tydzień temu | **Hermes** (pamięć długoterminowa) |
| Analiza wzorców w moich tradach | **Hermes** (journal + skill generation) |

---

## 🚀 Szybki start — jak uruchomić

### Wariant A: Pełna sesja tradingowa (Claude + Telegram)

```powershell
tgtrade
```

Startuje: Claude Code + Telegram + keepalive + daemony w tle

### Wariant B: Tylko lokalnie (bez Telegram)

```powershell
trade
```

### Wariant C: Uruchom daemony (skanery w tle)

```powershell
bots
```

Otwiera 3 okna CMD w tle:
- Volume Scanner (co 1h)
- Smart Money Tracker (co 1h)
- Listings Scanner (co 6h)

### Hermes działa automatycznie

Hermes startuje sam przy każdym uruchomieniu Windows (Scheduled Task). Nie musisz nic robić. Możesz pisać do `@markowyy_hermes_bot` w każdej chwili.

Jeśli Hermes nie odpowiada:
```powershell
hermes gateway start
```

---

## ⌨️ Aliasy PowerShell

| Komenda | Co robi |
|---|---|
| `tgtrade` | Claude Code + Telegram + keepalive + daemony (główny tryb) |
| `trade` | Claude Code lokalnie w trading-ai |
| `tg` | Claude Code + Telegram z aktualnego folderu |
| `bots` | Start 3 demonów (volume + smart_money + listings) |
| `daemons` | To samo co `bots` |
| `raport` | Podgląd najnowszego raportu dziś w terminalu |
| `raport v2` | Konkretna wersja raportu |
| `hermes` | Otwórz Hermesa w terminalu (TUI) |
| `hermes gateway start/stop` | Zarządzaj bramką Telegram Hermesa |

Plik profilu: `C:\Users\markowyy\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`

---

## 📊 Stack — pełny stan

| Warstwa | Narzędzie | Status | Uwagi |
|---|---|---|---|
| **Brain 1** | Claude Code (Sonnet 4.6) | ✅ | Główny mózg, analiza, zlecenia |
| **Brain 2** | Hermes Agent (DeepSeek V4 Flash) | ✅ | Pamięć, journal, 24/7 |
| **Telegram 1** | Claude Plugins channel | ✅ | `tgtrade` → główny bot |
| **Telegram 2** | Hermes Gateway | ✅ | Automatyczny, zawsze online |
| **Charts** | TradingView MCP (78 narzędzi) | ✅ | Wykresy, wskaźniki, Pine Script |
| **DEX 1** | Hyperliquid (agent wallet) | ✅ LIVE | Crypto perps + 78 TradFi (xyz) |
| **DEX 2** | Extended Exchange (StarkNet) | ✅ LIVE | 115 rynków, ex-Revolut team |
| **DEX 3** | Solana / Jupiter DEX | ✅ LIVE | Bot wallet: $11 (~AEbGdS6...) |
| **Stocks** | Alpaca paper trading | ✅ PAPER | US akcje, paper only |
| **Prices** | Hyperliquid xyz (allMids) | ✅ | Gold, Silver, Oil, SP500, DXY... |
| **News** | Firecrawl (coindesk/reuters/theblock) | ✅ | 3 kredyty/run, 1000/miesiąc |
| **X Sentiment** | Grok xAI live search | ✅ | 15 aktywów, BTC do COCOA |
| **Whale Tracker** | HL leaderboard top 20 | ✅ | Weekly + daily divergence |
| **Smart Money** | smart_money_tracker.py (daemon 1h) | ✅ | Nowe pozycje >$50k, konsensusy |
| **Listings** | listings_scanner.py (daemon 6h) | ✅ | Binance/Bybit/Coinbase/Upbit/OKX |
| **Volume Scan** | volume_scanner.py (daemon 1h) | ✅ | Anomalie 3x+ Binance Futures+Spot |
| **COT** | CFTC tygodniowy | ✅ | Gold, Silver, Oil, SP500, Nasdaq... |
| **Econ Calendar** | FinnHub API | ✅ | Z wpływem na 5 aktywów bazowych |
| **Polymarket** | Public API | ✅ | Fed, BTC, Iran, geopolityka |
| **Fear & Greed** | Alternative.me | ✅ | Trend 5-dniowy w --brief |
| **Open Interest** | Binance + Bybit + Extended | ✅ | Aggregate + trend + funding |
| **Token Research** | CoinGecko + DexScreener + GoPlus + Grok | ✅ | EVM + Solana |
| **Token Dashboard** | token_dashboard.py | ✅ | Composite score 0-10 z etykietą |
| **Database** | SQLite lokalnie | ✅ | Historia briefów, OI, F&G, trendy |
| **Repo** | github.com/michalszafron-netizen/Autmattrader | ✅ | |

---

## 📁 Skrypty — kompletna lista

### Dane rynkowe

| Skrypt | Komenda | Co robi |
|---|---|---|
| `quotes.py` | `python scripts/quotes.py --brief` | Live TradFi: Gold/Silver/Oil/SP500/VIX/DXY/NVDA |
| `fear_greed.py` | `python scripts/fear_greed.py --brief` | Fear & Greed + trend 5d (`28→25→27→29→28 →`) |
| `fear_greed.py` | `python scripts/fear_greed.py --days 7` | Historia 7 dni z wykresem |
| `oi_tracker.py` | `python scripts/oi_tracker.py --brief` | OI: Binance+Bybit+Extended per coin |
| `oi_tracker.py` | `python scripts/oi_tracker.py --trend --save` | OI trend + zapis do DB |
| `token_dashboard.py` | `python scripts/token_dashboard.py` | Kafelki BTC/ETH/SOL/HYPE/LINK ze score |
| `token_dashboard.py` | `python scripts/token_dashboard.py --save` | Dashboard + zapis do DB |
| `macro_news.py` | `python scripts/macro_news.py --source coindesk` | Newsy crypto (1 kredyt) |
| `macro_news.py` | `python scripts/macro_news.py --category alpha` | coindesk + theblock + reuters (3 kredyty) |
| `econ_calendar.py` | `python scripts/econ_calendar.py` | Pełny kalendarz dziś |
| `econ_calendar.py` | `python scripts/econ_calendar.py --upcoming` | Tylko nadchodzące dziś |
| `polymarket.py` | `python scripts/polymarket.py --brief` | Prediction markets (Fed, BTC, Iran...) |
| `cot_tracker.py` | `python scripts/cot_tracker.py --brief` | COT CFTC — percentyle 3-letnie |
| `x_sentiment.py` | `python scripts/x_sentiment.py sentiment --group all` | X sentiment: 15 aktywów |
| `x_sentiment.py` | `python scripts/x_sentiment.py trending` | Trending tokeny live Grok |

### Giełdy — pozycje i zlecenia

| Skrypt | Komenda | Co robi |
|---|---|---|
| `hl_executor.py` | `python scripts/hl_executor.py positions` | Pozycje HL (crypto + xyz TradFi) |
| `hl_executor.py` | `python scripts/hl_executor.py orders` | Wszystkie zlecenia HL (TP/SL/limit/trigger) |
| `hl_executor.py` | `python scripts/hl_executor.py quote SILVER` | Live cena z HL |
| `hl_executor.py` | `python scripts/hl_executor.py tickers --xyz` | 78 xyz TradFi instrumentów |
| `extended_executor.py` | `python scripts/extended_executor.py positions` | Pozycje Extended (StarkNet DEX) |
| `extended_executor.py` | `python scripts/extended_executor.py balance` | Equity, margin, health% Extended |
| `extended_executor.py` | `python scripts/extended_executor.py orders` | Zlecenia TPSL Extended |
| `alpaca_executor.py` | `python scripts/alpaca_executor.py positions` | Pozycje Alpaca paper |
| `solana_executor.py` | `python scripts/solana_executor.py balance` | SOL balance bot wallet |
| `solana_executor.py` | `python scripts/solana_executor.py tokens` | SPL tokeny w bot wallet |
| `solana_executor.py` | `python scripts/solana_executor.py swap SOL USDC 0.01 --yes` | Swap przez Jupiter DEX (bez potwierdzenia) |
| `solana_executor.py` | `python scripts/solana_executor.py price BONK` | Cena tokena z Jupiter |
| `hl_whale_tracker.py` | `python scripts/hl_whale_tracker.py whales --top 20 --window week` | Whale aggregate weekly |
| `hl_whale_tracker.py` | `python scripts/hl_whale_tracker.py whales --top 20 --window day` | Whale aggregate daily |

### Daemony (działają w tle 24/7)

| Skrypt | Interwał | Co robi | Alert na Telegram gdy |
|---|---|---|---|
| `volume_scanner.py` | 1h | Anomalie wolumenu Binance Futures+Spot | Volume > 3x średnia 30d |
| `smart_money_tracker.py` | 1h | Top 20 HL traderów pozycje | Nowa pozycja >$50k, konsensus 3+ traderów |
| `listings_scanner.py` | 6h | Nowe listingi na 5 giełdach | Nowy token na Binance/Bybit/Coinbase/Upbit/OKX |

Start: `bots` w PowerShell

### Analiza, kalkulator, baza

| Skrypt | Komenda | Co robi |
|---|---|---|
| `position_calc.py` | `python scripts/position_calc.py risk SILVER long --risk-pct 2 --entry 75.62 --sl-pct 4` | Kalkulator rozmiaru pozycji |
| `token_research.py` | `python scripts/token_research.py 0x123...` | Deep research tokena EVM/Solana |
| `db.py` | `python scripts/db.py stats` | Stan bazy danych |
| `db.py` | `python scripts/db.py context-daily` | Poprzednie daily briefs (dla Claude) |
| `db.py` | `python scripts/db.py context-trending` | Historia trending tokenów |

---

## 💬 Komendy przez Telegram (Claude — główny bot)

| Komenda | Co robi |
|---|---|
| `/daily-alpha` | Pełna analiza: MY BOOK + OI + WHALE + COT + CHART + SENTIMENT + ECON + EXPERT VIEW |
| `/raport` | Analiza 6 instrumentów na TradingView + rysowanie poziomów |
| `/raport BTC` | Analiza + poziomy tylko dla BTC |
| `/raport clean` | Usuń rysunki ze wszystkich wykresów |
| `pokaż pozycje` | HL + Extended + Alpaca + Solana |
| `zrób research tokena [CA]` | Deep dive: bezpieczeństwo, liquidity, holders |
| `jakie tokeny są hot na X?` | Trending scan Grok live |
| `kalendarz na dziś` | Econ calendar z wpływem na BTC/Gold/Silver/Oil/Nasdaq |
| `jaki jest fear and greed?` | F&G + trend 5d |
| `kup [X] USDC na Solana` | Swap SOL → USDC przez Jupiter |

---

## 🔔 Composite Score — co oznacza

Każdy token w Token Dashboard ma score 0-10:

| Score | Etykieta | Co to znaczy |
|---|---|---|
| 7.5–10 | 🟢 LONG SETUP | Wszystkie sygnały aligned bullish — szukaj wejścia long |
| 6.0–7.4 | 🟢 LEKKO BYCZO | Przewaga bullish, ale nie pełny alignment |
| 5.0–5.9 | 🟡 MIXED / CZEKAJ | Sprzeczne sygnały — brak edge, czekaj |
| 3.5–4.9 | 🔴 LEKKO NIEDŹWIEDZI | Przewaga niedźwiedzia — uważaj z longiem |
| 0–3.4 | 🔴 SHORT BIAS | Silny sygnał spadkowy — unikaj longa |

Score łączy: trend H4/H1/M15 + Smart Money bias + OI/price action + funding rate + X sentiment.

---

## 📰 ECON CALENDAR — format w daily brief

### ✅ Opublikowane (dane już wyszły)
Podaje: wynik vs oczekiwania + werdykt (MOCNE/SŁABE/ZGODNE) + rzeczywisty wpływ na BTC/Gold/Silver/Oil/Nasdaq + impact na otwarte pozycje. **Bez scenariuszy** — dane wyszły, piszemy co to ZNACZY.

### ⏳ Nadchodzące (dane jeszcze nie wyszły)
Podaje: godzinę, ważność, estymaty + **dwa scenariusze** (jeśli WYŻSZE / jeśli NIŻSZE) dla BTC/Gold/Silver/Oil/Nasdaq + otwartych pozycji.

---

## 🔐 Giełdy — szczegóły

### Hyperliquid (HL)
- **Typ:** DEX perpetuals (onchain, EVM signed)
- **Instrumenty:** 230+ crypto perps + 78 xyz TradFi (Gold, Silver, Oil, SP500, Nasdaq, NVDA, TSLA...)
- **Klucz:** Agent wallet — delegowany, **bez uprawnień do wypłat** (built-in bezpieczeństwo)
- **Tryb:** `HL_TRADING_MODE=live`

### Extended Exchange
- **Typ:** DEX perpetuals (StarkNet, ZK rollup na Ethereum)
- **Zespół:** ex-Revolut (CEO: Head of Crypto Ops Revolut + McKinsey)
- **Instrumenty:** 115 rynków: crypto + Gold, Silver, Oil, SP500, Nasdaq, akcje US
- **Vault:** 214869 | Client ID: 114295

### Solana / Jupiter DEX
- **Bot wallet:** `AEbGdS6BmT9yKBJGsHMxDneQT8aUv5JXgtVWD7AUMoGq`
- **Saldo:** ~$11 (testowe — nie ładuj więcej niż $50)
- **RPC:** Helius primary → Ankr → public fallback
- **DEX:** Jupiter aggregator — najlepsza cena ze wszystkich Solana DEXów
- **Automatyzacja:** `--yes` flag omija potwierdzenie (dla automatycznych swapów)
- **WAŻNE:** To jest dedykowany bot wallet — **nigdy nie używaj głównego portfela**

### Alpaca
- **Typ:** US stocks, paper trading
- **Tryb:** `ALPACA_PAPER=true` — wszystkie zlecenia papierowe (wirtualne pieniądze)

---

## 🗄️ Baza danych (SQLite)

Plik: `data/trading.db` (gitignored)

| Tabela | Co przechowuje |
|---|---|
| `daily_briefs` | Historia wszystkich daily alpha briefów (dla kontekstu) |
| `fear_greed_history` | Historia Fear & Greed — trend wielotygodniowy |
| `oi_snapshots` | Snapshots Open Interest per coin per godzina |
| `token_snapshots` | Token dashboard dane historyczne |
| `sm_snapshots` | Smart money snapshots (top 20 traderów) |
| `sm_alerts` | Historia alertów smart money |
| `listing_announcements` | Historia skanowanych listingów (baseline delta) |
| `volume_anomalies` | Zarejestrowane anomalie wolumenu |
| `trending_tokens` | Historia trending tokenów z X |
| `token_research` | Wyniki deep research tokenów |

---

## 🧰 Źródła cen — zasada rozdzielenia

| Kontekst | Źródło | Dlaczego |
|---|---|---|
| Analizy, raporty, OI, quotes | **Hyperliquid xyz** (`quotes.py`) | Live, bez opóźnień, jeden call zwraca wszystko |
| Rysowanie poziomów na TV | **TradingView** `quote_get()` | Spójne z tym co widzisz na wykresie |
| **NIGDY** | ETF proxy (GLD, SLV, USO) | GLD ≠ cena złota w USD/oz (błąd 10x) |

---

## 🏗️ Struktura folderów

```
trading-ai/
├── scripts/
│   ├── quotes.py              # live ceny TradFi (HL xyz allMids)
│   ├── oi_tracker.py          # Open Interest agregat
│   ├── hl_executor.py         # Hyperliquid execution
│   ├── extended_executor.py   # Extended Exchange (StarkNet DEX)
│   ├── alpaca_executor.py     # Alpaca paper US stocks
│   ├── solana_executor.py     # Solana / Jupiter DEX swaps
│   ├── hl_whale_tracker.py    # whale positions agregat
│   ├── smart_money_tracker.py # daemon: top 20 HL traderzy co 1h
│   ├── listings_scanner.py    # daemon: nowe listingi co 6h
│   ├── volume_scanner.py      # daemon: anomalie wolumenu co 1h
│   ├── token_dashboard.py     # dashboard per token (composite score)
│   ├── x_sentiment.py         # X sentiment przez Grok xAI
│   ├── macro_news.py          # newsy Firecrawl
│   ├── econ_calendar.py       # kalendarz FinnHub z wpływem
│   ├── cot_tracker.py         # COT CFTC instytucje
│   ├── fear_greed.py          # Fear & Greed + trend 5d
│   ├── polymarket.py          # prediction markets
│   ├── token_research.py      # deep token research EVM/Solana
│   ├── position_calc.py       # kalkulator wielkości pozycji
│   ├── db.py                  # SQLite baza danych
│   ├── tz_utils.py            # UTC → CET/CEST konwersja
│   ├── start_daemons.bat      # launcher 3 demonów (bots/daemons alias)
│   ├── run_volume.bat         # launcher tylko volume scanner
│   ├── run_smart_money.bat    # launcher tylko smart money
│   ├── run_listings.bat       # launcher tylko listings scanner
│   └── keepalive.ps1          # Windows anti-sleep
├── docs/
│   ├── hl_prompts.md          # lista komend HL
│   └── roadmap.md             # plan dalszego rozwoju
├── reports/                   # auto-generowane raporty (gitignored)
├── data/                      # SQLite DB (gitignored)
├── .env                       # klucze API (gitignored!)
├── .hermes.md                 # kontekst projektu dla Hermesa
├── CLAUDE.md                  # instrukcje dla Claude Code
└── README.md                  # ten plik
```

---

## 🔑 Klucze API — przegląd

| Serwis | Zmienna w .env | Limit | Do czego |
|---|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | pay-per-use | Claude Code (główny mózg) |
| DeepSeek | `DEEPSEEK_API_KEY` | pay-per-use | Hermes Agent ($0.14/1M tokenów) |
| OpenRouter | `OPENROUTER_API_KEY` | pay-per-use | Fallback dla Hermesa (300+ modeli) |
| xAI / Grok | `XAI_API_KEY` | pay-per-use | X sentiment live search |
| Firecrawl | `FIRECRAWL_API_KEY` | 1000 stron/mies | Scraping newsów |
| FinnHub | `FINNHUB_API_KEY` | 60 req/min | Kalendarz ekonomiczny |
| Etherscan V2 | `ETHERSCAN_API_KEY` | 100k calls/dzień | Token research EVM |
| Helius | `HELIUS_API_KEY` | 100k credits/mies | Solana RPC + token data |
| Birdeye | `BIRDEYE_API_KEY` | 1k req/dzień | Solana DeFi data |
| Alpaca | `ALPACA_API_KEY/SECRET` | — | Paper trading US stocks |
| Senpi | `SENPI_AUTH_TOKEN` | — | Hyperliquid MCP (78 narzędzi) |

---

## ⚠️ Zasady bezpieczeństwa

1. **`.env` jest w `.gitignore`** — nigdy nie commituj kluczy
2. **Hyperliquid:** agent wallet bez uprawnień wypłat — nawet jak bot się pomyli, nie może opróżnić głównego konta
3. **Solana:** bot wallet tylko z $50 testowymi — nigdy główny portfel (ten jest na hardware wallet)
4. **Alpaca:** `ALPACA_PAPER=true` zawsze — live wymaga świadomej decyzji
5. **Risk per trade:** max 2% | Portfolio risk: max 6% | Kill switch przy -3% dziennie
6. **Extended Stark Key Private** — nigdy nikomu nie wysyłaj, nie wpisuj w kod
7. **Klucze w chacie:** jeśli przypadkowo wkleisz klucz w chat — natychmiast zrotuj go na dashboardzie dostawcy

---

## 🩺 Rozwiązywanie problemów

| Problem | Rozwiązanie |
|---|---|
| Bot nie odpowiada na Telegram (Claude) | Uruchom `tgtrade` od nowa |
| Hermes nie odpowiada | `hermes gateway stop` → `hermes gateway start` |
| Hermes odpowiada po angielsku | Napisz "odpowiadaj po polsku" — zapamięta na przyszłość |
| "Provider authentication failed" w Hermesie | Sprawdź `%LOCALAPPDATA%\hermes\.env` — klucz DEEPSEEK_API_KEY |
| Telegram polling conflict | Dwa boty używają tego samego tokena — sprawdź czy Hermes ma SWÓJ token |
| `ModuleNotFoundError` | Nie aktywowano venv — użyj `.venv\Scripts\python.exe` bezpośrednio |
| PowerShell nie zna aliasów | `. $PROFILE` lub otwórz nowy terminal |
| Ceny wyglądają dziwnie | Sprawdź czy nie używasz ETF proxy zamiast `quotes.py` |
| SSL error | `$env:NODE_TLS_REJECT_UNAUTHORIZED="0"` — już jest w profilu, otwórz nowy terminal |
| Daemony przestały działać | `bots` w PowerShell — startuje 3 okna CMD |
| Daily brief nadpisał poprzedni | Nie powinien — CLAUDE.md ma regułę wersjonowania (_v2, _v3...) |
| Raport nie widać w chacie | CLAUDE.md: MUST wyświetlić pełny brief w czacie (nie summary) |
| `hermes config edit` nie działa | Edytuj bezpośrednio: `%LOCALAPPDATA%\hermes\config.yaml` |

---

## 📅 Changelog

| Data | Co dodano |
|---|---|
| 2026-05-23 | **Hermes Agent** — pamięć długoterminowa, skill generation, drugi kanał Telegram |
| 2026-05-23 | **DeepSeek V4 Flash** jako model Hermesa ($0.14/1M tokenów) |
| 2026-05-22 | ECON CALENDAR — nowy format: published=werdykt, upcoming=scenariusze dla 5 aktywów |
| 2026-05-22 | Fear & Greed trend 5-dniowy w `--brief` |
| 2026-05-22 | Composite score z etykietą (LONG SETUP / MIXED / SHORT BIAS) |
| 2026-05-22 | Daily brief w chacie zawsze pełny (nie condensed summary) |
| 2026-05-21 | **Solana / Jupiter DEX** executor — swappy, balance, token prices |
| 2026-05-21 | **volume_scanner.py** — anomalie 3x+ Binance Futures+Spot (daemon 1h) |
| 2026-05-21 | **smart_money_tracker.py** — top 20 HL traderów (daemon 1h) |
| 2026-05-21 | **listings_scanner.py** — nowe listingi 5 giełd (daemon 6h) |
| 2026-05-21 | **start_daemons.bat** + aliasy `bots`/`daemons` |
| 2026-05-20 | **Extended Exchange** — StarkNet DEX, 4 pozycje, TPSL |
| 2026-05-20 | **token_dashboard.py** — composite score 0-10, kafelki per token |
| 2026-05-20 | **oi_tracker.py** — Open Interest Binance+Bybit+Extended |
| 2026-05-19 | **quotes.py** — live TradFi ceny z HL xyz (jeden call, wszystkie ceny) |
| 2026-05-19 | SQLite DB rozszerzona: OI, smart money, listings, volume, token snapshots |
| 2026-05-18 | Wersjonowanie raportów (_v2, _v3...) — nigdy nie nadpisuje |
