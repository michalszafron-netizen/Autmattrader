"""TradingView → Hyperliquid webhook receiver.

TradingView fires an alert → POST /tv → validates JSON → logs to alerts.jsonl
→ shells out to hl_executor.py to place the trade.

Security: shared secret in TV_SECRET env var, sent as X-TV-Secret header.
Default mode: PAPER (dry-run). Set TRADING_MODE=live in .env for real orders.

Usage:
    python scripts/tv_webhook.py           # starts on port 5005
    python scripts/tv_webhook.py --port 8080

TV Alert JSON schema (paste into TradingView alert message):
{
  "symbol": "SILVER",
  "side": "{{strategy.order.action}}",
  "price": "{{close}}",
  "time": "{{timenow}}",
  "strategy": "zl-volatility-v1",
  "risk_pct": 1,
  "stop_pct": 2,
  "tp_r_multiple": 2.5,
  "leverage": 5
}

side values: "buy"/"long" for long, "sell"/"short" for short, "close" to close.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv(Path(__file__).parent.parent / ".env")

TV_SECRET    = os.getenv("TV_SECRET", "")
TRADING_MODE = os.getenv("TRADING_MODE", "paper")
PY           = sys.executable
SCRIPTS      = Path(__file__).parent
ALERTS_FILE  = Path(__file__).parent.parent / "alerts.jsonl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("tv_webhook")

app = Flask(__name__)

# ── Schema validation ─────────────────────────────────────────────────────────

REQUIRED_FIELDS = {"symbol", "side", "price"}
VALID_SIDES     = {"long", "short", "buy", "sell", "close", "exit"}

def normalize_side(side: str) -> str:
    s = side.lower().strip()
    if s in ("buy", "long"):
        return "long"
    if s in ("sell", "short"):
        return "short"
    if s in ("close", "exit"):
        return "close"
    return s

def validate_payload(data: dict) -> tuple[bool, str]:
    for field in REQUIRED_FIELDS:
        if field not in data:
            return False, f"Missing required field: {field}"
    side = normalize_side(str(data.get("side", "")))
    if side not in VALID_SIDES:
        return False, f"Invalid side: {data['side']}"
    try:
        float(data["price"])
    except (ValueError, TypeError):
        return False, "price must be numeric"
    return True, "ok"

# ── Logging ───────────────────────────────────────────────────────────────────

def log_alert(data: dict, status: str, note: str = "") -> None:
    record = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "note": note,
        **data,
    }
    with open(ALERTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log.info("Alert logged: %s %s %s | status=%s", data.get("symbol"), data.get("side"), data.get("price"), status)

# ── Trade execution ───────────────────────────────────────────────────────────

def detect_venue(symbol: str, data: dict) -> str:
    """Auto-detect venue: alpaca for stocks, hl for crypto/commodities."""
    explicit = data.get("venue", "").lower()
    if explicit in ("alpaca", "hl", "hyperliquid"):
        return explicit
    # US stock symbols: 1-5 uppercase letters, no numbers
    import re
    if re.match(r'^[A-Z]{1,5}$', symbol) and symbol not in ("BTC","ETH","SOL","HYPE","SILVER","GOLD"):
        return "alpaca"
    return "hl"


def execute_trade(data: dict) -> tuple[bool, str]:
    symbol   = str(data["symbol"]).upper()
    side     = normalize_side(str(data["side"]))
    price    = float(data["price"])
    risk_pct = float(data.get("risk_pct", 1))
    stop_pct = float(data.get("stop_pct", 2))
    venue    = detect_venue(symbol, data)

    log.info("Venue: %s | Symbol: %s | Side: %s | Price: %s", venue, symbol, side, price)

    # ── ALPACA path ───────────────────────────────────────────────────────────
    if venue == "alpaca":
        if side == "close":
            cmd = [PY, str(SCRIPTS / "alpaca_executor.py"), "close", symbol]
        else:
            alpaca_side = "buy" if side == "long" else "sell"
            # Risk sizing: account equity × risk_pct% / stop_distance
            try:
                import subprocess as sp2
                acct_r = sp2.run([PY, str(SCRIPTS / "alpaca_executor.py"), "positions"],
                                  capture_output=True, text=True, timeout=15)
                equity = 100000.0  # fallback
                for line in acct_r.stdout.splitlines():
                    if "Equity:" in line:
                        import re
                        m = re.search(r'Equity:\s*\$([0-9,.]+)', line)
                        if m:
                            equity = float(m.group(1).replace(",",""))
                            break
            except Exception:
                equity = 100000.0

            stop_price = price * (1 - stop_pct/100) if side == "long" else price * (1 + stop_pct/100)
            risk_usd = equity * risk_pct / 100
            stop_dist = abs(price - stop_price)
            qty = max(round(risk_usd / stop_dist, 0), 1) if stop_dist > 0 else 1
            qty = int(qty)
            log.info("Alpaca sizing: equity=$%.0f risk=$%.2f qty=%d", equity, risk_usd, qty)
            cmd = [PY, str(SCRIPTS / "alpaca_executor.py"), "order", symbol, alpaca_side, str(qty), str(round(price, 2))]

        if TRADING_MODE != "live":
            return True, f"PAPER mode — would run: {' '.join(cmd)}"
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        success = result.returncode == 0
        return success, (result.stdout.strip() or result.stderr.strip())

    # ── HYPERLIQUID path ──────────────────────────────────────────────────────
    if side == "close":
        # Close existing position
        cmd = [PY, str(SCRIPTS / "hl_executor.py"), "close", symbol]
        log.info("Closing position: %s", symbol)
    else:
        # Calculate stop price
        if side == "long":
            stop_price = round(price * (1 - stop_pct / 100), 4)
        else:
            stop_price = round(price * (1 + stop_pct / 100), 4)

        # Use position_calc to get size + ready command
        calc_cmd = [
            PY, str(SCRIPTS / "position_calc.py"),
            "risk", symbol, side,
            "--risk-pct", str(risk_pct),
            "--sl-pct", str(stop_pct),
            "--entry", str(price),
        ]
        log.info("Calculating position: %s", " ".join(calc_cmd))
        calc_result = subprocess.run(calc_cmd, capture_output=True, text=True, timeout=30)

        # Parse ready-made hl_executor command from last line of output
        cmd = None
        for line in reversed(calc_result.stdout.splitlines()):
            if "hl_executor.py" in line and "order" in line:
                parts = line.strip().split()
                # Replace 'python' with our venv python
                idx = next((i for i, p in enumerate(parts) if "hl_executor" in p), None)
                if idx:
                    cmd = [PY] + parts[idx:]
                break

        if not cmd:
            # Fallback: minimum viable size
            size = max(round(11.0 / price, 2), 0.15)
            log.warning("Could not parse command from position_calc, fallback size: %s", size)
            cmd = [PY, str(SCRIPTS / "hl_executor.py"), "order", symbol, side, str(size), str(price)]
        else:
            log.info("Using position_calc command: %s", " ".join(cmd))

    if TRADING_MODE != "live":
        log.info("[PAPER] Would execute: %s", " ".join(cmd))
        return True, f"PAPER mode — would run: {' '.join(cmd)}"

    log.info("Executing: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return True, result.stdout.strip()
    else:
        return False, result.stderr.strip() or result.stdout.strip()

# ── Endpoint ──────────────────────────────────────────────────────────────────

@app.route("/tv", methods=["POST"])
def receive_alert():
    # 1. Secret check — header OR query param (TV nie obsługuje custom headers)
    if TV_SECRET:
        sent_secret = (
            request.headers.get("X-TV-Secret", "") or
            request.args.get("secret", "") or
            (request.get_json(force=True, silent=True) or {}).get("secret", "")
        )
        if sent_secret != TV_SECRET:
            log.warning("Rejected request: wrong secret from %s", request.remote_addr)
            return jsonify({"error": "unauthorized"}), 401

    # 2. Parse JSON
    try:
        data = request.get_json(force=True)
        if not data:
            raise ValueError("empty body")
    except Exception as e:
        log.warning("Bad JSON: %s", e)
        return jsonify({"error": "invalid json"}), 400

    # 3. Validate schema
    ok, msg = validate_payload(data)
    if not ok:
        log_alert(data, "rejected", msg)
        return jsonify({"error": msg}), 422

    # 4. Log received
    log_alert(data, "received")

    # 5. Execute trade
    try:
        success, note = execute_trade(data)
        status = "executed" if success else "failed"
        log_alert(data, status, note)
        return jsonify({"status": status, "note": note}), 200 if success else 500
    except Exception as e:
        log.exception("Execution error")
        log_alert(data, "error", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "trading_mode": TRADING_MODE,
        "alerts_logged": sum(1 for _ in open(ALERTS_FILE, encoding="utf-8")) if ALERTS_FILE.exists() else 0,
    })


@app.route("/alerts", methods=["GET"])
def show_alerts():
    if not ALERTS_FILE.exists():
        return jsonify([])
    alerts = []
    with open(ALERTS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                alerts.append(json.loads(line))
            except Exception:
                pass
    return jsonify(alerts[-20:])  # ostatnie 20


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5005)
    args = p.parse_args()

    mode_color = "\033[91mLIVE\033[0m" if TRADING_MODE == "live" else "\033[93mPAPER\033[0m"
    print(f"\n  TV Webhook Server")
    print(f"  Port:    {args.port}")
    print(f"  Mode:    {mode_color}")
    print(f"  Secret:  {'SET' if TV_SECRET else 'NOT SET (open)'}")
    print(f"  Alerts:  {ALERTS_FILE}")
    print(f"\n  Endpoints:")
    print(f"    POST http://localhost:{args.port}/tv       <- TradingView alert")
    print(f"    GET  http://localhost:{args.port}/health   <- status")
    print(f"    GET  http://localhost:{args.port}/alerts   <- last 20 alerts\n")

    app.run(host="0.0.0.0", port=args.port, debug=False)
