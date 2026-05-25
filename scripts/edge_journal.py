"""Edge Journal — personal market observations with AI verification.

Captures your market edge hypotheses, verifies them via DeepSeek (default, cheap),
stores in SQLite, and auto-generates context/my_edge.md for Hermes.

Usage:
  python scripts/edge_journal.py add "tekst obserwacji" [options]
  python scripts/edge_journal.py list [--status open] [--all]
  python scripts/edge_journal.py view ID
  python scripts/edge_journal.py close ID --result "co się stało" [--pnl 120.5]
  python scripts/edge_journal.py invalidate ID --reason "powód"
  python scripts/edge_journal.py expire ID
  python scripts/edge_journal.py context
  python scripts/edge_journal.py recheck ID

Options for 'add' / 'recheck':
  --type TYPE       edge_type: weekend_arb | divergence | funding | macro | pattern | other
  --assets A B C    asset tags, e.g. --assets BTC GOLD USOIL
  --timeframe TF    timeframe: weekend | intraday | swing | multi-day
  (default)         DeepSeek verifies the logic/reasoning only — fast, cheap
  --data            fetch live HL prices + COT + Fear&Greed before verifying (price-related observations)
  --grok            use Grok + X search instead of DeepSeek (narrative/sentiment observations)
  --no-ai           skip AI verification entirely (just save the note)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console encoding for Polish/emoji chars
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
_ENV  = _ROOT / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))
from db import DB

import subprocess

XAI_KEY             = os.getenv("XAI_API_KEY", "")
DEEPSEEK_KEY        = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE       = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL      = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
_GROK_RESPONSES_URL = "https://api.x.ai/v1/responses"
_GROK_MODEL         = "grok-4.3"
_CONTEXT_DIR        = _ROOT / "context"
_CONTEXT_FILE       = _CONTEXT_DIR / "my_edge.md"

# HL xyz TradFi asset name mapping → exact xyz DEX name (without "xyz:" prefix)
_HL_XYZ = {
    "GOLD": "GOLD", "XAU": "GOLD",
    "SILVER": "SILVER", "XAG": "SILVER",
    "USOIL": "BRENTOIL", "OIL": "BRENTOIL", "BRENTOIL": "BRENTOIL", "ROPA": "BRENTOIL",
    "NQ": "XYZ100", "NASDAQ": "XYZ100", "NDX": "XYZ100", "NQ100": "XYZ100",
    "SPX": "SP500", "SPX500": "SP500", "SP500": "SP500",
    "EUR": "EUR", "GBP": "GBP", "DXY": "DXY",
    "CORN": "CORN", "COFFEE": "COFFEE", "COCOA": "COCOA",
    "COPPER": "COPPER", "ALUMINIUM": "ALUMINIUM",
}
_HL_CRYPTO = {"BTC","ETH","SOL","HYPE","AVAX","LINK","ARB","OP","DOGE","MATIC","POL","SUI","APT"}

# xyz DEX stocks — these trade 24/7 on HL even when US markets are closed
_HL_XYZ_STOCKS = {
    "AAPL","AMZN","NVDA","MSFT","GOOGL","META","TSLA","AMD","INTC",
    "MSTR","HOOD","COIN","PLTR","ARM","ASML","BABA","EBAY","GME",
    "BX","COST","DKNG","CRCL","CRWV",
}


# ── HTTP client ───────────────────────────────────────────────────────────────
def _client():
    try:
        import httpx
        return httpx.Client(timeout=60, verify=False)
    except ImportError:
        raise SystemExit("httpx required: pip install httpx")


# ── Market data gathering ─────────────────────────────────────────────────────
def _run_script(script: str, *args, timeout: int = 20) -> str:
    """Run a trading-ai script, return stdout. Silent on error."""
    try:
        cmd = [sys.executable, str(_ROOT / "scripts" / script)] + list(args)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(_ROOT))
        out = r.stdout.strip()
        return out if out else r.stderr.strip()[:200]
    except Exception as e:
        return f"[unavailable: {e}]"


def _fetch_hl_prices(asset_names: list[str]) -> str:
    """Fetch live mark prices from Hyperliquid public API (no key needed).
    Queries both standard perp and xyz HIP-3 TradFi DEX.
    """
    if not asset_names:
        return ""
    try:
        import httpx
        with httpx.Client(verify=False, timeout=10) as c:
            mids_std = c.post("https://api.hyperliquid.xyz/info",
                              json={"type": "allMids"}).json()
            mids_xyz = c.post("https://api.hyperliquid.xyz/info",
                              json={"type": "allMids", "dex": "xyz"}).json()
        # Merge: xyz assets use "xyz:NAME" key
        all_mids: dict = {**mids_std}
        for k, v in mids_xyz.items():
            all_mids[k] = v                      # e.g. "xyz:SILVER"
            bare = k.replace("xyz:", "").upper()
            all_mids[bare] = v                   # also store as "SILVER" for easy lookup

        lines = []
        for name in asset_names:
            hl_name  = _HL_XYZ.get(name.upper(), name.upper())
            xyz_name = f"xyz:{hl_name}"
            price    = (all_mids.get(xyz_name)           # xyz:GOLD
                        or all_mids.get(hl_name)          # GOLD / BTC
                        or all_mids.get(name.upper()))     # fallback
            if price:
                is_stock = hl_name in _HL_XYZ_STOCKS
                source   = ("xyz/stock(24h)" if is_stock
                            else "xyz/TradFi" if xyz_name in all_mids
                            else "HL perp")
                lines.append(f"  {hl_name}: ${float(price):,.4f}  [{source}]")
        return "\n".join(lines) if lines else "No prices found for requested assets"
    except Exception as e:
        return f"[HL API error: {e}]"


def _yf_last_close(yf_ticker: str) -> tuple[float | None, str]:
    """Fetch last close from Yahoo Finance via httpx (SSL-bypassed). Returns (price, date_str)."""
    try:
        import httpx
        r = httpx.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}",
            params={"interval": "1d", "range": "5d"},
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False, timeout=10, follow_redirects=True,
        )
        data  = r.json()
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        stamps = result["timestamp"]
        for i in range(len(closes) - 1, -1, -1):
            if closes[i] is not None:
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(stamps[i], tz=timezone.utc).strftime("%Y-%m-%d")
                return float(closes[i]), dt
    except Exception:
        pass
    return None, ""


def _fetch_reference_prices(all_tags: list[str], hl_prices_str: str = "") -> str:
    """Fetch last TradFi close via Yahoo Finance and compare with current HL price.

    Shows delta % so AI can immediately see 'HL PREMIUM +3.1%' vs just a raw price.
    Works for commodities, indices, and individual stocks.
    """
    if not all_tags:
        return ""

    # Mapping tag → Yahoo Finance ticker
    yf_map: dict[str, str] = {
        "GOLD": "GC=F", "XAU": "GC=F",
        "SILVER": "SI=F", "XAG": "SI=F",
        "USOIL": "CL=F", "OIL": "CL=F", "BRENTOIL": "BZ=F",
        "NQ": "NQ=F", "NASDAQ": "NQ=F", "XYZ100": "NQ=F",
        "SPX": "ES=F", "SPX500": "ES=F", "SP500": "ES=F",
        "BTC": "BTC-USD", "ETH": "ETH-USD",
    }
    # Stocks: direct ticker
    for tag in all_tags:
        if tag.upper() in _HL_XYZ_STOCKS and tag.upper() not in yf_map:
            yf_map[tag.upper()] = tag.upper()

    # Get current HL prices for comparison
    try:
        import httpx
        mids_xyz = httpx.post("https://api.hyperliquid.xyz/info",
                              json={"type": "allMids", "dex": "xyz"},
                              verify=False, timeout=8).json()
        mids_std = httpx.post("https://api.hyperliquid.xyz/info",
                              json={"type": "allMids"},
                              verify=False, timeout=8).json()
        all_mids = {**mids_std, **{k.replace("xyz:", "").upper(): v for k, v in mids_xyz.items()}}
    except Exception:
        all_mids = {}

    lines: list[str] = []
    for tag in all_tags:
        yf_ticker = yf_map.get(tag.upper())
        if not yf_ticker:
            continue
        hl_key    = _HL_XYZ.get(tag.upper(), tag.upper())
        hl_price  = float(all_mids.get(f"xyz:{hl_key}") or all_mids.get(hl_key)
                          or all_mids.get(tag.upper()) or 0)
        close, date_s = _yf_last_close(yf_ticker)
        if close and hl_price:
            delta = (hl_price - close) / close * 100
            status = ("HL PREMIUM" if delta > 0.5
                      else "HL DISCOUNT" if delta < -0.5
                      else "flat")
            lines.append(
                f"  {tag.upper():<8} HL={hl_price:>10.2f}  TradFi close={close:>10.2f} ({date_s})  {delta:>+6.2f}%  {status}"
            )
        elif close:
            lines.append(f"  {tag.upper():<8} TradFi close={close:>10.2f} ({date_s})  [no HL price]")

    return "\n".join(lines) if lines else ""


def _get_us_market_clock() -> dict:
    """Check US stock market open/close via Alpaca API.
    Returns is_open (bool), next_open, next_close — handles holidays correctly.
    Falls back to empty dict on error.
    """
    key    = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_API_SECRET", "")
    base   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if not key:
        return {}
    try:
        import httpx
        with httpx.Client(verify=False, timeout=8) as c:
            r = c.get(
                f"{base}/v1/clock",
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            )
        d = r.json()
        is_open    = d.get("is_open", False)
        next_open  = (d.get("next_open") or "")[:16].replace("T", " ")
        next_close = (d.get("next_close") or "")[:16].replace("T", " ")
        # Detect holiday: weekday but market closed and opens tomorrow or later
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        reason = ""
        if not is_open and now_utc.weekday() < 5:
            reason = "US holiday"
        return {"is_open": is_open, "next_open": next_open,
                "next_close": next_close, "reason": reason}
    except Exception as e:
        return {"error": str(e)}


# ── AI planning prompt ────────────────────────────────────────────────────────
_PLANNER_PROMPT = """\
You are a data research planner for a trading edge verification system.
A trader submitted an edge observation. Your job: decide EXACTLY which data tools to fetch.

