"""collector.py — Faza 0 kolektor danych dla bota liquidation-scalp.

Laczy sie z Bybit public WS (linear), subskrybuje:
  allLiquidation.{symbol}  — kazde zdarzenie likwidacji
  tickers.{symbol}         — lastPrice (throttle do ~1/s/symbol)

Zapisuje do data/liqscalp.db (przez store.Store). Reconnect przy zerwaniu,
app-level ping co 20s, heartbeat co 30s, flush bufora co 2s.

Uzycie:
    python collector.py                  # domyslny koszyk, zbiera w nieskonczonosc
    python collector.py --symbols BTCUSDT,ETHUSDT,SOLUSDT
    python collector.py --stats          # podglad bazy i wyjscie
"""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import truststore
import websockets

sys.path.insert(0, str(Path(__file__).parent))
from store import Store, _fmt_span  # noqa: E402

URL = "wss://stream.bybit.com/v5/public/linear"
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

# Koszyk startowy. Dobor wg wolumenu 24h (sprawdzone na zywo — patrz README).
DEFAULT_SYMBOLS = [
    # Crypto: majors + hot mid-capy (najbogatsze w likwidacje)
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT",
    "DOGEUSDT", "1000PEPEUSDT", "WIFUSDT",
    # Metale (realny wolumen: zloto ~$55M/d, srebro ~$32M/d)
    "XAUTUSDT", "XAGUSDT",
    # Stokenizowane equity / indeks
    "SPCXUSDT",            # SpaceX (Elon) — swiezy debiut, ~$43M/d, realnie plynny
    "NVDAUSDT", "SPXUSDT",  # DISCOVERY — cienkie (~$1.7M / $6M d.), sprawdzamy czy zyja
]

PRICE_THROTTLE_MS = 1000   # max 1 tick ceny / symbol / sekunde
FLUSH_EVERY_S = 2.0
HEARTBEAT_EVERY_S = 30.0
PING_EVERY_S = 20.0

_running = True


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _handle_sig(signum, frame) -> None:
    global _running
    _running = False


signal.signal(signal.SIGINT, _handle_sig)
signal.signal(signal.SIGTERM, _handle_sig)


async def collect(symbols: list[str]) -> None:
    store = Store()
    store.set_meta("symbols", ",".join(symbols))
    store.set_meta("started_utc", datetime.now(timezone.utc).isoformat())

    topics = [f"allLiquidation.{s}" for s in symbols] + [f"tickers.{s}" for s in symbols]

    liq_buf: list[tuple] = []
    price_buf: list[tuple] = []
    last_price_ts: dict[str, int] = {}
    counts = {"liq": 0, "price": 0, "msgs": 0}
    last_flush = time.monotonic()
    last_hb = time.monotonic()

    print(f"[{_utc()}] collector start | {len(symbols)} symboli: {', '.join(symbols)}")
    print(f"[{_utc()}] DB: {store.path}")

    while _running:
        try:
            async with websockets.connect(URL, ssl=_SSL, ping_interval=20,
                                          ping_timeout=20, max_queue=2048) as ws:
                await ws.send(json.dumps({"op": "subscribe", "args": topics}))
                last_ping = time.monotonic()
                print(f"[{_utc()}] WS connected, subscribed {len(topics)} topics")

                while _running:
                    # app-level ping
                    if time.monotonic() - last_ping >= PING_EVERY_S:
                        await ws.send(json.dumps({"op": "ping"}))
                        last_ping = time.monotonic()

                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        raw = None

                    if raw is not None:
                        counts["msgs"] += 1
                        _process(raw, liq_buf, price_buf, last_price_ts, counts)

                    # flush bufora
                    now = time.monotonic()
                    if now - last_flush >= FLUSH_EVERY_S:
                        if liq_buf:
                            store.insert_liqs(liq_buf); liq_buf.clear()
                        if price_buf:
                            store.insert_prices(price_buf); price_buf.clear()
                        store.commit()
                        last_flush = now

                    # heartbeat
                    if now - last_hb >= HEARTBEAT_EVERY_S:
                        print(f"[{_utc()}] hb | msgs={counts['msgs']} "
                              f"liq={counts['liq']} price={counts['price']}", flush=True)
                        last_hb = now

        except Exception as e:
            # flush co mamy, potem reconnect
            try:
                store.insert_liqs(liq_buf); liq_buf.clear()
                store.insert_prices(price_buf); price_buf.clear()
                store.commit()
            except Exception:
                pass
            if _running:
                print(f"[{_utc()}] WS error: {type(e).__name__}: {e} -> reconnect za 3s", flush=True)
                await asyncio.sleep(3)

    # zamkniecie
    store.insert_liqs(liq_buf)
    store.insert_prices(price_buf)
    store.commit()
    print(f"[{_utc()}] stop | liq={counts['liq']} price={counts['price']}")
    store.close()


def _process(raw: str, liq_buf: list, price_buf: list,
             last_price_ts: dict, counts: dict) -> None:
    try:
        msg = json.loads(raw)
    except Exception:
        return
    topic = msg.get("topic", "")
    if not topic:
        return  # ack / pong / op response

    recv = _now_ms()

    if topic.startswith("allLiquidation."):
        data = msg.get("data", [])
        if isinstance(data, dict):
            data = [data]
        for d in data:
            try:
                price = float(d.get("p", 0) or 0)
                size = float(d.get("v", 0) or 0)
                liq_buf.append((
                    int(d.get("T", recv)), recv, d.get("s", ""),
                    d.get("S", ""), size, price, round(size * price, 2),
                    json.dumps(d, separators=(",", ":")),
                ))
                counts["liq"] += 1
            except Exception:
                continue

    elif topic.startswith("tickers."):
        d = msg.get("data", {})
        sym = d.get("symbol", "")
        last = d.get("lastPrice")
        if sym and last is not None:
            if recv - last_price_ts.get(sym, 0) >= PRICE_THROTTLE_MS:
                try:
                    price_buf.append((recv, sym, float(last)))
                    last_price_ts[sym] = recv
                    counts["price"] += 1
                except Exception:
                    pass


def cmd_stats() -> None:
    s = Store()
    summ = s.summary()
    print(f"DB: {s.path}")
    print(f"Likwidacje: {summ['liq_total']}  |  ticki ceny: {summ['price_total']}")
    print(f"Zakres zbierania: {_fmt_span(summ['liq_span_ms'])}")
    print("Per symbol (count likwidacji, suma notional USD):")
    for sym, cnt, notional in summ["per_symbol"]:
        print(f"  {sym:14s} {cnt:6d}  ${notional or 0:,.0f}")
    s.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Bybit liquidation+price collector (Faza 0)")
    ap.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--stats", action="store_true", help="podglad bazy i wyjscie")
    args = ap.parse_args()

    if args.stats:
        cmd_stats()
        return

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    try:
        asyncio.run(collect(symbols))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
