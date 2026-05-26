# BlogWatcher v2 — Słownik komend
> Skopiuj komendę → wklej w terminal → gotowe.
> Wszystkie komendy uruchamiaj z katalogu `C:\Users\markowyy\trading-ai\`

---

## 🚀 Najczęściej używane — zacznij od tutaj

### 0. ⭐ MARKET SCAN — czysty obraz rynku (bez Twojej księgi)
```powershell
python scripts/blogwatcher.py --market-scan
```
**Co dostaniesz:**
- NEWS BRIEFING — co się dzieje w 5 tematach (Fed, Geopolityka, Crypto, Metals, Energia)
- TOP HEADLINES — pogrupowane tematycznie
- ASSET IMPACT TABLE — net sentiment dla WSZYSTKICH 18 aktywów
- MARKET OPPORTUNITIES — newsowy bias dla WSZYSTKICH aktywów (nie filtruje po tym co masz)

**Czego NIE dostaniesz:** żadnej wzmianki o Twoich otwartych pozycjach. Zupełnie czysty obraz rynku.

**Kiedy używać:**
> Przed analizą wykresu przez Hermesa/Telegrama — "Hermesie, zrób wejścia/wyjścia/SL/TP"
> Chcesz wiedzieć co newsy mówią o danym aktywie ZANIM zdecydujesz czy wchodzić
> Rano, zanim sprawdzisz pozycje — najpierw zbadaj rynek obiektywnie

```powershell
# Z zapisem do pliku (polecane — potem wklejasz Hermesowi jako kontekst)
python scripts/blogwatcher.py --market-scan --output reports/market_scan_today.md
```

**Koszt:** ~7 kredytów Firecrawl

---

### 1. Pełny raport + Twoje pozycje (standard daily)
```powershell
python scripts/blogwatcher.py --positions positions.json
```
**Co dostaniesz:**
- Legenda symboli
- NEWS BRIEFING — skrót co się dzieje w 5 tematach (Fed, Geopolityka, Crypto, Metals, Energia)
- TOP HEADLINES — nagłówki pogrupowane tematycznie
- ASSET IMPACT TABLE — 18 aktywów, net sentiment (BULL/BEAR/MIXED/--)
- POSITION IMPACTS — jak newsy uderzają w Twoje otwarte pozycje (TEZA WZMOCNIONA / POD PRESJĄ / MIXED)
- TRADE OPPORTUNITIES — aktywa bez pozycji, gdzie jest silny bias newsowy

**Koszt:** ~7 kredytów Firecrawl

---

### 2. Tylko newsy — bez analizy pozycji (szybki przegląd rynku)
```powershell
python scripts/blogwatcher.py --news-only
```
**Co dostaniesz:**
- Legenda
- NEWS BRIEFING (5 tematów z opisami)
- TOP HEADLINES (pogrupowane)
- ASSET IMPACT TABLE

**Koszt:** ~7 kredytów Firecrawl

---

### 3. Zapisz raport do pliku (zamiast wyświetlać w terminalu)
```powershell
python scripts/blogwatcher.py --positions positions.json --output reports/blogwatcher_today.md
```
**Co dostaniesz:** plik `.md` gotowy do otwarcia w VSCode/Obsidian/Notepad++

**Wskazówka:** Otwórz w VSCode z rozszerzeniem Markdown Preview — tabele i emoji wyglądają świetnie.

---

### 4. Pełny raport + zapisz do pliku (combo)
```powershell
python scripts/blogwatcher.py --positions positions.json --output reports/blogwatcher_today.md
```
*(to samo co wyżej — `--output` nie wyklucza `--positions`)*

---

## 🔁 Cache replay — zero kredytów

### 5. Ponowne renderowanie z wcześniej pobranych danych
```powershell
python scripts/blogwatcher.py --from-cache 20250524_1430 --positions positions.json
```
**Co robi:** Wczytuje pliki z `.firecrawl/blogwatcher/20250524_1430_*.json` — bez nowego scrapowania.
**Kiedy używać:** Chcesz zobaczyć te same newsy z innymi flagami (np. `--top 20`, `--news-only`) bez zużywania kredytów.

**Jak znaleźć stamp (timestamp):**
```powershell
dir .firecrawl\blogwatcher\ | Select-Object -Last 20
```
Stamp to pierwsza część nazwy pliku, np. `20250524_1430` z pliku `20250524_1430_kitco.json`.

---

### 6. Cache replay + tylko newsy (bez pozycji)
```powershell
python scripts/blogwatcher.py --from-cache 20250524_1430 --news-only
```

---

### 7. Cache replay + pokaż wszystkie artykuły (bez limitu)
```powershell
python scripts/blogwatcher.py --from-cache 20250524_1430 --top 0
```
**Co robi:** Domyślnie MACRO PULSE pokazuje top 8 artykułów. `--top 0` = pokaż wszystkie.

---

## 🎯 Wybór źródeł

### 8. Tylko wybrane źródła (oszczędność kredytów)
```powershell
python scripts/blogwatcher.py --sources coindesk,theblock
```
```powershell
python scripts/blogwatcher.py --sources kitco,oilprice
```
```powershell
python scripts/blogwatcher.py --sources reuters_world,reuters_markets
```

**Dostępne źródła:**
| Klucz | Co scrape'uje | Naturalna tematyka |
|-------|---------------|--------------------|
| `coindesk` | CoinDesk Markets | ₿ Crypto |
| `theblock` | The Block Latest | ₿ Crypto / DeFi |
| `reuters_markets` | Reuters Financial Markets | 🏦 Fed / Macro / Equities |
| `reuters_world` | Reuters World | 🌍 Geopolityka |
| `kitco` | Kitco Gold & Silver | 🥇 Metals |
| `oilprice` | OilPrice.com | 🛢️ Energia |
| `barchart` | Barchart Agriculture | 🌾 Agriculture |
| `fed` | Federal Reserve press releases | 🏦 Fed / Macro |
| `bbc_world` | BBC World News | 🌍 Geopolityka |

---

### 9. Wszystkie źródła (core + fallback + backup)
```powershell
python scripts/blogwatcher.py --tier all --positions positions.json
```
**Koszt:** ~9–10 kredytów

---

### 10. Tylko tier core_fallback (core + BBC + FED)
```powershell
python scripts/blogwatcher.py --tier core_fallback --positions positions.json
```

---

## 📊 Kontrola output

### 11. Pokaż więcej artykułów w MACRO PULSE (np. top 15)
```powershell
python scripts/blogwatcher.py --top 15 --positions positions.json
```

### 12. Pokaż WSZYSTKIE artykuły w MACRO PULSE
```powershell
python scripts/blogwatcher.py --top 0 --positions positions.json
```

### 13. Surowy JSON (do debugowania lub integracji)
```powershell
python scripts/blogwatcher.py --json > articles.json
```
**Co dostaniesz:** Lista wszystkich sparsowanych artykułów w formacie JSON z polami:
`headline`, `summary`, `affected_assets`, `sentiment`, `impact`, `category`, `source`, `ts`

---

## 🧪 Testowanie / dry run

### 14. Sprawdź URLs bez scrapowania (zero kredytów)
```powershell
python scripts/blogwatcher.py --dry-run
```
**Co robi:** Wypisuje listę URL-i które zostałyby scrapowane — nie zużywa kredytów Firecrawl.

---

## ⏱️ Kombinacje na co dzień

### Poranny brief (7:00–8:00) — pełna analiza z pozycjami
```powershell
python scripts/blogwatcher.py --positions positions.json --output reports/brief_morning.md
```

### Przed analizą wykresu (Hermes / Telegram) — market scan BEZ pozycji
```powershell
python scripts/blogwatcher.py --market-scan --output reports/market_scan_today.md
```
> Daj Hermesowi ten plik jako kontekst → "na podstawie tego zrób mi SL/TP/entry dla BTC"

### Szybki mid-day check (bez zapisywania)
```powershell
python scripts/blogwatcher.py --news-only --top 5
```

### Pre-close (przed zamknięciem US, 21:30 PL) — geopolitics + markets
```powershell
python scripts/blogwatcher.py --sources reuters_world,reuters_markets,coindesk --positions positions.json
```

### Crypto-only (po weekendzie)
```powershell
python scripts/blogwatcher.py --sources coindesk,theblock --market-scan
```

### Commodities check (przed otwarciem Londynu, 9:00 PL)
```powershell
python scripts/blogwatcher.py --sources kitco,oilprice,barchart --market-scan
```

---

## 📋 Legenda output — skrót

| Symbol | Znaczenie |
|--------|-----------|
| `[+]` | Bullish — news pozytywny dla ceny |
| `[-]` | Bearish — news negatywny dla ceny |
| `[~]` | Neutral / Mixed |
| `[!!!]` | HIGH impact — market mover |
| `[!!]` | MEDIUM impact |
| `[!]` | LOW impact |
| `BULL` | Więcej bullish niż bearish hits w danym dniu |
| `BEAR` | Więcej bearish |
| `MIXED` | Bull = Bear (sprzeczne sygnały) |
| `—` | Brak news dla tego aktywa |
| `[OK] TEZA WZMOCNIONA` | News zgodny z Twoją pozycją |
| `[!] TEZA POD PRESJĄ` | News sprzeczny z pozycją |
| `[~] MIXED` | Niejasny sygnał |

---

## 🗂️ Gdzie są pliki

| Co | Ścieżka |
|----|---------|
| Skrypt | `scripts/blogwatcher.py` |
| Config (aktywa, źródła) | `config/assets.json` |
| Pozycje (ręczny plik) | `positions.json` |
| Cache scrapy (JSON) | `.firecrawl/blogwatcher/` |
| Raporty (jeśli `--output`) | `reports/` (utwórz folder jeśli nie istnieje) |

---

## ⚠️ Limity Firecrawl

| Plan | Kredyty/miesiąc | Rotacja kluczy |
|------|-----------------|----------------|
| Free x2 | 2000 / miesiąc | FIRECRAWL_API_KEY + FIRECRAWL_API_KEY_2 |
| 1 pełny run (7 źródeł) | ~7 kredytów | tak |
| Maks. runów/miesiąc | ~285 | — |

**Wskazówka oszczędnościowa:** Używaj `--from-cache STAMP` do re-renderowania już pobranych danych — zero kredytów.

---

*Ostatnia aktualizacja: 2026-05-24*
