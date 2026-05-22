# Roadmap — Planowane funkcjonalności

Status: backlog. Nie wdrażamy dopóki nie skończymy tutorialu + VPS deploy.
Kolejność wg trudności — od najłatwiejszego.

---

## POZIOM 0 — Najwyższy priorytet (dodać ASAP do daily brief)

### 0.1 Kalendarz ekonomiczny — Forex Factory + analiza wpływu
**Co to:** Dwa zastosowania:
1. **Rano w daily brief** — jakie dane wychodzą dziś/jutro, które są high-impact
2. **Po publikacji danych** — analiza siły odczytu vs oczekiwania + wpływ na rynki

**Dlaczego kluczowe:** NFP, CPI, FOMC, GDP, PPI — to są eventy które w 30 sekund ruszają BTC ±3%, Gold ±1.5%, Oil ±2%. Bez kalendarza blind-tradeujemy w dniu danych.

**Dwa moduły do zbudowania:**

#### Moduł A — Calendar fetcher (codziennie rano)
Output w daily brief:
```
ECONOMIC CALENDAR — dziś (2026-05-20)
  14:30  [HIGH]   US CPI MoM        oczekiwane: 0.3%  poprzednie: 0.4%
  14:30  [HIGH]   US CPI YoY        oczekiwane: 3.1%  poprzednie: 3.2%
  20:00  [MEDIUM] FOMC Minutes
Jutro:
  14:30  [HIGH]   US Retail Sales
Watch: CPI jest market-moving dla BTC (risk-off/on), Gold (inflation hedge), USD
```

#### Moduł B — Impact analyzer (po wyjściu danych)
Trigger: ręcznie lub automatycznie gdy dane wyjdą.
Prompt: `Właśnie wyszło CPI: actual=3.4%, expected=3.1%. Zanalizuj surprise i wpływ.`

Output:
```
CPI SURPRISE: +0.3pp powyżej oczekiwań → HAWKISH SURPRISE
Siła: MOCNA (odchylenie >0.2pp = market-moving)

Oczekiwany wpływ w ciągu 1-4h:
  BTC:    -2% do -4%  (risk-off, Fed może nie ciąć)
  ETH:    -2% do -5%  (beta wyższa niż BTC)
  GOLD:   +0.5% do +1.5%  (inflation hedge mimo USD strength)
  USD:    +0.3% do +0.8%  (DXY w górę)
  NASDAQ: -0.5% do -1.5%  (wyższe stopy = spółki tech cierpią)
  OIL:    neutralny (demand story ważniejsza)

Historyczny precedens: ostatnie 3 hawkish CPI → BTC avg -3.2% w ciągu 4h
Trade idea: czekaj 15-30 min na stabilizację, potem szukaj odbiecia na BTC jeśli
  spada do $X (key support). Stop ścisły. Nie łap falling knife.
```

**Narzędzia (wszystkie darmowe):**

| Źródło | Co daje | Dostęp |
|---|---|---|
| **FinnHub** Economic Calendar | Kalendarz z datami, oczekiwaniami, previous | Free API key (finnhub.io) |
| **Alpha Vantage** Economic Indicators | Historyczne dane ekonomiczne (CPI series, GDP) | Free API key |
| **FRED API** (Federal Reserve) | Oficjalne dane Fed — CPI, PCE, unemployment | Free, no key needed |
| **Investing.com** (Firecrawl) | Forex Factory alternatywa, pełny kalendarz | 1 Firecrawl credit |
| **Forexfactory.com** (Firecrawl) | Oryginalny, najlepszy UI kalendarza | 1 Firecrawl credit |

**Rekomendacja:** FinnHub API (darmowy klucz) + FRED dla historycznych danych. Firecrawl jako fallback jeśli API nie wystarczy.

**Nowy klucz do .env:** `FINNHUB_API_KEY` (free na finnhub.io)

**Integracja z daily brief:** dodać jako STEP 0.5 między MY BOOK a MACRO PULSE:
```
python scripts/econ_calendar.py --today   # co wychodzi dziś
python scripts/econ_calendar.py --impact CPI 3.4 3.1  # analiza po danych
```

**Priorytet:** ⭐⭐⭐⭐⭐ — to powinno wejść ZARAZ PO VPS deploy, przed innymi roadmap items.

---

## POZIOM 1 — Łatwe (kilka godzin)

