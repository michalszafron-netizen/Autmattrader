# trading-ai — Claude Code project instructions

This is a personal AI trading project. When working in this folder, follow these rules.

## Kontrakty tokenów — zasada obowiązkowa

Przy każdej analizie tokenów z X (trending, research, wzmianka w briefie):
- **ZAWSZE szukaj adresu kontraktu** dla każdego wymienionego tokena
- Ethereum/BSC/Base: adres zaczyna się od `0x...`
- Solana: adres base58 (44 znaki, np. z pump.fun lub DexScreener)
- TON: adres zaczyna się od `EQ...` lub `UQ...`
- Jeśli znaleziony — wyróżnij pogrubioną czcionką jako `Kontrakt: ADRES`
- Jeśli nie znaleziony — napisz gdzie szukać (DexScreener, pump.fun, Birdeye)
- Nigdy nie zostawiaj tokena bez kontraktu lub wskazówki jak go znaleźć

## Język raportów — styl edukacyjny (obowiązkowy)

**Wszystkie raporty, analizy i odpowiedzi dotyczące finansów MUSZĄ być pisane prostym, edukacyjnym językiem.**
Użytkownik uczy się finansów razem z danymi. Piszesz jak do znajomego który jest inteligentny ale nie zna żargonu finansowego.

### Zasady języka — BEZWYJĄTKOWE:

1. **Angielskie terminy finansowe — ZAWSZE przetłumacz i wyjaśnij.**
   Nie ma wyjątków. Każde angielskie słowo branżowe = tłumaczenie + wyjaśnienie co oznacza w praktyce.

2. **Zero żargonu bez wyjaśnienia.** Wyjaśnienie następuje W TYM SAMYM zdaniu, nie w osobnym.
   - Źle: "Dane są hawkish co wpłynie na yield curve"
   - Dobrze: "Dane pokazują że inflacja jest wyższa niż oczekiwano — to oznacza że Fed (bank centralny USA) prawdopodobnie nie obniży stóp procentowych (czyli kosztu kredytu) w najbliższym czasie. Droższy kredyt = mniej pieniędzy w obiegu = rynki spadają."

3. **Zawsze wyjaśnij CO TO ZNACZY dla zwykłego człowieka.** Nie tylko co wyszło, ale łańcuch przyczynowo-skutkowy.
   - Źle: "CPI YoY 3.4% vs est 3.1%, yield 10Y przebił 4.50%"
   - Dobrze: "Inflacja roczna wyniosła 3.4% zamiast oczekiwanych 3.1% — ceny w sklepach rosną szybciej niż myślano. Efekt: obligacje rządowe (papiery wartościowe które rząd sprzedaje żeby pożyczyć pieniądze) zaczęły się wyprzedawać, a ich rentowność (procent który rząd płaci za pożyczkę) skoczyła do 4.50% — historycznie wysoko."

4. **Zawsze podaj wpływ na WSZYSTKIE kluczowe aktywa:** BTC, Gold, Ropa, Akcje (SPX/Nasdaq), USD.

5. **Scenariusze opisuj w tabeli:** Scenariusz | Co to znaczy po ludzku | BTC | Gold | Ropa | Akcje | Nasdaq | USD

6. **Na końcu każdej analizy:** "Co z tym zrobić?" — obserwacja praktyczna.

### Słownik — te słowa ZAWSZE zamieniaj:

