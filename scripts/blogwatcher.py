"""BlogWatcher v2 — Asset-aware news intelligence for Daily Alpha Brief.

Replaces ad-hoc macro_news.py runs with:
- Per-asset classification (18 base assets from config/assets.json)
- Position-aware mapping (cross-ref MY BOOK)
- Multi-key Firecrawl rotation (2 keys = 2000/m capacity)
- Output: 3 sections (MACRO PULSE, POSITION IMPACTS, TRADE OPPORTUNITIES)

Sources (7 core): coindesk, theblock, reuters_markets, reuters_world,
                  kitco, oilprice, barchart
Backup:           fed, bbc_world, reuters_commodities

Usage:
    python scripts/blogwatcher.py                     # 7 core sources
    python scripts/blogwatcher.py --tier all          # core + fallback + backup
    python scripts/blogwatcher.py --sources coindesk,kitco
    python scripts/blogwatcher.py --positions positions.json
    python scripts/blogwatcher.py --dry-run           # show URLs, no scrape
    python scripts/blogwatcher.py --json              # raw articles JSON
    python scripts/blogwatcher.py --output report.md  # save markdown

Legacy macro_news.py is NOT modified — runs side-by-side as compat.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from itertools import cycle
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows (cp1252 can't render emoji / arrows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv(Path(__file__).parent.parent / ".env")

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "assets.json"
OUTPUT_DIR = ROOT / ".firecrawl" / "blogwatcher"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

API_KEYS = [
    k for k in [
        os.getenv("FIRECRAWL_API_KEY"),
        os.getenv("FIRECRAWL_API_KEY_2"),
    ]
    if k
]
BASE_URL = "https://api.firecrawl.dev/v1"

console = Console(legacy_windows=False, force_terminal=True)
_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_key_cycle = cycle(API_KEYS) if API_KEYS else None


# ── Config ────────────────────────────────────────────────────────────
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        console.print(f"[red]Config not found: {CONFIG_PATH}[/red]")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _alias_map(config: dict) -> dict[str, str]:
    """Build {ALIAS_UPPER: CANONICAL_SYMBOL} from base_assets."""
    out: dict[str, str] = {}
    for sym, meta in config.get("base_assets", {}).items():
        out[sym.upper()] = sym
        for alias in meta.get("aliases", []):
            out[alias.upper()] = sym
    return out


def _next_key() -> str | None:
    if not _key_cycle:
        return None
    return next(_key_cycle)


# ── Scrape ───────────────────────────────────────────────────────────
def scrape(url: str, extract_prompt: str, key: str | None = None) -> object:
    key = key or _next_key()
    if not key:
        raise RuntimeError("No FIRECRAWL_API_KEY available in .env")
    with httpx.Client(verify=_SSL_CTX, timeout=120.0) as client:
        r = client.post(
            f"{BASE_URL}/scrape",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "url": url,
                "formats": ["extract"],
                "extract": {"prompt": extract_prompt},
                "onlyMainContent": True,
            },
        )
        r.raise_for_status()
        data = r.json()
    return data.get("data", {}).get("extract")


def _build_prompt(source: dict, common_rules: str) -> str:
    """Concatenate common extract rules with per-source specifics."""
    specifics = source.get("extract_prompt", "")
    if not common_rules:
        return specifics
    return f"{common_rules.strip()}\n\nSOURCE-SPECIFIC INSTRUCTIONS:\n{specifics.strip()}"


def run_source(skey: str, source: dict, common_rules: str = "", retries: int = 1) -> object:
    label = source["label"]
    prompt = _build_prompt(source, common_rules)
    console.print(f"  → [cyan]{label}[/cyan] ... ", end="")
    for attempt in range(retries + 1):
        try:
            result = scrape(source["url"], prompt)
            console.print("[green]OK[/green]")
            return result
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if attempt < retries and code in (429, 500, 502, 503, 504):
                console.print(f"[yellow]retry {attempt+1} ({code})[/yellow]", end=" ")
                time.sleep(3)
                continue
            console.print(f"[red]FAIL HTTP {code}[/red]")
            return None
        except Exception as e:
            if attempt < retries:
                console.print(f"[yellow]retry {attempt+1}[/yellow]", end=" ")
                time.sleep(2)
                continue
            console.print(f"[red]FAIL {type(e).__name__}: {e}[/red]")
            return None


# ── Parse ────────────────────────────────────────────────────────────
def parse_articles(raw: object, source_key: str, alias_map: dict) -> list[dict]:
    """Normalize Firecrawl LLM-extract output to a flat list of articles."""
    if raw is None:
        return []

    # Sometimes Firecrawl returns markdown wrapping JSON; try to coerce
    if isinstance(raw, str):
        raw_stripped = raw.strip().strip("`")
        if raw_stripped.startswith("json"):
            raw_stripped = raw_stripped[4:].strip()
        try:
            raw = json.loads(raw_stripped)
        except Exception:
            console.print(f"  [yellow]{source_key}: extract not JSON-parseable, skipping[/yellow]")
            return []

    # Sometimes nested
    if isinstance(raw, dict):
        for k in ("articles", "headlines", "news", "items", "data", "results"):
            if k in raw and isinstance(raw[k], list):
                raw = raw[k]
                break
        else:
            raw = [raw]

    if not isinstance(raw, list):
        return []

    articles = []
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for a in raw:
        if not isinstance(a, dict):
            continue
        affected = a.get("affected_assets") or a.get("assets") or []
        articles.append({
            "headline": (a.get("headline") or a.get("title") or "").strip(),
            "summary": (a.get("summary") or a.get("description") or "").strip(),
            "affected_assets": _normalize_assets(affected, alias_map),
            "sentiment": _normalize_sentiment(a.get("sentiment")),
            "impact": str(a.get("impact") or "medium").lower().strip(),
            "category": str(a.get("category") or "general").lower().strip(),
            "key_levels": a.get("key_levels") or [],
            "source": source_key,
            "ts": now_iso,
        })
    # Skip empty headlines
    return [a for a in articles if a["headline"]]


def _normalize_assets(raw_list: object, alias_map: dict) -> list[str]:
    if isinstance(raw_list, str):
        raw_list = [raw_list]
    if not isinstance(raw_list, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_list:
        if not isinstance(raw, str):
            continue
        norm = alias_map.get(raw.strip().upper())
        if norm and norm not in seen:
            out.append(norm)
            seen.add(norm)
    return out


# ── Rendering ────────────────────────────────────────────────────────
# ASCII-safe markers — render identically in PowerShell, VSCode, Notepad, GitHub
SENTIMENT_EMOJI = {"bullish": "[+]", "bearish": "[-]", "neutral": "[~]"}
IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}
IMPACT_TAG = {"high": "[!!!]", "medium": "[!!] ", "low": "[!]  "}

# Common LLM sentiment aliases — normalize before storing
SENTIMENT_ALIASES = {
    "positive": "bullish",
    "pos": "bullish",
    "bull": "bullish",
    "up": "bullish",
    "supportive": "bullish",
    "negative": "bearish",
    "neg": "bearish",
    "bear": "bearish",
    "down": "bearish",
    "adverse": "bearish",
    "mixed": "neutral",
    "uncertain": "neutral",
    "flat": "neutral",
    "neutral": "neutral",
    "bullish": "bullish",
    "bearish": "bearish",
}


def _normalize_sentiment(s: object) -> str:
    if not isinstance(s, str):
        return "neutral"
    return SENTIMENT_ALIASES.get(s.strip().lower(), "neutral")


def _merge_duplicate_headlines(articles: list[dict]) -> list[dict]:
    """Merge entries with identical headline + sentiment, unioning affected_assets."""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for a in articles:
        key = (a["headline"].strip().lower(), a["sentiment"], a["source"])
        if key not in merged:
            merged[key] = dict(a)
            merged[key]["affected_assets"] = list(a.get("affected_assets", []))
            order.append(key)
        else:
            existing = merged[key]
            for sym in a.get("affected_assets", []):
                if sym not in existing["affected_assets"]:
                    existing["affected_assets"].append(sym)
            # Upgrade impact to highest
            if IMPACT_RANK.get(a["impact"], 3) < IMPACT_RANK.get(existing["impact"], 3):
                existing["impact"] = a["impact"]
    return [merged[k] for k in order]


# ── Theme taxonomy (source-based default + category override) ────────
# Tag list in display order (sorted by hit-count in renderer)
ALL_GROUPS = [
    "🏦 Fed / Macro",
    "🌍 Geopolityka",
    "🛢️ Energia",
    "🥇 Metals",
    "🌾 Agriculture",
    "₿ Crypto",
    "📜 Regulatory",
    "📰 Inne",
]

# Each source has a natural domain — clearest signal of "what theme is this?"
SOURCE_DEFAULT_GROUP = {
    "coindesk":          "₿ Crypto",
    "theblock":          "₿ Crypto",
    "reuters_markets":   "🏦 Fed / Macro",
    "reuters_world":     "🌍 Geopolityka",
    "bbc_world":         "🌍 Geopolityka",
    "kitco":             "🥇 Metals",
    "oilprice":          "🛢️ Energia",
    "barchart":          "🌾 Agriculture",
    "fed":               "🏦 Fed / Macro",
    "reuters_commodities": None,  # use category
}

# Category-based hard overrides — apply REGARDLESS of source
# (e.g. SEC delay news on theblock = Regulatory, not Crypto)
CATEGORY_HARD_OVERRIDE = {
    "regulatory": "📜 Regulatory",
    "regulation": "📜 Regulatory",
    "war":        "🌍 Geopolityka",
    "sanctions":  "🌍 Geopolityka",
    "geopolitics":"🌍 Geopolityka",
    "election":   "🌍 Geopolityka",
    "trade":      "🌍 Geopolityka",
    "fomc":       "🏦 Fed / Macro",
    "fed":        "🏦 Fed / Macro",
    "monetary_policy": "🏦 Fed / Macro",
    "opec":       "🛢️ Energia",
}

# Category-based soft fallback (only if source has no default)
CATEGORY_SOFT_FALLBACK = {
    "rates":        "🏦 Fed / Macro",
    "inflation":    "🏦 Fed / Macro",
    "macro":        "🏦 Fed / Macro",
    "fx":           "🏦 Fed / Macro",
    "bonds":        "🏦 Fed / Macro",
    "equities":     "🏦 Fed / Macro",
    "supply":       "🛢️ Energia",
    "demand":       "🛢️ Energia",
    "refining":     "🛢️ Energia",
    "inventory":    "🛢️ Energia",
    "cb_buying":    "🥇 Metals",
    "etf_flows":    "🥇 Metals",
    "weather":      "🌾 Agriculture",
    "harvest":      "🌾 Agriculture",
    "usda":         "🌾 Agriculture",
    "crop_report":  "🌾 Agriculture",
    "whale":        "₿ Crypto",
    "exchange":     "₿ Crypto",
    "defi":         "₿ Crypto",
    "ecosystem":    "₿ Crypto",
    "china":        "🌍 Geopolityka",
    "emerging_markets": "🌍 Geopolityka",
}


def _get_theme_group(article: dict) -> str:
    """Choose reader-friendly theme group for one article.

    Priority: hard category override > source default > soft category fallback > Inne.
    """
    cat = (article.get("category") or "").lower().strip()
    src = (article.get("source") or "").lower().strip()
    if cat in CATEGORY_HARD_OVERRIDE:
        return CATEGORY_HARD_OVERRIDE[cat]
    src_default = SOURCE_DEFAULT_GROUP.get(src)
    if src_default:
        return src_default
    if cat in CATEGORY_SOFT_FALLBACK:
        return CATEGORY_SOFT_FALLBACK[cat]
    return "📰 Inne"


def render_news_briefing(articles: list[dict], stories_per_theme: int = 3) -> str:
    """Extended executive briefing — per-theme metrics + top stories with summaries.

    For each of top 5 themes by impact-weight:
      - Headline metrics (hits, sentiment breakdown, impact level, net bias)
      - Top N stories with headline + summary + affected assets + source
    """
    if not articles:
        return "## 🗞️ NEWS BRIEFING\n\n_Brak newsów._\n"

    sources_used = sorted({a["source"] for a in articles})
    merged = _merge_duplicate_headlines(articles)

    theme_buckets: dict[str, list[dict]] = defaultdict(list)
    for a in merged:
        theme_buckets[_get_theme_group(a)].append(a)

    def _weight(items: list[dict]) -> int:
        return sum(3 if x["impact"] == "high" else 2 if x["impact"] == "medium" else 1 for x in items)

    sorted_themes = sorted(theme_buckets.items(), key=lambda kv: -_weight(kv[1]))[:5]

    lines = [
        "## 🗞️ NEWS BRIEFING — co się dzieje na rynkach",
        f"_{len(articles)} articles z {len(sources_used)} źródeł · "
        f"{len(merged)} unikalnych historii_",
        "",
    ]

    for theme, items in sorted_themes:
        bull = sum(1 for a in items if a["sentiment"] == "bullish")
        bear = sum(1 for a in items if a["sentiment"] == "bearish")
        neut = sum(1 for a in items if a["sentiment"] == "neutral")
        high_count = sum(1 for a in items if a["impact"] == "high")

        # Impact emoji
        if high_count >= 2:
            impact_label = f"🔥 {high_count} HIGH"
        elif high_count == 1:
            impact_label = "📊 1 HIGH"
        else:
            impact_label = "📰 MED/LOW"

        # Net direction (1.5× threshold for bias)
        if bull >= max(1, bear * 1.5) and bull > 0:
            net = "🟢 BULLISH bias"
        elif bear >= max(1, bull * 1.5) and bear > 0:
            net = "🔴 BEARISH bias"
        else:
            net = "🟡 MIXED"

        lines.append(f"### {theme}")
        lines.append(
            f"`{len(items)} hits` · `🟢{bull} / 🔴{bear} / 🟡{neut}` · "
            f"`{impact_label}` · **{net}**"
        )
        lines.append("")

        # Top stories — by impact, then dedupe within theme by (headline+sentiment)
        seen_keys: set[tuple] = set()
        ordered = sorted(items, key=lambda a: IMPACT_RANK.get(a["impact"], 3))
        top_stories: list[dict] = []
        for s in ordered:
            key = (s["headline"].strip().lower(), s["sentiment"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            top_stories.append(s)
            if len(top_stories) >= stories_per_theme:
                break

        for s in top_stories:
            em = SENTIMENT_EMOJI.get(s["sentiment"], "⚪")
            assets = ", ".join(s["affected_assets"]) if s["affected_assets"] else "—"
            lines.append(
                f"- {em} `{s['impact'].upper():6}` **{s['headline']}**  `[{assets}]`"
            )
            summary = (s.get("summary") or "").strip()
            if summary:
                if len(summary) > 240:
                    summary = summary[:237] + "…"
                lines.append(f"  > {summary}  _(src: {s['source']})_")
        lines.append("")

    return "\n".join(lines)


def render_legend() -> str:
    """Symbol legend — placed at top of report. ASCII markers — work in any editor."""
    return (
        "## Jak czytać raport — legenda symboli\n"
        "\n"
        "**Sentyment (kierunek wpływu newsa na cenę aktywa):**\n"
        "- `[+]` **Bullish** — news pozytywny, cena prawdopodobnie wzrośnie\n"
        "- `[-]` **Bearish** — news negatywny, cena prawdopodobnie spadnie\n"
        "- `[~]` **Neutral / Mixed** — bez wyraźnego kierunku lub zniuansowany\n"
        "- `[?]` **Unknown** — sentyment nieokreślony przez LLM (rzadko)\n"
        "\n"
        "**Impact (siła wpływu na rynek):**\n"
        "- `[!!!]` **HIGH** — market-mover: FOMC, wybuch wojny, hack >$100M, major data print\n"
        "- `[!!]`  **MEDIUM** — notable: analyst calls, secondary data, sector news\n"
        "- `[!]`   **LOW** — kontekstowe / minor\n"
        "\n"
        "**Net direction (ASSET IMPACT table):**\n"
        "- `BULL`  — przewaga bullish hits nad bearish dla tego aktywa\n"
        "- `BEAR`  — przewaga bearish nad bullish\n"
        "- `MIXED` — bull = bear (sprzeczne sygnały, rozbieżność = okazja do alpha)\n"
        "- `—`     — brak hits dziś (asset poza radarem newsów)\n"
        "\n"
        "**Position verdict (POSITION IMPACTS):**\n"
        "- `[OK]` **TEZA WZMOCNIONA** — news potwierdza kierunek Twojej pozycji\n"
        "- `[!]`  **TEZA POD PRESJĄ** — news sprzeczne z pozycją (rozważ SL/exit)\n"
        "- `[~]`  **MIXED** — niejednoznaczny sygnał (bull = bear w hits)\n"
        "\n"
        "**Trade opportunities (assets bez pozycji):**\n"
        "- `[+]` **LONG bias**  — więcej bullish niż bearish news = potencjalny LONG setup\n"
        "- `[-]` **SHORT bias** — odwrotnie\n"
    )


def render_top_headlines_grouped(articles: list[dict], per_group: int = 3) -> str:
    """Top headlines per theme group — no duplicates."""
    if not articles:
        return ""

    merged = _merge_duplicate_headlines(articles)
    grouped: dict[str, list[dict]] = defaultdict(list)
    seen_keys: set[tuple] = set()

    for a in merged:
        key = (a["headline"].strip().lower(), a["sentiment"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        grouped[_get_theme_group(a)].append(a)

    lines = ["## 📋 TOP HEADLINES — pogrupowane tematycznie", ""]
    group_order = ALL_GROUPS
    for group in group_order:
        if group not in grouped:
            continue
        items = sorted(grouped[group], key=lambda a: IMPACT_RANK.get(a["impact"], 3))[:per_group]
        lines.append(f"### {group}")
        for a in items:
            em = SENTIMENT_EMOJI.get(a["sentiment"], "⚪")
            assets = ", ".join(a["affected_assets"]) if a["affected_assets"] else "—"
            lines.append(
                f"- {em} `{a['impact'].upper():6}` **[{assets}]** {a['headline']}  "
                f"_({a['source']})_"
            )
        lines.append("")
    return "\n".join(lines)


def render_asset_impact_table(articles: list[dict], base_assets: dict) -> str:
    """Net sentiment per each of 18 base assets — wide-eye view."""
    if not base_assets:
        return ""

    asset_data: dict[str, dict] = {
        sym: {"bullish": 0, "bearish": 0, "neutral": 0, "articles": []}
        for sym in base_assets
    }
    merged = _merge_duplicate_headlines(articles)
    for a in merged:
        for sym in a["affected_assets"]:
            if sym in asset_data:
                asset_data[sym][a["sentiment"]] += 1
                asset_data[sym]["articles"].append(a)

    # Display order — crypto → makro → metals → energy → equity → agri
    ORDER = [
        "BTC", "ETH", "SOL", "HYPE", "LINK", "BTC.D",
        "DXY", "US10Y", "VIX",
        "GOLD", "SILVER",
        "OIL", "NATGAS",
        "NDX", "SPX",
        "CORN", "COFFEE", "COCOA",
    ]

    lines = ["## 📊 ASSET IMPACT — wszystkie 18 base assets", ""]
    lines.append("| Asset | Net | 🟢/🔴/🟡 | Key driver |")
    lines.append("|-------|-----|----------|------------|")

    for sym in ORDER:
        d = asset_data.get(sym, {"bullish": 0, "bearish": 0, "neutral": 0, "articles": []})
        bull, bear, neut = d["bullish"], d["bearish"], d["neutral"]
        total = bull + bear + neut

        if total == 0:
            net_label = "—"
            driver = "_brak catalysts_"
        else:
            if bull > bear:
                net_label = "🟢 BULL"
            elif bear > bull:
                net_label = "🔴 BEAR"
            else:
                net_label = "🟡 MIXED"
            top = sorted(d["articles"], key=lambda a: IMPACT_RANK.get(a["impact"], 3))[0]
            hl = top["headline"]
            driver = (hl[:68] + "…") if len(hl) > 70 else hl

        lines.append(f"| **{sym}** | {net_label} | {bull}/{bear}/{neut} | {driver} |")
    lines.append("")
    return "\n".join(lines)


def render_macro_pulse(articles: list[dict], top_n: int = 8) -> str:
    sources_used = {a["source"] for a in articles}
    merged = _merge_duplicate_headlines(articles)
    sorted_all = sorted(
        merged,
        key=lambda a: (IMPACT_RANK.get(a["impact"], 3), a["source"]),
    )
    sorted_a = sorted_all if top_n == 0 else sorted_all[:top_n]

    total_unique = len(merged)
    showing_note = f"showing all {total_unique}" if top_n == 0 or top_n >= total_unique else f"showing top {len(sorted_a)} of {total_unique}"
    lines = [
        "### MACRO PULSE",
        f"*(BlogWatcher v2 — {len(sources_used)} sources, {len(articles)} raw articles, "
        f"{total_unique} unique after dedup, {showing_note} by impact)*",
        "",
    ]
    for a in sorted_a:
        em = SENTIMENT_EMOJI.get(a["sentiment"], "⚪")
        impact = a["impact"].upper()
        assets = ", ".join(a["affected_assets"]) if a["affected_assets"] else "macro"
        lines.append(f'{em} **[{assets}]** {a["source"]}: "{a["headline"]}"')
        if a["summary"]:
            lines.append(f'   • {impact} {a["sentiment"]} | {a["summary"]}')
        if a["key_levels"]:
            lvls = a["key_levels"] if isinstance(a["key_levels"], list) else [str(a["key_levels"])]
            lines.append(f'   • Levels: {", ".join(str(x) for x in lvls)}')
        lines.append("")
    return "\n".join(lines)


def render_position_impacts(articles: list[dict], positions: list[dict]) -> str:
    if not positions:
        return ""

    lines: list[str] = []
    for pos in positions:
        symbol = str(pos.get("symbol", "")).upper()
        if not symbol:
            continue
        side = str(pos.get("side", "?")).upper()
        entry = pos.get("entry", "?")

        relevant = [
            a for a in articles
            if symbol in [s.upper() for s in a["affected_assets"]]
        ]
        if not relevant:
            continue

        bull = sum(1 for a in relevant if a["sentiment"] == "bullish")
        bear = sum(1 for a in relevant if a["sentiment"] == "bearish")
        neut = sum(1 for a in relevant if a["sentiment"] == "neutral")
        bias = "BULLISH" if bull > bear else ("BEARISH" if bear > bull else "MIXED")

        if side == "LONG":
            verdict = ("✅ TEZA WZMOCNIONA" if bias == "BULLISH"
                       else "⚠️ TEZA POD PRESJĄ" if bias == "BEARISH"
                       else "🟡 MIXED")
        elif side == "SHORT":
            verdict = ("✅ TEZA WZMOCNIONA" if bias == "BEARISH"
                       else "⚠️ TEZA POD PRESJĄ" if bias == "BULLISH"
                       else "🟡 MIXED")
        else:
            verdict = "🟡 OBSERWUJ"

        lines.append(f"**[{symbol}] {side} @ ${entry}** — {len(relevant)} news hits")
        lines.append(f"  • Sentiment: 🟢{bull} 🔴{bear} 🟡{neut} → **{bias}** → {verdict}")
        lines.append("  • Top news:")
        sorted_rel = sorted(relevant, key=lambda a: IMPACT_RANK.get(a["impact"], 3))[:3]
        for a in sorted_rel:
            em = SENTIMENT_EMOJI.get(a["sentiment"], "⚪")
            lines.append(f'    {em} [{a["source"]} / {a["impact"].upper()}] {a["headline"]}')
        lines.append("")
    return "\n".join(lines)


def render_trade_opportunities(articles: list[dict], base_assets: dict, positions: list[dict]) -> str:
    held_symbols = {str(p.get("symbol", "")).upper() for p in positions}
    asset_news: dict[str, list[dict]] = {}
    for a in articles:
        if a["impact"] not in ("high", "medium"):
            continue
        for sym in a["affected_assets"]:
            if sym not in base_assets or sym in held_symbols:
                continue
            asset_news.setdefault(sym, []).append(a)

    lines: list[str] = []
    if not asset_news:
        lines.append("_Brak istotnych katalizatorów na obserwowanych aktywach bez pozycji._")
        lines.append("")
        return "\n".join(lines)

    for sym, news in sorted(asset_news.items(), key=lambda x: -len(x[1])):
        bull = sum(1 for a in news if a["sentiment"] == "bullish")
        bear = sum(1 for a in news if a["sentiment"] == "bearish")
        if bull == bear:
            continue
        bias = "LONG bias" if bull > bear else "SHORT bias"
        em = "🟢" if bull > bear else "🔴"
        lines.append(f"{em} **{sym}** — {bias} ({bull} bull / {bear} bear)")
        for a in sorted(news, key=lambda a: IMPACT_RANK.get(a["impact"], 3))[:2]:
            lines.append(f'   • [{a["source"]} / {a["impact"].upper()}] {a["headline"]}')
        lines.append("")
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(description="BlogWatcher v2 — asset-aware news ingestion")
    p.add_argument("--sources", help="Comma-separated source keys (overrides --tier)")
    p.add_argument("--tier", default="core",
                   choices=["core", "core_fallback", "all"],
                   help="Source tier (default: core = 7 sources)")
    p.add_argument("--positions", help="Path to positions JSON file ([{symbol,side,entry,...}])")
    p.add_argument("--hours", type=int, default=12, help="Look-back window (informational; sources control via prompts)")
    p.add_argument("--dry-run", action="store_true", help="Show URLs, don't scrape")
    p.add_argument("--output", help="Save markdown report to this path")
    p.add_argument("--json", action="store_true", help="Print raw articles JSON instead of rendering")
    p.add_argument("--no-cache", action="store_true", help="Skip writing raw per-source cache")
    p.add_argument("--top", type=int, default=8,
                   help="Top N articles in MACRO PULSE (0 = unlimited / show all)")
    p.add_argument("--news-only", action="store_true",
                   help="Render only MACRO PULSE (skip POSITION IMPACTS + TRADE OPPORTUNITIES)")
    p.add_argument("--market-scan", action="store_true",
                   help="Pure market view: news + all-asset impact + opportunities for ALL assets, "
                        "no position filtering (ignores --positions). Use before chart analysis.")
    p.add_argument("--from-cache", metavar="STAMP",
                   help="Load articles from cached JSONs matching .firecrawl/blogwatcher/STAMP_*.json (zero credits)")
    args = p.parse_args()

    if not args.from_cache and not API_KEYS:
        console.print("[red]No FIRECRAWL_API_KEY / FIRECRAWL_API_KEY_2 in .env[/red]")
        sys.exit(1)

    config = load_config()
    sources_cfg = config.get("sources", {})
    base_assets = config.get("base_assets", {})
    tier_groups = config.get("tier_groups", {})
    common_rules = config.get("common_extract_rules", "")
    alias_map = _alias_map(config)

    # Resolve target sources
    if args.sources:
        keys = [k.strip() for k in args.sources.split(",")]
        targets = {k: sources_cfg[k] for k in keys if k in sources_cfg}
        missing = set(keys) - set(targets.keys())
        if missing:
            console.print(f"[yellow]Unknown sources skipped: {sorted(missing)}[/yellow]")
    elif args.tier == "core":
        targets = {k: sources_cfg[k] for k in tier_groups.get("core", []) if k in sources_cfg}
    elif args.tier == "core_fallback":
        keys = tier_groups.get("core", []) + tier_groups.get("fallback", [])
        targets = {k: sources_cfg[k] for k in keys if k in sources_cfg}
    else:  # all
        targets = dict(sources_cfg)

    ts_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    console.print(f"\n[bold]BlogWatcher v2[/bold] — {ts_label}")
    console.print(f"[dim]Firecrawl keys: {len(API_KEYS)} | sources: {len(targets)} | "
                  f"assets: {len(base_assets)}[/dim]\n")

    all_articles: list[dict] = []
    cache_stamp = datetime.now().strftime("%Y%m%d_%H%M")

    # ── Cache replay mode (zero credits) ─────────────────────────────
    if args.from_cache:
        stamp = args.from_cache
        cache_files = sorted(OUTPUT_DIR.glob(f"{stamp}_*.json"))
        if not cache_files:
            console.print(f"[red]No cache files found matching {stamp}_*.json[/red]")
            sys.exit(1)
        console.print(f"[dim]Loading {len(cache_files)} cache files (stamp: {stamp})[/dim]")
        for cf in cache_files:
            try:
                data = json.loads(cf.read_text(encoding="utf-8"))
                parsed = data.get("parsed", [])
                # Re-normalize sentiment/assets in case rules changed since cache write
                for a in parsed:
                    a["sentiment"] = _normalize_sentiment(a.get("sentiment"))
                    a["affected_assets"] = _normalize_assets(a.get("affected_assets", []), alias_map)
                all_articles.extend(parsed)
                console.print(f"  ← [cyan]{cf.stem}[/cyan]: {len(parsed)} articles")
            except Exception as e:
                console.print(f"  [yellow]skip {cf.name}: {e}[/yellow]")
    else:
        for skey, source in targets.items():
            if args.dry_run:
                console.print(f"  [dim]DRY RUN:[/dim] {source['url']}")
                continue
            raw = run_source(skey, source, common_rules=common_rules)
            articles = parse_articles(raw, skey, alias_map)
            all_articles.extend(articles)

            if not args.no_cache:
                cache_file = OUTPUT_DIR / f"{cache_stamp}_{skey}.json"
                cache_file.write_text(
                    json.dumps({"raw": raw, "parsed": articles}, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

        if args.dry_run:
            return

    console.print(f"\n[bold]Total: {len(all_articles)} articles parsed[/bold]")

    # Load positions if provided
    positions: list[dict] = []
    if args.positions:
        pp = Path(args.positions)
        if pp.exists():
            try:
                positions = json.loads(pp.read_text(encoding="utf-8"))
                if isinstance(positions, dict):
                    positions = positions.get("positions", [])
                console.print(f"[dim]Loaded {len(positions)} positions[/dim]")
            except Exception as e:
                console.print(f"[yellow]Could not load positions: {e}[/yellow]")
        else:
            console.print(f"[yellow]Positions file not found: {pp}[/yellow]")

    # JSON output mode
    if args.json:
        print(json.dumps(all_articles, indent=2, ensure_ascii=False))
        return

    # --market-scan: ignore loaded positions → pure market view, no book contamination
    if args.market_scan:
        positions = []

    # Render Markdown — legend FIRST (czytelnik się wkręca w symbole),
    # potem briefing, analiza, pozycje, opportunities
    header_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    scan_note = " · [MARKET SCAN — bez pozycji]" if args.market_scan else ""
    sections = [
        f"# 📰 BlogWatcher — {header_ts}{scan_note}\n",
        render_legend(),
        render_news_briefing(all_articles),
        render_top_headlines_grouped(all_articles, per_group=3),
        render_asset_impact_table(all_articles, base_assets),
    ]
    if not args.news_only:
        pi = render_position_impacts(all_articles, positions)
        if pi:
            sections.append("## 🎯 POSITION IMPACTS — wpływ na Twoje pozycje\n")
            sections.append(pi)
        if not args.market_scan:
            opp_header = "## 💡 TRADE OPPORTUNITIES — assets bez pozycji\n"
        else:
            opp_header = "## 💡 MARKET OPPORTUNITIES — newsowy bias na wszystkich aktywach\n"
        sections.append(opp_header)
        sections.append(render_trade_opportunities(all_articles, base_assets, positions))

    output = "\n".join(sections)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        console.print(f"[green]Saved → {args.output}[/green]")
    else:
        console.print()
        console.print(Panel(output, title="BlogWatcher Output", expand=False))

    credits = len(targets)
    console.print(f"\n[dim]Credits used this run: ~{credits} (rotated across {len(API_KEYS)} key(s))[/dim]")
    console.print(f"[dim]Cache: {OUTPUT_DIR}[/dim]")


if __name__ == "__main__":
    main()
