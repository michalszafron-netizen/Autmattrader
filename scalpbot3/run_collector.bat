@echo off
REM ScalpBot3 — kolektor Fazy 0 (Windows). Zostaw okno otwarte.
REM Zbiera Pyth + HL xyz + HL perp + Extended -> data\scalpbot3.db
cd /d "%~dp0"
"C:\Users\krypt\trading-ai\.venv\Scripts\python.exe" collector.py
pause
