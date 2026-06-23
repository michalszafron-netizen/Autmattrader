"""_bybit_liquidity.py — obrot 24h + OI dla kandydatow do koszyka (public)."""
from __future__ import annotations

import ssl
import httpx
import truststore

_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
BASE = "https://api.bybit.com"

CANDIDATES = [
    # obecny koszyk (porownanie)
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "1000PEPEUSDT", "WIFUSDT",
    # nowi kandydaci
    "HYPEUSDT",
    "NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "MSTRUSDT", "COINUSDT", "METAUSDT",
    "XAUUSDT", "XAUTUSDT", "XAGUSDT", "SPXUSDT",
    "SPCXUSDT", "SPACEUSDT",
]


def main() -> None:
    with httpx.Client(verify=_SSL, timeout=20) as c:
        r = c.get(f"{BASE}/v5/market/tickers", params={"category": "linear"}).json()
    rows = {i["symbol"]: i for i in r.get("result", {}).get("list", [])}

    print(f"{'symbol':14s} {'lastPrice':>12s} {'turnover24h $':>16s} {'openInterest $':>16s}")
    print("-" * 62)
    data = []
    for s in CANDIDATES:
        i = rows.get(s)
        if not i:
            print(f"{s:14s} {'BRAK':>12s}")
            continue
        to = float(i.get("turnover24h") or 0)
        oi = float(i.get("openInterestValue") or 0)
        data.append((s, float(i.get("lastPrice") or 0), to, oi))
    # sortuj po obrocie malejaco
    for s, px, to, oi in sorted(data, key=lambda x: -x[2]):
        print(f"{s:14s} {px:>12.4f} {to:>16,.0f} {oi:>16,.0f}")


if __name__ == "__main__":
    main()
