@echo off
title Listings Scanner
cd /d C:\Users\krypt\trading-ai
.venv\Scripts\python.exe scripts\listings_scanner.py --daemon --interval 21600
pause
