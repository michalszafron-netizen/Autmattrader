# 🗺️ Scalp Bots — Roadmap przyszłych systemów (#2 i #3)

**Status:** odłożone na przyszłość. Budujemy najpierw **#1 Liquidation-Cascade Fade**
(osobny dokument: `LiqScalp_Bot.md` powstanie przy implementacji).
Ten plik to "magazyn pomysłów" — gdy wrócimy do tematu, zaczynamy stąd.

**Data:** 2026-06-20
**Autor:** Claude Code + krypt

---

## 🚨 PLAN AWARYJNY — migracja Bybit → Hyperliquid (gdyby Bybit zablokował Polskę)

**Ryzyko:** Bybit potrafi z dnia na dzień ograniczyć dostęp dla użytkowników z UE/Polski
(konto, region POL). Jeśli to się stanie, bot likwidacyjny #1 traci giełdę wykonania.
**Musi istnieć ścieżka pełnego przeskoku na Hyperliquid.**

**Dlaczego HL to dobry plan B (a momentami nawet lepszy):**
- HL ma **własny feed likwidacji** (WS) — ta sama mechanika, inny endpoint. Kolektor
  `collector.py` wymaga tylko podmiany URL/topików + parsera eventu, reszta logiki ta sama.
- HL ma **rynki, których Bybit NIE ma**: ropa (xyz:CL), Nasdaq, pełen zestaw xyz TradFi —
  czyli plan B otwiera aktywa niedostępne na Bybit.
- HL = on-chain, **brak ryzyka geo-blokady** (nie ma KYC regionowego jak CEX).
- Egzekucja już gotowa: `hl_executor.py` (limit maker, trigger SL/TP) — reużycie przez import.

**Co trzeba będzie zrobić przy migracji (szkic):**
1. Kolektor: nowy adapter `collector_hl.py` — HL WS liquidations + mids/L2, ten sam schemat DB.
2. Zmapować symbole Bybit → HL (BTC, ETH, SOL, HYPE natywnie; metale/indeksy → xyz:GOLD/SP500…).
3. Egzekucja: zamiast Bybit REST → `hl_executor.py`. Reszta (signal, research, DSL) bez zmian.
4. Uwaga: HL likwidacje mają inną strukturę/wolumen niż Bybit — Faza 0 trzeba przejść od nowa
   na danych HL (nie zakładać, że progi z Bybit przeniosą się 1:1).

**Status:** tylko notatka. Robimy dopiero jeśli Bybit zablokuje PL lub jeśli #1 okaże się
działać i zechcemy go zduplikować na HL dla ropy/Nasdaqa.

---

## Zasada wspólna dla wszystkich botów scalpowych

> **Najpierw mierzymy edge na danych (Faza 0), dopiero potem piszemy logikę tradingową.**
> Żaden bot nie idzie na paper, dopóki backtest nie pokaże dodatniej oczekiwanej wartości
> (expectancy) **po odjęciu fee i slippage**. Żaden nie idzie live, dopóki paper tego nie potwierdzi.

Każdy scalp edge jest cienki i konkurencyjny — obietnica "super skuteczny" jest warta tyle,
ile dane za nią stoją. Dlatego każdy z tych systemów ma tę samą strukturę faz:
**Faza 0 (pomiar) → Faza 1 (paper) → Faza 2 (live micro)**.

---

# SYSTEM #2 — Same-Asset Cross-Venue Lag (HL xyz vs szybszy feed)

## Teza

Ten sam aktyw bazowy (GOLD, SP500, Crude Oil, SILVER) jest notowany na **wielu rynkach
naraz**. Globalne rynki futures (COMEX, CME) ustalają "prawdziwą" cenę. HL xyz to mniejsza,
mniej efektywna giełda, której mark price jest sterowany oracle'em. Jeśli oracle HL aktualizuje
się z **opóźnieniem** względem szybszego feedu referencyjnego — powstaje okno, w którym
referencja już się ruszyła, a HL xyz jeszcze nie przecenił. Gramy "dogonienie".

## Dlaczego to MOCNIEJSZY sygnał niż obecny bot korelacyjny

Obecny `correlation_scalp.py` gra **proxy-korelacje** (DXY → GOLD). To korelacja statystyczna —
zawodzi, gdy reżim się zmienia (np. gdy złoto i dolar rosną razem w panice). System #2 gra
**ten sam aktyw** — to nie korelacja, to ta sama rzecz na dwóch zegarach. Dużo czystszy sygnał.

## Mechanizm

1. **Feed referencyjny** (szybki): kandydaci — Bybit (dla crypto-proxy), TradingView MCP
   (`quote_get` na realnym futures), **Pyth Network** (on-chain oracle, sub-sekundowy,
   ten sam typ źródła co HL używa) lub bezpośredni feed CME-pochodny.
2. **Feed HL xyz** (potencjalnie wolny): `allMids` z `dex=xyz` co ~300ms.
3. Liczymy **spread bazowy** (mid_ref − mid_hl) znormalizowany. Gdy |spread| przekroczy próg
   (np. > 2σ historycznego spreadu) i referencja prowadzi → limit maker na HL xyz w kierunku
   domknięcia spreadu. Zamknięcie, gdy spread wróci do ~0.

