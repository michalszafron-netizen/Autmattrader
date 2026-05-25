"""Fundamental token research — łączy 6 źródeł w jeden raport.

Obsługuje: BSC (BEP-20), Ethereum (ERC-20), Base, Polygon
Automatycznie wykrywa sieć po formacie adresu.

Usage:
    python scripts/token_research.py 0xb5761f36fdfe2892f1b54bc8ee8babb2a1b698d3
    python scripts/token_research.py RICE                          # po tickerze
    python scripts/token_research.py 0x... --chain eth             # force Ethereum
    python scripts/token_research.py 0x... --no-x                  # bez X search (oszczędza kredyty)
"""

from __future__ import annotations

import argparse
import io
import os
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows UTF-8 fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

console  = Console()
_SSL     = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

ROOT         = Path(__file__).parent.parent
RESEARCH_DIR = ROOT / "reports" / "research"
CACHE_DAYS   = 7   # ile dni raport jest "świeży" — powyżej robi fresh research

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "")
ETHERSCAN_V2  = "https://api.etherscan.io/v2/api"
HELIUS_KEY    = os.getenv("HELIUS_API_KEY", "")
BIRDEYE_KEY   = os.getenv("BIRDEYE_API_KEY", "")
XAI_KEY        = os.getenv("XAI_API_KEY", "")
CRYPTOCOMPARE_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "")

# Chains przetestowane na free tier Etherscan V2 (2026-05-20)
# DZIALA: ETH, BSC, Polygon, Arbitrum, Optimism, Base, Avalanche, Gnosis, Linea, Blast
# BRAK: Fantom (250), Cronos (25), zkSync (324), Polygon zkEVM (1101), Scroll (534352)
CHAIN_IDS = {
    "eth":      "1",       # Ethereum mainnet
    "bsc":      "56",      # Binance Smart Chain
    "polygon":  "137",     # Polygon PoS
    "arbitrum": "42161",   # Arbitrum One
    "optimism": "10",      # Optimism
    "base":     "8453",    # Base (Coinbase L2)
    "avax":     "43114",   # Avalanche C-Chain
    "gnosis":   "100",     # Gnosis Chain
    "linea":    "59144",   # Linea (ConsenSys)
    "blast":    "81457",   # Blast L2
    # NIE DZIALA na free tier:
    # fantom=250, cronos=25, zksync=324, polygon_zkevm=1101, scroll=534352
}

CG_PLATFORMS = {
    "bsc":      "binance-smart-chain",
    "eth":      "ethereum",
    "base":     "base",
    "polygon":  "polygon-pos",
    "arbitrum": "arbitrum-one",
}

# ── Research cache helpers ────────────────────────────────────────────────────

def _cache_filename(symbol: str, chain: str, ca: str, date_str: str) -> Path:
    """Canonical path: reports/research/GMT_eth_0xe3c408bd_2026-05-24.md"""
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    safe = f"{symbol.upper()}_{chain}_{ca[:10]}_{date_str}.md"
    return RESEARCH_DIR / safe


def find_cached_report(query: str, chain: str, max_age_days: int = CACHE_DAYS) -> Path | None:
    """Find the newest cached report for this contract or ticker (case-insensitive).

    Matches both contract address prefix and ticker symbol in filename.
    Returns Path if found and < max_age_days old, else None.
    """
    if not RESEARCH_DIR.exists():
        return None
    now = datetime.now(timezone.utc)
    query_lower = query.lower()[:10]  # first 10 chars of contract or full ticker
    candidates = []
    for f in RESEARCH_DIR.glob("*.md"):
        if query_lower in f.name.lower():
            try:
                # Extract date from filename suffix _YYYY-MM-DD.md
                date_part = f.stem.split("_")[-1]
                file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = (now - file_date).days
                if age_days <= max_age_days:
                    candidates.append((age_days, f))
            except Exception:
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])  # newest first
    return candidates[0][1]


