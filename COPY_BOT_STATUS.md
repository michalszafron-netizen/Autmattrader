# 📊 Copy Bot — raport stanu (gdzie jesteśmy)

**Ostatnia aktualizacja: 2026-06-16** | Status: **PAPER, faza obserwacji 6 traderów**

> Ten dokument = pamięć projektu copy-trading. Czytaj go najpierw przy wznowieniu pracy.
> Komendy: `KOMENDY_COPY_BOT.md`. Serwer: `SERWER.md` → sekcja Copy Bot.

---

## 🎯 Cel i filozofia

Własny copy-trading na Hyperliquid **bez Senpi** (zero opłaty pośrednika 0.05%/trade).
Śledzimy kilku dobrych traderów HL, kopiujemy ich pozycje proporcjonalnie do kapitału.
Model: **target-position reconciliation** (nie kopiowanie fillów) — porównujemy CEL
(jego pozycja × ratio) z naszym stanem i wykonujemy tylko różnicę. Dzięki temu drabinkowe
fille tradera nie generują u nas spamu zleceń.

**Decyzja architektoniczna (2026-06):** Senpi odrzucony do egzekucji (haracz 0.05% > opłata
giełdy 0.045%, ponad podwaja koszt). Senpi zostaje tylko do *discovery* (znajdowanie traderów),
i to opcjonalnie — mamy własne wyszukiwanie przez publiczne HL API.

---

## 🟢 Stan obecny (2026-06-16)

- **Tryb:** PAPER (symulacja, ZERO realnych pieniędzy). Live = jeszcze nie zaimplementowane.
- **Działa:** 24/7 na VPS jako systemd `trading-copybot` (auto-restart, przeżywa reboot).
- **Kapitał:** $200/trader (globalnie), `0x4b1c` ma override $1000.
- **6 traderów pod obserwacją:**

| Adres | Kapitał | Profil | Status obserwacji |
|-------|---------|--------|-------------------|
| `0x4b1c` | $1000 | Maszyna HFT, $2M konto, ~26 poz, zawsze aktywny | Realnie zarabia (+$19k/tydz na koncie). Trudny/drogi do kopiowania (HFT). $1000 daje 69% pokrycia (było 34% @ $200) |
| `0xba93` | $200 | Konserwatywny, 2.5 roku, DD-10%, WR93% | Działa, ale pozycje za małe — przy $200 często <min $10. Słaby do tego kapitału |
| `0x83b0` | $200 | Prosty 2-poz (ETH-S/HYPE-L), all-time **+2175%** | NOWY. 2/2 kopiowalne. Najlepszy profil — prosty, sprawdzony długoterminowo |
| `0x75c2` | $200 | 4-poz longi (WLD/RENDER/HYPE/FART), all-time +387% | NOWY. 4/4 kopiowalne. Bias long (przeciwwaga do shortów 0x4b1c) |
| `0x48ec` | $200 | Prosty 2-poz (BTC-S/ETH-L), konto $60k | NOWY. 2/2 kopiowalne |
| `0xe21b` | $200 | Snajper HYPE, all-time **+$408k**, robi DŁUGIE przerwy | Obserwacja — był martwy 5+ dni. Trzymamy bo gdy wraca może zrobić mocne trejdy. Łapiemy moment powrotu |

**Następny krok:** zebrać 3-4+ dni danych (od 2026-06-16 reset), potem `--report` →
pierwszy uczciwy ranking PnL → wybór zwycięzcy → decyzja o live.

---

## 🛠️ Co zbudowano (chronologicznie)

