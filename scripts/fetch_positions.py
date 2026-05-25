"""fetch_positions.py — Fetch live positions from all 4 venues and save positions.json.

Venues:
  1. Hyperliquid — standard crypto perps + xyz HIP-3 TradFi (SILVER, GOLD, OIL...)
  2. Extended Exchange — StarkNet DEX perps
  3. Solana — spot wallet holdings (SOL + known SPL tokens)
  4. Alpaca — paper US stock positions

Output: positions.json — unified schema consumed by blogwatcher.py and hermes.py

Schema per position:
  symbol       - canonical asset name (BTC, ETH, SILVER, SOL, NVDA, ...)
  side         - LONG | SHORT
  entry        - entry price USD
  size         - contracts / tokens / shares
  venue        - Hyperliquid | Extended | Solana | Alpaca
  venue_symbol - raw symbol on that venue (xyz:SILVER, ETH-USD, NVDA, ...)
  leverage     - "20x" | "1x" (spot)
  tp           - take-profit price or null
  sl           - stop-loss price or null
  upnl_usd     - unrealized P&L USD or null

Usage:
  python scripts/fetch_positions.py               # fetch all, save positions.json
  python scripts/fetch_positions.py --no-solana   # skip Solana RPC (faster)
  python scripts/fetch_positions.py --dry-run     # display without saving
  python scripts/fetch_positions.py --json        # raw JSON to stdout
  python scripts/fetch_positions.py --output /path/to/alt.json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import ssl
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── SSL (Windows cert store) ──────────────────────────────────────────────────
_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
os.environ.setdefault(
    "REQUESTS_CA_BUNDLE",
    str(Path.home() / ".claude" / "windows-ca-bundle.pem"),
)
os.environ.setdefault("SSL_CERT_FILE", os.environ["REQUESTS_CA_BUNDLE"])

# ── Config ────────────────────────────────────────────────────────────────────
HL_API        = "https://api.hyperliquid.xyz"
XYZ_DEX       = "xyz"
EXTENDED_URL  = "https://api.starknet.extended.exchange"
EXTENDED_KEY  = os.getenv("EXTENDED_API_KEY", "")
ALPACA_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_API_SECRET", "")
ALPACA_PAPER  = os.getenv("ALPACA_PAPER", "true").lower() == "true"
ALPACA_URL    = "https://paper-api.alpaca.markets" if ALPACA_PAPER else "https://api.alpaca.markets"
HL_WALLET       = os.getenv("HL_MAIN_WALLET_ADDRESS", "")
COINGECKO_URL   = "https://api.coingecko.com/api/v3/simple/price"
OUTPUT_PATH     = Path(__file__).parent.parent / "positions.json"

console = Console(legacy_windows=False)

# ── SQLite snapshot (historia pozycji) ────────────────────────────────────────
DB_PATH = Path(os.getenv("SQLITE_PATH", str(Path(__file__).parent.parent / "data" / "trading.db")))

_SNAPSHOT_DDL = """
CREATE TABLE IF NOT EXISTS position_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    venue       TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    side        TEXT    NOT NULL,
    size        REAL,
    entry_px    REAL,
    mark_px     REAL,
    upnl_usd    REAL,
    notional    REAL,
    leverage    TEXT,
    tp          REAL,
    sl          REAL
);
CREATE INDEX IF NOT EXISTS idx_possnap_ts  ON position_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_possnap_key ON position_snapshots(venue, symbol, side);
"""


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    for stmt in _SNAPSHOT_DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            try:
                con.execute(s)
            except sqlite3.OperationalError:
                pass
    con.commit()
    return con


def _save_snapshot(con: sqlite3.Connection, ts: float, positions: list[dict]) -> None:
    con.executemany(
        """INSERT INTO position_snapshots
           (ts, venue, symbol, side, size, entry_px, mark_px, upnl_usd, notional, leverage, tp, sl)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                ts,
                p.get("venue", ""),
                p.get("symbol", ""),
                p.get("side", ""),
                p.get("size"),
                p.get("entry"),
                p.get("mark_price"),
                p.get("upnl_usd"),
                (p.get("size") or 0) * (p.get("mark_price") or p.get("entry") or 0),
                p.get("leverage"),
                p.get("tp"),
                p.get("sl"),
            )
            for p in positions
        ],
    )
    con.commit()


