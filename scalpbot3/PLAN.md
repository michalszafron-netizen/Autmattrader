# ScalpBot3 — Plan (2 pomysły) — 2026-07-02

**Autor:** Claude Code + krypt
**Zasada nadrzędna (z liqscalp — sprawdziła się):** najpierw pomiar edge'u na danych (Faza 0),
potem paper, potem live micro. ALE: Faza 0 tutaj to **dni, nie miesiące** — mierzymy zjawiska
fizyczne (latencję, spread między giełdami), nie wzorce statystyczne. Kill-criteria są binarne:
albo lag/spread istnieje i jest większy niż koszty, albo nie. Tani, szybki werdykt.

**Dlaczego te 2 pomysły, a nie kolejny bot na RSI/świeczki:**
Edge **strukturalny** (segmentacja rynku, latencja, wymuszony przepływ) nie znika, gdy zmienia
się reżim rynkowy — w przeciwieństwie do edge'u **statystycznego** (wzorce cenowe), który
konkuruje z tysiącami botów i umiera po publikacji. Lekcja z liqscalp: fade-teza padła na
danych w 3 dni, momentum przeżyło test reżimu — bo było strukturalne (wymuszone likwidacje).
Oba pomysły poniżej grają struktury, nie wykresy.

---

# POMYSŁ A — "Event-Lag Sniper"
### Latencyjny scalp na HL xyz TradFi wokół publikacji danych makro i otwarć sesji

## Teza (edge)

Ten sam aktyw (złoto, srebro, ropa, S&P 500) żyje na dwóch zegarach:
- **CME/COMEX futures** (prawdziwa cena, ustalana przez największych graczy świata) — reaguje
  na dane makro w **milisekundach**,
- **HL xyz** (mały, oracle-anchored rynek, na którym prawie nikt nie handluje) — jego cena
  jest sterowana oracle'em, który może aktualizować się z **opóźnieniem sekund**.

W momencie publikacji CPI/NFP/FOMC futures robi ruch 0.2–1.0% w 1–3 sekundy. Jeśli xyz
"dogania" z opóźnieniem — istnieje okno, w którym **znamy przyszłą cenę xyz** (bo referencja
już się ruszyła) i możemy wejść w kierunku domknięcia. To nie jest prognoza — to odczyt.

**Dlaczego mało kto to robi:** xyz TradFi to niszowy zakątek HL — wolumeny małe, brak botów
HFT (nie opłaca im się kolokować pod rynek o takich wolumenach). Konkurencja bliska zeru.
To dokładnie mutacja z naszej roadmapy: "OBI/latencja na rynkach o niskiej konkurencji".

## Mechanizm

1. **Feed referencyjny:** Pyth Hermes (darmowy, publiczny, sub-sekundowy WS/HTTP) — ceny
   GOLD, SILVER, CL, ES/SP500, NDX pochodzące z agregacji realnych rynków.
2. **Feed HL xyz:** `allMids` z `dex=xyz` co ~300 ms (mamy to już w `xyz_scanner.py`).
3. **Kalendarz:** `econ_calendar.py` — znamy z góry minuty, w których świat się rusza
   (CPI 13:30 UTC, NFP, FOMC 18:00/18:30 UTC) + stałe otwarcia (CME open, US equity open 13:30 UTC).
4. **Sygnał:** w oknie ±5 min wokół eventu — gdy |ref_move| > próg (np. 0.15% w <3 s),
   a xyz jeszcze nie przeceniło (spread ref−xyz > 3× koszty) → wejście **taker** na xyz
   w kierunku ruchu referencji.
5. **Wyjście:** limit na cenie referencyjnej (konwergencja) lub time-stop 60–120 s.
   SL awaryjny za spreadem (gdyby referencja zawróciła).

## Faza 0 — pomiar (3–7 dni, werdykt binarny)

Kolektor zapisuje równolegle z timestampami ms: Pyth ticks + xyz mids + (próbka) xyz L2 depth.
Zbieramy przez tydzień sesji US — łapiemy min. 1 duży event (kalendarz: w każdym tygodniu jest
coś HIGH) + 5 otwarć sesji.

Metryki decyzyjne:
- **Lead-lag cross-correlation**: o ile ms/s xyz spóźnia się za Pyth przy dużych ruchach.
- **Rozkład max |spread|** w 60 s po evencie/otwarciu.
- **Depth xyz**: ile $ można wziąć taker bez przesuwania ceny > X bps (limit rozmiaru).
- **Expectancy po kosztach**: (median konwergencja) − (taker fee + połowa spreadu xyz + slippage).

