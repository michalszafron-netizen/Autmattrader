"""Economic calendar — FinnHub API + impact analyzer.

Usage:
    python scripts/econ_calendar.py                    # today's events
    python scripts/econ_calendar.py --days 3           # next 3 days
    python scripts/econ_calendar.py --brief            # one-liner for daily alpha
    python scripts/econ_calendar.py --impact CPI 3.4 3.1   # analyze surprise
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY  = os.getenv("FINNHUB_API_KEY", "")
BASE_URL = "https://finnhub.io/api/v1"
console  = Console()
_SSL     = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

# High-impact events that move crypto/commodities/FX
HIGH_IMPACT_KEYWORDS = [
    "nonfarm", "nfp", "payroll", "cpi", "pce", "inflation", "fomc", "fed",
    "interest rate", "gdp", "retail sales", "unemployment", "jobless",
    "ppi", "ism", "pmi", "core", "jackson hole", "powell",
]

# How each event affects our assets
MARKET_IMPACT = {
    "cpi":        {"BTC": "high", "GOLD": "high", "OIL": "medium", "USD": "high", "SPX": "high"},
    "pce":        {"BTC": "high", "GOLD": "high", "OIL": "low",    "USD": "high", "SPX": "high"},
    "fomc":       {"BTC": "high", "GOLD": "high", "OIL": "medium", "USD": "high", "SPX": "high"},
    "nonfarm":    {"BTC": "medium", "GOLD": "medium", "OIL": "low", "USD": "high", "SPX": "high"},
    "gdp":        {"BTC": "medium", "GOLD": "medium", "OIL": "medium", "USD": "high", "SPX": "high"},
    "retail":     {"BTC": "low",  "GOLD": "low",    "OIL": "low",    "USD": "medium", "SPX": "medium"},
}


def _ssl_client() -> httpx.Client:
    return httpx.Client(verify=_SSL, timeout=15)


def fetch_calendar(date_from: str, date_to: str) -> list[dict]:
    with _ssl_client() as c:
        r = c.get(f"{BASE_URL}/calendar/economic",
                  params={"from": date_from, "to": date_to, "token": API_KEY})
        r.raise_for_status()
    return r.json().get("economicCalendar", [])


def is_high_impact(event: dict) -> bool:
    name = (event.get("event") or "").lower()
    impact = (event.get("impact") or "").lower()
    if impact in ("high", "3"):
        return True
    return any(kw in name for kw in HIGH_IMPACT_KEYWORDS)


def format_time(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M UTC")
    except Exception:
        return dt_str or "TBD"


def impact_color(impact: str) -> str:
    i = (impact or "").lower()
    if i in ("high", "3"):    return "red"
    if i in ("medium", "2"):  return "yellow"
    return "dim"


IMPORTANCE_LABELS = {
    # Kluczowe eventy USA — zawsze czerwone niezaleznie od FinnHub impact
    "nonfarm":       ("KRYTYCZNY", "red",    "bold"),
    "nfp":           ("KRYTYCZNY", "red",    "bold"),
    "fomc":          ("KRYTYCZNY", "red",    "bold"),
    "fed":           ("WYSOKI",    "red",    ""),
    "powell":        ("WYSOKI",    "red",    ""),
    "cpi":           ("KRYTYCZNY", "red",    "bold"),
    "pce":           ("KRYTYCZNY", "red",    "bold"),
    "gdp":           ("WYSOKI",    "red",    ""),
    "jobless":       ("WYSOKI",    "red",    ""),
    "unemployment":  ("WYSOKI",    "red",    ""),
    "pmi":           ("SREDNI",    "yellow", ""),
    "retail sales":  ("SREDNI",    "yellow", ""),
    "ppi":           ("SREDNI",    "yellow", ""),
    "building":      ("NISKI",     "green",  "dim"),
    "housing":       ("NISKI",     "green",  "dim"),
}

# Jak dany event wplywa na nasze rynki
EVENT_IMPACT_MAP = {
    "nonfarm":      "BTC reaguje mocno — duzo miejsc pracy = Fed nie tnie = presja na crypto",
    "cpi":          "Kluczowy dla BTC i Zlota — inflacja powyzej oczekiwan = Fed ostrozny = spadki",
    "fomc":         "Najwazniejszy event w miesiacu — decyzja o kosztach kredytu w USA",
    "pce":          "Ulubiony wskaznik inflacji Fed — podobny efekt jak CPI",
    "gdp":          "PKB = jak szybko rosnie gospodarka USA",
    "jobless":      "Bezrobocie: wiecej wnioskow = slaba gospodarka = Fed moze ciac = wzrostowe dla BTC",
    "pmi":          "Termometr gospodarki: >50 rosnie, <50 kurczy sie",
    "retail sales": "Wydatki konsumentow: silne = gospodarka zdrowa = Fed nie tnie",
    "ppi":          "Inflacja u producentow — poprzedza inflacje konsumencka (CPI)",
}


def get_importance(event: dict) -> tuple[str, str, str]:
    """Returns (label, color, style)"""
    name = (event.get("event") or "").lower()
    imp  = (event.get("impact") or "").lower()

    # Najpierw sprawdz po slowie kluczowym
    for kw, (label, color, style) in IMPORTANCE_LABELS.items():
        if kw in name:
            return label, color, style

    # Potem po impact z FinnHub
    if imp in ("high", "3"):    return "WYSOKI",  "red",    ""
    if imp in ("medium", "2"):  return "SREDNI",  "yellow", ""
    return "NISKI", "green", "dim"


def get_event_tip(event: dict) -> str:
    name = (event.get("event") or "").lower()
    for kw, tip in EVENT_IMPACT_MAP.items():
        if kw in name:
            return tip
    return ""


def display_calendar(events: list[dict], days: int = 1) -> None:
    if not events:
        console.print("[dim]No economic events found for this period.[/dim]")
        return

    # Filtruj tylko US i wazne inne kraje, pomij egzotyczne
    important_countries = {"US", "GB", "EU", "DE", "FR", "JP", "CN", "CA", "AU"}
    filtered = [e for e in events if e.get("country", "") in important_countries
                or is_high_impact(e)]

    console.print(f"\n[bold]Kalendarz ekonomiczny — {days} dzien(dni)[/bold]")
    console.print("[dim]Skala: [red]KRYTYCZNY[/red] | [yellow]SREDNI[/yellow] | [green]NISKI[/green][/dim]\n")

    for e in sorted(filtered, key=lambda x: x.get("time", "")):
        label, color, style = get_importance(e)
        t    = format_time(e.get("time", ""))
        name = e.get("event", "")
        country = e.get("country", "")
        est  = e.get("estimate")
        prev = e.get("prev")
        tip  = get_event_tip(e)

        # Formatuj linie
        tag = f"[{color}][{label}][/{color}]"
        vals = ""
        if est:  vals += f"  oczekiwane: {est}"
        if prev: vals += f"  poprzednio: {prev}"

        if style == "bold":
            console.print(f"  [{color}]>> {t}[/{color}]  [{color}]{tag}[/{color}]  [{color}][bold]{country} — {name}[/bold][/{color}]{vals}")
        elif style == "dim":
            console.print(f"  [dim]   {t}  {tag}  {country} — {name}{vals}[/dim]")
        else:
            console.print(f"     {t}  {tag}  {country} — {name}{vals}")

        if tip and label in ("KRYTYCZNY", "WYSOKI"):
            console.print(f"            [dim italic]=> {tip}[/dim italic]")

    # EXPERT VIEW sekcja
    _expert_view_calendar(filtered)


def _expert_view_calendar(events: list[dict]) -> None:
    """Syntetyczny EXPERT VIEW na podstawie kalendarza dnia."""
    from datetime import datetime, timezone

    now_ts = datetime.now(timezone.utc).timestamp()
    upcoming = []
    passed   = []

    for e in events:
        label, color, _ = get_importance(e)
        if label not in ("KRYTYCZNY", "WYSOKI"):
            continue
        try:
            dt = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
            ts = dt.timestamp()
        except Exception:
            continue
        entry = {
            "time":    format_time(e.get("time", "")),
            "name":    e.get("event", ""),
            "country": e.get("country", ""),
            "label":   label,
            "color":   color,
            "est":     e.get("estimate"),
            "prev":    e.get("prev"),
            "tip":     get_event_tip(e),
        }
        if ts > now_ts:
            upcoming.append(entry)
        else:
            passed.append(entry)

    lines = []

    if upcoming:
        lines.append("[bold]Nadchodzace kluczowe dane:[/bold]")
        for e in upcoming[:5]:
            s = f"  [{e['color']}]{e['time']}[/{e['color']}]  [{e['color']}]{e['name']} ({e['country']})[/{e['color']}]"
            if e["est"]:  s += f"  oczekiwane: {e['est']}"
            if e["prev"]: s += f"  poprzednio: {e['prev']}"
            lines.append(s)
            if e["tip"]:
                lines.append(f"    [dim]=> {e['tip']}[/dim]")

    # Ocen ogolny risk dnia
    critical_count = sum(1 for e in upcoming if e["label"] == "KRYTYCZNY")
    high_count     = sum(1 for e in upcoming if e["label"] == "WYSOKI")

    if critical_count >= 2:
        risk_level = "[red]WYSOKI[/red]"
        risk_note  = "Kilka krytycznych danych — duze wahania mozliwe. Ogranicz wielkosc pozycji."
    elif critical_count == 1 or high_count >= 2:
        risk_level = "[yellow]SREDNI[/yellow]"
        risk_note  = "Jeden kluczowy event — uwazaj w okolicach godziny publikacji."
    elif high_count >= 1:
        risk_level = "[yellow]NISKI-SREDNI[/yellow]"
        risk_note  = "Spokojniejszy dzien, ale jest kilka danych sredniego wplywu."
    else:
        risk_level = "[green]NISKI[/green]"
        risk_note  = "Spokojny dzien makro — dobre warunki do tradowania technicznego."

    lines.append("")
    lines.append(f"[bold]Ryzyko makro na dzis: {risk_level}[/bold]")
    lines.append(f"[dim]{risk_note}[/dim]")

    if not upcoming:
        lines.append("[dim]Wszystkie kluczowe dane na dzis juz wyszly.[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]EXPERT VIEW — Kalendarz[/bold]",
        expand=False
    ))


def display_upcoming(events: list[dict]) -> None:
    """Compact list of upcoming (not yet released) events for today — for daily brief header."""
    now_ts = datetime.now(timezone.utc).timestamp()
    important_countries = {"US", "GB", "EU", "DE", "FR", "JP", "CN", "CA", "AU"}

    upcoming = []
    for e in events:
        # Skip already-released (actual value present)
        if e.get("actual") is not None and str(e.get("actual", "")).strip() not in ("", "null"):
            continue
        country = e.get("country", "")
        if country not in important_countries and not is_high_impact(e):
            continue
        try:
            dt = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
            if dt.timestamp() <= now_ts:
                continue
        except Exception:
            pass
        label, color, _ = get_importance(e)
        if label == "NISKI":
            continue  # skip low-importance in the brief
        upcoming.append((e, label, color))

    if not upcoming:
        print("Econ upcoming today: brak waznych danych")
        return

    print("Econ nadchodzace dzis:")
    for e, label, color in upcoming[:6]:
        t    = format_time(e.get("time", ""))
        name = e.get("event", "")
        country = e.get("country", "")
        est  = e.get("estimate", "")
        est_str = f" (est: {est})" if est else ""
        print(f"  • {t}  [{label}]  {country} — {name}{est_str}")


def display_brief(events: list[dict]) -> None:
    """One-liner with already-released high-impact events — for daily brief header."""
    high = [e for e in events if is_high_impact(e)]
    if not high:
        print("Econ calendar: no high-impact events today")
        return
    items = []
    for e in high[:4]:
        t    = format_time(e.get("time", ""))
        name = e.get("event", "")
        est  = e.get("estimate")
        parts = [f"{t} {name}"]
        if est: parts.append(f"est:{est}")
        items.append(" ".join(parts))
    print("Econ today: " + " | ".join(items))


def analyze_impact(event_name: str, actual: float, expected: float) -> None:
    surprise    = actual - expected
    surprise_pct = (surprise / abs(expected) * 100) if expected else 0
    direction   = "HAWKISH" if surprise > 0 else "DOVISH"
    strength    = "MOCNA" if abs(surprise_pct) > 5 else "UMIARKOWANA" if abs(surprise_pct) > 2 else "SLABA"
    color       = "red" if surprise > 0 else "green"

    console.print(Panel(
        f"[bold]{event_name.upper()}[/bold]\n"
        f"Actual: [bold]{actual}[/bold]  |  Expected: {expected}  |  "
        f"Surprise: [{color}]{surprise:+.2f} ({surprise_pct:+.1f}%)[/{color}]\n"
        f"[{color}]{direction} SURPRISE — {strength}[/{color}]",
        title="Impact Analysis"
    ))

    # Find matching impact template
    key = next((k for k in MARKET_IMPACT if k in event_name.lower()), None)
    impacts = MARKET_IMPACT.get(key, {}) if key else {}

    console.print("\n[bold]Oczekiwany ruch w ciagu 1-4h:[/bold]")
    if surprise > 0:
        moves = {
            "BTC":  ("-2% do -4%",  "risk-off, Fed moze nie ciac"),
            "GOLD": ("+0.5% do +1.5%", "inflation hedge mimo USD strength"),
            "OIL":  ("neutralny",    "demand story wazniejsza"),
            "USD":  ("+0.2% do +0.5%", "DXY w gore"),
            "SPX":  ("-0.5% do -1.5%", "wyzsze stopy = spólki tech cierpia"),
        }
    else:
        moves = {
            "BTC":  ("+1.5% do +3%",  "risk-on, Fed moze ciac"),
            "GOLD": ("-0.3% do -0.8%", "USD slabnie"),
            "OIL":  ("neutralny",      ""),
            "USD":  ("-0.2% do -0.4%", "DXY spada"),
            "SPX":  ("+0.5% do +1%",   "nizsze stopy = spólki rosna"),
        }

    for asset, (move, reason) in moves.items():
        imp_level = impacts.get(asset, "low")
        ic = "red" if imp_level == "high" else "yellow" if imp_level == "medium" else "dim"
        console.print(f"  [{ic}]{asset:6}[/{ic}]  {move:18}  [dim]{reason}[/dim]")

    console.print(
        "\n[bold]Trade idea:[/bold] Czekaj 15-30 min na stabilizacje."
    )
    if surprise > 0:
        console.print("Hawkish surprise -> szukaj odbiecia BTC na key support po inicjalnej wyprzedazy.")
    else:
        console.print("Dovish surprise -> momentum long BTC/Gold. Uwazaj na fakeout jesli rynek juz zdyskontowal.")


def main() -> None:
    if not API_KEY:
        console.print("[red]FINNHUB_API_KEY not set in .env[/red]")
        sys.exit(1)

    p = argparse.ArgumentParser(description="Economic calendar + impact analyzer")
    sub = p.add_subparsers(dest="cmd")

    # impact subcommand
    imp_p = sub.add_parser("impact", help="Analyze data surprise")
    imp_p.add_argument("event",    help="Event name e.g. CPI")
    imp_p.add_argument("actual",   type=float)
    imp_p.add_argument("expected", type=float)

    p.add_argument("--days",     type=int, default=1)
    p.add_argument("--brief",    action="store_true", help="One-liner for daily alpha header")
    p.add_argument("--upcoming", action="store_true", help="Show only upcoming (not yet released) events today")

    args = p.parse_args()

    if args.cmd == "impact":
        analyze_impact(args.event, args.actual, args.expected)
        return

    today = datetime.now(timezone.utc)
    date_from = today.strftime("%Y-%m-%d")
    date_to   = (today + timedelta(days=max(args.days - 1, 0))).strftime("%Y-%m-%d")

    try:
        events = fetch_calendar(date_from, date_to)
    except Exception as e:
        console.print(f"[red]FinnHub error: {e}[/red]")
        sys.exit(1)

    if args.upcoming:
        display_upcoming(events)
    elif args.brief:
        display_brief(events)
    else:
        display_calendar(events, days=args.days)


if __name__ == "__main__":
    main()