def _prev_snapshot(con: sqlite3.Connection, before_ts: float) -> list[sqlite3.Row]:
    """Najnowszy zapis na każdą pozycję (venue+symbol+side) PRZED before_ts."""
    return con.execute(
        """SELECT * FROM position_snapshots
           WHERE ts = (
               SELECT MAX(ts) FROM position_snapshots p2
               WHERE p2.venue  = position_snapshots.venue
                 AND p2.symbol = position_snapshots.symbol
                 AND p2.side   = position_snapshots.side
                 AND p2.ts     < ?
           )
           GROUP BY venue, symbol, side""",
        (before_ts,),
    ).fetchall()


def _time_ago(ts: float) -> str:
    d = time.time() - ts
    if d < 60:   return f"{int(d)}s temu"
    if d < 3600: return f"{int(d/60)}m temu"
    if d < 86400:return f"{d/3600:.1f}h temu"
    return f"{d/86400:.1f}d temu"


# ── Venue → canonical symbol mapping ─────────────────────────────────────────
_VENUE_TO_SYM: dict[str, str] = {
    # Extended perps (market name → canonical)
    "BTC-USD": "BTC",      "ETH-USD": "ETH",      "SOL-USD": "SOL",
    "HYPE-USD": "HYPE",    "LINK-USD": "LINK",     "AVAX-USD": "AVAX",
    "BNB-USD": "BNB",      "XRP-USD": "XRP",       "ADA-USD": "ADA",
    "DOGE-USD": "DOGE",    "PEPE-USD": "PEPE",     "WIF-USD": "WIF",
    "XAU-USD": "GOLD",     "XAG-USD": "SILVER",    "BRENT-USD": "OIL",
    "TECH100m-USD": "NDX", "US500m-USD": "SPX",    "NAS100m-USD": "NDX",
    "US30m-USD": "DJI",    "CORN-USD": "CORN",     "NATURAL_GAS-USD": "NATGAS",
    "COFFEE-USD": "COFFEE","SUGAR-USD": "SUGAR",   "COCOA-USD": "COCOA",
    # HL xyz TradFi (coin → canonical)
    "xyz:SILVER": "SILVER","xyz:GOLD": "GOLD",     "xyz:BRENTOIL": "OIL",
    "xyz:SP500": "SPX",    "xyz:NVDA": "NVDA",     "xyz:TSLA": "TSLA",
    "xyz:CORN": "CORN",    "xyz:NATGAS": "NATGAS", "xyz:COFFEE": "COFFEE",
}

# Known Solana mint → ticker
_SOL_MINTS: dict[str, str] = {
    "So11111111111111111111111111111111111111112": "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "WIF",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "RAY",
    "HZ1JovNiVvGrGs7cTsBcEbqhKADYN2cVLYU5HpnNbvzU": "PYTH",
    "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4": "JLP",
}

_STABLECOINS = {"USDC", "USDT", "DAI", "USDS"}

# Mint → CoinGecko coin ID (for price lookup)
_MINT_TO_CGK_ID: dict[str, str] = {
    "So11111111111111111111111111111111111111112": "solana",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "usd-coin",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "tether",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "bonk",
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "dogwifcoin",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN":  "jupiter-exchange-solana",
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "raydium",
    "HZ1JovNiVvGrGs7cTsBcEbqhKADYN2cVLYU5HpnNbvzU": "pyth-network",
    "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4": "jupiter-perpetuals-liquidity-provider-token",
}


def _canonical(venue_sym: str) -> str:
    if venue_sym in _VENUE_TO_SYM:
        return _VENUE_TO_SYM[venue_sym]
    # HL standard perp coin names are already canonical (BTC, ETH, ...)
    return venue_sym.replace("-USD", "").replace("-PERP", "").upper()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _hl_post(payload: dict) -> dict | list:
    with httpx.Client(verify=_SSL, timeout=20) as c:
        r = c.post(f"{HL_API}/info", json=payload)
        r.raise_for_status()
        return r.json()


