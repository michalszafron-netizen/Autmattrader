@echo off
REM Podglad zebranych danych Fazy 0 (likwidacje + ticki ceny).
cd /d C:\Users\krypt\trading-ai
.venv\Scripts\python.exe scripts\liqscalp\collector.py --stats
pause
