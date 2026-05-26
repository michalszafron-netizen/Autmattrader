#!/usr/bin/env python3
"""
insider_tracker.py — Eddie, Maggie, Frank scout agents

Eddie  : SEC Form 4 — insider buys ≥$100k            (daily 06:00)
Maggie : 13F filings — top 5 institutional funds     (weekly Sun 19:00)
Frank  : Fed speeches — hawkish/dovish scoring        (weekly Mon 08:00)

All data sources are FREE public US government APIs (SEC EDGAR + Fed).
Requires ANTHROPIC_API_KEY for Claude signal analysis.

Usage:
  python scripts/insider_tracker.py form4          # Eddie: insider buys
  python scripts/insider_tracker.py institutional  # Maggie: 13F fund moves
  python scripts/insider_tracker.py fed            # Frank: Fed speech sentiment
  python scripts/insider_tracker.py all            # all three scouts
  python scripts/insider_tracker.py all --dry-run  # fetch + analyze, no DB/Telegram
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_SSL    = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
console = Console()

# ── Constants ─────────────────────────────────────────────────────────────────

EDGAR_EFTS   = "https://efts.sec.gov/LATEST/search-index"
EDGAR_BASE   = "https://www.sec.gov"
EDGAR_DATA   = "https://data.sec.gov"
FED_RSS_URL  = "https://www.federalreserve.gov/feeds/speeches.xml"

# EDGAR requires a User-Agent identifying the requester (their ToS).
_UA = "trading-ai-research contact@trading-ai.local"

MIN_BUY_USD  = 100_000   # Eddie: minimum insider buy value
EDGAR_DELAY  = 0.15      # seconds between EDGAR requests (10 req/s limit)

SENIOR_ROLES = {"ceo", "cfo", "president", "chairman", "director", "chief"}

# ── DeepSeek API ──────────────────────────────────────────────────────────────
DEEPSEEK_KEY   = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE  = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 13F fund watchlist — CIK zero-padded to 10 digits
FUNDS_13F = [
    ("Berkshire Hathaway",    "0001067983"),
    ("Bridgewater Associates","0001350694"),
    ("Renaissance Technologies","0001037389"),
    ("Citadel Advisors",      "0001423053"),
    ("Two Sigma Investments", "0001179392"),
]

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class InsiderSignal:
    scout:      str
    ticker:     str       # stock ticker or "MACRO"
    direction:  str       # BULLISH | BEARISH | NEUTRAL
    confidence: int       # 1-5
    reason:     str       # one-liner
    raw:        str       # full Claude response for audit

@dataclass
class Form4Buy:
    ticker:      str
    company:     str
    filer:       str
    role:        str
    total_value: float
    date:        str

@dataclass
class Fund13F:
    fund:    str
    cik:     str
    filing:  str    # accession number
    period:  str    # report period
    url:     str

# ── HTTP client ───────────────────────────────────────────────────────────────

def _edgar_client() -> httpx.Client:
    return httpx.Client(
        verify=_SSL,
        timeout=20.0,
        headers={"User-Agent": _UA, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
    )

def _llm_call(system: str, user: str, max_tokens: int = 1024) -> str:
    """Call DeepSeek chat completions. Returns full response text."""
    if not DEEPSEEK_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY missing from .env")
    with httpx.Client(verify=_SSL, timeout=60.0) as c:
        resp = c.post(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}",
                     "Content-Type": "application/json"},
            json={"model": DEEPSEEK_MODEL,
                  "max_tokens": max_tokens,
                  "messages": [
                      {"role": "system", "content": system},
                      {"role": "user",   "content": user},
                  ]},
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

# ── XML helpers ───────────────────────────────────────────────────────────────

def _xv(node: ET.Element, path: str) -> str:
    """Get text at XPath path, empty string if missing."""
    el = node.find(path)
    return (el.text or "").strip() if el is not None else ""

def _xf(node: ET.Element, path: str) -> float:
    """Get float at XPath path, 0.0 if missing."""
    try:
        return float(_xv(node, path))
    except (ValueError, TypeError):
        return 0.0

# ── EDDIE — SEC Form 4 ────────────────────────────────────────────────────────

def _fetch_form4_index(days_back: int = 1) -> list[dict]:
    """Hit EDGAR EFTS to get recent Form 4 filing metadata."""
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days_back)).isoformat()
    end   = today.isoformat()

    try:
        with _edgar_client() as c:
            resp = c.get(
                EDGAR_EFTS,
                params={"forms": "4", "dateRange": "custom",
                        "startdt": start, "enddt": end, "_source": "accession_no,entity_name,file_date"},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        console.print(f"[yellow][eddie] EDGAR EFTS error: {e}[/yellow]")
        return []

    hits = data.get("hits", {}).get("hits", [])
    return [h.get("_source", {}) for h in hits if h.get("_source")]


def _fetch_form4_xml(accession_no: str) -> str | None:
    """
    Fetch the Form 4 XML for a given accession number.
    Derives filer CIK from first 10 digits of accession_no.
    """
    # accession_no format: "0000123456-26-000001"
    nodashes = accession_no.replace("-", "")
    cik_str  = accession_no.split("-")[0].lstrip("0") or "0"

    # Get filing index to find XML filename
    index_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik_str}/{nodashes}/{nodashes}-index.json"
    try:
        with _edgar_client() as c:
            resp = c.get(index_url, timeout=15)
            if resp.status_code != 200:
                return None
            idx = resp.json()
        time.sleep(EDGAR_DELAY)
    except Exception:
        return None

    # Find the XML document for Form 4
    xml_file = None
    items = idx.get("directory", {}).get("item", [])
    if isinstance(items, dict):
        items = [items]
    for item in items:
        name = item.get("name", "")
        if name.endswith(".xml") and item.get("type", "") in ("4", "4/A", ""):
            xml_file = name
            break
    if not xml_file:
        # fallback: first .xml
        for item in items:
            if item.get("name", "").endswith(".xml"):
                xml_file = item["name"]
                break
    if not xml_file:
        return None

    xml_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik_str}/{nodashes}/{xml_file}"
    try:
        with _edgar_client() as c:
            resp = c.get(xml_url, timeout=15)
            resp.raise_for_status()
        time.sleep(EDGAR_DELAY)
        return resp.text
    except Exception:
        return None


def _parse_form4_xml(xml_text: str) -> Form4Buy | None:
    """Parse Form 4 XML. Returns Form4Buy if it's a qualifying open-market purchase."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    ticker  = _xv(root, ".//issuerTradingSymbol").upper()
    company = _xv(root, ".//issuerName")
    if not ticker:
        return None

    filer   = _xv(root, ".//rptOwnerName")
    role    = _xv(root, ".//officerTitle")
    is_dir  = _xv(root, ".//isDirector") == "1"
    is_off  = _xv(root, ".//isOfficer")  == "1"

    # Must be director or senior officer
    role_lower = role.lower()
    is_senior  = is_dir or any(k in role_lower for k in SENIOR_ROLES)
    if not is_senior and not is_off:
        return None

    total_value = 0.0
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = _xv(txn, ".//transactionCode")
        if code != "P":
            continue
        shares = _xf(txn, ".//transactionShares/value")
        price  = _xf(txn, ".//transactionPricePerShare/value")
        if shares > 0 and price > 0:
            total_value += shares * price

    if total_value < MIN_BUY_USD:
        return None

    date = _xv(root, ".//periodOfReport") or datetime.now(timezone.utc).date().isoformat()
    return Form4Buy(
        ticker=ticker, company=company, filer=filer,
        role=role, total_value=total_value, date=date,
    )


