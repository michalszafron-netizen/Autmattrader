"""X (Twitter) sentiment layer via Grok API — live X search.

Windows SSL fix: gRPC BoringSSL lacks AIA fetching.
We build a combined CA bundle from certifi + Windows cert store (ROOT + CA),
which includes intermediates cached by Windows after any prior HTTPS connection.
This must be applied BEFORE importing xai_sdk (which initializes gRPC channels).

Pricing (grok-4.3, May 2026):
  Input: $1.25 / 1M tokens | Output: $2.50 / 1M tokens
  Est. ~$0.005-0.010 per asset (live search) | discovery ~$0.015

Usage:
  python scripts/x_sentiment.py                     # crypto: BTC ETH HYPE (live)
  python scripts/x_sentiment.py --group macro        # gold silver oil indices
  python scripts/x_sentiment.py --group all          # crypto + macro
  python scripts/x_sentiment.py --coins BTC XAU SPX  # custom mix
  python scripts/x_sentiment.py trending             # discover trending tokens
  python scripts/x_sentiment.py --hours 48           # look back 48h (default 24)
  python scripts/x_sentiment.py --no-live            # fallback to knowledge-based
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import ssl
import sys
from pathlib import Path

# ── Windows gRPC SSL fix (must happen before xai_sdk import) ─────────────────
# gRPC BoringSSL doesn't do AIA fetching; Windows cert store has cached intermediates.

def _build_windows_ca_bundle() -> bytes:
    import certifi
    parts = []
    with open(certifi.where(), "r") as f:
        parts.append(f.read())
    for store in ["ROOT", "CA"]:
        try:
            for cert_data, enc, _ in ssl.enum_certificates(store):
                if enc == "x509_asn":
                    try:
                        parts.append(ssl.DER_cert_to_PEM_cert(cert_data))
                    except Exception:
                        pass
        except Exception:
            pass
    return "\n".join(parts).encode()


def _patch_grpc_ssl() -> None:
    import grpc
    _ca_bundle = _build_windows_ca_bundle()
    _orig = grpc.ssl_channel_credentials

    def _patched(root_certificates=None, private_key=None, certificate_chain=None):
        if root_certificates is None:
            root_certificates = _ca_bundle
        return _orig(root_certificates, private_key, certificate_chain)

    grpc.ssl_channel_credentials = _patched


_patch_grpc_ssl()

# ── Now safe to import xai_sdk ────────────────────────────────────────────────
import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from xai_sdk import Client
from xai_sdk.chat import user as xai_user
from xai_sdk.chat import system as xai_system
from xai_sdk.tools import x_search, web_search

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.getenv("XAI_API_KEY", "")
BASE_URL = "https://api.x.ai/v1"
MODEL = "grok-4.3"

console = Console(highlight=False)
_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


# ── Asset config ──────────────────────────────────────────────────────────────

CRYPTO_DEFAULT = ["BTC", "ETH", "SOL", "HYPE", "LINK"]
MACRO_ASSETS = ["GOLD", "SILVER", "OIL", "SPX", "NDX", "DXY",
                "CORN", "COFFEE", "COCOA", "SUGAR"]

ASSET_LABELS = {
    "BTC": "Bitcoin $BTC",
    "ETH": "Ethereum $ETH",
    "HYPE": "$HYPE Hyperliquid",
    "SOL": "Solana $SOL",
    "GOLD": "Gold XAU precious metals",
    "XAU": "Gold XAU precious metals",
    "SILVER": "Silver XAG precious metals",
    "XAG": "Silver XAG precious metals",
    "OIL": "crude oil WTI Brent energy prices",
    "WTI": "crude oil WTI Brent energy prices",
    "SPX": "S&P 500 SPX US equities",
    "NDX": "Nasdaq NDX QQQ tech stocks",
    "DXY": "US Dollar DXY dollar index",
}

MACRO_SET = {"GOLD", "XAU", "SILVER", "XAG", "OIL", "WTI", "SPX", "NDX", "DXY"}


# ── Prompts ───────────────────────────────────────────────────────────────────

LIVE_CRYPTO_PROMPT = """\
Search X (Twitter) for recent posts about {label} from the last {hours} hours.