OBSERVATION: {note}
ASSETS: {assets}
EDGE TYPE: {edge_type}
TIMEFRAME: {timeframe}

AVAILABLE TOOLS:
1. fear_greed       — Crypto Fear & Greed index (0-100). Use for crypto sentiment context.
2. hl_prices        — Live Hyperliquid mark prices (crypto perps + xyz TradFi stocks/commodities 24/7).
3. tradfi_reference — Last TradFi close (Yahoo Finance) vs current HL price with delta %. Use for detecting HL premium/discount vs traditional markets.
4. cot              — CFTC COT institutional positioning. Works for: GOLD, SILVER, OIL, NQ, SPX, EUR.
5. market_clock     — US stock market open/closed via Alpaca (handles public holidays). Use if market hours matter.
6. macro_news       — Scrape 10 macro news sources (expensive: 3+ Firecrawl credits). Only if observation directly references a specific news catalyst.

SELECTION LOGIC:
- Observation mentions HL vs TradFi prices, gaps, premiums → select: hl_prices + tradfi_reference
- Observation mentions market hours, weekends, holidays, tokenized assets → select: market_clock
- Observation mentions institutional positioning, COT → select: cot
- Crypto assets mentioned → consider: fear_greed
- Specific macro news event mentioned → consider: macro_news (use sparingly)
- Pure logical/structural hypothesis (no live numbers needed) → return empty tools list

