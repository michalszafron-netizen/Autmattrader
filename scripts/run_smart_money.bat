@echo off
title Smart Money Tracker
cd /d C:\Users\markowyy\trading-ai
.venv\Scripts\python.exe scripts\smart_money_tracker.py --daemon --interval 3600
pause