def save_research_report(
    symbol: str, chain: str, ca: str,
    name: str, price, mc, fdv, vol24, ath_pct, ch7d, ch30d,
    verdict: str, flags: list[str], dangers: list[str],
    src_data: dict, owner_f: list[str], github: list[dict],
    pairs: list[dict], positives: list[str], negatives: list[str],
    conviction: int, overall: str, website: str, twitter: str, telegram: str,
    x_out: str = "",
    news_data: dict | None = None,
) -> Path:
    """Build clean markdown report and save to reports/research/."""
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    path  = _cache_filename(symbol, chain, ca, today)

    def _n(v, d=2):
        if v is None: return "—"
        if v >= 1e9:  return f"${v/1e9:.2f}B"
        if v >= 1e6:  return f"${v/1e6:.2f}M"
        if v >= 1e3:  return f"${v/1e3:.1f}K"
        return f"${v:.{d}f}"

    lines = [
        f"# 🔍 Token Research: {symbol} — {name}",
        f"",
        f"**Ticker:** ${symbol}  ",
        f"**Contract:** `{ca}`  ",
        f"**Chain:** {chain}  ",
        f"**Research date:** {ts}  ",
        f"**Cache valid until:** {datetime.now(timezone.utc).strftime('%Y-%m-')}{ (datetime.now(timezone.utc).day + CACHE_DAYS):02d}",
        f"",
        f"---",
        f"",
        f"## 📊 Podstawowe dane",
        f"",
        f"| Metryka | Wartość |",
        f"|---------|---------|",
        f"| Cena | {_n(price, 6)} |",
        f"| Market Cap | {_n(mc)} |",
        f"| FDV | {_n(fdv)} |",
        f"| Volume 24h | {_n(vol24)} |",
    ]
    if mc and vol24 and vol24 > 0:
        lines.append(f"| MC/Vol ratio | {mc/vol24:.2f}x |")
    if ath_pct is not None:
        lines.append(f"| Spadek od ATH | {ath_pct:.1f}% |")
    if ch7d is not None:
        lines.append(f"| Zmiana 7d | {ch7d:+.1f}% |")
    if ch30d is not None:
        lines.append(f"| Zmiana 30d | {ch30d:+.1f}% |")
    if website:
        lines.append(f"| Strona | {website} |")
    if twitter:
        lines.append(f"| Twitter | [@{twitter}](https://twitter.com/{twitter}) |")
    if telegram:
        lines.append(f"| Telegram | [t.me/{telegram}](https://t.me/{telegram}) |")

    lines += ["", "---", "", "## 🔐 Bezpieczeństwo (GoPlus)", ""]
    lines.append(f"**Wynik:** `{verdict}`")
    if flags:
        lines.append("")
        for f_ in flags:
            lines.append(f"- ⚠️ {f_}")

    lines += ["", "---", "", "## 📜 Kontrakt (Etherscan)", ""]
    if src_data.get("verified"):
        lines.append(f"- **Zweryfikowany:** TAK")
        lines.append(f"- **Nazwa:** `{src_data.get('contract_name', '?')}`")
        lines.append(f"- **Kompilator:** {src_data.get('compiler', '?')}")
        lines.append(f"- **Proxy:** {'TAK' if src_data.get('is_proxy') else 'NIE'}")
        if owner_f:
            lines.append(f"- **Funkcje onlyOwner:** {', '.join(owner_f)}")
        if dangers:
            lines.append("")
            for d in dangers:
                lines.append(f"- ⚠️ {d}")
    else:
        lines.append("Kontrakt niezweryfikowany lub brak klucza Etherscan.")

    if pairs:
        lines += ["", "---", "", "## 💧 Liquidity (DexScreener)", ""]
        lines.append("| DEX | Liquidity | Vol 24h |")
        lines.append("|-----|-----------|---------|")
        for p in pairs:
            dex = p.get("dexId", "?")
            liq = p.get("liquidity", {}).get("usd", 0)
            v24 = p.get("volume", {}).get("h24", 0)
            lines.append(f"| {dex} | {_n(liq)} | {_n(v24)} |")

    if github:
        lines += ["", "---", "", "## 💻 GitHub", ""]
        for g in github:
            lines.append(f"- **{g['name']}** — ⭐{g['stars']:,} | last push: {g.get('last_push','?')}")
    else:
        lines += ["", "---", "", "## 💻 GitHub", "", "_Brak repozytorium._"]

    if x_out:
        lines += ["", "---", "", "## 🐦 X/Twitter Sentiment", "", "```", x_out[:600], "```"]

    # ── NEWS SECTION ──────────────────────────────────────────────────────────
    nd = news_data or {}
    cc_items = nd.get("cryptocompare", [])
    gn_items = nd.get("google_news", [])
    cg_items = nd.get("cg_updates", [])
    tw_items = nd.get("twitter", [])

    has_news = cc_items or gn_items or cg_items or tw_items
    if has_news:
        lines += ["", "---", "", "## 📰 News & Catalysts", ""]

        if tw_items:
            lines.append("### 🐦 Oficjalny Twitter (Grok live search)")
            lines.append("")
            for item in tw_items:
                lines.append(f"- {item}")
            lines.append("")

        if cg_items:
            lines.append("### 🦎 CoinGecko Status Updates")
            lines.append("")
            for item in cg_items:
                lines.append(f"- **[{item['created_at']}]** `{item['category']}` — {item['description'][:200]}")
            lines.append("")

        if cc_items:
            lines.append("### 📡 CryptoCompare News")
            lines.append("")
            lines.append("| Data | Tytuł | Źródło |")
            lines.append("|------|-------|--------|")
            for item in cc_items:
                title_link = f"[{item['title'][:60]}]({item['url']})" if item.get("url") else item["title"][:60]
                lines.append(f"| {item['published']} | {title_link} | {item['source']} |")
            lines.append("")

        if gn_items:
            lines.append("### 🔍 Google News")
            lines.append("")
            lines.append("| Data | Tytuł | Źródło |")
            lines.append("|------|-------|--------|")
            for item in gn_items:
                title_link = f"[{item['title'][:60]}]({item['url']})" if item.get("url") else item["title"][:60]
                lines.append(f"| {item['published']} | {title_link} | {item['source']} |")
            lines.append("")

    lines += [
        "", "---", "",
        "## 🎯 Expert View", "",
        f"**Ocena ogólna:** {overall}  ",
        f"**Conviction:** {conviction}/10",
        "",
        "**Plusy:**",
    ]
    for p_ in positives:
        lines.append(f"- ✅ {p_}")
    if not positives:
        lines.append("- (brak wyraźnych plusów)")
    lines.append("")
    lines.append("**Minusy:**")
    for n_ in negatives:
        lines.append(f"- ❌ {n_}")
    if not negatives:
        lines.append("- (brak wyraźnych minusów)")
    lines += [
        "", "---",
        f"*Wygenerowano automatycznie przez token_research.py | {ts}*",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


DANGEROUS_FUNCS = {
    "mint":                   "Moze tworzyc nowe tokeny — inflacja supply",
    "blacklist|blklist":      "Moze zablokowac twoj wallet przed sprzedaza",
    "setSellFee|setSellTax":  "Moze podniesc podatek sprzedazy do 99%",
    "setBuyFee|setBuyTax":    "Moze podniesc podatek kupna",
    "pause|freeze":           "Moze zatrzymac wszystkie transfery",
    "setMaxTx|setMaxWallet":  "Moze zmienic limity per transakcja/wallet",
}


def client() -> httpx.Client:
    return httpx.Client(verify=_SSL, timeout=20)


# ── 1. CoinGecko ─────────────────────────────────────────────────────────────

def fetch_coingecko(ca: str, chain: str) -> dict:
    platform = CG_PLATFORMS.get(chain, "binance-smart-chain")
    with client() as c:
        r = c.get(f"https://api.coingecko.com/api/v3/coins/{platform}/contract/{ca}")
    if r.status_code != 200:
        return {}
    return r.json()


# ── 2. Etherscan V2 — source code + contract analysis ───────────────────────

def fetch_etherscan_source(ca: str, chain_id: str) -> dict:
    """Fetch verified source code and analyze for dangerous patterns."""
    if not ETHERSCAN_KEY:
        return {}
    with client() as c:
        r = c.get(ETHERSCAN_V2, params={
            "module": "contract", "action": "getsourcecode",
            "address": ca, "apikey": ETHERSCAN_KEY, "chainid": chain_id
        })
    if r.status_code != 200:
        return {}
    res = r.json()
    if res.get("status") != "1":
        return {}
    item = res["result"][0]
    src  = item.get("SourceCode", "")

    # Analyze dangerous patterns
    import re
    dangers_found = []
    for pattern, description in DANGEROUS_FUNCS.items():
        if re.search(pattern, src, re.IGNORECASE):
            dangers_found.append(description)

    # Owner-only functions
    owner_funcs = re.findall(r"function\s+(\w+)\s*\([^)]*\)[^{]*onlyOwner", src)

    # Vesting indicators
    vesting_keywords = ["vesting", "vest(", "cliff", "TGE", "release(", "schedule"]
    has_vesting = any(kw.lower() in src.lower() for kw in vesting_keywords)

    # Mint check — is it callable by owner or only internal?
    mint_external = bool(re.search(r"function mint.*external|function mint.*public", src, re.IGNORECASE))
    mint_internal = "function _mint" in src and not mint_external

    return {
        "contract_name":   item.get("ContractName", "Unknown"),
        "compiler":        item.get("CompilerVersion", ""),
        "verified":        True,
        "license":         item.get("LicenseType", ""),
        "is_proxy":        item.get("Proxy", "0") == "1",
        "implementation":  item.get("Implementation", ""),
        "source_len":      len(src),
        "owner_functions": owner_funcs,
        "dangers_found":   dangers_found,
        "has_vesting":     has_vesting,
        "mint_external":   mint_external,
        "mint_internal_only": mint_internal,
    }


# ── 3. DexScreener ───────────────────────────────────────────────────────────

def fetch_dexscreener(ca: str) -> list[dict]:
    with client() as c:
        r = c.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}")
    if r.status_code != 200:
        return []
    data = r.json()
    if not isinstance(data, dict):
        return []
    return (data.get("pairs") or [])[:3]


# ── 3. GoPlus Security (honeypot + rug check, free) ──────────────────────────

def fetch_goplus(ca: str, chain_id: str) -> dict:
    with client() as c:
        r = c.get(f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}",
                  params={"contract_addresses": ca})
    if r.status_code != 200:
        return {}
    result = r.json().get("result", {})
    return result.get(ca.lower(), result.get(ca, {}))


# ── 4. GitHub ─────────────────────────────────────────────────────────────────

def fetch_github(repo_urls: list[str]) -> list[dict]:
    results = []
    for url in repo_urls[:2]:
        # convert github.com/org/repo → api
        url = url.rstrip("/")
        parts = url.split("github.com/")
        if len(parts) < 2:
            continue
        api_url = f"https://api.github.com/repos/{parts[1]}"
        try:
            with client() as c:
                r = c.get(api_url, headers={"Accept": "application/vnd.github+json"})
            if r.status_code == 200:
                d = r.json()
                results.append({
                    "name": d.get("full_name"),
                    "stars": d.get("stargazers_count", 0),
                    "forks": d.get("forks_count", 0),
                    "open_issues": d.get("open_issues_count", 0),
                    "last_push": d.get("pushed_at", "")[:10],
                    "language": d.get("language", ""),
                })
        except Exception:
            pass
    return results


# ── SOLANA APIs ──────────────────────────────────────────────────────────────

def is_solana_address(addr: str) -> bool:
    """Solana addresses are base58, 32-44 chars, no 0x prefix."""
    return not addr.startswith("0x") and 32 <= len(addr) <= 44

def fetch_helius_asset(mint: str) -> dict:
    if not HELIUS_KEY:
        return {}
    with client() as c:
        r = c.post(
            f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}",
            json={"jsonrpc": "2.0", "id": "1", "method": "getAsset", "params": {"id": mint}}
        )
    if r.status_code != 200:
        return {}
    result = r.json().get("result", {})
    meta = result.get("content", {}).get("metadata", {})
    ti   = result.get("token_info", {})
    pi   = ti.get("price_info", {})
    return {
        "name":     meta.get("name", ""),
        "symbol":   meta.get("symbol", ""),
        "supply":   ti.get("supply", 0),
        "decimals": ti.get("decimals", 0),
        "price":    pi.get("price_per_token"),
        "currency": pi.get("currency", "USDC"),
        "links":    result.get("content", {}).get("links", {}),
    }

