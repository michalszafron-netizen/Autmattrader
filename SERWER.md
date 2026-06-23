# 🖥️ Zarządzanie serwerem VPS — trading-ai

**Hostinger | Ubuntu 24.04 | IP: srv856418 | Folder: `/trading-ai/`**

---

## 🟢 Co działa na VPS (24/7, auto-start)

| Daemon | Skrypt | Co robi | Interval |
|--------|--------|---------|----------|
| `trading-smart-money` | `smart_money_tracker.py` | Śledzi pozycje hybrydowej listy traderów HL: top 20 wg tygodniowego PnL + top 20 wg wartości konta (deduplikacja, ~30-40 unikalnych portfeli — łapie też "grubasów" pomijanych przez czyste rankingi PnL). Wysyła alert gdy otworzą/zamkną/zwiększą pozycję ≥$50k | co 1h |
| `trading-listings` | `listings_scanner.py` | Skanuje nowe listingi na Binance, Coinbase, Bybit, OKX, Kraken | co 5 min |
| `trading-volume` | `volume_scanner.py` | Anomalie wolumenowe Binance Futures+Spot (próg 3x). Alert na Telegram | co ~1 min |
| `trading-webhook` | `tv_webhook.py` | TradingView alerty → Alpaca/HL executor. POST /tv, GET /oi_history na porcie 5005 (proxy: `tv-webhook-proxy` + Traefik → `https://tv.prawosfera.online`) | zawsze online |
| `trading-copybot` | `copy_bot.py --daemon` | **Copy trading (PAPER)** — śledzi kilku traderów HL naraz, symuluje mirror (target-position reconciliation), alert na Telegram przy OPEN/CLOSE/ADD/REDUCE. Bez Senpi. Traderzy w `config/copy_trader.json` | co 60s |

> `trading-ngrok` zostal wycofany 2026-06-22 — patrz sekcja "ngrok — WYCOFANY" nizej.

### Cron (Eddie / Maggie / Frank — Insider Intelligence)

| Job | Skrypt | Kiedy |
|-----|--------|-------|
| Eddie | `insider_tracker.py form4` | codziennie 06:00 UTC |
| Maggie | `insider_tracker.py institutional` | niedziela 19:00 UTC |
| Frank | `insider_tracker.py fed` | poniedziałek 08:00 UTC |

### Cron (oi-tracker — 14D Open Interest history)

| Job | Skrypt | Kiedy |
|-----|--------|-------|
| oi-tracker | `oi_tracker.py --brief --no-history` | co godzinę (min. 5) |

Zapisuje snapshot OI do `data/trading.db` na VPS (24/7, niezależnie od tego czy
lokalny dashboard na Windows jest włączony). Historia jest wystawiona przez
`GET /oi_history` na `tv_webhook.py` (patrz sekcja "Endpointy" niżej) —
`scripts/oi_tracker.py` odpytuje ten endpoint, żeby policzyć trend 14D i
interpretację niezależnie od tego, gdzie jest odpalany (VPS albo Windows).

---

## 📋 Komendy zarządzania

### Status wszystkich demonów
```bash
systemctl status trading-smart-money trading-listings trading-volume --no-pager
```

### Logi (na żywo)
```bash
tail -f /trading-ai/logs/smart_money.log
tail -f /trading-ai/logs/listings.log
tail -f /trading-ai/logs/volume.log
tail -f /trading-ai/logs/webhook.log
```

### Restart pojedynczego demona
```bash
systemctl restart trading-smart-money
systemctl restart trading-listings
systemctl restart trading-volume
systemctl restart trading-webhook
systemctl restart trading-copybot
```

### Stop / Start
```bash
systemctl stop trading-smart-money
systemctl start trading-smart-money
```

### Restart wszystkich demonów
```bash
systemctl restart trading-smart-money trading-listings trading-volume trading-webhook
systemctl status trading-smart-money trading-listings trading-volume trading-webhook --no-pager
```

### Aktualizacja kodu (po git push z laptopa)
```bash
cd /trading-ai
git pull
systemctl restart trading-smart-money trading-listings trading-volume trading-webhook
systemctl status trading-smart-money trading-listings trading-volume trading-webhook --no-pager
```

> ⚠️ Gdy `git pull` narzeka *"local changes would be overwritten"* na pliku który serwer sam zapisuje (np. `alerts.jsonl`, `annual.txt`) — porzuć lokalną wersję i ponów: `git checkout -- alerts.jsonl && git pull`. To tylko logi, odtworzą się.

---

## 🤖 Copy Bot (trading-copybot) — copy trading PAPER

