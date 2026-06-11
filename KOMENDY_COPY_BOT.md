# 🤖 Copy Bot — ściąga komend (pod rękę)

Własny copy-trading na Hyperliquid, **bez Senpi** (zero opłat za pośrednika).
Tryb **PAPER** = symulacja, ZERO realnych pieniędzy. Egzekucja live = dopiero Sesja 2.

---

## ⚡ NAJWAŻNIEJSZE — uruchomienie (kopiuj-wklej)

### KROK 1 — ustaw tryb paper (ZAWSZE najpierw, w każdym nowym oknie!)

```powershell
$env:HL_TRADING_MODE="paper"; $env:TRADING_MODE="paper"
```

> ⚠️ Bez tego bot się NIE uruchomi (`.env` ma `live` dla hl_executor → bezpiecznik blokuje).
> Ta linijka żyje tylko w TYM oknie. Nowe okno = wklej ponownie.

### KROK 2 — odpal daemon (pętla co 60s)

```powershell
& "C:\Users\krypt\trading-ai\.venv\Scripts\python.exe" "C:\Users\krypt\trading-ai\scripts\copy_bot.py" --daemon
```

To okno = bot. Zostaw otwarte. **NIE klikaj w nie** (QuickEdit zamrozi — patrz niżej).

---

## 📋 POZOSTAŁE KOMENDY

Każdą poprzedź `$env:HL_TRADING_MODE="paper"; $env:TRADING_MODE="paper"` jeśli nowe okno.

### Status — podgląd 3 portfeli (co kto trzyma)

```powershell
& "C:\Users\krypt\trading-ai\.venv\Scripts\python.exe" "C:\Users\krypt\trading-ai\scripts\copy_bot.py" --status
```

### Reset — wyczyść wszystkie wirtualne portfele (start od zera)

```powershell
& "C:\Users\krypt\trading-ai\.venv\Scripts\python.exe" "C:\Users\krypt\trading-ai\scripts\copy_bot.py" --reset
```

### Jednorazowy reconcile (bez pętli — 1 sprawdzenie)

```powershell
& "C:\Users\krypt\trading-ai\.venv\Scripts\python.exe" "C:\Users\krypt\trading-ai\scripts\copy_bot.py"
```

---

## 🔄 RESTART DAEMONA (po KAŻDEJ zmianie kodu bota!)

Daemon trzyma starą wersję kodu w pamięci. Gdy kod się zmieni, MUSISZ go ubić i odpalić nowy:

1. W oknie daemona: **Ctrl+C** (jeśli zamrożony QuickEdit → kliknij okno, Enter, potem Ctrl+C)
2. `--reset` (komenda wyżej) — wyczyść bazę
3. `--daemon` (KROK 2 wyżej) — odpal nową wersję

---

## ⚠️ PUŁAPKI (zapamiętaj)

| Problem | Rozwiązanie |
|---|---|
| Okno zamrożone, nic się nie dzieje | QuickEdit — kliknij okno, naciśnij **Enter**. Na przyszłość: nie klikaj w okno daemona |
| `LIVE MODE wykryty` — bot nie startuje | Zapomniałeś `$env:...="paper"` — wklej i odpal ponownie |
| Zmieniłem config, ale bot widzi stary | Restart daemona (sekcja wyżej) |
| Bot kasuje pozycje bez sensu | Stary daemon z poprzednią wersją kodu wciąż chodzi — ubij wszystkie, odpal jeden |
| Zamknąłem okno = bot padł | Normalne. Nowe okno → paper → daemon |

---

## 👥 TRADERZY (config/copy_trader.json)

Bot śledzi kilku naraz, każdy osobny wirtualny portfel. Aktualnie:

| Adres | Profil |
|---|---|
| `0xe21b` | Snajper HYPE (ELITE, +$408k, ale ZNIKA na dni) |
| `0xba93` | Konserwatywny (2.5 roku, DD-10%, WR93%, ~5 tradów/dzień) |
| `0x4b1c` | Maszyna HFT ($2M, DD-4.5%, 26 pozycji, zawsze aktywny) |

**Dodać/wyłączyć tradera:** edytuj `config/copy_trader.json` → sekcja `traders` →
ustaw `"active": true/false` (lub dopisz nowy wpis z `address` + `label`).
Bez dotykania kodu. Po zmianie configu — **restart daemona**.

**Kapitał / mnożnik:** w tym samym pliku `my_capital_usd` (teraz $200) i `multiplier` (teraz 1.0).

---

## 📊 GDZIE LĄDUJĄ DANE

- Wirtualne portfele + akcje → SQLite `data/trading.db` (tabele `copybot_positions`, `copybot_actions`)
- Log → `logs/copy_bot.log`
- Alerty → Telegram (przy każdej realnej akcji, z etykietą kto)

---

## 🚦 TRYB LIVE (jeszcze NIEgotowy)

Egzekucja na realne pieniądze = **Sesja 2** (nie zaimplementowana). Bot celowo blokuje
uruchomienie w live. Najpierw paper potwierdza logikę, potem dorabiamy realne zlecenia
(maker-limity, kill switch -3%, obowiązkowy SL) i ewentualnie systemd na VPS.
