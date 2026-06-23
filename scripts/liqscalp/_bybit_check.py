"""_bybit_check.py — jednorazowy podglad konta Bybit (READ-ONLY).

Odpytuje Bybit v5 REST: pozycje perps (linear), wallet, typ konta, spot.
Nie sklada zadnych zlecen. Uzywany do weryfikacji dostepnych rynkow przed
budowa bota liquidation-scalp. Mozna usunac po sprawdzeniu.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import ssl
import time
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parents[2] / ".env")

API_KEY = os.getenv("BYBIT_API_KEY", "")
API_SECRET = os.getenv("BYBIT_API_SECRET", "")
TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
BASE = "https://api-testnet.bybit.com" if TESTNET else "https://api.bybit.com"

_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
RECV = "5000"


def _signed_get(path: str, params: dict) -> dict:
    ts = str(int(time.time() * 1000))
    query = "&".join(f"{k}={v}" for k, v in params.items())
    payload = ts + API_KEY + RECV + query
    sign = hmac.new(API_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": API_KEY,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": RECV,
        "X-BAPI-SIGN": sign,
    }
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    with httpx.Client(verify=_SSL, timeout=15) as c:
        r = c.get(url, headers=headers)
        return r.json()


def section(title: str) -> None:
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def main() -> None:
    print(f"Bybit {'TESTNET' if TESTNET else 'MAINNET'} | key ...{API_KEY[-4:]}")

    section("ACCOUNT INFO (margin mode / UTA)")
    print(json.dumps(_signed_get("/v5/account/info", {}), indent=2)[:1500])

    section("LINEAR PERPS POSITIONS (settleCoin=USDT)")
    pos = _signed_get("/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
    print(json.dumps(pos, indent=2)[:3000])

    section("WALLET BALANCE (UNIFIED)")
    wb = _signed_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    # skroc do coinow z saldem
    try:
        for acc in wb.get("result", {}).get("list", []):
            print(f"  totalEquity={acc.get('totalEquity')} totalAvailable={acc.get('totalAvailableBalance')}")
            for coin in acc.get("coin", []):
                wb_ = float(coin.get("walletBalance") or 0)
                if wb_ != 0:
                    print(f"    {coin.get('coin')}: bal={coin.get('walletBalance')} "
                          f"usdValue={coin.get('usdValue')} unrealisedPnl={coin.get('unrealisedPnl')}")
    except Exception as e:
        print("wallet parse err:", e, json.dumps(wb)[:800])

    section("SPOT BORROW / MARGIN STATE")
    print(json.dumps(_signed_get("/v5/spot-margin-trade/state", {}), indent=2)[:1200])

    section("API KEY PERMISSIONS")
    print(json.dumps(_signed_get("/v5/user/query-api", {}), indent=2)[:1500])


if __name__ == "__main__":
    main()
