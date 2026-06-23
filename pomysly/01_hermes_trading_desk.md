# Pomysł #1 — Hermes Trading Desk

> **Jeden agent-trader przeżywa dzień jak człowiek-profesjonalista — ale szybciej,
> bez emocji i bez przeoczeń.** Najbliższe temu, co opisałeś: wstaje, czyta rynek,
> planuje, handluje, pilnuje, zamyka/odwraca, wieczorem robi rozrachunek.

**Filozofia:** spójna „osobowość" tradera w cyklu dobowym. Najprostszy start, bo
reużywa to, co masz (`hermes.py` Daily Alpha Brief, scanery, executory, dziennik edge).

---

## Dzień z życia agenta (cron schedule)

Każda faza to osobny cron job w Hermesie. Czasy UTC (dostosuj do sesji, którą gramy).

| Godz. (UTC) | Faza | Co robi | Model | Output |
|---|---|---|---|---|
| **06:30** | 🌅 Pre-market | `hermes.py` (brief) + kalendarz + pozycje + overnight news | tani→średni | **Plan dnia**: watchlista, bias, kluczowe poziomy, ryzyka dnia |
| **co 15 min w sesji** | 👀 Skaner setupów | dla watchlisty: czy cena doszła do poziomu + confluence (whale/OI/sentyment) | tani | „setup gotowy na X" lub cisza |
| **na trigger setupu** | 🎯 Decyzja | mocny model ocenia setup: wchodzę? rozmiar? SL/TP? | **mocny** | decyzja JSON → executor |
| **co 30–60 min** | 🩺 Position Watch | re-ocena każdej otwartej pozycji vs teza + nowe dane | średni | trzymaj / dokup / przytnij / zamknij / odwróć |
| **−30 min do zamknięcia płynności** | 🌆 De-risk | realizacja zysków / redukcja przed cienkimi godzinami | tani | trim/close |
| **21:30** | 📔 EOD review | co zadziałało, co nie → wpis do `edge_journal.py` + DB | średni | dziennik + lekcje na jutro |
| **niedziela** | 📊 Weekly review | analiza tygodnia, propozycje zmian parametrów | mocny | raport + tweak-lista |

Pętla się domyka: **EOD review zasila Plan dnia następnego ranka** (przez `db.py context-daily`,
które już masz). Agent „pamięta" wczoraj i nie powtarza błędów.

---

## Jak myśli przy decyzji (warstwa Strategist)

Setup nie wystarcza — agent gra jak ekspert, czyli z **checklistą i adwokatem diabła**:

1. **Teza** — jedno zdanie: czemu ten trade ma sens (np. „BTC odbija od wsparcia $61k,
   whale net-long rośnie, funding neutralny, kalendarz pusty do 14:30").
2. **Confluence score** — ile niezależnych czynników się zgadza (trend / whale / OI /
   sentyment / poziom techniczny). Próg np. ≥4/6.
3. **Pre-mortem (adwokat diabła)** — osobny szybki prompt: „podaj 3 powody, czemu ten trade
   to błąd". Jeśli któryś jest poważny → veto albo mniejszy rozmiar.
4. **Risk gate (kod)** — ryzyko ≤2%, jest SL, nie przekraczamy max pozycji/dzień, kalendarz
   nie ma high-impact eventu w ciągu 30 min.
5. **Wykonanie** — `executor` składa maker entry + SL + TP. LLM tylko zwrócił JSON.

---

## Narzędzia, które spina (wszystko już masz)

- **Dane:** `hermes.py`, `econ_calendar.py`, `oi_tracker.py`, `cot_tracker.py`,
  `fear_greed.py`, `hl_whale_tracker.py`, `x_sentiment.py`, `macro_news.py`, `polymarket.py`,
  `token_dashboard.py`.
- **Pozycje:** `fetch_positions.py` (4 venue naraz).
- **Wykres/poziomy:** TradingView MCP (`quote_get`, `data_get_study_values`, poziomy Pine).
- **Wykonanie:** `hl_executor.py` / `extended_order.py` / `alpaca_executor.py` / Bybit MCP.
- **Pamięć/nauka:** `edge_journal.py`, `db.py` (briefy + historia).
- **Kokpit:** Telegram (plan, zgody, `flatten`).

---

## Tryby i bezpieczeństwo

- Start: **SHADOW** — wszystkie decyzje logowane jako paper, porównujemy z rynkiem 2–4 tyg.
- Potem: **SEMI-AUTO** — plan i każdy nowy trade idą na Telegram po `approve`.
- Na końcu: **FULL-AUTO** — z twardym dziennym kill-switchem (−3% → flatten + pauza do jutra).

---

## ✅ Plusy / ⚠️ Minusy

**Plusy:** intuicyjny, łatwy do debugowania (dyskretne uruchomienia = czytelne logi),
naturalnie ograniczony kosztowo, reużywa istniejący `hermes.py`. Najszybszy do pierwszego
shadow-runu.

**Minusy:** cykliczny rytm może przegapić gwałtowny ruch między uruchomieniami. *Mitygacja:*
scanery (`volume_scanner`, `liqscalp`, whale alerts) wysyłają **event-trigger** na Telegram/bus,
który budzi fazę Decyzji poza harmonogramem.

**Dla kogo:** najlepszy **pierwszy krok**. Buduje nawyk i infrastrukturę, na której staną #2 i #3.
