"""TradingView → Hyperliquid webhook receiver.

TradingView fires an alert → POST /tv → validates JSON → logs to alerts.jsonl
→ shells out to hl_executor.py to place the trade.

Security: shared secret in TV_SECRET env var, sent as X-TV-Secret header.
Default mode: PAPER (dry-run). Set TRADING_MODE=live in .env for real orders.

Usage:
    python scripts/tv_webhook.py           # starts on port 5005
    python scripts/tv_webhook.py --port 8080

TV Alert JSON schema — sent automatically by the Pine alert() function:
{
  "symbol":    "RGTI",
  "side":      "buy",          ← buy/sell/close/update_sl (set by Pine alert())
  "price":     12.45,          ← entry price ({{close}} at signal bar)
  "sl_price":  11.23,          ← ATR-based SL calculated by strategy (PREFERRED)
  "tp_price":  14.56,          ← ATR-based TP calculated by strategy (PREFERRED)
  "strategy":  "zl-volatility-v1",
  "risk_pct":  1                ← % of equity to risk per trade
}

IMPORTANT — TV alert condition must be: "alert() function calls only"
Do NOT use "Order fills and alert()" — it fires duplicate events.

Legacy fallback (no sl_price): uses "stop_pct" field (static %, less accurate).
side values: buy/long → open long  |  sell/short → open short
             close → close position |  update_sl → log only (bracket manages SL)
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
VALID_SIDES     = {"long", "short", "buy", "sell", "close", "exit", "update_sl", "partial_close"}

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

def log_alert(data: dict, status: str, note: str = "", exec_detail: dict | None = None) -> None:
    record = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "note": note,
        **data,
    }
    if exec_detail:
        # Never let exec_detail overwrite fields already set by this function
        protected = {"status", "note", "received_at"}
        record.update({k: v for k, v in exec_detail.items() if k not in protected})
    with open(ALERTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    log.info("Alert logged: %s %s %s | status=%s", data.get("symbol"), data.get("side"), data.get("price"), status)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_sl_order_id(symbol: str) -> str | None:
    """Return the most recent sl_order_id logged for this symbol (from entry or update_sl records)."""
    if not ALERTS_FILE.exists():
        return None
    sl_oid = None
    for line in ALERTS_FILE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            if r.get("symbol", "").upper() == symbol.upper() and r.get("sl_order_id"):
                sl_oid = r["sl_order_id"]
        except Exception:
            pass
    return sl_oid

# ── Trade execution ───────────────────────────────────────────────────────────

def symbol_to_ext_market(symbol: str) -> str:
    """Convert TV ticker to Extended market name.
    BTCUSDT → BTC-USD  |  BTCUSD → BTC-USD  |  BTC → BTC-USD
    """
    s = symbol.upper()
    for suffix in ("USDT", "BUSD", "PERP", "USD"):
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break
    return f"{s}-USD"


def detect_venue(symbol: str, data: dict) -> str:
    """Auto-detect venue: alpaca for stocks, hl for crypto/commodities."""
    explicit = data.get("venue", "").lower()
    if explicit in ("alpaca", "hl", "hyperliquid"):
        return explicit
    if explicit == "extended":
        return "extended"
    # US stock symbols: 1-5 uppercase letters, no numbers
    import re
    if re.match(r'^[A-Z]{1,5}$', symbol) and symbol not in ("BTC","ETH","SOL","HYPE","SILVER","GOLD"):
        return "alpaca"
    return "hl"


def _parse_exec_output(stdout: str) -> dict:
    """Try to parse JSON from executor stdout → exec_detail dict."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {}