def _ext_get(path: str) -> dict | list:
    headers = {"User-Agent": "trading-ai-bot/1.0"}
    if EXTENDED_KEY:
        headers["X-Api-Key"] = EXTENDED_KEY
    with httpx.Client(verify=_SSL, timeout=15, headers=headers) as c:
        r = c.get(f"{EXTENDED_URL}{path}")
        r.raise_for_status()
        body = r.json()
        return body["data"] if isinstance(body, dict) and "data" in body else body


def _alpaca_get(path: str) -> dict | list:
    with httpx.Client(
        verify=_SSL, timeout=15,
        headers={"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET},
    ) as c:
        r = c.get(f"{ALPACA_URL}{path}")
        r.raise_for_status()
        return r.json()


def _sol_rpc(method: str, params: list) -> dict:
    endpoints = [
        os.getenv("SOLANA_RPC", ""),
        "https://rpc.ankr.com/solana",
        "https://api.mainnet-beta.solana.com",
    ]
    for url in filter(None, endpoints):
        try:
            with httpx.Client(verify=_SSL, timeout=15) as c:
                r = c.post(url, json={"jsonrpc": "2.0", "id": 1,
                                      "method": method, "params": params})
                if r.status_code == 429:
                    continue
                r.raise_for_status()
                result = r.json()
                if "error" not in result:
                    return result.get("result", {})
        except Exception:
            continue
    return {}


def _coingecko_prices(mints: list[str]) -> dict[str, float]:
    """Fetch USD prices from CoinGecko for given Solana mint addresses.

    Returns {mint_address: price_usd}.
    Stablecoins (USDC/USDT) always return 1.0 without a network call.
    """
    if not mints:
        return {}

    result: dict[str, float] = {}

    # Stablecoins are always $1 — no API call needed
    stable_mints = {m for m in mints if _SOL_MINTS.get(m) in _STABLECOINS}
    for m in stable_mints:
        result[m] = 1.0

    # Non-stablecoin mints need CoinGecko lookup
    non_stable = [m for m in mints if m not in stable_mints]
    mint_to_id = {m: _MINT_TO_CGK_ID[m] for m in non_stable if m in _MINT_TO_CGK_ID}
    if not mint_to_id:
        return result

    cgk_ids = list(set(mint_to_id.values()))
    try:
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.get(COINGECKO_URL, params={"ids": ",".join(cgk_ids), "vs_currencies": "usd"})
            r.raise_for_status()
            data = r.json()   # {"solana": {"usd": 86.55}, ...}
        for mint, cgk_id in mint_to_id.items():
            result[mint] = float(data.get(cgk_id, {}).get("usd", 0.0))
    except Exception as e:
        console.print(f"[yellow]CoinGecko price lookup failed: {e}[/yellow]")

    return result


# ── Venue fetchers ────────────────────────────────────────────────────────────

def fetch_hl(wallet: str) -> list[dict]:
    if not wallet:
        console.print("[yellow]HL: HL_MAIN_WALLET_ADDRESS not set — skipping.[/yellow]")
        return []

    # Build TP/SL map from frontendOpenOrders (both standard + xyz)
    tpsl: dict[str, dict] = {}
    try:
        for dex_param in (None, XYZ_DEX):
            payload: dict = {"type": "frontendOpenOrders", "user": wallet}
            if dex_param:
                payload["dex"] = dex_param
            orders = _hl_post(payload)
            for o in (orders if isinstance(orders, list) else []):
                coin      = o.get("coin", "")
                tpsl_type = o.get("tpsl", "")
                trigger   = o.get("triggerPx")
                if not trigger or not coin:
                    continue
                val = float(trigger)
                bucket = tpsl.setdefault(coin, {"tp": None, "sl": None})
                if tpsl_type == "tp":
                    bucket["tp"] = val
                elif tpsl_type == "sl":
                    bucket["sl"] = val
    except Exception as e:
        console.print(f"[yellow]HL orders warning: {e}[/yellow]")

    results = []

    def _parse_positions(asset_positions: list, dex_label: str) -> None:
        for p in asset_positions:
            pos = p.get("position", {})
            szi = Decimal(str(pos.get("szi", "0")))
            if szi == 0:
                continue
            coin = pos.get("coin", "?")
            # xyz coins may come back as "SILVER" or "xyz:SILVER" — normalise to "xyz:SILVER"
            if dex_label == "xyz" and not coin.startswith("xyz:"):
                venue_sym = f"xyz:{coin}"
            else:
                venue_sym = coin
            side    = "LONG" if szi > 0 else "SHORT"
            lev_obj = pos.get("leverage", {})
            lev_val = lev_obj.get("value", "?") if isinstance(lev_obj, dict) else "?"
            tp_sl   = tpsl.get(coin, tpsl.get(venue_sym, {}))
            entry_f = float(pos.get("entryPx", 0))
            upnl_f  = float(pos.get("unrealizedPnl", 0))
            size_f  = float(abs(szi))
            # mark_price = entry ± upnl/size
            # LONG:  upnl = (mark - entry)*size  →  mark = entry + upnl/size
            # SHORT: upnl = (entry - mark)*size  →  mark = entry - upnl/size
            if size_f > 0 and entry_f > 0:
                dir_  = 1.0 if side == "LONG" else -1.0
                mark_price = entry_f + dir_ * upnl_f / size_f
            else:
                mark_price = entry_f
            results.append({
                "symbol":       _canonical(venue_sym),
                "side":         side,
                "entry":        entry_f,
                "size":         size_f,
                "venue":        "Hyperliquid",
                "venue_symbol": venue_sym,
                "leverage":     f"{lev_val}x",
                "tp":           tp_sl.get("tp"),
                "sl":           tp_sl.get("sl"),
                "upnl_usd":     upnl_f,
                "mark_price":   mark_price,
            })

    try:
        state = _hl_post({"type": "clearinghouseState", "user": wallet})
        _parse_positions(state.get("assetPositions", []), "hl")
    except Exception as e:
        console.print(f"[red]HL standard perps error: {e}[/red]")

    try:
        xyz_state = _hl_post({"type": "clearinghouseState", "user": wallet, "dex": XYZ_DEX})
        _parse_positions(xyz_state.get("assetPositions", []), "xyz")
    except Exception as e:
        console.print(f"[red]HL xyz TradFi error: {e}[/red]")

    return results


def fetch_extended() -> list[dict]:
    if not EXTENDED_KEY:
        console.print("[yellow]Extended: EXTENDED_API_KEY not set — skipping.[/yellow]")
        return []

    # Build TP/SL map from orders
    tpsl: dict[str, dict] = {}
    try:
        orders = _ext_get("/api/v1/user/orders")
        for o in (orders if isinstance(orders, list) else []):
            market = o.get("market", "")
            bucket = tpsl.setdefault(market, {"tp": None, "sl": None})
            tp_obj = o.get("takeProfit")
            sl_obj = o.get("stopLoss")
            if tp_obj and tp_obj.get("triggerPrice"):
                bucket["tp"] = float(tp_obj["triggerPrice"])
            if sl_obj and sl_obj.get("triggerPrice"):
                bucket["sl"] = float(sl_obj["triggerPrice"])
    except Exception as e:
        console.print(f"[yellow]Extended orders warning: {e}[/yellow]")

    results = []
    try:
        data      = _ext_get("/api/v1/user/positions")
        positions = data if isinstance(data, list) else data.get("positions", [])
        for p in positions:
            market = p.get("market", p.get("symbol", "?"))
            side   = p.get("side", "?").upper()
            size   = p.get("size", p.get("quantity", 0))
            entry  = p.get("openPrice", p.get("entryPrice", 0))
            upnl   = p.get("unrealisedPnl", p.get("unrealizedPnl", 0))
            lev    = p.get("leverage", "?")
            mark   = p.get("markPrice", None)
            try:
                lev_str = f"{float(lev):.0f}x"
            except Exception:
                lev_str = str(lev)
            tp_sl = tpsl.get(market, {})
            entry_f = float(entry) if entry else 0.0
            mark_f  = float(mark) if mark else entry_f
            results.append({
                "symbol":       _canonical(market),
                "side":         side,
                "entry":        entry_f,
                "size":         float(size) if size else 0.0,
                "venue":        "Extended",
                "venue_symbol": market,
                "leverage":     lev_str,
                "tp":           tp_sl.get("tp"),
                "sl":           tp_sl.get("sl"),
                "upnl_usd":     float(upnl) if upnl else 0.0,
                "mark_price":   mark_f,
            })
    except Exception as e:
        console.print(f"[red]Extended positions error: {e}[/red]")

    return results


def fetch_solana() -> list[dict]:
    pk_b58 = os.getenv("SOLANA_PRIVATE_KEY", "")
    if not pk_b58:
        console.print("[yellow]Solana: SOLANA_PRIVATE_KEY not set — skipping.[/yellow]")
        return []

    try:
        from solders.keypair import Keypair
        import base58 as b58
        keypair = Keypair.from_bytes(b58.b58decode(pk_b58))
        pubkey  = str(keypair.pubkey())
    except Exception as e:
        console.print(f"[yellow]Solana keypair: {e} — skipping.[/yellow]")
        return []

    results = []
    SOL_MINT = "So11111111111111111111111111111111111111112"

    # SOL native balance
    try:
        bal = _sol_rpc("getBalance", [pubkey, {"commitment": "confirmed"}])
        lamports   = bal.get("value", 0) if isinstance(bal, dict) else bal
        sol_amount = lamports / 1e9
        if sol_amount > 0.001:
            prices    = _coingecko_prices([SOL_MINT])
            sol_price = prices.get(SOL_MINT, 0.0)
            results.append({
                "symbol": "SOL", "side": "LONG",
                "entry": sol_price, "size": round(sol_amount, 6),
                "venue": "Solana", "venue_symbol": "SOL",
                "leverage": "1x", "tp": None, "sl": None,
                "upnl_usd": None, "mark_price": sol_price,
            })
    except Exception as e:
        console.print(f"[yellow]Solana SOL balance: {e}[/yellow]")

    # SPL token accounts
    try:
        token_resp = _sol_rpc("getTokenAccountsByOwner", [
            pubkey,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed", "commitment": "confirmed"},
        ])
        accounts = token_resp.get("value", []) if isinstance(token_resp, dict) else []

        mints_to_fetch: list[str] = []
        holdings: dict[str, float] = {}
        for acc in accounts:
            info     = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint     = info.get("mint", "")
            decimals = info.get("tokenAmount", {}).get("decimals", 0)
            raw_amt  = int(info.get("tokenAmount", {}).get("amount", "0"))
            ui_amt   = raw_amt / (10 ** decimals) if decimals else raw_amt
            if mint in _SOL_MINTS and ui_amt > 0:
                mints_to_fetch.append(mint)
                holdings[mint] = ui_amt

        if mints_to_fetch:
            prices = _coingecko_prices(mints_to_fetch)
            for mint in mints_to_fetch:
                ticker = _SOL_MINTS[mint]
                amt    = holdings[mint]
                price  = prices.get(mint, 0.0)
                # Stablecoins: show only if > $0.01 (use $1.00 price)
                if ticker in _STABLECOINS:
                    if amt < 0.01:
                        continue
                    price = 1.0  # guaranteed $1
                else:
                    if amt * price < 0.01:
                        continue  # skip dust
                results.append({
                    "symbol": ticker, "side": "LONG",
                    "entry": price, "size": round(amt, 6),
                    "venue": "Solana", "venue_symbol": mint,
                    "leverage": "1x", "tp": None, "sl": None,
                    "upnl_usd": None, "mark_price": price,
                })
    except Exception as e:
        console.print(f"[yellow]Solana SPL tokens: {e}[/yellow]")

    return results


def fetch_alpaca() -> list[dict]:
    if not ALPACA_KEY:
        console.print("[yellow]Alpaca: ALPACA_API_KEY not set — skipping.[/yellow]")
        return []

    results = []
    try:
        positions = _alpaca_get("/v2/positions")
        for p in (positions if isinstance(positions, list) else []):
            side = "LONG" if p.get("side", "long").lower() == "long" else "SHORT"
            mark_px = float(p.get("current_price", p.get("avg_entry_price", 0)))
            results.append({
                "symbol":       p.get("symbol", "?").upper(),
                "side":         side,
                "entry":        float(p.get("avg_entry_price", 0)),
                "size":         float(p.get("qty", 0)),
                "venue":        "Alpaca",
                "venue_symbol": p.get("symbol", "?"),
                "leverage":     "1x",
                "tp":           None,
                "sl":           None,
                "upnl_usd":     float(p.get("unrealized_pl", 0)),
                "mark_price":   mark_px,
            })
    except Exception as e:
        console.print(f"[red]Alpaca positions error: {e}[/red]")

    return results


# ── Display ───────────────────────────────────────────────────────────────────

def _fp(v: float | None, d: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):,.{d}f}"
    except Exception:
        return str(v)