Śledzi kilku traderów HL naraz i symuluje mirror (bez Senpi, bez realnych pieniędzy).
Traderzy + kapitał + mnożnik: `config/copy_trader.json`. Tryb paper wymuszony w pliku
`.service` (`Environment=HL_TRADING_MODE=paper`). Dane: SQLite `data/trading.db`
(tabele `copybot_positions`, `copybot_actions`). Log: `/trading-ai/logs/copybot.log`.

### Komendy zarządzania
```bash
# Status usługi
systemctl status trading-copybot --no-pager

# Log na żywo (Ctrl+C wychodzi z podglądu, NIE zatrzymuje bota)
tail -f /trading-ai/logs/copybot.log

# Restart (po git pull z nowym kodem copy bota)
systemctl restart trading-copybot

# Stop / Start
systemctl stop trading-copybot
systemctl start trading-copybot

# Podgląd portfeli (status traderów, jednorazowo)
cd /trading-ai && HL_TRADING_MODE=paper TRADING_MODE=paper .venv/bin/python scripts/copy_bot.py --status

# Reset wirtualnych portfeli (start od zera — np. po zmianie traderów w configu)
cd /trading-ai && HL_TRADING_MODE=paper TRADING_MODE=paper .venv/bin/python scripts/copy_bot.py --reset && systemctl restart trading-copybot
```

### Śledzeni traderzy (stan: 2026-06-11)
| Adres | Profil |
|-------|--------|
| `0xe21b` | Snajper HYPE (ELITE, all-time +$408k, ale ZNIKA na całe dni) |
| `0xba93` | Konserwatywny (konto 2.5 roku, DD-10%, WR93%, ~5 tradów/dzień) |
| `0x4b1c` | Maszyna HFT ($2M, DD-4.5%, ~26 pozycji naraz, zawsze aktywny) |

Zmiana traderów: edytuj `config/copy_trader.json` (`"active": true/false`) → `git push` z laptopa → `git pull` na VPS → `systemctl restart trading-copybot`.

### PIERWSZE WDROŻENIE (zrobione 2026-06-11 — dokumentacja dla odtworzenia)
Plik `/etc/systemd/system/trading-copybot.service`:
```ini
[Unit]
Description=Copy Bot — paper copy-trading (multi-trader, bez Senpi)
After=network.target

[Service]
WorkingDirectory=/trading-ai
Environment=HL_TRADING_MODE=paper
Environment=TRADING_MODE=paper
ExecStart=/trading-ai/.venv/bin/python scripts/copy_bot.py --daemon
Restart=always
RestartSec=10
StandardOutput=append:/trading-ai/logs/copybot.log
StandardError=append:/trading-ai/logs/copybot.log

[Install]
WantedBy=multi-user.target
```
Aktywacja: `systemctl daemon-reload && systemctl enable --now trading-copybot`

> ⚠️ **PAPER only.** Egzekucja na realne pieniądze (live) NIE jest jeszcze zaimplementowana
> w `copy_bot.py` — bot blokuje start w trybie live. Przejście na live = osobna sesja
> (maker-limity, kill switch -3%, obowiązkowy SL).

---

## 📁 Struktura folderów na VPS

```
/trading-ai/
├── scripts/               # wszystkie skrypty
├── data/
│   └── trading.db         # SQLite — snapshoty, alerty, pozycje
├── logs/
│   ├── smart_money.log    # logi Smart Money Tracker
│   ├── listings.log       # logi Listings Scanner
│   └── volume.log         # logi Volume Scanner
├── .env                   # SEKRETY — nigdy nie ruszaj git pull
├── .venv/                 # Python virtualenv
└── requirements.txt       # zależności
```

---

## ⚠️ Ważne zasady

1. **NIE rób `git pull` bez `systemctl restart`** — kod się zmieni ale procesy nadal będą na starym
2. **NIE edytuj `.env` przez git** — plik jest gitignored, zmiany rób przez `nano /trading-ai/.env`
3. **Kernel upgrade** — gdy zobaczysz "Pending kernel upgrade", wpisz `reboot` (daemony wstają same)
4. **Backup bazy** — co jakiś czas pobierz `data/trading.db` na laptop (historia snapshotów)

---

## 🔧 Diagnostyka problemów

### Daemon crashuje w pętli
```bash
journalctl -u trading-smart-money -n 50 --no-pager
```

### Sprawdź czy Python i .env są OK
```bash
cd /trading-ai && source .venv/bin/activate
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('DEEPSEEK_API_KEY','BRAK')[:8])"
```

