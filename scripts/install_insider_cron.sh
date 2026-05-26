#!/usr/bin/env bash
# install_insider_cron.sh — dodaje Eddie/Maggie/Frank do crontab na VPS (Linux)
#
# Uruchom raz na VPS:
#   bash scripts/install_insider_cron.sh
#
# Idempotentny — bezpieczne do ponownego uruchamiania.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
SCRIPT="$ROOT/scripts/insider_tracker.py"
LOGS="$ROOT/logs"

if [[ ! -f "$PY" ]]; then
    echo "ERROR: Python not found at $PY" >&2
    echo "       Run: cd $ROOT && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

mkdir -p "$LOGS"

MARK_START="# >>> insider-tracker (eddie/maggie/frank) >>>"
MARK_END="# <<< insider-tracker (eddie/maggie/frank) <<<"

# Wytnij stary blok (jeśli istnieje) i dopisz świeży
current="$(crontab -l 2>/dev/null || true)"
stripped="$(printf '%s\n' "$current" | awk -v s="$MARK_START" -v e="$MARK_END" '
  $0==s {skip=1; next}
  $0==e {skip=0; next}
  !skip {print}
')"

block="$(cat <<EOF
${MARK_START}
# Eddie  — codziennie 06:00  — SEC Form 4 insider buys
0 6 * * *    $PY $SCRIPT form4         >> $LOGS/eddie.log  2>&1
# Maggie — niedziela 19:00  — 13F institutional filings
0 19 * * 0   $PY $SCRIPT institutional >> $LOGS/maggie.log 2>&1
# Frank  — poniedziałek 08:00 — Fed speech sentiment
0 8 * * 1    $PY $SCRIPT fed           >> $LOGS/frank.log  2>&1
${MARK_END}
EOF
)"

printf '%s\n\n%s\n' "$stripped" "$block" | crontab -

echo "✓ Cron zainstalowany. Harmonogram:"
echo "  Eddie   — codziennie 06:00   (SEC Form 4)"
echo "  Maggie  — niedziela 19:00    (13F funds)"
echo "  Frank   — poniedziałek 08:00 (Fed speeches)"
echo ""
echo "Logi: $LOGS/{eddie,maggie,frank}.log"
echo "Sprawdź: crontab -l"