Return ONLY valid JSON (no markdown, no extra text):
{{
  "reasoning": "One sentence: why these tools verify this specific edge",
  "tools": ["tool1", "tool2"],
  "hl_assets": ["BTC", "GOLD", "MSTR"],
  "tradfi_assets": ["GOLD", "MSTR"]
}}

Rules:
- tools: subset of [fear_greed, hl_prices, tradfi_reference, cot, market_clock, macro_news]
- hl_assets: assets to fetch HL prices for (all mentioned assets if hl_prices selected, else [])
- tradfi_assets: assets to compare vs Yahoo Finance (if tradfi_reference selected, else [])
"""


def _plan_data_fetch(note: str, asset_tags: list[str], edge_type: str, timeframe: str) -> dict:
    """Ask DeepSeek which data tools to use for this specific edge observation.

    Returns: {"tools": [...], "hl_assets": [...], "tradfi_assets": [...]}
    Falls back to a safe conservative default on error.
    """
    if not DEEPSEEK_KEY:
        # No key — use all-round defaults
        return {"tools": ["hl_prices", "tradfi_reference", "market_clock"],
                "hl_assets": asset_tags, "tradfi_assets": asset_tags,
                "reasoning": "No DeepSeek key — using defaults"}

    prompt = _PLANNER_PROMPT.format(
        note=note,
        assets=", ".join(asset_tags) or "not specified",
        edge_type=edge_type,
        timeframe=timeframe or "not specified",
    )
    print("[plan] AI dobiera narzędzia weryfikacji...")
    try:
        with _client() as c:
            r = c.post(
                f"{DEEPSEEK_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model":       DEEPSEEK_MODEL,
                    "messages":    [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens":  300,
                },
                timeout=30,
            )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        plan = _parse_ai_json(raw)

        tools        = plan.get("tools", [])
        hl_assets    = [t.upper() for t in plan.get("hl_assets", [])] or [t.upper() for t in asset_tags]
        tradfi_assets = [t.upper() for t in plan.get("tradfi_assets", [])]
        reasoning    = plan.get("reasoning", "")

        if tools:
            print(f"  [plan] {', '.join(tools)}")
        else:
            print("  [plan] Brak danych rynkowych — weryfikacja czysto logiczna")
        if reasoning:
            print(f"  [plan] {reasoning}")

        return {"tools": tools, "hl_assets": hl_assets,
                "tradfi_assets": tradfi_assets, "reasoning": reasoning}

    except Exception as e:
        print(f"[WARN] Planning failed ({e}) — using defaults")
        return {"tools": ["hl_prices", "tradfi_reference", "market_clock"],
                "hl_assets": [t.upper() for t in asset_tags],
                "tradfi_assets": [t.upper() for t in asset_tags]}


def gather_market_context(note: str, asset_tags: list[str], edge_type: str, timeframe: str) -> str:
    """Intelligently gather market data for AI edge verification.

    Step 1 — Planning: Ask DeepSeek which data sources are actually needed for THIS edge.
    Step 2 — Execution: Fetch only what was selected.

    This prevents wasted calls (e.g. fetching COT for a crypto funding edge)
    and ensures the verifier gets exactly the data it needs to give a good verdict.
    """
    parts: list[str] = []
    tags_upper = [t.upper() for t in asset_tags]

    # ── Step 1: planning ──────────────────────────────────────────────────────
    plan = _plan_data_fetch(note, asset_tags, edge_type, timeframe)
    tools         = set(plan.get("tools", []))
    hl_planned    = plan.get("hl_assets", tags_upper) or tags_upper
    tradfi_planned = plan.get("tradfi_assets", [])

    # If planner selected tradfi_reference but gave no assets, fall back to all tags
    if "tradfi_reference" in tools and not tradfi_planned:
        tradfi_planned = tags_upper

    # ── Step 2: execution ─────────────────────────────────────────────────────

    # Market hours — always included (free, always relevant context)
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    status_lines = [f"  Current UTC: {now_utc.strftime('%Y-%m-%d %H:%M')} ({now_utc.strftime('%A')})"]
    clock = _get_us_market_clock()
    if clock.get("is_open") is True:
        status_lines.append("  US stocks (NYSE/NASDAQ): OPEN")
        status_lines.append(f"  Closes at: {clock.get('next_close','?')}")
    elif clock.get("is_open") is False:
        reason = clock.get("reason", "")
        status_lines.append(f"  US stocks (NYSE/NASDAQ): CLOSED{(' — ' + reason) if reason else ''}")
        status_lines.append(f"  Next open: {clock.get('next_open','?')}")
    else:
        weekday = now_utc.weekday()
        hour = now_utc.hour
        if weekday >= 5:
            status_lines.append("  US stocks: CLOSED (weekend)")
        elif 13 <= hour < 21:
            status_lines.append("  US stocks: probably OPEN (weekday 13-21 UTC) — Alpaca unavailable")
        else:
            status_lines.append("  US stocks: probably CLOSED (off-hours) — Alpaca unavailable")
    parts.append("=== MARKET HOURS ===\n" + "\n".join(status_lines))

    # Fear & Greed
    if "fear_greed" in tools:
        print("  [data] Fear & Greed...")
        fg = _run_script("fear_greed.py", "--brief", timeout=15)
        if fg and "unavailable" not in fg:
            parts.append(f"=== FEAR & GREED INDEX ===\n{fg}")

    # HL live prices
    if "hl_prices" in tools and hl_planned:
        hl_known = [t for t in hl_planned if t in _HL_CRYPTO or t in _HL_XYZ or t in _HL_XYZ_STOCKS]
        if hl_known:
            print(f"  [data] HL prices: {', '.join(hl_known)}...")
            prices = _fetch_hl_prices(hl_known)
            if prices:
                parts.append(f"=== HYPERLIQUID LIVE PRICES (mark) ===\n{prices}")

    # TradFi reference — HL vs Yahoo Finance close + delta %
    if "tradfi_reference" in tools and tradfi_planned:
        all_ref = list(dict.fromkeys(tradfi_planned))
        print(f"  [data] TradFi vs HL delta: {', '.join(all_ref)}...")
        ref = _fetch_reference_prices(all_ref)
        if ref:
            parts.append(f"=== TRADFI LAST CLOSE vs HL PREMIUM/DISCOUNT ===\n{ref}")

    # COT institutional positioning
    if "cot" in tools:
        cot_relevant = [t for t in tags_upper if t in
                        {"GOLD","XAU","SILVER","XAG","USOIL","OIL","NQ","NASDAQ","SPX","SPX500","EUR"}]
        if cot_relevant:
            print(f"  [data] COT report ({', '.join(cot_relevant)})...")
            cot = _run_script("cot_tracker.py", "--brief", timeout=30)
            if cot and "unavailable" not in cot:
                parts.append(f"=== COT INSTITUTIONAL POSITIONING ===\n{cot[:800]}")

    # Macro news (expensive — only when AI planner explicitly selects it)
    if "macro_news" in tools:
        print("  [data] Macro news (Firecrawl)...")
        news = _run_script("macro_news.py", "--brief", timeout=45)
        if news and "unavailable" not in news:
            parts.append(f"=== MACRO NEWS (recent headlines) ===\n{news[:600]}")

    return "\n\n".join(parts)


# ── AI verification prompts ───────────────────────────────────────────────────
_DEEPSEEK_PROMPT = """\
You are a professional trading analyst with a skeptical, data-driven mindset.
A trader has shared a market observation/edge hypothesis. You have been given REAL live market data below.

