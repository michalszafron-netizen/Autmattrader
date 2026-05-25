# 🖥️ Zarządzanie serwerem VPS — trading-ai

**Hostinger | Ubuntu 24.04 | IP: srv856418 | Folder: `/trading-ai/`**

---

## 🟢 Co działa na VPS (24/7, auto-start)

| Daemon | Skrypt | Co robi | Interval |
|--------|--------|---------|----------|
| `trading-smart-money` | `smart_money_tracker.py` | Śledzi pozycje top 20 traderów HL. Wysyła alert gdy otworzą/zamkną/zwiększą pozycję ≥$50k | co 1h |
| `trading-listings` | `listings_scanner.py` | Skanuje nowe listingi na Binance, Coinbase, Bybit, OKX, Kraken | co 5 min |
| `trading-volume` | `volume_scanner.py` | Anomalie wolumenowe Binance Futures+Spot (próg 3x). Alert na Telegram | co ~1 min |

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
systemctl restart trading-smart-money trading-listings trading-volume
systemctl status trading-smart-money trading-listings trading-volume --no-pager
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
