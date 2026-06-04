"""New Listings Scanner — monitors exchange announcement pages for upcoming listings.

The REAL edge: exchanges announce listings 1-48h BEFORE trading starts.
Knowing the announcement = knowing the pump before it happens.

Sources monitored:
  Binance   — cms announcement API (1-24h before listing)
  Coinbase  — asset listing announcements (24-48h before)
  Bybit     — announcements API v5 (1-24h before)
  Upbit     — Korean exchange, often biggest pumps (1-24h before)
  OKX       — announcements (1-24h before)

Alert types:
  🔔 ANNOUNCEMENT — exchange announced upcoming listing (1-48h before go-live)
  🚀 LIVE NOW     — token just appeared in available markets (go-live moment)
  ⏰ SCHEDULED    — announcement includes specific date/time

Usage:
    python scripts/listings_scanner.py              # one-shot scan
    python scripts/listings_scanner.py --daemon     # run every 1h forever
    python scripts/listings_scanner.py --interval 1800  # custom interval (seconds)
    python scripts/listings_scanner.py --dry-run    # no Telegram, print only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Force UTF-8 on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_SSL       = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")

# Tickers to always ignore (stablecoins, already everywhere)
IGNORE_TICKERS = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "USDE",
    "USD", "EUR", "GBP", "AED", "JPY", "KRW",          # fiat
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX",
    "OKB", "BNX",                                       # exchange tokens
}

# Title substrings that indicate NOISE — not a new crypto listing
# (case-insensitive match — skip if ANY of these appear in the title)
IGNORE_TITLE_PATTERNS = [
    "pre-ipo",       # Bybit/Binance pre-IPO perps (ANTHROPICUSDT Pre-IPO etc.)
    "tradfi",        # traditional finance perps (SAMSUNG, HYUNDAI etc.)
    "margin",        # margin pair additions — not new listings
    "/aed", "/eur", "/gbp", "/jpy",   # fiat trading pair additions
    "stablecoin",
    "institutional",
    "simple earn",
    "hodler airdrop",  # airdrop announcements, not listings
    "earn flexible",
    "earn yield",
    "loan",
    "vip loan",
    "convert",
    "cross margin",
    "isolated margin",
    "multiple usd",    # "Multiple USDT-Margined" batch futures announcements
]


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"\n[TELEGRAM DRY-RUN]\n{text}\n")
        return
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        with httpx.Client(verify=_SSL, timeout=10) as c:
            c.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
    except Exception as e:
        print(f"[WARN] Telegram: {e}")


# ── SQLite state (seen announcements) ─────────────────────────────────────────

def _get_db():
    sys.path.insert(0, str(Path(__file__).parent))
    from db import DB
    db = DB()
    db._sqlite.execute("""
        CREATE TABLE IF NOT EXISTS listing_announcements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            exchange    TEXT NOT NULL,
            ann_id      TEXT NOT NULL UNIQUE,
            title       TEXT,
            ticker      TEXT,
            url         TEXT,
            ann_type    TEXT DEFAULT 'announcement'
        )""")
    db._sqlite.execute(
        "CREATE INDEX IF NOT EXISTS idx_listing_exchange ON listing_announcements(exchange)")
    return db


def is_seen(db, ann_id: str) -> bool:
    rows = db._sqlite.query(
        "SELECT id FROM listing_announcements WHERE ann_id = ?", (ann_id,))
    return len(rows) > 0


def mark_seen(db, exchange: str, ann_id: str, title: str,
              ticker: str, url: str, ann_type: str = "announcement") -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        db._sqlite.execute(
            """INSERT OR IGNORE INTO listing_announcements
               (ts, exchange, ann_id, title, ticker, url, ann_type)
               VALUES (?,?,?,?,?,?,?)""",
            (ts, exchange, ann_id, title, ticker, url, ann_type),
        )
    except Exception:
        pass


def exchange_initialized(db, exchange: str) -> bool:
    """True if we've done at least one baseline scan for this exchange."""
    rows = db._sqlite.query(
        "SELECT id FROM listing_announcements WHERE exchange = ? LIMIT 1",
        (exchange,),
    )
    return len(rows) > 0