## ⚠️ Krytyczne ryzyko — wymaga twardej walidacji (Faza 0)

Cały edge zależy od jednego pytania: **czy oracle HL faktycznie laguje?**
HL mark jest oracle-anchored — jeśli oracle jest szybki, lag ≈ 0 i edge nie istnieje.
- **Faza 0 musi to zmierzyć empirycznie**: zbieramy równolegle feed referencyjny + HL xyz mid
  z dokładnymi timestampami przez kilka dni sesji US, liczymy cross-correlation z opóźnieniem
  (lead-lag), sprawdzamy czy istnieje stabilne okno > kosztu transakcji.
- Jeśli lag < (fee + spread + slippage) → **system odrzucony**. Tani, szybki werdykt.

## Frekwencja (szacunek)

Zależna od progu σ. Realnie sygnały skupione w godzinach otwarcia rynków bazowych
(US session, otwarcia CME). Poza sesją (weekend, azjatycka noc) — cisza, bo aktyw bazowy śpi.
Prawdopodobnie **kilka–kilkanaście sygnałów dziennie w sesji**, zero poza nią.

## Edge

- Strukturalny: **niska konkurencja na HL xyz** (mało kto handluje xyz TradFi).
- Maker fee 0.003% — najniższe w ekosystemie.
- "Arbitraż" tego samego aktywu jest bardziej niezawodny niż korelacja proxy.

## Reużywalna infrastruktura

`xyz_scanner.py` (ring buffer + allMids), `hl_executor.py` (limit maker + trigger SL/TP),
`quotes.py`. Dochodzi: kolektor feedu referencyjnego (Pyth/TV/Bybit) + silnik spreadu.

---

# SYSTEM #3 — Order-Flow Micro-Momentum / Order-Book Imbalance (OBI)

## Teza

Na płynnym perpie (SOL, HYPE) krótkoterminowy ruch ceny da się przewidzieć z **nierównowagi
księgi zleceń** (więcej wolumenu po stronie bid niż ask = presja w górę) połączonej z
**mikro-momentum** (przyspieszenie ceny na ostatnich tickach) i **agresją w taśmie**
(czy taker'zy biją w ask czy w bid).

## Mechanizm

1. WS L2 book + trade tape z HL (lub Bybit) na 1 płynny perp.
2. Liczymy w oknie ~1–5s:
   - **OBI** = (Σ bid_sz − Σ ask_sz) / (Σ bid_sz + Σ ask_sz) na N poziomach.
   - **Trade imbalance** = (buy_volume − sell_volume) / total w oknie.
   - **Micro-momentum** = przyspieszenie mid-price.
3. Gdy wszystkie trzy zgodne i przekroczą próg → wejście w kierunku presji, TP po kilku tickach,
   SL ciasny. Holding sekundy.

## ⚠️ Dlaczego ODŁOŻONE (najsłabszy edge dla naszego setupu)

- **Najwyższa konkurencja**: to dokładnie to, co robią boty HFT z kolokacją. Ścigamy się
  z graczami, którzy mają przewagę latencji liczoną w mikrosekundach.
- **Edge cienki i nietrwały**: OBI bywa "spoofowany" (fałszywe zlecenia znikające przed fill).
- Wymaga **najszybszej możliwej egzekupcji** (WS order entry, nie REST) — największy nakład
  inżynierski przy najmniejszej pewności zysku.

## Kiedy ma sens

Gdyby HL xyz lub jakiś mniej płynny perp miał **wyraźnie mniej botów HFT** — wtedy OBI
na takim "zaniedbanym" rynku może działać. Czyli: zastosować ideę #3, ale na rynku z #2
(niska konkurencja xyz), nie na zatłoczonym SOL/HYPE. To jest najciekawsza mutacja na przyszłość:
**OBI na rynkach o niskiej konkurencji**.

## Frekwencja

Potencjalnie **bardzo wysoka** (dziesiątki–setki sygnałów dziennie) — ale większość to noise.
Realna liczba dochodowych po fee jest dużo niższa i wymaga twardego progu.

## Reużywalna infrastruktura

`hl_executor.py`, wzorzec WS z bota #1 (kolektor strumieniowy). Dochodzi: parser L2 book
depth + silnik OBI.

---

## Podsumowanie porównawcze

| Cecha | #1 Liquidation Fade (budujemy) | #2 Cross-Venue Lag | #3 OBI Micro-Momentum |
|---|---|---|---|
| Źródło sygnału | Bybit liquidation WS | spread HL xyz vs ref feed | L2 book + tape |
| Typ edge | mechaniczny (forced flow) | strukturalny (latencja) | mikrostruktura |
| Konkurencja | średnia | **niska** | **wysoka (HFT)** |
| Główne ryzyko | kaskada = początek trendu | oracle HL może być szybki | spoofing + wyścig latencji |
| Frekwencja | wysoka, strojona progiem | średnia (tylko w sesji) | b. wysoka (dużo noise) |
| Pewność edge | średnia-wysoka | wymaga walidacji | niska |
| Priorytet | **TERAZ** | później | najpóźniej / jako mutacja na xyz |

---

*Gdy wrócimy do #2 lub #3 — zaczynamy od Fazy 0 (pomiar), tak jak przy #1.*
