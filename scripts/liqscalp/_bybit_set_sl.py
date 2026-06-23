"""_bybit_set_sl.py — przesuniecie stop-loss na istniejacej pozycji (Bybit v5).

Modyfikuje TYLKO stop-loss pozycji (set-trading-stop). Nie sklada nowych zlecen,
nie zmienia rozmiaru. Read-modify dla zarzadzania ryzykiem na zyczenie uzytkownika.

Uzycie:
    python _bybit_set_sl.py SOLUSDT 62
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import ssl
import sys
import time
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

API_KEY = os.getenv("BYBIT_API_KEY", "")
API_SECRET = os.getenv("BYBIT_API_SECRET", "")
TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
BASE = "https://api-testnet.bybit.com" if TESTNET else "https://api.bybit.com"
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
RECV = "5000"


def _headers(body: str) -> dict:
    ts = str(int(time.time() * 1000))
    payload = ts + API_KEY + RECV + body
    sign = hmac.new(API_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {
        "X-BAPI-API-KEY": API_KEY,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": RECV,
        "X-BAPI-SIGN": sign,
        "Content-Type": "application/json",
    }


def _signed_get(path: str, params: dict) -> dict:
    ts = str(int(time.time() * 1000))
    query = "&".join(f"{k}={v}" for k, v in params.items())
    payload = ts + API_KEY + RECV + query
    sign = hmac.new(API_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": API_KEY, "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": RECV, "X-BAPI-SIGN": sign,
    }
    url = f"{BASE}{path}?{query}"
    with httpx.Client(verify=_SSL, timeout=15) as c:
        return c.get(url, headers=headers).json()


def set_sl(symbol: str, sl: str) -> dict:
    body_obj = {
        "category": "linear",
        "symbol": symbol,
        "stopLoss": sl,
        "tpslMode": "Full",
        "positionIdx": 0,
    }
    body = json.dumps(body_obj, separators=(",", ":"))
    with httpx.Client(verify=_SSL, timeout=15) as c:
        r = c.post(f"{BASE}/v5/position/trading-stop", headers=_headers(body), content=body)
        if not r.text.strip():
            return {"retCode": -1, "retMsg": f"EMPTY RESPONSE http={r.status_code}"}
        try:
            return r.json()
        except Exception:
            return {"retCode": -1, "retMsg": f"NON-JSON http={r.status_code} body={r.text[:300]}"}


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "SOLUSDT"
    sl = sys.argv[2] if len(sys.argv) > 2 else None
    if not sl:
        print("Usage: python _bybit_set_sl.py SYMBOL SL_PRICE")
        return

    print(f"Bybit {'TESTNET' if TESTNET else 'MAINNET'} | {symbol} -> set SL ${sl}")
    res = set_sl(symbol, sl)
    print("RESPONSE:", json.dumps(res, indent=2))

    if res.get("retCode") == 0:
        print("\n[OK] Stop-loss zaktualizowany. Weryfikacja pozycji:")
        pos = _signed_get("/v5/position/list", {"category": "linear", "symbol": symbol})
        for p in pos.get("result", {}).get("list", []):
            print(f"  {p['symbol']} {p['side']} size={p['size']} avg={p['avgPrice']} "
                  f"mark={p['markPrice']} SL={p['stopLoss']} TP={p['takeProfit']} "
                  f"liq={p['liqPrice']} uPnL={p['unrealisedPnl']}")
    else:
        print(f"\n[BLAD] retCode={res.get('retCode')} retMsg={res.get('retMsg')}")


if __name__ == "__main__":
    main()
