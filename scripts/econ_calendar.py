"""Economic calendar — FinnHub API + impact analyzer.

Usage:
    python scripts/econ_calendar.py                    # today's events
    python scripts/econ_calendar.py --days 3           # next 3 days
    python scripts/econ_calendar.py --brief            # one-liner for daily alpha
    python scripts/econ_calendar.py --upcoming         # only what's left to release today
    python scripts/econ_calendar.py --full             # released + upcoming today, with per-asset impact
    python scripts/econ_calendar.py impact CPI 3.4 3.1 # analyze a specific surprise
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY  = os.getenv("FINNHUB_API_KEY", "")
BASE_URL = "https://finnhub.io/api/v1"

FRED_API_KEY  = os.getenv("FRED_API_KEY", "")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

console  = Console()
_SSL     = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

# High-impact events that move crypto/commodities/FX
HIGH_IMPACT_KEYWORDS = [
    "nonfarm", "nfp", "payroll", "cpi", "pce", "inflation", "fomc", "fed",
    "interest rate", "gdp", "retail sales", "unemployment", "jobless",
    "ppi", "ism", "pmi", "core", "jackson hole", "powell",
]

# Wydarzenia czysto techniczne (aukcje obligacji/bonow, wlasne sondaze
# myfxbook, ankiety bez realnego wyniku) — brak sygnalu makro dla
# krypto/zlota/akcji, pomijane w raporcie --full, by nie tworzyc szumu.
NOISE_KEYWORDS = ["auction", "myfxbook", "survey of monetary analysts"]

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


# Free fallback (no API key) — used when FinnHub's economic calendar
# endpoint is unavailable (403 on free plan).
FF_CALENDAR_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
FF_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

FF_COUNTRY_MAP = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP",
    "CNY": "CN", "CAD": "CA", "AUD": "AU", "CHF": "CH", "NZD": "NZ",
}

# Cloudflare on the FF feed rate-limits hard (429, retry-after ~3-4 min) —
# cache responses on disk so dashboard polling doesn't get throttled.
_CACHE_DIR = Path(__file__).parent.parent / ".cache"
_CACHE_TTL = 1800  # 30 min


def _ff_fetch(url: str, c: httpx.Client) -> list[dict]:
    cache_file = _CACHE_DIR / (url.rsplit("/", 1)[-1])
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < _CACHE_TTL:
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        r = c.get(url, headers=FF_HEADERS)
        r.raise_for_status()
        data = r.json()
        _CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception:
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []


def fetch_calendar_fallback(date_from: str, date_to: str) -> list[dict]:
    d_from = datetime.fromisoformat(date_from).date()
    d_to = datetime.fromisoformat(date_to).date()

    events = []
    seen = set()
    with _ssl_client() as c:
        for url in FF_CALENDAR_URLS:
            raw = _ff_fetch(url, c)
            for e in raw:
                try:
                    dt_utc = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
                except Exception:
                    continue
                if not (d_from <= dt_utc.date() <= d_to):
                    continue
                key = (e.get("title", ""), e.get("country", ""), dt_utc.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                events.append({
                    "event":    e.get("title", ""),
                    "country":  FF_COUNTRY_MAP.get(e.get("country", ""), e.get("country", "")),
                    "time":     dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "impact":   (e.get("impact") or "").lower(),
                    "estimate": e.get("forecast") or None,
                    "prev":     e.get("previous") or None,
                    "actual":   None,
                })
    return events


# ── Pobieranie kalendarza — myfxbook.com (PRIMARY od 2026-06) ───────────────
# Strona renderuje cala tabele po stronie serwera (bez AJAX/JS) i — w
# odroznieniu od darmowego feedu Forex Factory powyzej — podaje realne
# "actual" dla wydarzen, ktore juz wyszly. To usuwa potrzebe zgadywania
# WYNIK-u z FRED (ktore czasem trafialo na zla serie i fabrykowalo np.
# "+1599%" dla niemieckiego/francuskiego Final CPI).
MYFXBOOK_URL = "https://www.myfxbook.com/forex-economic-calendar"
MYFXBOOK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}
_MYFXBOOK_CACHE = _CACHE_DIR / "myfxbook_calendar.html"
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _myfxbook_clean_value(s: str | None) -> str | None:
    """Usuwa symbole walut (£/$/€/¥), zeby _parse_numeric() odczytal liczbe."""
    if not s:
        return None
    s = re.sub(r"[€£¥$]", "", s).strip()
    return s or None


def _myfxbook_fetch_html() -> str | None:
    if _MYFXBOOK_CACHE.exists() and (time.time() - _MYFXBOOK_CACHE.stat().st_mtime) < _CACHE_TTL:
        try:
            return _MYFXBOOK_CACHE.read_text(encoding="utf-8")
        except Exception:
            pass
    try:
        with httpx.Client(verify=_SSL, headers=MYFXBOOK_HEADERS, timeout=30, follow_redirects=True) as c:
            r = c.get(MYFXBOOK_URL)
            r.raise_for_status()
            html = r.text
        _CACHE_DIR.mkdir(exist_ok=True)
        _MYFXBOOK_CACHE.write_text(html, encoding="utf-8")
        return html
    except Exception:
        if _MYFXBOOK_CACHE.exists():
            try:
                return _MYFXBOOK_CACHE.read_text(encoding="utf-8")
            except Exception:
                pass
        return None


def fetch_calendar_myfxbook(date_from: str, date_to: str) -> list[dict]:
    """Kalendarz z myfxbook.com. Jedno zapytanie zwraca ~8 dni danych z
    realnym "actual" dla wydarzen, ktore juz wyszly. Zwraca [], jesli strona
    jest niedostepna albo bs4 nie jest zainstalowane — wtedy fetch_calendar()
    spada na FinnHub/Forex Factory."""
    html = _myfxbook_fetch_html()
    if not html:
        return []

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    try:
        d_from = datetime.fromisoformat(date_from).date()
        d_to = datetime.fromisoformat(date_to).date()
    except ValueError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    events: list[dict] = []
    current_date = None

    for tr in soup.find_all("tr"):
        header_td = tr.find("td", class_=lambda c: c and "background-color-ghostwhite" in c)
        if header_td:
            try:
                current_date = datetime.strptime(header_td.get_text(strip=True), "%A, %b %d, %Y").date()
            except ValueError:
                current_date = None
            continue

        if "economicCalendarRow" not in (tr.get("class") or []):
            continue
        if current_date is None or not (d_from <= current_date <= d_to):
            continue

        link = tr.find("a", class_="calendar-event-link")
        event_name = link.get_text(strip=True) if link else None
        if not event_name:
            continue

        time_div = tr.find("div", class_="calendarDateTd")
        hh, mm = 0, 0
        if time_div:
            time_str = time_div.get_text(strip=True)
            if "," in time_str:
                try:
                    hh, mm = map(int, time_str.rsplit(",", 1)[1].strip().split(":"))
                except ValueError:
                    pass

        currency = None
        for td in tr.find_all("td", class_="calendarToggleCell"):
            txt = td.get_text(strip=True)
            if _CURRENCY_RE.match(txt):
                currency = txt
                break
        country_code = FF_COUNTRY_MAP.get(currency, currency) if currency else ""

        impact_div = tr.find("div", class_=lambda c: c and c.startswith("impact_"))
        impact = impact_div.get_text(strip=True).lower() if impact_div else ""

        prev = None
        prev_td = tr.find("td", attrs={"data-previous": True})
        if prev_td:
            prev_span = prev_td.find("span", class_="previousCell")
            prev = prev_span.get_text(strip=True) if prev_span else None

        estimate = None
        cons_td = tr.find("td", attrs={"data-concensus": True})
        if cons_td:
            estimate = cons_td.get("concensus") or cons_td.get_text(strip=True) or None

        actual = None
        actual_td = tr.find("td", attrs={"data-actual": True})
        if actual_td:
            actual_span = actual_td.find("span", class_="actualCell")
            actual = actual_span.get_text(strip=True) if actual_span else None

        dt_utc = datetime(current_date.year, current_date.month, current_date.day, hh, mm, tzinfo=timezone.utc)

        events.append({
            "event":    event_name,
            "country":  country_code,
            "time":     dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "impact":   impact,
            "estimate": _myfxbook_clean_value(estimate),
            "prev":     _myfxbook_clean_value(prev),
            "actual":   _myfxbook_clean_value(actual),
        })

    return events


def fetch_calendar(date_from: str, date_to: str) -> list[dict]:
    """Glowne pobieranie kalendarza, w kolejnosci:

    1) myfxbook.com (PRIMARY) — ma realne "actual" dla wydarzen, ktore juz
       wyszly (czego darmowy feed Forex Factory nigdy nie podawal).
    2) FinnHub — BACKUP nr 1, dziala jak przed zmiana (wymaga platnego planu).
    3) Forex Factory free feed (fetch_calendar_fallback) — BACKUP nr 2,
       zawsze dostepny bez klucza, ale bez "actual".

    Ustaw ECON_DISABLE_MYFXBOOK=1 w .env, aby pominac (1) i wrocic do
    poprzedniego zachowania (FinnHub -> FF) na wypadek problemow z myfxbook.
    """
    if os.getenv("ECON_DISABLE_MYFXBOOK", "") != "1":
        events = fetch_calendar_myfxbook(date_from, date_to)
        if events:
            return events

    try:
        with _ssl_client() as c:
            r = c.get(f"{BASE_URL}/calendar/economic",
                      params={"from": date_from, "to": date_to, "token": API_KEY})
            r.raise_for_status()
        return r.json().get("economicCalendar", [])
    except Exception:
        return fetch_calendar_fallback(date_from, date_to)


# ── Pobieranie REALNYCH wynikow (actual) — FRED (US + EU) ───────────────────
# Darmowy feed Forex Factory nie podaje "actual" wcale. FRED (oficjalne dane
# Fed, US gov) i serie ECB dostepne na FRED daja prawdziwe, swieze odczyty dla
# najwazniejszych wskaznikow USA i strefy euro.

_SUFFIX_MULT = {"": 1.0, "%": 1.0, "K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}


def _parse_numeric(val) -> float | None:
    """Parsuje wartosci typu '3.4%', '180K', '-0.2%', '2,500K' na liczbe."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none"):
        return None
    m = re.match(r"^(-?[\d.,]+)\s*([KMB%]?)$", s, re.IGNORECASE)
    if not m:
        return None
    num_str, suffix = m.groups()
    try:
        num = float(num_str.replace(",", ""))
    except ValueError:
        return None
    return num * _SUFFIX_MULT.get(suffix.upper(), 1.0)