### Wyczyść stare logi (jeśli za duże)
```bash
truncate -s 0 /trading-ai/logs/smart_money.log
truncate -s 0 /trading-ai/logs/listings.log
truncate -s 0 /trading-ai/logs/volume.log
truncate -s 0 /trading-ai/logs/webhook.log
```

---

## 🚀 PIERWSZE WDROŻENIE — trading-webhook (tv_webhook.py)

Wykonaj raz na VPS. Potem normalny flow to tylko `git pull` + `systemctl restart`.

### Krok 1 — utwórz plik service

```bash
sudo nano /etc/systemd/system/trading-webhook.service
```

Wklej dokładnie to:

```ini
[Unit]
Description=TradingView Webhook — TV alert to Alpaca/HL executor
After=network.target

[Service]
WorkingDirectory=/trading-ai
ExecStart=/trading-ai/.venv/bin/python scripts/tv_webhook.py
Restart=always
RestartSec=5
EnvironmentFile=/trading-ai/.env
StandardOutput=append:/trading-ai/logs/webhook.log
StandardError=append:/trading-ai/logs/webhook.log

[Install]
WantedBy=multi-user.target
```

Zapisz: `Ctrl+O` → `Enter` → `Ctrl+X`

### Krok 2 — załaduj, włącz, uruchom

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-webhook
sudo systemctl start trading-webhook
sudo systemctl status trading-webhook --no-pager
```

### Krok 3 — sprawdź że działa

```bash
# Logi na żywo
tail -f /trading-ai/logs/webhook.log

# Health check
curl http://localhost:5005/health
# Powinno zwrócić: {"status":"ok","trading_mode":"live",...}
```

### Krok 4 — otwórz port 5005 w firewallu (jeśli UFW aktywny)

```bash
sudo ufw allow 5005/tcp
sudo ufw status
```

### Krok 5 — ustaw URL w TradingView

W każdym alercie TV w polu **Webhook URL** wpisz:
```
http://TWÓJ_VPS_IP:5005/tv?secret=TWÓJ_TV_SECRET
```

`TWÓJ_TV_SECRET` to wartość `TV_SECRET` z `.env` na VPS.

---

## 🚀 PIERWSZE WDROŻENIE — Insider Intelligence (Eddie / Maggie / Frank)

Wykonaj raz na VPS.

### Krok 1 — zainstaluj crony

```bash
cd /trading-ai
bash scripts/install_insider_cron.sh
```

### Krok 2 — sprawdź crony

```bash
crontab -l | grep insider
# Powinno pokazać 3 wpisy: form4, institutional, fed
```

### Krok 3 — test ręczny (opcjonalnie)

```bash
cd /trading-ai && source .venv/bin/activate
python scripts/insider_tracker.py form4
# Powinien wysłać sygnał na Telegram
```

---

## 🔧 Logi webhook

```bash
tail -f /trading-ai/logs/webhook.log
tail -100 /trading-ai/logs/webhook.log | grep -i "error\|failed\|executed"

# Ostatnie 20 alertów przez API (gdy serwer działa)
curl http://localhost:5005/alerts
```

---

## 🚀 PIERWSZE WDROŻENIE — ngrok (tunel HTTPS dla TradingView)

### Dlaczego ngrok?

TradingView akceptuje tylko port 80 (HTTP) lub 443 (HTTPS z ważnym certyfikatem).
VPS używa Traefika z Dockerem na portach 80/443 (inne projekty: n8n, kryptopit itd.).
Let's Encrypt jest zablokowany przez limit certyfikatów dla domeny `hstgr.cloud` (Hostinger shared domain, 50k cert/tydzień).
**Rozwiązanie:** ngrok jako tunel — Flask działa lokalnie na porcie 5005, ngrok wystawia publiczny URL HTTPS.

### Instalacja (raz)

```bash
snap install ngrok
ngrok config add-authtoken TWÓJ_AUTHTOKEN
# authtoken znajdziesz na: https://dashboard.ngrok.com/authtokens
```

### ngrok — WYCOFANY (2026-06-22)

ngrok tunelowanie zostało usunięte. Powód: free-tier ngrok wyczerpał miesięczny limit transferu
(`ERR_NGROK_725`), co blokowało WSZYSTKIE webhooki (403 Forbidden) — łącznie z Alpaca i Extended —
do końca miesiąca rozliczeniowego. To był już drugi/trzeci incydent tego typu.

Pierwsza próba zamiany na `http://92.112.181.37:5005/tv` (bezpośrednio przez IP) odpadła —
TradingView wymaga HTTPS dla niestandardowych portów ("Only port 80 is allowed for HTTP").
Port 80/443 na VPS jest zajęty przez Traefik (obsługuje 8 innych projektów: kebabrank, kryptopit,
radca, n8n, media-master, kokoro-tts) — **nie wolno** ruszać głównego configu Traefika.