def run_eddie(dry_run: bool = False) -> InsiderSignal:
    """Eddie: SEC Form 4 insider buy scanner."""
    console.print("[cyan][eddie][/cyan] Fetching SEC EDGAR Form 4 filings…")
    index = _fetch_form4_index(days_back=1)
    if not index:
        # Try 2-day window (weekends/holidays)
        index = _fetch_form4_index(days_back=2)

    console.print(f"[cyan][eddie][/cyan] Found {len(index)} filings, parsing up to 30…")

    buys: list[Form4Buy] = []
    for entry in index[:30]:
        acc = entry.get("accession_no", "")
        if not acc:
            continue
        xml = _fetch_form4_xml(acc)
        if not xml:
            continue
        buy = _parse_form4_xml(xml)
        if buy:
            buys.append(buy)

    if buys:
        # Sort by value descending
        buys.sort(key=lambda b: b.total_value, reverse=True)
        t = Table(title=f"Eddie — Form 4 Insider Buys (top {min(5, len(buys))})")
        t.add_column("Ticker"); t.add_column("Company"); t.add_column("Filer")
        t.add_column("Role");   t.add_column("Value $"); t.add_column("Date")
        for b in buys[:5]:
            t.add_row(b.ticker, b.company[:30], b.filer[:22], b.role[:20],
                      f"${b.total_value:,.0f}", b.date)
        console.print(t)
    else:
        console.print("[dim][eddie] No qualifying buys found — passing to Claude for analysis[/dim]")

    # Claude analysis — pass raw data + ask for structured signal
    context = _format_eddie_context(buys, index)
    signal  = _llm_signal("eddie", _EDDIE_SYSTEM, context)
    _print_signal(signal)
    return signal