| Zamiast | Pisz |
|---|---|
| hawkish | "Fed martwi się inflacją i chce utrzymać wysokie stopy (drogi kredyt)" |
| dovish | "Fed sygnalizuje obniżki stóp — tanie pieniądze w drodze" |
| risk-off | "inwestorzy uciekają z ryzykownych aktywów (BTC, akcje) do bezpiecznych (złoto, USD)" |
| risk-on | "inwestorzy chętnie kupują ryzykowne aktywa (BTC, akcje rosną)" |
| yield | "rentowność obligacji (procent który rząd płaci za pożyczone pieniądze)" |
| rally | "wzrost ceny / odbicie w górę" |
| selloff | "nagła wyprzedaż / gwałtowny spadek" |
| minutes (Fed) | "protokół z posiedzenia Fed (szczegółowy zapis dyskusji)" |
| implied volatility | "oczekiwana zmienność ceny (jak bardzo rynek spodziewa się wahań)" |
| leverage | "lewar — inwestowanie pożyczonymi pieniędzmi, amplifikuje zyski i straty" |
| ETF | "fundusz inwestycyjny notowany na giełdzie — można go kupić jak akcję" |
| long | "pozycja zakładająca że cena wzrośnie (kupiłem, liczę na wzrost)" |
| short | "pozycja zakładająca że cena spadnie (pożyczyłem i sprzedałem, liczę na spadek)" |
| squeeze | "nagłe zamknięcie strat przez tych co grali na spadek — wywołuje gwałtowny wzrost ceny" |
| macro | "dane gospodarcze (inflacja, PKB, bezrobocie) wpływające na globalne rynki" |
| bullish | "nastawienie wzrostowe — ktoś wierzy że cena wzrośnie" |
| bearish | "nastawienie spadkowe — ktoś wierzy że cena spadnie" |
| spread | "różnica między ceną kupna a sprzedaży — zysk brokera lub market makera" |
| hedge | "zabezpieczenie pozycji — otwierasz drugą pozycję żeby ograniczyć straty na pierwszej" |
| liquidity | "płynność — jak łatwo kupić lub sprzedać bez zmiany ceny" |

## EXPERT VIEW — obowiązkowa sekcja końcowa każdego raportu

**Każdy raport (daily brief, analiza eventu, whale scan, COT) MUSI kończyć się sekcją EXPERT VIEW.**

Jesteś doświadczonym traderem i analitykiem rynkowym. Po zebraniu wszystkich danych — nie podsumowujesz, tylko **wyrażasz konkretną opinię** i dajesz **edge**.

### Format EXPERT VIEW:

```
## EXPERT VIEW

**Ogólny obraz rynku:** [Byczo / Niedźwiedzio / Neutralnie] — [pewność: niska/średnia/wysoka]
[2-3 zdania: co widzisz patrząc na WSZYSTKIE dane razem — nie po kolei, ale jako całość]

**Jedna najważniejsza rzecz na dziś:**
[Konkretna obserwacja — co jest najważniejszym czynnikiem teraz. Nie "watch CPI" — tylko "jeśli FOMC Minutes
pokażą X, to jest to sygnał do Y bo historycznie..."]

**Potencjalny game changer:**
[Co mogłoby wszystko zmienić w ciągu 24-48h — jeden scenariusz który mało kto rozważa]

**Największe ryzyko dla obecnej pozycji:**
[Co mogłoby uderzyć w otwarte pozycje — nie oczywiste rzeczy]

**Edge na dziś:**
[Konkretna przewaga informacyjna którą masz dzięki zebranym danym — czego większość retail traderów
nie widzi lub nie łączy w całość]

**Conviction:** [1-10] — [jednozdaniowe uzasadnienie]
```

### Zasady EXPERT VIEW:

- **Bądź konkretny.** Nie "rynek może wzrosnąć lub spaść" — tylko "dane wskazują na X, bo Y i Z zbiegają się"
- **Łącz dane** — whale bias + COT + Fear&Greed + econ calendar + X sentiment = jeden spójny obraz
- **Nie bój się mieć zdania.** Lepiej się mylić konkretnie niż być nijako poprawnym
- **Jeśli dane są sprzeczne** — powiedz to wprost: "whales są long ale COT mówi short — to jest setup niepewny, czekaj"
- **Game changer** = coś co zmienia wszystko, nie kolejny event. Przykład: "Iran deal może uderzyć w Oil -10% i zabrać tail risk z rynku"
- **Conviction 1-10**: 1=zgaduję, 5=ok dane, 8=mocne zbieżności, 10=wszystkie wskaźniki razem krzyczą to samo
- **Dotyczy WSZYSTKICH analiz bez wyjątku:** daily brief, whale scan, COT, econ calendar, trending tokens, fundamental analysis, chart read, każda inna analiza rynkowa

## Reporting Policy (wszystkie rutyny)

