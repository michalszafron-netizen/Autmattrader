"""Token Dashboard — unified per-token view (price, trend, smart money, OI, sentiment, catalyst).

Inspired by All-In Pro tile-based watchlist.
Combines all data sources into one beautiful per-token card.

Usage:
    python scripts/token_dashboard.py                       # default tokens
    python scripts/token_dashboard.py --coins BTC ETH HYPE  # custom
    python scripts/token_dashboard.py --brief               # 1 line per coin
    python scripts/token_dashboard.py --json                # for dashboard
    python scripts/token_dashboard.py --save                # to SQLite

Composite score (0-10):
    Trend alignment (3 timeframes)  → 0-3
    Smart money bias clarity        → 0-2
    OI trend + price action         → 0-2
    Funding rate neutrality         → 0-1
    X sentiment                     → 0-2
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv(Path(__file__).parent.parent / ".env")

# Force UTF-8 stdout on Windows — fixes rich Unicode rendering crash
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_SSL    = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
console = Console(force_terminal=True, legacy_windows=False)
HL_API  = "https://api.hyperliquid.xyz"

DEFAULT_COINS = ["BTC", "ETH", "SOL", "HYPE", "LINK"]

# Smart Money fetch ONLY for these coins — others get "brak" to keep runtime <3 min
# Add TradFi tickers here if they appear in HL whale positions
SM_COINS = {"BTC", "ETH", "SOL", "LINK"}


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class TokenData:
    coin:          str
    price:         float | None = None
    change_24h:    float | None = None
    change_7d:     float | None = None
    change_30d:    float | None = None
    vs_btc_24h:    float | None = None
    trend_h4:      str = "?"
    trend_h1:      str = "?"
    trend_m15:     str = "?"
    sm_count:      int = 0
    sm_long_pct:   float | None = None
    sm_short_pct:  float | None = None
    sm_net_usd:    float | None = None
    whale_avg_long:  float | None = None
    whale_avg_short: float | None = None
    oi_total_usd:  float | None = None
    oi_change_1h:  float | None = None
    funding_rate:  float | None = None
    sentiment_score: int | None = None
    composite_score: float = 0.0
    catalysts:     list[str] = field(default_factory=list)


# ── HL data fetchers ─────────────────────────────────────────────────────────

def _hl_post(payload: dict) -> Any:
    with httpx.Client(verify=_SSL, timeout=8) as c:
        r = c.post(f"{HL_API}/info", json=payload)
        r.raise_for_status()
        return r.json()


def fetch_hl_prices() -> dict[str, float]:
    """One call — all HL mid prices."""
    try:
        data = _hl_post({"type": "allMids"})
        return {k: float(v) for k, v in data.items() if v}
    except Exception:
        return {}


def fetch_hl_candles(coin: str, interval: str = "1h", lookback_hours: int = 48) -> list[dict]:
    """Fetch OHLCV candles for trend computation."""
    try:
        end_ts   = int(time.time() * 1000)
        start_ts = end_ts - (lookback_hours * 3600 * 1000)
        data = _hl_post({
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval,
                    "startTime": start_ts, "endTime": end_ts},
        })
        return data if isinstance(data, list) else []
    except Exception:
        return []


def compute_trend(candles: list[dict]) -> str:
    """Determine trend from candles: 'up', 'down', or 'flat'.

    Method: compare last close to close 10 periods ago + check direction of last 3 candles.
    """
    if len(candles) < 10:
        return "?"
    try:
        last_close = float(candles[-1].get("c", 0))
        prev_close = float(candles[-10].get("c", 0))
        if prev_close == 0:
            return "?"
        change_pct = (last_close - prev_close) / prev_close * 100

        # Recent direction
        recent_greens = sum(
            1 for c in candles[-3:]
            if float(c.get("c", 0)) >= float(c.get("o", 0))
        )

        if change_pct > 1.5 and recent_greens >= 2:
            return "up"
        if change_pct < -1.5 and recent_greens <= 1:
            return "down"
        return "flat"
    except Exception:
        return "?"


def fetch_price_changes(coin: str, current_price: float) -> dict:
    """Compute 24h/7d/30d changes from daily candles."""
    try:
        candles = fetch_hl_candles(coin, interval="1d", lookback_hours=24 * 35)
        if not candles or current_price == 0:
            return {}

        def pct_change(idx_back: int) -> float | None:
            if len(candles) < idx_back + 1:
                return None
            old = float(candles[-(idx_back + 1)].get("c", 0))
            return ((current_price - old) / old * 100) if old else None

        return {
            "change_24h": pct_change(1),
            "change_7d":  pct_change(7),
            "change_30d": pct_change(30),
        }
    except Exception:
        return {}


def fetch_smart_money_for_coin(coin: str, top_n: int = 20) -> dict:
    """Aggregate positions on this coin from top N HL traders."""
    try:
        # Fetch leaderboard
        with httpx.Client(verify=_SSL, timeout=12) as c:
            r = c.get(
                "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard",
                timeout=10,
            )
        rows = r.json().get("leaderboardRows", [])

        # Sort by weekly pnl
        def perf_pnl(row: dict) -> Decimal:
            for p in row.get("windowPerformances", []):
                if p[0] == "week":
                    try:
                        return Decimal(p[1].get("pnl", "0"))
                    except Exception:
                        return Decimal(0)
            return Decimal(0)

        top = sorted(rows, key=perf_pnl, reverse=True)[:top_n]
        wallets = [r.get("ethAddress", "") for r in top if r.get("ethAddress")]

        long_count   = 0
        short_count  = 0
        long_total   = 0.0
        short_total  = 0.0
        long_entries:  list[tuple[float, float]] = []  # (entry, size_usd)
        short_entries: list[tuple[float, float]] = []

        def fetch_one(w: str) -> dict:
            try:
                return _hl_post({"type": "clearinghouseState", "user": w})
            except Exception:
                return {}

        with ThreadPoolExecutor(max_workers=10) as pool:
            for state in pool.map(fetch_one, wallets):
                for pos_wrap in state.get("assetPositions", []):
                    pos = pos_wrap.get("position", {})
                    if pos.get("coin", "").upper() != coin.upper():
                        continue
                    try:
                        szi = float(pos.get("szi", "0"))
                        if szi == 0:
                            continue
                        entry = float(pos.get("entryPx", "0"))
                        notional = abs(szi) * entry
                        if szi > 0:
                            long_count += 1
                            long_total += notional
                            long_entries.append((entry, notional))
                        else:
                            short_count += 1
                            short_total += notional
                            short_entries.append((entry, notional))
                    except Exception:
                        pass

        total_count = long_count + short_count
        if total_count == 0:
            return {"count": 0}

        def weighted_avg(entries: list[tuple[float, float]]) -> float | None:
            total_size = sum(e[1] for e in entries)
            if total_size == 0:
                return None
            return sum(e[0] * e[1] for e in entries) / total_size

        return {
            "count":       total_count,
            "long_pct":    long_count / total_count * 100,
            "short_pct":   short_count / total_count * 100,
            "net_usd":     long_total - short_total,
            "avg_long":    weighted_avg(long_entries),
            "avg_short":   weighted_avg(short_entries),
        }
    except Exception:
        return {"count": 0}


# ── Binance/Bybit OI (lekkie — bez duplikacji oi_tracker.py) ─────────────────

def fetch_oi_funding(coin: str) -> dict:
    """OI from Binance + Bybit + Extended summed."""
    sym = f"{coin}USDT"
    oi_total = 0.0
    funding_vals = []
    oi_1h_change = None

    try:
        with httpx.Client(verify=_SSL, timeout=6) as c:
            # Binance OI
            r1 = c.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}")
            r2 = c.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}")
            if r1.status_code == 200 and r2.status_code == 200:
                bnb_oi  = float(r1.json().get("openInterest", 0))
                bnb_px  = float(r2.json().get("markPrice", 0))
                oi_total += bnb_oi * bnb_px
                funding_vals.append(float(r2.json().get("lastFundingRate", 0)))

            # Binance OI history for 1h change
            r3 = c.get(
                "https://fapi.binance.com/futures/data/openInterestHist",
                params={"symbol": sym, "period": "5m", "limit": 13},
            )
            if r3.status_code == 200:
                hist = r3.json()
                if len(hist) >= 2:
                    latest = float(hist[-1].get("sumOpenInterestValue", 0))
                    hour_ago = float(hist[0].get("sumOpenInterestValue", 0))
                    if hour_ago > 0:
                        oi_1h_change = (latest - hour_ago) / hour_ago * 100

            # Bybit
            r4 = c.get(
                "https://api.bybit.com/v5/market/open-interest",
                params={"category": "linear", "symbol": sym,
                        "intervalTime": "1h", "limit": 1},
            )
            r5 = c.get(
                "https://api.bybit.com/v5/market/tickers",
                params={"category": "linear", "symbol": sym},
            )
            if r4.status_code == 200 and r5.status_code == 200:
                oi_list = r4.json().get("result", {}).get("list", [])
                tk_list = r5.json().get("result", {}).get("list", [])
                if oi_list and tk_list:
                    bbt_oi = float(oi_list[0].get("openInterest", 0))
                    bbt_px = float(tk_list[0].get("markPrice", 0))
                    oi_total += bbt_oi * bbt_px
                    funding_vals.append(float(tk_list[0].get("fundingRate", 0)))
    except Exception:
        pass

    return {
        "oi_total":     oi_total or None,
        "oi_change_1h": oi_1h_change,
        "funding":      sum(funding_vals) / len(funding_vals) if funding_vals else None,
    }


# ── Catalyst feed (from DB) ──────────────────────────────────────────────────

def fetch_catalysts(coin: str, days: int = 7) -> list[str]:
    """Extract catalyst events for this coin from SQLite (trending_tokens + daily_briefs)."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()

        # Recent trending mentions
        rows = db._sqlite.query(
            f"""SELECT date, ticker, top_post_likes, raw_json
                FROM trending_tokens
                WHERE date >= date('now', '-{days} days')
                AND UPPER(ticker) = ?
                ORDER BY ts DESC LIMIT 3""",
            (coin.upper(),),
        )
        catalysts = []
        for r in rows:
            try:
                d = json.loads(r["raw_json"]) if r["raw_json"] else {}
                why = d.get("why_trending", "")
                if why:
                    catalysts.append(f"{r['date']}: {why[:80]}")
            except Exception:
                pass
        return catalysts[:3]
    except Exception:
        return []