def fetch_birdeye_overview(mint: str) -> dict:
    if not BIRDEYE_KEY:
        return {}
    with client() as c:
        r = c.get(
            f"https://public-api.birdeye.so/defi/token_overview?address={mint}",
            headers={"X-API-KEY": BIRDEYE_KEY, "x-chain": "solana"}
        )
    if r.status_code != 200:
        return {}
    return r.json().get("data", {})

def fetch_rugcheck(mint: str) -> dict:
    with client() as c:
        r = c.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    if r.status_code != 200:
        return {}
    return r.json()

def run_solana_research(mint: str, no_x: bool = False) -> None:
    console.print(f"\n[bold]Solana Token Research[/bold] | {mint[:12]}...")
    console.print("[dim]Odpytuję: Helius, Birdeye, RugCheck, DexScreener, CoinGecko...[/dim]\n")

    asset   = fetch_helius_asset(mint)
    birdeye = fetch_birdeye_overview(mint)
    rug     = fetch_rugcheck(mint)
    pairs   = fetch_dexscreener(mint)
    cg      = fetch_coingecko(mint, "solana") if not asset.get("name") else {}

    name    = asset.get("name") or birdeye.get("name") or cg.get("name", mint[:8])
    symbol  = (asset.get("symbol") or birdeye.get("symbol") or cg.get("symbol", "?")).upper()
    price   = asset.get("price") or birdeye.get("price")
    holders = birdeye.get("holder", 0)
    vol24   = birdeye.get("v24hUSD", 0)
    buys24  = birdeye.get("buy24h", 0)
    sells24 = birdeye.get("sell24h", 0)
    uniq24  = birdeye.get("uniqueWallet24h", 0)

    supply_raw = int(asset.get("supply", 0) or 0)
    decimals   = int(asset.get("decimals", 0) or 0)
    supply     = supply_raw / (10 ** decimals) if decimals else supply_raw

    # Market data from CoinGecko if available
    cg_md  = cg.get("market_data", {}) if cg else {}
    mc     = cg_md.get("market_cap", {}).get("usd") or birdeye.get("mc")
    ath    = cg_md.get("ath", {}).get("usd")
    ath_pct= cg_md.get("ath_change_percentage", {}).get("usd")
    ch30d  = cg_md.get("price_change_percentage_30d")

    # ── Overview ──
    overview = (
        f"[bold cyan]{name} (${symbol})[/bold cyan]  [dim]Solana[/dim]\n"
        f"Cena:       ${price:.8f}\n" if price else ""
        f"Market Cap: {format_number(mc)}\n" if mc else ""
        f"Holders:    {holders:,}\n"
        f"Vol 24h:    {format_number(vol24)}\n"
        f"Buys/Sells: {buys24}/{sells24}  |  Unikalne wallety 24h: {uniq24:,}\n"
        f"Supply:     {supply:,.0f} {symbol}\n"
    )
    if ath:
        ath_str = f"${ath:.6f}  |  Spadek od ATH: {ath_pct:.1f}%" if ath_pct is not None else f"${ath:.6f}"
        overview += f"ATH:        {ath_str}\n"
    if ch30d is not None:
        overview += f"30 dni:     {ch30d:+.1f}%\n"

    console.print(Panel(overview.strip(), title="[bold]Podstawowe dane[/bold]", expand=False))

    # ── DEX ──
    if pairs:
        table = Table(title="Liquidity na DEX (Solana)")
        table.add_column("DEX",       width=14)
        table.add_column("Liquidity", justify="right", width=12)
        table.add_column("Vol 24h",   justify="right", width=12)
        table.add_column("Buys/Sells",justify="center",width=12)
        table.add_column("FDV",       justify="right", width=12)
        for p in [x for x in pairs if x.get("chainId") == "solana"][:3]:
            liq = format_number(p.get("liquidity", {}).get("usd"))
            vol = format_number(p.get("volume", {}).get("h24"))
            fdv = format_number(p.get("fdv"))
            txns = p.get("txns", {}).get("h24", {})
            bs  = f"{txns.get('buys',0)}/{txns.get('sells',0)}"
            table.add_row(p.get("dexId","?"), liq, vol, bs, fdv)
        console.print(table)

    # ── RugCheck ──
    if rug:
        score    = rug.get("score", "?")
        rugged   = rug.get("rugged", False)
        risks    = rug.get("risks", [])
        markets  = rug.get("markets", [])

        danger_count = sum(1 for r in risks if r.get("level") in ("danger", "critical"))
        warn_count   = sum(1 for r in risks if r.get("level") == "warn")
        verdict      = "DANGER" if rugged or danger_count >= 2 else ("WARN" if warn_count > 0 or danger_count == 1 else "PASS")
        vc = {"PASS":"green","WARN":"yellow","DANGER":"red"}[verdict]

        lp_locked = 0
        if markets:
            lp_locked = markets[0].get("lp", {}).get("lpLockedPct", 0) or 0

        risk_lines = "\n".join(f"  {'[red]' if r.get('level') in ('danger','critical') else '[yellow]'}{r.get('level','?').upper()}[/{'red' if r.get('level') in ('danger','critical') else 'yellow'}] {r.get('name','')} — {r.get('description','')}"
                               for r in risks[:6])

        rug_text = (
            f"[{vc}]Wynik: {verdict}[/{vc}]  |  RugCheck score: {score}/1000  |  Rugged: {'TAK' if rugged else 'NIE'}\n"
            f"LP zablokowane: {lp_locked:.1f}%\n\n"
            f"Ryzyka:\n{risk_lines or '  Brak'}"
        )
        console.print(Panel(rug_text, title="[bold]RugCheck Security[/bold]", expand=False))

    # ── X Sentiment ──
    if not no_x:
        console.print("\n[dim]Sprawdzam X/Twitter...[/dim]")
        x_out = fetch_x_sentiment(symbol)
        console.print(Panel(x_out, title="[bold]X / Twitter Sentiment[/bold]", expand=False))

    # ── Expert View ──
    positives, negatives = [], []
    if holders and holders > 5000:
        positives.append(f"Duzo holderow ({holders:,}) — token ma zasieg")
    if buys24 and sells24 and buys24 > sells24:
        positives.append(f"Wiecej kupujacych niz sprzedajacych ({buys24}/{sells24})")
    if lp_locked > 50 if rug else False:
        positives.append(f"Liquidity {lp_locked:.0f}% zablokowane")
    if ch30d and ch30d > 20:
        positives.append(f"+{ch30d:.0f}% w 30 dniach — momentum")

    if rug and rug.get("rugged"):
        negatives.append("UWAGA: Token oznaczony jako RUGGED")
    if rug and danger_count >= 2:
        negatives.append(f"{danger_count} krytycznych flag bezpieczenstwa")
    if ath_pct and ath_pct < -80:
        negatives.append(f"Spadek {ath_pct:.0f}% od ATH — wiele portfeli pod woda")
    if lp_locked < 20 if rug and markets else False:
        negatives.append("Liquidity prawie niezablokowane — ryzyko rug pull")

    pos_text = "\n".join(f"  + {p}" for p in positives) or "  brak wyraznych plusow"
    neg_text = "\n".join(f"  - {n}" for n in negatives) or "  brak wyraznych minusow"
    conviction = min(max(4 + len(positives) - len(negatives), 1), 9)

    expert = (
        f"[bold]Conviction: {conviction}/10[/bold]\n\n"
        f"[green]Plusy:[/green]\n{pos_text}\n\n"
        f"[red]Minusy:[/red]\n{neg_text}\n\n"
        f"[bold]Co sprawdzic recznie:[/bold]\n"
        f"  Solscan: https://solscan.io/token/{mint}\n"
        f"  Birdeye: https://birdeye.so/token/{mint}"
    )
    console.print(Panel(expert, title="[bold]EXPERT VIEW[/bold]", expand=False))

    # ── Save to DB ──
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent))
        from db import DB as _DB
        _db = _DB()
        mc_sol = birdeye.get("mc") or birdeye.get("realMc")
        _db.save_token_research(
            ticker=symbol,
            contract=mint,
            data={
                "chain": "solana",
                "name": name,
                "price_usd": price,
                "mcap_usd": mc_sol,
                "rug_score": "RUGGED" if (rug and rug.get("rugged")) else "OK",
                "verdict": f"conviction={conviction}/10",
                "summary": "; ".join(positives[:2]) if positives else "no positives",
            },
        )
    except Exception:
        pass