# ── Ticker extraction ─────────────────────────────────────────────────────────

def extract_ticker(text: str) -> str | None:
    """Extract token ticker from announcement title.

    Handles:
    - "Will List XYZ" / "Lists XYZ" / "(XYZ)"
    - "New listing: XYZUSDT Perpetual Contract" → XYZ
    - "OKX will launch XYZ/USD" → XYZ
    - "Binance Futures Will Launch XYZUSDT" → XYZ
    """
    # Pattern: "Will List XYZ" or "Lists XYZ" or "(XYZ)" or "XYZ Spot"
    patterns = [
        r'\(([A-Z]{2,12})\)',                          # (TICKER) — most reliable
        r'[Ll]ist(?:ing)?[:\s]+([A-Z]{2,12})\b',      # list/listing: TICKER (covers "listing: NOWUSDT")
        r'[Ll]aunch\s+([A-Z]{2,12})\b',               # launch TICKER
        r'[Aa]dds?\s+([A-Z]{2,12})\b',                # adds/add TICKER
        r'[Ll]ist\s+([A-Z]{2,12})\b',                 # list TICKER
        r'^([A-Z]{2,12})\s+[Ss]pot',                  # TICKER Spot
        r'[Tt]oken[:\s]+([A-Z]{2,12})\b',             # token: TICKER
        r'launch\s+([A-Z]{2,12})/[A-Z]{3}',           # launch XYZ/USD (OKX style)
    ]
    # Common quote-currency suffixes on futures/spot contract names
    QUOTE_SUFFIXES = ("USDT", "USD", "USDC", "BUSD", "BTC", "ETH", "BNB", "EUR")

    for pat in patterns:
        m = re.search(pat, text)
        if m:
            ticker = m.group(1).upper()
            # Strip trailing quote currency (XYZUSDT → XYZ)
            for suffix in QUOTE_SUFFIXES:
                if ticker.endswith(suffix) and len(ticker) > len(suffix) + 1:
                    ticker = ticker[: -len(suffix)]
                    break
            if ticker not in IGNORE_TICKERS and len(ticker) >= 2:
                return ticker
    return None


# ── Exchange scrapers ─────────────────────────────────────────────────────────

