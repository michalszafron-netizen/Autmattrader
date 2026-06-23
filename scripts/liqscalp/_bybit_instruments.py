"""_bybit_instruments.py — sprawdza dostepne perpy na Bybit (public, bez auth).

Szuka: HYPE, stokenizowanych spolek (NVDA/TSLA/SpaceX...), surowcow (zloto/srebro/ropa),
indeksow (Nasdaq/SPX). Filtruje po slowach kluczowych zeby output byl zwiezly.
"""
from __future__ import annotations

import ssl
import httpx
import truststore

_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
BASE = "https://api.bybit.com"

KEYWORDS = [
    "HYPE",
    # SpaceX / Elon — sprawdzenie tickera
    "SPCX", "SPACE", "SPAC", "STARLINK", "XAI",
    # spolki / equity
    "NVDA", "TSLA", "SPACEX", "SPX", "AAPL", "MSFT", "META", "AMZN", "GOOGL",
    "COIN", "MSTR", "AMD", "NFLX", "PLTR", "STOCK", "X:",
    # surowce
    "XAU", "GOLD", "XAG", "SILVER", "OIL", "WTI", "BRENT", "CRUDE", "NGAS", "COPPER",
    # indeksy / forex
    "NAS", "NDX", "NASDAQ", "US100", "US500", "SPX500", "DJI", "DXY",
]


def fetch(category: str) -> list[dict]:
    out, cursor = [], ""
    with httpx.Client(verify=_SSL, timeout=20) as c:
        while True:
            params = {"category": category, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            r = c.get(f"{BASE}/v5/market/instruments-info", params=params).json()
            res = r.get("result", {})
            out.extend(res.get("list", []))
            cursor = res.get("nextPageCursor") or ""
            if not cursor:
                break
    return out


def main() -> None:
    for category in ("linear",):
        items = fetch(category)
        trading = [i for i in items if i.get("status") == "Trading"]
        print(f"\n=== category={category} | {len(items)} instrumentow ({len(trading)} Trading) ===")

        # 1) HYPE dokladnie
        hype = [i for i in trading if i.get("baseCoin") == "HYPE"]
        print(f"\n[HYPE] {[i['symbol'] for i in hype]}")

        # 2) slowa kluczowe (spolki/surowce/indeksy)
        hits = []
        for i in trading:
            sym = i.get("symbol", "")
            base = i.get("baseCoin", "")
            blob = f"{sym} {base}".upper()
            if any(k in blob for k in KEYWORDS if k != "HYPE"):
                hits.append(i)
        print(f"\n[STOKENIZOWANE / SUROWCE / INDEKSY] {len(hits)} trafien:")
        for i in sorted(hits, key=lambda x: x["symbol"]):
            print(f"  {i['symbol']:20s} base={i.get('baseCoin',''):10s} "
                  f"quote={i.get('quoteCoin',''):6s} settle={i.get('settleCoin','')}")

        # 3) podpowiedz: ile symboli NIE konczy sie na USDT (moga byc USDC/specjalne)
        non_usdt = [i["symbol"] for i in trading if not i["symbol"].endswith("USDT")]
        print(f"\n[non-USDT settle: {len(non_usdt)}] przyklady: {non_usdt[:25]}")


if __name__ == "__main__":
    main()