# ── 5. X Sentiment (Grok) ────────────────────────────────────────────────────

def fetch_x_sentiment(ticker: str) -> str:
    import subprocess
    py = Path(sys.executable)
    script = Path(__file__).parent / "x_sentiment.py"
    try:
        r = subprocess.run(
            [str(py), str(script), "sentiment", "--coins", ticker],
            capture_output=True, text=True, timeout=60
        )
        return r.stdout.strip()
    except Exception as e:
        return f"X search error: {e}"


# ── 6. News & Catalysts ───────────────────────────────────────────────────────

def fetch_google_news_rss(ticker: str, name: str = "", limit: int = 5) -> list[dict]:
    """Google News RSS — bezpłatne, bez klucza. Zwraca ostatnie newsy dla tickera.
    Łączy ticker + nazwę projektu dla lepszych wyników (np. 'GMT STEPN').
    """
    import xml.etree.ElementTree as ET
    query = f"{ticker} {name} crypto".strip() if name else f"{ticker} crypto"
    try:
        with client() as c:
            r = c.get(
                "https://news.google.com/rss/search",
                params={"q": query, "hl": "en", "gl": "US", "ceid": "US:en"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
        items = root.findall(".//item")
        results = []
        for item in items[:limit]:
            src_el = item.find("source")
            results.append({
                "title":     item.findtext("title", ""),
                "source":    src_el.text if src_el is not None else "",
                "url":       item.findtext("link", ""),
                "published": item.findtext("pubDate", "")[:16],
                "body":      "",
            })
        return results
    except Exception:
        return []


def fetch_cryptocompare_news(ticker: str, name: str = "", limit: int = 5) -> list[dict]:
    """CryptoCompare News — CoinDesk/CoinTelegraph/Decrypt filtered by ticker.
    Wymaga CRYPTOCOMPARE_API_KEY (free: 11k req/mies).
    Filtruje wyniki: zwraca tylko artykuły które NAPRAWDĘ dotyczą tego tokena.
    """
    if not CRYPTOCOMPARE_KEY:
        return []
    # Try ticker + common aliases (e.g. UTK,UTRUST,XMONEY)
    categories = ticker.upper()
    if name:
        # Add first word of name as extra category hint
        first_word = name.split()[0].upper()
        if first_word != ticker.upper() and len(first_word) >= 3:
            categories = f"{ticker.upper()},{first_word}"
    try:
        with client() as c:
            r = c.get(
                "https://min-api.cryptocompare.com/data/v2/news/",
                params={"categories": categories, "lang": "EN", "limit": limit * 3},  # fetch extra for filtering
                headers={"Authorization": f"Apikey {CRYPTOCOMPARE_KEY}"},
            )
        if r.status_code != 200:
            return []
        items = r.json().get("Data", [])
        if not isinstance(items, list):
            return []

        # Filter: only keep articles that mention ticker or name in title/body
        keywords = {ticker.lower(), ticker.upper()}
        if name:
            for word in name.split()[:2]:
                if len(word) >= 4:
                    keywords.add(word.lower())
        relevant = []
        for item in items:
            title = item.get("title", "").lower()
            body  = item.get("body",  "")[:300].lower()
            if any(kw.lower() in title or kw.lower() in body for kw in keywords):
                relevant.append(item)
            if len(relevant) >= limit:
                break

        return [
            {
                "title":     item.get("title", ""),
                "source":    item.get("source_info", {}).get("name", item.get("source", "")),
                "url":       item.get("url", ""),
                "published": datetime.fromtimestamp(
                    int(item.get("published_on", 0)), tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "body":      item.get("body", "")[:200],
            }
            for item in relevant
        ]
    except Exception:
        return []


def fetch_cg_status_updates(cg_id: str) -> list[dict]:
    """CoinGecko status_updates — darmowy endpoint, zero kredytów."""
    if not cg_id:
        return []
    try:
        with client() as c:
            r = c.get(
                f"https://api.coingecko.com/api/v3/coins/{cg_id}/status_updates",
                params={"per_page": 5},
            )
        if r.status_code != 200:
            return []
        updates = r.json().get("status_updates", [])
        return [
            {
                "description": u.get("description", "")[:300],
                "category":    u.get("category", ""),
                "created_at":  u.get("created_at", "")[:10],
            }
            for u in updates[:5]
            if u.get("description")
        ]
    except Exception:
        return []


_GROK_RESPONSES_URL = "https://api.x.ai/v1/responses"
_GROK_MODEL         = "grok-4.3"


def _extract_responses_text(data: dict) -> str:
    """Extract text from xAI /v1/responses output array (same format as x_sentiment.py)."""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return c.get("text", "")
    return ""


def fetch_official_twitter_news(twitter_handle: str, symbol: str) -> list[str]:
    """Grok live search: ważne ogłoszenia z oficjalnego konta @{twitter_handle}.
    Używa xAI Responses API (grok-4.3 + x_search tool) — identyczny pattern co x_sentiment.py.
    Filtruje śmieci, zostawia tylko konkrety. Zwraca listę max 5 linii.
    """
    if not XAI_KEY or not twitter_handle:
        return []
    prompt = (
        f"Search recent posts (last 30 days) from the official X/Twitter account @{twitter_handle} "
        f"for the ${symbol} cryptocurrency project.\n"
        f"Extract ONLY substantive announcements — partnerships, exchange listings, "
        f"product launches, protocol upgrades, security incidents, tokenomics changes, "
        f"major milestones, governance votes, migration/swap deadlines.\n"
        f"SKIP: generic 'gm'/'gn' posts, price comments, retweets of others, "
        f"promotional hype, follower milestones, memes, routine replies.\n"
        f"Format each item as: [YYYY-MM-DD] SHORT_SUMMARY (1-2 sentences max).\n"
        f"List up to 5 items. If no important news found in 30 days, return exactly: "
        f"Brak waznych ogloszen w ostatnich 30 dniach."
    )
    try:
        with client() as c:
            r = c.post(
                _GROK_RESPONSES_URL,
                headers={"Authorization": f"Bearer {XAI_KEY}"},
                json={
                    "model":      _GROK_MODEL,
                    "input":      [{"role": "user", "content": prompt}],
                    "tools":      [{"type": "x_search"}],
                    "temperature": 0.1,
                    "max_output_tokens": 600,
                },
                timeout=45,
            )
        if r.status_code != 200:
            return [f"Grok error {r.status_code}: {r.text[:100]}"]
        text = _extract_responses_text(r.json()).strip()
        if not text:
            return ["Brak odpowiedzi od Grok"]
        lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 8]
        return lines[:5]
    except Exception as e:
        return [f"Twitter fetch error: {e}"]


def fetch_all_news(
    symbol: str,
    name: str = "",
    cg_id: str = "",
    twitter_handle: str = "",
    no_x: bool = False,
) -> dict:
    """Pobiera news ze wszystkich trzech warstw. Zwraca dict z kluczami:
       'google_news', 'cg_updates', 'twitter'
    """
    return {
        "cryptocompare": fetch_cryptocompare_news(symbol, name),
        "google_news":   fetch_google_news_rss(symbol, name),
        "cg_updates":    fetch_cg_status_updates(cg_id),
        "twitter":       [] if no_x else fetch_official_twitter_news(twitter_handle, symbol),
    }


# ── Analysis helpers ──────────────────────────────────────────────────────────

def rug_summary(gp: dict) -> tuple[str, list[str]]:
    """Returns (PASS/WARN/DANGER, list of flags)"""
    if not gp:
        return "UNKNOWN", ["GoPlus API nie odpowiedzial"]

    flags = []
    danger = 0

    checks = [
        ("is_honeypot",          "1", "HONEYPOT — nie mozesz sprzedac",     3),
        ("can_take_back_ownership","1", "Owner moze odebrac wlasnosc",        2),
        ("owner_change_balance", "1", "Owner moze zmienic saldo",            2),
        ("hidden_owner",         "1", "Ukryty owner",                        2),
        ("selfdestruct",         "1", "Kontrakt moze sie samozniszczyc",     2),
        ("external_call",        "1", "Zewnetrzne wywolania (ryzyko)",       1),
        ("is_mintable",          "1", "Mozna mintowac nowe tokeny",          1),
        ("transfer_pausable",    "1", "Transfer moze byc wstrzymany",        1),
        ("trading_cooldown",     "1", "Limit handlu (cooling down)",         1),
    ]

    for key, bad_val, msg, weight in checks:
        if str(gp.get(key, "")) == bad_val:
            flags.append(msg)
            danger += weight

    buy_tax  = float(gp.get("buy_tax",  0) or 0) * 100
    sell_tax = float(gp.get("sell_tax", 0) or 0) * 100
    if buy_tax > 10:
        flags.append(f"Wysoki podatek przy kupnie: {buy_tax:.1f}%")
        danger += 1
    if sell_tax > 10:
        flags.append(f"Wysoki podatek przy sprzedazy: {sell_tax:.1f}%")
        danger += 2

    lp_locked = gp.get("lp_holders", [])
    locked_pct = sum(float(h.get("percent", 0)) for h in lp_locked
                     if h.get("is_locked") == 1) * 100
    if locked_pct < 50 and lp_locked:
        flags.append(f"Tylko {locked_pct:.0f}% liquidity zablokowane")
        danger += 1
    elif locked_pct >= 80:
        flags.append(f"Liquidity {locked_pct:.0f}% zablokowane (dobry znak)")

    holder_count = int(gp.get("holder_count", 0) or 0)
    holders = gp.get("holders", [])
    if holders:
        top_holder_pct = float(holders[0].get("percent", 0)) * 100
        if top_holder_pct > 30:
            flags.append(f"Top holder trzyma {top_holder_pct:.1f}% supply (koncentracja)")
            danger += 1

    if danger >= 5:
        return "DANGER", flags
    elif danger >= 2:
        return "WARN", flags
    return "PASS", flags


def format_number(n) -> str:
    if n is None:
        return "N/A"
    n = float(n)
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.1f}K"
    return f"${n:.4f}"


# ── Main report ───────────────────────────────────────────────────────────────

def run_research(ca: str, chain: str, no_x: bool = False) -> None:
    chain_id = CHAIN_IDS.get(chain, "56")

    console.print(f"\n[bold]Fundamental Research[/bold] | {ca[:10]}... | chain: {chain}")
    console.print("[dim]Odpytuję: CoinGecko, DexScreener, GoPlus, Etherscan, GitHub, X...[/dim]\n")

    # Fetch all sources
    cg      = fetch_coingecko(ca, chain)
    pairs   = fetch_dexscreener(ca)
    gp      = fetch_goplus(ca, chain_id)
    src_data = fetch_etherscan_source(ca, chain_id)
    github  = []

    if cg:
        repo_urls = cg.get("links", {}).get("repos_url", {}).get("github", [])
        if repo_urls:
            github = fetch_github(repo_urls)

    # ── BASIC INFO ────────────────────────────────────────────────────────────
    name    = cg.get("name", ca[:8])
    symbol  = cg.get("symbol", "?").upper()
    md      = cg.get("market_data", {})
    mc      = md.get("market_cap", {}).get("usd")
    price   = md.get("current_price", {}).get("usd")
    vol24   = md.get("total_volume", {}).get("usd")
    ath     = md.get("ath", {}).get("usd")
    ath_pct = md.get("ath_change_percentage", {}).get("usd")
    ch7d    = md.get("price_change_percentage_7d")
    ch30d   = md.get("price_change_percentage_30d")
    supply_circ  = md.get("circulating_supply")
    supply_total = md.get("total_supply")
    fdv     = md.get("fully_diluted_valuation", {}).get("usd")

    website   = (cg.get("links", {}).get("homepage", [""])[0] or "").strip()
    twitter   = cg.get("links", {}).get("twitter_screen_name", "")
    telegram  = cg.get("links", {}).get("telegram_channel_identifier", "")
    desc      = cg.get("description", {}).get("en", "")[:400]

    # ── PANEL: OVERVIEW ───────────────────────────────────────────────────────
    pct_circ = (supply_circ / supply_total * 100) if supply_circ and supply_total else None
    overview = (
        f"[bold cyan]{name} (${symbol})[/bold cyan]\n"
        f"Cena:      {format_number(price)}\n"
        f"Market Cap:{format_number(mc)}   |   FDV: {format_number(fdv)}\n"
        f"Volume 24h:{format_number(vol24)}   |   MC/Vol ratio: "
        f"{(mc/vol24):.1f}x\n" if (mc and vol24 and vol24 > 0) else ""
        + (f"ATH:       {format_number(ath)}   |   Spadek od ATH: {ath_pct:.1f}%\n" if ath and ath_pct is not None else "")
        + (f"7 dni:     {ch7d:+.1f}%   |   30 dni: {ch30d:+.1f}%\n" if ch7d is not None and ch30d is not None else "")
        + (f"Supply:    {pct_circ:.0f}% w obiegu ({format_number(supply_circ)} / {format_number(supply_total)} max)\n" if pct_circ else "")
    )
    if website:
        overview += f"Strona:    {website}\n"
    if twitter:
        overview += f"Twitter:   @{twitter}\n"
    if telegram:
        overview += f"Telegram:  t.me/{telegram}\n"

    console.print(Panel(overview.strip(), title="[bold]Podstawowe dane[/bold]", expand=False))

    # ── PANEL: DESCRIPTION ────────────────────────────────────────────────────
    if desc:
        console.print(Panel(desc, title="[bold]Co to jest?[/bold]", expand=False))

    # ── PANEL: DEX LIQUIDITY ──────────────────────────────────────────────────
    if pairs:
        table = Table(title="Liquidity na DEX")
        table.add_column("DEX",        width=14)
        table.add_column("Liquidity",  justify="right", width=12)
        table.add_column("Vol 24h",    justify="right", width=12)
        table.add_column("Buys/Sells", justify="center", width=12)
        table.add_column("FDV",        justify="right", width=12)
        for p in pairs:
            liq  = format_number(p.get("liquidity", {}).get("usd"))
            vol  = format_number(p.get("volume", {}).get("h24"))
            fdv2 = format_number(p.get("fdv"))
            txns = p.get("txns", {}).get("h24", {})
            bs   = f"{txns.get('buys',0)}/{txns.get('sells',0)}"
            table.add_row(p.get("dexId", "?"), liq, vol, bs, fdv2)
        console.print(table)

    # ── PANEL: SECURITY ───────────────────────────────────────────────────────
    verdict, flags = rug_summary(gp)
    color = {"PASS": "green", "WARN": "yellow", "DANGER": "red", "UNKNOWN": "dim"}[verdict]

    flag_text = "\n".join(f"  {'[red]WARNING[/red]' if 'dobry' not in f.lower() else '[green]OK[/green]'} {f}" for f in flags) if flags else "  Brak ostrzezen"
    holder_count = int(gp.get("holder_count", 0) or 0)
    buy_tax  = float(gp.get("buy_tax",  0) or 0) * 100
    sell_tax = float(gp.get("sell_tax", 0) or 0) * 100
    owner    = gp.get("owner_address", "N/A")
    renounced = "TAK (bezpieczniej)" if gp.get("owner_address") in ("", "0x0000000000000000000000000000000000000000") else "NIE"

    sec_text = (
        f"[{color}]Wynik bezpieczenstwa: {verdict}[/{color}]\n\n"
        f"Liczba holderow:   {holder_count:,}\n"
        f"Podatek kupno/sprzedaz: {buy_tax:.1f}% / {sell_tax:.1f}%\n"
        f"Owner zrzekl sie kontroli: {renounced}\n\n"
        f"Flagi:\n{flag_text}"
    )
    console.print(Panel(sec_text, title="[bold]Bezpieczenstwo kontraktu (GoPlus)[/bold]", expand=False))

    # ── PANEL: SOURCE CODE (Etherscan) ───────────────────────────────────────
    if src_data:
        verified_color = "green" if src_data.get("verified") else "red"
        owner_f = src_data.get("owner_functions", [])
        dangers = src_data.get("dangers_found", [])
        d_color = "red" if dangers else "green"

        mint_note = ""
        if src_data.get("mint_external"):
            mint_note = "\n[red]UWAGA: mint() jest publiczny — owner moze tworzyc nowe tokeny![/red]"
        elif src_data.get("mint_internal_only"):
            mint_note = "\n[green]OK: mint() tylko wewnetrzny (uzywany w konstruktorze) — supply jest staly[/green]"

        vesting_note = "[green]TAK — kontrakt ma mechanizm stopniowego uwalniania[/green]" \
                       if src_data.get("has_vesting") else \
                       "[yellow]NIE — brak vestingu w kodzie[/yellow]"

        proxy_note = f"[yellow]PROXY → implementacja: {src_data['implementation']}[/yellow]" \
                     if src_data.get("is_proxy") else "[green]Nie jest proxy[/green]"

        src_text = (
            f"[{verified_color}]Zweryfikowany na blockchainie: {'TAK' if src_data.get('verified') else 'NIE'}[/{verified_color}]\n"
            f"Nazwa kontraktu:  {src_data.get('contract_name')}\n"
            f"Kompilator:       {src_data.get('compiler')}\n"
            f"Typ:              {proxy_note}\n"
            f"Vesting w kodzie: {vesting_note}\n"
            f"{mint_note}\n\n"
            f"Funkcje onlyOwner: {', '.join(owner_f) if owner_f else 'brak'}\n\n"
            f"[{d_color}]Niebezpieczne wzorce:[/{d_color}]\n"
            + ("\n".join(f"  [red]WARNING[/red] {d}" for d in dangers) if dangers
               else "  [green]Nie znaleziono niebezpiecznych wzorcow[/green]")
        )
        console.print(Panel(src_text, title="[bold]Analiza kodu kontraktu (Etherscan)[/bold]", expand=False))
    else:
        console.print(Panel("[dim]Etherscan: brak klucza lub kontrakt niezweryfikowany[/dim]",
                           title="[bold]Analiza kodu[/bold]", expand=False))

    # ── PANEL: GITHUB ─────────────────────────────────────────────────────────
    if github:
        for g in github:
            last = g.get("last_push", "?")
            days_ago = ""
            try:
                dt = datetime.fromisoformat(last + "T00:00:00+00:00")
                days_ago = f" ({(datetime.now(timezone.utc)-dt).days} dni temu)"
            except Exception:
                pass
            console.print(Panel(
                f"Repo:         {g['name']}\n"
                f"Gwiazdki:     {g['stars']:,}   |   Forki: {g['forks']:,}\n"
                f"Ostatni push: {last}{days_ago}\n"
                f"Otwarty issues: {g['open_issues']:,}\n"
                f"Jezyk:        {g['language']}",
                title="[bold]GitHub — aktywnosc deweloperska[/bold]", expand=False
            ))
    else:
        console.print(Panel("[dim]Brak repozytoriow GitHub — typowe dla wczesnych projektow lub projektow non-tech[/dim]",
                           title="[bold]GitHub[/bold]", expand=False))

    # ── X SENTIMENT ───────────────────────────────────────────────────────────
    if not no_x:
        console.print("\n[dim]Sprawdzam X/Twitter...[/dim]")
        x_out = fetch_x_sentiment(symbol)
        console.print(Panel(x_out, title="[bold]X / Twitter Sentiment[/bold]", expand=False))

    # ── NEWS & CATALYSTS ──────────────────────────────────────────────────────
    cg_id = cg.get("id", "")
    _news_sources = "CryptoCompare + Google News RSS"
    if not no_x and twitter:
        _news_sources += " + Twitter Grok"
    console.print(f"\n[dim]Pobieranie news ({_news_sources})...[/dim]")
    news = fetch_all_news(
        symbol=symbol,
        name=name,
        cg_id=cg_id,
        twitter_handle=twitter,
        no_x=no_x,
    )

    cc_items = news.get("cryptocompare", [])
    gn_items = news.get("google_news", [])
    cg_upd   = news.get("cg_updates", [])
    tw_items = news.get("twitter", [])
    has_news = cc_items or gn_items or cg_upd or tw_items

    if has_news:
        news_lines = []
        if tw_items:
            news_lines.append(f"[bold cyan]🐦 Oficjalny Twitter (@{twitter})[/bold cyan]")
            news_lines.extend(f"  {l}" for l in tw_items)
            news_lines.append("")
        if cg_upd:
            news_lines.append("[bold cyan]🦎 CoinGecko Status Updates[/bold cyan]")
            for u in cg_upd:
                news_lines.append(f"  [{u['created_at']}] [dim]{u['category']}[/dim] {u['description'][:180]}")
            news_lines.append("")
        if cc_items:
            news_lines.append("[bold cyan]📡 CryptoCompare News[/bold cyan]")
            for n in cc_items:
                news_lines.append(f"  {n['published']} [{n['source']}] {n['title'][:80]}")
            news_lines.append("")
        if gn_items:
            news_lines.append("[bold cyan]🔍 Google News[/bold cyan]")
            for n in gn_items:
                news_lines.append(f"  {n['published']} [{n['source']}] {n['title'][:80]}")
        console.print(Panel("\n".join(news_lines), title="[bold]📰 News & Catalysts[/bold]", expand=False))
    else:
        console.print(Panel("[dim]Brak newsów z żadnego źródła.[/dim]", title="[bold]📰 News & Catalysts[/bold]", expand=False))

    # ── EXPERT VIEW ───────────────────────────────────────────────────────────
    # Buduj syntetyczną ocenę na podstawie wszystkich danych
    score = 5  # bazowy
    positives, negatives = [], []

    if mc and mc < 5_000_000:
        positives.append(f"Maly market cap ({format_number(mc)}) — duzy potencjal wzrostu jesli projekt jest legitymny")
    if ch30d and ch30d > 30:
        positives.append(f"Wzrost +{ch30d:.0f}% w ostatnich 30 dniach — momentum")
    if pairs and pairs[0].get("liquidity", {}).get("usd", 0) > 200_000:
        positives.append(f"Dobra liquidity ({format_number(pairs[0]['liquidity']['usd'])}) — mozesz wejsc i wyjsc")
    if github:
        positives.append("Aktywne repozytorium GitHub — projekt ma kod")
    if verdict == "PASS":
        positives.append("Kontrakt przeszedl audyt bezpieczenstwa GoPlus")

    if not github:
        negatives.append("Brak GitHub — nie mozna zweryfikowac kodu")
    if ath_pct and ath_pct < -80:
        negatives.append(f"Spadek {ath_pct:.0f}% od ATH — wiele portfeli jest pod woda, presja sprzedazy")
    if verdict in ("WARN", "DANGER"):
        negatives.append(f"Flagi bezpieczenstwa: {', '.join(flags[:2])}")
    if website and "floki" in website.lower():
        negatives.append("Strona na subdomenie floki.id — brak wlasnej domeny to zly sygnal dla powaznego projektu AI")
    if vol24 and mc and vol24 / mc < 0.02:
        negatives.append(f"Niskie dzienne volume ({vol24/mc*100:.1f}% MC) — maly zainteresowanie rynku")

    # News catalyst signal
    if "news" in dir():
        total_news = (len(news.get("cryptocompare", [])) + len(news.get("google_news", []))
                      + len(news.get("cg_updates", [])) + len(news.get("twitter", [])))
        if total_news >= 3:
            positives.append(f"Aktywne media — {total_news} nowych newsów/ogłoszeń")
        elif total_news == 0:
            negatives.append("Brak aktualnych newsów — projekt może być nieaktywny lub zapomniany")

    pos_text = "\n".join(f"  + {p}" for p in positives) or "  brak wyraznych plusow"
    neg_text = "\n".join(f"  - {n}" for n in negatives) or "  brak wyraznych minusow"

    conviction = min(max(3 + len(positives) - len(negatives), 1), 9)
    overall = "Neutralnie" if conviction <= 5 else ("Ciekawa opcja" if conviction <= 7 else "Mocny sygnał")

    expert = (
        f"[bold]Ogolna ocena: {overall}[/bold] — conviction: {conviction}/10\n\n"
        f"[green]Plusy:[/green]\n{pos_text}\n\n"
        f"[red]Minusy:[/red]\n{neg_text}\n\n"
        f"[bold]Edge:[/bold] Wiekszosc retail patrzy tylko na cene i volume. Ty masz pelny obraz: "
        f"kontrakt, liquidity, bezpieczenstwo i sentiment razem.\n\n"
        f"[bold]Co sprawdzic recznie:[/bold]\n"
        f"  1. Odwiedz {website or 'strone projektu'} — czy team jest doxxed (znani z imienia i nazwiska)?\n"
        f"  2. Twitter @{twitter} — kiedy ostatni tweet, jaka aktywnosc?\n"
        f"  3. Telegram t.me/{telegram} — ile czlonkow, jaka aktywnosc?\n"
        f"  4. Czy jest audit bezpieczenstwa (CertiK, Hacken) — szukaj na stronie"
    )

    console.print(Panel(expert, title="[bold]EXPERT VIEW[/bold]", expand=False))

    # ── Save markdown report (inline — bezpośredni dostęp do wszystkich zmiennych) ──
    try:
        def _n(v, d=2):
            if v is None: return "N/A"
            v = float(v)
            if v >= 1e9:  return f"${v/1e9:.2f}B"
            if v >= 1e6:  return f"${v/1e6:.2f}M"
            if v >= 1e3:  return f"${v/1e3:.1f}K"
            return f"${v:.{d}f}"

        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        _path  = _cache_filename(symbol, chain, ca, _today)

        _md = []
        _md += [
            f"# 🔍 Token Research: {symbol} — {name}",
            f"",
            f"**Ticker:** `${symbol}` | **Contract:** `{ca}` | **Chain:** {chain}",
            f"**Research:** {_ts} | **Cache valid 7 days**",
            f"",
        ]

        # ── OVERVIEW ──
        _md += ["---", "", "## 📊 Podstawowe dane", ""]
        _md += ["| Metryka | Wartość |", "|---------|---------|"]
        _md.append(f"| Cena | {_n(price, 6)} |")
        _md.append(f"| Market Cap | {_n(mc)} |")
        _md.append(f"| FDV | {_n(fdv)} |")
        _md.append(f"| Volume 24h | {_n(vol24)} |")
        if mc and vol24 and vol24 > 0:
            _md.append(f"| MC/Vol ratio | {mc/vol24:.2f}x |")
        if ath is not None:
            _md.append(f"| ATH | {_n(ath, 6)} |")
        if ath_pct is not None:
            _md.append(f"| Spadek od ATH | {ath_pct:.1f}% |")
        if ch7d is not None:
            _md.append(f"| Zmiana 7d | {ch7d:+.1f}% |")
        if ch30d is not None:
            _md.append(f"| Zmiana 30d | {ch30d:+.1f}% |")
        if pct_circ:
            _md.append(f"| Supply w obiegu | {pct_circ:.0f}% ({_n(supply_circ)} / {_n(supply_total)} max) |")
        if website:  _md.append(f"| Strona | {website} |")
        if twitter:  _md.append(f"| Twitter | [@{twitter}](https://x.com/{twitter}) |")
        if telegram: _md.append(f"| Telegram | [t.me/{telegram}](https://t.me/{telegram}) |")

        # ── DESCRIPTION ──
        if desc:
            _md += ["", "---", "", "## 📖 Co to jest?", "", desc, ""]

        # ── DEX LIQUIDITY ──
        if pairs:
            _md += ["---", "", "## 💧 Liquidity (DexScreener)", ""]
            _md += ["| DEX | Liquidity | Vol 24h | Buys/Sells | FDV |",
                    "|-----|-----------|---------|-----------|-----|"]
            for _p in pairs:
                _liq  = _n(_p.get("liquidity", {}).get("usd"))
                _vol  = _n(_p.get("volume", {}).get("h24"))
                _fdv2 = _n(_p.get("fdv"))
                _txns = _p.get("txns", {}).get("h24", {})
                _bs   = f"{_txns.get('buys',0)}/{_txns.get('sells',0)}"
                _md.append(f"| {_p.get('dexId','?')} | {_liq} | {_vol} | {_bs} | {_fdv2} |")

        # ── SECURITY (GoPlus) ──
        _md += ["", "---", "", "## 🔐 Bezpieczeństwo (GoPlus)", ""]
        _verdict_icon = {"PASS": "✅", "WARN": "⚠️", "DANGER": "🚨", "UNKNOWN": "❓"}.get(verdict, "❓")
        _md.append(f"**Wynik:** {_verdict_icon} `{verdict}`")
        _md += ["", f"| Metryka | Wartość |", f"|---------|---------|"]
        _md.append(f"| Holders | {holder_count:,} |")
        _md.append(f"| Podatek kupno/sprzedaż | {buy_tax:.1f}% / {sell_tax:.1f}% |")
        _md.append(f"| Owner zrzekł się kontroli | {renounced} |")
        if flags:
            _md += ["", "**Flagi:**"]
            for _f in flags:
                _icon = "✅" if "dobry" in _f.lower() or "zablokowane" in _f.lower() and "0%" not in _f else "⚠️"
                _md.append(f"- {_icon} {_f}")

        # ── ETHERSCAN / SOURCE CODE ──
        _md += ["", "---", "", "## 📜 Analiza kodu kontraktu (Etherscan)", ""]
        if src_data and src_data.get("verified"):
            _owner_f = src_data.get("owner_functions", [])
            _dangers = src_data.get("dangers_found", [])
            _md += [
                f"- **Zweryfikowany:** ✅ TAK",
                f"- **Nazwa:** `{src_data.get('contract_name','?')}`",
                f"- **Kompilator:** {src_data.get('compiler','?')}",
                f"- **Typ:** {'🔄 PROXY → ' + src_data.get('implementation','') if src_data.get('is_proxy') else '✅ Nie jest proxy'}",
                f"- **Vesting w kodzie:** {'✅ TAK' if src_data.get('has_vesting') else '⚠️ NIE'}",
            ]
            if src_data.get("mint_external"):
                _md.append("- **Mint:** 🚨 mint() jest PUBLICZNY — owner może tworzyć nowe tokeny!")
            elif src_data.get("mint_internal_only"):
                _md.append("- **Mint:** ✅ mint() tylko wewnętrzny — supply jest stały")
            if _owner_f:
                _md.append(f"- **Funkcje onlyOwner:** `{', '.join(_owner_f)}`")
            if _dangers:
                _md += ["", "**⚠️ Niebezpieczne wzorce:**"]
                for _d in _dangers:
                    _md.append(f"- 🚨 {_d}")
            else:
                _md.append("- ✅ Nie znaleziono niebezpiecznych wzorców")
        else:
            _md.append("_Kontrakt niezweryfikowany lub brak klucza Etherscan._")

        # ── GITHUB ──
        _md += ["", "---", "", "## 💻 GitHub", ""]
        if github:
            for _g in github:
                _last = _g.get("last_push", "?")
                _ago = ""
                try:
                    _dt = datetime.fromisoformat(_last + "T00:00:00+00:00")
                    _ago = f" ({(datetime.now(timezone.utc)-_dt).days} dni temu)"
                except Exception:
                    pass
                _md += [
                    f"- **Repo:** [{_g['name']}](https://github.com/{_g['name']})",
                    f"- **Gwiazdki:** {_g['stars']:,} | **Forki:** {_g['forks']:,} | **Open issues:** {_g['open_issues']:,}",
                    f"- **Ostatni push:** {_last}{_ago} | **Język:** {_g.get('language','?')}",
                ]
        else:
            _md.append("_Brak repozytoriów GitHub._")

        # ── X SENTIMENT ──
        if not no_x and "x_out" in dir() and x_out:
            _md += ["", "---", "", "## 🐦 X/Twitter Sentiment (market)", "", "```"]
            _md += x_out.split("\n")
            _md += ["```"]

        # ── NEWS & CATALYSTS ──
        _nd = news if "news" in dir() else {}
        _cc  = _nd.get("cryptocompare", [])
        _gn  = _nd.get("google_news", [])
        _cgu = _nd.get("cg_updates", [])
        _tw  = _nd.get("twitter", [])
        _md += ["", "---", "", "## 📰 News & Catalysts", ""]

        if _tw:
            _md += [f"### 🐦 Oficjalny Twitter (@{twitter})", ""]
            for _item in _tw:
                _md.append(f"- {_item}")
            _md.append("")
        if _cgu:
            _md += ["### 🦎 CoinGecko Status Updates", ""]
            for _u in _cgu:
                _md.append(f"- **[{_u['created_at']}]** `{_u['category']}` — {_u['description'][:300]}")
            _md.append("")
        if _cc:
            _md += ["### 📡 CryptoCompare News", "", "| Data | Tytuł | Źródło |", "|------|-------|--------|"]
            for _item in _cc:
                _tl = f"[{_item['title'][:70]}]({_item['url']})" if _item.get("url") else _item["title"][:70]
                _md.append(f"| {_item['published']} | {_tl} | {_item['source']} |")
            _md.append("")
        if _gn:
            _md += ["### 🔍 Google News", "", "| Data | Tytuł | Źródło |", "|------|-------|--------|"]
            for _item in _gn:
                _tl = f"[{_item['title'][:70]}]({_item['url']})" if _item.get("url") else _item["title"][:70]
                _md.append(f"| {_item['published']} | {_tl} | {_item['source']} |")
            _md.append("")
        if not (_tw or _cgu or _cc or _gn):
            _md.append("_Brak newsów z żadnego źródła._")

        # ── EXPERT VIEW ──
        _md += ["", "---", "", "## 🎯 Expert View", ""]
        _ov_icon = {"Neutralnie": "🔸", "Ciekawa opcja": "🟡", "Mocny sygnał": "🟢"}.get(overall, "🔸")
        _md += [
            f"**Ocena ogólna:** {_ov_icon} {overall}",
            f"**Conviction:** {conviction}/10",
            "",
            "### ✅ Plusy",
        ]
        for _p in positives:
            _md.append(f"- {_p}")
        if not positives:
            _md.append("- _(brak wyraźnych plusów)_")
        _md += ["", "### ❌ Minusy"]
        for _neg in negatives:
            _md.append(f"- {_neg}")
        if not negatives:
            _md.append("- _(brak wyraźnych minusów)_")
        _md += [
            "",
            "### 🔎 Co sprawdzić ręcznie",
            f"1. [{website}]({website}) — czy team jest doxxed?" if website else "1. Strona projektu — czy team jest doxxed?",
            f"2. [@{twitter}](https://x.com/{twitter}) — kiedy ostatni tweet, jaka aktywność?" if twitter else "2. Twitter projektu",
            f"3. [t.me/{telegram}](https://t.me/{telegram}) — ile członków, jaka aktywność?" if telegram else "3. Telegram projektu",
            "4. Audit bezpieczeństwa (CertiK, Hacken, PeckShield) — szukaj na stronie",
            "",
            "---",
            f"*Wygenerowano automatycznie przez token_research.py | {_ts}*",
        ]

        _path.write_text("\n".join(_md), encoding="utf-8")
        console.print(f"\n[green]💾 Raport zapisany →[/green] [cyan]{_path.relative_to(ROOT)}[/cyan]")
    except Exception as _e:
        console.print(f"[yellow]Zapis raportu: błąd — {_e}[/yellow]")

    # ── Save to DB ──
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).parent))
        from db import DB as _DB
        _db = _DB()
        _db.save_token_research(
            ticker=symbol,
            contract=ca,
            data={
                "chain": chain,
                "name": name or symbol,
                "price_usd": price,
                "mcap_usd": mc,
                "rug_score": verdict,
                "verdict": overall,
                "summary": f"conviction={conviction}/10 | {'; '.join(positives[:2])}",
            },
        )
    except Exception:
        pass