def _format_eddie_context(buys: list[Form4Buy], index: list[dict]) -> str:
    if buys:
        lines = [f"Qualifying insider buys found ({len(buys)} total):"]
        for b in buys[:10]:
            lines.append(f"  {b.ticker} — {b.filer} ({b.role}) bought ${b.total_value:,.0f} on {b.date} [{b.company}]")
    else:
        lines = ["No qualifying buys (≥$100k, open-market, C-suite) parsed from today's Form 4 filings."]
        lines.append(f"Total Form 4 filings in window: {len(index)}")

    lines.append("\nGenerate your structured signal based on the data above.")
    return "\n".join(lines)


_EDDIE_SYSTEM = """You are Eddie, an SEC Form 4 insider trading analyst.
You receive pre-filtered data about open-market insider purchases by C-suite officers and directors.

Rules:
- A buy is BULLISH for that ticker (insider conviction).
- The bigger the buy relative to the insider's known compensation, the higher confidence.
- If no qualifying buys: ticker=MACRO, direction=NEUTRAL, confidence=1.

Output a brief prose summary (2-3 sentences), then a strict JSON object on its own line:
{"ticker": "<TICKER>", "direction": "BULLISH", "confidence": <1-5>, "reason": "<one line under 120 chars>"}

Confidence: 1=small buy sub-$200k; 3=CEO buy $500k+; 5=CEO/founder buying $1M+ own stock."""

# ── MAGGIE — 13F Institutional Filings ───────────────────────────────────────

def _fetch_latest_13f(cik: str) -> Fund13F | None:
    """Get the most recent 13F-HR filing metadata for a fund CIK."""
    url = f"{EDGAR_DATA}/submissions/CIK{cik}.json"
    try:
        with _edgar_client() as c:
            resp = c.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        time.sleep(EDGAR_DELAY)
    except Exception as e:
        console.print(f"[yellow][maggie] Submissions fetch error ({cik}): {e}[/yellow]")
        return None

    name     = data.get("name", cik)
    filings  = data.get("filings", {}).get("recent", {})
    forms    = filings.get("form", [])
    accs     = filings.get("accessionNumber", [])
    dates    = filings.get("reportDate", [])

    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            acc = accs[i] if i < len(accs) else ""
            period = dates[i] if i < len(dates) else ""
            cik_clean = cik.lstrip("0") or "0"
            nodashes  = acc.replace("-", "")
            url_filing = f"{EDGAR_BASE}/Archives/edgar/data/{cik_clean}/{nodashes}/"
            return Fund13F(fund=name, cik=cik, filing=acc, period=period, url=url_filing)
    return None