def _scan_binance_catalog(db, catalog_id: str, exchange_name: str,
                          id_prefix: str, kw_filter: list[str]) -> list[dict]:
    """Generic Binance CMS scanner for any catalog ID.

    Uses the /catalog/list/query endpoint (updated — old /article/list/query
    changed structure to data.catalogs[].articles[] which broke the scanner).
    """
    alerts = []
    is_first_run = not exchange_initialized(db, exchange_name)
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(
                # NEW endpoint — returns data.articles[] directly
                "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query",
                params={"catalogId": catalog_id, "pageSize": "20", "pageNo": "1"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        items = r.json().get("data", {}).get("articles", [])
        for item in items:
            ann_id = f"{id_prefix}_{item.get('id', '')}"
            title  = item.get("title", "")
            url    = f"https://www.binance.com/en/support/announcement/{item.get('code', '')}"

            if not title or is_seen(db, ann_id):
                continue

            ticker = extract_ticker(title)

            # ALWAYS mark as seen — even if kw_filter doesn't match.
            # Without this, non-matching items silently re-process every scan forever.
            mark_seen(db, exchange_name, ann_id, title, ticker or "", url)

            if kw_filter and not any(kw in title.lower() for kw in kw_filter):
                continue  # baseline'd but don't alert — not a listing announcement

            if not is_first_run:
                alerts.append({
                    "exchange": exchange_name,
                    "title":    title,
                    "ticker":   ticker,
                    "url":      url,
                    "type":     "announcement",
                })
        if is_first_run and items:
            print(f"[{exchange_name}] baseline saved ({len(items)} articles)", end=" ")
    except Exception as e:
        print(f"[{exchange_name}] Error: {e}")
    return alerts


def scan_binance(db, dry_run: bool) -> list[dict]:
    """Binance Spot (catalogId 48) + Futures (catalogId 161)."""
    spot = _scan_binance_catalog(
        db, "48", "Binance", "binance_spot",
        ["will list", "lists", "adds", "new listing", "spot listing"]
    )
    futures = _scan_binance_catalog(
        db, "161", "Binance Futures", "binance_fut",
        ["will launch", "launch", "futures", "perpetual", "will list", "usdt-m"]
    )
    return spot + futures


def scan_bybit(db, dry_run: bool) -> list[dict]:
    """Bybit announcements — v5 API (old announcements.bybit.com/api/v1 is dead).

    New endpoint: api.bybit.com/v5/announcements/index with type=new_crypto.
    No unique numeric ID — use URL slug as ann_id.
    """
    alerts = []
    is_first_run = not exchange_initialized(db, "Bybit")
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(
                "https://api.bybit.com/v5/announcements/index",
                params={"locale": "en-US", "type": "new_crypto",
                        "page": "1", "limit": "20"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        items = r.json().get("result", {}).get("list", [])
        for item in items:
            url   = item.get("url", "https://announcements.bybit.com")
            title = item.get("title", "")
            # Use URL slug as unique ID (no numeric id in v5)
            slug  = url.rstrip("/").split("/")[-1] if url else ""
            ann_id = f"bybit_{slug}" if slug else f"bybit_{title[:40]}"

            if not title or is_seen(db, ann_id):
                continue

            ticker = extract_ticker(title)
            mark_seen(db, "Bybit", ann_id, title, ticker or "", url)
            if not is_first_run:
                alerts.append({
                    "exchange": "Bybit",
                    "title":    title,
                    "ticker":   ticker,
                    "url":      url,
                    "type":     "announcement",
                })
        if is_first_run and items:
            print(f"[Bybit] baseline saved ({len(items)} articles)", end=" ")
    except Exception as e:
        print(f"[Bybit] Error: {e}")
    return alerts


def scan_coinbase(db, dry_run: bool) -> list[dict]:
    """Coinbase new assets — detects when asset appears in /currencies."""
    alerts = []
    is_first_run = not exchange_initialized(db, "Coinbase")
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get("https://api.exchange.coinbase.com/currencies",
                      headers={"User-Agent": "Mozilla/5.0"})
        currencies = r.json()
        for curr in currencies:
            if curr.get("type") != "crypto":
                continue
            ticker = curr.get("id", "").upper()
            if ticker in IGNORE_TICKERS:
                continue
            ann_id = f"coinbase_{ticker}"
            if is_seen(db, ann_id):
                continue

            name = curr.get("name", ticker)
            url  = f"https://www.coinbase.com/price/{name.lower().replace(' ', '-')}"
            mark_seen(db, "Coinbase", ann_id, f"Coinbase listed {ticker}", ticker, url, "live")

            # First run = baseline only, no alerts
            if not is_first_run:
                alerts.append({
                    "exchange": "Coinbase",
                    "title":    f"Coinbase listed {ticker} ({name})",
                    "ticker":   ticker,
                    "url":      url,
                    "type":     "live",
                })
        if is_first_run:
            print(f"[Coinbase] baseline saved ({len(currencies)} assets)", end=" ")
    except Exception as e:
        print(f"[Coinbase] Error: {e}")
    return alerts


def scan_upbit(db, dry_run: bool) -> list[dict]:
    """Upbit — new token listings across ALL markets (KRW, USDT, BTC).
    Deduplicates by base ticker so SLX from KRW-SLX/USDT-SLX/BTC-SLX = one alert.
    """
    alerts = []
    is_first_run = not exchange_initialized(db, "Upbit")
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get("https://api.upbit.com/v1/market/all",
                      headers={"User-Agent": "Mozilla/5.0"})
        markets = r.json()

        # Deduplicate by base ticker (SLX from KRW-SLX, USDT-SLX, BTC-SLX → one entry)
        # Priority: KRW > USDT > BTC (KRW listing = bigger pump signal)
        priority = {"KRW": 0, "USDT": 1, "BTC": 2}
        best: dict[str, tuple] = {}  # ticker → (priority, market_str, market_obj)
        for m in markets:
            mkt = m.get("market", "")
            parts = mkt.split("-")
            if len(parts) != 2:
                continue
            quote, base = parts[0], parts[1]
            if base in IGNORE_TICKERS:
                continue
            p = priority.get(quote, 99)
            if base not in best or p < best[base][0]:
                best[base] = (p, mkt, m)

        new_count = 0
        for ticker, (_, market_str, m) in best.items():
            ann_id = f"upbit_{ticker}"
            if is_seen(db, ann_id):
                continue

            name  = m.get("korean_name", ticker)
            quote = market_str.split("-")[0]
            url   = f"https://upbit.com/exchange?code=CRIX.UPBIT.{market_str}"
            mark_seen(db, "Upbit", ann_id,
                      f"Upbit {quote} listing: {ticker} ({name})", ticker, url, "live")
            new_count += 1

            if not is_first_run:
                alerts.append({
                    "exchange": "Upbit",
                    "title":    f"Upbit {quote}: {ticker} ({name})",
                    "ticker":   ticker,
                    "url":      url,
                    "type":     "live",
                })
        if is_first_run:
            print(f"[Upbit] baseline saved ({new_count} unique tickers)", end=" ")
    except Exception as e:
        print(f"[Upbit] Error: {e}")
    return alerts


def scan_okx(db, dry_run: bool) -> list[dict]:
    """OKX announcement feed.

    Uses data.notices[] (not data.lists[] — old field name is gone).
    Category: 'announcements-new-listings' (not 'New Listings').
    """
    alerts = []
    is_first_run = not exchange_initialized(db, "OKX")
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(
                "https://www.okx.com/v2/support/home/web",
                params={"category": "announcements-new-listings", "limit": "15"},
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
        items = r.json().get("data", {}).get("notices", [])
        for item in items:
            slug   = item.get("slug", item.get("link", "").strip("/").split("/")[-1])
            ann_id = f"okx_{slug}"
            title  = item.get("title", item.get("shareTitle", ""))
            url    = f"https://www.okx.com{item.get('link', '')}"

            if not title or is_seen(db, ann_id):
                continue

            ticker = extract_ticker(title)
            mark_seen(db, "OKX", ann_id, title, ticker or "", url)
            if not is_first_run:
                alerts.append({
                    "exchange": "OKX",
                    "title":    title,
                    "ticker":   ticker,
                    "url":      url,
                    "type":     "announcement",
                })
        if is_first_run and items:
            print(f"[OKX] baseline saved ({len(items)} articles)", end=" ")
    except Exception as e:
        print(f"[OKX] Error: {e}")
    return alerts


# ── Alert formatting ──────────────────────────────────────────────────────────

def format_listing_alert(alert: dict, ts: str) -> str:
    exchange = alert["exchange"]
    ticker   = alert.get("ticker") or "?"
    title    = alert["title"]
    url      = alert["url"]
    atype    = alert.get("type", "announcement")

    if atype == "announcement":
        emoji = "🔔"
        label = "UPCOMING LISTING"
        note  = "⚡ Ogłoszenie — listing jeszcze nie na żywo. Sprawdź datę i kup przed listingiem."
    else:
        emoji = "🚀"
        label = "LIVE NOW"
        note  = "✅ Token już handluje. Sprawdź DexScreener czy jest early."

    exchange_emojis = {
        "Binance":  "🟡",
        "Coinbase": "🔵",
        "Bybit":    "🟠",
        "Upbit":    "🇰🇷",
        "OKX":      "⚫",
    }
    ex_emoji = exchange_emojis.get(exchange, "📢")

    lines = [
        f"{emoji} <b>{label}</b> — {ts}",
        f"",
        f"{ex_emoji} <b>{exchange}</b>: <b>${ticker}</b>",
        f"📋 {title[:100]}",
        f"",
        f"{note}",
        f"",
        f"🔍 DexScreener: https://dexscreener.com/search?q={ticker}",
        f"🔗 Ogłoszenie: {url[:80]}",
    ]
    return "\n".join(lines)


# ── Main scan ─────────────────────────────────────────────────────────────────

def _save_heartbeat(db, count: int) -> None:
    """Save scan run timestamp to DB — lets dashboard show when scanner last ran."""
    try:
        ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db._sqlite.execute("""CREATE TABLE IF NOT EXISTS scanner_runs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            scanner  TEXT NOT NULL,
            count    INTEGER DEFAULT 0
        )""")
        db._sqlite.execute(
            "INSERT INTO scanner_runs (ts, scanner, count) VALUES (?,?,?)",
            (ts_iso, "listings", count),
        )
    except Exception:
        pass


def _is_noise(alert: dict) -> bool:
    """Return True if this alert is noise and should be suppressed.

    Filters:
    - No ticker extracted (title unparseable) → too vague to act on
    - Title contains known noise patterns (Pre-IPO, TradFi, margin pairs, etc.)
    """
    # Must have a real ticker
    if not alert.get("ticker"):
        return True

    title_lower = alert.get("title", "").lower()
    for pattern in IGNORE_TITLE_PATTERNS:
        if pattern in title_lower:
            return True
    return False


def run_once(dry_run: bool, interval_s: int = 3600) -> int:
    ts  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db  = _get_db()
    all_alerts: list[dict] = []

    scanners = [
        ("Binance",  scan_binance),
        ("Bybit",    scan_bybit),
        ("Coinbase", scan_coinbase),
        ("Upbit",    scan_upbit),
        ("OKX",      scan_okx),
    ]

    print(f"[{ts}] Scanning {len(scanners)} exchanges...", end=" ", flush=True)
    for name, scanner_fn in scanners:
        try:
            raw = scanner_fn(db, dry_run)

            # Per-exchange flood protection: >4 items from one exchange in one run
            # = ann_id format changed / DB migration, not genuine new listings.
            # Items are already mark_seen'd — just suppress Telegram alerts.
            if len(raw) > 4:
                print(f"{name}:FLOOD({len(raw)},suppressed)", end=" ", flush=True)
                for a in raw:
                    print(f"  [FLOOD-{name}] {a.get('ticker','?')}")
                continue  # don't add to all_alerts

            # Noise filter — remove non-actionable items
            clean = [a for a in raw if not _is_noise(a)]
            noisy = len(raw) - len(clean)

            if clean:
                print(f"{name}:{len(clean)}", end=" ", flush=True)
            elif noisy:
                print(f"{name}:noise({noisy})", end=" ", flush=True)

            all_alerts.extend(clean)
        except Exception as e:
            print(f"{name}:ERR({e})", end=" ", flush=True)

    print(f"| Actionable: {len(all_alerts)}")
    _save_heartbeat(db, len(all_alerts))

    for alert in all_alerts:
        msg = format_listing_alert(alert, ts)
        send_telegram(msg, dry_run=dry_run)
        print(f"  → {alert['exchange']} {alert.get('ticker','?')} [{alert['type']}]")

    # Heartbeat — send status when no new listings (but not more than 1x/scan)
    if not all_alerts:
        interval_h = max(1, interval_s // 3600)
        hb = (
            f"📡 <b>Listings Scanner</b> — {ts}\n"
            f"\n"
            f"✅ Brak nowych listingów\n"
            f"Monitorowane: Binance | Binance Futures | Coinbase | Upbit | OKX\n"
            f"\n"
            f"<i>Następne sprawdzenie za {interval_h}h</i>"
        )
        send_telegram(hb, dry_run=dry_run)
        print(f"[{ts}] Heartbeat sent — no new listings.")

    return len(all_alerts)


def main() -> None:
    p = argparse.ArgumentParser(description="New Listings Scanner — exchange announcements")
    p.add_argument("--interval", type=int, default=3600,
                   help="Scan interval seconds (default: 3600 = 1h)")
    p.add_argument("--daemon",   action="store_true",
                   help="Run forever")
    p.add_argument("--dry-run",  action="store_true",
                   help="Print alerts, don't send Telegram")
    args = p.parse_args()

    if args.daemon:
        print(f"Listings Scanner daemon — interval: {args.interval}s | "
              f"Telegram: {'DRY-RUN' if args.dry_run else 'LIVE'}")
        while True:
            run_once(args.dry_run, args.interval)
            print(f"Sleeping {args.interval}s ({args.interval//60}min)...")
            time.sleep(args.interval)
    else:
        run_once(args.dry_run, args.interval)


if __name__ == "__main__":
    main()