**Każdy output z rutyny MUSI być zapisany do pliku przed wysyłką na Telegram.**
Folder: `C:\Users\markowyy\trading-ai\reports\`

| Rutyna | Plik |
|---|---|
| Daily Alpha Brief | `reports/YYYY-MM-DD_daily_alpha.md` |
| Whale Alert | `reports/YYYY-MM-DD_HH-MM_whale_alert.md` |
| Risk Check | `reports/YYYY-MM-DD_HH-MM_risk_check.md` |

Jeśli output to "SKIP" lub "All clear" — też zapisz (1 linijka). Plik = kopia zapasowa gdy Telegram zawiedzie.
Timestamp format: `2026-05-20_08-30` — użyj aktualnej daty/godziny w nazwie pliku.

## Identity & venues

- Primary execution venue: **Hyperliquid** (perp DEX, on-chain, EVM-signed)
- Fallback CEX: **Bybit International** (via CCXT)
- US stocks: **Alpaca paper** (live only after explicit user confirmation)
- **WEEX is NOT used.** Do not suggest WEEX integration even if mentioned in tutorial files.
- **Interactive Brokers is NOT used.** Skip references to IB / TWS / ib_insync.

## Safety rules (hard, non-negotiable)

1. **Default mode is paper / dry-run.** Never place a live order unless `TRADING_MODE=live` in .env AND user has explicitly confirmed in chat.
2. **Hyperliquid main wallet private key MUST NEVER be in code or .env.** Only agent wallet keys (delegated, no-withdraw permission).
3. **Bybit API keys must have IP whitelist + read+trade only.** Reject any code that enables withdraw permission.
4. **Risk per trade ≤ 2%.** Portfolio open risk ≤ 6%. Daily loss > 3% → kill switch flattens all positions.
5. **Stop-loss is mandatory.** Every order must attach SL before being submitted.
6. **Heartbeat to Telegram every loop.** Silent bot = broken bot.

## Code style

- Python 3.12+, type hints required, pydantic for I/O models, loguru for structured logs.
- All exchange calls go through a thin adapter layer (so swapping HL ↔ Bybit is one import).
- Tests use pytest. No code goes live before unit tests pass.

## Where things live

- `src/` — bot code (strategies, risk, execution, adapters)
- `scripts/` — one-shot tooling (data dumps, backtests)
- `data/` — local DBs, parquet files, cache (gitignored)
- `logs/` — runtime logs (gitignored)
- `tests/` — pytest
- `docs/` — module write-ups as we ship them

## MCP available

- `tradingview` (78 tools) — user-scope, works from any folder
- More to be added: hyperliquid whale tracker, firecrawl, alpaca, telegram

## API Keys — przegląd

| Serwis | Klucz w .env | Limit | Do czego |
|---|---|---|---|
| Firecrawl | FIRECRAWL_API_KEY | 1000 stron/mies | Scraping news, whitepaper |
| xAI / Grok | XAI_API_KEY | pay-per-use | X sentiment, trending |
| FinnHub | FINNHUB_API_KEY | 60 req/min | Kalendarz ekonomiczny |
| **Etherscan V2** | **ETHERSCAN_API_KEY** | **100k calls/dzień, 5/sek** | **Source code + ABI. Free tier: ETH(1), BSC(56), Polygon(137), Arbitrum(42161), Optimism(10), Base(8453), Avalanche(43114), Gnosis(100), Linea(59144), Blast(81457). NIE działa: Fantom, Cronos, zkSync, Scroll** |
| **Helius** | **HELIUS_API_KEY** | **100k credits/mies** | **Solana: getAsset (metadata, price, supply), token accounts, NFT data. RPC endpoint: mainnet.helius-rpc.com** |
| **Birdeye** | **BIRDEYE_API_KEY** | **1k req/dzień** | **Solana DeFi: holders count, volume, buy/sell ratio, unique wallets, price history** |
| Alpaca | ALPACA_API_KEY | - | Paper trading US stocks |

## Quick Commands

Filled in as skills/integrations are installed. Each entry: short label + exact command.

### Hyperliquid (whale tracker, read-only)

Activate venv first (in any new shell):
```powershell
C:\Users\markowyy\trading-ai\.venv\Scripts\activate
```

Or call the venv python directly (no activation needed):
```powershell
$py = "C:\Users\markowyy\trading-ai\.venv\Scripts\python.exe"
$script = "C:\Users\markowyy\trading-ai\scripts\hl_whale_tracker.py"

