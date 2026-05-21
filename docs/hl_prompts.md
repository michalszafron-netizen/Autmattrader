# Prompty do bota — kompletna lista

Wysyłaj przez Telegram do @markowyy_trading_ai_bot lub wpisz w Claude Code.
**Możesz pisać normalnym językiem** — nie musisz pamiętać komend.

---

## TRENDING TOKENS — jak to działa

**Komenda:** `jakie tokeny są hot na X?` lub `python scripts/x_sentiment.py trending`

**Jak działa skan:**
1. Grok przeszukuje X (live, ostatnie 24h) i wykrywa tokeny z nieoczekiwanym buzz
2. Dla **top 3 tokenów** wykonuje **weryfikację zaangażowania** — drugi live search który liczy PRAWDZIWE posty
3. Tokeny zweryfikowane mają znacznik `[verified]` — ich liczby wzmianek są z real search
4. Tokeny #4-7 mają `~est` przy wmiantkach — to model estimate, może być zawyżony

**Ograniczenia:**
- Weryfikacja spowalnia scan o ~30s (3 dodatkowe zapytania Grok)
- Szacunki Groka dla nieweryfikowanych tokenów bywają 10-50x zawyżone
- Zawsze patrz na `top post likes/RT` — to jest wiarygodniejsze niż liczba wzmianek
- Kontrakt tokena: jeśli Grok go znajdzie w postach, pojawia się jako `Kontrakt: ADRES`

**Jak interpretować wyniki:**
- `verified` + `trend: rosnie` + `>100 lajkow na top poście` = warto research
- `~est 1200 wzmianek` bez verified = ignoruj, liczba zmyślona
- `risk=high` ZAWSZE dla memecoins — bierz tylko pozycje które możesz stracić w całości

**Walidacja (zrób przed wejściem w token):**
```
zrób research tokena [TICKER] kontrakt [CA]
```

---

## EKONOMIA I MAKRO

### Kalendarz ekonomiczny
```
kalendarz na dziś
```
```
co wychodzi w tym tygodniu z danych makro?
```
```
kalendarz na najbliższe 3 dni
```

### Analiza po wyjściu danych
```
CPI wyszło 3.4, oczekiwano 3.1 - co to znaczy dla BTC i złota?
```
```
NFP wyszło poniżej oczekiwań - zanalizuj wpływ
```

### Fear & Greed
```
jaki jest teraz fear and greed?
```
```
fear and greed ostatnie 7 dni - jaki trend?
```

---

## WHALE TRACKER

### Pełny raport wielorybów
```
Uruchom: python scripts/hl_whale_tracker.py whales --top 20 --window week
Podsumuj: top 3 LONG bias, top 3 SHORT bias, gdzie consensus >80%, co zaskakuje.
```

### Smart money vs rekt money
```
Uruchom dwa razy:
  python scripts/hl_whale_tracker.py whales --top 20 --window week
  python scripts/hl_whale_tracker.py whales --top 20 --window day
Gdzie tygodniowi i dzienniowi zwycięzcy są NA PRZECIWNYCH stronach? Max 5 coinów.
```

### Morning scan (60 sekund)
```
Uruchom: python scripts/hl_whale_tracker.py whales --top 30 --window week
Risk-on czy risk-off? Jeden coin strongest LONG, jeden strongest SHORT. Co nieoczekiwanego?
```

### Deep dive na coin
```
Uruchom: python scripts/hl_whale_tracker.py whales --top 50 --window week
Dla [COIN]: ile portfeli long vs short, net $, consensus czy podzielony rynek?
```

### Wallet stalker
```
Uruchom: python scripts/hl_whale_tracker.py positions 0x[ADRES]
Jakie pozycje, unrealized PnL, ekspozycja, lewar agresywny czy konserwatywny?
```

### Squeeze hunt (contrarian)
```
Uruchom: python scripts/hl_whale_tracker.py whales --top 20 --window week
Znajdź: smart money SHORT ale cena nie spada → potencjalny short squeeze.
```

---

## POZYCJE I ZLECENIA