Analyze sentiment from: traders, analysts, on-chain watchers (ideally 1k+ followers).
Ignore obvious spam/bots.

Return ONLY valid JSON, no markdown, no extra text:
{{
  "coin": "{coin}",
  "sentiment_score": <1-10, 1=extreme fear, 10=extreme greed>,
  "sentiment_label": "<bearish|neutral|bullish>",
  "signal_strength": "<weak|moderate|strong>",
  "top_narratives": ["<what people are actually talking about — 3 items>"],
  "real_posts": [
    {{"handle": "@realhandle", "quote": "exact quote or close paraphrase", "tag": "bullish|bearish|neutral"}},
    {{"handle": "@realhandle2", "quote": "exact quote", "tag": "bullish|bearish|neutral"}}
  ],
  "warning_flags": ["<pump signals, coordinated activity, or empty string>"],
  "key_levels_mentioned": ["<e.g. $50 resistance, $45 support>"]
}}
"""

LIVE_MACRO_PROMPT = """\
Search X (Twitter) and financial news for recent posts about {label} from the last {hours} hours.
Focus on: macro analysts, commodity traders, FinTwit, Fed watchers (1k+ followers).

Return ONLY valid JSON, no markdown:
{{
  "coin": "{coin}",
  "sentiment_score": <1-10, 1=extreme bearish, 10=extreme bullish>,
  "sentiment_label": "<bearish|neutral|bullish>",
  "signal_strength": "<weak|moderate|strong>",
  "top_narratives": ["<3 dominant themes on X right now>"],
  "real_posts": [
    {{"handle": "@handle", "quote": "exact quote", "tag": "bullish|bearish|neutral"}},
    {{"handle": "@handle2", "quote": "exact quote", "tag": "bullish|bearish|neutral"}}
  ],
  "macro_context": "<1 sentence: macro regime relevance>",
  "key_levels_mentioned": ["<e.g. $2400 gold support>"],
  "warning_flags": ["<extreme positioning, contrarian signals, or empty string>"]
}}
"""

TRENDING_PROMPT = """\
Search X (Twitter) for crypto tokens getting UNUSUAL buzz right now that are NOT
in the top 20 by market cap (exclude BTC, ETH, BNB, SOL, XRP, USDT, USDC, etc.).

Look for: viral threads today, influencer callouts, sudden narrative emergence.

CRITICAL: For EVERY token, try hard to find its contract address or mint address.
- Ethereum/Base/BSC tokens: look for 0x... address in posts or replies
- Solana tokens: look for base58 mint address (44 chars) in posts, pump.fun links, or DexScreener
- TON tokens: look for EQ... or UQ... address in posts
- If you find it in a post or know it — include it in contract_address field
- If you cannot find it — leave contract_address as empty string ""

Return ONLY valid JSON:
{{
  "scan_date": "{date}",
  "trending_tokens": [
    {{
      "token": "<TICKER e.g. VIRL>",
      "name": "<full project name e.g. Viral>",
      "chain": "<blockchain e.g. Solana, Base, Ethereum, TON>",
      "contract_address": "<contract/mint address if found, else empty string>",
      "what_it_does": "<1 sentence: what this project actually is/does>",
      "buzz_score": <1-10>,
      "sentiment": "<bullish|bearish|neutral>",
      "why_trending": "<2-3 sentences: exact reason trending NOW, what happened>",
      "risk_level": "<low|medium|high>",
      "sample_post": "<real quote or paraphrase of actual X post driving buzz>",
      "where_to_find": "<DexScreener/pump.fun/CMC link or 'Search $TICKER on X'>",
      "mentions_24h": <estimated number of X posts/mentions about this token in last 24h, integer>,
      "top_post_likes": <likes on the single most viral post you found, integer or 0 if unknown>,
      "top_post_retweets": <retweets/reposts on that same viral post, integer or 0 if unknown>,
      "top_post_author": "<@handle of the most viral post author, or empty string>",
      "engagement_trend": "<rising|stable|falling — is buzz growing or fading in last few hours?>"
    }}
  ],
  "sector_hotspots": ["<e.g. AI agents, DePIN, RWA>"],
  "fading_narratives": ["<what was hot yesterday but fading today>"]
}}
Return 5-7 tokens. Be specific — real names, real reasons, real posts.
"""

# Fallback prompt (no live search)
KNOWLEDGE_PROMPT = """\
Analyze recent X/Twitter discourse about {label} based on your training data.
Return ONLY valid JSON (same format as live), but add a field
"data_source": "training_data" to flag this is not real-time.