# Top 20 traders by daily PnL
& $py $script leaderboard --top 20 --by pnl --window day

# Top 20 by weekly ROI
& $py $script leaderboard --top 20 --by roi --window week

# Positions for one wallet
& $py $script positions 0x4ec8fe22a09c0c1d96ec4d3d2f8b3e9f1a2b3c4d

# Aggregate net exposure across top 20 weekly traders
& $py $script whales --top 20 --window week

# Aggregate across top 50 — heavier (50 API calls)
& $py $script whales --top 50 --window week
```

Endpoints used (all public, no auth):
- `https://stats-data.hyperliquid.xyz/Mainnet/leaderboard` — top traders
- `https://api.hyperliquid.xyz/info` — per-wallet state (POST clearinghouseState)

### Hyperliquid (execution — agent wallet)

Covers: standard crypto perps (BTC, ETH, HYPE, SOL...) + HIP-3 xyz TradFi (SILVER, GOLD, BRENTOIL, SP500, NVDA, TSLA...).

HIP-3 formula: asset_index = 100000 + perp_dex_index(1) * 10000 + index_in_meta
xyz:SILVER = 110026, xyz:GOLD = 110003, xyz:BRENTOIL = 110049

```powershell
$py = "C:\Users\markowyy\trading-ai\.venv\Scripts\python.exe"
$hl = "C:\Users\markowyy\trading-ai\scripts\hl_executor.py"

# List all assets (77 xyz TradFi + 230 standard perps)
& $py $hl tickers
& $py $hl tickers --xyz        # xyz TradFi only

# Quote (works with short name: SILVER = xyz:SILVER auto-resolved)
& $py $hl quote SILVER
& $py $hl quote BTC

# Place limit order (PAPER MODE default — no real order unless TRADING_MODE=live)
& $py $hl order SILVER long 0.14 74.0
& $py $hl order BTC long 0.001 61000

# Cancel
& $py $hl cancel SILVER 432926143861

# Positions + open orders
& $py $hl positions
& $py $hl orders
```

Safety: TRADING_MODE=paper → dry-run only. Set TRADING_MODE=live in .env for real orders.

### Bybit (CCXT)
<!-- TODO: add after CCXT adapter scaffolded -->

### Firecrawl (macro & news)

```powershell
$py = "C:\Users\markowyy\trading-ai\.venv\Scripts\python.exe"
$script = "C:\Users\markowyy\trading-ai\scripts\macro_news.py"

# Daily brief default (3 credits): coindesk + reuters_world + kitco
& $py $script

# By category
& $py $script --category crypto       # coindesk + decrypt + theblock (3 credits)
& $py $script --category markets      # fed + reuters_markets + marketwatch (3)
& $py $script --category commodities  # kitco + oilprice (2)
& $py $script --category geo          # reuters_world + bbc_world (2)
& $py $script --category alpha        # coindesk + theblock + reuters_world (3) ← /daily-alpha preset

# All 10 sources (9 credits — use sparingly)
& $py $script --all

# Single source
& $py $script --source kitco          # gold/silver only
& $py $script --source reuters_world  # geopolitics only
& $py $script --source theblock       # crypto/DeFi — on-chain, institutional, regulatory
& $py $script --source oilprice       # oil/energy only
& $py $script --source fed            # Fed releases only

# Dry-run
& $py $script --dry-run --all
```

Sources (10 total):
  crypto:      coindesk, decrypt, theblock (on-chain/DeFi/institutional)
  markets:     fed, reuters_markets, marketwatch
  commodities: kitco (gold/silver), oilprice (crude/energy)
  geo:         reuters_world (geopolitics/wars), bbc_world (world events)

Budget guide:
  Alpha (daily): 3 credits × 30 = 90/month  → niski koszt
  Brief (daily): 3 credits × 30 = 90/month  → 910 credits remaining
  Full scan:     9 credits × 4/week = 144/month → still under 1000 limit

### X sentiment (Grok grok-4.3)

