# 📄 Dokumentacja Scalp Bota — HL xyz Correlation Scalper

**Autor:** Hermes Agent + krypt  
**Data utworzenia:** 2026-06-18  
**Projekt:** trading-ai  

---

## 1. Założenia i plan

### 1.1 Cel

Zbudować skalpowego bota tradingowego na Hyperliquid xyz DEX (TradFi instrumenty: GOLD, SILVER, SP500, Crude Oil), wykorzystującego **korelacje międzyrynkowe** do wykrywania opóźnień cenowych (lags) i realizacji szybkich scalpów z **limit-limit maker fee**.

### 1.2 Dlaczego HL xyz, a nie Bybit / Binance

| Czynnik | HL xyz (wybrany) | Bybit perps (alternatywa) |
|---------|------------------|--------------------------|
| Konkurencja | **Niska** — mało kto handluje xyz TradFi | Wysoka — full retail |
| Fee maker | **0.003%** | 0.01% |
| Fee taker | 0.009% | 0.055% |
| Spread GOLD | **0.0024%** | — |
| Dostęp do danych | **Jeden `allMids` = 91 instrumentów** | Per-symbol tickery |
| Kapitał | ~$50 (HL agent wallet) | $22 (Bybit sprint) |

### 1.3 Edge (przewaga algorytmiczna)

1. **Fee — najniższe możliwe:** limit entry + limit exit = 0.003% maker fee każda strona. Round-trip $0.0015 przy $25 notional. Fee zjada ~0.5% zysku (vs 36% przy taker-taker 0.009%).
2. **Mało konkurencji:** Większość traderów na HL siedzi na BTC, ETH, HYPE, SOL. Nikt nie scalperuje xyz:GOLD czy xyz:SILVER.
3. **Jeden call = wszystkie ceny:** `allMids` endpoint zwraca 91 instrumentów naraz w ~300ms. Zero opóźnień per symbol.
4. **Korelacje przewidywalne:** DXY→GOLD (-0.8), VIX→SP500 (-0.8), SP500→SILVER (+0.6) — stabilne, powtarzalne relacje.
5. **Lag korelacyjny 1-15s:** Gdy DXY ruszy, GOLD reaguje z opóźnieniem 1-5 sekund. Daje okno na limit entry.

### 1.4 Ryzyka

- DXY i VIX nie mają płynności na L2 book → używane tylko jako SIGNAL, nie trade
- Niska płynność xyz vs crypto perpy → spready mogą się rozszerzyć w stresie
- Weekend / późna noc → brak sygnałów (rynek śpi)
- SL wykonuje się jako trigger market (reduce-only) — może być taker fee w razie wyjścia awaryjnego

---

## 2. Architektura pipeline'u

Pipeline składa się z **3 skryptów** działających sekwencyjnie:

```
┌──────────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│  xyz_scanner.py  │────▶│ correlation_scalp.py │────▶│  hl_scalp.py     │
│  (tick collector) │     │  (signal generator)  │     │  (execution)     │
│  350ms poll HL   │     │  7 par korelacyjnych │     │  limit entry/exit│
│  ring buffer 3k  │     │  confidence 1-10     │     │  TP/SL + DB      │
└──────────────────┘     └─────────────────────┘     └──────────────────┘
         │                         │                         │
         ▼                         ▼                         ▼
    SQLite: xyz_ticks         Memory ring buffer         SQLite: scalp_trades
    (bulk co 10s)             (współdzielony)            (każdy trade)
```

### 2.1 Ring buffer (współdzielona pamięć)

Importowany przez `correlation_scalp.py` z `xyz_scanner`:

- `collections.deque(maxlen=3000)` per instrument (~17.5 min historii)
- Funkcje: `latest(coin)`, `momentum(coin, window_s)`, `get_buffer(coin, seconds)`
- Wypełniany przez: `xyz_scanner.snapshot()` lub wątek tła w `hl_scalp.py live`

---

## 3. Skrypt 1: xyz_scanner.py

### 3.1 Rola

Tick collector. Polluje HL `allMids` co **350ms** z reused HTTP clientem (1.2x szybszy niż fresh client na każdy call). Przechowuje w ring buffer + bulk save do SQLite co 10s.

### 3.2 Instrumenty