### 1.1 Solana token enricher — DexScreener + Birdeye
**Co to:** Auto-wzbogacenie tokenów z `x_sentiment.py trending` o dane on-chain.
Dla każdego trending tokena dociągnij: market cap, liquidity, 24h volume, holders, wiek kontraktu, rug-check score.

**Dlaczego ważne:** Teraz dostajemy ticker z X. Nie wiemy czy jest 10k MC czy 10M MC. DexScreener daje to w jednym API callu.

**Narzędzia:**
- DexScreener API — `https://api.dexscreener.com/latest/dex/search?q=TICKER` — **darmowe, bez klucza**
- Birdeye API — bardziej szczegółowe (holders, top wallets) — free tier dostępny, klucz potrzebny
- RugCheck API — `https://api.rugcheck.xyz/v1/tokens/CA/report` — **darmowe, bez klucza**

**Output:** Automatyczne oznaczenie LOW/MEDIUM/HIGH quality po dołączeniu on-chain data do trending output.

---

### 1.2 Fear & Greed — historia (ostatnie 30 dni)
**Co to:** Wykres / tabela F&G z ostatniego miesiąca. Czy idziemy z 20→70 (recovery) czy 80→30 (crash)?
`python scripts/fear_greed.py --days 30`
Już prawie gotowe — skrypt obsługuje `--days N`, tylko dodać ładny display trendu.

---

## POZIOM 2 — Średnie (1-2 dni)

### 2.1 Whale tracker — rozszerzenie o CEX (Binance / Bybit)
**Co to:** Dodanie danych wielorybów z największych CEX obok Hyperliquid.

**Ważna uwaga:** Binance/Bybit NIE udostępniają pozycji per-wallet (jak HL public API). Możemy mierzyć inne metryki:
- **Open Interest** — łączna ekspozycja na rynku futures (bullish/bearish bias)
- **Long/Short ratio** — % traderów long vs short (kontrariański sygnał)
- **Funding rate** — ujemny = market jest short-heavy (potencjalny squeeze)
- **Large trades** — transakcje >$1M w ciągu ostatnich 24h

**Narzędzia:**
- Binance Futures API — `GET /futures/data/globalLongShortAccountRatio` — **darmowe**
- Bybit API — `/v5/market/account-ratio` — **darmowe**
- CoinGlass — agreguje OI + funding ze wszystkich giełd (free tier)

**Output:** Nowy skrypt `scripts/cex_sentiment.py` — zestawienie HL whale bias vs Binance/Bybit long-short ratio per coin.

---

### 2.2 Fundamentalna analiza tokena — pipeline źródeł
**Co to:** Głęboka analiza wybranego tokena z wielu źródeł. Komenda: `python scripts/token_research.py [TICKER lub CA]`

**Potrzebne źródła (7 warstw):**

| # | Źródło | Co daje | Narzędzie |
|---|---|---|---|
| 1 | **Twitter/X** (Grok live) | Sentyment, influencerzy, narracja | Grok API (już mamy) |
| 2 | **DexScreener** | Market cap, volume, liquidity, wiek | Free API |
| 3 | **RugCheck** | Rug risk score, mint authority, freeze authority | Free API |
| 4 | **Birdeye** | Top holders, whale wallets, insider activity | Free tier API |
| 5 | **GitHub** | Aktywność repo (commits, contributors, stars) | GitHub API (free) |
| 6 | **Website** (Firecrawl) | Whitepaper, team, roadmap, tokenomics | Firecrawl (mamy, 1 credit) |
| 7 | **Solscan / Explorer** | Token distribution, top 10 holders %, vesting | Free API |

**Output na każdy token:**
```
FUNDAMENTAL SCORE: X/100

Legitymność:    [##########] XX/100
  - Team doxxed: tak/nie
  - GitHub: aktywny/martwy/brak
  - Audit: tak/nie/brak

On-chain health: [##########] XX/100
  - Top 10 holders: XX% supply
  - Insider wallets: XX%
  - Liquidity locked: tak/nie/ile

Social proof:   [##########] XX/100
  - KOL mentions: X influencerów
  - Sentiment: bullish/bearish
  - Organiczne vs paid: ocena

Rug risk:       LOW/MEDIUM/HIGH/CRITICAL
  - Mint authority: revoked/aktywna
  - Freeze authority: revoked/aktywna
  - RugCheck score: XX/100

WERDYKT: PASS / WATCH / AVOID
```

---

## POZIOM 3 — Trudne (kilka dni)