YOUR JOB: Critically evaluate the observation using the actual data provided.
- Do NOT simply validate what the trader says
- Use the real numbers from the market data to confirm or contradict the claim
- If the data doesn't support the observation, say so clearly
- Look for alternative explanations, one-time events, data artifacts

TRADER'S OBSERVATION:
{note}

Assets: {assets}
Edge type: {edge_type}
Timeframe: {timeframe}

LIVE MARKET DATA (collected right now from real sources):
{market_data}

Return your analysis in EXACTLY this JSON format (no markdown, no extra text — just the JSON object):

{{
  "verdict": "VALID|QUESTIONABLE|INVALID",
  "confidence": 7,
  "data_check": "What do the real numbers say? Does the data confirm or contradict the observation?",
  "mechanism": "What is the underlying market mechanism? Why would/wouldn't this work structurally?",
  "trade_idea": "Concrete setup if actionable: which instrument, direction, entry condition, when to act. Or 'no setup' if not actionable.",
  "red_flags": "Specific reasons this could be wrong: data artifact, one-time event, correlation regime change, liquidity, etc.",
  "conditions": "Exact conditions needed for this edge to activate. What would invalidate it?"
}}
"""

_GROK_PROMPT = """\
You are a professional trading analyst. A trader shared a market observation.
Search X/Twitter for recent discussion and use your knowledge to evaluate it critically.
Do NOT simply validate what the trader says.

TRADER'S OBSERVATION:
{note}

Assets: {assets} | Edge type: {edge_type} | Timeframe: {timeframe}

Return EXACTLY this JSON (no markdown, just the object):

