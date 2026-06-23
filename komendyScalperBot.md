Podsumowanie na jutro

Komenda którą odpalasz i zostawiasz na noc

Jeden terminal, nic więcej:

.venv/Scripts/python.exe scripts/hl_scalp.py live


Rano sprawdzasz wynik

Drugi terminal, nowe okno:

.venv/Scripts/python.exe scripts/show_scalp_stats.py


# Podgląd statystyk (działa, bez błędów escapingu)
.venv/Scripts/python.exe scripts/show_scalp_stats.py

# Dzisiejsze trade'y tylko
.venv/Scripts/python.exe scripts/show_scalp_stats.py --today

# Wszystkie trade'y ze szczegółami
.venv/Scripts/python.exe scripts/show_scalp_stats.py --all

# Szybki status
.venv/Scripts/python.exe scripts/hl_scalp.py status


Session ID: 20260618_155912_a2316adf
Title: Scalping Bot Development Ideas and Plans
Created: 2026-06-18 15:59
Last Activity: 2026-06-19 01:32
Cumulative API tokens (re-sent each call): 32,201,540