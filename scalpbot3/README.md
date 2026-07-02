# ScalpBot3 — Faza 0 (pomiar edge'u)

Nowy bot scalpowy budowany od zera. **Wdrażana strategia: A (Event-Lag Sniper)**,
kolektor zbiera dane dla **obu** strategii (A + B). Pełne uzasadnienie i logika: [`PLAN.md`](PLAN.md).

**Zasada żelazna (z liqscalp — sprawdziła się):** żaden paper/live, dopóki Faza 0 nie
udowodni edge'u po fee. Tu Faza 0 mierzy zjawiska fizyczne (lag oracle, spread giełd) →
werdykt binarny w **dni, nie miesiące**.

---

## Co robi kolektor

Samowystarczalny (zero importów ze `scripts/`), zbiera równolegle z timestampami ms:

| Źródło | Co | Dla strategii |
|---|---|---|
| **Pyth Hermes** | GOLD, SILVER, CL(WTI spot), SP500(SPY) — szybka referencja | A |
| **HL xyz** | xyz:GOLD/SILVER/SP500/CL — potencjalnie wolny oracle | A |
| **HL perp** | BTC, ETH, SOL, HYPE | B |
| **Extended** | BTC/ETH/SOL/HYPE mark + funding | B |

Wynik → `data/scalpbot3.db` (własna baza SQLite, **nie dotyka** `db.py`).

> **SP500:** Pyth nie ma czystego indeksu S&P — używamy SPY ETF (~1/10 poziomu indeksu,
> godziny US). Skala x10 jest OK: edge liczymy na **zwrotach %**, nie cenie bezwzględnej.
> SPY handluje w sesji US = dokładnie okno eventów CPI/NFP/FOMC.

---

## Pliki

| Plik | Rola |
|---|---|
| `collector.py` | Faza 0 — 4 pollery → SQLite. Heartbeat co 30 s. |
| `store.py` | warstwa SQLite (writer-thread + kolejka, WAL) |
| `research_lag.py` | **werdykt strategii A**: lead-lag, rozkład spreadu, event study, expectancy po fee |
| `run_collector.bat` | uruchom lokalnie (Windows) |
| `run_collector.sh` / `scalpbot3.service` | uruchom na VPS (Linux) |

Do napisania **po** Fazie 0 (dla zwycięzcy): `detector.py`, `executor.py`, `bot.py`,
oraz `research_basis.py` (werdykt B).

---

## Uruchomienie — LOKALNIE (Windows, szybki test)

```powershell
# zbieraj (zostaw okno; Ctrl+C konczy)
scalpbot3\run_collector.bat

# podglad zebranych danych + snapshot spread/basis
.venv\Scripts\python.exe scalpbot3\collector.py --stats

# werdykt strategii A (po min. dobie, najlepiej tydzien)
.venv\Scripts\python.exe scalpbot3\research_lag.py
.venv\Scripts\python.exe scalpbot3\research_lag.py --asset CL --jump-bps 8
```

Diagnostyka mapowania Pyth (bez zbierania):
```powershell
.venv\Scripts\python.exe scalpbot3\collector.py --resolve-only
```

---

## Uruchomienie — VPS (Hostinger, produkcja 24/7) ✅ zalecane

Kolektor jest **w pełni VPS-owalny**: tylko publiczne feedy + SQLite, **zero sekretów**
(nie potrzebuje `.env`!), zero podpisywania kluczem, zero windowsowych zależności
(SSL sam spada z truststore na certifi). Konwencja zgodna z `SERWER.md` (repo w `/trading-ai/`).

```bash
# 1. na VPS: pobierz kod (po git push z laptopa)
cd /trading-ai && git pull

# 2. jednorazowy test na pierwszym planie (Ctrl+C konczy)
cd /trading-ai/scalpbot3 && /trading-ai/.venv/bin/python collector.py

# 3. PIERWSZE WDROZENIE — systemd (auto-restart, log do pliku)
sudo cp /trading-ai/scalpbot3/scalpbot3.service /etc/systemd/system/trading-scalpbot3.service
sudo systemctl daemon-reload
sudo systemctl enable --now trading-scalpbot3
systemctl status trading-scalpbot3 --no-pager

# 4. podglad
tail -f /trading-ai/logs/scalpbot3.log
/trading-ai/.venv/bin/python /trading-ai/scalpbot3/collector.py --stats

# aktualizacja kodu pozniej: git pull + systemctl restart trading-scalpbot3
```

Jesli brakuje httpx w venv: `/trading-ai/.venv/bin/pip install httpx` (research = czysty stdlib).

**Uwaga o lagu (strategia A):** mierzymy **względną** różnicę timestampów dwóch feedów
docierających do *tej samej* maszyny — lokalizacja VPS prawie nie wpływa na werdykt.
Idealnie kolektor na tym samym VPS, na którym potem będzie handel → zmierzony lag ≈ realny.

---

## Kryteria werdyktu (Faza 0)

**Strategia A** (`research_lag.py`) — szukamy w danych:
- **lead-lag**: peak cross-correlation przy `lag > 0` (xyz podąża za Pyth) o stabilnej wartości;
- **event study**: gdy Pyth skacze ≥ próg, xyz dogania z opóźnieniem, `median NET po fee > 0`;
- **KILL:** peak przy lag ≤ 0 (oracle szybki) LUB median NET ≤ 0 → strategia A odrzucona, tanio.

**Spread jako baza vs oscylacja:** `mean ≫ sd` = trwała baza (mało miejsca na fade);
`mean ≈ 0, duże sd` = oscylacja (potencjał). Trwała baza na strategię A jest OK, jeśli to
**lag** (xyz dogania), a nie stała różnica feedów.

Minimum na werdykt: **~tydzień** danych z sesji US + **≥1 duży event makro** (CPI/NFP/FOMC).
Bez eventu event-study nie ma czego mierzyć.
