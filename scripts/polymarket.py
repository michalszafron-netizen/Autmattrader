"""Polymarket prediction market data — public API, no key needed.

Fetches active markets relevant to crypto, macro, Fed, geopolitics.
Adds smart interpretation of probabilities for BTC/ETH/Gold/Oil positions.

Usage:
    python scripts/polymarket.py              # key markets summary
    python scripts/polymarket.py --brief      # one-liner for daily alpha
    python scripts/polymarket.py --all        # all active markets (top 30)
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
from pathlib import Path

import httpx
import truststore
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console  = Console()
_SSL     = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
API_URL  = "https://gamma-api.polymarket.com"

# Keywords dla filtrowania rynkow istotnych dla nas
RELEVANT_KEYWORDS = [
    # Fed / macro
    "fed", "rate", "interest", "fomc", "powell", "inflation", "cpi", "pce",
    "recession", "gdp", "unemployment", "tariff", "trade war",
    # Crypto
    "bitcoin", "btc", "ethereum", "eth", "crypto", "sec", "etf", "solana", "sol",
    "hype", "hyperliquid",
    # TradFi commodities
    "gold", "silver", "oil", "crude", "opec",
    # Geopolitics
    "iran", "russia", "ukraine", "nato", "china", "taiwan", "war", "ceasefire",
    "israel", "middle east", "north korea",
    # US politics
    "trump", "congress", "election", "senate",
]

# Jak interpretowac prawdopodobienstwo dla naszych assetow
# Format: (substring_in_question, threshold_yes, msg_if_above, msg_if_below)
INTERPRETATIONS = [
    # Fed
    ("fed cut",   0.5, "Crowd spodziewa sie ciec stop => bullish BTC/Gold, bearish USD",
                       "Crowd nie spodziewa sie ciec => bearish BTC, bullish USD"),
    ("rate cut",  0.5, "Wiecej szans na tanie pieniadze => risk-on, BTC/akcje w gore",
                       "Mniejsze szanse na ciecia => risk-off"),
    ("fomc",      0.5, "Crowd liczy na golebia decyzje Fed", "Crowd liczy na jastrzebia decyzje Fed"),
    # BTC
    ("bitcoin",   0.5, "Crowd bullish BTC", "Crowd bearish BTC"),
    ("btc",       0.5, "Crowd bullish BTC", "Crowd bearish BTC"),
    # ETH
    ("ethereum",  0.5, "Crowd bullish ETH", "Crowd bearish ETH"),
    ("eth etf",   0.6, "Crypto regulacje pozytywne => bullish caly sektor",
                       "Ryzyko odrzucenia ETF => bearish ETH/BTC"),
    ("eth",       0.5, "Crowd bullish ETH", "Crowd bearish ETH"),
    # Macro risk
    ("recession", 0.3, "Mala szansa recesji => risk-on",
                       "Wysoka szansa recesji => risk-off, zloto i USD jako hedge"),
    ("tariff",    0.5, "Taryfy rosna => stagflacja, risk-off, presja na akcje/BTC",
                       "Taryfy lagodnieja => risk-on, akcje w gore"),
    ("trade war", 0.5, "Eskalacja war handlowej => risk-off",
                       "De-eskalacja => risk-on"),
    # Geopolitics
    ("iran",      0.4, "Iran deal mozliwy => Oil spada (wiecej podazy)",
                       "Iran deal malo prawdopodobny => Oil stabilny/wyzej"),
    ("ukraine",   0.5, "Pokoj na Ukrainie => risk-on, Oil/Gas tanieje",
                       "Konflikt trwa => risk-off, energia droga"),
    ("ceasefire", 0.5, "Rozejm mozliwy => risk-on, energia tanieje",
                       "Rozejm malo prawdopodobny => ryzyko geopolityczne"),
    ("nato",      0.5, "Stabilnosc NATO => risk-on",
                       "Napiecia w NATO => risk-off"),
    ("china",     0.5, "Stabilne relacje USA-Chiny => risk-on",
                       "Napiecia z Chinami => risk-off, presja na supply chain"),
    ("taiwan",    0.3, "Napiecia o Tajwan rosna => ekstremalne risk-off",
                       "Napiecia o Tajwan male"),
    # TradFi
    ("oil",       0.5, "Crowd bullish Oil", "Crowd bearish Oil"),
    ("crude",     0.5, "Crowd bullish Oil", "Crowd bearish Oil"),
    ("gold",      0.5, "Crowd bullish Gold => zloto jako safe haven rozne",
                       "Crowd bearish Gold"),
    ("silver",    0.5, "Crowd bullish Silver", "Crowd bearish Silver"),
    # US politics
    ("trump",     0.5, "Pro-crypto, pro-deregulacja => bullish BTC/akcje",
                       ""),
    ("sec",       0.5, "Pozytywna regulacja crypto => risk-on dla sektora",
                       "Negatywna regulacja => presja na ceny"),
]


def fetch_markets(limit: int = 100) -> list[dict]:
    with httpx.Client(verify=_SSL, timeout=20) as c:
        r = c.get(f"{API_URL}/markets",
                  params={"active": "true", "limit": limit, "order": "volume24hr",
                          "ascending": "false"})
    r.raise_for_status()
    return r.json()


def is_relevant(market: dict) -> bool:
    text = (market.get("question", "") + " " + market.get("description", "")).lower()
    return any(kw in text for kw in RELEVANT_KEYWORDS)


def get_probability(market: dict) -> float | None:
    """Get YES probability from market outcomes."""
    import json as _json
    try:
        outcomes = market.get("outcomes", "[]")
        prices   = market.get("outcomePrices", "[]")
        if isinstance(outcomes, str):
            outcomes = _json.loads(outcomes)
        if isinstance(prices, str):
            prices = [float(p) for p in _json.loads(prices)]
        for i, o in enumerate(outcomes):
            if "yes" in str(o).lower() and i < len(prices):
                return float(prices[i])
    except Exception:
        pass
    return None


def interpret(question: str, prob: float) -> str:
    q = question.lower()
    for kw, threshold, bull_msg, bear_msg in INTERPRETATIONS:
        if kw in q:
            if prob >= threshold:
                return bull_msg if bull_msg else ""
            else:
                return bear_msg if bear_msg else ""
    return ""


def format_prob(p: float) -> tuple[str, str]:
    """Return (colored_string, color)"""
    if p >= 0.70:   return f"{p*100:.0f}%", "green"
    if p >= 0.50:   return f"{p*100:.0f}%", "yellow"
    if p >= 0.30:   return f"{p*100:.0f}%", "orange3"
    return f"{p*100:.0f}%", "red"


def display_markets(markets: list[dict]) -> None:
    relevant = [m for m in markets if is_relevant(m)][:20]
    if not relevant:
        console.print("[dim]No relevant markets found[/dim]")
        return

    console.print("\n[bold]Polymarket — rynki istotne dla portfela[/bold]\n")
    for m in relevant:
        prob = get_probability(m)
        if prob is None:
            continue
        q     = m.get("question", "")
        vol   = float(m.get("volume24hr", 0) or 0)
        vol_s = f"${vol/1000:.0f}K" if vol >= 1000 else f"${vol:.0f}"
        p_str, color = format_prob(prob)
        interp = interpret(q, prob)
        console.print(f"  [{color}]{p_str:>5}[/{color}] YES | vol:{vol_s:>7} | {q[:60]}")
        if interp:
            console.print(f"         [dim]=>{interp[:70]}[/dim]")

    console.print()
    _expert_view(relevant)


def _expert_view(markets: list[dict]) -> None:
    insights = []
    warnings = []

    for m in markets:
        prob = get_probability(m)
        if prob is None:
            continue
        q = m.get("question", "").lower()
        vol = float(m.get("volume24hr", 0) or 0)

        # Fed cut — kluczowe dla BTC
        if any(kw in q for kw in ["fed cut", "rate cut", "fomc"]):
            if prob > 0.6:
                insights.append(f"Crowd ({prob*100:.0f}%) spodziewa sie ciecia stop => tailwind dla BTC/Gold")
            elif prob < 0.35:
                warnings.append(f"Mala szansa ciecia stop ({prob*100:.0f}%) => headwind dla crypto/akcji")

        # Recession risk
        if "recession" in q and vol > 10000:
            if prob > 0.45:
                warnings.append(f"Ryzyko recesji {prob*100:.0f}% => rozważ hedge na Gold, ogranicz akcje")
            else:
                insights.append(f"Niska szansa recesji ({prob*100:.0f}%) => risk-on environment")

        # Crypto specific — BTC
        if any(kw in q for kw in ["bitcoin", "btc 100", "btc hit", "btc reach", "btc above"]) and vol > 5000:
            insights.append(f"BTC crowd: {prob*100:.0f}% YES na '{m.get('question','')[:45]}'")

        # Crypto specific — ETH
        if any(kw in q for kw in ["ethereum", "eth 5000", "eth 4000", "eth 3000", "eth reach", "eth above", "eth etf"]) and vol > 1000:
            ec = "green" if prob > 0.5 else "yellow"
            insights.append(f"ETH crowd: [{ec}]{prob*100:.0f}%[/{ec}] YES na '{m.get('question','')[:45]}'")

        # Gold price targets
        if any(kw in q for kw in ["gold 3000", "gold 3500", "gold hit", "gold reach", "gold above"]) and vol > 1000:
            insights.append(f"Gold crowd: {prob*100:.0f}% YES na '{m.get('question','')[:45]}'")

        # Geopolitics
        if "iran" in q and vol > 1000:
            if prob > 0.5:
                warnings.append(f"Iran deal mozliwy ({prob*100:.0f}%) => Oil pod presja")

        if any(kw in q for kw in ["ukraine", "ceasefire", "peace"]) and vol > 2000:
            if prob > 0.5:
                insights.append(f"Rozejm/pokoj UA: {prob*100:.0f}% => risk-on, energia tanieje")
            else:
                warnings.append(f"Pokoj UA malo prawdopodobny ({prob*100:.0f}%) => ryzyko geopolityczne")

        if "taiwan" in q and vol > 1000:
            if prob > 0.3:
                warnings.append(f"Napiecia Tajwan: {prob*100:.0f}% => potencjalne ekstremalne risk-off")

        if "tariff" in q and vol > 2000:
            if prob > 0.5:
                warnings.append(f"Taryfy: {prob*100:.0f}% => stagflacja, presja na akcje/BTC")
            else:
                insights.append(f"Taryfy lagodnieja: {(1-prob)*100:.0f}% szansa na de-eskalacje => risk-on")

    if not insights and not warnings:
        console.print(Panel("[dim]Brak wyraznych sygnalow z prediction markets na teraz[/dim]",
                           title="[bold]Smart Interpretation[/bold]", expand=False))
        return

    text = ""
    if insights:
        text += "[green]Sygnaly pozytywne:[/green]\n"
        text += "\n".join(f"  + {i}" for i in insights)
    if warnings:
        if text: text += "\n\n"
        text += "[yellow]Sygnaly ostrzegawcze:[/yellow]\n"
        text += "\n".join(f"  ! {w}" for w in warnings)

    console.print(Panel(text, title="[bold]Smart Interpretation — wplyw na portfel[/bold]", expand=False))


def display_brief(markets: list[dict]) -> None:
    relevant = [m for m in markets if is_relevant(m)][:15]

    # Kategoryzuj po tematach
    categories = {
        "BTC/ETH":      [],
        "Fed/Macro":    [],
        "Geopolityka":  [],
        "Gold/Oil":     [],
    }
    for m in relevant:
        prob = get_probability(m)
        if prob is None:
            continue
        q   = m.get("question", "")
        ql  = q.lower()
        vol = float(m.get("volume24hr", 0) or 0)
        entry = f"{q[:40]}: {prob*100:.0f}%"
        if any(kw in ql for kw in ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana"]):
            categories["BTC/ETH"].append((vol, entry))
        elif any(kw in ql for kw in ["fed", "rate", "fomc", "inflation", "recession", "tariff", "gdp"]):
            categories["Fed/Macro"].append((vol, entry))
        elif any(kw in ql for kw in ["iran", "ukraine", "russia", "nato", "taiwan", "war", "ceasefire", "israel"]):
            categories["Geopolityka"].append((vol, entry))
        elif any(kw in ql for kw in ["gold", "silver", "oil", "crude", "opec"]):
            categories["Gold/Oil"].append((vol, entry))

    lines = []
    for cat, items in categories.items():
        top = sorted(items, key=lambda x: -x[0])[:2]
        if top:
            lines.append(f"{cat}: " + " | ".join(e for _, e in top))

    if lines:
        print("Polymarket (crowd consensus):")
        for l in lines:
            print(f"  • {l}")
    else:
        print("Polymarket: brak danych")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--brief", action="store_true")
    p.add_argument("--all",   action="store_true")
    args = p.parse_args()

    try:
        limit = 100 if args.all else 50
        markets = fetch_markets(limit)
    except Exception as e:
        console.print(f"[red]Polymarket API error: {e}[/red]")
        sys.exit(1)

    if args.brief:
        display_brief(markets)
    else:
        display_markets(markets)


if __name__ == "__main__":
    main()