{{
  "coin": "{coin}",
  "sentiment_score": <1-10>,
  "sentiment_label": "<bearish|neutral|bullish>",
  "signal_strength": "<weak|moderate|strong>",
  "top_narratives": ["<3 items>"],
  "real_posts": [],
  "warning_flags": [""],
  "key_levels_mentioned": [],
  "data_source": "training_data"
}}
"""


# ── API helpers ───────────────────────────────────────────────────────────────

def _strip_emoji(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii").replace("?", " ").strip()


def _parse_json(raw: str) -> dict:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Try to find JSON object in response
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(clean[start:end])
        raise


def query_live(coin: str, hours: int = 24) -> dict:
    label = ASSET_LABELS.get(coin.upper(), coin)
    is_macro = coin.upper() in MACRO_SET
    prompt_tmpl = LIVE_MACRO_PROMPT if is_macro else LIVE_CRYPTO_PROMPT
    prompt = prompt_tmpl.format(coin=coin.upper(), label=label, hours=hours)

    from_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    client = Client(api_key=API_KEY)
    tools = [x_search(from_date=from_dt), web_search()] if is_macro else [x_search(from_date=from_dt)]
    chat = client.chat.create(model=MODEL, tools=tools)
    chat.append(xai_system(
        "You are a market sentiment analyst. "
        "Return ONLY valid JSON. No markdown fences. No extra text."
    ))
    chat.append(xai_user(prompt))

    raw = ""
    for _, chunk in chat.stream():
        if chunk.content:
            raw += chunk.content

    try:
        return _parse_json(raw)
    except Exception:
        return {
            "coin": coin, "sentiment_score": 5, "sentiment_label": "neutral",
            "signal_strength": "weak", "top_narratives": ["parse error"],
            "real_posts": [], "warning_flags": ["JSON parse failed"],
            "key_levels_mentioned": [], "_raw": raw[:200],
        }


def query_knowledge(coin: str) -> dict:
    label = ASSET_LABELS.get(coin.upper(), coin)
    prompt = KNOWLEDGE_PROMPT.format(coin=coin.upper(), label=label)
    with httpx.Client(verify=_SSL_CTX, timeout=60.0) as client:
        r = client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "Output JSON only. No markdown."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1, "max_tokens": 700,
            },
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
    try:
        return _parse_json(raw)
    except Exception:
        return {"coin": coin, "sentiment_score": 5, "sentiment_label": "neutral",
                "signal_strength": "weak", "top_narratives": [], "real_posts": [],
                "warning_flags": [], "key_levels_mentioned": []}


ENGAGEMENT_VERIFY_PROMPT = """\
Search X for posts about ${ticker} from last 72 hours (3 days).
I need a day-by-day breakdown to see the trend.

Count actual posts you find in search results — do NOT estimate or guess counts.

Return ONLY valid JSON:
{{
  "ticker": "{ticker}",
  "days": [
    {{
      "label": "3 dni temu",
      "mentions": <count of posts from ~48-72h ago that you actually found>,
      "top_likes": <max likes on any post that day>,
      "top_rt": <max retweets on any post that day>
    }},
    {{
      "label": "2 dni temu",
      "mentions": <count from ~24-48h ago>,
      "top_likes": <int>,
      "top_rt": <int>
    }},
    {{
      "label": "wczoraj",
      "mentions": <count from ~0-24h ago>,
      "top_likes": <int>,
      "top_rt": <int>
    }}
  ],
  "top_posts": [
    {{
      "author": "@handle",
      "likes": <int>,
      "retweets": <int>,
      "views": <int or 0>,
      "text": "<first 100 chars>"
    }}
  ],
  "engagement_trend": "<rising|stable|falling>",
  "total_72h": <total mentions across all 3 days>
}}
"""


def verify_engagement(ticker: str) -> dict:
    """Fetch REAL engagement data with 3-day day-by-day breakdown."""
    from_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=72)
    client = Client(api_key=API_KEY)
    chat = client.chat.create(model=MODEL, tools=[x_search(from_date=from_dt)])
    prompt = ENGAGEMENT_VERIFY_PROMPT.format(ticker=ticker)
    chat.append(xai_system("Output JSON only. No markdown fences."))
    chat.append(xai_user(prompt))
    raw = ""
    for _, chunk in chat.stream():
        if chunk.content:
            raw += chunk.content
    try:
        return _parse_json(raw)
    except Exception:
        return {}


def _load_trending_context() -> str:
    """Load 7-day trending history from DB for context injection."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from db import DB
        return DB().get_trending_context(days=7)
    except Exception:
        return ""