def run_maggie(dry_run: bool = False) -> InsiderSignal:
    """Maggie: 13F institutional filing scanner."""
    console.print("[cyan][maggie][/cyan] Fetching 13F filings from top institutional funds…")

    fund_data: list[dict] = []
    for fund_name, cik in FUNDS_13F:
        console.print(f"[dim]  checking {fund_name}…[/dim]")
        f13 = _fetch_latest_13f(cik)
        if f13:
            fund_data.append({
                "fund":   fund_name,
                "period": f13.period,
                "filing": f13.filing,
                "url":    f13.url,
            })
            console.print(f"  [green]✓[/green] {fund_name} — 13F period {f13.period}")
        else:
            console.print(f"  [dim]  {fund_name} — no 13F found[/dim]")

    t = Table(title="Maggie — Latest 13F Filings Found")
    t.add_column("Fund"); t.add_column("Period"); t.add_column("Accession")
    for fd in fund_data:
        t.add_row(fd["fund"], fd["period"], fd["filing"])
    console.print(t)

    context = _format_maggie_context(fund_data)
    signal  = _llm_signal("maggie", _MAGGIE_SYSTEM, context)
    _print_signal(signal)
    return signal


def _format_maggie_context(fund_data: list[dict]) -> str:
    if not fund_data:
        return "No 13F filings could be retrieved. Return NEUTRAL MACRO signal."
    lines = ["Most recent 13F-HR filings retrieved from EDGAR:"]
    for fd in fund_data:
        lines.append(f"  {fd['fund']}: period {fd['period']}, accession {fd['filing']}")
        lines.append(f"    Filing index: {fd['url']}")
    lines.append(
        "\nBased on your knowledge of these funds' recent disclosed positions and any "
        "notable changes you are aware of, identify the single most notable institutional "
        "move. Generate your structured signal."
    )
    return "\n".join(lines)


_MAGGIE_SYSTEM = """You are Maggie, an institutional smart-money analyst.
You track 13F filings from the world's most sophisticated funds: Berkshire Hathaway,
Bridgewater Associates, Renaissance Technologies, Citadel Advisors, Two Sigma.

Based on the 13F filing metadata provided and your knowledge of these funds' recent
disclosed positions:
- Identify the most notable position change: new entry, large increase, or full exit.
- NEW POSITION or major INCREASE → BULLISH on that ticker.
- FULL EXIT or major REDUCTION → BEARISH on that ticker.

Output a brief prose summary, then a strict JSON on its own line:
{"ticker": "<TICKER>", "direction": "BULLISH|BEARISH", "confidence": <1-5>, "reason": "<one line>"}

Confidence: 1=marginal single-fund change; 5=multi-fund alignment or $1B+ new position.
If nothing notable: {"ticker": "MACRO", "direction": "NEUTRAL", "confidence": 1, "reason": "no notable 13F moves this cycle"}"""

# ── FRANK — Fed Speeches ──────────────────────────────────────────────────────

def _fetch_fed_speeches() -> list[dict]:
    """Fetch recent speeches from the Federal Reserve RSS feed."""
    try:
        with _edgar_client() as c:
            resp = c.get(FED_RSS_URL, timeout=20)
            resp.raise_for_status()
            rss_text = resp.text
    except Exception as e:
        console.print(f"[yellow][frank] Fed RSS error: {e}[/yellow]")
        return []

    # Parse RSS/XML
    speeches = []
    try:
        root = ET.fromstring(rss_text)
        # RSS namespace handling
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # Try standard RSS first
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        for item in items[:20]:
            title = (item.findtext("title") or
                     item.findtext("{http://www.w3.org/2005/Atom}title") or "")
            link  = (item.findtext("link") or
                     item.findtext("{http://www.w3.org/2005/Atom}id") or "")
            date_raw = (item.findtext("pubDate") or
                        item.findtext("{http://www.w3.org/2005/Atom}updated") or "")
            desc  = (item.findtext("description") or
                     item.findtext("{http://www.w3.org/2005/Atom}summary") or "")

            speeches.append({
                "title": title.strip(),
                "link":  link.strip(),
                "date":  date_raw.strip()[:30],
                "desc":  desc.strip()[:300],
            })
    except ET.ParseError as e:
        console.print(f"[yellow][frank] RSS parse error: {e}[/yellow]")
        return []

    return speeches