**Finalne rozwiązanie:** nowy, izolowany kontener `tv-webhook-proxy` (nginx:alpine) w
`/opt/tv-webhook-proxy/` na VPS, podłączony do sieci `root_default` z własnym Traefik labelem
(`Host(tv.prawosfera.online)`), w pełni addytywny — zero zmian w innych routerach/projektach.
Traefik automatycznie wystawił certyfikat Let's Encrypt dla tej subdomeny (resolver `mytlschallenge`,
ten sam co dla innych projektów).

```bash
# Pliki konfiguracji (lokalnie w repo):
#   deploy/tv-webhook-proxy/docker-compose.yml
#   deploy/tv-webhook-proxy/nginx.conf
# Deploy:
scp deploy/tv-webhook-proxy/*.* root@92.112.181.37:/opt/tv-webhook-proxy/
ssh root@92.112.181.37 "cd /opt/tv-webhook-proxy && docker compose up -d"
```

DNS: rekord A `tv.prawosfera.online` → `92.112.181.37` (TTL 14400, u rejestratora domeny).

```bash
# Zatrzymać/wyłączyć stary ngrok tunel (już zatrzymany):
pkill ngrok 2>/dev/null
```

### Weryfikacja

```bash
curl https://tv.prawosfera.online/health
# Powinno zwrócić: {"status":"ok","trading_mode":"live",...}
```

### TradingView Webhook URL (aktualny)

```
https://tv.prawosfera.online/tv?secret=tvhook_markowyy_2026
```

**WAŻNE:** zaktualizuj URL w każdym alercie TradingView (ZL-Volatility v1, IMBUS v1) —
stary `https://gladiator-doorbell-handwoven.ngrok-free.dev/tv` już nie działa (403, limit ngrok),
a `http://92.112.181.37:5005/tv` jest odrzucany przez TradingView (custom port + HTTP).

### Endpointy tv_webhook.py (przez tę samą domenę)

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/tv` | POST | TradingView alert → egzekucja (wymaga `?secret=`) |
| `/health` | GET | status serwisu |
| `/alerts` | GET | ostatnie 50 alertów |
| `/clear` | DELETE | czyści alerts.jsonl (wymaga `?secret=`) |
| `/oi_history` | GET | historia OI z `oi_snapshots` (2026-06-22+), zasilana cronem `oi_tracker.py --no-history` co godzinę. `?coin=BTC&days=14` → lista; bez `coin` → `{coin: [...]}`. Wymaga `?secret=`. Czyta `scripts/oi_tracker.py` (lokalnie na Windows albo z VPS — wybiera ten endpoint jako pierwszy, lokalny SQLite jako fallback) |

### Ważne uwagi

- Traefik + Docker na portach 80/443 NIE są ruszane na poziomie config — `tv-webhook-proxy` to
  tylko nowy kontener z własnymi labelami, identyczny mechanizm jak kebabrank/kryptopit/radca
- Wymagany był 2× restart `root-traefik-1` żeby wymusić świeże żądanie ACME (DNS negative-cache,
  ~10 min od dodania rekordu) — restart Traefika to ~2-5s przerwy dla WSZYSTKICH projektów za nim,
  nie tylko webhooka. Potwierdzone że wszystkie 8 innych kontenerów przetrwało bez zmian.
- `tv_webhook.py` wciąż słucha lokalnie na `127.0.0.1:5005` (systemd `tv-webhook.service`,
  niezmieniony) — `tv-webhook-proxy` to jedyny nowy element, czysty reverse-proxy bez logiki

---

---

## 📡 TradingView → VPS → Extended/Alpaca — pełny setup (2026-06-18)

### Architektura — dwubiegunowy system

```
AUTOMATYCZNY (24/7 przez VPS):
  TradingView alert → ngrok (VPS:443) → tv_webhook.py (VPS:5005)
    ├─ venue="extended" → extended_order.py → Extended DEX (x10 SDK)
    └─ venue="alpaca"   → alpaca_executor.py → Alpaca (paper)

MANUALNY (lokalnie, na żądanie):
  Claude / Hermes → extended_order.py lokalnie → Extended DEX
                 → alpaca_executor.py lokalnie → Alpaca