### Sprawdź otwarte pozycje HL
```
Uruchom: python scripts/hl_executor.py positions
Podsumuj: co mam otwarte, unrealized PnL, % konta w ryzyku.
```

### Sprawdź otwarte pozycje Alpaca
```
Sprawdź moje pozycje na Alpaca paper. Unrealized PnL, dzienne zmiany.
```

### Kalkulator pozycji (2% ryzyka)
```
Uruchom: python scripts/position_calc.py risk [COIN] [long/short] [ENTRY] [STOP] 2
Pokaż gotową komendę do złożenia zlecenia.
```

### Złóż zlecenie HL (PAPER MODE)
```
Uruchom: python scripts/hl_executor.py order [COIN] [long/short] [SIZE] [PRICE]
Przykład: python scripts/hl_executor.py order BTC long 0.001 95000
```

### Quote (aktualna cena)
```
Uruchom: python scripts/hl_executor.py quote [COIN]
Przykład: python scripts/hl_executor.py quote SILVER
```

---

## MAKRO I NEWSY

### Daily macro brief
```
Uruchom: python scripts/macro_news.py --category alpha
Top 5 nagłówków z coindesk + theblock + reuters. Co może ruszyć rynkiem w 24h?
```

### Crypto only
```
Uruchom: python scripts/macro_news.py --category crypto
```

### Commodities (Gold, Oil)
```
Uruchom: python scripts/macro_news.py --category commodities
```

### Fed / rates
```
Uruchom: python scripts/macro_news.py --source fed
```

---

## COT REPORT (instytucje, co tydzień)

### Pełny COT
```
Uruchom: python scripts/cot_tracker.py --brief
Gdzie instytucje są ekstremalnie long/short? Co to oznacza dla Gold, Silver, Oil, SP500?
```

### Jeden asset
```
Uruchom: python scripts/cot_tracker.py --asset GOLD
```

---

## X SENTIMENT (Grok live)

### Crypto sentiment
```
Uruchom: python scripts/x_sentiment.py sentiment --group crypto
BTC, ETH, HYPE — nastroje na X teraz.
```

### Macro sentiment
```
Uruchom: python scripts/x_sentiment.py sentiment --group macro
Gold, Silver, Oil, SPX, DXY.
```

### Custom coins
```
Uruchom: python scripts/x_sentiment.py sentiment --coins BTC ETH SOL HYPE
```

### Trending tokens
```
Uruchom: python scripts/x_sentiment.py trending
Jakie nowe tokeny są hot na X dzisiaj?
```

---

## BAZA DANYCH (SQLite lokalnie)

Każdy skan automatycznie zapisuje do `data/trading.db`. Poniższe komendy pozwalają przeglądać historię.

### Status bazy
```
python scripts/db.py stats
```

### Historia trending tokenów (raw, ostatnie 7 dni)
```
python scripts/db.py trending
```

### Porównanie tokenów — ile razy się pojawiły, szczyt buzz/likes
```
python scripts/db.py compare
```

### Historia researchu tokena
```
python -c "import sys; sys.path.insert(0,'scripts'); from db import DB; [print(r) for r in DB().get_token_history('SHIBCORN')]"
```

---

## PEŁNY TRADE SETUP (łączy wszystkie warstwy)

### AI Trade Setup
```
Dla [COIN]:
1. python scripts/hl_whale_tracker.py whales --top 20 --window week
2. python scripts/x_sentiment.py sentiment --coins [COIN]
3. python scripts/hl_executor.py quote [COIN]

Na podstawie whale bias + sentiment + ceny: czy warto wchodzić, kierunek, SL, TP.
Następnie: python scripts/position_calc.py risk [COIN] [side] [ENTRY] [STOP] 2
```

---

## DAILY ALPHA BRIEF (pełny)

### Trigger ręczny
```
/daily-alpha
```

Lub przez Telegram wpisz: `/daily-alpha`

---

## PRZYDATNE SKRÓTY (PowerShell)

| Komenda | Opis |
|---|---|
| `tgtrade` | Claude Code z Telegramem (bez permission prompts) |
| `trade` | Claude Code w trading-ai |
| `tg` | Claude Code z Telegramem (z aktualnego folderu) |