```powershell
$py = "C:\Users\markowyy\trading-ai\.venv\Scripts\python.exe"
$script = "C:\Users\markowyy\trading-ai\scripts\x_sentiment.py"

# Crypto: BTC ETH HYPE (default)
& $py $script sentiment

# Macro: Gold Silver Oil + Indices
& $py $script sentiment --group macro

# All assets (crypto + macro)
& $py $script sentiment --group all

# Custom mix
& $py $script sentiment --coins BTC XAU SPX DXY

# Discover trending new tokens on X (not top-20 mcap)
& $py $script trending

# With raw Grok response
& $py $script sentiment --coins HYPE --verbose
```

Asset groups:
  crypto: BTC ETH HYPE
  macro:  GOLD SILVER OIL SPX NDX DXY
  trending: autonomous query for hot new tokens + sector hotspots

Mode: Grok knowledge-based (REST, httpx + truststore).
TODO: switch to live X search via xai_sdk gRPC when on Linux VPS —
grpcio BoringSSL AIA-fetching issue on Windows. Live on VPS = real tweets.

### COT Report (CFTC — institutional positioning for TradFi)

```powershell
$py = "C:\Users\markowyy\trading-ai\.venv\Scripts\python.exe"
$cot = "C:\Users\markowyy\trading-ai\scripts\cot_tracker.py"

# All 6 assets (Gold, Silver, Oil, SP500, Nasdaq, Euro)
& $py $cot

# Single asset
& $py $cot --asset GOLD
& $py $cot --asset SP500

# One-liner for daily brief
& $py $cot --brief
```

Data: CFTC weekly (Tuesday data, Friday release). Free, no API key.
Percentile = how extreme is current positioning vs 3-year history.
Commercials = smart money for commodities. NonComm = trend followers for equities.

### Alpaca (paper trading — US stocks)

MCP server: `alpaca-paper` (Connected) — official alpacahq/alpaca-mcp-server v2.0.1
Paper account URL: https://paper-api.alpaca.markets

Tools available via MCP (use in conversation, no code needed):
- Get account balance and buying power
- Get open positions
- Place orders (market, limit, stop)
- Get portfolio history
- Search for stock symbols
- Get quotes and market data

Example prompts:
  "Check my Alpaca paper account balance and buying power"
  "What positions do I have open on Alpaca paper?"
  "Buy $100 of NVDA at market on Alpaca paper account"
  "Show my Alpaca paper P&L for the last week"

IMPORTANT: ALPACA_PAPER=true is set — all orders go to paper account.
Never change to live without explicit confirmation.

### Daily Alpha Brief

Trigger: `/daily-alpha`

Assets in scope (crypto): BTC, ETH, SOL, HYPE, LINK
Assets in scope (TradFi): GOLD, SILVER, USOIL
Assets in scope (Soft Commodities): CORN, COFFEE, COCOA, SUGAR

Steps Claude executes when you type this:

**PRE-STEP — CONTEXT (zawsze pierwsze, przed czymkolwiek)**
- Run: `python scripts/db.py context-daily`
- Wczytaj output jako KONTEKST HISTORYCZNY — zobaczysz co było napisane w poprzednich briefach
- Zasada: **nie powtarzaj obserwacji które się nie zmieniły**
  - Jeśli wczoraj pisałeś "short squeeze na Nasdaq" i dziś nadal jest — napisz "short squeeze na Nasdaq (trwa od X dni)" zamiast opisywać od nowa
  - Jeśli coś nowego zastąpiło poprzedni temat — wspomnij zmianę wprost: "poprzednio uwaga była na X, teraz dominuje Y"
  - Jeśli brak historii w DB (pierwsze uruchomienie) — pomiń i kontynuuj normalnie
- Run: `python scripts/db.py context-trending` — historia trending tokenów (użyj w STEP 5 i X SENTIMENT)

**STEP 0 — MY BOOK + MARKET PULSE (zawsze najpierw, równolegle)**
- Run: `python scripts/hl_executor.py positions` — otwarte pozycje HL, unrealized PnL
- Run: `python scripts/hl_executor.py orders` — WSZYSTKIE zlecenia HL: limity + TP + SL + trigger orders
- Run: `python scripts/alpaca_executor.py positions` — pozycje Alpaca paper (ZAWSZE pokaż: nawet "brak pozycji" + equity + buying power)
- Run: `python scripts/fear_greed.py --brief` — Crypto Fear & Greed Index
- Run: `python scripts/econ_calendar.py` — pełny kalendarz dziś: co już wyszło + EXPERT VIEW
- Run: `python scripts/econ_calendar.py --upcoming` — lista nadchodzących (jeszcze nie opublikowanych) eventów na dziś
- Run: `python scripts/econ_calendar.py --brief` — jedna linia skrót dla nagłówka
- Oblicz % wykorzystanego max ryzyka (max portfolio risk = 6%)

