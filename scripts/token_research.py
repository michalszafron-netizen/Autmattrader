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

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "")
ETHERSCAN_V2  = "https://api.etherscan.io/v2/api"
HELIUS_KEY    = os.getenv("HELIUS_API_KEY", "")
BIRDEYE_KEY   = os.getenv("BIRDEYE_API_KEY", "")

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
    return r.json().get("pairs", [])[:3]


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
    p.add_argument("token",   help="Contract address (0x...) or ticker")
    p.add_argument("--chain", default="bsc",
                   choices=["bsc", "eth", "base", "polygon"],
                   help="Blockchain (default: bsc)")
    p.add_argument("--no-x",  action="store_true", help="Skip X sentiment search")
    args = p.parse_args()

    token = args.token.strip()
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