{{
  "verdict": "VALID|QUESTIONABLE|INVALID",
  "confidence": 7,
  "mechanism": "Underlying market mechanism",
  "facts_check": "What is factually correct vs questionable?",
  "trade_idea": "Specific trade setup or 'no setup'",
  "red_flags": "Reasons this could be wrong",
  "conditions": "Conditions needed + what would invalidate it"
}}
"""


def _parse_ai_json(raw_text: str) -> dict:
    """Extract JSON dict from model response (handles markdown fences etc.)."""
    j_start = raw_text.find("{")
    j_end   = raw_text.rfind("}") + 1
    if j_start >= 0 and j_end > j_start:
        try:
            return json.loads(raw_text[j_start:j_end])
        except json.JSONDecodeError:
            pass
    return {"mechanism": raw_text, "verdict": "QUESTIONABLE", "confidence": 5}


def _extract_responses_text(data: dict) -> str:
    """Parse xAI Responses API output format."""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return c.get("text", "")
    return ""


# ── Verification backends ─────────────────────────────────────────────────────
def verify_with_deepseek(
    note: str,
    asset_tags: list[str],
    edge_type: str,
    timeframe: str,
    market_data: str,
) -> dict:
    """Verify observation using DeepSeek + real market data. Cheap, no Twitter."""
    if not DEEPSEEK_KEY:
        print("[WARN] DEEPSEEK_API_KEY not set")
        return {}
    prompt = _DEEPSEEK_PROMPT.format(
        note=note,
        assets=", ".join(asset_tags) or "not specified",
        edge_type=edge_type,
        timeframe=timeframe,
        market_data=market_data or "(no market data collected)",
    )
    print("[AI] Analizuję z DeepSeek + live market data...")
    try:
        with _client() as c:
            r = c.post(
                f"{DEEPSEEK_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
                json={
                    "model":       DEEPSEEK_MODEL,
                    "messages":    [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens":  2500,
                },
                timeout=60,
            )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        return _parse_ai_json(raw)
    except Exception as e:
        print(f"[WARN] DeepSeek verification failed: {e}")
        return {}


def verify_with_grok(
    note: str,
    asset_tags: list[str],
    edge_type: str,
    timeframe: str,
) -> dict:
    """Verify using Grok + X/Twitter search. More expensive — use with --grok flag."""
    if not XAI_KEY:
        print("[WARN] XAI_API_KEY not set")
        return {}
    prompt = _GROK_PROMPT.format(
        note=note,
        assets=", ".join(asset_tags) or "not specified",
        edge_type=edge_type,
        timeframe=timeframe,
    )
    print("[AI] Weryfikuję przez Grok + X search...")
    try:
        with _client() as c:
            r = c.post(
                _GROK_RESPONSES_URL,
                headers={"Authorization": f"Bearer {XAI_KEY}", "Content-Type": "application/json"},
                json={
                    "model":             _GROK_MODEL,
                    "input":             [{"role": "user", "content": prompt}],
                    "tools":             [{"type": "x_search"}],
                    "temperature":       0.2,
                    "max_output_tokens": 1000,
                },
                timeout=60,
            )
        r.raise_for_status()
        raw = _extract_responses_text(r.json()).strip()
        return _parse_ai_json(raw)
    except Exception as e:
        print(f"[WARN] Grok verification failed: {e}")
        return {}


def run_verification(
    note: str,
    asset_tags: list[str],
    edge_type: str,
    timeframe: str,
    use_grok: bool = False,
    no_ai: bool = False,
    fetch_data: bool = False,
) -> tuple[dict, str]:
    """Main verification entry point. Returns (ai_result, market_data_text).

    fetch_data=False (default): DeepSeek verifies logic only — fast, no API calls.
    fetch_data=True  (--data) : AI planner decides which tools to call, fetches data, passes to verifier.
    use_grok=True    (--grok) : Uses Grok + X search instead of DeepSeek.
    no_ai=True       (--no-ai): Skips verification entirely.
    """
    if no_ai:
        return {}, ""

    market_data = ""
    if fetch_data:
        print("[data] Zbieram dane rynkowe (AI-guided)...")
        market_data = gather_market_context(note, asset_tags, edge_type, timeframe)

    if use_grok:
        ai = verify_with_grok(note, asset_tags, edge_type, timeframe)
    else:
        ai = verify_with_deepseek(note, asset_tags, edge_type, timeframe, market_data)

    return ai, market_data


# ── Context file generator ────────────────────────────────────────────────────
_STATUS_EMOJI = {
    "open":        "🔵",
    "confirmed":   "✅",
    "invalidated": "❌",
    "expired":     "⏰",
}

_VERDICT_EMOJI = {
    "VALID":        "✅",
    "QUESTIONABLE": "🟡",
    "INVALID":      "❌",
    "PENDING":      "⏳",
}


def _fmt_tags(raw: str | None) -> str:
    if not raw:
        return "—"
    try:
        return ", ".join(json.loads(raw))
    except Exception:
        return raw or "—"


def regenerate_context(db: DB) -> None:
    """Write context/my_edge.md with all open observations."""
    _CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    rows = db.get_edge_observations(limit=100)
    open_rows   = [r for r in rows if r.get("status") == "open"]
    closed_rows = [r for r in rows if r.get("status") != "open"][:10]

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# 🧠 MOJE EDGE — Obserwacje rynkowe",
        "",
        f"*Ostatnia aktualizacja: {now_str}*",
        "",
        "> **Instrukcja dla Hermes / Daily Brief:**",
        "> Te obserwacje to hipotezy tradera — weryfikuj je krytycznie.",
        "> Nie traktuj verdyktu AI jako pewnika. Sprawdzaj w aktualnym kontekście rynkowym.",
        "> Jeśli obserwacja jest VALID, uwzględnij ją w EXPERT VIEW.",
        "",
        "---",
        "",
    ]

    if open_rows:
        lines.append(f"## 🔵 Aktywne obserwacje ({len(open_rows)})")
        lines.append("")
        for r in open_rows:
            obs_id   = r["id"]
            tags     = _fmt_tags(r.get("asset_tags"))
            etype    = r.get("edge_type") or "other"
            tf       = r.get("timeframe") or "—"
            verdict  = r.get("ai_verdict") or "PENDING"
            conf     = r.get("ai_confidence")
            conf_str = f" {conf}/10" if conf else ""
            v_emoji  = _VERDICT_EMOJI.get(verdict, "⏳")
            created  = (r.get("created_at") or "")[:10]

            lines += [
                f"### #{obs_id} | {etype.upper()} | {tags}",
                f"**Data dodania:** {created} | **Timeframe:** {tf} | **AI Verdict:** {v_emoji} {verdict}{conf_str}",
                "",
                "**Moja obserwacja:**",
                r.get("raw_note", ""),
                "",
            ]
            if r.get("ai_analysis"):
                lines += ["**AI — Weryfikacja faktów:**", r["ai_analysis"], ""]
            if r.get("ai_trade_idea"):
                lines += ["**AI — Trade Idea:**", r["ai_trade_idea"], ""]
            if r.get("ai_red_flags"):
                lines += ["**AI — Red Flags:**", r["ai_red_flags"], ""]
            lines.append("---")
            lines.append("")
    else:
        lines += ["## 🔵 Aktywne obserwacje", "", "*Brak aktywnych obserwacji.*", "", "---", ""]

    if closed_rows:
        lines += ["", "## 📋 Ostatnio zamknięte obserwacje", ""]
        for r in closed_rows:
            obs_id  = r["id"]
            status  = r.get("status") or "closed"
            s_emoji = _STATUS_EMOJI.get(status, "⚫")
            tags    = _fmt_tags(r.get("asset_tags"))
            verdict = r.get("ai_verdict") or "—"
            created = (r.get("created_at") or "")[:10]
            pnl     = r.get("outcome_pnl")
            pnl_str = f" | PnL: {pnl:+.2f}$" if pnl is not None else ""
            note_short = (r.get("outcome_note") or "")[:120]
            lines += [
                f"- {s_emoji} **#{obs_id}** [{created}] {tags} — {verdict}{pnl_str}",
            ]
            if note_short:
                lines.append(f"  _{note_short}_")

    _CONTEXT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] Wygenerowano: {_CONTEXT_FILE}")


# ── Display helpers ───────────────────────────────────────────────────────────
def _print_observation(r: dict, verbose: bool = True) -> None:
    obs_id  = r["id"]
    status  = r.get("status") or "open"
    s_emoji = _STATUS_EMOJI.get(status, "⚫")
    verdict = r.get("ai_verdict") or "PENDING"
    v_emoji = _VERDICT_EMOJI.get(verdict, "⏳")
    conf    = r.get("ai_confidence")
    tags    = _fmt_tags(r.get("asset_tags"))
    etype   = r.get("edge_type") or "other"
    tf      = r.get("timeframe") or "—"
    created = (r.get("created_at") or "")[:16].replace("T", " ")

    print(f"\n{'─'*65}")
    print(f"  #{obs_id}  {s_emoji} {status.upper()}  |  {v_emoji} {verdict}"
          + (f" ({conf}/10)" if conf else ""))
    print(f"  Type: {etype}  |  Assets: {tags}  |  TF: {tf}")
    print(f"  Created: {created}")
    print(f"{'─'*65}")
    note = r.get("raw_note", "")
    print(textwrap.fill("  " + note, width=70, subsequent_indent="  "))

    if verbose:
        if r.get("ai_analysis"):
            print(f"\n  [AI Analysis]\n" + textwrap.fill("  " + r["ai_analysis"], 70, subsequent_indent="  "))
        if r.get("ai_trade_idea"):
            print(f"\n  [Trade Idea]\n" + textwrap.fill("  " + r["ai_trade_idea"], 70, subsequent_indent="  "))
        if r.get("ai_red_flags"):
            print(f"\n  [Red Flags]\n" + textwrap.fill("  " + r["ai_red_flags"], 70, subsequent_indent="  "))
        if r.get("outcome_note"):
            pnl = r.get("outcome_pnl")
            pnl_str = f"  PnL: {pnl:+.2f}$" if pnl is not None else ""
            print(f"\n  [Outcome]{pnl_str}\n  {r['outcome_note']}")


def _print_list(rows: list[dict]) -> None:
    if not rows:
        print("  Brak obserwacji.")
        return
    print(f"\n  {'#':>4}  {'Status':<12} {'Verdict':<14} {'Type':<15} {'Assets':<20} {'Date'}")
    print("  " + "─" * 78)
    for r in rows:
        obs_id  = r["id"]
        status  = r.get("status") or "open"
        verdict = r.get("ai_verdict") or "PENDING"
        conf    = r.get("ai_confidence")
        conf_s  = f"({conf})" if conf else "   "
        tags    = _fmt_tags(r.get("asset_tags"))[:18]
        etype   = (r.get("edge_type") or "other")[:13]
        date    = (r.get("created_at") or "")[:10]
        s_emoji = _STATUS_EMOJI.get(status, "⚫")
        v_emoji = _VERDICT_EMOJI.get(verdict, "⏳")
        print(f"  {obs_id:>4}  {s_emoji} {status:<10} {v_emoji} {verdict:<10} {conf_s:<3} "
              f"{etype:<15} {tags:<20} {date}")


# ── CLI commands ──────────────────────────────────────────────────────────────
def _apply_ai_result(obs_id: int, ai: dict, market_data: str, db: DB) -> None:
    """Save AI result to DB and print it."""
    if not ai:
        print("[WARN] AI verification zwróciło puste dane — obserwacja zapisana bez verdyktu.")
        return

    verdict    = ai.get("verdict", "QUESTIONABLE")
    conf       = ai.get("confidence", 5)
    # Build analysis text: data_check (DeepSeek) or facts_check (Grok) + mechanism
    analysis   = ai.get("data_check") or ai.get("facts_check") or ""
    mechanism  = ai.get("mechanism", "")
    if mechanism:
        analysis = (analysis + ("\n\nMechanizm: " + mechanism if analysis else mechanism)).strip()
    trade_idea = ai.get("trade_idea", "")
    red_flags  = ai.get("red_flags", "")
    conditions = ai.get("conditions", "")
    if conditions:
        red_flags = (red_flags + "\n\nWarunki: " + conditions).strip()

    db.update_edge_observation(
        obs_id,
        ai_verdict=verdict,
        ai_confidence=conf,
        ai_analysis=analysis,
        ai_trade_idea=trade_idea,
        ai_red_flags=red_flags,
    )

    v_emoji = _VERDICT_EMOJI.get(verdict, "⏳")
    print(f"\n{'═'*65}")
    print(f"  AI VERDICT: {v_emoji} {verdict}  ({conf}/10)")
    if analysis:
        print(f"\n  Analiza (dane + mechanizm):")
        print(textwrap.fill("  " + analysis, 70, subsequent_indent="  "))
    if trade_idea:
        print(f"\n  Trade Idea:")
        print(textwrap.fill("  " + trade_idea, 70, subsequent_indent="  "))
    if red_flags:
        print(f"\n  Red Flags:")
        print(textwrap.fill("  " + red_flags, 70, subsequent_indent="  "))
    print(f"{'═'*65}")


def cmd_add(args, db: DB) -> None:
    note      = args.note
    etype     = args.type or "other"
    tags      = args.assets or []
    timeframe = args.timeframe or ""

    # Save to DB first (status open, no AI yet)
    obs_id = db.save_edge_observation(
        raw_note=note,
        asset_tags=tags,
        edge_type=etype,
        timeframe=timeframe,
    )
    print(f"\n[OK] Obserwacja #{obs_id} zapisana.")

    # Verification: gather live data + AI analysis
    use_grok   = getattr(args, "grok", False)
    no_ai      = getattr(args, "no_ai", False)
    fetch_data = getattr(args, "data", False)
    ai, market_data = run_verification(note, tags, etype, timeframe,
                                       use_grok=use_grok, no_ai=no_ai,
                                       fetch_data=fetch_data)
    if not no_ai:
        _apply_ai_result(obs_id, ai, market_data, db)

    regenerate_context(db)
    obs = db.get_edge_observation(obs_id)
    if obs:
        _print_observation(obs)


def cmd_list(args, db: DB) -> None:
    status = None if args.all else (args.status or "open")
    rows = db.get_edge_observations(status=status, limit=50)
    label = "wszystkie" if args.all else f"status={status}"
    print(f"\n=== Edge Journal ({label}) — {len(rows)} obserwacji ===")
    _print_list(rows)
    print()


def cmd_view(args, db: DB) -> None:
    obs = db.get_edge_observation(args.id)
    if not obs:
        print(f"[ERR] Obserwacja #{args.id} nie istnieje.")
        sys.exit(1)
    _print_observation(obs, verbose=True)
    print()


def cmd_close(args, db: DB) -> None:
    obs = db.get_edge_observation(args.id)
    if not obs:
        print(f"[ERR] Obserwacja #{args.id} nie istnieje.")
        sys.exit(1)
    updates: dict = {
        "status":       "confirmed",
        "outcome_note": args.result,
    }
    if args.pnl is not None:
        updates["outcome_pnl"] = args.pnl
    db.update_edge_observation(args.id, **updates)
    regenerate_context(db)
    print(f"\n[OK] Obserwacja #{args.id} zamknięta jako CONFIRMED.")
    if args.pnl is not None:
        print(f"     PnL: {args.pnl:+.2f}$")


def cmd_invalidate(args, db: DB) -> None:
    obs = db.get_edge_observation(args.id)
    if not obs:
        print(f"[ERR] Obserwacja #{args.id} nie istnieje.")
        sys.exit(1)
    reason = args.reason or ""
    prev   = obs.get("outcome_note") or ""
    note   = (prev + "\nINVALIDATED: " + reason).strip() if reason else prev
    db.update_edge_observation(args.id, status="invalidated", outcome_note=note)
    regenerate_context(db)
    print(f"\n[OK] Obserwacja #{args.id} oznaczona jako INVALIDATED.")


def cmd_expire(args, db: DB) -> None:
    obs = db.get_edge_observation(args.id)
    if not obs:
        print(f"[ERR] Obserwacja #{args.id} nie istnieje.")
        sys.exit(1)
    db.update_edge_observation(args.id, status="expired")
    regenerate_context(db)
    print(f"\n[OK] Obserwacja #{args.id} oznaczona jako EXPIRED.")


def cmd_recheck(args, db: DB) -> None:
    """Re-run AI verification with fresh live market data."""
    obs = db.get_edge_observation(args.id)
    if not obs:
        print(f"[ERR] Obserwacja #{args.id} nie istnieje.")
        sys.exit(1)

    tags      = json.loads(obs.get("asset_tags") or "[]")
    etype     = obs.get("edge_type") or "other"
    timeframe = obs.get("timeframe") or ""
    use_grok   = getattr(args, "grok", False)
    fetch_data = getattr(args, "data", False)

    ai, market_data = run_verification(obs["raw_note"], tags, etype, timeframe,
                                       use_grok=use_grok, fetch_data=fetch_data)
    _apply_ai_result(args.id, ai, market_data, db)
    regenerate_context(db)
    obs = db.get_edge_observation(args.id)
    if obs:
        _print_observation(obs)


def cmd_context(args, db: DB) -> None:
    regenerate_context(db)
    print(f"\n[Preview] {_CONTEXT_FILE}\n")
    print(_CONTEXT_FILE.read_text(encoding="utf-8"))


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Edge Journal — moje obserwacje rynkowe z AI weryfikacją",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="Dodaj nową obserwację")
    p_add.add_argument("note", help="Treść obserwacji (tekst w cudzysłowie)")
    p_add.add_argument("--type", dest="type", default="other",
                       choices=["weekend_arb", "divergence", "funding", "macro", "pattern", "other"],
                       help="Typ edge'a")
    p_add.add_argument("--assets", nargs="+", metavar="ASSET",
                       help="Aktywa, np. --assets BTC GOLD USOIL")
    p_add.add_argument("--timeframe", default="",
                       help="Timeframe: weekend | intraday | swing | multi-day")
    p_add.add_argument("--data", action="store_true",
                       help="Pobierz live dane rynkowe (HL ceny, COT, F&G) przed weryfikacją")
    p_add.add_argument("--no-ai", action="store_true",
                       help="Pomiń AI verification (szybko, zero kosztu)")
    p_add.add_argument("--grok", action="store_true",
                       help="Użyj Grok + X search zamiast DeepSeek (drożej, ale szuka na Twitterze)")

    # list
    p_list = sub.add_parser("list", help="Lista obserwacji")
    p_list.add_argument("--status", default="open",
                        help="Filtr statusu: open | confirmed | invalidated | expired")
    p_list.add_argument("--all", action="store_true", help="Pokaż wszystkie statusy")

    # view
    p_view = sub.add_parser("view", help="Szczegóły obserwacji")
    p_view.add_argument("id", type=int, help="ID obserwacji")

    # close (confirm)
    p_close = sub.add_parser("close", help="Zamknij obserwację jako potwierdzoną")
    p_close.add_argument("id", type=int, help="ID obserwacji")
    p_close.add_argument("--result", default="", help="Co się stało / opis wyniku")
    p_close.add_argument("--pnl", type=float, default=None, help="Zrealizowany PnL w USD")

    # invalidate
    p_inv = sub.add_parser("invalidate", help="Oznacz obserwację jako nieprawidłową")
    p_inv.add_argument("id", type=int, help="ID obserwacji")
    p_inv.add_argument("--reason", default="", help="Powód inwalidacji")

    # expire
    p_exp = sub.add_parser("expire", help="Oznacz obserwację jako wygasłą")
    p_exp.add_argument("id", type=int, help="ID obserwacji")

    # recheck
    p_recheck = sub.add_parser("recheck", help="Ponowna weryfikacja AI z aktualnymi danymi")
    p_recheck.add_argument("id", type=int, help="ID obserwacji")
    p_recheck.add_argument("--data", action="store_true",
                           help="Pobierz live dane rynkowe przed weryfikacją")
    p_recheck.add_argument("--grok", action="store_true",
                           help="Użyj Grok + X search zamiast DeepSeek")

    # context
    sub.add_parser("context", help="Wygeneruj/podgląd context/my_edge.md")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    db = DB()

    dispatch = {
        "add":        cmd_add,
        "list":       cmd_list,
        "view":       cmd_view,
        "close":      cmd_close,
        "invalidate": cmd_invalidate,
        "expire":     cmd_expire,
        "recheck":    cmd_recheck,
        "context":    cmd_context,
    }
    dispatch[args.command](args, db)


if __name__ == "__main__":
    main()