**STEP 0.5 — PREDICTION MARKETS (Polymarket, free, no key)**
- Run: `python scripts/polymarket.py --brief` — crowd consensus na Fed, BTC, Iran, Oil

**STEP 1 — MACRO PULSE (Firecrawl, ostatnie 12h)**
- Run: `python scripts/macro_news.py --source coindesk` (1 credit — crypto)
- Run: `python scripts/macro_news.py --source theblock` (1 credit — crypto/DeFi)
- Run: `python scripts/macro_news.py --source reuters_world` (1 credit — geopolityka)
- Wyciągnij 5 bulletów; oznacz co może ruszyć assets w ciągu 24h

**STEP 2 — WHALE READ (Hyperliquid)**
- Run: `python scripts/hl_whale_tracker.py whales --top 20 --window week`
- Run: `python scripts/hl_whale_tracker.py whales --top 20 --window day`
- Zidentyfikuj: najbardziej zatłoczony long, najbardziej zatłoczony short
- Porównaj weekly vs daily — gdzie wieloryby się nie zgadzają (rozbieżność = sygnał)

**STEP 3 — COT (CFTC, TradFi)**
- Run: `python scripts/cot_tracker.py --brief`

**STEP 4 — CHART READ (TV MCP, 4H per asset)**
Dla każdego asseta z listy (BTC, ETH, SOL, HYPE, LINK):
```
chart_set_symbol(symbol)
chart_set_timeframe("240")        # 4H
data_get_ohlcv(summary=true)      # trend context, range, avg volume
data_get_study_values()           # RSI, EMA values z aktywnych indykatorów
data_get_pine_lines()             # kluczowe poziomy z custom indykatorów
quote_get()                       # aktualna cena
```
Na podstawie danych określ dla każdego asseta:
- Trend: UP / DOWN / CHOP
- Kluczowe S/R (support i resistance)
- Jeden clean trade setup: entry, stop, TP1, TP2

**STEP 5 — X SENTIMENT (Grok)**
- Run: `python scripts/x_sentiment.py sentiment --group all` (BTC, ETH, SOL, HYPE, LINK + macro)

**STEP 6 — SENPI (jeśli MCP dostępny)**
- Call: `leaderboard_get_top` (ELITE/RELIABLE traders + ich pozycje)
- Call: `market_get_cross_asset_flows` (BTC lag correlation)

**STEP 7 — SYNTEZA → Daily Alpha Brief**

Output format (90s read, no fluff):

```
## Daily Alpha Brief — [DATA]

### MY BOOK

**Hyperliquid:**
[tabela pozycji HL — coin, kierunek, rozmiar, entry, uPnL, lewar]
[tabela zleceń HL — osobne kolumny: Type (LIMIT/TP/SL/TRIGGER), Side, Trigger $, Limit $, Size]

**Alpaca Paper:**
[equity, cash, buying power, day P&L]
[tabela pozycji Alpaca — nawet jeśli pusta: "brak pozycji"]

[Ryzyko portfela: konto $X | Max risk deployed Y% (limit: 6%) → opis]

---

### POSITION WATCH
*(sekcja generowana tylko gdy są otwarte pozycje — pomiń gdy book pusty)*

Dla **każdej otwartej pozycji** z MY BOOK napisz oddzielny blok:

```
[COIN] [LONG/SHORT] @ $[entry] | uPnL: $X | TP: $Y | SL: $Z (lub: brak SL)

Teza trade: [1 zdanie — dlaczego ta pozycja w ogóle była otwarta, co miało się wydarzyć]

Co obserwować dziś:
  • [konkretny poziom cenowy który potwierdza tezę]
  • [konkretny poziom cenowy który anuluje tezę]

