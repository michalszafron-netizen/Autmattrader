@echo off
title Trading AI Daemons
start /min "Volume Scanner"   cmd /k "cd /d C:\Users\markowyy\trading-ai && .venv\Scripts\python.exe scripts\volume_scanner.py --daemon --interval 3600 --threshold 3"
start /min "Smart Money"      cmd /k "cd /d C:\Users\markowyy\trading-ai && .venv\Scripts\python.exe scripts\smart_money_tracker.py --daemon --interval 3600"
start /min "Listings Scanner" cmd /k "cd /d C:\Users\markowyy\trading-ai && .venv\Scripts\python.exe scripts\listings_scanner.py --daemon --interval 21600"
