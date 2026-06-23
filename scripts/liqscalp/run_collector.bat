@echo off
REM Faza 0 — kolektor likwidacji + ceny (Bybit WS). Zostaw to okno otwarte.
REM Zatrzymanie: Ctrl+C w tym oknie. Podglad: run_stats.bat
cd /d C:\Users\krypt\trading-ai
title liqscalp-collector
.venv\Scripts\python.exe scripts\liqscalp\collector.py
pause
