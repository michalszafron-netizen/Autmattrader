"""_ws_probe.py — jednorazowy test Bybit public WS (likwidacje + cena).

Laczy sie, subskrybuje kilka topikow, drukuje ack + surowe wiadomosci przez ~25s.
Cel: potwierdzic poprawne nazwy topikow i ksztalt danych przed budowa kolektora.
Mozna usunac po walidacji.
"""
from __future__ import annotations

import asyncio
import json
import ssl
import time

import truststore
import websockets

URL = "wss://stream.bybit.com/v5/public/linear"
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

TOPICS = [
    "allLiquidation.BTCUSDT",
    "allLiquidation.ETHUSDT",
    "allLiquidation.SOLUSDT",
    "publicTrade.SOLUSDT",      # ksztalt ceny (trade prints)
    "tickers.SOLUSDT",          # lzejsza opcja ceny
]

RUN_SECONDS = 25


async def main() -> None:
    seen = {"ack": 0, "liq": 0, "trade": 0, "ticker": 0}
    printed_shape = {"liq": False, "trade": False, "ticker": False}

    async with websockets.connect(URL, ssl=_SSL, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({"op": "subscribe", "args": TOPICS}))
        print(f"[probe] subscribed to {len(TOPICS)} topics, listening {RUN_SECONDS}s...\n")

        t_end = time.time() + RUN_SECONDS
        while time.time() < t_end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=t_end - time.time())
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)

            # Subscription ack
            if msg.get("op") == "subscribe":
                seen["ack"] += 1
                print(f"[ACK] success={msg.get('success')} ret={msg.get('ret_msg')} "
                      f"conn={msg.get('conn_id','')[:8]}")
                continue

            topic = msg.get("topic", "")
            if topic.startswith("allLiquidation") or topic.startswith("liquidation"):
                seen["liq"] += 1
                if not printed_shape["liq"]:
                    print(f"\n[LIQ SHAPE] topic={topic}\n{json.dumps(msg, indent=2)[:700]}\n")
                    printed_shape["liq"] = True
                else:
                    print(f"[LIQ] {topic} -> {json.dumps(msg.get('data'))[:160]}")
            elif topic.startswith("publicTrade"):
                seen["trade"] += 1
                if not printed_shape["trade"]:
                    print(f"\n[TRADE SHAPE] {json.dumps(msg, indent=2)[:500]}\n")
                    printed_shape["trade"] = True
            elif topic.startswith("tickers"):
                seen["ticker"] += 1
                if not printed_shape["ticker"]:
                    d = msg.get("data", {})
                    print(f"\n[TICKER SHAPE] keys={list(d.keys())[:15]} lastPrice={d.get('lastPrice')}\n")
                    printed_shape["ticker"] = True

    print(f"\n[probe done] acks={seen['ack']} liq_events={seen['liq']} "
          f"trade_msgs={seen['trade']} ticker_msgs={seen['ticker']}")


if __name__ == "__main__":
    asyncio.run(main())