1. **`shadow_copy_tracker.py`** — pierwsza wersja, śledziła pojedynczego tradera przez
   `userFillsByTime`. Pokazała że per-fill to zły model (drabinki dają fałszywe „0% kopiowalnych").
2. **`copy_bot.py`** — właściwy bot. Target-position reconciliation, paper mode, obowiązkowy SL -8%.
3. **Multi-trader** — śledzenie kilku naraz, osobny wirtualny portfel per trader (SQLite).
4. **Deploy VPS** — systemd `trading-copybot`, 24/7, niezależny od laptopa.
5. **PnL per trader** (`--report`) — zrealizowany (z CLOSE/REDUCE) + niezrealizowany (otwarte
   vs ceny teraz), ranking wg % (sprawiedliwie przy różnych kapitałach).
6. **Kapitał per-trader** (`capital_usd` w configu) — bo trader z $2M kontem wymaga więcej
   niż $200 żeby go wiernie kopiować.

---

## 🧠 Kluczowe lekcje (NIE zapomnieć)

1. **maxDrawdown z rankingu kłamie** — liczy wąskie okno. Zawsze ciągnij pełną krzywą all-time
   (`portfolio` endpoint). Trader `0xd8f3` miał „0% DD" w rankingu, all-time PnL -$745k.
2. **averageTradesPerDay ≠ liczba decyzji** — liczy fille z drabinkowania. `0xe21b` „18/dzień"
   = realnie ~0.6 zamknięć/dzień. Realną częstotliwość bierz z historii zamknięć.
3. **Wysoki win rate = pułapka** (bag-holder trzyma stratne pozycje miesiącami). Waż drawdown wyżej.
4. **Kapitał musi pasować do tradera** — trader z 26 pozycjami i $2M kontem za $200 = kopiujesz
   losowy wycinek 34% → pomiar bezsensowny. Mało pozycji + mniejsze konto = wierne kopiowanie za $200.
5. **Traderzy znikają** — `0xe21b` wyszedł do zera na dni. Bot musi to wykrywać (zamyka pozycje
   gdy trader na zero) — NAPRAWIONE. Kopiowanie jednego = ryzyko martwych okien → trzymaj kilku.
6. **Koszt kopiowania = styl tradera, nie kwota.** HFT (dużo ruchów) = dużo opłat. Maker-limit
   zbija opłatę giełdy (0.045→0.015) ale nie ruchliwość. Preferuj traderów co robią mniej, większych ruchów.

---

## 🔍 System wyszukiwania traderów (DWA podejścia)

### A) Senpi MCP (bogatszy, ale ROZŁĄCZONY) — patrz sekcja niżej
Discovery Senpi miało ~10 narzędzi analitycznych: `discovery_get_top_traders` (filtry: activity
DEGEN/ACTIVE, consistency ELITE/RELIABLE, sort GAIN_TO_PAIN_RATIO, open_position_filter),
`discovery_get_trader_state/history`, `strategy_get_pnl_and_account_value_history`,
`leaderboard_get_top` (4h momentum) + etykiety TAS/TCS/risk. To był plan na **Wallet Analyzer
w dashboardzie** (roadmap 1.3): wklejasz adres → werdykt KOPIUJ/OBSERWUJ/UNIKAJ.

### B) Własne wyszukiwanie przez publiczne HL API (DZIAŁA, użyte 2026-06-16)
Gdy Senpi padł, użyliśmy `stats-data.hyperliquid.xyz/Mainnet/leaderboard` (39k traderów) +
`clearinghouseState` per wallet. Filtr który zadziałał:
- top 60 wg ROI miesięcznego
- konto ≥ $3000 (nie mikro 1-strzały)
- aktywny w ostatnich 48h (lekcja z 0xe21b)
- **1-6 pozycji** (kluczowe — kopiowalne wiernie za $200)
- weryfikacja: all-time ROI > 0 (nie odbicie po stratach — odrzuciliśmy `0x6ab645ff` z all-time -12%)

To podejście B znalazło 0x83b0, 0x75c2, 0x48ec. **Wystarcza** — Senpi nie jest konieczny.

---

## ⚠️ Senpi — czemu się nie łączy (status 2026-06-16)

**Przyczyna: w `~/.claude.json` NIE MA już wpisu `mcpServers.senpi`** (0 wpisów — sprawdzone).
Najpewniej zniknął przy reinstalacji Windows (nowy profil `krypt`, świeży `.claude.json`).
Wcześniej był: `type: http, url: https://mcp.prod.senpi.ai/mcp, Authorization: Bearer <JWT>`.

**Żeby przywrócić Senpi MCP:** dodać z powrotem ten wpis do `~/.claude.json` z ważnym tokenem
Senpi (z senpi.ai). Token mógł też wygasnąć — do sprawdzenia przy reaktywacji.
Konto Senpi: user `M194956`, embedded wallet `0x4f63...8348`, login przez Privy (email/Google).

**Czy potrzebny:** do działania copy bota NIE (mamy podejście B). Przydałby się do bogatszego
Wallet Analyzera w dashboardzie (roadmap 1.3) — więcej metryk (gain-to-pain, TAS/TCS) jednym callem.

---

## 🚦 Co dalej (kolejność)

1. **TERAZ:** zbierać dane 3-4+ dni (bot pracuje sam na VPS).
2. `--report` → ranking → wybór 1-2 najlepszych traderów.
3. **Sesja LIVE** (duża): realna egzekucja przez `hl_executor.py` — maker-limity (0.015%),
   obowiązkowy SL, kill switch -3% dziennie, osobny sub-account HL. Najpierw mały kapitał.
4. **Opcjonalnie:** przywrócić Senpi MCP + zbudować Wallet Analyzer w dashboardzie (roadmap 1.3).