def run_frank(dry_run: bool = False) -> InsiderSignal:
    """Frank: Fed speech hawkish/dovish sentiment scorer."""
    console.print("[cyan][frank][/cyan] Fetching Federal Reserve speeches…")
    speeches = _fetch_fed_speeches()

    if speeches:
        t = Table(title=f"Frank — Recent Fed Speeches ({len(speeches)} found)")
        t.add_column("Date", style="dim", width=12)
        t.add_column("Title")
        for sp in speeches[:8]:
            t.add_row(sp["date"][:10], sp["title"][:70])
        console.print(t)
    else:
        console.print("[dim][frank] No speeches fetched[/dim]")

    context = _format_frank_context(speeches)
    signal  = _llm_signal("frank", _FRANK_SYSTEM, context)
    _print_signal(signal)
    return signal


def _format_frank_context(speeches: list[dict]) -> str:
    if not speeches:
        return "No Fed speeches fetched from RSS. Return NEUTRAL MACRO."
    lines = [f"Federal Reserve speeches fetched (last 7 days, {len(speeches)} entries):"]
    for sp in speeches[:12]:
        lines.append(f"\n  [{sp['date'][:10]}] {sp['title']}")
        if sp["desc"]:
            lines.append(f"  Summary: {sp['desc'][:200]}")
    lines.append("\nClassify each speech hawkish/dovish/neutral and give your aggregated signal.")
    return "\n".join(lines)


_FRANK_SYSTEM = """You are Frank, a Federal Reserve speech analyst.
You read Fed speeches and FOMC commentary and score the net tilt for risk assets.

Rules:
- Net DOVISH (rate cuts coming, accommodative) → BULLISH on risk assets (equities + crypto)
- Net HAWKISH (rates staying high or rising) → BEARISH on risk assets
- Mixed or no clear signal → NEUTRAL
- ticker is always "MACRO"

For each speech: extract speaker name, one-line stance, and classify hawkish/dovish/neutral.
Then give a net tilt.

Output prose summary (3-5 sentences), then strict JSON on its own line:
{"ticker": "MACRO", "direction": "BULLISH|BEARISH|NEUTRAL", "confidence": <1-5>, "reason": "<one line>"}

Confidence: 1=single speech mixed signals; 5=unanimous Powell + governors, unambiguous language."""

# ── Claude signal engine ──────────────────────────────────────────────────────

def _llm_signal(scout: str, system: str, user_context: str) -> InsiderSignal:
    """Run a scout prompt through DeepSeek. Parse the structured JSON trailer."""
    try:
        raw = _llm_call(system, user_context)
    except Exception as e:
        console.print(f"[red][{scout}] DeepSeek API error: {e}[/red]")
        return InsiderSignal(scout=scout, ticker="MACRO", direction="NEUTRAL",
                             confidence=1, reason=f"LLM error: {e}", raw="")

    payload = _extract_last_json(raw)
    if payload:
        return InsiderSignal(
            scout=scout,
            ticker=str(payload.get("ticker", "MACRO")).upper(),
            direction=_norm_dir(payload.get("direction", "NEUTRAL")),
            confidence=max(1, min(5, int(payload.get("confidence", 1) or 1))),
            reason=str(payload.get("reason", ""))[:200],
            raw=raw,
        )

    # Fallback NEUTRAL
    return InsiderSignal(scout=scout, ticker="MACRO", direction="NEUTRAL",
                         confidence=1, reason="no structured signal parsed", raw=raw)


def _extract_last_json(text: str) -> dict[str, Any] | None:
    depth = 0; start = -1; candidates: list[str] = []
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start:i+1]); start = -1
    for c in reversed(candidates):
        try:
            obj = json.loads(c)
            if isinstance(obj, dict): return obj
        except json.JSONDecodeError:
            continue
    return None


