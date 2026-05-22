"""New Listings Scanner — monitors exchange announcement pages for upcoming listings.

The REAL edge: exchanges announce listings 1-48h BEFORE trading starts.
Knowing the announcement = knowing the pump before it happens.

Sources monitored:
  Binance   — cms announcement API (1-24h before listing)
  Coinbase  — asset listing announcements (24-48h before)
  Bybit     — announcements API (1-24h before)
  Upbit     — Korean exchange, often biggest pumps (1-24h before)
  OKX       — announcements (1-24h before)

Alert types:
  🔔 ANNOUNCEMENT — exchange announced upcoming listing (1-48h before go-live)
  🚀 LIVE NOW     — token just appeared in available markets (go-live moment)
  ⏰ SCHEDULED    — announcement includes specific date/time

Usage:
    python scripts/listings_scanner.py              # one-shot scan
    python scripts/listings_scanner.py --daemon     # run every 30min forever
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
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP",
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "TRX",
}


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
    """Extract token ticker from announcement title."""
    # Pattern: "Will List XYZ" or "Lists XYZ" or "(XYZ)" or "XYZ Spot"
    patterns = [
        r'[Ll]ist\s+([A-Z]{2,10})\b',
        r'\(([A-Z]{2,10})\)',
        r'[Aa]dds?\s+([A-Z]{2,10})\b',
        r'^([A-Z]{2,10})\s+[Ss]pot',
        r'[Tt]oken[:\s]+([A-Z]{2,10})\b',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            ticker = m.group(1).upper()
            if ticker not in IGNORE_TICKERS and len(ticker) >= 2:
                return ticker
    return None


# ── Exchange scrapers ─────────────────────────────────────────────────────────

def scan_binance(db, dry_run: bool) -> list[dict]:
    """Binance announcement CMS API — new listing announcements."""
    alerts = []
    is_first_run = not exchange_initialized(db, "Binance")
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(
                "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
                params={"type": "1", "catalogId": "48", "pageSize": "20", "pageNo": "1"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        items = r.json().get("data", {}).get("articles", [])
        for item in items:
            ann_id = f"binance_{item.get('id', '')}"
            title  = item.get("title", "")
            url    = f"https://www.binance.com/en/support/announcement/{item.get('code', '')}"

            if not title or is_seen(db, ann_id):
                continue
            if not any(kw in title.lower() for kw in
                       ["will list", "lists", "adds", "new listing", "spot listing"]):
                continue

            ticker = extract_ticker(title)
            mark_seen(db, "Binance", ann_id, title, ticker or "", url)
            if not is_first_run:
                alerts.append({
                    "exchange": "Binance",
                    "title":    title,
                    "ticker":   ticker,
                    "url":      url,
                    "type":     "announcement",
                })
        if is_first_run and items:
            print(f"[Binance] baseline saved", end=" ")
    except Exception as e:
        print(f"[Binance] Error: {e}")
    return alerts


def scan_bybit(db, dry_run: bool) -> list[dict]:
    """Bybit announcements API."""
    alerts = []
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(
                "https://announcements.bybit.com/api/v1/announcements",
                params={"locale": "en-US", "category": "new_crypto",
                        "page": "1", "limit": "15"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        items = r.json().get("result", {}).get("list", [])
        for item in items:
            ann_id = f"bybit_{item.get('id', '')}"
            title  = item.get("title", "")
            url    = item.get("url", "https://announcements.bybit.com")

            if not title or is_seen(db, ann_id):
                continue

            ticker = extract_ticker(title)
            mark_seen(db, "Bybit", ann_id, title, ticker or "", url)
            alerts.append({
                "exchange": "Bybit",
                "title":    title,
                "ticker":   ticker,
                "url":      url,
                "type":     "announcement",
            })
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
    """Upbit (Korea) — new KRW markets. Upbit listings often = biggest pumps."""
    alerts = []
    is_first_run = not exchange_initialized(db, "Upbit")
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get("https://api.upbit.com/v1/market/all",
                      headers={"User-Agent": "Mozilla/5.0"})
        markets = r.json()
        krw = [m for m in markets if m.get("market", "").startswith("KRW-")]
        new_count = 0
        for m in krw:
            ticker = m.get("market", "").replace("KRW-", "")
            if ticker in IGNORE_TICKERS:
                continue
            ann_id = f"upbit_{ticker}"
            if is_seen(db, ann_id):
                continue

            name = m.get("korean_name", ticker)
            url  = f"https://upbit.com/exchange?code=CRIX.UPBIT.KRW-{ticker}"
            mark_seen(db, "Upbit", ann_id, f"Upbit KRW listing: {ticker} ({name})",
                      ticker, url, "live")
            new_count += 1

            # First run = baseline only, no spam
            if not is_first_run:
                alerts.append({
                    "exchange": "Upbit",
                    "title":    f"Upbit KRW: {ticker} ({name})",
                    "ticker":   ticker,
                    "url":      url,
                    "type":     "live",
                })
        if is_first_run:
            print(f"[Upbit] baseline saved ({new_count} tokens)", end=" ")
    except Exception as e:
        print(f"[Upbit] Error: {e}")
    return alerts


def scan_okx(db, dry_run: bool) -> list[dict]:
    """OKX announcement feed."""
    alerts = []
    try:
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(
                "https://www.okx.com/v2/support/home/web",
                params={"category": "New Listings", "limit": "10"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
        items = r.json().get("data", {}).get("lists", [])
        for item in items:
            ann_id = f"okx_{item.get('pCode', item.get('id', ''))}"
            title  = item.get("title", "")
            url    = f"https://www.okx.com/support/hc/en-us/articles/{item.get('pCode', '')}"

            if not title or is_seen(db, ann_id):
                continue
            if not any(kw in title.lower() for kw in
                       ["list", "adds", "new", "spot"]):
                continue

            ticker = extract_ticker(title)
            mark_seen(db, "OKX", ann_id, title, ticker or "", url)
            alerts.append({
                "exchange": "OKX",
                "title":    title,
                "ticker":   ticker,
                "url":      url,
                "type":     "announcement",
            })
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

def run_once(dry_run: bool) -> int:
    ts  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db  = _get_db()
    all_alerts = []

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
            alerts = scanner_fn(db, dry_run)
            if alerts:
                print(f"{name}:{len(alerts)}", end=" ", flush=True)
            all_alerts.extend(alerts)
        except Exception as e:
            print(f"{name}:ERR({e})", end=" ", flush=True)

    print(f"| Total new: {len(all_alerts)}")

    for alert in all_alerts:
        msg = format_listing_alert(alert, ts)
        send_telegram(msg, dry_run=dry_run)
        print(f"  → {alert['exchange']} {alert.get('ticker','?')} [{alert['type']}]")

    return len(all_alerts)


def main() -> None:
    p = argparse.ArgumentParser(description="New Listings Scanner — exchange announcements")
    p.add_argument("--interval", type=int, default=1800,
                   help="Scan interval seconds (default: 1800 = 30min)")
    p.add_argument("--daemon",   action="store_true",
                   help="Run forever")
    p.add_argument("--dry-run",  action="store_true",
                   help="Print alerts, don't send Telegram")
    args = p.parse_args()

    if args.daemon:
        print(f"Listings Scanner daemon — interval: {args.interval}s | "
              f"Telegram: {'DRY-RUN' if args.dry_run else 'LIVE'}")
        while True:
            run_once(args.dry_run)
            print(f"Sleeping {args.interval}s ({args.interval//60}min)...")
            time.sleep(args.interval)
    else:
        run_once(args.dry_run)


if __name__ == "__main__":
    main()