def query_trending(hours: int = 24) -> dict:
    from_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    client = Client(api_key=API_KEY)
    chat = client.chat.create(model=MODEL, tools=[x_search(from_date=from_dt)])

    history_ctx = _load_trending_context()
    base_prompt = TRENDING_PROMPT.format(date=datetime.datetime.now().strftime("%Y-%m-%d"))
    if history_ctx:
        prompt = history_ctx + "\n\n" + base_prompt
    else:
        prompt = base_prompt
    chat.append(xai_system("Output JSON only. No markdown."))
    chat.append(xai_user(prompt))
    raw = ""
    for _, chunk in chat.stream():
        if chunk.content:
            raw += chunk.content
    try:
        data = _parse_json(raw)
    except Exception:
        return {"trending_tokens": [], "sector_hotspots": [], "fading_narratives": []}

    # Verify engagement for top 3 tokens with real live search
    tokens = data.get("trending_tokens", [])
    console.print(f"[dim]Weryfikuje zaangazowanie dla top {min(3, len(tokens))} tokenow...[/dim]")
    for t in tokens[:3]:
        ticker = t.get("token", "")
        if not ticker:
            continue
        verified = verify_engagement(ticker)
        if verified:
            t["_engagement_verified"] = True
            t["_days"]              = verified.get("days", [])
            t["mentions_24h"]       = verified.get("total_72h", t.get("mentions_24h", 0))
            t["engagement_trend"]   = verified.get("engagement_trend", t.get("engagement_trend", ""))
            real_posts = verified.get("top_posts", [])
            if real_posts:
                t["top_post_likes"]    = real_posts[0].get("likes", 0)
                t["top_post_retweets"] = real_posts[0].get("retweets", 0)
                t["top_post_author"]   = real_posts[0].get("author", "")
                t["_real_posts"]       = real_posts

    return data


# ── Display ───────────────────────────────────────────────────────────────────

def score_color(score: int) -> str:
    return "green" if score >= 7 else "red" if score <= 3 else "yellow"


def display_asset(result: dict) -> None:
    coin = result.get("coin", "?")
    score = result.get("sentiment_score", 5)
    label = result.get("sentiment_label", "neutral").upper()
    strength = result.get("signal_strength", "?")
    color = score_color(score)
    is_live = "data_source" not in result

    narratives = "\n".join(f"  * {_strip_emoji(n)}" for n in result.get("top_narratives", []))

    posts = result.get("real_posts", [])
    post_lines = ""
    for t in posts[:3]:
        tag = t.get("tag", "neutral")
        tc = "green" if tag == "bullish" else "red" if tag == "bearish" else "dim"
        handle = _strip_emoji(t.get("handle", "?"))
        quote = _strip_emoji(t.get("quote", ""))[:90]
        post_lines += f"  [{tc}]{handle}[/{tc}]: {quote}\n"

    macro_ctx = _strip_emoji(result.get("macro_context", ""))
    macro_line = f"\n[dim]Macro: {macro_ctx}[/dim]" if macro_ctx else ""

    warnings = [_strip_emoji(w) for w in result.get("warning_flags", []) if w]
    warn_text = ("\n[bold red]!! " + " | ".join(warnings) + "[/bold red]") if warnings else ""

    levels = result.get("key_levels_mentioned", [])
    levels_text = ("\n[dim]Levels: " + ", ".join(levels) + "[/dim]") if levels else ""

    src_tag = "[green]LIVE[/green]" if is_live else "[yellow]training data[/yellow]"

    body = (
        f"[{color}][bold]{label}[/bold] — {score}/10[/{color}]  "
        f"|  Signal: {strength}  |  {src_tag}\n\n"
        f"[bold]Narratives:[/bold]\n{narratives}\n\n"
        f"[bold]Real posts:[/bold]\n{post_lines}"
        f"{macro_line}{warn_text}{levels_text}"
    )
    console.print(Panel(body, title=f"[bold cyan]X — {coin}[/bold cyan]", expand=False))