### 3.1 Auto altcoin selector + Solana bot execution
**Co to:** Pełny pipeline:
1. `x_sentiment.py trending` → lista hot tokenów
2. DexScreener enrichment → filtruj: MC > $500k, liquidity > $100k, wiek > 48h
3. RugCheck → odrzuć HIGH/CRITICAL risk
4. Fundamental score → wybierz top 1-2
5. Telegram prompt do ciebie: "Znalazłem setup: $TOKEN, MC=$X, risk=MEDIUM. Kupić?"
6. Odpowiadasz "tak" → bot wykonuje przez **Telegram Solana bot** (Maestro / Trojan on Solana)

**Narzędzia do egzekucji:**
- **Maestro Sniper Bot** — Telegram bot z API dla Solana DEX (Jupiter)
- **Trojan on Solana** — alternatywa, podobny model
- **Jupiter Aggregator API** — bezpośrednia integracja (najtrudniejsza, pełna kontrola)

**Human-in-the-loop:** Bot NIGDY nie kupuje sam. Zawsze Telegram confirmation → "tak/nie".

**Trudność:** Wymaga: scoring modelu, risk rules, integracji z jednym z powyższych, testów na małych kwotach.

---

## POZIOM 4 — Własny bot Market Making / Scalping na Hyperliquid

### 4.1 MM/Scalping bot — xyz TradFi assets (HL CLOB)

**Inspiracja:** Trader `0xe687b524903fea10a648326d90130ffabe0215f9` — robi 2000+ tradów/tydzień na xyz:SKHX i xyz:EWY (Korea ETF), avg 28.6s między tradami. +3585% ROI z $56k konta w 30 dni. Klasyczny market maker na niszowych aktywach z szerokim spreadem.

**Cel:** Nie chodzi o wielkie zyski — chodzi o **konsekwentne małe groszówki + wysoki wolumen**. Break even + 0.1% dziennie wystarczy jeśli bot działa 24/7.

**Strategia:**
```
Co 1-2 sekundy:
1. Pobierz mid-price z L2 order book
2. Oblicz spread (ATR-based lub fixed threshold)
3. Postaw BID = mid - spread/2  (limit order)
4. Postaw ASK = mid + spread/2  (limit order)
5. Po fill → natychmiast odśwież quote po drugiej stronie
6. Inventory control: jeśli pozycja >X → zmniejsz quote rozmiar
```

**Target:** 2-5 bps per round-trip, 100-500 tradów/dzień
**HL maker fees:** 0.01% (na wyższych tierach — ujemne, czyli REBATE)
**Asset:** xyz:SKHX, xyz:EWY lub inny xyz z wide spread i regularnym wolumenem

**Risk controls (niezbędne):**
- Max pozycja: ±5% kapitału na stronę
- Daily loss limit: -1% → kill switch, flatten all
- Spread threshold: nie kwotuj gdy spread < min (rynek zbyt wąski)
- Godziny: ew. filtr na godziny otwarcia rynku bazowego (SKHX = Korea 01:00-07:00 UTC)
- Telegram heartbeat co 5 minut

**Technologia:**
- HL Python SDK (już mamy) + agent wallet (już mamy)
- Osobny folder: `trading-ai/bots/mm_bot/`
- Paper mode domyślnie, live tylko po 2 tygodniach paper z pozytywnym wynikiem

**Timeline:** 3 sesje po wdrożeniu VPS
- Sesja 1: L2 book reader + quote engine
- Sesja 2: Risk management + kill switch + Telegram alerts
- Sesja 3: Backtesting + paper run → live

**Trudność:** WYSOKA — wymaga low-latency execution, race conditions, inventory management

---

## POZIOM 5 — Baza danych + RAG (pamięć długoterminowa bota)

### Problem który rozwiązujemy

Teraz każdy raport, analiza, trending token, zapytanie z Telegrama — ląduje w plikach `.md` i `.jsonl` które nikt nie przeszukuje. Bot nie pamięta że tydzień temu analizował SATO, nie wie że 3 miesiące temu silver był na tym samym poziomie, nie może odpowiedzieć na "jak wyglądały wyniki wielorybów w poprzedni piątek".

Baza danych + RAG = **bot ma pamięć**.

---

### Co trafia do bazy

