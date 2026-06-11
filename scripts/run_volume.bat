@echo off
title Volume Scanner
cd /d C:\Users\krypt\trading-ai
.venv\Scripts\python.exe scripts\volume_scanner.py --daemon --interval 3600 --threshold 3
pause