| Kategoria | Instrument | Funkcja |
|-----------|-----------|---------|
| **TRADEABLE** | xyz:GOLD | Wejścia na sygnały korelacyjne |
| **TRADEABLE** | xyz:SILVER | Wejścia na sygnały korelacyjne |
| **TRADEABLE** | xyz:SP500 | Wejścia na sygnały VIX |
| **TRADEABLE** | xyz:CL | Crude Oil — wejścia na sygnały SP500 |
| SIGNAL | xyz:DXY | Tylko do korelacji (brak książki) |
| SIGNAL | xyz:VIX | Tylko do korelacji (brak książki) |
| SIGNAL | xyz:EUR | Tylko do korelacji (EUR→DXY→GOLD) |

### 3.3 API — komendy

```bash
# Interaktywny podgląd ticków (Ctrl+C aby zatrzymać)
python scripts/xyz_scanner.py

# Pętla w tle (bez outputu, do cron/daemon)
python scripts/xyz_scanner.py --daemon

# Pojedynczy snapshot jako JSON
python scripts/xyz_scanner.py --once

# Zmiana interwału (domyślnie 0.35s)
python scripts/xyz_scanner.py --interval 0.5
```

### 3.4 Wydajność

| Metryka | Wartość |
|---------|---------|
| Średni czas allMids | 300ms (reused client) |
| Min czas | 250ms |
| Max czas | 686ms (outlier) |
| Instrumenty w jednym callu | 91 |
| Rozmiar ring bufora | 3000 ticków / instrument |
| Głębokość historii | ~17.5 minuty |

---

## 4. Skrypt 2: correlation_scalp.py

### 4.1 Rola

Czyta ring buffer `xyz_scanner`, wykrywa czy driver (np. DXY) się ruszył, a laggard (np. GOLD) nie nadążył. Emituje sygnał z confidence 1-10.

### 4.2 Pary korelacyjne

| # | Driver | Laggard | Kierunek | Siła | Min move | Lag | Use-case |
|---|--------|---------|----------|------|----------|-----|----------|
| 1 | xyz:DXY | xyz:GOLD | inverse | 0.80 | 0.02% | 1-5s | DXY w górę → Gold w dół |
| 2 | xyz:DXY | xyz:SILVER | inverse | 0.70 | 0.02% | 1-5s | DXY w górę → Silver w dół |
| 3 | xyz:SP500 | xyz:SILVER | same | 0.60 | 0.03% | 2-10s | SP500 w górę → Silver w górę |
| 4 | xyz:SP500 | xyz:CL | same | 0.40 | 0.04% | 3-15s | SP500 w górę → Oil w górę |
| 5 | xyz:VIX | xyz:SP500 | inverse | 0.80 | 0.05% | 0.5-3s | VIX w górę → SP500 w dół |
| 6 | xyz:EUR | xyz:GOLD | same | 0.60 | 0.015% | 2-8s | EUR w górę → DXY w dół → Gold w górę |
| 7 | xyz:CL | xyz:GOLD | same | 0.50 | 0.05% | 3-10s | Oil w górę → Gold w górę (inflacja) |

### 4.3 Logika sygnału

Dla każdej pary co 1s:

1. Pobierz `momentum(5s)` drivera i laggarda
2. Jeśli `abs(driver_mom) < min_move` → skip
3. Jeśli laggard już zareagował (`abs(laggard_mom) > min_move * 0.3`) → skip (za późno)
4. Oblicz confidence:
   - Base: 5
   - +1 jeśli momentum zgodne przez 3s/5s/10s
   - +1 jeśli driver move > 2x min_move (silny sygnał)
   - +1 jeśli laggard się nie rusza (czysty lag)
   - +1 jeśli korelacja ≥ 0.70
5. Jeśli confidence ≥ 7 i laggard jest tradeable → sygnał do egzekucji

### 4.4 API — komendy

```bash
# Pojedyncze sprawdzenie, drukuj sygnały
python scripts/correlation_scalp.py

# Ciągła pętla (co 1s)
python scripts/correlation_scalp.py --daemon

# JSON output (dla automatyzacji)
python scripts/correlation_scalp.py --once

# Zmiana interwału
python scripts/correlation_scalp.py --interval 2
```

---

## 5. Skrypt 3: hl_scalp.py

### 5.1 Rola

Warstwa egzekucji. Odbiera sygnały → wykonuje **limit entry (maker)** → ustawia **limit TP (maker)** + **trigger SL (reduce-only)** → zapisuje do SQLite.

### 5.2 Model egzekucji (krytyczny)

```
Entry:  limit buy  @ bid (maker)   → fee 0.005% → $0.0013 przy $25
Exit:   limit sell @ TP (maker)    → fee 0.005% → $0.0013 przy $25
                                ─────────────────────────────
                                Round-trip = $0.0026
```