def _norm_dir(d: Any) -> str:
    s = str(d).upper().strip()
    return s if s in ("BULLISH", "BEARISH", "NEUTRAL") else "NEUTRAL"

# ── Output / persistence ──────────────────────────────────────────────────────

def _print_signal(sig: InsiderSignal) -> None:
    col = "green" if sig.direction == "BULLISH" else ("red" if sig.direction == "BEARISH" else "yellow")
    console.print(Panel(
        f"[bold]{sig.scout.upper()}[/bold]  [{col}]{sig.direction}[/{col}]  "
        f"[cyan]{sig.ticker}[/cyan]  conf={sig.confidence}/5\n{sig.reason}",
        expand=False,
    ))


def _save_signal(sig: InsiderSignal) -> None:
    """Persist signal to trading.db via db.py."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        db = DB()
        with db._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS insider_signals (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                scout     TEXT NOT NULL,
                ticker    TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence INTEGER NOT NULL,
                reason    TEXT NOT NULL,
                raw       TEXT,
                ts        TEXT NOT NULL
            )""")
            c.execute(
                "INSERT INTO insider_signals (scout,ticker,direction,confidence,reason,raw,ts) "
                "VALUES (?,?,?,?,?,?,?)",
                (sig.scout, sig.ticker, sig.direction, sig.confidence,
                 sig.reason, sig.raw, datetime.now(timezone.utc).isoformat()),
            )
        console.print(f"[dim]  saved to DB[/dim]")
    except Exception as e:
        console.print(f"[yellow]  DB save skipped: {e}[/yellow]")


def _send_telegram(sig: InsiderSignal) -> None:
    """Send signal to Telegram via bot API."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_ALLOWED_USER_ID", os.getenv("TELEGRAM_CHAT_ID", ""))
    if not token or not chat_id:
        console.print("[dim]  Telegram not configured — skipping[/dim]")
        return

    dir_emoji = "🟢" if sig.direction == "BULLISH" else ("🔴" if sig.direction == "BEARISH" else "⚪")
    scout_emoji = {"eddie": "📋", "maggie": "🏛", "frank": "🏦"}.get(sig.scout, "🔍")
    text = (
        f"{scout_emoji} *INSIDER SCOUT — {sig.scout.upper()}*\n"
        f"{dir_emoji} `{sig.direction}` on `{sig.ticker}` (conf {sig.confidence}/5)\n"
        f"_{sig.reason}_"
    )
    import urllib.request, urllib.parse
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            if 200 <= r.status < 300:
                console.print("[dim]  Telegram sent ✓[/dim]")
    except Exception as e:
        console.print(f"[yellow]  Telegram error: {e}[/yellow]")

# ── Main ──────────────────────────────────────────────────────────────────────

SCOUTS = {
    "form4":         run_eddie,
    "institutional": run_maggie,
    "fed":           run_frank,
}

def main() -> int:
    p = argparse.ArgumentParser(description="Insider Tracker — Eddie / Maggie / Frank")
    p.add_argument("scout", choices=["form4", "institutional", "fed", "all"],
                   help="Which scout to run")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch + analyze, but skip DB writes and Telegram")
    args = p.parse_args()

    runners = (
        list(SCOUTS.values()) if args.scout == "all"
        else [SCOUTS[args.scout]]
    )

    signals: list[InsiderSignal] = []
    for runner in runners:
        sig = runner(dry_run=args.dry_run)
        signals.append(sig)
        if not args.dry_run:
            _save_signal(sig)
            _send_telegram(sig)
        console.print()

    # Summary table
    t = Table(title="Insider Tracker — Session Summary")
    t.add_column("Scout"); t.add_column("Ticker"); t.add_column("Direction")
    t.add_column("Conf"); t.add_column("Reason")
    for sig in signals:
        col = "green" if sig.direction == "BULLISH" else ("red" if sig.direction == "BEARISH" else "dim")
        t.add_row(
            sig.scout, sig.ticker,
            f"[{col}]{sig.direction}[/{col}]",
            str(sig.confidence),
            sig.reason[:60],
        )
    console.print(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