Kalendarz na dziś — wpływ na pozycję:
  [Dla każdego eventu z `--upcoming` który może ruszyć tym aktywem — tabela:]

  | Godzina | Event | Jeśli WYŻEJ niż oczekiwano | Jeśli NIŻEJ niż oczekiwano |
  |---------|-------|---------------------------|---------------------------|
  | 14:30   | CPI   | Silver spada — Fed ostroż… | Silver rośnie — tanie pien… |
  | 16:00   | PMI   | Neutralne dla srebra       | Lekki risk-off, presja     |

  Jeśli dziś nie ma eventów wpływających na tę pozycję — napisz: "Brak istotnych danych makro dziś dla [COIN]"

Scenariusze:
  ✅ Pozytywny: [cena X + event Y = teza działa]
  ❌ Negatywny: [cena X lub event Y = teza jest błędem, rozważ wyjście]
  ⚠️ Ryzyko nieoczywiste: [COT, whale bias, korelacja z innym aktywem, geopolityka]

Sugerowane działanie na dziś: [TRZYMAJ / ROZWAŻ DOKUP / ZMNIEJSZ / ZAMKNIJ] — [1 zdanie]
[Jeśli brak SL: ⚠️ Brak stop-loss — likwidacja przy $X, strata maksymalna $Y]
```

Zasady POSITION WATCH:
- Kalendarz jest KLUCZOWY — dla każdej pozycji przejrzyj `--upcoming` i oceń wpływ każdego eventu
- Konkretne liczby: nie "srebro może spaść" ale "PMI miss → silver -1.5% w ciągu godziny, historycznie"
- Kierunek efektu: wyższe dane makro = Fed ostrożny = drogi kredyt = risk-off = srebro/złoto mogą spaść LUB rosnąć (srebro ma podwójną naturę: industrial metal + safe haven — zawsze określ który efekt dominuje)
- Uwzględnij istniejące zlecenia: jeśli TP $80.69 — czy któryś event może dać impuls do TP?
- Uwzględnij uśrednienie: jeśli jest BUY average-down — czy event może zepchnąć do tej ceny?
- Krzyżuj z COT i whale bias dla danego aktywa

### MACRO PULSE
[5 bulletów z najważniejszych nagłówków ostatnich 12h]

### WHALE LAYER
[Weekly vs daily divergence table — net $ per coin; crowded long/short]

### MARKET PULSE
Fear & Greed: [wartość]/100 - [label] | Interpretacja: [co to oznacza dla pozycji]

### COT SNAPSHOT
[1 linijka per TradFi asset: bias + percentyl]

### CHART READ (4H)
| Asset | Trend | Support | Resistance | Setup |
|-------|-------|---------|------------|-------|
| BTC   | ...   | ...     | ...        | Long/Short entry X stop Y TP1 Z TP2 W |
| ETH   | ...   | ...     | ...        | ... |
| SOL   | ...   | ...     | ...        | ... |
| HYPE  | ...   | ...     | ...        | ... |
| LINK  | ...   | ...     | ...        | ... |

### X SENTIMENT
[Crypto + macro sentiment w 2 zdaniach]

### TRADE PLAN — TOP PICK
Asset: [najwyższe przekonanie z CHART READ potwierdzone przez WHALE + SENTIMENT]
Direction: LONG / SHORT
Entry: X  |  Stop: Y  |  TP1: Z  |  TP2: W
Risk: 2% konta

Exact HL order:
[output z `python scripts/position_calc.py risk ASSET DIRECTION ENTRY STOP 2`]
(NIE WYKONUJ — tylko wydrukuj)

### ECON CALENDAR

**Już opublikowane dziś:**
[Wyniki danych które wyszły + krótki komentarz co oznaczają dla rynku]

**Nadchodzące dziś:**
[Lista z `--upcoming`: godzina | ważność | kraj — nazwa (est: X)]
[Każdy event: 1 zdanie co może zmienić jeśli wyjdzie powyżej/poniżej oczekiwań]

### CREDITS USED
Firecrawl: 3 kredyty tej sesji | Pozostało: X/1000 w miesiącu

---

### EXPERT VIEW

**Ogólny obraz rynku:** [Byczo/Niedźwiedzio/Neutralnie] — pewność: [niska/średnia/wysoka]
[2-3 zdania syntezy WSZYSTKICH danych — nie lista, tylko jeden spójny obraz]

**Najważniejsza rzecz na dziś:**
[Konkretny czynnik dominujący — co napędza lub blokuje ruch]

**Potencjalny game changer:**
[Jeden scenariusz który może zmienić wszystko w 24-48h]

**Największe ryzyko dla otwartych pozycji:**
[Jedno zdanie — nieoczywiste zagrożenie dla całego booka. Szczegóły per-pozycja są w sekcji POSITION WATCH powyżej.]

**Edge na dziś:**
[Co widzisz w danych czego większość retail nie łączy w całość]

**Conviction: [X]/10** — [jednozdaniowe uzasadnienie]
```

