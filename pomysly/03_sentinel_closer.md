# Pomysł #3 — Sentinel & Closer (Strażnik Ryzyka i Zamykacz)

> **Pieniądze robi się na WYJŚCIACH i zarządzaniu ryzykiem, nie na wejściach.**
> Większość retail nie ginie przez złe wejścia — ginie przez trzymanie stratnych za długo,
> brak SL i jeden katastrofalny dzień. Ten agent odwraca priorytety: jest **zachowawczy przy
> wejściach, bezwzględny przy wyjściach**. To najkrótsza droga do *stałego dochodu*.

**Filozofia:** najpierw przetrwaj, potem zarabiaj. Agent, który nigdy nie ma złego dnia
przekraczającego limit, z czasem wygrywa samą konsekwencją.

---

## Dwie role agenta

### A) SENTINEL — strażnik księgi (zawsze włączony, event-driven)
Pętla 24/7 (nie cron co godzinę — reaguje na zdarzenia), pilnuje WSZYSTKICH pozycji na 4 venue:

- **Trailing / ratchet stops** — przesuwa SL za ceną gdy trade idzie w zysk (masz wzorzec
  w Senpi DSL + `update_sl`). Zysk się nie oddaje.
- **Skalowanie wyjścia** — realizuje część na TP1, resztę puszcza z trailing (winners run).
- **Cięcie stratnych** — jeśli teza pęka (cena przebija invalidację / whale się odwraca /
  funding flip), zamyka BEZ czekania na pełny SL.
- **Reakcja na zdarzenia** — spike likwidacji (z Twojego kolektora!), high-impact event z
  kalendarza za 5 min, nagły news (firecrawl) → przytnij ryzyko/zabezpiecz.
- **Twardy kill-switch** — strata dzienna >3% → **flatten wszystko + pauza do jutra**.
- **Flatten na szok** — makro-szok (VIX spike, BTC −X% w godzinę) → redukcja całego booka.

### B) CLOSER + curated entries — wejścia są nudne i sprawdzone
Sentinel nie szuka loterii. Wejścia pochodzą z **wąskiej, sprawdzonej białej listy**:
- **Copy najlepszych** — Senpi top traders / `discovery_get_top_traders` (mirror sprawdzonych).
- **Twoje własne setupy** zatwierdzone w `edge_journal` jako działające.
- **liqscalp** — gdy Faza 0 udowodni edge.
Każde wejście przechodzi **pre-mortem** (adwokat diabła) i risk gate. Mało wejść, każde z SL,
każde małe. Cała przewaga jest w tym, co dzieje się PO wejściu.

---

## Czemu to celuje prosto w „$2000/mies."

Stały dochód = **niska zmienność wyników + brak katastrof**. Ten agent:
- nie pozwala jednemu trade'owi ani jednemu dniu zniszczyć miesiąca,
- pozwala zwycięzcom biec (trailing zamiast wczesnego TP),
- tnie stratne, zanim urosną.

To matematyka konsekwencji: nawet przeciętne wejścia + świetne zarządzanie ryzykiem dają
dodatnią, gładką krzywą. Świetne wejścia + złe zarządzanie = zmienna katastrofa. Pensję płaci
gładka krzywa.

---

## Kreatywne dodatki

- **Pre-mortem sub-agent** — przed każdym wejściem osobny prompt „czemu to błąd?". Tani, a
  odsiewa najgorsze trade'y.
- **Korelacja z całym bookiem** — nowe wejście tylko jeśli nie dubluje istniejącej ekspozycji
  (np. już masz 3 longi w alty → kolejny long-alt podnosi ryzyko, nie dywersyfikuje).
- **„Cisza to pozycja"** — agent ma prawo NIE handlować. Brak setupu = gotówka. Większość
  botów przegrywa, bo MUSZĄ działać; ten może czekać.
- **Tryb obronny przy obsuwie** — po 2 stratnych z rzędu automatycznie zmniejsza rozmiar o
  połowę, aż wróci passa (anty-tilt, którego człowiek nie potrafi).

---

## Narzędzia

- **Monitoring pozycji:** `fetch_positions.py`, Senpi `position_tracker` / DSL, Bybit MCP.
- **Wyjścia:** `hl_executor.py update_sl`, Senpi `ratchet_stop_*`, `close_position`.
- **Zdarzenia:** kolektor likwidacji (`scripts/liqscalp`), `econ_calendar.py`, `macro_news.py`.
- **Wejścia:** Senpi `discovery_get_top_traders` + `strategy_create` (copy), `edge_journal`.
- **Kokpit:** Telegram (`status`, `flatten`, `pause`).

---

## Tryby i bezpieczeństwo

Sentinel jest z natury warstwą bezpieczeństwa, więc może działać **od razu w trybie
półautonomicznym nad Twoimi obecnymi ręcznymi pozycjami** — np. tylko pilnować SL i alarmować,
zanim damy mu prawo do zamykania. To najbezpieczniejszy pierwszy „żywy" agent ze wszystkich.

---

## ✅ Plusy / ⚠️ Minusy

**Plusy:** celuje w to, co naprawdę decyduje o dochodzie (ryzyko/wyjścia). Pasuje do KAŻDEGO
źródła wejść (działa też nad #1 i #2 jako ich Guardian). Może wystartować najszybciej w realu,
bo zaczyna od pilnowania, nie od ryzykownych wejść. Chroni kapitał = chroni „pensję".

**Minusy:** ogranicza górę (zachowawczy — nie złapie każdego pompowania). Wymaga niezawodnych
feedów w czasie rzeczywistym (event-driven, nie tylko cron) — trochę więcej inżynierii pętli.

**Dla kogo:** **warstwa Guardian dla całego systemu.** Nawet jeśli wybierzesz #1 lub #2 jako
„mózg" wejść, Sentinel z #3 powinien pilnować booka. Najlepszy stosunek „bezpieczeństwo do
wysiłku" i najszybsza realna wartość: zacznij od trybu „pilnuj i alarmuj" już nad obecnymi
pozycjami (np. nad Twoim longiem SOL na Bybit).
