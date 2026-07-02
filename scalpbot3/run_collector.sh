#!/usr/bin/env bash
# ScalpBot3 — kolektor Fazy 0 (Linux VPS).
# Uzycie:
#   ./run_collector.sh              # na pierwszym planie
#   nohup ./run_collector.sh >collector.log 2>&1 &   # w tle (prosto)
# Lepiej: uzyj systemd (patrz scalpbot3.service ponizej / README).
cd "$(dirname "$0")"
# dostosuj sciezke do venv na VPS jesli inna:
PY="${SCALPBOT3_PY:-python3}"
exec "$PY" collector.py