def execute_trade(data: dict) -> tuple[bool, str, dict]:
    """Returns (success, note, exec_detail). exec_detail has order info on Alpaca fills."""
    symbol   = str(data["symbol"]).upper()
    side_raw = str(data["side"]).lower().strip()
    side     = normalize_side(side_raw) if side_raw != "partial_close" else "partial_close"
    price    = float(data["price"])
    risk_pct = float(data.get("risk_pct", 1))
    stop_pct = float(data.get("stop_pct", 2))
    venue    = detect_venue(symbol, data)

    log.info("Venue: %s | Symbol: %s | Side: %s | Price: %s", venue, symbol, side, price)

    # ── EXTENDED path ─────────────────────────────────────────────────────────
    if venue == "extended":
        market = symbol_to_ext_market(symbol)
        log.info("[Extended] Market: %s | Side: %s", market, side)

        if side == "close":
            cmd = [PY, str(SCRIPTS / "extended_order.py"), "close", market]

        elif side == "partial_close":
            close_pct = int(float(data.get("close_pct", 100)))
            if close_pct >= 100:
                cmd = [PY, str(SCRIPTS / "extended_order.py"), "close", market]
            else:
                cmd = [PY, str(SCRIPTS / "extended_order.py"), "partial-close", market, str(close_pct)]
            log.info("[Extended] Partial close %d%% of %s", close_pct, market)

        elif side == "update_sl":
            log.info("[Extended] Trailing SL update for %s → SL=%.4f (log only)",
                     market, float(data.get("sl_price", 0)))
            return True, f"update_sl logged for {market} (manual SL management on Extended)", {}

        else:
            ext_side   = "long" if side in ("long", "buy") else "short"
            sl_raw     = data.get("sl_price")
            tp1_raw    = data.get("tp1_price")
            sl_price   = float(sl_raw) if sl_raw else (
                price * (1 - stop_pct / 100) if ext_side == "long" else price * (1 + stop_pct / 100)
            )
            sl_dist    = abs(price - sl_price)
            equity     = 100.0
            risk_usd   = equity * risk_pct / 100
            amount_btc = max(round(risk_usd / sl_dist, 6), 0.0001) if sl_dist > 0 else 0.0001
            log.info("[Extended] Sizing: equity=$%.0f risk=$%.2f sl_dist=%.2f qty=%.6f",
                     equity, risk_usd, sl_dist, amount_btc)
            cmd = [PY, str(SCRIPTS / "extended_order.py"), "order",
                   market, ext_side, str(amount_btc), str(round(price, 2)),
                   "--sl", str(round(sl_price, 2))]
            if tp1_raw:
                cmd += ["--tp", str(round(float(tp1_raw), 2))]

        if TRADING_MODE != "live":
            return True, f"PAPER mode — would run: {' '.join(cmd)}", {}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        success = result.returncode == 0
        return success, (result.stdout.strip() or result.stderr.strip()), {}

    # ── ALPACA path ───────────────────────────────────────────────────────────
    if venue == "alpaca":
        if side == "close":
            cmd = [PY, str(SCRIPTS / "alpaca_executor.py"), "close", symbol]

        elif side == "update_sl":
            new_sl = float(data.get("sl_price") or 0)
            if not new_sl:
                return True, "update_sl: no sl_price in payload", {}
            sl_oid = _find_sl_order_id(symbol)
            if not sl_oid:
                log.warning("[Alpaca] update_sl: no sl_order_id tracked for %s", symbol)
                return True, f"update_sl: no tracked SL order for {symbol}, new_sl={new_sl}", {}
            log.info("[Alpaca] Replacing SL order %s → new stop=%.4f", sl_oid[:8], new_sl)
            cmd = [PY, str(SCRIPTS / "alpaca_executor.py"),
                   "update_sl", sl_oid, str(round(new_sl, 4))]

        else:
            alpaca_side = "buy" if side == "long" else "sell"
            try:
                acct_r = subprocess.run([PY, str(SCRIPTS / "alpaca_executor.py"), "equity"],
                                        capture_output=True, text=True, timeout=15)
                equity = float(acct_r.stdout.strip()) if acct_r.returncode == 0 and acct_r.stdout.strip() else 100000.0
            except Exception:
                equity = 100000.0
            log.info("[Alpaca] Equity: $%.2f", equity)

            sl_price_raw = data.get("sl_price")
            tp_price_raw = data.get("tp_price")
            if sl_price_raw:
                stop_price = float(sl_price_raw)
                log.info("[Alpaca] Using Pine ATR SL: %.4f (entry=%.4f)", stop_price, price)
            else:
                stop_price = price * (1 - stop_pct/100) if side == "long" else price * (1 + stop_pct/100)
                log.info("[Alpaca] Using static stop_pct=%.1f%%: SL=%.4f", stop_pct, stop_price)

            stop_dist = abs(price - stop_price)
            risk_usd  = equity * risk_pct / 100
            qty = max(round(risk_usd / stop_dist, 0), 1) if stop_dist > 0 else 1
            qty = int(qty)
            max_qty = max(int(equity * 0.10 / price), 1) if price > 0 else qty
            if qty > max_qty:
                log.warning("[Alpaca] qty=%d capped to %d (10%% equity cap)", qty, max_qty)
                qty = max_qty
            log.info("Alpaca bracket sizing: equity=$%.0f risk_usd=$%.2f stop_dist=%.4f qty=%d",
                     equity, risk_usd, stop_dist, qty)

            if sl_price_raw:
                cmd = [PY, str(SCRIPTS / "alpaca_executor.py"),
                       "bracket", symbol, alpaca_side, str(qty),
                       "--sl", str(round(stop_price, 4))]
                if tp_price_raw:
                    cmd += ["--tp", str(round(float(tp_price_raw), 4))]
            else:
                cmd = [PY, str(SCRIPTS / "alpaca_executor.py"),
                       "order", symbol, alpaca_side, str(qty), str(round(price, 2))]

        if TRADING_MODE != "live":
            return True, f"PAPER mode — would run: {' '.join(cmd)}", {}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        success = result.returncode == 0
        detail  = _parse_exec_output(result.stdout) if success else {}
        # Strip JSON lines from note — they go into exec_detail separately
        clean_lines = [l for l in result.stdout.splitlines() if not l.strip().startswith("{")]
        note = "\n".join(clean_lines).strip() or result.stderr.strip()
        return success, note, detail

    # ── HYPERLIQUID path ──────────────────────────────────────────────────────
    if side == "close":
        cmd = [PY, str(SCRIPTS / "hl_executor.py"), "close", symbol]
        log.info("Closing position: %s", symbol)
    else:
        if side == "long":
            stop_price = round(price * (1 - stop_pct / 100), 4)
        else:
            stop_price = round(price * (1 + stop_pct / 100), 4)

        calc_cmd = [
            PY, str(SCRIPTS / "position_calc.py"),
            "risk", symbol, side,
            "--risk-pct", str(risk_pct),
            "--sl-pct", str(stop_pct),
            "--entry", str(price),
        ]
        log.info("Calculating position: %s", " ".join(calc_cmd))
        calc_result = subprocess.run(calc_cmd, capture_output=True, text=True, timeout=30)

        cmd = None
        for line in reversed(calc_result.stdout.splitlines()):
            if "hl_executor.py" in line and "order" in line:
                parts = line.strip().split()
                idx = next((i for i, p in enumerate(parts) if "hl_executor" in p), None)
                if idx:
                    cmd = [PY] + parts[idx:]
                break

        if not cmd:
            size = max(round(11.0 / price, 2), 0.15)
            log.warning("Could not parse command from position_calc, fallback size: %s", size)
            cmd = [PY, str(SCRIPTS / "hl_executor.py"), "order", symbol, side, str(size), str(price)]
        else:
            log.info("Using position_calc command: %s", " ".join(cmd))

    if TRADING_MODE != "live":
        log.info("[PAPER] Would execute: %s", " ".join(cmd))
        return True, f"PAPER mode — would run: {' '.join(cmd)}", {}

    log.info("Executing: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return True, result.stdout.strip(), {}
    else:
        return False, result.stderr.strip() or result.stdout.strip(), {}

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
        success, note, exec_detail = execute_trade(data)
        status = "executed" if success else "failed"
        log_alert(data, status, note, exec_detail)
        return jsonify({"status": status, "note": note, **exec_detail}), 200 if success else 500
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
    return jsonify(alerts[-50:])


@app.route("/clear", methods=["DELETE"])
def clear_alerts():
    """Clear all alerts or filter by strategy/symbol. Requires secret."""
    if TV_SECRET:
        sent = request.args.get("secret", "") or request.headers.get("X-TV-Secret", "")
        if sent != TV_SECRET:
            return jsonify({"error": "unauthorized"}), 401
    strategy = request.args.get("strategy", "").strip().lower()
    symbol   = request.args.get("symbol",   "").strip().upper()
    if not ALERTS_FILE.exists():
        return jsonify({"ok": True, "cleared": 0})
    try:
        lines = [l for l in ALERTS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if strategy or symbol:
            kept, n = [], 0
            for line in lines:
                try:
                    d = json.loads(line)
                    s_ok = not strategy or d.get("strategy","").lower() == strategy or not d.get("strategy")
                    y_ok = not symbol   or d.get("symbol","").upper() == symbol
                    if s_ok and y_ok:
                        n += 1
                    else:
                        kept.append(line)
                except Exception:
                    kept.append(line)
            cleared = n
        else:
            kept, cleared = [], len(lines)
        ALERTS_FILE.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        log.info("Cleared %d alerts (strategy=%r symbol=%r)", cleared, strategy or "*", symbol or "*")
        return jsonify({"ok": True, "cleared": cleared})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