def _fmt_num(x: float) -> str:
    if x == int(x):
        return str(int(x))
    return f"{x:.2f}"


_FRED_SEEN_FILE = _CACHE_DIR / "fred_seen.json"


def _fred_fetch(series_id: str, units: str = "lin") -> tuple[float, str] | None:
    """Najnowsza obserwacja z FRED (cache 30 min). Zwraca (wartosc, data) albo None."""
    if not FRED_API_KEY:
        return None
    cache_file = _CACHE_DIR / f"fred_{series_id}_{units}.json"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < _CACHE_TTL:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return data["value"], data["date"]
        except Exception:
            pass
    try:
        with _ssl_client() as c:
            r = c.get(FRED_BASE_URL, params={
                "series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json",
                "units": units, "sort_order": "desc", "limit": 1,
            })
            r.raise_for_status()
        obs = r.json().get("observations", [])
        if not obs or obs[0].get("value") in (".", "", None):
            return None
        value = float(obs[0]["value"])
        date  = obs[0]["date"]
        _CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps({"value": value, "date": date}), encoding="utf-8")
        return value, date
    except Exception:
        return None


def fred_lookup(event_name: str, country: str) -> tuple[str, str, float] | None:
    """Mapuje nazwe wydarzenia (z Forex Factory) na serie FRED.

    Zwraca (series_id, units, scale) gdzie 'scale' przelicza wartosc z FRED na
    jednostki uzywane przez Forex Factory (np. NFP: FRED daje zmiane w
    tysiacach, FF pisze '180K' -> scale=1000 sprowadza obie wartosci do tej
    samej skali po przejsciu przez _parse_numeric).
    """
    name = (event_name or "").lower()
    is_yoy = "y/y" in name or "yoy" in name
    is_core = "core" in name

    if country == "US":
        if "cpi" in name:
            series = "CPILFESL" if is_core else "CPIAUCSL"
            return series, ("pc1" if is_yoy else "pch"), 1.0
        if "pce" in name and "price" in name:
            series = "PCEPILFE" if is_core else "PCEPI"
            return series, ("pc1" if is_yoy else "pch"), 1.0
        if "non-farm" in name or "nonfarm" in name or "nfp" in name:
            return "PAYEMS", "chg", 1000.0
        if "unemployment rate" in name:
            return "UNRATE", "lin", 1.0
        if "unemployment claims" in name or "jobless claims" in name or "initial claims" in name:
            return "ICSA", "lin", 1.0
        if "retail sales" in name and "core" not in name:
            return "RSXFS", "pch", 1.0
        if "gdp" in name:
            return "A191RL1Q225SBEA", "lin", 1.0
        if "federal funds rate" in name or "interest rate" in name or "fomc" in name:
            return "DFEDTARU", "lin", 1.0
    elif country == "EU":
        if "main refinancing" in name or "refinancing rate" in name:
            return "ECBMRRFR", "lin", 1.0
        if "deposit facility" in name or "deposit rate" in name:
            return "ECBDFR", "lin", 1.0
        # Eurozone-wide headline HICP y/y (flash estimate). FF tagguje pod EUR
        # rowniez NARODOWE odczyty (np. "German Final CPI m/m",
        # "French Final CPI m/m") — to INNE serie (i inna jednostka: m/m, nie
        # y/y), wiec wykluczamy je tutaj, zamiast podsuwac zle dopasowanie.
        _national = ("german", "france", "french", "italy", "italian", "spain",
                      "spanish", "greece", "portugal", "dutch", "netherlands",
                      "austria", "belgium", "finland", "ireland")
        if ("cpi" in name or "hicp" in name) and is_yoy and not is_core \
                and not any(n in name for n in _national):
            return "CP0000EZ19M086NEST", "pc1", 1.0
    return None