| Kategoria | Dane | Częstotliwość |
|---|---|---|
| `daily_briefs` | Pełny raport + key signals + assets | 1x dziennie |
| `trending_tokens` | Ticker, chain, kontrakt, buzz, engagement, wynik po 24h/72h | każdy scan |
| `whale_snapshots` | HL top traders, coin bias, net $ | co scan |
| `cot_snapshots` | Asset, net contracts, percentyl, sygnał | co tydzień |
| `x_sentiment` | Asset, score, label, narracje | każdy scan |
| `econ_events` | Event, actual vs est, surprise, market reaction | po każdych danych |
| `token_research` | Ticker, kontrakt, MC, safety verdict, conviction | każdy research |
| `trade_alerts` | Symbol, side, price, size, venue, status, PnL | każdy alert TV |
| `positions_history` | Snapshot pozycji HL + Alpaca | 1x dziennie |
| `telegram_queries` | Zapytanie użytkownika + odpowiedź bota | każde zapytanie |

---

### Opcje bazy danych

**Opcja A — PocketBase** *(twoja propozycja — dobra)*
- Jeden binarny plik, zero konfiguracji serwera
- REST API + realtime subscriptions
- Wbudowany panel admin w przeglądarce
- Świetny na VPS: `./pocketbase serve`
- **Rekomendowany dla danych strukturalnych** (raporty, tokeny, whale snapshots)

**Opcja B — SQLite + Python** *(najprostszy start)*
- Zero dependencji, wbudowany w Python
- Dostęp lokalnie i na VPS
- Brak REST API (tylko bezpośredni dostęp przez skrypt)
- **Dobry do szybkiego prototypu przed VPS**

**Opcja C — Supabase** *(najsilniejszy)*
- PostgreSQL + REST API + realtime + wbudowany pgvector (do RAG)
- Free tier: 500MB, 2 projekty
- Dostępny z każdego miejsca (cloud)
- **Rekomendowany gdy potrzebujesz RAG + dostępu zdalnego**

**Opcja D — Chroma (vector DB)** *(dla RAG)*
- Lokalny vector store, Python native, zero setup
- Embedduje raporty jako wektory
- Zapytanie: "pokaż analizy silver z ostatnich 3 miesięcy" → semantic search
- **Najlepszy do RAG, uzupełnienie do A/B/C**

---

### Rekomendacja architektury

```
Etap 1 (lokalnie, teraz możliwe):
  SQLite → przechowuje trending tokens, raporty, whale snapshots
  Chroma → embedduje raporty do semantic search

Etap 2 (po VPS deploy):
  PocketBase → zastępuje SQLite, dodaje REST API + admin panel
  Chroma → zostaje (lub pgvector w Supabase)

Etap 3 (opcjonalny):
  Supabase → pełny cloud, dostęp z Telegrama do historii
```

---

### RAG — co daje praktycznie

Bot z RAG może odpowiadać na:
- *"Jak wyglądał COT silver 3 miesiące temu vs dziś?"*
- *"Które trending tokeny z ostatnich 30 dni zrobiły >5x?"*
- *"Kiedy ostatnio whale bias na HYPE był tak wysoki?"*
- *"Pokaż wszystkie analizy tokenów z Ethereum z ostatniego miesiąca"*
- *"Co raportowałem o FOMC w marcu?"*

**Embedding:** raporty → chunki → wektory (model: text-embedding-3-small OpenAI lub darmowy lokalny)
**Query:** zapytanie → wektor → cosine similarity → top-5 relevantnych chunków → odpowiedź z kontekstem

---

### Trudność i timeline

- SQLite logger (etap 1): **1 sesja** — prosta integracja do istniejących skryptów
- PocketBase deploy (etap 2): **pół sesji** po VPS — jeden plik binarny
- Chroma RAG (etap 3): **2 sesje** — embedding pipeline + query interface
- Supabase migration (opcja): **1 sesja** — zamiana SQLite na Supabase client

---

---

## JUTRO — Plan sesji 2026-05-23

> ⏰ **PRZYPOMNIENIE: Deploy na VPS jutro!** Wrzucić repo na serwer Hostinger.

### 🎯 Priorytety jutrzejszej sesji (w kolejności)

---

### J.1 Gotowe prompty dla Hermesa — biblioteka komend

Zestaw gotowych, przetestowanych promptów do wklejenia na Telegramie do Hermesa.
Wychodzisz rano, wybierasz jeden, modyfikujesz 2 słowa, wpisujesz — gotowe.

**Prompty do przygotowania:**