def main() -> None:
    p = argparse.ArgumentParser(description="Deep fundamental token research")
    p.add_argument("token",    nargs="?", default="", help="Contract address (0x...) or ticker")
    p.add_argument("--chain",  default="bsc",
                   choices=["bsc", "eth", "base", "polygon"],
                   help="Blockchain (default: bsc)")
    p.add_argument("--no-x",   action="store_true", help="Skip X sentiment search")
    p.add_argument("--force",  action="store_true", help="Ignoruj cache, rób fresh research")
    p.add_argument("--list",   action="store_true", help="Pokaż wszystkie zapisane raporty")
    args = p.parse_args()

    # ── --list: pokaż zapisane raporty ──
    if args.list:
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(RESEARCH_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            console.print("[dim]Brak zapisanych raportów w reports/research/[/dim]")
        else:
            from rich.table import Table as _T
            t = _T(title=f"Token Research Cache ({len(files)} raportów)")
            t.add_column("Plik", style="cyan")
            t.add_column("Data", style="dim")
            t.add_column("Rozmiar", justify="right", style="dim")
            from datetime import datetime as _dt
            for f in files:
                mtime = _dt.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                size  = f"{f.stat().st_size // 1024}KB" if f.stat().st_size > 1024 else f"{f.stat().st_size}B"
                t.add_row(f.name, mtime, size)
            console.print(t)
            console.print(f"\n[dim]Folder: {RESEARCH_DIR}[/dim]")
        return

    token = args.token.strip()

    # ── Cache check (skip if --force) ──
    if not args.force:
        cached = find_cached_report(token, args.chain)
        if cached:
            age = (datetime.now(timezone.utc).date() -
                   datetime.strptime(cached.stem.split("_")[-1], "%Y-%m-%d").date()).days
            console.print(
                f"\n[green]📋 Znaleziono raport w cache[/green] "
                f"[dim]({cached.name}, {age}d temu)[/dim]\n"
                f"[dim]Użyj [bold]--force[/bold] aby zrobić fresh research.[/dim]\n"
            )
            console.print(cached.read_text(encoding="utf-8"))
            return
    # Auto-detect Solana (base58 address, no 0x prefix, 32-44 chars)
    if is_solana_address(token):
        console.print(f"[cyan]Auto-detected: Solana token[/cyan]")
        run_solana_research(token, no_x=args.no_x)
        return

    if not token.startswith("0x"):
        console.print(f"[yellow]Szukam {token} po tickerze...[/yellow]")
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r = c.get(f"https://api.coingecko.com/api/v3/search?query={token}")
        coins = r.json().get("coins", [])
        if not coins:
            console.print("[red]Nie znaleziono tokena[/red]")
            sys.exit(1)
        coin_id = coins[0]["id"]
        console.print(f"[green]Znaleziono: {coins[0]['name']} ({coin_id})[/green]")
        with httpx.Client(verify=_SSL, timeout=15) as c:
            r2 = c.get(f"https://api.coingecko.com/api/v3/coins/{coin_id}")
        platforms = r2.json().get("detail_platforms", {})
        chain_platform = CG_PLATFORMS.get(args.chain)
        ca = platforms.get(chain_platform, {}).get("contract_address", "")
        if not ca:
            for plat, data in platforms.items():
                if data.get("contract_address"):
                    ca = data["contract_address"]
                    break
        if not ca:
            console.print("[red]Nie znaleziono adresu kontraktu[/red]")
            sys.exit(1)
        console.print(f"Kontrakt: [cyan]{ca}[/cyan]")
        token = ca
        if is_solana_address(token):
            run_solana_research(token, no_x=args.no_x)
            return

    run_research(token, args.chain, no_x=args.no_x)


if __name__ == "__main__":
    main()