def _load_fred_seen() -> dict:
    if _FRED_SEEN_FILE.exists():
        try:
            return json.loads(_FRED_SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_fred_seen(data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(exist_ok=True)
        _FRED_SEEN_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def resolve_actual(event: dict, fred_seen: dict, fred_updates: dict) -> tuple[float, str | None, bool] | None:
    """Zwraca (wartosc, data_zrodla, czy_nowy) jesli FRED/ECB ma dane dla tego
    wydarzenia, albo None jesli nie ma zadnego mapowania / FRED nie odpowiada.

    'czy_nowy' = True jesli wartosc/data z FRED zmienila sie wzgledem ostatnio
    zapamietanej (czyli to swiezy odczyt od ostatniego sprawdzenia dzisiaj).
    Gdy False — FRED ma dana, ale nie zmienila sie od ostatniego sprawdzenia,
    wiec moze to byc nadal POPRZEDNI odczyt (FRED bywa opozniony)."""
    direct = _parse_numeric(event.get("actual"))
    if direct is not None:
        return direct, None, True

    lookup = fred_lookup(event.get("event", ""), event.get("country", ""))
    if not lookup:
        return None
    series_id, units, scale = lookup

    fetched = _fred_fetch(series_id, units)
    if not fetched:
        return None
    value, date = fetched

    prev = fred_seen.get(series_id)
    is_new = prev is None or prev.get("date") != date or prev.get("value") != value
    fred_updates[series_id] = {"date": date, "value": value}

    return value * scale, date, is_new


# ── Edukacyjna baza wiedzy: wplyw danych makro na obserwowane aktywa ────────
# Dla kazdej kategorii danych okreslamy kierunek reakcji aktywow gdy odczyt
# jest "hawkish" (jastrzebi — sugeruje wyzsze/dluzej utrzymane stopy procentowe)
# vs "dovish" (golebi — sugeruje nizsze/szybciej ciete stopy).
# Format wpisu w "assets": (kierunek_gdy_hawkish, kierunek_gdy_dovish,
#                           wyjasnienie_gdy_hawkish, wyjasnienie_gdy_dovish)
# "horizon" to slownik {"hawkish": ..., "dovish": ...} — tekst musi opisywac
# ten scenariusz, ktory faktycznie zaszedl, nie zawsze ten sam.
IMPACT_TEMPLATES: dict[str, dict] = {
    "inflation": {  # CPI, PCE, PPI — wyzszy odczyt = wyzsza inflacja = hawkish
        "hawkish_desc": "Inflacja wyzsza niz oczekiwano",
        "dovish_desc":  "Inflacja nizsza niz oczekiwano",
        "horizon": {
            "hawkish": (
                "Krotkoterminowo (1-4h): ruch jak w tabeli powyzej — wyzsza "
                "inflacja = presja na BTC/zloto/akcje, wsparcie dla USD. "
                "Dlugoterminowo: to JEDEN odczyt — dopiero gdy inflacja "
                "zaskakuje W GORE kilka miesiecy z rzedu, Fed moze odlozyc "
                "obnizki stop, co potrafi wyznaczyc wielomiesieczny trend na "
                "BTC i zlocie."
            ),
            "dovish": (
                "Krotkoterminowo (1-4h): ruch jak w tabeli powyzej — nizsza "
                "inflacja = wsparcie dla BTC/zlota/akcji, presja na USD. "
                "Dlugoterminowo: to JEDEN odczyt — dopiero gdy inflacja "
                "zaskakuje W DOL kilka miesiecy z rzedu, zmienia sie "
                "oczekiwana sciezka stop Fed, a to potrafi wyznaczyc "
                "wielomiesieczny trend na BTC i zlocie."
            ),
        },
        "assets": {
            "BTC i altcoiny (ETH/SOL/HYPE/LINK)": ("down", "up",
                "Wyzsze stopy procentowe na dluzej = mniej kapitalu plynie w ryzykowne aktywa jak BTC i altcoiny",
                "Nizsza inflacja zwieksza szanse na obnizki stop Fed = wiecej kapitalu moze plynac w ryzykowne aktywa jak BTC i altcoiny"),
            "Zloto i srebro": ("down", "up",
                "Wyzsze realne stopy obnizaja atrakcyjnosc metali, ktore nie generuja odsetek",
                "Nizsze realne stopy zwiekszaja atrakcyjnosc metali, ktore nie generuja odsetek"),
            "Ropa (OIL)": ("down", "up",
                "Mocniejszy dolar (ropa wyceniana w USD) lekko obniza jej cene",
                "Slabszy dolar (ropa wyceniana w USD) lekko podnosi jej cene"),
            "SP500 / akcje": ("down", "up",
                "Drozszy kredyt = nizsze wyceny spolek, zwlaszcza technologicznych",
                "Tanszy kredyt (perspektywa nizszych stop) = wyzsze wyceny spolek, zwlaszcza technologicznych"),
            "USD (dolar)": ("up", "down",
                "Rynek wycenia dluzej utrzymane wysokie stopy = mocniejszy dolar",
                "Rynek wycenia szybsze obnizki stop = slabszy dolar"),
        },
    },
    "growth": {  # GDP, Retail Sales, PMI/ISM, Consumer Sentiment — wyzszy odczyt = silniejsza gospodarka
        "hawkish_desc": "Gospodarka silniejsza niz oczekiwano",
        "dovish_desc":  "Gospodarka slabsza niz oczekiwano",
        "horizon": {
            "hawkish": (
                "Krotkoterminowo (1-4h) reakcja bywa odwrotna do intuicji — "
                "mocne dane = 'Fed nie spieszy sie z cieciem stop' = chwilowa "
                "presja na BTC/zloto. Dlugoterminowo: trwale silna gospodarka "
                "('soft landing') jest pozytywna dla aktywow ryzykownych, bo "
                "oddala widmo recesji."
            ),
            "dovish": (
                "Krotkoterminowo (1-4h) slabe dane = wieksza szansa na "
                "obnizki stop Fed = chwilowe wsparcie dla BTC/zlota. "
                "Dlugoterminowo: jesli slabosc danych jest trwala/systemowa, "
                "to sygnal nadchodzacej recesji — wtedy nawet BTC i akcje "
                "moga zaczac spadac mimo obnizek stop."
            ),
        },
        "assets": {
            "BTC i altcoiny (ETH/SOL/HYPE/LINK)": ("down", "up",
                "Silna gospodarka = Fed nie spieszy sie z obnizkami stop, co krotkoterminowo szkodzi aktywom ryzykownym",
                "Slabsza gospodarka zwieksza szanse na obnizki stop Fed, co krotkoterminowo wspiera aktywa ryzykowne jak BTC"),
            "Zloto i srebro": ("down", "up",
                "Mniejszy popyt na 'bezpieczna przystan', gdy gospodarka radzi sobie dobrze",
                "Slabsze dane zwiekszaja popyt na 'bezpieczna przystan' jak zloto, a tez podnosza szanse na obnizki stop"),
            "Ropa (OIL)": ("up", "down",
                "Silniejsza gospodarka = wiekszy popyt na energie",
                "Slabsza gospodarka = mniejszy oczekiwany popyt na energie"),
            "SP500 / akcje": ("up", "down",
                "Lepsze dane gospodarcze = wyzsze oczekiwane zyski spolek",
                "Slabsze dane gospodarcze = nizsze oczekiwane zyski spolek, mimo nadziei na obnizki stop"),
            "USD (dolar)": ("up", "down",
                "Silniejsza gospodarka USA przyciaga kapital, dolar zyskuje",
                "Slabsze dane z USA zmniejszaja atrakcyjnosc dolara dla kapitalu"),
        },
    },
    "labor_slack": {  # Unemployment Claims/Rate — wyzszy odczyt = SLABSZY rynek pracy = dovish
        "hawkish_desc": "Rynek pracy mocniejszy niz oczekiwano (mniej wnioskow/bezrobocia)",
        "dovish_desc":  "Rynek pracy slabszy niz oczekiwano (wiecej wnioskow/bezrobocia)",
        "horizon": {
            "hawkish": (
                "Krotkoterminowo: mocniejszy rynek pracy niz oczekiwano "
                "zmniejsza szanse na szybkie obnizki stop = chwilowa presja "
                "na BTC/zloto w ciagu 1-4h. Dlugoterminowo: trwale mocny "
                "rynek pracy wspiera scenariusz 'soft landing' i jest "
                "pozytywny dla aktywow ryzykownych w dluzszej perspektywie."
            ),
            "dovish": (
                "Krotkoterminowo: slabsze dane = wieksza szansa na obnizki "
                "stop = wzrosty BTC/zlota w ciagu 1-4h. Dlugoterminowo: "
                "jesli rynek pracy slabnie SYSTEMATYCZNIE przez kilka "
                "miesiecy, to sygnal recesji — wtedy nawet BTC i akcje moga "
                "zaczac spadac mimo obnizek stop."
            ),
        },
        "assets": {
            "BTC i altcoiny (ETH/SOL/HYPE/LINK)": ("down", "up",
                "Mocniejszy rynek pracy niz oczekiwano zmniejsza szanse na szybkie obnizki stop Fed, co krotkoterminowo moze ciazyc aktywom ryzykownym jak BTC",
                "Slabszy rynek pracy zwieksza szanse na obnizki stop, co sprzyja aktywom ryzykownym"),
            "Zloto i srebro": ("down", "up",
                "Mniejsze szanse na szybkie obnizki stop obnizaja atrakcyjnosc zlota i srebra, ktore nie generuja odsetek",
                "Oczekiwania na obnizki stop wspieraja cene zlota i srebra"),
            "Ropa (OIL)": ("up", "down",
                "Mocniejszy rynek pracy niz oczekiwano wspiera oczekiwania popytu na energie",
                "Slabszy rynek pracy budzi obawy o popyt na energie"),
            "SP500 / akcje": ("down", "up",
                "Mocniejszy rynek pracy niz oczekiwano zmniejsza prawdopodobienstwo szybkich obnizek stop, co moze chwilowo ciazyc wycenom akcji",
                "Slabsze dane zwiekszaja nadzieje na obnizki stop, co krotkoterminowo wspiera wyceny akcji — choc przy bardzo slabych danych moga przewazyc obawy o recesje"),
            "USD (dolar)": ("up", "down",
                "Mocniejszy rynek pracy niz oczekiwano zwieksza szanse na utrzymanie wyzszych stop dluzej, co wspiera dolara",
                "Slabsze dane obnizaja szanse na utrzymanie wysokich stop, dolar traci"),
        },
    },
    "policy": {  # FOMC / Fed funds rate / ECB / BOE i inne decyzje stop procentowych
        "hawkish_desc": "Decyzja/komunikat bardziej jastrzebi niz oczekiwano (wyzsze stopy / dluzej restrykcyjna polityka)",
        "dovish_desc":  "Decyzja/komunikat bardziej golebi niz oczekiwano (nizsze stopy / szybsze ciecia)",
        "horizon": {
            "hawkish": (
                "To NAJWAZNIEJSZY typ wydarzenia dla DLUGOTERMINOWEGO "
                "trendu — bardziej jastrzebi ton/decyzja FOMC/ECB wyznacza "
                "kierunek na kolejne tygodnie/miesiace (presja na "
                "BTC/zloto/akcje, wsparcie dla USD), nie tylko na kilka "
                "godzin po publikacji."
            ),
            "dovish": (
                "To NAJWAZNIEJSZY typ wydarzenia dla DLUGOTERMINOWEGO "
                "trendu — bardziej golebi ton/decyzja FOMC/ECB wyznacza "
                "kierunek na kolejne tygodnie/miesiace (wsparcie dla "
                "BTC/zlota/akcji, presja na USD), nie tylko na kilka godzin "
                "po publikacji."
            ),
        },
        "assets": {
            "BTC i altcoiny (ETH/SOL/HYPE/LINK)": ("down", "up",
                "Polityka pieniezna ma najwiekszy wplyw na wycene aktywow ryzykownych jak BTC — bardziej restrykcyjny ton ciazy wycenom",
                "Polityka pieniezna ma najwiekszy wplyw na wycene aktywow ryzykownych jak BTC — bardziej golebi ton wspiera wyceny"),
            "Zloto i srebro": ("down", "up",
                "Zloto bardzo czulo reaguje na oczekiwania co do przyszlych stop procentowych — wyzsze stopy na dluzej ciazyc zlotu",
                "Zloto bardzo czulo reaguje na oczekiwania co do przyszlych stop procentowych — perspektywa nizszych stop wspiera zloto"),
            "Ropa (OIL)": ("down", "up",
                "Restrykcyjna polityka budzi obawy o spowolnienie gospodarcze i mniejszy popyt na energie",
                "Golebia polityka (nizsze stopy/szybsze ciecia) wspiera oczekiwania wzrostu gospodarczego i popytu na energie"),
            "SP500 / akcje": ("down", "up",
                "Drozszy kredyt = nizsze wyceny, zwlaszcza spolek wzrostowych",
                "Tanszy kredyt (perspektywa nizszych stop) = wyzsze wyceny, zwlaszcza spolek wzrostowych"),
            "USD (dolar)": ("up", "down",
                "Wyzsze stopy procentowe przyciagaja kapital do dolara",
                "Nizsze stopy procentowe (lub szybsze ciecia) zmniejszaja atrakcyjnosc dolara dla kapitalu"),
        },
    },
    "trade": {  # Balance of Trade — mniejszy deficyt/wieksza nadwyzka = mocniejsza waluta
        "hawkish_desc": "Saldo handlowe lepsze niz oczekiwano (mniejszy deficyt / wieksza nadwyzka)",
        "dovish_desc":  "Saldo handlowe gorsze niz oczekiwano (wiekszy deficyt / mniejsza nadwyzka)",
        "horizon": {
            "hawkish": (
                "Wplyw zwykle SLABY i POSREDNI — saldo handlowe rzadko samo "
                "w sobie rusza krypto/zloto/akcje w ciagu 1-4h. Liczy sie "
                "bardziej jako potwierdzenie ogolnego trendu danej "
                "gospodarki niz pojedynczy katalizator."
            ),
            "dovish": (
                "Wplyw zwykle SLABY i POSREDNI — saldo handlowe rzadko samo "
                "w sobie rusza krypto/zloto/akcje w ciagu 1-4h. Liczy sie "
                "bardziej jako potwierdzenie ogolnego trendu danej "
                "gospodarki niz pojedynczy katalizator."
            ),
        },
        "assets": {
            "BTC i altcoiny (ETH/SOL/HYPE/LINK)": ("neutral", "neutral",
                "Saldo handlowe ma marginalny, posredni wplyw na aktywa krypto",
                "Saldo handlowe ma marginalny, posredni wplyw na aktywa krypto"),
            "Zloto i srebro": ("neutral", "neutral",
                "Saldo handlowe rzadko wplywa na zloto bezposrednio",
                "Saldo handlowe rzadko wplywa na zloto bezposrednio"),
            "Ropa (OIL)": ("neutral", "neutral",
                "Brak bezposredniego zwiazku z cena ropy",
                "Brak bezposredniego zwiazku z cena ropy"),
            "SP500 / akcje": ("neutral", "neutral",
                "Marginalny wplyw — liczy sie bardziej trend niz pojedynczy odczyt",
                "Marginalny wplyw — liczy sie bardziej trend niz pojedynczy odczyt"),
            "USD (dolar)": ("up", "down",
                "Mniejszy deficyt / wieksza nadwyzka = mniej sprzedazy waluty na "
                "import = lekkie wsparcie dla niej",
                "Wiekszy deficyt / mniejsza nadwyzka = wiecej sprzedazy waluty na "
                "import = lekka presja na nia"),
        },
    },
}

# keyword (lowercase, sprawdzane w nazwie wydarzenia) ->
#   (kategoria, czy_wyzszy_odczyt_jest_hawkish, opis, wyjasnienie_dla_laika)
# Kolejnosc ma znaczenie — bardziej szczegolowe frazy sprawdzane sa pierwsze.
EVENT_CATEGORY: dict[str, tuple[str, bool, str, str]] = {
    "core pce": ("inflation", True, "Inflacja bazowa PCE (preferowany wskaznik Fed)",
        "Inflacja bazowa PCE pokazuje jak szybko rosna ceny (bez zywnosci i energii) — "
        "to ULUBIONY wskaznik inflacji Fed przy decyzjach o stopach procentowych."),
    "pce": ("inflation", True, "Inflacja PCE",
        "PCE pokazuje jak szybko rosna ceny w calej gospodarce (z zywnoscia i energia)."),
    "core cpi": ("inflation", True, "Inflacja bazowa CPI",
        "Inflacja bazowa CPI = wzrost cen towarow i uslug bez zywnosci/energii (te sa "
        "zmienne). Najczesciej cytowany wskaznik inflacji."),
    "cpi": ("inflation", True, "Inflacja konsumencka CPI",
        "CPI = inflacja konsumencka. Pokazuje o ile % wzrosly ceny dla przecietnego "
        "konsumenta. Wysoka inflacja = Fed trzyma wysokie stopy procentowe dluzej."),
    "core ppi": ("inflation", True, "Inflacja produkcyjna — bazowa (PPI)",
        "Inflacja producencka bazowa = ceny, jakie placa firmy za surowce/polprodukty "
        "(bez zywnosci/energii). Czesto zapowiada przyszla inflacje konsumencka (CPI)."),
    "ppi": ("inflation", True, "Inflacja produkcyjna PPI",
        "PPI = inflacja po stronie producentow (hurtowa). Wzrost dzis = mozliwy wzrost "
        "cen w sklepach za kilka miesiecy."),
    "inflation expectations": ("inflation", True, "Oczekiwania inflacyjne (sondaz)",
        "Sondaz: ile inflacji ludzie SPODZIEWAJA SIE w przyszlosci. Wazne, bo Fed "
        "pilnuje, by te oczekiwania nie wymknely sie spod kontroli."),
    # Nazewnictwo myfxbook (od 2026-06) — odpowiedniki "core cpi"/"cpi" powyzej.
    # Kolejnosc: "core"/"harmonised" warianty PRZED ogolnym "inflation rate".
    "core inflation rate": ("inflation", True, "Inflacja bazowa (CPI)",
        "Inflacja bazowa = wzrost cen towarow i uslug bez zywnosci/energii (te sa "
        "zmienne). Najczesciej cytowany wskaznik inflacji — odpowiednik 'core CPI'."),
    "harmonised inflation rate": ("inflation", True, "Inflacja HICP (zharmonizowana)",
        "HICP = zharmonizowany wskaznik inflacji konsumenckiej (metodologia UE), "
        "porownywalny miedzy krajami strefy euro. Odpowiednik CPI."),
    "inflation rate": ("inflation", True, "Inflacja konsumencka (CPI)",
        "Odpowiednik CPI — pokazuje o ile % wzrosly ceny dla przecietnego konsumenta. "
        "Wysoka inflacja = bank centralny trzyma wysokie stopy procentowe dluzej."),
    "nonfarm": ("growth", True, "Zatrudnienie poza rolnictwem (NFP)",
        "NFP = ile NOWYCH miejsc pracy powstalo w gospodarce USA (poza rolnictwem) w "
        "zeszlym miesiacu. Jeden z najwazniejszych raportow miesiaca."),
    "non farm": ("growth", True, "Zatrudnienie poza rolnictwem (NFP)",
        "NFP = ile NOWYCH miejsc pracy powstalo w gospodarce USA (poza rolnictwem) w "
        "zeszlym miesiacu. Jeden z najwazniejszych raportow miesiaca."),
    "nfp": ("growth", True, "Zatrudnienie poza rolnictwem (NFP)",
        "NFP = ile NOWYCH miejsc pracy powstalo w gospodarce USA (poza rolnictwem) w "
        "zeszlym miesiacu. Jeden z najwazniejszych raportow miesiaca."),
    "gdp": ("growth", True, "Produkt Krajowy Brutto (PKB)",
        "GDP/PKB = tempo wzrostu calej gospodarki. Wyzsze = gospodarka rosnie szybciej "
        "niz sadzono."),
    "retail sales": ("growth", True, "Sprzedaz detaliczna",
        "Sprzedaz detaliczna = ile ludzie wydaja w sklepach. Termometr sily konsumenta "
        "(konsumpcja to wiekszosc gospodarki USA)."),
    "pmi": ("growth", True, "Indeks PMI",
        "PMI = ankieta wsrod menedzerow firm. Powyzej 50 = sektor sie rozwija, ponizej "
        "50 = sie kurczy."),
    "ism": ("growth", True, "Indeks ISM",
        "ISM = jak PMI — ankieta nastrojow w przemysle/uslugach USA. >50 = ekspansja, "
        "<50 = recesja sektora."),
    "consumer sentiment": ("growth", True, "Nastroje konsumentow",
        "Sondaz nastrojow konsumentow — jak optymistycznie ludzie patrza na gospodarke "
        "i swoje finanse."),
    "consumer confidence": ("growth", True, "Zaufanie konsumentow",
        "Sondaz zaufania konsumentow — jak optymistycznie ludzie patrza na gospodarke i "
        "swoje finanse."),
    "unemployment claims": ("labor_slack", False, "Wnioski o zasilek dla bezrobotnych",
        "Ile osob w zeszlym tygodniu po raz pierwszy zlozylo wniosek o zasilek dla "
        "bezrobotnych. Mniej wnioskow = mocny rynek pracy."),
    "jobless claims": ("labor_slack", False, "Wnioski o zasilek dla bezrobotnych",
        "Ile osob w zeszlym tygodniu po raz pierwszy zlozylo wniosek o zasilek dla "
        "bezrobotnych. Mniej wnioskow = mocny rynek pracy."),
    "unemployment rate": ("labor_slack", False, "Stopa bezrobocia",
        "Stopa bezrobocia = % osob aktywnych zawodowo bez pracy. Niska = mocny rynek "
        "pracy = Fed moze trzymac wysokie stopy dluzej."),
    "fomc": ("policy", True, "Decyzja FOMC (Fed)",
        "FOMC = posiedzenie Fed, na ktorym decyduja o poziomie stop procentowych w "
        "USA. Najwazniejszy event miesiaca dla wszystkich rynkow."),
    "federal funds rate": ("policy", True, "Stopa procentowa Fed",
        "Stopa procentowa Fed = koszt pieniadza w USA. Wyzsze stopy = drozej pozyczac "
        "= mniej kapitalu w ryzykownych aktywach (BTC, akcje)."),
    "interest rate": ("policy", True, "Decyzja o stopach procentowych",
        "Decyzja banku centralnego o stopach procentowych — kluczowy czynnik dla "
        "wszystkich rynkow."),
    "refinancing rate": ("policy", True, "Stopa referencyjna (np. ECB)",
        "Glowna stopa procentowa ECB (strefa euro) — europejski odpowiednik stopy "
        "Fed."),
    "monetary policy statement": ("policy", True, "Komunikat polityki pienieznej",
        "Komunikat banku centralnego — ton (jastrzebi/golebi) czesto wazniejszy niz "
        "sama decyzja o stopach."),
    "rate statement": ("policy", True, "Komunikat ws. stop procentowych",
        "Komunikat banku centralnego — ton (jastrzebi/golebi) czesto wazniejszy niz "
        "sama decyzja o stopach."),
    "wholesale prices": ("inflation", True, "Inflacja cen hurtowych",
        "Ceny hurtowe (poziom sprzedazy wielkopowierzchniowej) — podobnie jak PPI, "
        "czesto zapowiadaja przyszla inflacje konsumencka (CPI)."),
    "industrial production": ("growth", True, "Produkcja przemyslowa",
        "Ile wyprodukowaly fabryki/zaklady w danym miesiacu. Wyzszy odczyt = "
        "gospodarka pracuje na wyzszych obrotach."),
    "manufacturing production": ("growth", True, "Produkcja w przetwórstwie przemyslowym",
        "Podzbior produkcji przemyslowej — tylko przetwórstwo (bez energetyki/"
        "wydobycia). Wyzszy odczyt = mocniejszy sektor produkcyjny."),
    "capacity utilization": ("growth", True, "Wykorzystanie mocy produkcyjnych",
        "Jaki procent mocy produkcyjnych fabryk jest faktycznie wykorzystywany. "
        "Wyzej = gospodarka blizej granicy mozliwosci, moze rodzic presje "
        "inflacyjna."),
    "construction output": ("growth", True, "Produkcja budowlana",
        "Wartosc prac budowlanych w gospodarce. Wyzszy odczyt = sektor "
        "budowlany rosnie szybciej niz sadzono."),
    "tertiary industry index": ("growth", True, "Indeks sektora uslug (Japonia)",
        "Japonski wskaznik aktywnosci w sektorze uslug (handel, transport, "
        "finanse). Wyzej = sektor uslugowy rosnie szybciej."),
    "empire state manufacturing": ("growth", True, "Indeks NY Fed (Empire State)",
        "Ankieta wsrod firm produkcyjnych w stanie Nowy Jork — regionalny "
        "wskaznik wyprzedzajacy dla calego sektora przemyslowego USA. Powyzej "
        "0 = ekspansja, ponizej 0 = kontrakcja."),
    "philadelphia fed manufacturing": ("growth", True, "Indeks Philly Fed",
        "Ankieta wsrod firm produkcyjnych w regionie Filadelfii — kolejny "
        "regionalny wskaznik wyprzedzajacy dla przemyslu USA. Powyzej 0 = "
        "ekspansja, ponizej 0 = kontrakcja."),
    "philly fed": ("growth", True, "Indeks Philly Fed",
        "Ankieta wsrod firm produkcyjnych w regionie Filadelfii — kolejny "
        "regionalny wskaznik wyprzedzajacy dla przemyslu USA. Powyzej 0 = "
        "ekspansja, ponizej 0 = kontrakcja."),
    "balance of trade": ("trade", True, "Saldo handlowe (Balance of Trade)",
        "Roznica miedzy eksportem i importem. Mniejszy deficyt / wieksza "
        "nadwyzka = lekkie wsparcie dla waluty danego kraju."),
    "trade balance": ("trade", True, "Saldo handlowe (Trade Balance)",
        "Roznica miedzy eksportem i importem. Mniejszy deficyt / wieksza "
        "nadwyzka = lekkie wsparcie dla waluty danego kraju."),
}

# kierunek -> (kolor Rich, etykieta)
ARROW_LABEL = {
    "up":      ("green", "W GORE  (+)"),
    "down":    ("red",   "W DOL   (-)"),
    "neutral": ("dim",   "NEUTRALNIE (=)"),
}


def get_event_category(name: str) -> tuple[str, bool, str, str] | None:
    name = (name or "").lower()
    for kw, val in EVENT_CATEGORY.items():
        if kw in name:
            return val
    return None


def format_event_impact(
    event: dict,
    actual_value: float | None = None,
    actual_date: str | None = None,
    is_new: bool = True,
) -> list[str]:
    """Linie do wyswietlenia: jak dane wydarzenie wplywa (lub moze wplynac) na
    obserwowane aktywa.

    Jesli mamy juz POTWIERDZONY wynik (actual_value, np. z FRED/ECB) i prognoze
    (estimate), liczymy realne zaskoczenie i pokazujemy ROZSTRZYGNIETA analize
    (kierunek dla kazdego aktywa + tabela). W przeciwnym razie — jak dotychczas
    — pokazujemy oba warianty (WYZEJ / NIZEJ od prognozy).
    """
    expected_raw = _parse_numeric(event.get("estimate"))

    # Zabezpieczenie przed zlym dopasowaniem serii FRED: jesli "wynik" i
    # prognoza wygladaja na zupelnie inna skale/jednostke (np. wynik ~3 jako
    # YoY%, a prognoza ~-0.2 jako m/m%), to nie jest realne zaskoczenie —
    # pokaz oba scenariusze (WYZEJ/NIZEJ), nie rozstrzygnieta analize.
    if actual_value is not None and expected_raw not in (None, 0):
        if abs((actual_value - expected_raw) / abs(expected_raw) * 100) > 300:
            actual_value, actual_date = None, None

    cat = get_event_category(event.get("event", ""))
    if not cat:
        # Siatka bezpieczenstwa: dla wazniejszych danych (SREDNI+) bez wlasnego
        # szablonu kategorii pokazujemy chociaz surowe zaskoczenie, zeby nic
        # istotnego nie przeszlo w calkowitej ciszy.
        imp_label, _, _ = get_importance(event)
        if (imp_label in ("SREDNI", "WYSOKI", "KRYTYCZNY")
                and actual_value is not None and expected_raw is not None):
            surprise = actual_value - expected_raw
            if surprise != 0:
                surprise_pct = (surprise / abs(expected_raw) * 100) if expected_raw else 0.0
                strength = "MOCNA" if abs(surprise_pct) > 5 else "UMIARKOWANA" if abs(surprise_pct) > 2 else "SLABA"
                return [
                    f"  [bold yellow]ZASKOCZENIE: {_fmt_num(actual_value)} vs prognoza "
                    f"{_fmt_num(expected_raw)}  ->  {surprise:+.2f} ({surprise_pct:+.1f}%) — "
                    f"{strength}[/bold yellow]",
                    "  [dim](brak szablonu analizy wplywu dla tej kategorii danych — "
                    "zaskoczenie odnotowane, ale bez tabeli aktywow)[/dim]",
                ]
        return []
    category, higher_is_hawkish, label, explain = cat
    tpl = IMPACT_TEMPLATES[category]
    lines = [f"  [bold magenta]» {label}[/bold magenta]"]
    lines.append(f"  [dim italic]Co to jest: {explain}[/dim italic]")

    if event.get("country") and event["country"] != "US":
        lines.append(
            f"  [dim](dana dla {event['country']} — wplyw na USD/BTC zwykle slabszy "
            f"i posredni niz przy danych z USA)[/dim]"
        )

    if actual_value is not None and expected_raw is not None:
        surprise = actual_value - expected_raw
        surprise_pct = (surprise / abs(expected_raw) * 100) if expected_raw else 0.0
        is_hawkish = (surprise > 0) if higher_is_hawkish else (surprise < 0)
        desc = tpl["hawkish_desc"] if is_hawkish else tpl["dovish_desc"]

        lines.append("")
        if surprise == 0:
            lines.append(
                "  [dim]Brak zaskoczenia — wynik zgodny z prognoza, "
                "neutralny wplyw na rynki.[/dim]"
            )
            if actual_date:
                lines.append(f"  [dim](zrodlo: FRED/ECB, dane na {actual_date})[/dim]")
            else:
                lines.append("  [dim](zrodlo: myfxbook.com)[/dim]")
            if not is_new:
                lines.append(
                    "  [dim yellow]Uwaga: ten odczyt z FRED nie zmienil sie od ostatniego "
                    "sprawdzenia dzisiaj — moze to byc wciaz POPRZEDNI odczyt (FRED bywa "
                    "opozniony o 1-2 dni wzgledem publikacji)[/dim yellow]"
                )
            return lines

        strength = "MOCNA" if abs(surprise_pct) > 5 else "UMIARKOWANA" if abs(surprise_pct) > 2 else "SLABA"
        scolor = "red" if is_hawkish else "green"
        lines.append(
            f"  [bold {scolor}]ZASKOCZENIE: {_fmt_num(actual_value)} vs prognoza "
            f"{_fmt_num(expected_raw)}  ->  {surprise:+.2f} ({surprise_pct:+.1f}%) — "
            f"{strength}[/bold {scolor}]"
        )
        if actual_date:
            lines.append(f"  [dim](zrodlo: FRED/ECB, dane na {actual_date})[/dim]")
        else:
            lines.append("  [dim](zrodlo: myfxbook.com)[/dim]")
        if not is_new:
            lines.append(
                "  [dim yellow]Uwaga: ten odczyt z FRED nie zmienil sie od ostatniego "
                "sprawdzenia dzisiaj — moze to byc wciaz POPRZEDNI odczyt (FRED bywa "
                "opozniony o 1-2 dni wzgledem publikacji)[/dim yellow]"
            )
        lines.append(f"  -> [bold {scolor}]{desc}[/bold {scolor}]")

        table = Table(box=box.SIMPLE_HEAVY, show_edge=False, pad_edge=False, expand=False)
        table.add_column("Aktywo", style="bold", no_wrap=True)
        table.add_column("Kierunek", no_wrap=True)
        table.add_column("Dlaczego")
        for asset, (hawk_dir, dove_dir, hawk_note, dove_note) in tpl["assets"].items():
            if is_hawkish:
                d, note = hawk_dir, hawk_note
            else:
                d, note = dove_dir, dove_note
            color, txt = ARROW_LABEL[d]
            table.add_row(asset, f"[{color}]{txt}[/{color}]", note)

        with console.capture() as cap:
            console.print(table)
        for ln in cap.get().splitlines():
            if ln.strip():
                lines.append("  " + ln)

        horizon_key = "hawkish" if is_hawkish else "dovish"
        lines.append(f"  [dim]Horyzont: {tpl['horizon'][horizon_key]}[/dim]")
        return lines

    # Brak rozstrzygnietego wyniku -> pokaz oba warianty (WYZEJ / NIZEJ)
    if actual_value is not None:
        date_part = f" ({actual_date})" if actual_date else ""
        lines.append(
            f"  [dim]Najnowszy znany odczyt{date_part}: {_fmt_num(actual_value)} — "
            f"brak prognozy do porownania[/dim]"
        )

    def asset_lines(direction_key: str) -> list[str]:
        out = []
        for asset, (hawk_dir, dove_dir, hawk_note, dove_note) in tpl["assets"].items():
            if direction_key == "hawkish":
                d, note = hawk_dir, hawk_note
            else:
                d, note = dove_dir, dove_note
            color, txt = ARROW_LABEL[d]
            out.append(f"    [{color}]{txt}[/{color}]  {asset:38} {note}")
        return out

    lines.append("")
    lines.append(f"  [bold red]-> JESLI WYZEJ[/bold red] niz prognoza: {tpl['hawkish_desc']}")
    lines += asset_lines("hawkish")
    lines.append(f"  [bold green]-> JESLI NIZEJ[/bold green] niz prognoza: {tpl['dovish_desc']}")
    lines += asset_lines("dovish")
    lines.append(f"  [dim]Horyzont (gdy WYZEJ): {tpl['horizon']['hawkish']}[/dim]")
    lines.append(f"  [dim]Horyzont (gdy NIZEJ): {tpl['horizon']['dovish']}[/dim]")

    return lines


def display_full(events: list[dict]) -> None:
    """Kompleksowy raport: wszystkie dzisiejsze wydarzenia z najwazniejszych
    gospodarek (USA, Strefa Euro, Niemcy, Japonia), z wyjasnieniem PO POLSKU
    co dana oznacza i jak wplywa (lub moze wplynac) na obserwowane aktywa.

    Dla danych z USA i strefy euro probujemy automatycznie pobrac realny
    wynik (FRED/ECB). Jesli mamy swiezy wynik + prognoze — pokazujemy
    rozstrzygnieta analize (kierunek per aktywo + tabela). W przeciwnym razie
    (Niemcy/Japonia, lub wynik jeszcze niedostepny) — oba warianty WYZEJ/NIZEJ.
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    today = datetime.now(timezone.utc).date()

    important_countries = {"US", "EU", "DE", "JP"}
    todays = []
    for e in events:
        try:
            dt = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.date() != today:
            continue
        if e.get("country", "") not in important_countries:
            continue
        if any(kw in e.get("event", "").lower() for kw in NOISE_KEYWORDS):
            continue
        todays.append(e)

    released, upcoming = [], []
    for e in todays:
        ts = datetime.fromisoformat(e["time"].replace("Z", "+00:00")).timestamp()
        (released if ts <= now_ts else upcoming).append(e)

    # Sprobuj pobrac realne wyniki dla juz wydanych danych USA/EU — najpierw
    # "actual" z myfxbook (resolve_actual zwraca je bezposrednio), a gdy go
    # nie ma, FRED/ECB jako zapasowe zrodlo. Pamiec "co juz widzielismy"
    # resetuje sie co dzien — dzieki temu kazdego dnia pierwsze uruchomienie
    # pokazuje rozstrzygnieta analize dla wszystkich dzisiejszych wydarzen z
    # dostepnym wynikiem, a kolejne (tego samego dnia) nie powtarzaja w kolko
    # tej samej analizy.
    today_str = today.isoformat()
    fred_seen = _load_fred_seen()
    if fred_seen.get("_date") != today_str:
        fred_seen = {"_date": today_str}
    fred_updates: dict = {}
    actuals: dict[int, tuple[float, str | None, bool]] = {}
    for e in released:
        result = resolve_actual(e, fred_seen, fred_updates)
        if result is not None:
            actuals[id(e)] = result
    if fred_updates:
        fred_seen.update(fred_updates)
        fred_seen["_date"] = today_str
        _save_fred_seen(fred_seen)

    resolved_count = len(actuals)
    new_count = sum(1 for v in actuals.values() if v[2])
    stale_count = resolved_count - new_count
    if new_count:
        info = (
            f"[bold green]{new_count} wydarzen ma juz NOWY potwierdzony wynik "
            f"(myfxbook / FRED-ECB)[/bold green]"
        )
        if stale_count:
            info += f" + {stale_count} bez zmian od ostatniego sprawdzenia"
        info += " — ponizej pelna analiza wplywu na aktywa.\n"
    elif resolved_count:
        info = (
            f"[yellow]{resolved_count} wydarzen ma dane z FRED/ECB, ale bez zmiany "
            f"od ostatniego sprawdzenia dzisiaj[/yellow] — ponizej analiza z "
            f"zastrzezeniem ze to moze byc nadal poprzedni odczyt.\n"
        )
    else:
        info = (
            "[dim]Dla wydarzen bez jeszcze potwierdzonego wyniku ponizej widac OBA "
            "warianty: co sie stanie z aktywami, jesli odczyt wyjdzie WYZEJ a co "
            "jesli NIZEJ od prognozy.[/dim]\n"
        )

    console.print(Panel(
        f"[bold]{today.strftime('%d.%m.%Y')}[/bold]   "
        f"Juz bylo dzisiaj: [green]{len(released)}[/green]   "
        f"Jeszcze dzis wyjdzie: [yellow]{len(upcoming)}[/yellow]\n\n"
        + info +
        "[dim]Zakres: tylko najwazniejsze gospodarki — USA, Strefa Euro, Niemcy, "
        "Japonia. Pozostale kraje pominiete, by nie tworzyc szumu.[/dim]",
        title="[bold]KALENDARZ EKONOMICZNY — PELNY RAPORT[/bold]",
    ))

    def _print_section(title_: str, items: list[dict], color: str, est_label: str) -> None:
        if not items:
            return
        console.print(f"\n[bold {color}]{title_}[/bold {color}]\n")
        for e in sorted(items, key=lambda x: x["time"]):
            label, lcolor, _ = get_importance(e)
            t = format_time(e["time"])
            console.print(f"[{lcolor}][{label}][/{lcolor}] {t}  {e['country']} — [bold]{e['event']}[/bold]")
            meta = []
            raw_actual = e.get("actual")
            if raw_actual not in (None, "", "null"):
                meta.append(f"[bold cyan]Wynik: {raw_actual}[/bold cyan]")
            if e.get("estimate") not in (None, ""): meta.append(f"[dim]{est_label}: {e['estimate']}[/dim]")
            if e.get("prev") not in (None, ""):     meta.append(f"[dim]Poprzednio: {e['prev']}[/dim]")
            if meta:
                console.print("  " + "  |  ".join(meta))
            actual_value, actual_date, is_new = actuals.get(id(e), (None, None, True))
            impact_lines = format_event_impact(e, actual_value, actual_date, is_new)
            if impact_lines:
                console.print()
                for line in impact_lines:
                    console.print(line)
            console.print()

    _print_section("== JUZ BYLO DZISIAJ ==", released, "green", "Prognoza")
    _print_section("== JESZCZE DZIS WYJDZIE ==", upcoming, "yellow", "Prognoza")

    if not released and not upcoming:
        console.print("[dim]Brak istotnych wydarzen makro na dzis (USA / Strefa Euro / Niemcy / Japonia).[/dim]")

    _full_report_summary(released, upcoming, resolved_count)


def _full_report_summary(released: list[dict], upcoming: list[dict], resolved_count: int = 0) -> None:
    """Calosciowe podsumowanie dnia: harmonogram najwazniejszych danych
    (juz minionych i nadchodzacych) + przypomnienie jak sprawdzic realny wplyw."""
    key_events = [e for e in released + upcoming if get_importance(e)[0] in ("KRYTYCZNY", "WYSOKI")]

    if not key_events:
        console.print(Panel(
            "Dzis brak danych o najwyzszym znaczeniu (KRYTYCZNY/WYSOKI) — "
            "ponizsze (mniej wazne) dane moga nadal lekko poruszyc rynek, "
            "ale raczej nie zmienia trendu.",
            title="[bold]PODSUMOWANIE DNIA[/bold]", expand=False,
        ))
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    lines = ["Najwazniejsze dane dzisiaj (KRYTYCZNY / WYSOKI):", ""]
    for e in sorted(key_events, key=lambda x: x["time"]):
        ts = datetime.fromisoformat(e["time"].replace("Z", "+00:00")).timestamp()
        status = "[dim]juz bylo[/dim]" if ts <= now_ts else "[yellow]nadchodzi[/yellow]"
        t = format_time(e["time"])
        label, color, _ = get_importance(e)
        lines.append(f"  {t}  [{color}][{label}][/{color}]  {e['country']} — {e['event']}  ({status})")

    lines.append("")
    if resolved_count:
        lines.append(
            "Dla danych z USA/strefy euro powyzej pokazana jest juz automatyczna "
            "analiza wplywu (gdy wynik byl juz dostepny na myfxbook lub w FRED/ECB)."
        )
    else:
        lines.append(
            "Gdy pojawi sie realny wynik (myfxbook aktualizuje 'actual' zwykle w "
            "ciagu kilku minut od publikacji), kolejne uruchomienie --full pokaze "
            "automatyczna analize. Mozna tez sprawdzic recznie:"
        )
        lines.append('  python scripts/econ_calendar.py impact "NAZWA WYDARZENIA" WYNIK PROGNOZA')

    console.print(Panel("\n".join(lines), title="[bold]PODSUMOWANIE DNIA[/bold]", expand=False))


def is_high_impact(event: dict) -> bool:
    name = (event.get("event") or "").lower()
    impact = (event.get("impact") or "").lower()
    if impact in ("high", "3"):
        return True
    return any(kw in name for kw in HIGH_IMPACT_KEYWORDS)


def format_time(dt_str: str) -> str:
    try:
        from tz_utils import fmt_both
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return fmt_both(dt)
    except Exception:
        return dt_str or "TBD"


def impact_color(impact: str) -> str:
    i = (impact or "").lower()
    if i in ("high", "3"):    return "red"
    if i in ("medium", "2"):  return "yellow"
    return "dim"


# Eventy, ktore z natury dotycza TYLKO USA (nazwa nie powtarza sie dla innych
# krajow) — podwyzszenie wagi obowiazuje zawsze, niezaleznie od kraju.
IMPORTANCE_LABELS = {
    "nonfarm":       ("KRYTYCZNY", "red",    "bold"),
    "non farm":      ("KRYTYCZNY", "red",    "bold"),
    "nfp":           ("KRYTYCZNY", "red",    "bold"),
    "fomc":          ("KRYTYCZNY", "red",    "bold"),
    "fed":           ("WYSOKI",    "red",    ""),
    "powell":        ("WYSOKI",    "red",    ""),
    "pce":           ("KRYTYCZNY", "red",    "bold"),
    "building":      ("NISKI",     "green",  "dim"),
    "housing":       ("NISKI",     "green",  "dim"),
}

# Eventy, ktorych nazwa (np. "Inflation Rate", "Unemployment Rate", "Retail
# Sales") wystepuje w myfxbook dla KAZDEGO kraju — podwyzszenie wagi ma sens
# TYLKO dla USA. Dla innych krajow ten sam event jest zazwyczaj realnie mniej
# wazny i myfxbook juz prawidlowo oznacza go jako Low/Medium — bez tego
# gate'u np. niemiecka/francuska "Inflation Rate MoM" (impact=Low) zostalaby
# nadpisana na KRYTYCZNY tylko dlatego, ze zawiera slowo "inflation rate".
IMPORTANCE_LABELS_US = {
    "inflation rate": ("KRYTYCZNY", "red",    "bold"),
    "cpi":            ("KRYTYCZNY", "red",    "bold"),
    "gdp":            ("WYSOKI",    "red",    ""),
    "jobless":        ("WYSOKI",    "red",    ""),
    "unemployment":   ("WYSOKI",    "red",    ""),
    "pmi":            ("SREDNI",    "yellow", ""),
    "retail sales":   ("SREDNI",    "yellow", ""),
    "ppi":            ("SREDNI",    "yellow", ""),
}

_IMPORTANCE_LABELS_US_ALL = {**IMPORTANCE_LABELS, **IMPORTANCE_LABELS_US}

# Jak dany event wplywa na nasze rynki
EVENT_IMPACT_MAP = {
    "nonfarm":        "BTC reaguje mocno — duzo miejsc pracy = Fed nie tnie = presja na crypto",
    "non farm":       "BTC reaguje mocno — duzo miejsc pracy = Fed nie tnie = presja na crypto",
    "cpi":            "Kluczowy dla BTC i Zlota — inflacja powyzej oczekiwan = Fed ostrozny = spadki",
    "inflation rate": "Kluczowy dla BTC i Zlota — inflacja powyzej oczekiwan = bank centralny ostrozny = spadki",
    "fomc":           "Najwazniejszy event w miesiacu — decyzja o kosztach kredytu w USA",
    "pce":            "Ulubiony wskaznik inflacji Fed — podobny efekt jak CPI",
    "gdp":            "PKB = jak szybko rosnie gospodarka USA",
    "jobless":        "Bezrobocie: wiecej wnioskow = slaba gospodarka = Fed moze ciac = wzrostowe dla BTC",
    "pmi":            "Termometr gospodarki: >50 rosnie, <50 kurczy sie",
    "retail sales":   "Wydatki konsumentow: silne = gospodarka zdrowa = Fed nie tnie",
    "ppi":            "Inflacja u producentow — poprzedza inflacje konsumencka (CPI)",
}


_IMPORTANCE_RANK = {"KRYTYCZNY": 3, "WYSOKI": 2, "SREDNI": 1, "NISKI": 0}


def get_importance(event: dict) -> tuple[str, str, str]:
    """Returns (label, color, style)"""
    name    = (event.get("event") or "").lower()
    imp     = (event.get("impact") or "").lower()
    country = event.get("country", "")

    if imp in ("high", "3"):     base = ("WYSOKI", "red",    "")
    elif imp in ("medium", "2"): base = ("SREDNI", "yellow", "")
    elif imp in ("low", "1"):    base = ("NISKI",  "green",  "dim")
    else:                        base = None

    # Slowa kluczowe moga PODNIESC waznosc dla kluczowych eventow, ale nigdy
    # nie obnizyc faktyczny rating z feedu. "Final"/"Revised" to tylko
    # potwierdzenie wczesniejszego (flash) odczytu — nizszy realny impact,
    # wiec dla nich nie stosujemy podwyzszenia po slowie kluczowym.
    labels = _IMPORTANCE_LABELS_US_ALL if country == "US" else IMPORTANCE_LABELS
    if "final" not in name and "revised" not in name:
        for kw, (label, color, style) in labels.items():
            if kw in name:
                if base is None or _IMPORTANCE_RANK[label] > _IMPORTANCE_RANK[base[0]]:
                    return label, color, style
                break

    if base:
        return base
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


def display_alpha(events: list[dict]) -> None:
    """Compact calendar for Daily Alpha Brief — plain text, max 7 events total.

    Format: 3-4 already-published HIGH/CRITICAL + 3 upcoming HIGH/CRITICAL.
    Plain print() output (no Rich colors) — goes directly to Claude context.
    """
    from datetime import datetime, timezone as _tz
    now_ts = datetime.now(_tz.utc).timestamp()

    important_countries = {"US", "GB", "EU", "DE", "FR", "JP", "CN", "CA", "AU", "CH"}

    published: list[dict] = []
    upcoming:  list[dict] = []

    for e in sorted(events, key=lambda x: x.get("time", "")):
        label, _, _ = get_importance(e)
        if label == "NISKI":
            continue
        country = e.get("country", "")
        if country not in important_countries and not is_high_impact(e):
            continue

        # Determine if already released: has actual value OR time already passed
        actual_raw = e.get("actual")
        has_actual = actual_raw is not None and str(actual_raw).strip() not in ("", "null")
        try:
            ev_ts = datetime.fromisoformat(e["time"].replace("Z", "+00:00")).timestamp()
        except Exception:
            ev_ts = 0
        is_past = ev_ts < now_ts

        t       = format_time(e.get("time", ""))
        name    = e.get("event", "")
        est     = e.get("estimate")
        prev    = e.get("prev")
        actual  = e.get("actual") if has_actual else None
        tip_tag = "[WYS]" if label == "WYSOKI" else "[KRY]" if label == "KRYTYCZNY" else "[SRD]"

        # Build value string
        vals = ""
        if actual is not None:
            vals += f"  actual:{actual}"
        if est:
            vals += f"  est:{est}"
        if prev:
            vals += f"  prev:{prev}"

        entry = f"{t} {tip_tag} {country} — {name}{vals}"

        if has_actual or is_past:
            published.append(entry)
        else:
            upcoming.append(entry)

    # Risk summary
    total_critical = sum(1 for e in events if get_importance(e)[0] == "KRYTYCZNY")
    total_high     = sum(1 for e in events if get_importance(e)[0] == "WYSOKI")
    if total_critical >= 2:
        risk = "WYSOKI"
    elif total_critical == 1 or total_high >= 2:
        risk = "SREDNI"
    elif total_high == 1:
        risk = "NISKI-SREDNI"
    else:
        risk = "NISKI"

    sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None
    print(f"ECON CALENDAR — ryzyko makro dzis: {risk}")
    print("")

    if published:
        print("[OK] JUZ OPUBLIKOWANE:")
        for line in published[:4]:
            print(f"  {line}")
    else:
        print("[OK] Brak opublikowanych danych wysokiego wplywu.")

    print("")

    if upcoming:
        print("[>>] NADCHODZACE DZIS:")
        for line in upcoming[:3]:
            print(f"  {line}")
    else:
        print("[>>] Brak nadchodzacych danych wysokiego wplywu na dzis.")


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
    p.add_argument("--alpha",    action="store_true", help="Compact plain-text output for Daily Alpha: max 7 events (4 published + 3 upcoming), HIGH/CRITICAL only")
    p.add_argument("--upcoming", action="store_true", help="Show only upcoming (not yet released) events today")
    p.add_argument("--full",     action="store_true", help="Pelny raport: co juz wyszlo + co jeszcze dzis wyjdzie + wplyw na BTC/Zloto/Srebro/Ropa/SP500/USD")

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

    if args.full:
        display_full(events)
    elif args.alpha:
        display_alpha(events)
    elif args.upcoming:
        display_upcoming(events)
    elif args.brief:
        display_brief(events)
    else:
        display_calendar(events, days=args.days)


if __name__ == "__main__":
    main()