# ── Sentiment (from DB or default) ───────────────────────────────────────────

def fetch_sentiment(coin: str) -> int | None:
    """Most recent X sentiment score for this coin from DB (1-10 → 0-100)."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()
        rows = db._sqlite.query(
            "SELECT score FROM x_sentiment WHERE coin = ? ORDER BY ts DESC LIMIT 1",
            (coin.upper(),),
        )
        if rows and rows[0].get("score") is not None:
            score = rows[0]["score"]
            return int(score * 10) if score <= 10 else int(score)
    except Exception:
        pass
    return None


# ── Composite scoring ────────────────────────────────────────────────────────

def composite_score(d: TokenData) -> float:
    """Combine all signals into 0-10 score. Higher = stronger bullish bias."""
    score = 0.0

    # 1. Trend alignment (0-3 pts)
    trends = [d.trend_h4, d.trend_h1, d.trend_m15]
    ups    = sum(1 for t in trends if t == "up")
    downs  = sum(1 for t in trends if t == "down")
    if ups == 3:    score += 3
    elif ups == 2:  score += 2
    elif ups == 1 and downs == 0: score += 1
    elif downs == 3: score -= 1  # all bearish = penalty
    # mixed → 0

    # 2. Smart money clarity (0-2 pts)
    if d.sm_long_pct is not None:
        if d.sm_long_pct >= 70:    score += 2
        elif d.sm_long_pct >= 60:  score += 1
        elif d.sm_short_pct and d.sm_short_pct >= 70: score -= 1

    # 3. OI + price action (0-2 pts)
    if d.oi_change_1h is not None and d.change_24h is not None:
        if d.oi_change_1h > 1 and d.change_24h > 0:
            score += 2  # strong trend (new money + price up)
        elif d.oi_change_1h < -3 and d.change_24h < 0:
            score += 1  # capitulation, possible bottom
        elif d.oi_change_1h > 5 and d.change_24h < -2:
            score -= 1  # shorts piling on

    # 4. Funding (0-1 pt)
    if d.funding_rate is not None:
        # Mild positive (0-0.01%) = healthy trend; extreme = contrarian
        if 0 < d.funding_rate < 0.0001:
            score += 1
        elif abs(d.funding_rate) > 0.001:
            score -= 0.5  # crowded, vulnerable

    # 5. Sentiment (0-2 pts)
    if d.sentiment_score is not None:
        if d.sentiment_score >= 70:    score += 2
        elif d.sentiment_score >= 50:  score += 1
        elif d.sentiment_score <= 20:  score -= 1

    # Clamp to 0-10
    return max(0.0, min(10.0, round(score + 5, 1)))  # baseline 5, range 0-10


# ── Main fetch ───────────────────────────────────────────────────────────────

def fetch_all_for_coin(coin: str, mids: dict[str, float]) -> TokenData:
    d = TokenData(coin=coin)
    d.price = mids.get(coin)

    if not d.price:
        return d

    # Parallelize independent calls
    # Smart Money only for key coins — skip others to keep runtime fast
    run_sm = coin.upper() in SM_COINS

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_changes  = pool.submit(fetch_price_changes, coin, d.price)
        f_candles4 = pool.submit(fetch_hl_candles, coin, "4h", 48)
        f_candles1 = pool.submit(fetch_hl_candles, coin, "1h", 24)
        f_candles15= pool.submit(fetch_hl_candles, coin, "15m", 6)
        f_oi       = pool.submit(fetch_oi_funding, coin)
        f_sm       = pool.submit(fetch_smart_money_for_coin, coin) if run_sm else None

        changes = f_changes.result()
        d.change_24h = changes.get("change_24h")
        d.change_7d  = changes.get("change_7d")
        d.change_30d = changes.get("change_30d")

        d.trend_h4  = compute_trend(f_candles4.result())
        d.trend_h1  = compute_trend(f_candles1.result())
        d.trend_m15 = compute_trend(f_candles15.result())

        oi = f_oi.result()
        d.oi_total_usd = oi.get("oi_total")
        d.oi_change_1h = oi.get("oi_change_1h")
        d.funding_rate = oi.get("funding")

        sm = f_sm.result() if f_sm else {"count": 0}
        d.sm_count       = sm.get("count", 0)
        d.sm_long_pct    = sm.get("long_pct")
        d.sm_short_pct   = sm.get("short_pct")
        d.sm_net_usd     = sm.get("net_usd")
        d.whale_avg_long  = sm.get("avg_long")
        d.whale_avg_short = sm.get("avg_short")

    # Compute vs BTC change (run after parallel block)
    btc_24h = None
    if coin != "BTC" and "BTC" in mids:
        try:
            btc_changes = fetch_price_changes("BTC", mids["BTC"])
            btc_24h = btc_changes.get("change_24h")
        except Exception:
            pass
    if btc_24h is not None and d.change_24h is not None:
        d.vs_btc_24h = d.change_24h - btc_24h

    d.sentiment_score = fetch_sentiment(coin)
    d.catalysts       = fetch_catalysts(coin)
    d.composite_score = composite_score(d)
    return d


# ── Display helpers ──────────────────────────────────────────────────────────

def _arrow(trend: str) -> str:
    return {"up": "[green]↑[/green]", "down": "[red]↓[/red]",
            "flat": "[yellow]→[/yellow]"}.get(trend, "[dim]?[/dim]")


def _pct(v: float | None, plus_color: bool = True) -> str:
    if v is None:
        return "[dim]—[/dim]"
    if plus_color:
        color = "green" if v >= 0 else "red"
        return f"[{color}]{v:+.2f}%[/{color}]"
    return f"{v:+.2f}%"


def _money(v: float | None) -> str:
    if v is None or v == 0:
        return "—"
    if abs(v) >= 1e9:  return f"${v/1e9:.2f}B"
    if abs(v) >= 1e6:  return f"${v/1e6:.1f}M"
    if abs(v) >= 1e3:  return f"${v/1e3:.0f}K"
    return f"${v:.2f}"


def _price(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1000:  return f"${v:,.2f}"
    if v >= 1:     return f"${v:.3f}"
    return f"${v:.6f}"


def _score_bar(score: float) -> str:
    """Visual bar 0-10."""
    filled = int(score)
    if score >= 7.5:    color = "green"
    elif score >= 5:    color = "yellow"
    else:               color = "red"
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{color}]{bar} {score}/10[/{color}]"


def render_tile(d: TokenData) -> Panel:
    title = f"[bold cyan]{d.coin}[/bold cyan]  {_price(d.price)}"
    if d.vs_btc_24h is not None:
        title += f"  [dim]vs BTC: {_pct(d.vs_btc_24h, False)}[/dim]"

    # Changes line
    changes_line = (
        f"[bold]1D[/bold]: {_pct(d.change_24h)}   "
        f"[bold]7D[/bold]: {_pct(d.change_7d)}   "
        f"[bold]30D[/bold]: {_pct(d.change_30d)}"
    )

    # Trend
    trend_line = (
        f"[bold]Trend:[/bold]      H4 {_arrow(d.trend_h4)}  "
        f"H1 {_arrow(d.trend_h1)}  M15 {_arrow(d.trend_m15)}"
    )

    # Smart money
    if d.sm_count > 0 and d.sm_long_pct is not None:
        lpct = d.sm_long_pct
        spct = d.sm_short_pct or (100 - lpct)
        lc = "green" if lpct > 60 else "yellow"
        sc = "red" if spct > 60 else "yellow"
        sm_line = (
            f"[bold]Smart Money:[/bold] {d.sm_count} pozycji  "
            f"[{lc}]{lpct:.0f}% LONG[/{lc}] / [{sc}]{spct:.0f}% SHORT[/{sc}]"
        )
    else:
        sm_line = "[bold]Smart Money:[/bold] [dim]brak danych[/dim]"

    # Whale avg
    whale_line = "[bold]Whale avg:[/bold]"
    if d.whale_avg_long:
        diff = (d.whale_avg_long - d.price) / d.price * 100 if d.price else 0
        whale_line += f"   L {_price(d.whale_avg_long)} ({_pct(diff, False)})"
    if d.whale_avg_short:
        diff = (d.whale_avg_short - d.price) / d.price * 100 if d.price else 0
        whale_line += f"   S {_price(d.whale_avg_short)} ({_pct(diff, False)})"
    if not d.whale_avg_long and not d.whale_avg_short:
        whale_line = "[bold]Whale avg:[/bold]  [dim]brak pozycji[/dim]"

    # OI + funding
    oi_line = f"[bold]OI:[/bold]         {_money(d.oi_total_usd)}"
    if d.oi_change_1h is not None:
        oi_line += f"   1h: {_pct(d.oi_change_1h)}"

    fund_line = "[bold]Funding:[/bold]    "
    if d.funding_rate is not None:
        fp = d.funding_rate * 100
        fc = "green" if abs(fp) < 0.005 else "yellow" if abs(fp) < 0.02 else "red"
        fund_line += f"[{fc}]{fp:+.4f}%[/{fc}]"
    else:
        fund_line += "[dim]—[/dim]"

    # Sentiment
    if d.sentiment_score is not None:
        s = d.sentiment_score
        sc = "green" if s >= 60 else "yellow" if s >= 40 else "red"
        sent_line = f"[bold]Sentiment:[/bold]  [{sc}]{s}/100[/{sc}]"
    else:
        sent_line = "[bold]Sentiment:[/bold]  [dim]brak[/dim]"

    # Composite
    comp_line = f"[bold]Composite:[/bold]  {_score_bar(d.composite_score)}"

    # Catalysts
    cat_line = ""
    if d.catalysts:
        cat_line = "\n[bold]Catalyst 7d:[/bold]\n"
        for c in d.catalysts:
            cat_line += f"  • [dim]{c}[/dim]\n"

    body = (
        f"{changes_line}\n"
        f"{'─' * 56}\n"
        f"{trend_line}\n"
        f"{sm_line}\n"
        f"{whale_line}\n"
        f"{oi_line}\n"
        f"{fund_line}\n"
        f"{sent_line}\n"
        f"{comp_line}"
        f"{cat_line}"
    )
    return Panel(body, title=title, expand=False, padding=(0, 1))


def display_brief(tokens: list[TokenData]) -> None:
    """Compact one-liner per token for daily-alpha."""
    print("\nToken Dashboard:")
    for d in tokens:
        sm = f"{d.sm_long_pct:.0f}%L" if d.sm_long_pct else "—"
        trend = f"{d.trend_h4[0].upper()}{d.trend_h1[0].upper()}{d.trend_m15[0].upper()}"
        print(
            f"  {d.coin:<6} {_price(d.price):>10}  "
            f"24h {_pct(d.change_24h, False):>8}  "
            f"Trend {trend}  SM {sm:<4}  "
            f"OI {_money(d.oi_total_usd):>7}  "
            f"Score {d.composite_score}/10"
        )


def display_json(tokens: list[TokenData]) -> None:
    out = [asdict(d) for d in tokens]
    print(json.dumps(out, indent=2, default=str))


# ── DB save ──────────────────────────────────────────────────────────────────

def save_snapshots(tokens: list[TokenData]) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for d in tokens:
            try:
                db._sqlite.execute(
                    """INSERT OR IGNORE INTO token_snapshots
                       (ts, coin, price, change_24h, trend_h4, trend_h1, trend_m15,
                        sm_long_pct, sm_short_pct, oi_total_usd, oi_change_1h,
                        funding_rate, sentiment_score, composite_score)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ts, d.coin, d.price, d.change_24h, d.trend_h4, d.trend_h1,
                     d.trend_m15, d.sm_long_pct, d.sm_short_pct, d.oi_total_usd,
                     d.oi_change_1h, d.funding_rate, d.sentiment_score,
                     d.composite_score),
                )
            except Exception as ex:
                console.print(f"[dim]DB write skipped for {d.coin}: {ex}[/dim]")
    except Exception as ex:
        console.print(f"[dim]DB unavailable: {ex}[/dim]")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Token Dashboard — unified per-token view")
    p.add_argument("--coins", nargs="+", metavar="COIN", help="Filter tokens")
    p.add_argument("--brief", action="store_true", help="One-liner per coin")
    p.add_argument("--json",  action="store_true", help="JSON output")
    p.add_argument("--save",  action="store_true", help="Save to SQLite")
    args = p.parse_args()

    coins = [c.upper() for c in args.coins] if args.coins else DEFAULT_COINS

    console.print(f"[dim]Fetching data for {', '.join(coins)}...[/dim]")
    mids = fetch_hl_prices()

    tokens: list[TokenData] = []
    for coin in coins:
        try:
            t = fetch_all_for_coin(coin, mids)
            tokens.append(t)
        except Exception as ex:
            console.print(f"[red]Error for {coin}: {ex}[/red]")

    if args.json:
        display_json(tokens)
    elif args.brief:
        display_brief(tokens)
    else:
        try:
            from tz_utils import fmt_both
            ts = fmt_both(datetime.now(timezone.utc))
        except Exception:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        console.print(f"\n[bold]Token Dashboard[/bold] — [dim]{ts}[/dim]\n")
        for t in tokens:
            console.print(render_tile(t))

    if args.save:
        save_snapshots(tokens)


if __name__ == "__main__":
    main()
