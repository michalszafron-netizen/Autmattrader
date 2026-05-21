# trading-ai — Personal AI Trading Stack

AI-augmented trading stack. Hyperliquid + Extended Exchange + Alpaca, driven by Claude Code + Telegram.

---

## Szybki start — jak uruchomić bota

### 1. Otwórz PowerShell w folderze projektu

```powershell
cd C:\Users\markowyy\trading-ai
```

### 2. Aktywuj środowisko wirtualne (venv)

```powershell
.venv\Scripts\activate
```

Po aktywacji zobaczysz `(.venv)` na początku linii w terminalu.  
**Bez tego żaden skrypt nie zadziała** — Python nie znajdzie zainstalowanych bibliotek.

### 3. Uruchom bota z Telegramem (główna komenda)

```powershell
tgtrade
```

To jest alias zdefiniowany w PowerShell profile. Robi trzy rzeczy naraz:
- przechodzi do folderu `trading-ai`
- uruchamia `keepalive.ps1` w tle (zapobiega uśpieniu przez Windows)
- startuje Claude Code z kanałem Telegram

### 4. Lub uruchom bez Telegrama (lokalnie)

```powershell
trade
```

---

## Aliasy PowerShell (skróty)

| Komenda | Co robi |
|---------|---------|
| `tgtrade` | Claude Code + Telegram + keepalive (główny tryb) |
| `trade` | Claude Code lokalnie w trading-ai |
| `tg` | Claude Code + Telegram z aktualnego folderu |

Aliasy są w: `C:\Users\markowyy\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`

---

## Jeśli venv nie startuje / błąd "activate nie znaleziono"

```powershell
# Sprawdź czy folder .venv istnieje
Test-Path .venv

# Jeśli nie — utwórz od nowa
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Jeśli `python` nie jest znaleziony:
```powershell
# Sprawdź gdzie Python
where.exe python