**Kill-criteria (odrzucamy bez żalu):**
- mediana laga < 300 ms → oracle jest szybki, edge nie istnieje;
- max spread przy evencie < 2× koszty rundy → za mało mięsa;
- depth < $200 po sensownej cenie → nie da się wejść nawet mikro.

## Frekwencja i profil

- 2–10 sygnałów dziennie (otwarcia) + 2–5 dużych eventów/tydzień.
- Mało trade'ów, **wysoka wartość oczekiwana per trade** — odwrotność typowego scalpu
  (który robi 200 trade'ów po +0.02%). To cecha, nie wada: mniej fee, mniej noise.
- Martwe okresy: weekendy, noce (rynki bazowe śpią) — bot po prostu milczy.

## Ryzyka (uczciwie)

| Ryzyko | Mitygacja |
|---|---|
| Oracle HL okazuje się szybki | Faza 0 to wykryje w kilka dni — najtańszy możliwy kill |
| Cienka książka xyz = slippage zjada edge | pomiar depth w Fazie 0, twardy limit rozmiaru |
| HL zaostrzy parametry xyz (open interest cap itp.) | monitoring; edge może mieć datę ważności — zbieramy póki działa |
| Ruch referencji to fałszywy spike (odwrót) | wejście tylko przy utrzymanym ruchu ≥2 s + SL za spreadem |

## Reużycie infrastruktury

`xyz_scanner.py` (ring buffer xyz mids — wzorzec), `hl_executor.py` (egzekucja, limity, SL),
`econ_calendar.py` (harmonogram eventów), `tz_utils.py`, wzorzec collector/store/research
z `liqscalp/` (sprawdzony w boju). Nowe: klient Pyth Hermes (~100 linii, publiczne API).

---

# POMYSŁ B — "Basis Harvester"
### Delta-neutral spread-scalp między Hyperliquid a Extended (ten sam aktyw, dwie giełdy)

## Teza (edge)

BTC/ETH/SOL/HYPE notowane są jednocześnie na HL (duży DEX) i Extended (młody StarkNet DEX,
cieńszy, mniej arbitrażystów). Ceny **muszą** być prawie identyczne — ale na młodej giełdzie
z płytszą książką lokalne przepływy (czyjś duży market order, likwidacja) odchylają cenę
o kilka–kilkanaście bps od HL, zanim ktoś to domknie.

Gramy **spread, nie kierunek**: gdy basis = mid_EXT − mid_HL przekracza próg →
**long tańsza noga + short droższa noga jednocześnie**. Delta ≈ 0 (obojętne czy BTC rośnie
czy spada — zarabiamy na zejściu różnicy do zera). Każda konwergencja = mały, powtarzalny zysk.

**Bonus — funding carry:** perpy płacą funding (opłata co 1–8 h między longami a shortami).
Jeśli funding na EXT ≠ funding na HL (na młodych giełdach częste), pozycja delta-neutral
**inkasuje różnicę** przez cały czas trzymania. Dwa strumienie zysku w jednym trejdzie.

**Dlaczego to jest inny zwierz niż wszystko co mamy:** każdy dotychczasowy bot (liqscalp,
hl_scalp, correlation) zgaduje kierunek. Ten NIE — ryzyko kierunkowe ≈ 0. To profil zysków
jak u market makera: dużo małych wygranych, rzadkie i ograniczone straty (leg risk).

## Mechanizm

1. **Feedy:** WS mids z obu giełd (HL `allMids` + Extended WS/REST) na BTC, ETH, SOL, HYPE.
2. **Basis engine:** rolling μ/σ spreadu; sygnał gdy |basis − μ| > k·σ ORAZ > (koszty 4 nóg + margines).
3. **Wejście:** maker limit na obu nogach jednocześnie; jeśli jedna noga wypełniona a druga
   nie w ciągu N sekund → natychmiastowy taker hedge (kontrola leg risk — to jest serce bota).
4. **Wyjście:** konwergencja basis do ~μ → zamykamy obie nogi (maker gdzie się da).
   Jeśli funding differential > próg — trzymamy dłużej i inkasujemy carry.
5. **Limity:** max kapitał na Extended (młoda giełda = ryzyko wypłacalności — trzymamy tam
   tylko margin roboczy), max 1 spread/aktywo, kill-switch przy rozjeździe > X%.

## Faza 0 — pomiar (3–5 dni, werdykt binarny)

Kolektor: mids obu giełd + funding rates obu, timestampy ms, 24/7 (crypto nie śpi).

Metryki decyzyjne:
- **Rozkład basis** per aktywo: σ, częstość przekroczeń progów (ile okazji/dzień).
- **Half-life konwergencji**: jak szybko basis wraca (sekundy? minuty?).
- **Historia funding differential**: czy jest trwały przechył (= darmowy carry)?
- **Expectancy po 4 nogach fee**: HL maker 0.01%/taker 0.035% (crypto), Extended wg cennika —
  suma kosztów rundy to główny zabójca; liczymy wariant maker-maker i maker-taker.

**Kill-criteria:**
- 2σ basis < koszty 4 nóg + 2 bps marginesu → spread-scalp odpada; zostaje wolniejszy
  wariant czysto fundingowy (wejście raz, trzymanie dniami — inny bot, też wartościowy);
- < 5 okazji dziennie po progu → za mała frekwencja na scalp (ale znowu: carry zostaje).

## Frekwencja i profil

- Jeśli edge jest: kilkanaście–kilkadziesiąt konwergencji dziennie po kilka bps netto.
- Zysk = (przechwycony basis − fee) × obrót + funding carry. Skaluje się kapitałem, nie zgadywaniem.
- Działa 24/7 (crypto), niezależnie od reżimu rynku — hossa/bessa obojętna (delta-neutral).

## Ryzyka (uczciwie)

| Ryzyko | Mitygacja |
|---|---|
| Fee 4 nóg zjada spread (killer #1) | maker entries; Faza 0 liczy to PRZED napisaniem bota |
| Leg risk (jedna noga bez fill'a, rynek ucieka) | timeout N s → wymuszony taker hedge; limit rozmiaru |
| Extended: wypłacalność / halt / API padnie | mały kapitał roboczy na EXT; kill-switch przy braku feedu |
| Likwidacja jednej nogi przy dużym ruchu (różne marki oracle) | niski lewar (2–3×), alarm przy margin health < próg |
| Basis się rozjeżdża zamiast wracać (delisting, incydent) | hard-stop na |basis| > X% → zamknij obie nogi, strata ograniczona |

## Reużycie infrastruktury

`hl_executor.py` + `extended_order.py`/`extended_executor.py` (obie egzekucje GOTOWE),
`oi_tracker.py` (funding — częściowo), wzorzec collector/store/research z `liqscalp/`.
Nowe: WS klient Extended (mids stream) + basis engine.

---

# Porównanie i rekomendacja

| Cecha | A: Event-Lag Sniper | B: Basis Harvester |
|---|---|---|
| Typ edge | strukturalny (latencja oracle) | strukturalny (segmentacja rynku) |
| Ryzyko kierunkowe | tak, sekundy–minuty | **~zero (delta-neutral)** |
| Konkurencja | ~zero (xyz TradFi to pustynia) | niska (młody DEX, mało arbów) |
| Frekwencja | niska (eventy + otwarcia) | średnia–wysoka, 24/7 |
| Główne ryzyko | oracle może być szybki | fee 4 nóg + leg risk |
| Koszt Fazy 0 | tydzień zbierania | 3–5 dni zbierania |
| Skalowalność | ograniczona depth xyz | skalowana kapitałem |
| Charakter zysku | rzadkie, tłuste trade'y | drobne, powtarzalne + carry |

**Rekomendacja (GOAT move):** Faza 0 obu pomysłów to **ten sam typ kolektora** (równoległe
feedy cenowe z timestampami ms). Budujemy JEDEN kolektor zbierający naraz: Pyth + HL xyz mids
+ HL crypto mids + Extended mids + funding obu giełd. Tydzień działania → **dwa werdykty
za cenę jednego**. Dane wybiorą bota — nie my. Jeśli oba edge'e przejdą kill-criteria,
budujemy najpierw B (brak ryzyka kierunkowego = bezpieczniejszy pierwszy live), A jako drugi.

## Struktura docelowa `scalpbot3/`

```
scalpbot3/
├── PLAN.md            ← ten plik
├── collector.py       ← Faza 0: Pyth + HL (xyz+crypto) + Extended → SQLite (timestampy ms)
├── store.py           ← własna baza data/scalpbot3.db (nie dotyka db.py)
├── research_lag.py    ← werdykt A: lead-lag, spread po eventach, expectancy
├── research_basis.py  ← werdykt B: rozkład basis, half-life, funding diff, expectancy
├── run_collector.bat
└── (po Fazie 0)       ← detector.py, executor.py, bot.py — tylko dla zwycięzcy
```

Zasady twarde (dziedziczone z ekosystemu): paper default · ryzyko ≤2%/trade · SL obowiązkowy ·
kill-switch −3%/dzień · heartbeat Telegram · żadnych zmian w istniejących skryptach (read-only).