```
# CRON — Skaner wykresów co 4h
Ustaw zadanie cron: co 4 godziny sprawdź wykresy BTC, ETH i SOL
na interwale 4H przez TradingView MCP. Dla każdego podaj: trend,
kluczowy support, kluczowy resistance. Jeśli widzisz wyraźny setup
(breakout lub odbicie od wsparcia), wyślij alert z opisem i entry.

# CRON — Poranny brief 07:00
Ustaw cron na 07:00 każdego dnia: uruchom python scripts/daily_alpha.py
i wyślij mi wynik przez Telegram.

# CRON — Monitoring newsów co 30 min
Ustaw cron co 30 minut: sprawdź RSS feedy coindesk i theblock przez
blogwatcher, filtruj po słowach: Silver, Gold, BTC, Fed, Iran, OPEC.
Jeśli coś trafnego — wyślij mi alert natychmiast.

# QUICK — Szybki scan rynku
Sprawdź przez TradingView MCP: BTC 1H trend, ETH 1H trend, aktualny
Fear&Greed. Daj mi 3 zdania: gdzie jesteśmy, czego nie robić teraz.

# QUICK — Moje pozycje
Uruchom: python scripts/hl_executor.py positions oraz
python scripts/extended_executor.py positions. Podsumuj uPnL total
i powiedz czy któraś pozycja wymaga uwagi.

# ANALIZA — Token research
Zbadaj token [CA/TICKER] na Solana: cena, MC, liquidity, holders,
rug risk. Powiedz czy warto wejść i przy jakim rozmiarze pozycji.

# POLYMARKET — Deep check
Sprawdź przez Polymarket skill: aktualne probability na BTC $150k,
Fed cut w czerwcu, Iran deal. Pokaż jak zmieniały się ostatnie 24h.
```

---

### J.2 Analiza kosztów Hermesa — refresh co 10-15 minut

**Szacunkowe koszty dla DeepSeek V4 Flash** przy ciągłym monitoringu:

| Scenariusz | Tokeny/scan | Scany/dzień | Koszt/dzień | Koszt/miesiąc |
|---|---|---|---|---|
| Refresh 15 min | ~3,000 | 96 | ~$0.04 | **~$1.20** |
| Refresh 10 min | ~3,000 | 144 | ~$0.06 | **~$1.80** |
| Refresh 5 min | ~3,000 | 288 | ~$0.12 | **~$3.60** |
| Z cache hit (-98%) | ~3,000 | 144 | ~$0.002 | **~$0.06** |

**Wniosek:** Nawet co 10 minut to **mniej niż 2$ miesięcznie**. Cache hit przy powtarzalnych system promptach redukuje do groszy. Możesz sobie pozwolić na refresh co 5 minut bez żadnego problemu finansowego.

**Co skanować co 10-15 min:**
- Trend BTC/ETH/SOL (4H + 1H)
- Kluczowe S/R czy cena je narusza
- Nagłe zmiany OI (>5% w 1h)
- Breaking news z RSS

---

### J.3 Hermes News Intelligence — BlogWatcher Setup

**Cel:** Hermes monitoruje ~15 źródeł newsów 24/7, filtruje po relevance, alertuje natychmiast.

**Źródła RSS do dodania:**
```
Crypto:      coindesk.com/arc/outboundfeeds/rss/
             theblock.co/rss/all
             decrypt.co/feed
             cointelegraph.com/rss
TradFi:      reuters.com/finance/rss
             ft.com/markets?format=rss
Commodities: kitco.com/rss/news/gold-news.rss
             oilprice.com/rss
Macro:       federalreserve.gov/feeds/press_all.xml
             forexlive.com/feed
Geopolitics: bbc.com/news/world/rss.xml
```

**Trigger keywords per asset:**
- Silver: silver, XAG, precious metals, SILVER Act, industrial demand
- Gold: gold, XAU, central bank, inflation, safe haven
- BTC: bitcoin, BTC, ETF, regulation, SEC, halving
- Fed: Federal Reserve, FOMC, rate cut, interest rates, Powell/Warsh

**Implementacja:** `hermes tools install blogwatcher` + cron co 20 min

---

### J.4 Polymarket — Głębsza Analiza Prediction Markets

Obecny `polymarket.py` pobiera tylko price/probability. Rozszerzenie:

- **Orderbook depth** — gdzie są duże pieniądze (np. $500k zakłady na BTC $150k)
- **Price history 7d** — jak zmieniało się prawdopodobieństwo w czasie
- **Alert gdy skok >10%** w ciągu 1h — rynek wie coś czego Ty nie wiesz jeszcze
- **Nowe rynki scanner** — nowo otwarte markety mogą być arbitraż okazją

