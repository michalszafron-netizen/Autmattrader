"""Crypto Fear & Greed Index — alternative.me (free, no API key).

Usage:
    python scripts/fear_greed.py              # dzisiaj
    python scripts/fear_greed.py --days 7     # ostatnie 7 dni
    python scripts/fear_greed.py --days 30    # historia 30 dni z trendem
    python scripts/fear_greed.py --brief      # jedna linia do daily alpha
"""

from __future__ import annotations

import argparse
import ssl
from datetime import datetime
from pathlib import Path

import httpx
import truststore
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console  = Console()
_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
API_URL  = "https://api.alternative.me/fng/"

ZONES = [
    (0,  24,  "red",          "Extreme Fear",  "Rynek jest w panice. Historycznie dobry moment do kupna dla cierpliwych."),
    (25, 44,  "orange3",      "Fear",          "Wiekszosc inwestorow sie boi. Rynek moze spasc dalej lub sie odwrocic."),
    (45, 54,  "yellow",       "Neutral",       "Brak wyraznego sentymentu. Rynek czeka na kierunek."),
    (55, 74,  "green",        "Greed",         "Inwestorzy sa zachlanni. Wzrosty moga trwac ale ostroznosc wskazana."),
    (75, 100, "bold green",   "Extreme Greed", "Euforia. Historycznie sygnał ostrzegawczy — blisko szczytu."),
]


def get_zone(value: int) -> tuple:
    for lo, hi, color, label, desc in ZONES:
        if lo <= value <= hi:
            return color, label, desc
    return "white", "Unknown", ""


def fetch(limit: int = 1) -> list[dict]:
    r = httpx.get(f"{API_URL}?limit={limit}&format=json", verify=_SSL_CTX, timeout=10)
    r.raise_for_status()
    return r.json()["data"]


def bar(value: int, width: int = 20) -> str:
    filled = round(value / 100 * width)
    return "#" * filled + "." * (width - filled)


def display_single(d: dict) -> None:
    value  = int(d["value"])
    color, label, desc = get_zone(value)
    ts     = datetime.fromtimestamp(int(d["timestamp"])).strftime("%Y-%m-%d")
    b      = bar(value)
    console.print(Panel(
        f"[{color}]{b} {value}/100 -- {label}[/{color}]\n\n{desc}",
        title=f"[bold]Crypto Fear & Greed — {ts}[/bold]",
        expand=False
    ))


def display_history(data: list[dict]) -> None:
    values = [int(d["value"]) for d in data]
    avg    = sum(values) / len(values)
    mn, mx = min(values), max(values)

    # trend: porownaj pierwsza polowe z druga
    mid    = len(values) // 2
    first_half_avg  = sum(values[mid:]) / max(len(values[mid:]), 1)   # starsze dni
    second_half_avg = sum(values[:mid]) / max(len(values[:mid]), 1)   # nowsze dni
    trend_delta = second_half_avg - first_half_avg

    if trend_delta > 5:
        trend_str = "[green]rosnacy (sentyment sie poprawia)[/green]"
        trend_tip = "Rynek wychodzi ze strachu — mozliwa kontynuacja wzrostow."
    elif trend_delta < -5:
        trend_str = "[red]spadajacy (strach rosnie)[/red]"
        trend_tip = "Sentyment sie pogarsza — uwazaj na dalsze spadki."
    else:
        trend_str = "[yellow]boczny (bez wyraznego kierunku)[/yellow]"
        trend_tip = "Rynek niezdecydowany — czekaj na wyrazny sygnal."

    _, avg_label, _ = get_zone(int(avg))
    _, min_label, _ = get_zone(mn)
    _, max_label, _ = get_zone(mx)

    # tabela dni
    table = Table(title=f"Fear & Greed — ostatnie {len(data)} dni", show_lines=False)
    table.add_column("Data",       style="dim", width=12)
    table.add_column("Pasek",      width=22)
    table.add_column("Wartosc",    justify="center", width=8)
    table.add_column("Strefa",     width=16)

    for d in data:
        v = int(d["value"])
        ts = datetime.fromtimestamp(int(d["timestamp"])).strftime("%Y-%m-%d")
        color, label, _ = get_zone(v)
        table.add_row(
            ts,
            f"[{color}]{bar(v, 20)}[/{color}]",
            f"[{color}]{v}/100[/{color}]",
            f"[{color}]{label}[/{color}]",
        )

    console.print(table)

    # podsumowanie trendu
    console.print(Panel(
        f"Srednia {len(data)}-dniowa:  [bold]{avg:.0f}/100[/bold] -- {avg_label}\n"
        f"Minimum:              [red]{mn}/100[/red] -- {min_label}\n"
        f"Maximum:              [green]{mx}/100[/green] -- {max_label}\n"
        f"Trend:                {trend_str}\n\n"
        f"[dim]{trend_tip}[/dim]",
        title="[bold]Podsumowanie trendu[/bold]",
        expand=False
    ))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days",  type=int, default=1)
    p.add_argument("--brief", action="store_true")
    args = p.parse_args()

    data = fetch(limit=max(args.days, 1))

    if args.brief:
        # Fetch 5 days for trend line
        data5 = fetch(limit=5)
        today = data5[0]
        # Chronological order: oldest → newest
        vals = [int(d["value"]) for d in reversed(data5)]
        trend_str = "→".join(str(v) for v in vals)
        delta = vals[-1] - vals[0]   # today minus 4 days ago
        if delta > 5:
            trend_sym = "↑ (sentyment poprawia się)"
        elif delta < -5:
            trend_sym = "↓ (strach rośnie)"
        else:
            trend_sym = "→ (stabilny)"
        _, today_label, _ = get_zone(int(today["value"]))
        print(f"Fear & Greed: {today['value']}/100 — {today_label} | Trend 5d: {trend_str} {trend_sym}")
    elif args.days == 1:
        display_single(data[0])
    else:
        display_history(data)

    # Auto-save to DB (silently)
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from db import DB as _DB
        from datetime import timezone as _tz
        _db = _DB()
        for d in data:
            _db._sqlite.execute(
                """INSERT OR IGNORE INTO fear_greed_history
                   (ts, date, value, classification)
                   VALUES (?,?,?,?)""",
                (
                    datetime.now(_tz.utc).isoformat(timespec="seconds"),
                    d.get("timestamp", d.get("date", "")),
                    int(d.get("value", 0)),
                    d.get("value_classification", d.get("classification", "")),
                ),
            )
    except Exception:
        pass


if __name__ == "__main__":
    main()
