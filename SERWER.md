# 🖥️ Zarządzanie serwerem VPS — trading-ai

**Hostinger | Ubuntu 24.04 | IP: srv856418 | Folder: `/trading-ai/`**

---

## 🟢 Co działa na VPS (24/7, auto-start)

| Daemon | Skrypt | Co robi | Interval |
|--------|--------|---------|----------|
| `trading-smart-money` | `smart_money_tracker.py` | Śledzi pozycje top 20 traderów HL. Wysyła alert gdy otworzą/zamkną/zwiększą pozycję ≥$50k | co 1h |
| `trading-listings` | `listings_scanner.py` | Skanuje nowe listingi na Binance, Coinbase, Bybit, OKX, Kraken | co 5 min |
| `trading-volume` | `volume_scanner.py` | Anomalie wolumenowe Binance Futures+Spot (próg 3x). Alert na Telegram | co ~1 min |
| `trading-webhook` | `tv_webhook.py` | TradingView alerty → Alpaca/HL executor. POST /tv na porcie 5005 | zawsze online |

### Cron (Eddie / Maggie / Frank — Insider Intelligence)

| Job | Skrypt | Kiedy |
|-----|--------|-------|
| Eddie | `insider_tracker.py form4` | codziennie 06:00 UTC |
| Maggie | `insider_tracker.py institutional` | niedziela 19:00 UTC |
| Frank | `insider_tracker.py fed` | poniedziałek 08:00 UTC |

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
```

### Restart pojedynczego demona
```bash
systemctl restart trading-smart-money
systemctl restart trading-listings
systemctl restart trading-volume
```

### Stop / Start
```bash
systemctl stop trading-smart-money
systemctl start trading-smart-money
```

### Aktualizacja kodu (po git push z laptopa)
```bash
cd /trading-ai
git pull
systemctl restart trading-smart-money trading-listings trading-volume trading-webhook
systemctl status trading-smart-money trading-listings trading-volume trading-webhook --no-pager
```

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

## 💻 Co działa LOKALNIE (laptop) — nie przeniesione na VPS

| Skrypt | Jak uruchomić | Kiedy |
|--------|--------------|-------|
| `hermes.py` | `python scripts/hermes.py` | Rano, ręcznie — Daily Alpha Brief |
| `blogwatcher.py` | `python scripts/blogwatcher.py` | Na żądanie — monitoring blogów |
| `edge_journal.py` | `python scripts/edge_journal.py add "..."` | Na żądanie — zapisz obserwację |
| `fetch_positions.py` | `python scripts/fetch_positions.py` | Na żądanie — podgląd pozycji |
| `/raport` w Claude | komenda w chacie | Na żądanie — analiza + rysunki TV |
