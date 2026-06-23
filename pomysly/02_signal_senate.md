# Pomysł #2 — Signal Senate (Komitet Sygnałów + Alokator Kapitału)

> **Nie jeden trader — cały zespół analityków, którzy głosują, a „dyrektor inwestycyjny"
> dzieli kapitał między najlepsze, nieskorelowane pomysły.** Edge nie leży w jednej
> przepowiedni, tylko w **dywersyfikacji i alokacji** — to daje gładką krzywą kapitału,
> czyli najbliżej „pensji".

**Filozofia:** mały fundusz quant we własnym domu. Każde Twoje narzędzie to osobny „analityk".

---

## Jak to działa

### 1. Magistrala sygnałów (signal bus)
Każdy scanner/strategia pisze swoje propozycje do wspólnej tabeli w DB (np. `signal_bus`):

```
źródło | symbol | kierunek | siła(0-10) | teza | ważność_do | ts
liqscalp        | SOL  | long  | 8 | kaskada wyczerpana        | +5 min  | ...
whale_tracker   | BTC  | long  | 7 | whale net-long +$12M      | +4 h    | ...
smart_money     | HYPE | long  | 6 | top trader otworzył       | +6 h    | ...
correlation     | GOLD | short | 5 | DXY lag                   | +2 min  | ...
senpi_fleet     | ETH  | long  | 9 | 3 agenty zgodne           | +8 h    | ...
pine_webhook    | SOL  | long  | 7 | ZeroLag + MTF align       | +12 h   | ...
```

Źródła, które już masz jako „analityków": `hl_whale_tracker`, `smart_money_tracker`,
`insider_tracker`, `volume_scanner`, `listings_scanner`, `kozaki_monitor`, `correlation_scalp`,
`liqscalp`, **Senpi fleet** (grizzly/kodiak/polar… — kilkanaście agentów!), Pine z `tv_webhook`.

### 2. Dyrektor Inwestycyjny (PM agent, cron co 15–30 min)
Mocny model czyta **żywe** propozycje z busa i:
1. **Waży po torze wyników** — każde źródło ma swój track record w DB (win rate, PnL z
   ostatnich N trade'ów). Whale-tracker celny 70%? Liczy się mocniej. Scanner, który ostatnio
   tylko tracił? Ważony w dół (jak usuwanie 0xeadc z watchlisty kozaków, które już robisz).
2. **Sprawdza korelację/koncentrację** — 5 sygnałów na „long alty" to JEDEN zakład, nie pięć.
   Wybiera **nieskorelowane** pomysły, żeby nie postawić wszystkiego na to samo.
3. **Alokuje budżet ryzyka** — np. 6% portfela na otwarte ryzyko, dzielone między 3–4 najlepsze
   nieskorelowane idee proporcjonalnie do siły × wiarygodności źródła.
4. **Zleca** — executor składa, Guardian (z #3) pilnuje wyjść.

### 3. Auto-ewolucja (Reviewer, codziennie)
Źródła z trwale ujemnym PnL są **degradowane lub wyłączane**; nowe wchodzą w shadow i muszą
„zasłużyć" na realny kapitał. System sam przesuwa kapitał do tego, co działa.

---

## Sekretna broń: Senpi jako gotowy silnik

Masz już **Senpi runtime** (DSL exits, risk guard rails, FEE_OPTIMIZED_LIMIT) + **flotę agentów**
(grizzly=BTC, kodiak=SOL, polar=ETH, wolverine=HYPE, owl=contrarian, pangolin=funding-fade…).
Senate może być **meta-alokatorem nad Senpi**: zamiast budować egzekucję od zera, PM agent
decyduje *którym* agentom Senpi dać kapitał w danym reżimie, a Senpi wykonuje. To skraca drogę
o miesiące.

---

## Reżimy rynku (kreatywny dodatek)

Osobny lekki „Regime Detector" (cron co 1 h) klasyfikuje rynek: **trend / chop / risk-off**
(z VIX, BTC 4h, funding, fear&greed). PM włącza inne zestawy analityków per reżim:
- **Trend** → momentum/whale/Senpi trend-hunters.
- **Chop** → faders (owl, pangolin, correlation_scalp, liqscalp).
- **Risk-off** → redukcja ekspozycji, tylko najpewniejsze, więcej gotówki.

Jeden parametr (reżim) przełącza zachowanie całego systemu — tak działają prawdziwe deski.

---

## Tryby i bezpieczeństwo

- SHADOW: cały bus + decyzje PM logowane jako paper; mierzymy krzywą kapitału ensemble vs
  pojedyncze źródła (czy dywersyfikacja faktycznie wygładza).
- SEMI/FULL-AUTO: jak w #1, plus **limit koncentracji** (max % w jednym koszyku korelacji) i
  globalny dzienny kill-switch.

---

## ✅ Plusy / ⚠️ Minusy

**Plusy:** dywersyfikacja → gładsza krzywa → najbliżej „stałej pensji". Edge w alokacji, nie w
jednej prognozie. Samo-uczący się (kapitał płynie do tego, co działa). Maksymalnie reużywa
Twój arsenał + Senpi.

**Minusy:** najwięcej infrastruktury (bus, atrybucja wyników, scoring źródeł). **Zimny start** —
ważenie po torze wyników wymaga danych historycznych (rozwiązanie: pierwsze tygodnie równe wagi
w shadow, potem przełącz na ważenie po wynikach).

**Dla kogo:** etap docelowy, gdy masz **kilka udowodnionych edge** wartych połączenia.
To jest maszyna, która realnie może dowieźć stabilny miesięczny zwrot — pod warunkiem, że
poszczególne edge są dodatnie (dlatego najpierw #1 i Faza 0 botów).
