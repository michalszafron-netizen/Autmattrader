# 🦅 LiqScalp Bot — Liquidation-Cascade Fade (Bybit perps)

Bot scalpowy #1. Fade wymuszonych likwidacji: kaskada likwidacji przepycha cenę
za daleko (forced flow), a my łapiemy mean-reversion po jej wyczerpaniu.

**Giełda wykonania:** Bybit perps USDT (potwierdzone działanie konta, region POL).
**Zasada żelazna:** żaden paper/live, dopóki Faza 0 nie udowodni edge po fee.

Pełny opis edge + dwa odłożone systemy: [`ScalpBots_Roadmap_Future.md`](ScalpBots_Roadmap_Future.md)

---

## Status faz

| Faza | Co | Status |
|---|---|---|
| **0 — Pomiar** | kolektor → `research.py` raport edge | 🔑 **WYNIK: fade martwy, momentum dodatni ale cienki** |
| 1 — Paper | detektor + egzekucja symulowana | 🟢 egzekucja gotowa; ⏸️ czeka na refine momentum + więcej danych |
| 2 — Live micro | mikro-rozmiar, ryzyko ≤2%, kill-switch | ⏳ po walidacji paper |

### 🔑 Wynik Fazy 0 (2026-06-22, ~68h, 6437 likwidacji, dwustronne)

`python scripts\liqscalp\research.py` (+ `--follow`, `--entry extreme`, `--short`, `--fee-bps`)

- **FADE (oryginalna teza fade-kaskady) = STRATNY** pod każdym założeniem (market/extreme entry,
  każdy horyzont, oba kierunki). Kaskady = **kontynuacja**, nie wyczerpanie. Większa kaskada = gorszy fade.
- **MOMENTUM (follow — iść Z kaskadą) = DODATNI, rośnie z czasem trzymania.**
  Najlepsza konfig: **ETH+SOL (bez BTC), follow, hold ~60min, taker fee 11bps** → **+0.17%/trade,
  63% win** (SOL: +0.27%, 69% win). Edge rośnie 15→60min. To **godzinny momentum, nie scalp.**
  Asymetria: SHORT (sell-kaskady) mocny 70% win, LONG słaby 50% — pewnie artefakt trendu spadkowego.

```
python research.py --follow --only ETHUSDT,SOLUSDT --fee-bps 11 --long
```

- **Decyzja:** nie budujemy fade-bota; momentum to mocny LEAD, nie green-light. Ograniczenia:
  (1) JEDEN reżim (3 dni trendu spadkowego) — to największe ryzyko, (2) exity wyidealizowane
  (stały hold, bez SL/TP), (3) mała próba, (4) slippage taker niemodelowany.