def display_trending(data: dict) -> None:
    tokens = data.get("trending_tokens", [])
    sectors = data.get("sector_hotspots", [])
    fading = data.get("fading_narratives", [])

    if sectors:
        console.print(f"\n[bold]Hot sectors:[/bold] {', '.join(sectors)}")
    if fading:
        console.print(f"[dim]Fading: {', '.join(fading)}[/dim]")

    console.print()

    for i, t in enumerate(tokens, 1):
        token   = t.get("token", "?")
        name    = t.get("name", "")
        chain   = t.get("chain", "")
        what    = _strip_emoji(t.get("what_it_does", ""))
        why     = _strip_emoji(t.get("why_trending", ""))
        post    = _strip_emoji(t.get("sample_post", ""))
        find    = t.get("where_to_find", "")
        ca          = t.get("contract_address", "").strip()
        mentions    = t.get("mentions_24h", 0)
        top_likes   = t.get("top_post_likes", 0)
        top_rt      = t.get("top_post_retweets", 0)
        top_author  = t.get("top_post_author", "")
        eng_trend   = t.get("engagement_trend", "")
        buzz    = t.get("buzz_score", 5)
        sent    = t.get("sentiment", "neutral")
        risk    = t.get("risk_level", "?")

        bc = score_color(buzz)
        sc = "green" if sent == "bullish" else "red" if sent == "bearish" else "yellow"
        rc = "red" if risk == "high" else "yellow" if risk == "medium" else "green"

        # is_verified needs to be defined before token age lookup
        is_verified = t.get("_engagement_verified", False)

        # Token age from DexScreener via CA
        token_age = ""
        ca_for_age = t.get("contract_address", "").strip()
        if ca_for_age and is_verified:
            import httpx as _hx, ssl as _ssl, truststore as _ts
            try:
                _ctx = _ts.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
                _r = _hx.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca_for_age}",
                             verify=_ctx, timeout=8)
                _pairs = _r.json().get("pairs", [])
                if _pairs:
                    created_ms = _pairs[0].get("pairCreatedAt", 0)
                    if created_ms:
                        import time as _t
                        age_days = (_t.time() - created_ms/1000) / 86400
                        if age_days < 1:
                            token_age = f"[yellow]{age_days*24:.0f}h stary[/yellow]"
                        elif age_days < 7:
                            token_age = f"[yellow]{age_days:.0f}d stary[/yellow]"
                        else:
                            token_age = f"[dim]{age_days:.0f}d stary[/dim]"
            except Exception:
                pass

        title = f"[bold cyan]#{i} ${token}[/bold cyan]"
        if name:
            title += f" [dim]({name})[/dim]"
        if chain:
            title += f"  [dim]{chain}[/dim]"
        if token_age:
            title += f"  {token_age}"

        # Engagement stats line
        eng_parts = []
        if mentions:
            prefix = "" if is_verified else "~est "
            eng_parts.append(f"Wzmianki 24h: {prefix}{mentions:,}")
        if top_likes:   eng_parts.append(f"Top post: {top_likes:,} lajkow")
        if top_rt:      eng_parts.append(f"{top_rt:,} RT")
        if top_author:  eng_parts.append(f"autor: {top_author}")
        if eng_trend:
            trend_color = "green" if eng_trend == "rising" else "red" if eng_trend == "falling" else "yellow"
            trend_label = {"rising": "rosnie", "falling": "spada", "stable": "stabilny"}.get(eng_trend, eng_trend)
            eng_parts.append(f"[{trend_color}]trend: {trend_label}[/{trend_color}]")
        if is_verified:
            eng_parts.append("[green]verified[/green]")
        eng_line = "  |  ".join(eng_parts) if eng_parts else ""

        lines = []

        # 1. NARRACJA — priorytet
        lines.append(f"[{bc}]Buzz {buzz}/10[/{bc}]  [{sc}]{sent.upper()}[/{sc}]  risk=[{rc}]{risk}[/{rc}]")
        if what:
            lines.append(f"[bold]Co robi:[/bold] {what}")
        if why:
            lines.append(f"[bold]Dlaczego trending:[/bold] {why}")
        if post:
            lines.append(f"[dim italic]Post: \"{post}\"[/dim italic]")

        # 2. KONTRAKT
        if ca:
            lines.append(f"[bold cyan]Kontrakt: {ca}[/bold cyan]")
        elif find:
            lines.append(f"[bold]Gdzie szukac:[/bold] {find}")

        # 3. METRYKI — na dole jako kontekst
        lines.append("")  # separator
        # 3-day trend
        days_data = t.get("_days", [])
        if days_data and is_verified:
            day_parts = []
            for d in days_data:
                m = d.get("mentions", 0)
                lk = d.get("top_likes", 0)
                lbl = d.get("label", "?")
                day_parts.append(f"{lbl}: {m}p/{lk}lk")
            lines.append(f"[dim]X trend 3d: {' -> '.join(day_parts)}[/dim]")

        if eng_line:
            note = "[dim](sample z live search — nie total)[/dim]" if is_verified else "[dim](estymacja modelu)[/dim]"
            lines.append(f"[dim]X stats: {eng_line}[/dim]  {note}")

        console.print(Panel("\n".join(lines), title=title, expand=False))
    console.print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not API_KEY:
        console.print("[red]XAI_API_KEY not set in .env[/red]")
        sys.exit(1)

    p = argparse.ArgumentParser(description="X/FinTwit live sentiment via Grok")
    sub = p.add_subparsers(dest="cmd")

    # sentiment (default)
    sent_p = sub.add_parser("sentiment", help="Asset sentiment with live X search")
    sent_p.add_argument("--coins", nargs="+", metavar="COIN")
    sent_p.add_argument("--group", choices=["crypto", "macro", "all"], default="crypto")
    sent_p.add_argument("--hours", type=int, default=24)
    sent_p.add_argument("--no-live", action="store_true", help="Skip live search, use knowledge")

    # trending
    trend_p = sub.add_parser("trending", help="Discover trending tokens on X (live)")
    trend_p.add_argument("--hours", type=int, default=24)

    args = p.parse_args()
    cmd = args.cmd or "sentiment"
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tz_utils import now_pl, pl_label
        import datetime as _dt
        _u = datetime.datetime.now(_dt.timezone.utc)
        now = f"{_u.strftime('%Y-%m-%d %H:%M')} UTC / {now_pl().strftime('%H:%M')} {pl_label(_u)}"
    except Exception:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    if cmd == "trending":
        console.print(f"\n[bold]X Trending Discovery — LIVE[/bold] ({now})\n")
        console.print("Searching X for trending tokens...", end=" ")
        try:
            data = query_trending(hours=getattr(args, "hours", 24))
            console.print("[green]OK[/green]")
            display_trending(data)
            # ── Save to DB ──
            try:
                import sys as _sys
                _sys.path.insert(0, str(Path(__file__).parent))
                from db import DB
                _db = DB()
                tokens_to_save = []
                for i, t in enumerate(data.get("trending_tokens", []), 1):
                    tokens_to_save.append({
                        "rank": i,
                        "ticker": t.get("token", ""),
                        "name": t.get("name", ""),
                        "chain": t.get("chain", ""),
                        "contract": t.get("contract_address", ""),
                        "buzz_score": t.get("buzz_score"),
                        "sentiment": t.get("sentiment", ""),
                        "risk": t.get("risk_level", ""),
                        "mentions_24h": t.get("mentions_24h"),
                        "top_post_likes": t.get("top_post_likes"),
                        "top_post_rts": t.get("top_post_retweets"),
                        "top_post_author": t.get("top_post_author", ""),
                        "engagement_trend": t.get("engagement_trend", ""),
                        "is_verified": t.get("_engagement_verified", False),
                    })
                if tokens_to_save:
                    _db.save_trending(tokens_to_save)
            except Exception as _dbe:
                pass  # DB errors never interrupt display
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in ["credit", "quota", "limit", "rate", "429", "billing", "insufficient"]):
                console.print("[yellow]LIMIT KREDYTOW xAI — brak live X search dla trending[/yellow]")
                console.print("[dim]Trending scan wymaga kredytow X search. Odnow na https://console.x.ai[/dim]")
                console.print("[dim]Mozna sprobowac: python scripts/x_sentiment.py sentiment --no-live[/dim]")
            else:
                console.print(f"[red]{e}[/red]")
        return

    # sentiment mode
    if hasattr(args, "coins") and args.coins:
        coins = [c.upper() for c in args.coins]
    elif hasattr(args, "group"):
        if args.group == "macro":
            coins = MACRO_ASSETS
        elif args.group == "all":
            coins = CRYPTO_DEFAULT + MACRO_ASSETS
        else:
            coins = CRYPTO_DEFAULT
    else:
        coins = CRYPTO_DEFAULT

    hours = getattr(args, "hours", 24)
    no_live = getattr(args, "no_live", False)
    mode = "knowledge-based" if no_live else f"LIVE X search ({hours}h window)"

    console.print(f"\n[bold]X Sentiment[/bold] — {now}  [{mode}]\n"
                  f"[dim]Assets: {', '.join(coins)}[/dim]\n")

    _credits_exhausted = False
    results = []
    for coin in coins:
        console.print(f"  {coin}...", end=" ")
        try:
            result = query_knowledge(coin) if (no_live or _credits_exhausted) else query_live(coin, hours)
            console.print("[green]OK[/green]")
            results.append(result)
        except Exception as e:
            err_str = str(e).lower()
            # Detect credit/quota exhaustion — switch to knowledge fallback for remaining coins
            if any(kw in err_str for kw in ["credit", "quota", "limit", "rate", "429", "billing", "insufficient"]):
                _credits_exhausted = True
                console.print(f"[yellow]LIMIT KREDYTOW — przelaczam na tryb bez live search[/yellow]")
                try:
                    result = query_knowledge(coin)
                    result["data_source"] = "training_data_fallback"
                    console.print("[yellow]OK (training data)[/yellow]")
                    results.append(result)
                except Exception as e2:
                    console.print(f"[red]fallback tez nie dziala: {e2}[/red]")
            else:
                console.print(f"[red]{e}[/red]")

    if _credits_exhausted:
        console.print("[yellow]\nUWAGA: Kredyty xAI wyczerpane. Sentiment oparty na danych treningowych (brak live X search).[/yellow]")
        console.print("[dim]Aby odnowic: https://console.x.ai — doladuj kredyty X search[/dim]")

    console.print()
    for r in results:
        display_asset(r)

    # ── Save sentiment to DB ──
    if results:
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent))
            from db import DB
            _db = DB()
            _db.save_x_sentiment([
                {
                    "coin": r.get("coin", ""),
                    "sentiment": r.get("sentiment_label", ""),
                    "score": r.get("sentiment_score"),
                    "summary": "; ".join(r.get("top_narratives", [])[:2]),
                }
                for r in results
            ])
        except Exception:
            pass

    if len(results) > 1:
        table = Table(title="Summary")
        table.add_column("Asset", style="cyan")
        table.add_column("Score", justify="center")
        table.add_column("Label")
        table.add_column("Signal")
        table.add_column("Source")
        for r in results:
            s = r.get("sentiment_score", 5)
            c = score_color(s)
            src = "training" if "data_source" in r else "live"
            table.add_row(
                r.get("coin", "?"),
                f"[{c}]{s}/10[/{c}]",
                f"[{c}]{r.get('sentiment_label','?').upper()}[/{c}]",
                r.get("signal_strength", "?"),
                src,
            )
        console.print(table)


if __name__ == "__main__":
    main()