Workflow notes:
- TV chart wraca na BTC po zakończeniu
- Nie wykonuj żadnych zleceń — tylko output
- Budget: 3 Firecrawl kredyty per run (coindesk + theblock + reuters_world)
- **ZAWSZE zapisz raport do pliku przed wysyłką na Telegram:**
  `reports/YYYY-MM-DD_daily_alpha.md` (utwórz folder jeśli nie istnieje)
  Zapis na dysk = kopia zapasowa gdy Telegram zawiedzie lub wiadomość zniknie
- **ZAWSZE po wygenerowaniu briefu zapisz do bazy danych:**
  ```python
  import sys; sys.path.insert(0,'scripts')
  from db import DB
  DB().save_daily_brief(open('reports/YYYY-MM-DD_daily_alpha.md').read())
  ```
  Zastąp YYYY-MM-DD aktualną datą. To zasila kontekst dla jutrzejszego briefu.

## Agent platforms (status)

Track which agent frameworks we've verified and installed.

| Platform | Status | Notes |
|---|---|---|
| **Senpi** | verified, install pending | Doxxed team (ex-Airstack/Moxie). Non-custodial via Privy + HL API wallet pattern. MIT license. Use only with delegated agent wallet, never main key. |
| **Hermes** | TBD | Tutorial claims ~95k stars Nous Research framework. Awaiting link from user for verification. |
| **OpenClaw** | TBD | Tutorial claims ~360k stars TypeScript runtime. Awaiting link from user for verification. High alleged supply-chain risk per tutorial itself — extra scrutiny needed. |
| **AgentPNL** | TBD | Tutorial pitches as no-code WEEX agent. WEEX is out of stack → likely skip entirely. |
| **Claude Code (this CLI)** | active | Primary brain for research, code, MCP orchestration. |

## Favorite prompts

Battle-tested prompts pinned for quick reuse. Add as we discover what works.

### Morning whale scan

```
Run: python scripts/hl_whale_tracker.py whales --top 30 --window week

Then give me a tight summary (read in 60s):
1. Aggregate net exposure: which 3 coins have strongest LONG bias, which 3 strongest SHORT
2. Any coin where >75% of whale wallets agree (high-conviction)
3. Compare BTC and ETH bias — divergent or aligned?
4. Any coin where the dollar size is dominated by a single whale (concentration risk for that signal)
5. One actionable observation for today's session — not a trade rec, just what to watch
```

### Whale vs. rekt comparison

```
Run twice:
  python scripts/hl_whale_tracker.py whales --top 20 --window week
  python scripts/hl_whale_tracker.py whales --top 20 --window day

Then: where do the WEEKLY winners and DAILY winners disagree?
Coins where they're on opposite sides = potential asymmetric setup.
List up to 5 such coins. Skip if no clear disagreement.
```

### Daily Alpha Brief
<!-- TODO: add after module 9 — master prompt chaining all sources -->

### Risk audit (any time)
<!-- TODO: prompt to scan open positions across HL + Bybit + Alpaca, flag missing SLs, total open risk -->

### Pine Script debugging
<!-- TODO: add after first real debug session via TV MCP -->

## Workflow with the user

- Polish language for chat replies.
- Krótko, konkretnie, bez korpo-mowy.
- Przed dotknięciem czegokolwiek, co może wpłynąć na istniejące pliki w `C:\Users\markowyy\tradingview\` — pytaj.
- Wszystkie destrukcyjne operacje (rm, drop, force push) — confirm first.