- **Następny krok (decydujący):** WIĘCEJ DANYCH (różne reżimy) + symulacja realnych SL/TP
  (ścieżka wewnątrz trade'u, nie stały hold). Bez tego nie ma paper. NIE przestrajać dalej na
  tych 3 dniach — to by było overfit.

### Warstwa egzekucji (gotowa, przetestowana w paper)

| Plik | Rola |
|---|---|
| `config.py` | ustawienia z `.env` (prefix `LIQSCALP_`) + TWARDE limity ryzyka (cap 2%/trade, halt 3%/dzień) |
| `bybit_rest.py` | klient Bybit v5 REST: market/account/order (podpis HMAC) |
| `executor.py` | sizing wg ryzyka, zaokrąglenia tick/qty, maker entry, **obowiązkowy SL+TP**, bramki bezpieczeństwa, paper-sim |

Test ręczny (paper, zero realnych zleceń):
```
python scripts\liqscalp\executor.py paper SOLUSDT long
python scripts\liqscalp\executor.py paper XAUTUSDT short --sl-pct 0.6 --tp-pct 0.4
```

Zasady wbudowane (nieprzekraczalne): domyślnie PAPER · ryzyko ≤2% equity · każde wejście
MA stop-loss (bez SL = blok) · max pozycji + max trade'ów/dzień · kill-switch przy stracie
dziennej >3% (live).

**Brakuje (świadomie — po Fazie 0):** `signal.py` (detektor klastra/wyczerpania — progi
strojone na danych) i `bot.py` (pętla WS→sygnał→executor + heartbeat). Logika sygnału
zostanie napisana, gdy obejrzę realne eventy likwidacji, żeby nie zgadywać semantyki pól.

---

## Pliki

| Plik | Rola |
|---|---|
| `collector.py` | Faza 0 — łączy się z Bybit WS, zapisuje likwidacje + cenę do `data/liqscalp.db` |
| `store.py` | warstwa SQLite (własna baza, NIE dotyka głównego `db.py`) |
| `run_collector.bat` | uruchom kolektor w osobnym oknie (zostaw otwarte) |
| `run_stats.bat` | podgląd ile danych zebrano |
| `research.py` | *(powstanie po zebraniu próbki likwidacji)* — liczy edge: overshoot, % powrotów, expectancy po fee przy różnych progach |
| `_ws_probe.py`, `_bybit_check.py`, `_bybit_set_sl.py` | jednorazowe narzędzia diagnostyczne — można usunąć |

---

## Jak zbierać dane (Faza 0)

Uruchom kolektor i zostaw okno otwarte (najlepiej na 2–4 dni, w tym jakaś
zmienna sesja):

```
scripts\liqscalp\run_collector.bat
```

Podgląd postępu w dowolnym momencie:

```
scripts\liqscalp\run_stats.bat
```

Koszyk domyślny (11 symboli, dobrany wg wolumenu 24h sprawdzonego na żywo):

| Grupa | Symbole | Po co |
|---|---|---|
| Crypto majors + hot | BTC, ETH, SOL, **HYPE**, DOGE, 1000PEPE, WIF | najbogatsze w likwidacje (HYPE ~$474M/d) |
| Metale | **XAUT** (złoto), **XAG** (srebro) | realny wolumen ($55M / $32M dz.) — metale lubią ruchy makro |
| Equity świeży debiut | **SPCX** (SpaceX, Elon) | realnie płynny ~$43M/d — świeży debiut + hype = zmienność |
| Equity/indeks (discovery) | **NVDA**, **SPX** (S&P 500) | bardzo cienkie ($1.7M / $6M dz.) — sprawdzamy czy w ogóle dają kaskady |

Zmiana: `collector.py --symbols BTCUSDT,ETHUSDT,...`

**Czego NIE ma na Bybit perps:** ropa (WTI/Brent), Nasdaq (NDX). Stokenizowane spółki
NVDA/TSLA/AAPL są, ale o płynności $0.1–1.7M/dzień — zbyt cienkie. SpaceX **jest** jako
**SPCX** i akurat jest płynny ($43M/d, świeży debiut). Ropa i Nasdaq istnieją za to na
Hyperliquid xyz — patrz plan awaryjny w [`ScalpBots_Roadmap_Future.md`](ScalpBots_Roadmap_Future.md).

---

## ⏰ Godziny rynku — WAŻNE dla pomiaru

Koszyk ma dwie natury:

| Grupa | Handel | Likwidacje w weekend? |
|---|---|---|
| Crypto (BTC ETH SOL HYPE DOGE 1000PEPE WIF) | **24/7** | ✅ tak — pełna doba, też sobota/niedziela |
| Metale (XAUT, XAG) | pon–pt ~24h, zamknięte weekend | ❌ martwe od pt ~21:00 UTC do niedz ~22:00 UTC |
| Equity/indeks (SPCX, NVDA, SPX) | godziny giełdy US (pon–pt) | ❌ martwe cały weekend, wracają **pon ~14:30 UTC** |

**Wniosek:** edge na **crypto mierzymy z danych weekendowych** (lecą 24/7 — weekend crypto
bywa nawet bardziej wybuchowy przez cieńszą książkę). Edge na **metalach/akcjach mierzymy
dopiero w przyszłym tygodniu** (pon–pt), bo w weekend te symbole mają zamrożoną cenę i zero
kaskad. Dlatego kolektor trzymamy włączony **przez cały tydzień**, nie tylko weekend.

## Co dalej

Gdy uzbiera się sensowna próbka likwidacji (najlepiej kilkaset zdarzeń, w tym
jeden-dwa większe „dumpy"), zbuduję `research.py`, który odpowie na pytanie
**czy to skarb**: ile jest przestrzelenie, jaki % kaskad się odwraca, jaki TP/SL
i jaka oczekiwana wartość per trade **po odjęciu fee** — przy różnych progach
częstotliwości. Dopiero dodatni wynik otwiera Fazę 1 (paper).