def _fmt_delta(v: float | None) -> str:
    if v is None:
        return "[dim]—[/dim]"
    c     = "green" if v >= 0 else "red"
    arrow = "▲" if v >= 0 else "▼"
    return f"[{c}]{arrow}{abs(v):,.2f}[/{c}]"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "[dim]—[/dim]"
    c     = "green" if v >= 0 else "red"
    arrow = "▲" if v >= 0 else "▼"
    return f"[{c}]{arrow}{abs(v):.2f}%[/{c}]"


def display(
    positions:  list[dict],
    prev_map:   dict[tuple, sqlite3.Row] | None = None,
    prev_ts:    float | None = None,
) -> None:
    if not positions:
        console.print("[dim]No open positions found across all venues.[/dim]")
        return

    by_venue: dict[str, int] = {}
    for p in positions:
        v = p.get("venue", "?")
        by_venue[v] = by_venue.get(v, 0) + 1
    summary = " | ".join(f"{v}: {n}" for v, n in by_venue.items())

    delta_label = ""
    if prev_ts:
        dt = datetime.fromtimestamp(prev_ts, tz=timezone.utc).strftime("%H:%M UTC")
        delta_label = f"  [dim](Δ od {_time_ago(prev_ts)} · {dt})[/dim]"
    elif prev_map is not None:
        delta_label = "  [dim](pierwszy snapshot — brak historii do porównania)[/dim]"

    console.print(
        f"\n[bold]Live Positions — {len(positions)} total[/bold]  "
        f"[dim]{summary}[/dim]{delta_label}\n"
    )

    show_delta = bool(prev_map)
    table = Table(show_header=True, header_style="bold")
    table.add_column("Symbol",   style="cyan")
    table.add_column("Venue",    style="dim")
    table.add_column("Side")
    table.add_column("Size",     justify="right")
    table.add_column("Entry $",  justify="right")
    table.add_column("Mark $",   justify="right")
    table.add_column("uPnL $",   justify="right")
    if show_delta:
        table.add_column("Δ PnL",    justify="right")
        table.add_column("Δ%",       justify="right")
    table.add_column("Lev",      justify="right", style="dim")
    table.add_column("TP $",     justify="right", style="green")
    table.add_column("SL $",     justify="right", style="red")

    total_upnl  = 0.0
    total_delta = 0.0
    any_delta   = False

    for p in sorted(positions, key=lambda x: x.get("venue", "")):
        side  = p.get("side", "?")
        sc    = "green" if side == "LONG" else ("red" if side == "SHORT" else "blue")
        upnl  = p.get("upnl_usd")
        entry = p.get("entry", 0) or 0.0
        mark  = p.get("mark_price", entry) or entry
        d     = 4 if entry and float(entry) < 10 else 2

        upnl_str = f"[{'green' if (upnl or 0) >= 0 else 'red'}]${(upnl or 0):+,.2f}[/]" if upnl is not None else "—"
        total_upnl += upnl or 0.0

        row = [
            p.get("symbol", "?"),
            p.get("venue", "?"),
            f"[{sc}]{side}[/{sc}]",
            str(p.get("size", "?")),
            _fp(entry, d),
            _fp(mark,  d),
            upnl_str,
        ]

        if show_delta and prev_map is not None:
            key  = (p.get("venue", ""), p.get("symbol", ""), p.get("side", ""))
            prev = prev_map.get(key)
            delta: float | None = None
            dpct:  float | None = None
            if prev is not None and prev["upnl_usd"] is not None and upnl is not None:
                delta = upnl - float(prev["upnl_usd"])
                notional = (p.get("size") or 0) * (mark or 1)
                if notional:
                    dpct = delta / abs(notional) * 100
                any_delta    = True
                total_delta += delta
            row += [_fmt_delta(delta), _fmt_pct(dpct)]

        row += [
            p.get("leverage", "?"),
            _fp(p.get("tp"), d),
            _fp(p.get("sl"), d),
        ]
        table.add_row(*row)

    console.print(table)

    # Podsumowanie
    uc = "green" if total_upnl >= 0 else "red"
    line = f"\n[bold]Total uPnL:[/bold]  [{uc}]{total_upnl:+,.2f} USD[/{uc}]"
    if any_delta:
        dc   = "green" if total_delta >= 0 else "red"
        line += f"   [bold]Zmiana od ost. checkup:[/bold]  [{dc}]{total_delta:+,.2f} USD[/{dc}]"
    console.print(line)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch live positions — z deltą od poprzedniego checkupu.")
    parser.add_argument("--output",    default=str(OUTPUT_PATH), help="Output JSON path")
    parser.add_argument("--no-solana", action="store_true",  help="Pomiń Solana RPC")
    parser.add_argument("--dry-run",   action="store_true",  help="Wyświetl bez zapisu")
    parser.add_argument("--json",      action="store_true",  help="Raw JSON na stdout")
    parser.add_argument("--no-save",   action="store_true",  help="Nie zapisuj snapshotu do SQLite")
    parser.add_argument("--diff",      action="store_true",  help="Tylko diff (bez pobierania na żywo)")
    parser.add_argument("--since",     type=str, default=None,
                        help="Diff vs snapshot sprzed X: 2h / 30m / 1d")
    parser.add_argument("--history",   type=int, default=0,
                        help="Pokaż ostatnich N snapshotów na każdą pozycję")
    args = parser.parse_args()

    con = _db()
    now = time.time()

    # ── Tryb historii ──
    if args.history > 0:
        rows = con.execute(
            "SELECT * FROM position_snapshots ORDER BY ts DESC LIMIT ?",
            (args.history * 20,),
        ).fetchall()
        if not rows:
            console.print("[dim]Brak historii snapshotów. Uruchom najpierw bez --history.[/dim]")
            return
        from rich.table import Table as _T
        t = _T(title=f"Historia snapshotów (do {args.history} wpisów na pozycję)")
        t.add_column("Czas", style="dim")
        t.add_column("Venue")
        t.add_column("Symbol", style="cyan")
        t.add_column("Side")
        t.add_column("Mark $",  justify="right")
        t.add_column("uPnL $",  justify="right")
        seen: dict[tuple, int] = {}
        for row in rows:
            key = (row["venue"], row["symbol"], row["side"])
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > args.history:
                continue
            dt  = datetime.fromtimestamp(row["ts"], tz=timezone.utc).strftime("%m-%d %H:%M UTC")
            mpx = row["mark_px"]
            mpx_str = (_fp(mpx, 4) if mpx and mpx < 10 else _fp(mpx)) if mpx else "—"
            upnl = row["upnl_usd"]
            u_str = (f"[{'green' if upnl >= 0 else 'red'}]${upnl:+,.2f}[/]" if upnl is not None else "—")
            t.add_row(dt, row["venue"], row["symbol"], row["side"], mpx_str, u_str)
        console.print(t)
        return

    # ── Parsowanie --since ──
    ref_ts: float | None = None
    if args.since:
        s = args.since.strip().lower()
        try:
            if   s.endswith("h"): ref_ts = now - float(s[:-1]) * 3600
            elif s.endswith("m"): ref_ts = now - float(s[:-1]) * 60
            elif s.endswith("d"): ref_ts = now - float(s[:-1]) * 86400
            else:
                console.print(f"[red]Nieznany format --since: {s}  (np. 2h, 30m, 1d)[/red]")
                sys.exit(1)
        except ValueError:
            console.print(f"[red]Nieprawidłowy format --since: {s}[/red]")
            sys.exit(1)

    # ── Tryb --diff (bez live fetch) ──
    if args.diff:
        last_rows = con.execute(
            """SELECT * FROM position_snapshots
               WHERE ts = (
                   SELECT MAX(ts) FROM position_snapshots p2
                   WHERE p2.venue  = position_snapshots.venue
                     AND p2.symbol = position_snapshots.symbol
                     AND p2.side   = position_snapshots.side
               )
               GROUP BY venue, symbol, side""",
        ).fetchall()
        if not last_rows:
            console.print("[dim]Brak snapshotów w bazie. Uruchom najpierw bez --diff.[/dim]")
            return
        last_ts = max(float(r["ts"]) for r in last_rows)
        dt_str  = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        console.print(f"[dim]Ostatni snapshot: {dt_str} ({_time_ago(last_ts)})[/dim]")
        current_positions = [
            {
                "venue":       r["venue"],
                "symbol":      r["symbol"],
                "side":        r["side"],
                "size":        r["size"]     or 0.0,
                "entry":       r["entry_px"] or 0.0,
                "mark_price":  r["mark_px"],
                "upnl_usd":    r["upnl_usd"] or 0.0,
                "leverage":    r["leverage"],
                "tp":          r["tp"],
                "sl":          r["sl"],
            }
            for r in last_rows
        ]
        prev_ref = ref_ts if ref_ts else (last_ts - 1)
        prev_rows = _prev_snapshot(con, before_ts=prev_ref + 1)
        prev_map  = {(r["venue"], r["symbol"], r["side"]): r for r in prev_rows}
        prev_ts_v = max((float(r["ts"]) for r in prev_rows), default=None)
        display(current_positions, prev_map, prev_ts_v)
        return

    # ── Normalny tryb: fetch na żywo ──
    console.print("\n[bold]Fetching live positions...[/bold]")
    positions: list[dict] = []
    positions += fetch_hl(HL_WALLET)
    positions += fetch_extended()
    if not args.no_solana:
        positions += fetch_solana()
    positions += fetch_alpaca()

    if args.json:
        print(json.dumps(positions, indent=2, ensure_ascii=False))
        return

    # Wczytaj poprzedni snapshot PRZED zapisem (before_ts = now, strict <)
    prev_ref2 = ref_ts if ref_ts else now
    prev_rows2 = _prev_snapshot(con, before_ts=prev_ref2)
    prev_map2  = {(r["venue"], r["symbol"], r["side"]): r for r in prev_rows2}
    prev_ts2   = max((float(r["ts"]) for r in prev_rows2), default=None)

    display(positions, prev_map2, prev_ts2)

    if not args.dry_run:
        out = Path(args.output)
        out.write_text(json.dumps(positions, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"\n[green]Saved {len(positions)} positions → {out}[/green]")
    else:
        console.print("\n[dim]--dry-run: positions.json not updated[/dim]")

    if not args.no_save and not args.dry_run:
        _save_snapshot(con, now, positions)
        dt_str = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%H:%M:%S UTC")
        console.print(f"[dim]Snapshot zapisany do SQLite @ {dt_str}[/dim]")


if __name__ == "__main__":
    main()