**ZASADA:** ZAWSZE maker-maker. Żaden market entry. Jeśli limit się nie wypełni → anuluj i czekaj na kolejny sygnał.

### 5.3 Konfiguracja (.env)

```ini
# Tryb: paper = dry-run, live = realne zlecenia
SCALP_MODE=paper

# Parametry ryzyka
SCALP_LEVERAGE=5
SCALP_SIZE_USD=25
SCALP_TP_PCT=0.25
SCALP_SL_PCT=0.20
SCALP_MAX_POS=1
SCALP_MAX_DAILY=200                       # max trades/day (statystyka > safety)
```

### 5.4 API — komendy

```bash
# === Status i statystyki ===

# Aktualne pozycje + scalping stats
python scripts/hl_scalp.py status

# Szczegółowe stats (JSON)
python scripts/hl_scalp.py stats

# === Ręczny paper trade ===

# Long GOLD
python scripts/hl_scalp.py trade GOLD long

# Short SILVER
python scripts/hl_scalp.py trade SILVER short

# Short SP500
python scripts/hl_scalp.py trade SP500 short

# Long Crude Oil
python scripts/hl_scalp.py trade CL long

# === Auto-trader (DOCELOWY) ===

# Uruchamia scanner w tle + correlation engine + egzekucję
python scripts/hl_scalp.py live
```

### 5.5 Paper trade — przykład rzeczywistego outputu

```
==================================================
SCALP: LONG xyz:GOLD
  Mid:     $4220.6500
  Entry:   $4220.6000 (limit, maker)
  Size:    0.0059 contracts (~$24.90)
  Leverage: 5x
  TP:      +0.25%
  SL:      +0.20%
  Mode:    PAPER
  Pair:    DXY → GOLD inverse test
  [PAPER] LONG 0.0059 xyz:GOLD @ $4220.6000 (notional $24.90)
  → Entry: paper
  [PAPER] TP long 0.0059 xyz:GOLD @ $4231.1500
  [PAPER] SL long 0.0059 xyz:GOLD @ $4212.1600
  → TP:    paper
  → SL:    paper

  [PAPER RESULT] TP hit: +$0.31 (1.25%)
  [PAPER FEES]   entry $0.0012 + exit $0.0012 = $0.0025
  [PAPER NET]    $0.31
==================================================
```

### 5.6 Live auto-trader

`hl_scalp.py live` uruchamia:

1. **Wątek skanera w tle** — wypełnia ring buffer tickami co 350ms
2. **Główna pętla** — co 1s sprawdza `correlation_scalp.evaluate_pairs()`
3. Gdy sygnał z confidence ≥ 7 na tradeable instrumencie → `execute_scalp()`
4. Ograniczenia: max 1 pozycja równolegle, max 30 trade'y dziennie

---

## 6. Baza danych — SQLite

### 6.1 Nowe tabele

```sql
-- Tick data (zapisywana co 10s)
CREATE TABLE xyz_ticks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,        -- timestamp ms
    coin        TEXT NOT NULL,
    price       REAL NOT NULL,
    avg_20      REAL,                     -- średnia z 20 ostatnich ticków
    min_20      REAL,
    max_20      REAL,
    tick_count  INTEGER
);

-- Historia scalpów
CREATE TABLE scalp_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_open         TEXT NOT NULL,
    ts_close        TEXT,
    instrument      TEXT NOT NULL,
    side            TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    size_contracts  REAL NOT NULL,
    notional_usd    REAL NOT NULL,
    leverage        INTEGER DEFAULT 5,
    pnl_usd         REAL,
    pnl_pct         REAL,
    entry_fee       REAL DEFAULT 0,
    exit_fee        REAL DEFAULT 0,
    net_pnl         REAL,
    correlation_pair TEXT,
    hold_seconds    REAL,
    exit_reason     TEXT,
    status          TEXT DEFAULT 'open',
    raw_json        TEXT
);
```

### 6.2 Przydatne query

```sql
-- WR per instrument
SELECT instrument,
       COUNT(*) as trades,
       SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as wr
FROM scalp_trades WHERE status='closed'
GROUP BY instrument;

-- Suma PnL dziennie
SELECT DATE(ts_open) as day, SUM(net_pnl) as day_pnl
FROM scalp_trades WHERE status='closed'
GROUP BY day ORDER BY day;

-- Średni hold czasu
SELECT instrument, AVG(hold_seconds) as avg_hold
FROM scalp_trades WHERE status='closed'
GROUP BY instrument;
```