```

Dashboard (server.py, port 5007) działa **lokalnie** na laptopie. VPS odpowiada tylko za webhook.

---

### Co naprawiono 2026-06-18

**Problem 1 — brak `.env` na VPS**
VPS nie miał pliku `.env`. Klucze były w środowisku procesu dashboardu (screen session, który żył od pierwszego wdrożenia). Po restarcie procesy straciłyby klucze. Naprawka: utworzono `/trading-ai/.env`.

**Problem 2 — brak `EXTENDED_STARK_PRIVATE`**
Klucz prywatny Extended był tylko w lokalnym `.env` na laptopie, nigdy nie trafił na VPS. Stąd każdy sygnał IMBUS zwracał `[BŁĄD] Brak w .env: EXTENDED_STARK_PRIVATE`. Alpaca działała bo miała klucze z dziedziczonego env dashboardu — Extended nie.

**Problem 3 — brak pakietu `x10-python-trading-starknet`**
SDK Extended nie był zainstalowany w `.venv` na VPS (`ModuleNotFoundError: No module named 'x10'`). Instalacja: `.venv/bin/pip install x10-python-trading-starknet`.

**Problem 4 — usługa `trading-webhook` vs `tv-webhook`**
Istniejąca dokumentacja mówiła o `trading-webhook.service`. Faktycznie aktywna usługa to `tv-webhook.service` (utworzona 2026-06-18, załadowana przez `EnvironmentFile`).

---

### Aktualny stan po naprawkach

| Komponent | Status |
|-----------|--------|
| `tv-webhook.service` | ✅ aktywny, systemd, auto-restart |
| `/trading-ai/.env` | ✅ istnieje, zawiera wszystkie klucze |
| `x10-python-trading-starknet` | ✅ zainstalowany w .venv |
| Extended (IMBUS v1) | ✅ test ręczny: BTC Long $50k weszło i zostało anulowane |
| Alpaca (ZL-Volatility v1) | ⏳ nie testowane przez webhook — czekamy na sygnał |
| IMBUS live sygnał | ⏳ czekamy na sygnał z TradingView |

---

### `/trading-ai/.env` — co zawiera (kategorie, nie wartości)

```
TRADING_MODE=live
TV_SECRET=...
EXTENDED_API_KEY / EXTENDED_STARK_PUBLIC / EXTENDED_STARK_PRIVATE / EXTENDED_VAULT / EXTENDED_CLIENT_ID
ALPACA_API_KEY / ALPACA_API_SECRET / ALPACA_PAPER=true / ALPACA_BASE_URL / ALPACA_TRADING_MODE=paper
```

> ⚠️ `.env` jest w `.gitignore` — edytuj przez `nano /trading-ai/.env` na VPS. Nigdy nie commituj.

---

### Aktywna usługa webhooks — poprawne nazwy

```bash
# Sprawdź status
systemctl status tv-webhook --no-pager

# Logi na żywo
tail -f /trading-ai/logs/tv_webhook.log

# Restart po zmianach kodu
systemctl restart tv-webhook

# Health check
curl http://localhost:5005/health
# Oczekiwane: {"status":"ok","trading_mode":"live",...}
```

---

### Na co czekamy — lista testów do wykonania

1. **Sygnał IMBUS → Extended** — poczekać na alert z TradingView (BTC/SUI na 15m). Sprawdzić w logach `[Extended] Sizing:` i że order wyszedł na Extended.
2. **Sygnał ZL-Volatility → Alpaca** — poczekać na alert z TradingView. Sprawdzić że alpaca_executor.py bracket order wchodzi (paper). Jeśli padnie brak kluczy Alpaka — dodać do `.env` i zrestartować usługę.
3. **Pine risk_pct** — w IMBUS Pine suwak `risk_pct` jest wbudowany w JSON alertu (`str.tostring(risk_pct)`). Sprawdzić w logach że `risk_pct` ≠ 1 po zmianie w TV.
4. **RGTI SL na Alpaca** — gdy zombie TP order (pending_cancel z 16.06) zostanie wyczyszczony przez Alpaca Paper Trading, uruchomić: `python scripts/alpaca_executor.py place_sl RGTI buy 437 22.04`

---

## 💻 Co działa LOKALNIE (laptop) — nie przeniesione na VPS

| Skrypt | Jak uruchomić | Kiedy |
|--------|--------------|-------|
| `hermes.py` | `python scripts/hermes.py` | Rano, ręcznie — Daily Alpha Brief |
| `blogwatcher.py` | `python scripts/blogwatcher.py` | Na żądanie — monitoring blogów |
| `edge_journal.py` | `python scripts/edge_journal.py add "..."` | Na żądanie — zapisz obserwację |
| `fetch_positions.py` | `python scripts/fetch_positions.py` | Na żądanie — podgląd pozycji |
| `/raport` w Claude | komenda w chacie | Na żądanie — analiza + rysunki TV |
