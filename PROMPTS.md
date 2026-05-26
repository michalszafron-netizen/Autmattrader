# Trading AI — Arsenał Promptów

> Killer prompts do wyciskania maksimum z całego stacku.
> Styl: imperatyw, wielowymiarowy, time-boxed, wynik = decyzja, framing kontrariański.

## Spis treści

- [Moduły](#moduły)
  - [1. hl_whale_tracker.py](#moduł-1--hl_whale_trackerpy)
  - [2. whale_scanner.py](#moduł-2--whale_scannerpy)
  - [3. hl_executor.py](#moduł-3--hl_executorpy)
  - [4. blogwatcher.py](#moduł-4--blogwatcherpy)
  - [5. token_research](#moduł-5--token-research-evm--solana)
  - [6. VPS Daemons](#moduł-6--vps-daemons)
  - [7. TradingView MCP](#moduł-7--tradingview-mcp)
  - [8. Senpi MCP](#moduł-8--senpi-mcp)
  - [9. fetch_positions.py](#moduł-9--fetch_positionspy)
  - [10. edge_journal.py](#moduł-10--edge_journalpy--strategy-review)
- [Compound Prompts](#compound-prompts--moc-kombinacji) — łączą wiele modułów
- [Daily Prompt](#daily-prompt--jeden-prompt-do-codziennego-użycia)
- [Najmocniejsze non-obvious prompts](#najmocniejsze-non-obvious-prompts)

---

## Zasady tych promptów

1. **Imperatyw, nie pytanie** — "find me", "show me", "identify" — żądają konkretu, nie eseju
2. **Wielowymiarowość** — łączą 2-3 niezależne sygnały (sentiment + pozycja + divergencja)
3. **Time-box** — "w ostatnich 24h", "ostatnie 7 dni" — wymuszają aktualność
4. **Wynik = decyzja** — entry/SL/TP/confidence, nie "interesujące obserwacje"
5. **Framing kontrariański** — smart vs rekt, narrative vs positioning, herd vs outlier

---

## Moduły

### MODUŁ 1 — `hl_whale_tracker.py`

> leaderboard / positions / whales / snapshot

**P1.1 — Concentration play**
> Uruchom `whales --top 50` i znajdź monetę gdzie >70% ekspozycji $ pochodzi od ≤3 wallet'ów. To są singularne convicstion bety wielorybów — daj mi top 3 takie monety, wraz z adresami tych wallet'ów i ich PnL na window=week.

**P1.2 — Whale timeframe divergence**
> Uruchom `whales --window day` i `whales --window week` osobno. Znajdź monetę gdzie smart money DAY jest LONG ale WEEK jest SHORT (albo odwrotnie) — to oznacza świeży flip wśród zwycięzców z dużą siłą. Daj mi listę z ratio.

**P1.3 — Solo legend stalker**
> Z `leaderboard --window allTime --top 10`, weź wallet z najwyższym ROI (nie PnL — ROI). Uruchom `positions` na nim. Powiedz mi co ma otwarte, czy ostatnie ruchy są zgodne z resztą rynku czy contrarian, i czy mogę zająć taką samą pozycję skalując do mojego konta przy max risk 2%.

**P1.4 — Conviction add detector**
> Uruchom `snapshot diff`. Znajdź wallet który: (a) miał już pozycję w monecie X w starym snapshocie, (b) w nowym snapshocie ma na X więcej $ niż wcześniej, (c) jego uPnL na tej pozycji jest UJEMNY. To są conviction adds w stratę — najmocniejszy sygnał wśród wielorybów.

**P1.5 — Whale liquidation cluster**
> Z `whales --coin BTC --top 100` daj mi histogram cen entry SHORT'ów. Tam gdzie jest największa kumulacja entries = strefa gdzie short squeeze będzie miał paliwo. Powtórz dla LONG entries — to twoja strefa long liquidation. Wskaż obie ceny.

---

### MODUŁ 2 — `whale_scanner.py`

> top / rekt / both / wallet

**P2.1 — Rekt conviction trade**
> Uruchom `whale_scanner.py both 30`. Znajdź monetę gdzie rekt money ma >5 wallet'ów LONG z negatywnym monthly PnL, jednocześnie smart money ma <2 wallety LONG. To jest klasyczny "rekt money chasing top" — daj mi setup SHORT z dokładnym entry/SL/TP.

**P2.2 — Rekt money exit signal**
> Z `whale_scanner.py rekt 50` zrób mi listę 5 monet, w których rekt money ma największą sumę pozycji $. Te monety są w "rekt zone" — gdy zaczną się likwidować, kaskada się rozpędza. Powiedz mi która z nich ma najbliżej do liquidation klastra na podstawie ich entry prices.

**P2.3 — Anti-consensus alpha**
> Wszystkie monety gdzie smart money i rekt money zgadzają się co do kierunku — pomiń. Skup się tylko tam gdzie się NIE zgadzają. Z tych: która ma największą rozbieżność $ exposure (smart $ long vs rekt $ short)? To jest twój trade.

**P2.4 — Rekt early-warning**
> Cross-reference: dla 10 walletów z `rekt 20`, sprawdź czy któryś z nich był w `top 20` jeszcze 30 dni temu (porównaj z leaderboard --window month). Ci traderzy się rozpierdolili od miesiąca — co oni teraz robią ŹLE? Wyciągnij wzorzec.

---

### MODUŁ 3 — `hl_executor.py`

> orders, SL/TP

**P3.1 — Pre-trade risk audit**
> Zanim wyślę zlecenie [coin] [direction] [size] [entry]: (1) policz exact distance do najbliższego liq klastra wielorybów, (2) sprawdź historyczny ATR(14) — czy mój SL nie jest zbyt ciasny (<0.5 ATR) lub zbyt szeroki (>2 ATR), (3) policz R:R do najbliższego significant level — jeśli <1.8 powiedz "skip".

**P3.2 — Ladder strategy builder**
> Mam konto $X, chcę otworzyć pozycję $Y na [coin]. Zbuduj ladder: 30% size przy market, 30% przy -0.5 ATR retest, 40% przy -1 ATR. SL pod całym ladderem. TP1 = 1R od średniego entry (zamyka 50%), TP2 = 2R (zamyka 30%), runner = 20% z trailing.

**P3.3 — Position size sanity check**
> Pokaż moją obecną aktywną ekspozycję (`fetch_positions.py`). Czy moja proponowana nowa pozycja $X na [coin] łamie regułę 2% per trade lub 6% portfolio? Daj mi maksymalny rozmiar pozycji jaki MOGĘ otworzyć bez łamania reguł, biorąc pod uwagę korelację z istniejącymi pozycjami.

**P3.4 — Trigger order placement template**
> Dla mojej obecnej pozycji [coin] [side]: oblicz SL pod najbliższą strukturą (swing low/high z 4h) i TP na 2R od entry. Wyślij oba jako reduce-only triggers przez `hl_executor sl/tp`. Pokaż mi command line przed wykonaniem.

---

### MODUŁ 4 — `blogwatcher.py`

> news, 7 sources, 18 assets

**P4.1 — Silent accumulation**
> Pokaż monety z mojej watchlisty gdzie blogwatcher zarejestrował <3 wzmianki w ostatnich 14 dniach (zero hype), ALE on-chain volume / whale exposure rośnie. To jest "smart money pre-positioning before narrative" — top 3 kandydaci.

**P4.2 — Narrative vs positioning divergence**
> Dla każdej monety, oceń sentiment z blogwatcher (bullish/bearish/neutral) i porównaj z whale bias (`whales` aggregate). Gdzie narracja jest bullish ale whale są SHORT — to fade-the-news. Gdzie narracja bearish ale whales LONG — to buy-the-fear.

**P4.3 — Source reliability scoring**
> Wyciągnij z blogwatcher ostatnie 30 dni news per source. Dla każdego źródła policz: ile razy artykuł pojawił się PRZED ruchem cenowym >5% w ciągu 24h. Daj mi ranking — które źródła są leading indicator, a które tylko opisują co już się wydarzyło.

**P4.4 — Event catalyst calendar**
> Z blogwatcher wyłuskaj eventy w następnych 7 dniach które mogą flip-ować funding regime (ETF decisions, FOMC, hard forks, unlocks). Dla każdego: które aktywa są najbardziej narażone i jaki jest current whale positioning na nich.

---

### MODUŁ 5 — Token Research (EVM + Solana)

**P5.1 — Distribution end signal**
> Znajdź token gdzie insider/team wallet outflow USTAŁ w ostatnich 14 dniach po >90 dniach konsystentnej sprzedaży. To są monety które właśnie zostały "uwolnione" z presji podażowej — top 3 z najlepszą płynnością.

**P5.2 — Whale-cohort accumulation**
> Token gdzie top 10 holders nie ruszyli się od 60+ dni (diamond hands), ALE pojawił się NOWY wallet który w ostatnich 7 dniach kupił >2% circulating. Brak distribution + nowy whale = asymmetric setup.

**P5.3 — Survivor cohort filter**
> Solana memecoins które: (a) mają >$500k daily volume, (b) NIE spadły >40% w ostatnich 30 dniach mimo bear-conditions, (c) holder count rośnie. To są kandydaci do "next cycle leaders".

**P5.4 — Liquidity trap detector**
> Token z high market cap ($100M+) ale slippage >5% na $20k order. To jest pułapka płynności — krótkie, ale brutalne moves możliwe. Daj mi listę takich tokenów które są na watchliście — i powiedz mi gdzie zostawić tight stop.

---

### MODUŁ 6 — VPS Daemons

> volume_scanner / smart_money_tracker / listings_scanner

**P6.1 — Pre-listing accumulation**
> Z listings_scanner: token świeżo dodany do CEX w ostatnich 24h. Sprawdź volume_scanner: czy on-chain volume zaczął rosnąć >12h PRZED ogłoszeniem listingu? Jeśli tak — sygnał front-runów = listing pump z paliwem.

**P6.2 — Smart money fresh entry**
> Z smart_money_tracker: wallet który zyskał >100% w 30 dni AND otworzył nową pozycję w ostatnich 4h AND ta pozycja nie była w jego portfolio 24h temu. To jest fresh alpha — alert mi natychmiast z linkiem do wallet'a.

**P6.3 — Volume anomaly bez price action**
> Volume_scanner outlier: asset z volume >3σ powyżej 30d mean ALE price ruch <3% w tym samym oknie. To accumulation albo distribution — porównaj z whale bias na tej monecie, żeby określić kierunek.

**P6.4 — Coordinated entry detector**
> W ostatnich 6h: czy ≥3 smart_money wallety otworzyły tę samą pozycję (ten sam coin, ta sama strona) niezależnie od siebie? Coordinated entry = silny sygnał. Daj mi listę z timestamps i wallet IDs.

---

### MODUŁ 7 — TradingView MCP

**P7.1 — Volatility breakout scanner**
> Dla każdego instrumentu z watchlisty: pobierz ATR(14) i porównaj z 90-day average. Znajdź te gdzie current ATR >150% rolling avg AND ADX >25 AND directional. To są volatility breakouts w trendzie — top 3 setups z poziomami.

**P7.2 — Multi-timeframe Zero Lag confluence**
> Uruchom Zero Lag basis check na 4h / 1h / 15m dla BTC, ETH, SOL. Znajdź instrument gdzie 4h i 1h pokazują ten sam bias (LONG/SHORT) ALE 15m jest contrarian. To jest pullback w trendzie — najlepszy moment na entry z 15m timing.

**P7.3 — Swing magnet level**
> Dla [coin]: znajdź ostatnie 10 swing highs/lows na 4h. Pogrupuj je w klastry (tolerancja 0.5%). Klaster z najwięcej dotknięciami = magnet level. Daj mi cenę magnetu i odległość od current price.

**P7.4 — Strategy regime fit**
> Mam Pine strategy [name] na [symbol] [timeframe]. Pobierz wszystkie historyczne trades i pogrupuj według: (a) day of week, (b) session (Asia/EU/US), (c) ADX bucket (low/mid/high). Pokaż mi gdzie win rate jest najgorszy — tam strategia NIE działa, dodaj filtr.

**P7.5 — Indicator cross-confirmation**
> Dla każdej pozycji z `fetch_positions`: otwórz wykres w TradingView, sprawdź EMA stack, ADX, RSI, ATR. Klasyfikuj każdą pozycję jako: "in confluence" (3+ indykatory zgodne z moim kierunkiem), "neutral", "fighting tape" (3+ przeciwko). Te ostatnie — rozważ exit.

---

### MODUŁ 8 — Senpi MCP

**P8.1 — Momentum + consistency overlap**
> Z `leaderboard_get_top` (4h momentum) weź top 20. Cross-reference z `discovery_get_top_traders` (90-day history) — kto jest w obu top 20? Ci traderzy mają BOTH momentum AND consistency — kopiuj/obserwuj ich pozycje.

**P8.2 — Add-on conviction**
> Senpi traders którzy w ostatnich 4h ZWIĘKSZYLI rozmiar pozycji podczas gdy ich uPnL na niej był UJEMNY. To są conviction adds — najsilniejszy sygnał spośród momentum.

**P8.3 — Senpi vs HL cross-platform consensus**
> Lista pozycji top 20 Senpi traderów (przez `leaderboard_get_trader_positions` per trader). Porównaj z HL whale aggregate (`whales --top 20`). Coiny gdzie obie platformy zgadzają się co do kierunku = high-conviction consensus. Coiny tylko na Senpi = potential edge.

**P8.4 — Funding regime alpha**
> Z `market_get_funding_regime` znajdź coin gdzie funding jest extreme (>0.1% / 8h lub <-0.05%). Sprawdź czy Senpi top traders są po przeciwnej stronie funding extreme. Jeśli tak — to klasyczny "fade the funding" trade z dodatkową walidacją.

---

### MODUŁ 9 — `fetch_positions.py`

> 4-venue unified (HL + Extended + Solana + Alpaca)

**P9.1 — Portfolio greek summary**
> Pokaż mi: net BTC delta (suma wszystkich BTC-exposed positions w $), net ETH delta, net SOL delta, net stablecoin (USDC/USDT idle). Powiedz mi czy mam concentration risk (>40% w jednym asset).

**P9.2 — Stale position killer**
> Pozycje otwarte >7 dni z |uPnL| <0.5R. To są zombie trades — ani win, ani loss, zżerają mental capacity. Dla każdej daj mi rekomendację: close / set tighter SL / set TP at scratch + exit.

**P9.3 — Cross-venue arbitrage check**
> Czy mam tę samą pozycję na różnych venue (np. BTC long na HL + BTC long na Senpi)? Jeśli tak — sprawdź funding rates na obu, czy nie powinienem przenieść pozycji na tańszy venue. Policz koszt funding per day per venue.

**P9.4 — Risk waterfall**
> Posortuj wszystkie moje pozycje wg risk: distance to SL × position size = $ at risk. Pokaż top 5 największych $ at risk. Jeśli wszystkie 5 idzie nie po mojej myśli — ile to wymaga adjustment portfela?

---

### MODUŁ 10 — `edge_journal.py` + Strategy review

**P10.1 — Session leak detector**
> Z ostatnich 100 trades: oblicz win rate per session (Asia / EU / US / weekend). Znajdź sesję gdzie win rate jest >10 pp poniżej średniej. Tam tracę edge — przestaję tradować w tej sesji albo zmniejszam size.

**P10.2 — Wick stop vs structural stop**
> Z ostatnich 30 LOSES: ile było stops trafionych w wick (low/high <5% od mojego stopu, potem cena wraca w moją stronę w <4h)? Jeśli >40% — moje stops są za ciasne, daj mi nowy framework.

**P10.3 — AI vs manual entries**
> Porównaj last 90 dni: AI-suggested entries vs moje manual entries. Win rate, avg R, max drawdown per category. Powiedz mi gdzie powinienem zaufać AI a gdzie trustnąć intuition.

**P10.4 — Setup type ROI ranking**
> Pogrupuj ostatnie 200 trades wg setup type (breakout / pullback / range fade / news fade / contrarian). Daj mi expectancy per setup w $ i w R. Najgorszy setup — wytnij go całkowicie z arsenału.

---

## Compound Prompts — moc kombinacji

> Tu zaczyna się prawdziwa magia. Te prompty łączą moduły w sposoby, których pojedynczo nie da się zrobić.

### C1 — Silent Accumulation Triangle
> *(whales + blogwatcher + token_research)*

Znajdź monetę gdzie: (1) HL whales dodali >$3M long exposure w ostatnich 48h (`snapshot diff` + porównanie), (2) blogwatcher zarejestrował ≤2 wzmianki w tym samym oknie (zero hype), (3) token_research pokazuje brak insider distribution. To jest CISZA + ZAKUPY = pre-narrative accumulation. Daj mi entry plan z confidence 1-10.

### C2 — Liquidation Hunt Setup
> *(whale_scanner rekt + hl_whales + TradingView)*

Identyfikuj setup gdzie: (1) `whale_scanner rekt` pokazuje >7 wallet'ów rekt LONG na monecie X, (2) `hl_whales --top 50` na tej samej monecie jest net SHORT $-ważone, (3) TradingView pokazuje cena w górnym pasie BB(20,2) na 4h, RSI >65. To jest perfect liquidation hunt SHORT — entry/SL/TP z R:R.

### C3 — Regime Change Alert
> *(snapshot diff + funding + smart_money_tracker)*

Daily debrief — flag mi monetę gdzie wszystkie 3 warunki w ostatnich 24h: (a) whale bias FLIP w `snapshot diff`, (b) funding zmienił znak (positive→negative lub odwrotnie), (c) smart_money_tracker zarejestrował świeże entry. Tripla = regime change, najsilniejszy sygnał jaki mamy.

### C4 — Honest Broker Self-Review
> *(edge_journal + fetch_positions + whale_tracker)*

Brutalna ocena: weź moje 30 ostatnich trades z edge_journal. Dla każdego sprawdź czy whales byli zgodni z moim kierunkiem (historical snapshots) i czy mój edge jest faktyczny czy losowy. Następnie dla obecnych otwartych pozycji (`fetch_positions`): oceń każdą jako "in line with my proven edge" / "outside my edge zone" / "fighting my own pattern". Te ostatnie — exit.

### C5 — Full Stack Trade Setup
> *(TradingView + whales --coin + Senpi + blogwatcher)*

Dla [coin] daj mi pełną synthesis: (1) TradingView state (S/R, EMAs, ADX, current ATR), (2) `whales --coin [coin]` wallet-level positioning, (3) Senpi top traders na tej monecie, (4) blogwatcher sentiment ostatnich 14 dni. Output: jedna decyzja — LONG / SHORT / NO TRADE — z confidence 1-10, dokładne poziomy, i 2-3 zdania uzasadnienia.

### C6 — Listing Pump Validator
> *(listings_scanner + blogwatcher + token_research + volume_scanner)*

Dla każdego tokena z listings_scanner w ostatnich 48h: (a) czy blogwatcher zarejestrował listing rumor PRZED faktycznym announce'em? (b) czy token_research pokazuje organic holder growth? (c) czy volume_scanner widział anomaly volume PRZED announce'em? Tylko tokeny które przeszły wszystkie 3 = real pump candidate, reszta to fade.

### C7 — Daily Alpha Brief (The Master Prompt)
> *(wszystko razem)*

Wygeneruj poranny briefing dla mnie:
- `snapshot save` + `snapshot diff` na HL whales (top 30, week window)
- blogwatcher digest ostatnie 24h (only sentiment-flipping events)
- `fetch_positions` — moje obecne pozycje z marker risk score
- TradingView state 6 instrumentów (BTC, ETH, SOL, GOLD, SILVER, USOIL)
- Senpi 4h momentum leaderboard top 5
- funding regime check na BTC, ETH, SOL

Output:
- **3 highest-conviction trades** z pełnymi setupami (entry/SL/TP/R:R/confidence)
- **1 watch coin** — czego pilnować dzisiaj
- **1 avoid coin** — czego NIE tradować i dlaczego
- **Portfolio adjustment** — jakie ruchy na obecnych pozycjach (jeśli jakieś)

### C8 — Counter-Crowd Indicator
> *(rekt + whales + funding + Senpi)*

Maksymalnie kontrariański scan: znajdź monetę gdzie (1) `whale_scanner rekt` jest heavy LONG, (2) HL smart money `whales` jest heavy SHORT, (3) funding jest dodatni (longs płacą — tłum jest long), (4) Senpi top 20 jest >70% SHORT. Cztery niezależne potwierdzenia tłumu po jednej stronie = perfekcyjny contrarian short. Najsilniejszy setup w arsenale.

### C9 — Strategy Performance Regime Map
> *(Pine + whale_tracker + edge_journal)*

Mój Zero Lag strategy na BTC 15m: weź historyczne trades z TradingView strategy tester (`data_get_trades`). Dla każdego trade sprawdź historyczny whale bias z snapshot archive w tym momencie. Pogrupuj trades wg whale alignment: aligned with whales / against whales / neutral. Powiedz mi gdzie strategia działa, a kiedy POWINIENEM ją wyłączać. Output: regime filter do dodania do strategii.

### C10 — The Conviction Stack
> *(whale add-ons + smart_money + Senpi)*

Find moment most rare na rynku — gdzie wszystkie 3 sygnały zbiegają w ostatnich 4h:
1. HL whale dodał do pozycji w UJEMNYM uPnL (conviction add — P1.4)
2. Smart_money_tracker wallet otworzył pozycję w tym samym kierunku na tej monecie
3. Senpi top trader też ma tę pozycję AND zwiększył ją w ostatnich 4h

Tripla = "elite conviction stack". To są pozycje za którymi powinienem iść z większym sizem (3% zamiast 2% risk).

### C11 — Pre-Mortem Generator
> *(TradingView + whales + edge_journal)*

Przed wejściem w trade: (1) TradingView pokaż mi worst-case scenario — gdzie wytnęło ostatnie 5 podobnych setupów, (2) whales — gdzie jest ich liquidation cluster przeciw mojemu kierunkowi, (3) edge_journal — jakie były moje top 3 mistakes na tym typie setupu w przeszłości. Output: 3 konkretne ryzyka + jak je mitigate'ować PRZED entry.

### C12 — Wallet Genealogy
> *(Senpi + HL + smart_money)*

Wybierz najsilniejszego smart_money wallet z ostatnich 30 dni. Cross-reference: czy jest na HL leaderboard? Czy jest aktywny na Senpi? Czy jego pozycje korelują z innymi top wallet'ami? Stwórz "genealogię" — z kim ten wallet trade'uje razem, czy widzimy networking effect (5+ wallet'ów stadnie wchodzących/wychodzących w tym samym czasie).

---

## Daily Prompt — Jeden Prompt do Codziennego Użycia

> Wpisz to codziennie rano. Dostajesz 80% wartości całego stacku w jednej odpowiedzi.

```
Uruchom moją wieczorną zmianę:
1. snapshot save → snapshot diff (jeśli mam previous snapshot)
2. whale_scanner.py both 25
3. blogwatcher digest 24h
4. fetch_positions
5. Funding regime na BTC/ETH/SOL

Daj mi w jednej odpowiedzi:
- TOP 1 LONG trade (najwyższa convicstion) z entry/SL/TP/confidence
- TOP 1 SHORT trade (contrarian setup) z entry/SL/TP/confidence
- 1 watchlist coin (jeszcze nie teraz, ale obserwuj)
- Ranking moich obecnych pozycji (best to worst) + action per pozycja
- Red flag — czego dziś NIE robić i dlaczego

Bądź brutalny w ocenie. Confidence rating 1-10 wymagany.
```

---

## Najmocniejsze non-obvious prompts

> Te prompty których inni traderzy nie pytają.

- **P1.5** (liquidation cluster z entry prices) — większość mówi "gdzie są stops", mało kto patrzy gdzie ENTRIES są skoncentrowane
- **P2.1, C8** (rekt money długo + smart short = top setup) — większość ignoruje rekt traderów, a to jest twoja kontrariańska kopalnia złota
- **C3** (regime change tripla) — pojedyncze sygnały są szumem, tripla z różnych modułów to alfa
- **C4** (honest broker) — większość traderów odmawia oceny czy ich edge jest prawdziwy
- **C9** (strategy regime fit z whale historical) — większość backtestuje na surowych cenach, nie na regime'ach

Te prompty rzeczywiście pozwalają wycisnąć z naszego stacku to, czego strona z poradnikiem **nie potrafi** — bo my mamy 4 venues + on-chain + news + TradingView, a oni mają tylko HL.

---

## Workflow użycia

1. **Rano** → wklejasz Daily Prompt do tgtrade Telegram bridge lub bezpośrednio do Claude Code w `trading-ai/`
2. **W ciągu dnia** → wybierasz konkretny moduł lub compound w zależności od pytania ("co teraz robić?" = C5 lub C7, "czy ten trade ma sens?" = P3.1 + C11)
3. **Wieczorem** → C4 (honest broker review) raz w tygodniu, snapshot save zawsze
4. **Pre-trade** → ZAWSZE P3.1 + P3.3 zanim wyślesz zlecenie LIVE

---

*Plik utworzony: 2026-05-26. Aktualizuj kiedy odkryjesz nowy killer prompt.*