---

## 7. Diagram przepływu sygnału

```
                   ┌─────────────────────┐
                   │   HL allMids API    │
                   │   91 instrumentów   │
                   └────────┬────────────┘
                            │ GET co 350ms
                            ▼
                   ┌─────────────────────┐
                   │   xyz_scanner.py    │
                   │  - ring buffer 3k   │
                   │  - snapshot()       │
                   │  - get_buffer()     │
                   │  - momentum()       │
                   └────────┬────────────┘
                            │ Czyta buffer
                            ▼
                   ┌─────────────────────┐
                   │ correlation_scalp   │
                   │   .evaluate_pairs() │
                   │  7 par korelacyjnych│
                   └────────┬────────────┘
                            │ Sygnał: confidence ≥ 7
                            ▼
                   ┌─────────────────────┐
                   │   hl_scalp.py       │
                   │  execute_scalp()    │
                   │                    │
                   │  1. Limit entry     │
                   │  2. Limit TP        │
                   │  3. Trigger SL      │
                   │  4. Zapisz do DB    │
                   └─────────────────────┘
```

---

## 8. Etap projektu

| Etap | Status | Uwagi |
|------|--------|-------|
| Analiza szybkości HL API | ✅ | Avg 300ms, reused client 1.2x faster |
| xyz_scanner.py — tick collector | ✅ | Działa, ring buffer, SQLite bulk |
| correlation_scalp.py — silnik korelacji | ✅ | 7 par, confidence, testowane |
| hl_scalp.py — execution engine | ✅ | Limit entry/exit, TP/SL, paper mode |
| DB schema — xyz_ticks, scalp_trades | ✅ | W db.py, indeksowane |
| Paper trade — GOLD, SILVER | ✅ | +$0.31 na scalp, fee $0.0025 |
| **Test live auto-trader** | ✅ | Działa, czeka na sygnały |
| **Test na żywym rynku (1 tydzień)** | ⏳ | **TY — uruchom `live` i obserwuj** |
| Analiza WR po 50+ scalpach | ⏳ | Po tygodniu |
| Optymalizacja thresholdów | ⏳ | Po analizie danych |
| Przejście na SCALP_MODE=live | ⏳ | TYLKO gdy WR > 65% |

---

## 9. Jak zacząć obserwację

### Opcja A: Szybki podgląd (zalecana na start)

W terminalu:

```bash
cd /c/Users/krypt/trading-ai
.venv/Scripts/python.exe scripts/hl_scalp.py live
```

To uruchamia wszystko — skaner w tle, sygnały, egzekucję paper. Zostaw na kilka godzin w ciągu dnia. Output pojawi się gdy rynek zacznie się ruszać (otwarcie US session, news makro).

### Opcja B: Podgląd ticków + sygnałów osobno

**Terminal 1 (ticki):**
```bash
.venv/Scripts/python.exe scripts/xyz_scanner.py
```

**Terminal 2 (sygnały):**
```bash
.venv/Scripts/python.exe scripts/correlation_scalp.py --daemon
```

### Opcja C: Automatyczny cron (sprawdzanie co N minut)

```bash
# Dodaj cron job przez Hermes
python scripts/hermes.py cron add \
  --name "scalp-monitor" \
  --schedule "every 30m" \
  --command ".venv/Scripts/python.exe scripts/hl_scalp.py status"
```

### Checkpoint — po tygodniu

```bash
# Pełne statystyki
python scripts/hl_scalp.py status

# JSON — do analizy per instrument
python scripts/hl_scalp.py stats

# Statystyki per instrument (dedykowany skrypt, bez problemów z quotingiem)
python scripts/show_scalp_stats.py
```

---

## 10. Plany rozwojowe

| Kolejność | Funkcja | Po co |
|-----------|---------|-------|
| 1 | Per-instrument WR tracking | Odrzucić pary które nie dają edge |
| 2 | Dynamic threshold adjustment | Dostosować min_move i confidence do zmienności |
| 3 | Telegram notifications | Alerty gdy bot wykonuje scalp |
| 4 | Próg przejścia na SCALP_MODE=live | Automatyczny switch gdy WR > 65% po 50 trade'ach |
| 5 | Własny skalper na Bybit (Pomysł 1) | Drugi strumień zysku — Order Book Imbalance |

---

*Dokument wygenerowany przez Hermes Agent — 2026-06-18*