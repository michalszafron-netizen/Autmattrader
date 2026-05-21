"""Macro & news layer for Daily Alpha Brief.

Uses Firecrawl REST API to scrape clean markdown from curated sources.
Organized in categories: crypto, markets, commodities, geopolitics.

Free plan: 1000 pages/month, 2 concurrent requests.
Budget guide:
  --category crypto    = 3 credits   (coindesk + decrypt + theblock)
  --category markets   = 2 credits   (reuters_markets + marketwatch)
  --category commodities = 2 credits (kitco + oilprice)
  --category geo       = 2 credits   (reuters_world + bbc_world)
  --category brief     = 3 credits   (coindesk + reuters_world + kitco)  ← daily brief default
  --all                = 9 credits   (all sources)

Usage:
    python scripts/macro_news.py                    # default: brief (3 credits)
    python scripts/macro_news.py --category crypto
    python scripts/macro_news.py --category geo
    python scripts/macro_news.py --all              # 8 sources
    python scripts/macro_news.py --source kitco     # single source
    python scripts/macro_news.py --dry-run          # show URLs without scraping
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from datetime import datetime
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
BASE_URL = "https://api.firecrawl.dev/v1"

console = Console()
_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

# ── Sources ───────────────────────────────────────────────────────────────────

SOURCES: dict[str, dict] = {

    # ── CRYPTO ──────────────────────────────────────────────────────────────
    "coindesk": {
        "label": "CoinDesk — crypto markets",
        "category": "crypto",
        "url": "https://www.coindesk.com/markets",
        "extract_prompt": (
            "List the top 5 market-moving headlines. "
            "For each: headline, one-sentence summary, bullish/bearish/neutral tag. "
            "Skip sponsored content. Output as markdown bullet list."
        ),
    },
    "decrypt": {
        "label": "Decrypt — crypto news",
        "category": "crypto",
        "url": "https://decrypt.co/news/markets",
        "extract_prompt": (
            "List top 5 market headlines. "
            "For each: headline, summary, bullish/bearish/neutral. "
            "Skip NFT/gaming. Output markdown bullet list."
        ),
    },
    "theblock": {
        "label": "The Block — crypto/DeFi markets",
        "category": "crypto",
        "url": "https://www.theblock.co/latest",
        "extract_prompt": (
            "List the top 5 crypto and DeFi market-moving headlines from the last 12 hours. "
            "For each: headline, one-sentence summary, affected asset or protocol, "
            "bullish/bearish/neutral tag. "
            "Prioritize: exchange flows, on-chain data, institutional moves, regulatory. "
            "Skip opinion pieces. Output markdown bullet list."
        ),
    },

    # ── MARKETS / MACRO ──────────────────────────────────────────────────────
    "fed": {
        "label": "Federal Reserve — press releases",
        "category": "markets",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
        "extract_prompt": (
            "List press releases from the last 14 days. "
            "Date, title, one-sentence summary. "
            "Flag anything about interest rates, inflation, monetary policy. "
            "Rate overall hawkishness 1-10 (1=very dovish, 10=very hawkish). "
            "Output markdown bullet list."
        ),
    },
    "reuters_markets": {
        "label": "Reuters — financial markets",
        "category": "markets",
        "url": "https://www.reuters.com/markets",
        "extract_prompt": (
            "List top 5 financial market headlines. "
            "For each: headline, summary (1 sentence), affected assets, bullish/bearish/neutral. "
            "Focus on: equities, FX, bonds, commodities. Output markdown bullet list."
        ),
    },
    "marketwatch": {
        "label": "MarketWatch — US markets",
        "category": "markets",
        "url": "https://www.marketwatch.com/latest-news",
        "extract_prompt": (
            "List top 5 market-moving US financial news items. "
            "For each: headline, summary, affected asset class, tag (bullish/bearish/neutral). "
            "Output markdown bullet list."
        ),
    },

    # ── COMMODITIES ──────────────────────────────────────────────────────────
    "kitco": {
        "label": "Kitco — gold & silver news",
        "category": "commodities",
        "url": "https://www.kitco.com/news/gold",
        "extract_prompt": (
            "List top 5 gold and silver market headlines. "
            "For each: headline, summary, price direction (up/down/flat), key driver. "
            "Include any mentions of: central banks, inflation, Fed, USD, ETF flows. "
            "Output markdown bullet list."
        ),
    },
    "oilprice": {
        "label": "OilPrice.com — crude oil & energy",
        "category": "commodities",
        "url": "https://oilprice.com/latest-energy-news/world-news",
        "extract_prompt": (
            "List top 5 oil and energy market headlines. "
            "For each: headline, summary, price direction, key driver (OPEC, demand, geopolitics). "
            "Include WTI and Brent levels if mentioned. "
            "Output markdown bullet list."
        ),
    },

    # ── GEOPOLITICS / WORLD ──────────────────────────────────────────────────
    "reuters_world": {
        "label": "Reuters — world & geopolitics",
        "category": "geo",
        "url": "https://www.reuters.com/world",
        "extract_prompt": (
            "List top 5 geopolitical/world news headlines that could impact financial markets. "
            "For each: headline, summary, potential market impact (e.g. oil spike, risk-off, safe-haven). "
            "Prioritize: wars, sanctions, elections, trade disputes, central bank decisions. "
            "Output markdown bullet list."
        ),
    },
    "bbc_world": {
        "label": "BBC News — world events",
        "category": "geo",
        "url": "https://www.bbc.com/news/world",
        "extract_prompt": (
            "List top 5 world news stories that could affect financial markets. "
            "For each: headline, summary, region affected, potential impact on: "
            "oil/energy, safe havens (gold/USD/JPY), risk assets. "
            "Include any war updates (Ukraine, Middle East), sanctions, political crises. "
            "Output markdown bullet list."
        ),
    },
}

# ── Category presets ──────────────────────────────────────────────────────────

CATEGORY_GROUPS = {
    "crypto":     ["coindesk", "decrypt", "theblock"],
    "markets":    ["fed", "reuters_markets", "marketwatch"],
    "commodities": ["kitco", "oilprice"],
    "geo":        ["reuters_world", "bbc_world"],
    "brief":      ["coindesk", "reuters_world", "kitco"],   # default: 3 credits
    "alpha":      ["coindesk", "theblock", "reuters_world"], # /daily-alpha: 3 credits
}


# ── Scrape ────────────────────────────────────────────────────────────────────

def scrape(url: str, extract_prompt: str) -> str:
    with httpx.Client(verify=_SSL_CTX, timeout=90.0) as client:
        r = client.post(
            f"{BASE_URL}/scrape",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "url": url,
                "formats": ["extract"],
                "extract": {"prompt": extract_prompt},
                "onlyMainContent": True,
            },
        )
        r.raise_for_status()
        data = r.json()

    extract = data.get("data", {}).get("extract") or data.get("data", {}).get("markdown", "")
    if isinstance(extract, dict):
        extract = json.dumps(extract, indent=2, ensure_ascii=False)
    return str(extract) if extract else "(no content returned)"


def run_source(key: str, source: dict, output_dir: Path, dry_run: bool) -> str:
    label = source["label"]
    url = source["url"]
    if dry_run:
        console.print(f"  [dim]DRY RUN:[/dim] [cyan]{url}[/cyan]")
        return f"[dry-run: {url}]"

    console.print(f"  Scraping [cyan]{label}[/cyan]...", end=" ")
    try:
        result = scrape(url, source["extract_prompt"])
        console.print("[green]OK[/green]")
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        out_file = output_dir / f"{ts}_{key}.md"
        out_file.write_text(result, encoding="utf-8")
        return result
    except httpx.HTTPStatusError as e:
        msg = f"HTTP {e.response.status_code}"
        console.print(f"[red]FAIL — {msg}[/red]")
        return f"[error: {msg}]"
    except Exception as e:
        console.print(f"[red]FAIL — {e}[/red]")
        return f"[error: {e}]"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not API_KEY:
        console.print("[red]FIRECRAWL_API_KEY not set in .env[/red]")
        sys.exit(1)

    p = argparse.ArgumentParser(description="Macro & news scraper via Firecrawl")
    p.add_argument(
        "--source",
        choices=list(SOURCES.keys()),
        help="Single source key",
    )
    p.add_argument(
        "--category",
        choices=list(CATEGORY_GROUPS.keys()),
        default="brief",
        help="Source category (default: brief = coindesk + reuters_world + kitco)",
    )
    p.add_argument("--all", action="store_true", help="Run all 9 sources (8 credits)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    output_dir = Path(__file__).parent.parent / ".firecrawl"
    output_dir.mkdir(exist_ok=True)

    if args.source:
        targets = {args.source: SOURCES[args.source]}
    elif args.all:
        targets = SOURCES
    else:
        keys = CATEGORY_GROUPS[args.category]
        targets = {k: SOURCES[k] for k in keys}

    console.print(
        f"\n[bold]Macro & News Layer[/bold] — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"[dim]Sources ({len(targets)}): {', '.join(targets.keys())}[/dim]\n"
    )

    results: dict[str, str] = {}
    for key, source in targets.items():
        results[key] = run_source(key, source, output_dir, args.dry_run)

    console.print()
    for key, content in results.items():
        label = SOURCES[key]["label"]
        console.print(Panel(content[:1800], title=f"[bold]{label}[/bold]", expand=False))

    if not args.dry_run:
        console.print(f"\n[dim]Saved to {output_dir}/[/dim]")
        console.print(f"[dim]Credits used this run: ~{len(targets)} of 1000/month[/dim]")


if __name__ == "__main__":
    main()
