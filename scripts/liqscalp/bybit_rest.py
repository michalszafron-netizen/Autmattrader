"""bybit_rest.py — czysty klient Bybit v5 REST (read + trade) dla bota liquidation-scalp.

Podpis HMAC SHA256 (timestamp + api_key + recv_window + (query|body)).
Publiczne endpointy (tickers, instruments) bez podpisu. Prywatne (wallet, position,
order, trading-stop) z podpisem. Zaden modul nie jest auto-uruchamiany — to biblioteka.

UWAGA: metody skladajace zlecenia (create_order, set_trading_stop, set_leverage) wykonuja
REALNE operacje na koncie. Tryb paper jest egzekwowany WYZEJ, w executor.py — tu jest
czysty transport.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import ssl
import time
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
RECV = "5000"


class BybitREST:
    def __init__(self) -> None:
        self.key = os.getenv("BYBIT_API_KEY", "")
        self.secret = os.getenv("BYBIT_API_SECRET", "")
        testnet = os.getenv("BYBIT_TESTNET", "false").lower() == "true"
        self.base = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        self.testnet = testnet
        self._instr_cache: dict[str, dict] = {}

    # ── podpis ────────────────────────────────────────────────────────────────
    def _sign(self, ts: str, payload: str) -> str:
        raw = ts + self.key + RECV + payload
        return hmac.new(self.secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

    def _headers(self, ts: str, payload: str) -> dict:
        return {
            "X-BAPI-API-KEY": self.key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV,
            "X-BAPI-SIGN": self._sign(ts, payload),
        }

    # ── transport ─────────────────────────────────────────────────────────────
    def get_public(self, path: str, params: dict) -> dict:
        with httpx.Client(verify=_SSL, timeout=15) as c:
            return c.get(f"{self.base}{path}", params=params).json()

    def get(self, path: str, params: dict) -> dict:
        ts = str(int(time.time() * 1000))
        query = "&".join(f"{k}={v}" for k, v in params.items())
        headers = self._headers(ts, query)
        with httpx.Client(verify=_SSL, timeout=15) as c:
            return c.get(f"{self.base}{path}?{query}", headers=headers).json()

    def post(self, path: str, body: dict) -> dict:
        ts = str(int(time.time() * 1000))
        raw = json.dumps(body, separators=(",", ":"))
        headers = self._headers(ts, raw)
        headers["Content-Type"] = "application/json"
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.post(f"{self.base}{path}", headers=headers, content=raw)
            if not r.text.strip():
                return {"retCode": -1, "retMsg": f"EMPTY http={r.status_code}"}
            try:
                return r.json()
            except Exception:
                return {"retCode": -1, "retMsg": f"NON-JSON http={r.status_code} {r.text[:200]}"}

    # ── market (public) ───────────────────────────────────────────────────────
    def ticker(self, symbol: str, category: str = "linear") -> dict:
        r = self.get_public("/v5/market/tickers", {"category": category, "symbol": symbol})
        lst = r.get("result", {}).get("list", [])
        return lst[0] if lst else {}

    def best_bid_ask(self, symbol: str, category: str = "linear") -> tuple[float, float]:
        t = self.ticker(symbol, category)
        return float(t.get("bid1Price") or 0), float(t.get("ask1Price") or 0)

    def last_price(self, symbol: str, category: str = "linear") -> float:
        return float(self.ticker(symbol, category).get("lastPrice") or 0)

    def instrument(self, symbol: str, category: str = "linear") -> dict:
        """Zwraca {tick_size, qty_step, min_qty, max_leverage} (cache)."""
        if symbol in self._instr_cache:
            return self._instr_cache[symbol]
        r = self.get_public("/v5/market/instruments-info",
                            {"category": category, "symbol": symbol})
        lst = r.get("result", {}).get("list", [])
        if not lst:
            raise ValueError(f"instrument {symbol} nie znaleziony")
        i = lst[0]
        info = {
            "tick_size": float(i["priceFilter"]["tickSize"]),
            "qty_step": float(i["lotSizeFilter"]["qtyStep"]),
            "min_qty": float(i["lotSizeFilter"]["minOrderQty"]),
            "max_leverage": float(i["leverageFilter"]["maxLeverage"]),
        }
        self._instr_cache[symbol] = info
        return info

    # ── account (private) ─────────────────────────────────────────────────────
    def equity_usd(self) -> float:
        r = self.get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        lst = r.get("result", {}).get("list", [])
        return float(lst[0].get("totalEquity") or 0) if lst else 0.0

    def position(self, symbol: str, category: str = "linear") -> dict:
        r = self.get("/v5/position/list", {"category": category, "symbol": symbol})
        lst = r.get("result", {}).get("list", [])
        return lst[0] if lst else {}

    def positions_all(self, category: str = "linear", settle: str = "USDT") -> list[dict]:
        r = self.get("/v5/position/list", {"category": category, "settleCoin": settle})
        return [p for p in r.get("result", {}).get("list", []) if float(p.get("size") or 0) != 0]

    def closed_pnl_today(self, category: str = "linear", settle: str = "USDT") -> float:
        """Suma realised PnL od polnocy UTC (na kill-switch)."""
        import datetime as _dt
        midnight = int(_dt.datetime.now(_dt.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        r = self.get("/v5/position/closed-pnl",
                    {"category": category, "startTime": midnight, "limit": 100})
        rows = r.get("result", {}).get("list", [])
        return sum(float(x.get("closedPnl") or 0) for x in rows)

    # ── trade (private) — REALNE operacje ─────────────────────────────────────
    def set_leverage(self, symbol: str, lev: int, category: str = "linear") -> dict:
        return self.post("/v5/position/set-leverage", {
            "category": category, "symbol": symbol,
            "buyLeverage": str(lev), "sellLeverage": str(lev)})

    def create_order(self, symbol: str, side: str, qty: str, price: str | None,
                     *, order_type: str = "Limit", tif: str = "PostOnly",
                     reduce_only: bool = False, take_profit: str | None = None,
                     stop_loss: str | None = None, category: str = "linear") -> dict:
        body: dict = {
            "category": category, "symbol": symbol, "side": side,
            "orderType": order_type, "qty": qty, "timeInForce": tif,
            "reduceOnly": reduce_only, "positionIdx": 0,
        }
        if price is not None:
            body["price"] = price
        if take_profit is not None:
            body["takeProfit"] = take_profit
        if stop_loss is not None:
            body["stopLoss"] = stop_loss
            body["tpslMode"] = "Full"
        return self.post("/v5/order/create", body)

    def set_trading_stop(self, symbol: str, *, stop_loss: str | None = None,
                         take_profit: str | None = None, category: str = "linear") -> dict:
        body: dict = {"category": category, "symbol": symbol,
                      "tpslMode": "Full", "positionIdx": 0}
        if stop_loss is not None:
            body["stopLoss"] = stop_loss
        if take_profit is not None:
            body["takeProfit"] = take_profit
        return self.post("/v5/position/trading-stop", body)

    def cancel_all(self, symbol: str, category: str = "linear") -> dict:
        return self.post("/v5/order/cancel-all", {"category": category, "symbol": symbol})