# Lub użyj pełnej ścieżki
C:\Users\markowyy\trading-ai\.venv\Scripts\python.exe scripts\quotes.py
```

---

## Stack — aktualny stan

| Warstwa | Narzędzie | Status |
|---------|-----------|--------|
| Brain | Claude Code (Sonnet 4.6 / Opus 4.7) | ✅ działa |
| Telegram | Claude Plugins Telegram channel | ✅ działa |
| Charts | TradingView MCP (78 narzędzi) | ✅ działa |
| Execution DEX 1 | Hyperliquid (agent wallet) | ✅ live |
| Execution DEX 2 | Extended Exchange (StarkNet, ex-Revolut) | ✅ live |
| Execution stocks | Alpaca paper trading | ✅ paper |
| Prices TradFi | Hyperliquid xyz + Extended (live, no delay) | ✅ działa |
| News/macro | Firecrawl (coindesk, reuters, theblock) | ✅ działa |
| X sentiment | Grok xAI live search | ✅ działa |
| Whale tracker | Hyperliquid leaderboard | ✅ działa |
| COT report | CFTC tygodniowy (gold, silver, oil, SP500) | ✅ działa |
| Econ calendar | FinnHub API | ✅ działa |
| Prediction markets | Polymarket public API | ✅ działa |
| Fear & Greed | Alternative.me | ✅ działa |
| Open Interest | Binance + Bybit + Extended (aggregate) | ✅ działa |
| Token research | CoinGecko + DexScreener + GoPlus + Grok | ✅ działa |
| Database | SQLite lokalne + PocketBase VPS (gdy gotowy) | ✅ SQLite |
| Daily brief | `/daily-alpha` — pełna analiza wszystkiego | ✅ działa |
| Keepalive | keepalive.ps1 — brak uśpienia w tle | ✅ działa |
| Repo | GitHub: michalszafron-netizen/Autmattrader | ✅ |

---

## Skrypty — co robi każdy

### Dane rynkowe

| Skrypt | Komenda | Co robi |
|--------|---------|---------|
| `quotes.py` | `python scripts/quotes.py` | Live ceny TradFi z HL xyz (gold, silver, oil, corn, SP500, VIX, DXY, NVDA...) |
| `quotes.py` | `python scripts/quotes.py --group metals` | Tylko metale |
| `quotes.py` | `python scripts/quotes.py --brief` | 1 linijka do daily brief |
| `oi_tracker.py` | `python scripts/oi_tracker.py` | Open Interest: Binance+Bybit+Extended |
| `oi_tracker.py` | `python scripts/oi_tracker.py --trend --save` | OI z trendem + zapis do DB |
| `token_dashboard.py` | `python scripts/token_dashboard.py` | Kafelki per token: trend+SM+OI+sentiment+composite score |
| `token_dashboard.py` | `python scripts/token_dashboard.py --coins BTC HYPE` | Wybrane tokeny |
| `token_dashboard.py` | `python scripts/token_dashboard.py --brief` | 1 linia per token (do daily-alpha) |
| `macro_news.py` | `python scripts/macro_news.py --category alpha` | Newsy: coindesk + theblock + reuters |
| `econ_calendar.py` | `python scripts/econ_calendar.py` | Kalendarz ekonomiczny dziś |
| `econ_calendar.py` | `python scripts/econ_calendar.py --upcoming` | Tylko nadchodzące eventy dziś |
| `fear_greed.py` | `python scripts/fear_greed.py --brief` | Crypto Fear & Greed index |
| `polymarket.py` | `python scripts/polymarket.py --brief` | Prediction markets (Fed, BTC, Iran...) |
| `cot_tracker.py` | `python scripts/cot_tracker.py --brief` | COT CFTC — instytucje long/short |
| `x_sentiment.py` | `python scripts/x_sentiment.py sentiment` | X sentiment: BTC ETH SOL HYPE LINK |
| `x_sentiment.py` | `python scripts/x_sentiment.py trending` | Trending tokeny na X (live Grok) |

### Giełdy — pozycje i zlecenia

| Skrypt | Komenda | Co robi |
|--------|---------|---------|
| `hl_executor.py` | `python scripts/hl_executor.py positions` | Pozycje HL (perps + xyz TradFi) |
| `hl_executor.py` | `python scripts/hl_executor.py orders` | Wszystkie zlecenia HL (TP/SL/limit) |
| `hl_executor.py` | `python scripts/hl_executor.py quote SILVER` | Live cena z HL |
| `hl_executor.py` | `python scripts/hl_executor.py tickers --xyz` | Lista 78 xyz TradFi instrumentów |
| `extended_executor.py` | `python scripts/extended_executor.py positions` | Pozycje Extended Exchange |
| `extended_executor.py` | `python scripts/extended_executor.py balance` | Konto Extended (equity, margin, health) |
| `extended_executor.py` | `python scripts/extended_executor.py orders` | Zlecenia TPSL na Extended |
| `extended_executor.py` | `python scripts/extended_executor.py markets` | Top 30 rynków Extended wg wolumenu |
| `alpaca_executor.py` | `python scripts/alpaca_executor.py positions` | Pozycje Alpaca paper |
| `alpaca_executor.py` | `python scripts/alpaca_executor.py orders` | Zlecenia Alpaca |
| `hl_whale_tracker.py` | `python scripts/hl_whale_tracker.py whales --top 20 --window week` | Aggregate whale positions HL |

### Analiza i kalkulacje

| Skrypt | Komenda | Co robi |
|--------|---------|---------|
| `position_calc.py` | `python scripts/position_calc.py risk BTC long 77000 75000 2` | Kalkulator rozmiaru pozycji (2% ryzyka) |
| `token_research.py` | `python scripts/token_research.py 0x123...` | Deep research tokena (EVM/Solana) |
| `db.py` | `python scripts/db.py stats` | Stan bazy danych (ile wpisów) |
| `db.py` | `python scripts/db.py compare` | Historia trending tokenów |

---

## Komendy bota (przez chat lub Telegram)

| Komenda | Co robi |
|---------|---------|
| `/daily-alpha` | Pełna analiza: MY BOOK + OI + WHALE + COT + CHART + SENTIMENT + EXPERT VIEW |
| `/raport` | Analiza wszystkich 6 instrumentów na TradingView + rysowanie poziomów |
| `/raport BTC` | Analiza + poziomy tylko dla BTC |
| `/raport clean` | Usuń rysunki ze wszystkich wykresów |
| `jakie tokeny są hot na X?` | Trending scan Grok (live X search) |
| `zrób research tokena [CA]` | Deep dive: kontrakt, liquidity, bezpieczeństwo |
| `pokaż pozycje` | Wszystkie pozycje: HL + Extended + Alpaca |
| `kalendarz na dziś` | Econ calendar z kolorami i EXPERT VIEW |
| `jaki jest fear and greed?` | F&G index + interpretacja |

---

## Giełdy w stacku

### Hyperliquid (HL)
- **Typ:** DEX perpetuals (onchain, EVM signed)
- **Instrumenty:** 230+ crypto perps + 78 xyz TradFi (Gold, Silver, Oil, SP500, Nasdaq, akcje US)
- **Klucz:** Agent wallet (nie może wypłacać — built-in bezpieczeństwo)
- **Tryb:** `HL_TRADING_MODE=live` w .env

### Extended Exchange
- **Typ:** DEX perpetuals (StarkNet, ZK rollup na Ethereum)
- **Zespół:** ex-Revolut (CEO: Head of Crypto Ops Revolut + McKinsey)
- **Instrumenty:** 115 aktywnych rynków: BTC, ETH, SOL + Gold, Silver, Oil, SP500, Nasdaq, akcje
- **API:** Read-only przez `EXTENDED_API_KEY`, write wymaga Stark private key
- **Vault:** 214869 | Client ID: 114295

### Alpaca
- **Typ:** US stocks, paper trading
- **Tryb:** `ALPACA_PAPER=true` — wszystkie zlecenia idą na papierowe konto

---

## Źródła cen — zasada

| Kontekst | Źródło |
|----------|--------|
| Analizy, raporty, OI | **Hyperliquid xyz** (live, bez opóźnień) |
| Rysowanie na wykresie TV | **TradingView** `quote_get()` (spójne z tym co widzisz) |
| **Nigdy** | ETF proxy (GLD, SLV, USO) jako cena spot |

---

## Baza danych (SQLite)

Plik: `data/trading.db` (gitignored)

Automatycznie zapisuje: trending tokeny, sentiment, OI snapshots, daily briefs, token research, zlecenia, pozycje, zapytania Telegram.

```powershell
python scripts/db.py stats      # ile wpisów w każdej tabeli
python scripts/db.py compare    # historia trending tokenów
```

Gdy będziesz gotowy na VPS (Hostinger):
- Dodaj `POCKETBASE_URL` do .env
- Dane będą zapisywane równolegle do SQLite (lokalnie) i PocketBase (VPS)

---

## Struktura folderów

```
trading-ai/
├── scripts/          # wszystkie skrypty bota
│   ├── quotes.py          # live ceny TradFi
│   ├── oi_tracker.py      # Open Interest agregat
│   ├── hl_executor.py     # Hyperliquid execution
│   ├── extended_executor.py  # Extended Exchange
│   ├── alpaca_executor.py # Alpaca paper
│   ├── hl_whale_tracker.py   # whale positions
│   ├── x_sentiment.py    # X/Grok sentiment
│   ├── macro_news.py      # newsy Firecrawl
│   ├── econ_calendar.py  # kalendarz FinnHub
│   ├── cot_tracker.py    # COT CFTC
│   ├── fear_greed.py     # Fear & Greed
│   ├── polymarket.py     # prediction markets
│   ├── token_research.py # deep token research
│   ├── position_calc.py  # kalkulator pozycji
│   ├── tv_webhook.py     # Flask webhook z TV
│   ├── db.py             # SQLite + PocketBase
│   ├── tz_utils.py       # UTC → CET/CEST konwersja
│   └── keepalive.ps1     # Windows anti-sleep
├── docs/
│   ├── hl_prompts.md     # lista wszystkich komend
│   └── roadmap.md        # plan dalszego rozwoju
├── reports/              # auto-generowane raporty (gitignored)
├── data/                 # SQLite DB (gitignored)
├── .env                  # klucze API (gitignored!)
├── .env.example          # template do skopiowania
├── CLAUDE.md             # instrukcje dla Claude
└── README.md             # ten plik
```

---

## Zasady bezpieczeństwa

- `.env` jest w `.gitignore` — nigdy nie commituj kluczy
- Hyperliquid: używaj **agent wallet** (nie może wypłacać)
- Alpaca: `ALPACA_PAPER=true` zawsze, chyba że świadomie decydujesz inaczej
- Max ryzyko na trade: 2% konta | Max portfolio risk: 6% | Kill switch przy -3% dziennie
- Stark Key Private (Extended) — nigdy nie wysyłaj nikomu, nie wpisuj w kod

---

## Problemy i rozwiązania

| Problem | Rozwiązanie |
|---------|-------------|
| `activate` nie działa | `.venv\Scripts\activate` (z backslash, nie forward slash) |
| `python not found` | Użyj pełnej ścieżki: `.venv\Scripts\python.exe scripts\...` |
| Bot nie odpowiada na Telegram | Uruchom `tgtrade` od nowa — keepalive powinien zapobiegać, ale po restarcie PC trzeba uruchomić ręcznie |
| `ModuleNotFoundError` | Nie aktywowałeś venv — patrz punkt 2 powyżej |
| PowerShell nie zna aliasów `tgtrade`/`trade` | `. $PROFILE` (przeładuj profil) lub otwórz nowy terminal |
| Ceny wyglądają dziwnie | Sprawdź czy nie używasz ETF (GLD/SLV) zamiast `quotes.py` |
| SSL error na Windows | `$env:NODE_TLS_REJECT_UNAUTHORIZED = "0"` już jest w profilu — otwórz nowy terminal |
| Bot próbuje Bash zamiast PowerShell (DeepSeek) | CLAUDE.md ma już regułę MUST PowerShell — jeśli model nadal próbuje Bash, przypomnij mu "use PowerShell tool only, never Bash" |
| Daily brief nadpisał poprzedni | Od teraz: pierwszy = `YYYY-MM-DD_daily_alpha.md`, kolejne = `_v2.md`, `_v3.md` (CLAUDE.md zaktualizowany) |
| Daily brief nie pokazał się w chacie | CLAUDE.md ma teraz regułę: MUST wyświetlić pełny brief w chacie ZANIM zapisze plik |

---

## Wersjonowanie raportów (od teraz)

Każdy `/daily-alpha` w tym samym dniu **nie nadpisuje** poprzedniego:

```
reports/2026-05-21_daily_alpha.md         ← pierwszy run dnia
reports/2026-05-21_daily_alpha_v2.md      ← drugi run tego samego dnia
reports/2026-05-21_daily_alpha_v3.md      ← trzeci...
```

Każda wersja jest też **osobno zapisywana do bazy danych** — możesz porównać jak ewoluowała sytuacja w ciągu dnia komendą `python scripts/db.py context-daily`.

---

## Korzystanie z DeepSeek vs Claude

Na lokalnym Windows i na VPS możesz używać różnych modeli przez Claude Code. Najważniejsze różnice:

| | Claude Sonnet 4.6 / Opus 4.7 | DeepSeek V4 |
|--|------|---------|
| Trzymanie się skompikowanego workflow | Bardzo dobre | Średnie — może improwizować |
| Tool calling (PowerShell/MCP) | Stabilne | Może mieszać Bash i PowerShell |
| Polskie znaki w outputach | Stabilne | Czasami encoding issues |
| Koszt | Wyższy | Niższy |
| Jakość treści finansowej | Bardzo dobra | Dobra (porównywalna) |

**Wniosek:** DeepSeek wymaga bardziej deterministycznych instrukcji w CLAUDE.md (które już są wprowadzone od dziś — sekcja "Workflow notes — OBOWIĄZKOWE"). Treść raportu będzie podobna, ale proces wykonawczy musi być twardszy.

Jeśli używasz DeepSeek i widzisz że próbuje Bash zamiast PowerShell — w czacie napisz: *"use PowerShell tool only, never Bash on Windows paths"* — to wystarczy.
