@echo off
title Kozaki Monitor
cd /d C:\Users\markowyy\trading-ai
.venv\Scripts\python.exe scripts\kozaki_monitor.py --daemon --interval 3600
pause
