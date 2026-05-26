"""Stock Research Module — full fundamental + technical + news analysis.

Data sources:
  US stocks  — yfinance (Yahoo Finance): price, fundamentals, news,
               options, insiders, analyst recommendations, short interest
  PL stocks  — yfinance .WA suffix (Warsaw Stock Exchange): same as above
               + Stooq.pl CSV for richer price history (needs STOOQ_API_KEY in .env)

Subcommands:
  research TICKER [TICKER ...]    full analysis (price + tech + fundamentals + news)
  news     TICKER [--days N]      news + sentiment digest only
  screen   [--type shorts|momentum|breakout]  scan top US/PL stocks for setups

Auto-detection:
  Plain ticker (e.g. NVDA, AAPL)  → treated as US
  3-5 char ticker not found on US exchange → retried as TICKER.WA (Polish)
  Explicit: PKN.WA, CDR.WA or --pl flag forces Polish lookup

Usage:
  python scripts/stock_research.py research NVDA
  python scripts/stock_research.py research PKN.WA        # Orlen
  python scripts/stock_research.py research NVDA PKN.WA   # both in one run
  python scripts/stock_research.py news TSLA --days 14
  python scripts/stock_research.py screen --type shorts
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import requests
import truststore
import urllib3
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Fix SSL on Windows: inject truststore into Python's ssl module (affects httpx)
try:
    truststore.inject_into_ssl()
except Exception:
    pass

# yfinance 1.x uses curl_cffi which ignores Python ssl. Fix: pass requests.Session
# with SSL verification disabled (corp proxy cert) + browser User-Agent for Yahoo crumb.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_YF_SESSION = requests.Session()
_YF_SESSION.verify = False
_YF_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

_SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
console = Console()


def _ticker(symbol: str) -> yf.Ticker:
    """Create a yfinance Ticker with our SSL-fixed requests session."""
    return yf.Ticker(symbol, session=_YF_SESSION)

STOOQ_API_KEY  = os.getenv("STOOQ_API_KEY", "")
STOOQ_BASE     = "https://stooq.com/q/d/l/"

# Warsaw Stock Exchange exchange codes returned by yfinance
WARSAW_CODES   = {"WAR", "WAR2", "WBA", "WSE"}

# Polish tickers the user might type without .WA suffix — common ones
KNOWN_PL_TICKERS = {
    "PKN", "PKO", "CDR", "KGH", "PZU", "ALE", "LPP", "DNP", "PCO",
    "JSW", "MBK", "SPL", "TPE", "OPL", "CCC", "EUR", "CAR", "GNB",
    "MGT", "KRU", "AMB", "BDX", "PEO", "AGO",
}


# ── Ticker resolution ─────────────────────────────────────────────────────────

def resolve_ticker(raw: str) -> tuple[str, str]:
    """Return (yf_symbol, market) where market is 'us' or 'pl'.

    Logic:
      1. Explicit .WA or .PL suffix → always Polish.
      2. Matches KNOWN_PL_TICKERS list → try .WA first.
      3. Otherwise assume US; if fast_info.exchange is Warsaw → mark as PL.
    """
    raw = raw.upper().strip()

    if raw.endswith(".WA"):
        return raw, "pl"
    if raw.endswith(".PL"):
        return raw.replace(".PL", ".WA"), "pl"

    # Known Polish ticker typed without suffix
    if raw in KNOWN_PL_TICKERS:
        return f"{raw}.WA", "pl"

    # Try as US ticker first
    try:
        fi = _ticker(raw).fast_info
        ex = getattr(fi, "exchange", "") or ""
        if ex in WARSAW_CODES:
            return f"{raw}.WA", "pl"
        if ex:
            return raw, "us"
    except Exception:
        pass

    # If short ticker with no US exchange found → try .WA
    if len(raw) <= 5:
        try:
            fi = _ticker(f"{raw}.WA").fast_info
            ex = getattr(fi, "exchange", "") or ""
            if ex:
                return f"{raw}.WA", "pl"
        except Exception:
            pass

    return raw, "us"


# ── Data fetchers ─────────────────────────────────────────────────────────────

def fetch_yf(yf_symbol: str) -> tuple[dict, pd.DataFrame]:
    """Return (info_dict, history_1y_df). Both may be empty on failure."""
    t = _ticker(yf_symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    try:
        hist = t.history(period="1y", auto_adjust=True)
    except Exception:
        hist = pd.DataFrame()
    return info, hist


def fetch_stooq_history(pl_symbol: str) -> pd.DataFrame | None:
    """Fetch Stooq.pl historical OHLCV for a Polish ticker.
    Requires STOOQ_API_KEY in .env. Returns None if key missing or request fails.
    """
    if not STOOQ_API_KEY:
        return None
    stooq_sym = pl_symbol.upper().replace(".WA", ".PL").replace(".pl", ".PL")
    if not stooq_sym.endswith(".PL"):
        stooq_sym += ".PL"
    url = f"{STOOQ_BASE}?s={stooq_sym}&i=d&apikey={STOOQ_API_KEY}"
    try:
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.get(url)
            r.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        df.columns = [col.lower() for col in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df.tail(365)
    except Exception as e:
        console.print(f"[dim][Stooq] {e}[/dim]")
        return None


# ── Technical analysis ────────────────────────────────────────────────────────

def compute_technicals(hist: pd.DataFrame) -> dict:
    """Compute RSI(14), ATR(14), SMA(20/50/200), volume ratio from OHLCV df."""
    if hist.empty or len(hist) < 20:
        return {}

    c = hist["Close"]
    h = hist["High"]
    lo = hist["Low"]
    v  = hist["Volume"]

    # RSI(14)
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

    # ATR(14)
    prev_c = c.shift(1)
    tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    atr_pct = atr / float(c.iloc[-1]) * 100 if float(c.iloc[-1]) > 0 else 0

    # SMAs
    def sma(n: int) -> float | None:
        if len(c) >= n:
            return float(c.rolling(n).mean().iloc[-1])
        return None

    sma20  = sma(20)
    sma50  = sma(50)
    sma200 = sma(200)

    # Volume ratio (last close vs 30d avg)
    vol_avg30 = float(v.tail(30).mean()) if len(v) >= 10 else 0
    vol_ratio = float(v.iloc[-1]) / vol_avg30 if vol_avg30 > 0 else 1.0

    # 52W high/low
    w52_high = float(c.tail(252).max())
    w52_low  = float(c.tail(252).min())
    price    = float(c.iloc[-1])
    dist_ath = (price - w52_high) / w52_high * 100  # negative = below ATH
    dist_atl = (price - w52_low)  / w52_low  * 100  # positive = above ATL

    # Trend (price vs MAs)
    above_sma50  = price > sma50  if sma50  else None
    above_sma200 = price > sma200 if sma200 else None

    return {
        "rsi": round(rsi, 1),
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct, 2),
        "sma20": round(sma20, 4)  if sma20  else None,
        "sma50": round(sma50, 4)  if sma50  else None,
        "sma200": round(sma200, 4) if sma200 else None,
        "vol_ratio": round(vol_ratio, 2),
        "w52_high": round(w52_high, 4),
        "w52_low":  round(w52_low, 4),
        "dist_ath_pct": round(dist_ath, 1),
        "dist_atl_pct": round(dist_atl, 1),
        "above_sma50":  above_sma50,
        "above_sma200": above_sma200,
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_num(v, prefix="$", decimals=2) -> str:
    if v is None:
        return "—"
    try:
        v = float(v)
        if abs(v) >= 1e12: return f"{prefix}{v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"{prefix}{v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"{prefix}{v/1e6:.2f}M"
        if abs(v) >= 1e3:  return f"{prefix}{v/1e3:.1f}K"
        return f"{prefix}{v:.{decimals}f}"
    except Exception:
        return str(v)


def _pct(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "—"


def _rsi_color(rsi: float | None) -> str:
    if rsi is None:
        return "white"
    if rsi >= 70:
        return "red"
    if rsi <= 30:
        return "green"
    return "yellow"


def _trend_label(above50: bool | None, above200: bool | None) -> str:
    if above50 is None or above200 is None:
        return "[dim]N/A[/dim]"
    if above50 and above200:
        return "[bold green]BULL (>SMA50 >SMA200)[/bold green]"
    if above200 and not above50:
        return "[yellow]PULLBACK (>SMA200 <SMA50)[/yellow]"
    if above50 and not above200:
        return "[yellow]RECOVERY (<SMA200 >SMA50)[/yellow]"
    return "[bold red]BEAR (<SMA50 <SMA200)[/bold red]"


# ── Research command ──────────────────────────────────────────────────────────

def _research_one(raw: str) -> None:
    yf_sym, market = resolve_ticker(raw)
    label = "🇵🇱 GPW" if market == "pl" else "🇺🇸 US"
    console.print(f"\n[bold cyan]{yf_sym}[/bold cyan]  [{label}]  fetching…")

    info, hist = fetch_yf(yf_sym)

    # For PL: try Stooq if API key available (richer history)
    if market == "pl" and STOOQ_API_KEY:
        stooq_hist = fetch_stooq_history(yf_sym)
        if stooq_hist is not None and len(stooq_hist) > len(hist):
            hist = stooq_hist
            console.print("[dim]  (price history from Stooq.pl)[/dim]")

    tech = compute_technicals(hist)

    name     = info.get("longName") or info.get("shortName") or yf_sym
    currency = info.get("currency", "USD")
    price    = info.get("currentPrice") or info.get("regularMarketPrice") or (
        float(hist["Close"].iloc[-1]) if not hist.empty else None
    )

    # Daily % change — compute from last 2 history bars (more reliable than info fields)
    chg_pct = None
    if not hist.empty and len(hist) >= 2:
        last_c = float(hist["Close"].iloc[-1])
        prev_c = float(hist["Close"].iloc[-2])
        if prev_c > 0:
            chg_pct = (last_c - prev_c) / prev_c * 100

    # ── HEADER ────────────────────────────────────────────────────────────────
    header = Text()
    header.append(f"{name}  ", style="bold white")
    header.append(f"({yf_sym}) ", style="dim")
    if price:
        header.append(f"{currency} {price:,.4f}", style="bold green")
    if chg_pct is not None:
        col = "green" if chg_pct >= 0 else "red"
        header.append(f"  {chg_pct:+.2f}% today", style=col)
    console.print(Panel(header, expand=False))

    # ── PRICE TABLE ───────────────────────────────────────────────────────────
    pt = Table(title="Price & Volume", show_header=True)
    pt.add_column("52W High")
    pt.add_column("52W Low")
    pt.add_column("vs ATH")
    pt.add_column("vs ATL")
    pt.add_column("Volume")
    pt.add_column("Avg30d Vol")
    pt.add_column("Vol Ratio")

    v52h = tech.get("w52_high") or info.get("fiftyTwoWeekHigh")
    v52l = tech.get("w52_low")  or info.get("fiftyTwoWeekLow")
    avg_vol = info.get("averageVolume") or info.get("averageDailyVolume10Day")
    cur_vol = info.get("volume") or info.get("regularMarketVolume")
    vol_ratio = tech.get("vol_ratio", 1.0)
    vr_col = "green" if vol_ratio >= 2 else "yellow" if vol_ratio >= 1.3 else "white"

    pt.add_row(
        f"${v52h:,.2f}" if v52h else "—",
        f"${v52l:,.2f}" if v52l else "—",
        f"[red]{tech.get('dist_ath_pct', 0):+.1f}%[/red]" if tech else "—",
        f"[green]{tech.get('dist_atl_pct', 0):+.1f}%[/green]" if tech else "—",
        _fmt_num(cur_vol, prefix=""),
        _fmt_num(avg_vol, prefix=""),
        f"[{vr_col}]{vol_ratio:.2f}x[/{vr_col}]" if tech else "—",
    )
    console.print(pt)

    # ── TECHNICALS ────────────────────────────────────────────────────────────
    if tech:
        tt = Table(title="Technicals")
        tt.add_column("RSI(14)")
        tt.add_column("ATR(14)")
        tt.add_column("ATR %")
        tt.add_column("SMA20")
        tt.add_column("SMA50")
        tt.add_column("SMA200")
        tt.add_column("Trend")

        rsi = tech.get("rsi")
        rc  = _rsi_color(rsi)
        tt.add_row(
            f"[{rc}]{rsi}[/{rc}]" if rsi else "—",
            str(tech.get("atr", "—")),
            f"{tech.get('atr_pct', '—')}%",
            str(tech.get("sma20", "—")),
            str(tech.get("sma50", "—")),
            str(tech.get("sma200", "—")),
            _trend_label(tech.get("above_sma50"), tech.get("above_sma200")),
        )
        console.print(tt)

    # ── FUNDAMENTALS ─────────────────────────────────────────────────────────
    mktcap  = info.get("marketCap")
    pe      = info.get("trailingPE") or info.get("forwardPE")
    fpe     = info.get("forwardPE")
    ps      = info.get("priceToSalesTrailing12Months")
    pb      = info.get("priceToBook")
    ev_eb   = info.get("enterpriseToEbitda")
    rev_grw = info.get("revenueGrowth")
    earn_grw= info.get("earningsGrowth")
    margin  = info.get("profitMargins")
    gross_m = info.get("grossMargins")
    debt_eq = info.get("debtToEquity")
    short_f = info.get("shortPercentOfFloat")
    short_r = info.get("shortRatio")
    beta    = info.get("beta")

    ft = Table(title="Fundamentals")
    ft.add_column("Market Cap")
    ft.add_column("P/E (trail)")
    ft.add_column("P/E (fwd)")
    ft.add_column("P/S")
    ft.add_column("P/B")
    ft.add_column("EV/EBITDA")
    ft.add_column("Rev Growth")
    ft.add_column("EPS Growth")
    ft.add_column("Net Margin")
    ft.add_column("Debt/Eq")
    ft.add_column("Beta")

    ft.add_row(
        _fmt_num(mktcap),
        f"{pe:.1f}x" if pe else "—",
        f"{fpe:.1f}x" if fpe else "—",
        f"{ps:.1f}x" if ps else "—",
        f"{pb:.1f}x" if pb else "—",
        f"{ev_eb:.1f}x" if ev_eb else "—",
        _pct(rev_grw  * 100 if rev_grw  else None),
        _pct(earn_grw * 100 if earn_grw else None),
        _pct(margin   * 100 if margin   else None),
        f"{debt_eq:.0f}" if debt_eq else "—",
        f"{beta:.2f}" if beta else "—",
    )
    console.print(ft)

    # ── SHORT DATA ────────────────────────────────────────────────────────────
    if short_f or short_r:
        st = Table(title="Short Data")
        st.add_column("Short % Float")
        st.add_column("Days to Cover")
        st.add_column("Signal")

        sf_pct = float(short_f) * 100 if short_f else None
        sf_col = "red" if sf_pct and sf_pct > 20 else "yellow" if sf_pct and sf_pct > 10 else "green"
        if sf_pct and sf_pct > 20:
            sig = "[red]HIGH — squeeze/short momentum risk[/red]"
        elif sf_pct and sf_pct > 10:
            sig = "[yellow]ELEVATED — watch for squeeze[/yellow]"
        else:
            sig = "[green]LOW — no squeeze risk[/green]"

        st.add_row(
            f"[{sf_col}]{sf_pct:.1f}%[/{sf_col}]" if sf_pct else "—",
            f"{float(short_r):.1f} days" if short_r else "—",
            sig,
        )
        console.print(st)

    # ── INSIDER ACTIVITY ──────────────────────────────────────────────────────
    try:
        insider = _ticker(yf_sym).insider_transactions
        if insider is not None and not insider.empty:
            it = Table(title="Insider Transactions (recent)")
            it.add_column("Date")
            it.add_column("Name")
            it.add_column("Title")
            it.add_column("Type")
            it.add_column("Shares")
            it.add_column("Value $")
            for _, row in insider.head(6).iterrows():
                txn_type = str(row.get("Transaction", ""))
                is_sell  = "Sale" in txn_type or "Sell" in txn_type
                tcolor   = "red" if is_sell else "green"
                val      = row.get("Value") or row.get("value")
                shrs     = row.get("Shares") or row.get("shares")
                date_val = row.get("Start Date") or row.get("date") or row.get("Date", "")
                it.add_row(
                    str(date_val)[:10],
                    str(row.get("Insider") or row.get("name", "—"))[:22],
                    str(row.get("Position") or row.get("title", "—"))[:18],
                    f"[{tcolor}]{txn_type}[/{tcolor}]",
                    _fmt_num(shrs, prefix=""),
                    _fmt_num(val),
                )
            console.print(it)
    except Exception:
        pass

    # ── ANALYST RECOMMENDATIONS ───────────────────────────────────────────────
    try:
        reco = _ticker(yf_sym).recommendations
        if reco is not None and not reco.empty:
            # Summary: count buys/holds/sells from recent period
            latest = reco.tail(1)
            if "strongBuy" in latest.columns:
                sb  = int(latest["strongBuy"].iloc[0])
                b   = int(latest["buy"].iloc[0])
                h   = int(latest["hold"].iloc[0])
                s   = int(latest["sell"].iloc[0])
                ss  = int(latest["strongSell"].iloc[0])
                total = sb + b + h + s + ss
                bull  = sb + b
                bear  = s + ss
                at = Table(title="Analyst Consensus")
                at.add_column("Strong Buy")
                at.add_column("Buy")
                at.add_column("Hold")
                at.add_column("Sell")
                at.add_column("Strong Sell")
                at.add_column("Consensus")
                cons = (
                    "[bold green]BUY[/bold green]" if bull > bear * 2 else
                    "[bold red]SELL[/bold red]"   if bear > bull * 2 else
                    "[yellow]HOLD[/yellow]"
                )
                at.add_row(
                    f"[green]{sb}[/green]",
                    f"[green]{b}[/green]",
                    str(h),
                    f"[red]{s}[/red]",
                    f"[bold red]{ss}[/bold red]",
                    cons,
                )
                console.print(at)

        # Price targets
        pt_info = _ticker(yf_sym).analyst_price_targets
        if pt_info is not None and hasattr(pt_info, "mean"):
            ptt = Table(title="Price Targets (analyst)")
            ptt.add_column("Current")
            ptt.add_column("Low")
            ptt.add_column("Mean")
            ptt.add_column("High")
            ptt.add_column("Upside (mean)")
            mean_pt = float(pt_info.mean) if pt_info.mean else None
            upside  = (mean_pt / price - 1) * 100 if mean_pt and price else None
            ucol    = "green" if upside and upside > 0 else "red"
            ptt.add_row(
                f"${price:,.2f}" if price else "—",
                f"${float(pt_info.low):,.2f}" if pt_info.low else "—",
                f"${mean_pt:,.2f}" if mean_pt else "—",
                f"${float(pt_info.high):,.2f}" if pt_info.high else "—",
                f"[{ucol}]{_pct(upside)}[/{ucol}]" if upside else "—",
            )
            console.print(ptt)
    except Exception:
        pass

    # ── NEWS ──────────────────────────────────────────────────────────────────
    try:
        news = _ticker(yf_sym).news or []
        if news:
            nt = Table(title="Recent News (last 7)")
            nt.add_column("Date", style="dim", width=10)
            nt.add_column("Headline")
            nt.add_column("Source", style="dim", width=18)
            for item in news[:7]:
                content = item.get("content", {})
                title   = content.get("title") or item.get("title", "—")
                src     = (content.get("provider", {}) or {}).get("displayName") or item.get("publisher", "—")
                pub_ts  = content.get("pubDate") or item.get("providerPublishTime")
                if pub_ts:
                    try:
                        if isinstance(pub_ts, (int, float)):
                            d = datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime("%Y-%m-%d")
                        else:
                            d = str(pub_ts)[:10]
                    except Exception:
                        d = str(pub_ts)[:10]
                else:
                    d = "—"
                nt.add_row(d, title[:80], src[:18])
            console.print(nt)
    except Exception:
        pass

    # ── EARNINGS CALENDAR ────────────────────────────────────────────────────
    try:
        cal = _ticker(yf_sym).calendar
        if cal:
            earnings_date = cal.get("Earnings Date") or cal.get("earningsDate")
            eps_est       = cal.get("EPS Estimate") or cal.get("epsEstimate")
            rev_est       = cal.get("Revenue Estimate") or cal.get("revenueEstimate")
            if earnings_date:
                ed = earnings_date
                if hasattr(ed, "__iter__") and not isinstance(ed, str):
                    ed = list(ed)[0] if ed else "—"
                console.print(
                    f"\n[bold]Next Earnings:[/bold] [yellow]{str(ed)[:10]}[/yellow]"
                    + (f"  EPS est: {eps_est}" if eps_est else "")
                    + (f"  Rev est: {_fmt_num(rev_est)}" if rev_est else "")
                )
    except Exception:
        pass

    console.print()


def cmd_research(args: argparse.Namespace) -> None:
    for ticker in args.tickers:
        _research_one(ticker)


# ── News command ──────────────────────────────────────────────────────────────

def cmd_news(args: argparse.Namespace) -> None:
    yf_sym, market = resolve_ticker(args.ticker)
    label = "🇵🇱 GPW" if market == "pl" else "🇺🇸 US"
    console.print(f"\n[bold cyan]{yf_sym}[/bold cyan]  [{label}]  fetching news…\n")

    try:
        news = _ticker(yf_sym).news or []
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if not news:
        console.print("[dim]No news found.[/dim]")
        return

    cutoff_days = getattr(args, "days", 7)
    cutoff_ts   = datetime.now(tz=timezone.utc).timestamp() - cutoff_days * 86400

    nt = Table(title=f"{yf_sym} — News (last {cutoff_days} days)")
    nt.add_column("Date", style="dim", width=10)
    nt.add_column("Headline")
    nt.add_column("Source", style="dim")

    shown = 0
    for item in news:
        content = item.get("content", {})
        pub_ts  = content.get("pubDate") or item.get("providerPublishTime")
        if pub_ts and isinstance(pub_ts, (int, float)) and pub_ts < cutoff_ts:
            continue
        title   = content.get("title") or item.get("title", "—")
        src     = (content.get("provider", {}) or {}).get("displayName") or item.get("publisher", "—")
        if pub_ts:
            try:
                d = datetime.fromtimestamp(float(pub_ts), tz=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                d = str(pub_ts)[:10]
        else:
            d = "—"
        nt.add_row(d, title[:90], src[:20])
        shown += 1

    if shown:
        console.print(nt)
    else:
        console.print(f"[dim]No news in the last {cutoff_days} days.[/dim]")


# ── Screener ──────────────────────────────────────────────────────────────────

# Watchlist for screen command — extend as needed
US_SCREEN_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "AMD",
    "NFLX", "UBER", "COIN", "MSTR", "PLTR", "RBLX", "HOOD", "SQ",
    "RIVN", "LCID", "GME", "AMC", "BBBY", "SMCI", "ARM", "AVGO",
]
PL_SCREEN_TICKERS = [
    "PKN.WA", "PKO.WA", "CDR.WA", "KGH.WA", "PZU.WA", "ALE.WA",
    "LPP.WA", "DNP.WA", "JSW.WA", "MBK.WA", "SPL.WA", "TPE.WA",
    "OPL.WA", "CCC.WA",
]


def cmd_screen(args: argparse.Namespace) -> None:
    screen_type = args.type
    use_pl      = getattr(args, "pl", False)
    tickers     = PL_SCREEN_TICKERS if use_pl else US_SCREEN_TICKERS

    console.print(
        f"\n[bold]Screener:[/bold] [cyan]{screen_type}[/cyan] "
        f"({'PL/GPW' if use_pl else 'US'}) — scanning {len(tickers)} tickers…\n"
    )

    results = []
    for sym in tickers:
        try:
            info, hist = fetch_yf(sym)
            tech = compute_technicals(hist)
            price = info.get("currentPrice") or info.get("regularMarketPrice") or (
                float(hist["Close"].iloc[-1]) if not hist.empty else None
            )
            short_f = info.get("shortPercentOfFloat")
            sf_pct  = float(short_f) * 100 if short_f else 0
            chg     = info.get("regularMarketChangePercent", 0) or 0

            results.append({
                "sym":     sym,
                "price":   price,
                "chg":     chg * 100 if abs(chg) < 1 else chg,
                "tech":    tech,
                "sf_pct":  sf_pct,
                "mktcap":  info.get("marketCap"),
                "pe":      info.get("trailingPE"),
                "rev_grw": info.get("revenueGrowth"),
                "name":    (info.get("shortName") or sym)[:20],
            })
        except Exception as e:
            console.print(f"[dim]  {sym}: {e}[/dim]")

    if screen_type == "shorts":
        # High short interest + technical weakness
        candidates = sorted(
            [r for r in results if r["sf_pct"] > 5],
            key=lambda x: (-x["sf_pct"])
        )
        t = Table(title="Short Candidates (high short interest)")
        t.add_column("Ticker", style="cyan")
        t.add_column("Name", style="dim")
        t.add_column("Price")
        t.add_column("Short %Float", style="red")
        t.add_column("RSI")
        t.add_column("Trend")
        t.add_column("vs SMA200")
        for r in candidates[:15]:
            tech  = r["tech"]
            rsi   = tech.get("rsi")
            rc    = _rsi_color(rsi)
            a200  = tech.get("above_sma200")
            s200  = (
                "[green]above[/green]" if a200 else
                "[red]BELOW[/red]" if a200 is False else "—"
            )
            t.add_row(
                r["sym"],
                r["name"],
                f"${r['price']:,.2f}" if r["price"] else "—",
                f"{r['sf_pct']:.1f}%",
                f"[{rc}]{rsi}[/{rc}]" if rsi else "—",
                _trend_label(tech.get("above_sma50"), tech.get("above_sma200")),
                s200,
            )
        console.print(t)

    elif screen_type in ("momentum", "breakout"):
        # Strong trend + RSI not overbought + high volume
        candidates = sorted(
            [r for r in results
             if r["tech"].get("above_sma50") and r["tech"].get("above_sma200")
             and r["tech"].get("rsi", 100) < 75
             and r["tech"].get("vol_ratio", 0) > 1.2],
            key=lambda x: -(x["tech"].get("vol_ratio", 0))
        )
        t = Table(title="Momentum / Breakout Candidates")
        t.add_column("Ticker", style="cyan")
        t.add_column("Name", style="dim")
        t.add_column("Price")
        t.add_column("1D Chg")
        t.add_column("RSI")
        t.add_column("Vol Ratio")
        t.add_column("vs ATH")
        for r in candidates[:15]:
            tech = r["tech"]
            rsi  = tech.get("rsi")
            rc   = _rsi_color(rsi)
            chg  = r["chg"]
            cc   = "green" if chg >= 0 else "red"
            t.add_row(
                r["sym"],
                r["name"],
                f"${r['price']:,.2f}" if r["price"] else "—",
                f"[{cc}]{chg:+.1f}%[/{cc}]",
                f"[{rc}]{rsi}[/{rc}]" if rsi else "—",
                f"{tech.get('vol_ratio', 1):.2f}x",
                f"{tech.get('dist_ath_pct', 0):+.1f}%",
            )
        console.print(t)
        if not candidates:
            console.print("[dim]No clear setups found in current watchlist.[/dim]")

    else:
        console.print(f"[red]Unknown screen type: {screen_type}[/red]")
        console.print("Available: shorts, momentum, breakout")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Stock Research — US + Polish GPW")
    sub = p.add_subparsers(dest="cmd", required=True)

    # research
    r = sub.add_parser("research", help="Full analysis (price + tech + fundamentals + news)")
    r.add_argument("tickers", nargs="+", metavar="TICKER",
                   help="One or more tickers, e.g. NVDA PKN.WA TSLA")
    r.set_defaults(func=cmd_research)

    # news
    n = sub.add_parser("news", help="News digest for a ticker")
    n.add_argument("ticker", metavar="TICKER")
    n.add_argument("--days", type=int, default=7, help="Look-back window in days (default 7)")
    n.set_defaults(func=cmd_news)

    # screen
    sc = sub.add_parser("screen", help="Scan watchlist for setups")
    sc.add_argument("--type", choices=["shorts", "momentum", "breakout"],
                    default="momentum", help="Screener type (default: momentum)")
    sc.add_argument("--pl", action="store_true", help="Scan Polish GPW tickers instead of US")
    sc.set_defaults(func=cmd_screen)

    args = p.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