**Narzędzie:** Hermes `polymarket` skill (już zainstalowany) + nowy skrypt `scripts/polymarket_deep.py`

---

### J.5 CRON Jobs — Serce Automatyzacji (Master Plan)

Pełny plan wszystkich cron jobów które chcemy uruchomić:

| Job | Trigger | Co robi | Status |
|---|---|---|---|
| Chart Scanner | co 4h | BTC/ETH/SOL na 4H — trend + setup | 🎯 JUTRO |
| News Monitor | co 20 min | RSS 15 źródeł — filter + alert | 🎯 JUTRO |
| Morning Brief | 07:00 CET | Pełny daily-alpha przez Hermesa | 📋 PLAN |
| OI Spike Alert | co 1h | OI > 5% zmiana → alert | 📋 PLAN |
| Polymarket Watch | co 2h | Probability shifts > 10% → alert | 📋 PLAN |
| Position Check | co 6h | uPnL + SL proximity alert | 📋 PLAN |
| Volume Daemon | co 1h | Już działa (volume_scanner.py) | ✅ DZIAŁA |
| Smart Money | co 1h | Już działa (smart_money_tracker.py) | ✅ DZIAŁA |
| Listings Scan | co 6h | Już działa (listings_scanner.py) | ✅ DZIAŁA |

---

### J.6 ⭐ OPCJE BINANCE — Arbitraż vs Spot/Perps

**To jest prawdziwa nisza. Zbadać dokładnie.**

**Idea:** Binance Options (europejskie, wygasają co godzinę i codziennie) vs:
- xyz:GOLD / xyz:SILVER na Hyperliquid (perpy TradFi)
- BTC/ETH perpy na HL i Extended
- Corn/Wheat na HL xyz vs opcje CME/Binance

**Potencjalne strategie:**
```
1. COVERED CALL na HL perp + sell Binance call option
   → Trzymasz long Silver na HL, sprzedajesz call na Binance
   → Zbierasz premium co tydzień, hedgujesz pozycję

2. SYNTHETIC LONG/SHORT bez depozytu
   → Kup call Binance + sprzedaj put Binance = synthetic long
   → vs tani perp na HL = czysty arbitraż fundingu

3. VOLATILITY ARBITRAŻ
   → IV Binance options vs realized vol HL = gdy rozbieżność > X%
   → Klasyczny vol arb, nieznany w krypto retail

4. CALENDAR SPREAD między BTC perp (HL) a BTC futures opcja (Binance)
```

**Dlaczego nisza?**
- Większość retail nawet nie wie że Binance ma opcje
- Likwidność opcji krypto = szeroki spread = okazja dla kogoś kto rozumie pricing
- HL xyz TradFi + Binance crypto options = cross-market arbitraż którego nikt nie robi

**Co zbadać jutro:**
1. Binance Options API — czy możemy quotować i handlować programowo?
2. Aktualny IV (implied volatility) na BTC/ETH opcjach Binance
3. Porównaj z realized vol z `oi_tracker.py` danych
4. Czy CCXT obsługuje Binance Options?

---

## Kolejność wdrożenia (rekomendacja)

```
1. Econ Calendar (FinnHub)   ← PIERWSZY zaraz po VPS — game changer dla daily brief
2. DexScreener enricher      ← 1 dzień, ogromna wartość dla Solana trendings
3. RugCheck integration      ← przy okazji enrichera (parę godzin)
4. SQLite logger              ← prosta baza danych dla raportów i tokenów (1 sesja)
5. CEX whale (Binance OI)    ← uzupełni whale layer w daily brief
6. Fundamental analysis      ← budujemy stopniowo, źródło po źródle
7. PocketBase + Chroma RAG   ← po VPS deploy, baza + pamięć semantyczna
8. Auto selector + execution ← ostatni, dopiero gdy 1-7 przetestowane
9. MM/Scalping bot           ← osobna gałąź, dopiero po VPS + stabilnej bazie
```

---

## Notatki techniczne

- Solana CA lookup: `https://api.dexscreener.com/latest/dex/tokens/[CA]`
- RugCheck: `https://api.rugcheck.xyz/v1/tokens/[CA]/report`
- GitHub API: `https://api.github.com/repos/[org]/[repo]` — 60 req/h bez klucza, 5000/h z kluczem
- Birdeye klucz: potrzebny (free tier = 1000 req/day) — dodać do .env jako `BIRDEYE_API_KEY`
- Binance futures: `https://fapi.binance.com/futures/data/globalLongShortAccountRatio`
