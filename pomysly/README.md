# 💡 Pomysły — Autonomiczny Trader (Hermes Agent)

Folder na koncepcje workflow, które przekazują **pracę tradera** agentowi Hermes
(agentyczny brat Claude Code: te same narzędzia/MCP, cron jobs, tańsze modele).

Cel użytkownika: **ekspert-trader, który zarabia na życie (~$2000/mies.)** — wstaje rano,
czyta rynek, analizuje, handluje, pilnuje pozycji, zamyka/odwraca — jak człowiek, ale
szybciej, bez emocji i bez przeoczeń.

**Data:** 2026-06-20 · **Autor:** Claude Code + krypt

> Folder nazwany `pomysly` (bez „ł") celowo — bezpieczne ścieżki w PowerShell/git/bash.

---

## ⚠️ Najpierw uczciwa matematyka (czytaj zanim się nakręcisz)

„$2000/mies." to **kapitał × miesięczna stopa zwrotu × konsekwencja** — nie magia agenta.

| Kapitał | Potrzebna stopa/mies. na $2k | Realność |
|---|---|---|
| $1 000 | **+200%** | niemożliwe bez samobójczego ryzyka |
| $10 000 | +20% | bardzo agresywne, rzadko utrzymywalne |
| $25 000 | +8% | ambitne, ale w zasięgu dobrego systemu |
| $50 000 | +4% | realne dla solidnego, konsekwentnego edge |

**Wniosek:** zadaniem agenta #1 jest **nie wysadzić konta i być konsekwentnym**. $2k przyjdzie
z *kapitału × udowodnionego edge*, nie z forsowania zysku na małym koncie. Dlatego każdy
pomysł zaczyna w **trybie shadow (paper)**, dowodzi krzywej kapitału, i dopiero wtedy
skalujemy kapitał. Agent, który robi stabilne +5%/mies. bez obsuwy > agent, który raz robi
+50% i raz traci wszystko.

---

## 🧱 Wspólna architektura (warstwy) — fundament wszystkich 3 pomysłów

Trader-agent to NIE jeden wielki prompt. To **warstwy** o różnej częstotliwości i koszcie:

```
┌─ SENSOR (tanio, często) ── zbiera dane: ceny, OI, funding, whale, news, kalendarz,
│                            sentyment, likwidacje, pozycje. Cron co 5–60 min. Tani model.
├─ ANALYST (średnio) ─────── synteza: łączy sygnały w jeden obraz + scoring setupów.
│                            Kilka razy dziennie. Model średni (grok-4 / sonnet).
├─ STRATEGIST (drogo, rzadko) decyzja: WCHODZĘ / NIE / ZAMYKAM / ODWRACAM + rozmiar.
│                            Tylko gdy jest realny setup. Model mocny (opus / grok-4.3).
├─ EXECUTOR (kod, ZERO LLM) ─ składa zlecenia: sizing, SL/TP, zaokrąglenia. Deterministyczny.
│                            LLM NIGDY nie składa zlecenia bezpośrednio — tylko przez kod.
├─ GUARDIAN (zawsze włączony) ryzyko: trailing stop, kill-switch dzienny, flatten na szok.
│                            Reaguje w czasie rzeczywistym, nie czeka na crona.
└─ REVIEWER (raz dziennie/tydz) nauka: czyta dziennik trade'ów → proponuje poprawki.
```

**Złota zasada bezpieczeństwa:** LLM *decyduje*, **kod *wykonuje***. Model nigdy nie ma
bezpośredniego dostępu do „kup/sprzedaj" — zwraca ustrukturyzowaną decyzję (JSON), a
deterministyczny executor (jak nasz `scripts/liqscalp/executor.py`) ją waliduje i składa,
z twardymi limitami ryzyka, których prompt nie obejdzie.

---

## 💸 Routing modeli (żeby koszty Cię nie zjadły)

| Warstwa | Częstotliwość | Model | Czemu |
|---|---|---|---|
| Sensor / monitoring | co 5–30 min | **grok-3-mini / haiku** | dużo wywołań, prosta robota |
| Analyst / synteza | 2–4× dzień | grok-4 / sonnet | łączenie danych, scoring |
| Strategist / decyzja | tylko na setup | **opus / grok-4.3** | tu zarabiasz lub tracisz |
| Reviewer | 1× dzień/tydz | sonnet / grok-4 | refleksja, mało wywołań |

Klucz: **eskalacja na żądanie**. 95% cykli to tani monitoring; drogi model odpala się tylko,
gdy tani wykryje, że „dzieje się coś, co wymaga decyzji".

---

## 🎛️ Powierzchnia kontroli i tryby autonomii

- **Telegram = kokpit.** Agent melduje plan, pyta o zgodę, przyjmuje komendy: `status`,
  `approve`, `veto`, `flatten` (zamknij wszystko), `pause`.
- **3 tryby dojrzałości** (każdy pomysł przechodzi je po kolei):
  1. **SHADOW** — pełna symulacja (paper), zero kasy. Dowodzimy edge na żywym rynku.
  2. **SEMI-AUTO** — agent proponuje, Ty klikasz `approve` w Telegramie. Człowiek w pętli.
  3. **FULL-AUTO** — agent działa sam, w twardych limitach + kill-switch. Dopiero po dowodach.

---

## 🪜 Te 3 pomysły to NIE alternatywy — to drabina dojrzałości

| # | Pomysł | Filozofia | Kiedy wdrożyć |
|---|---|---|---|
| **1** | [Hermes Trading Desk](01_hermes_trading_desk.md) | jeden trader, dzień jak człowiek | **START** — najniższy próg, reużywa `hermes.py` |
| **2** | [Signal Senate](02_signal_senate.md) | komitet strategii + alokator kapitału | gdy masz ≥3 udowodnione edge do dywersyfikacji |
| **3** | [Sentinel & Closer](03_sentinel_closer.md) | ryzyko/zarządzanie > wejścia | równolegle — warstwa Guardian dla 1 i 2 |

**Rekomendowana ścieżka:** zacznij od **#1 w trybie shadow**, dołóż warstwę Guardian z **#3**
jako zawsze-włączony nadzór ryzyka, a **#2** wprowadź, gdy masz kilka sprawdzonych źródeł
sygnału (liqscalp, whale-copy, Senpi fleet…) wartych alokacji. Razem składają się na jeden
system: Desk myśli, Sentinel pilnuje, Senate dzieli kapitał.

---

## Co dalej

Przeczytaj 3 dokumenty, powiedz który (lub jaki miks) Ci gra — wtedy zrobię z wybranego
**konkretny plan budowy** (cron schedule, pliki, prompty, limity) tak jak przy bocie likwidacyjnym.
Wszystko zacznie od shadow. Nic nie idzie na żywą kasę bez dowodu na krzywej kapitału.
