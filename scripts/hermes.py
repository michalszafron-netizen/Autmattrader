"""hermes.py — Daily Alpha Brief orchestrator.

Zbiera dane ze wszystkich modułów równolegle, buduje MarketContext,
syntetyzuje cross-modułowe wnioski przez LLM (Grok/xAI) i generuje
pełny Daily Alpha Brief.

Usage:
    python scripts/hermes.py                         # pełny brief
    python scripts/hermes.py --no-news               # pomiń blogwatcher (oszczędność Firecrawl)
    python scripts/hermes.py --no-sentiment          # pomiń x_sentiment (oszczędność Grok)
    python scripts/hermes.py --no-cot                # pomiń COT tracker
    python scripts/hermes.py --no-whales             # pomiń whale tracker
    python scripts/hermes.py --from-cache STAMP      # użyj cached news (zero Firecrawl)
    python scripts/hermes.py --positions FILE        # inny plik pozycji
    python scripts/hermes.py --output FILE.md        # zapisz brief do pliku
    python scripts/hermes.py --dry-run               # zbierz dane, pomiń LLM
    python scripts/hermes.py --model grok-4.3        # zmień model LLM
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from datetime import datetime, timezone
from pathlib import Path

import httpx
import truststore
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

load_dotenv(Path(__file__).parent.parent / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT    = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"

# Detect Python in venv (Windows vs Linux)
_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not _PYTHON.exists():
    _PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(_PYTHON)

_SSL          = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
console       = Console(legacy_windows=False, force_terminal=True)

XAI_API_KEY   = os.getenv("XAI_API_KEY", "")
XAI_BASE      = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-3-mini"

# Strip ANSI escape codes from subprocess output.
# Two forms: with ESC prefix (\x1b[...m) or without (e.g. [1;36m captured by some terminals).
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[mGKHFJST]"   # standard ANSI with ESC
    r"|\x1b\][^\x07]*\x07"        # OSC sequences
    r"|\r"                         # carriage returns
    r"|\[[\d;]+m"                  # ANSI without ESC prefix (subprocess capture artifact)
)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).strip()


# ── subprocess runner ──────────────────────────────────────────────────────────

def run_script(script: str, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run script from SCRIPTS dir.
    NO_COLOR=1 + TERM=dumb suppress Rich ANSI output.
    PYTHONIOENCODING=utf-8 prevents cp1252 UnicodeEncodeError on Windows.
    """
    env = {
        **os.environ,
        "NO_COLOR": "1",
        "TERM": "dumb",
        "FORCE_COLOR": "0",
        "PYTHONIOENCODING": "utf-8",
    }
    cmd = [PYTHON, str(SCRIPTS / script)] + args
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        cwd=str(ROOT), env=env, encoding="utf-8", errors="replace",
    )
    return result.returncode, strip_ansi(result.stdout), strip_ansi(result.stderr)


# ── Collectors ─────────────────────────────────────────────────────────────────

def collect_positions(path: str | None = None) -> list[dict]:
    """Load positions from JSON file (already fetched by fetch_positions.py)."""
    p = Path(path) if path else ROOT / "positions.json"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def collect_fear_greed() -> dict:
    """Fetch Fear & Greed (alternative.me). Parses fear_greed.py --brief output."""
    try:
        _, out, _ = run_script("fear_greed.py", ["--brief"], timeout=20)
        # Format: "Fear & Greed: 67/100 — Greed | Trend 5d: 62→65→67→68→67 → (stabilny)"
        m = re.search(r"(\d+)/100\s*[—-]\s*(\w[\w ]+?)\s*\|", out)
        score  = int(m.group(1)) if m else None
        label  = m.group(2).strip() if m else "Unknown"
        trend_m = re.search(r"Trend 5d:\s*([\d→]+)\s+(.+)$", out)
        trend  = trend_m.group(0).strip() if trend_m else ""
        return {"score": score, "label": label, "trend": trend, "raw": out}
    except Exception as e:
        return {"score": None, "label": "Error", "trend": "", "raw": str(e)}


def collect_econ_calendar() -> str:
    """Fetch today's economic events (FinnHub)."""
    try:
        _, out, err = run_script("econ_calendar.py", ["--brief"], timeout=20)
        return out or err or "N/A"
    except Exception as e:
        return f"Error: {e}"


def collect_cot() -> str:
    """COT institutional positioning brief."""
    try:
        _, out, err = run_script("cot_tracker.py", ["--brief"], timeout=60)
        return out or err or "N/A"
    except Exception as e:
        return f"Error: {e}"


def collect_oi() -> str:
    """Open Interest brief (Binance + Bybit + Extended)."""
    try:
        _, out, err = run_script("oi_tracker.py", ["--brief"], timeout=30)
        return out or err or "N/A"
    except Exception as e:
        return f"Error: {e}"


def collect_whales(top: int = 10) -> str:
    """Hyperliquid whale positions brief."""
    try:
        _, out, err = run_script(
            "hl_whale_tracker.py", ["whales", "--top", str(top)], timeout=40
        )
        return out or err or "N/A"
    except Exception as e:
        return f"Error: {e}"


def collect_news(
    positions_file: str | None = None,
    from_cache: str | None = None,
) -> tuple[list[dict], dict]:
    """Fetch news articles via blogwatcher (--json mode). Returns (articles, asset_impact)."""
    pos_path = positions_file or (str(ROOT / "positions.json") if (ROOT / "positions.json").exists() else None)
    args = ["--json"]
    if pos_path:
        args += ["--positions", pos_path]
    if from_cache:
        args += ["--from-cache", from_cache]

    try:
        _, out, err = run_script("blogwatcher.py", args, timeout=300)
        # blogwatcher --json prints Rich messages first, then the JSON array on its own line.
        # Find first line that starts a JSON array.
        m = re.search(r"^\[", out, re.MULTILINE)
        if m:
            articles = json.loads(out[m.start():])
        else:
            return [], {}
        return articles, _build_asset_impact(articles)
    except Exception as e:
        return [], {}


def _build_asset_impact(articles: list[dict]) -> dict:
    """Aggregate per-asset net sentiment from articles list."""
    data: dict[str, dict] = {}
    for a in articles:
        for sym in a.get("affected_assets", []):
            if sym not in data:
                data[sym] = {"bull": 0, "bear": 0, "neut": 0, "articles": []}
            sent = a.get("sentiment", "neutral")
            data[sym]["bull" if sent == "bullish" else "bear" if sent == "bearish" else "neut"] += 1
            data[sym]["articles"].append(a)

    impact: dict[str, dict] = {}
    _rank = {"high": 0, "medium": 1, "low": 2}
    for sym, d in data.items():
        bull, bear, neut = d["bull"], d["bear"], d["neut"]
        if bull > bear:
            sentiment = "bullish"
        elif bear > bull:
            sentiment = "bearish"
        elif bull == bear and bull > 0:
            sentiment = "mixed"
        else:
            sentiment = "neutral"
        top_articles = sorted(d["articles"], key=lambda a: _rank.get(a.get("impact", "low"), 2))
        top_hl = top_articles[0]["headline"] if top_articles else ""
        impact[sym] = {
            "sentiment": sentiment,
            "bull": bull,
            "bear": bear,
            "neut": neut,
            "top_headline": top_hl,
        }
    return impact


# ── LLM synthesis ──────────────────────────────────────────────────────────────

SYNTHESIS_PROMPT_TEMPLATE = """\
Jesteś Hermes — profesjonalny analityk tradingowy. Na podstawie poniższych danych \
multi-źródłowych napisz dwie sekcje Daily Alpha Brief.

WAŻNE ZASADY:
- Pisz po polsku
- Bądź konkretny — podawaj liczby i ceny z danych
- Pisz tylko o tym co widzisz w danych, bez halucynacji
- Format: markdown, sekcje z nagłówkami ##

WYMAGANE SEKCJE (tylko te dwie):

## POSITION WATCH
Dla każdej otwartej pozycji przeanalizuj cross-modułowo:
  - Czy news wspiera czy osłabia tezę?
  - Czy COT instytucje są po tej samej stronie?
  - Czy wieloryby HL są po tej samej stronie?
  - Jaki jest ogólny werdykt: HOLD / REDUCE / ADD / CLOSE?
  - Czy zbliża się event makro który może uderzyć w tę pozycję?

## 🧠 TWOJE EDGE (weryfikacja hipotez)
Jeśli w sekcji DANE są obserwacje z "MOJE EDGE":
  - Dla każdej aktywnej obserwacji: czy aktualne dane rynkowe WSPIERAJĄ czy OBALAJĄ hipotezę?
  - Podaj konkretne liczby/eventy z danych które to potwierdzają lub negują
  - NIE akceptuj obserwacji bez weryfikacji — zachowaj sceptycyzm
  - Jeśli brak aktywnych edge'ów lub sekcji MOJE EDGE → pomiń tę sekcję całkowicie

## EXPERT VIEW — Convergence Signals
Wymień 3-5 sygnałów gdzie CO NAJMNIEJ 2 źródła są zgodne.
Format każdego: `[ASSET] kierunek — źródło1 + źródło2 → implikacja`
Na końcu: ogólny bias rynkowy (RISK-ON / RISK-OFF / MIXED) i uzasadnienie.

═══════════════════════════════════════
DANE RYNKOWE:

{market_data}
"""


def _build_market_data_text(ctx: dict, articles: list[dict]) -> str:
    """Build human-readable market data block for LLM prompt."""
    parts: list[str] = []

    # Positions
    if ctx.get("positions"):
        lines = ["### OPEN POSITIONS"]
        for p in ctx["positions"]:
            tp   = f"TP=${p['tp']}" if p.get("tp") else "TP=—"
            sl   = f"SL=${p['sl']}" if p.get("sl") else "SL=—"
            upnl_raw = p.get("upnl_usd")
            upnl = f"uPnL=${upnl_raw:+.2f}" if upnl_raw is not None else ""
            lines.append(
                f"  {p['symbol']:8} {p['side']:5} @ ${p['entry']}"
                f"  [{p.get('venue','?')} {p.get('leverage','?')}]"
                f"  {tp}  {sl}  {upnl}"
            )
        parts.append("\n".join(lines))

    # Fear & Greed
    fg = ctx.get("fear_greed", {})
    if fg.get("score") is not None:
        parts.append(f"### FEAR & GREED\n  {fg['score']}/100 — {fg['label']}  {fg.get('trend','')}")

    # News asset impact
    if ctx.get("asset_impact"):
        lines = ["### NEWS SENTIMENT (last 12h)"]
        ORDER = ["BTC","ETH","SOL","HYPE","LINK","GOLD","SILVER","OIL","NDX","SPX","DXY","CORN","COFFEE","COCOA"]
        for sym in ORDER:
            d = ctx["asset_impact"].get(sym)
            if not d or (d["bull"] + d["bear"] + d["neut"]) == 0:
                continue
            hl = d["top_headline"][:80]
            lines.append(f"  {sym:8} {d['sentiment'].upper():8} ({d['bull']}B/{d['bear']}b/{d['neut']}n)  {hl}")
        parts.append("\n".join(lines))

    # Econ calendar
    econ = ctx.get("econ_calendar", "")
    if econ and econ not in ("N/A", ""):
        parts.append(f"### ECONOMIC CALENDAR\n{econ[:600]}")

    # COT
    cot = ctx.get("cot", "")
    if cot and cot not in ("N/A", ""):
        parts.append(f"### COT (INSTITUTIONAL POSITIONING)\n{cot[:800]}")

    # OI
    oi = ctx.get("oi", "")
    if oi and oi not in ("N/A", ""):
        parts.append(f"### OPEN INTEREST\n{oi[:600]}")

    # Whales
    whales = ctx.get("whales", "")
    if whales and whales not in ("N/A", ""):
        parts.append(f"### HL WHALE POSITIONS\n{whales[:800]}")

    # My Edge (personal observations from edge_journal)
    edge_path = Path(__file__).parent.parent / "context" / "my_edge.md"
    if edge_path.exists():
        edge_txt = edge_path.read_text(encoding="utf-8").strip()
        if edge_txt:
            # Extract only ACTIVE observations block (skip closed/archived)
            open_start = edge_txt.find("## 🔵 Aktywne obserwacje")
            closed_start = edge_txt.find("## 📋")
            if open_start >= 0:
                block = edge_txt[open_start:closed_start if closed_start > open_start else None]
                if "Brak aktywnych obserwacji" not in block:
                    parts.append(f"### MOJE EDGE (hipotezy tradera — weryfikuj krytycznie)\n{block[:1200]}")

    return "\n\n".join(parts)


def llm_synthesize(ctx: dict, articles: list[dict], model: str = DEFAULT_MODEL) -> str:
    """Call Grok REST API with MarketContext. Returns POSITION WATCH + EXPERT VIEW markdown."""
    if not XAI_API_KEY:
        return "_(brak XAI_API_KEY — synteza LLM pominięta. Dodaj do .env: XAI_API_KEY=xai-...)_"

    market_data = _build_market_data_text(ctx, articles)
    prompt = SYNTHESIS_PROMPT_TEMPLATE.format(market_data=market_data)

    try:
        with httpx.Client(verify=_SSL, timeout=120) as client:
            r = client.post(
                f"{XAI_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.25,
                    "max_tokens": 2500,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        return f"_[LLM HTTP error {e.response.status_code}: {e.response.text[:200]}]_"
    except Exception as e:
        return f"_[LLM error: {e}]_"


# ── Renderer ──────────────────────────────────────────────────────────────────

def render_brief(ctx: dict, llm_output: str, articles: list[dict]) -> str:
    """Assemble full Daily Alpha Brief as markdown string."""
    ts   = ctx["timestamp"]
    pos  = ctx.get("positions", [])
    fg   = ctx.get("fear_greed", {})
    ai   = ctx.get("asset_impact", {})
    cot  = ctx.get("cot", "")
    oi   = ctx.get("oi", "")
    whales = ctx.get("whales", "")
    econ = ctx.get("econ_calendar", "")

    lines: list[str] = [
        f"# Daily Alpha Brief — {ts}",
        "",
        "> **Hermes** | "
        f"Pozycje: {len(pos)} | "
        f"News: {len(articles)} art. | "
        f"F&G: {fg.get('score','?')}/100 — {fg.get('label','?')}",
        "",
        "---",
        "",
    ]

    # LLM synthesis (POSITION WATCH + EXPERT VIEW)
    if llm_output:
        lines.append(llm_output)
        lines.append("")
        lines.append("---")
        lines.append("")

    # Econ calendar
    if econ and econ not in ("N/A", ""):
        lines += ["## ECONOMIC CALENDAR", "", "```", econ[:1200], "```", ""]

    # COT
    if cot and cot not in ("N/A", ""):
        lines += ["## COT SNAPSHOT", "", "```", cot[:1200], "```", ""]

    # OI
    if oi and oi not in ("N/A", ""):
        lines += ["## OPEN INTEREST", "", "```", oi[:1200], "```", ""]

    # Whales
    if whales and whales not in ("N/A", ""):
        lines += ["## WHALE LAYER", "", "```", whales[:1200], "```", ""]

    # Asset impact table
    if ai:
        ORDER = [
            "BTC", "ETH", "SOL", "HYPE", "LINK", "BTC.D",
            "DXY", "US10Y", "VIX",
            "GOLD", "SILVER", "OIL", "NATGAS",
            "NDX", "SPX",
            "CORN", "COFFEE", "COCOA",
        ]
        lines += ["## ASSET IMPACT (news)", "",
                  "| Asset | Sentiment | B/Bear/N | Top headline |",
                  "|-------|-----------|----------|--------------|"]
        for sym in ORDER:
            d = ai.get(sym)
            if not d:
                continue
            hl = (d["top_headline"][:65] + "…") if len(d["top_headline"]) > 67 else d["top_headline"]
            tag = {"bullish": "🟢 BULL", "bearish": "🔴 BEAR",
                   "mixed": "🟡 MIXED", "neutral": "—"}.get(d["sentiment"], d["sentiment"])
            lines.append(f"| **{sym}** | {tag} | {d['bull']}/{d['bear']}/{d['neut']} | {hl} |")
        lines.append("")

    # Raw positions recap
    if pos:
        lines += ["## OPEN POSITIONS", "",
                  "| Symbol | Side | Entry | Venue | Lev | TP | SL | uPnL |",
                  "|--------|------|-------|-------|-----|----|----|------|"]
        for p in pos:
            tp  = f"${p['tp']}" if p.get("tp") else "—"
            sl  = f"${p['sl']}" if p.get("sl") else "—"
            upnl_raw = p.get("upnl_usd")
            upnl = f"${upnl_raw:+.2f}" if upnl_raw is not None else "—"
            lines.append(
                f"| **{p['symbol']}** | {p['side']} | ${p['entry']} "
                f"| {p.get('venue','?')} | {p.get('leverage','?')} "
                f"| {tp} | {sl} | {upnl} |"
            )
        lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Hermes — Daily Alpha Brief orchestrator")
    p.add_argument("--positions",        help="Ścieżka do pliku pozycji (default: positions.json)")
    p.add_argument("--output",           help="Zapisz brief do pliku .md")
    p.add_argument("--from-cache",       metavar="STAMP", help="Cache stamp dla blogwatcher (zero Firecrawl)")
    p.add_argument("--no-news",          action="store_true", help="Pomiń blogwatcher")
    p.add_argument("--no-sentiment",     action="store_true", help="Pomiń x_sentiment")
    p.add_argument("--no-cot",           action="store_true", help="Pomiń COT tracker")
    p.add_argument("--no-whales",        action="store_true", help="Pomiń whale tracker")
    p.add_argument("--no-llm",           action="store_true", help="Zbierz dane, pomiń LLM")
    p.add_argument("--dry-run",          action="store_true", help="Jak --no-llm")
    p.add_argument("--no-refresh",       action="store_true",
                   help="Pomiń auto-odświeżenie pozycji (użyj istniejącego positions.json)")
    p.add_argument("--model",            default=DEFAULT_MODEL, help=f"Model LLM (default: {DEFAULT_MODEL})")
    args = p.parse_args()

    skip_llm = args.no_llm or args.dry_run

    console.print(Panel.fit(
        f"[bold cyan]HERMES[/bold cyan] — Daily Alpha Brief Orchestrator\n"
        f"[dim]{datetime.now(timezone.utc).strftime('%Y-%m-%d  %H:%M UTC')}[/dim]",
        border_style="cyan",
    ))

    # ── Phase 1: Data collection (parallel) ───────────────────────────────────
    console.print("\n[bold]Phase 1 — Zbieranie danych[/bold]")

    # Auto-refresh positions from live venues (unless --no-refresh or explicit --positions path)
    if not args.no_refresh and not args.positions:
        console.print("  [dim]↻ Odświeżanie pozycji z giełd...[/dim]", end=" ")
        try:
            rc, out, err = run_script("fetch_positions.py", [], timeout=60)
            if rc == 0:
                console.print("[green]OK[/green]")
            else:
                console.print(f"[yellow]warn (rc={rc})[/yellow]")
                if err:
                    console.print(f"[dim]  {err[:200]}[/dim]")
        except Exception as e:
            console.print(f"[yellow]error: {e}[/yellow]")

    ctx: dict = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "positions": collect_positions(args.positions),
    }
    articles: list[dict] = []

    console.print(f"  [green]✓[/green] positions — {len(ctx['positions'])} pozycji")

    # Define parallel tasks
    tasks: dict[str, callable] = {
        "fear_greed":     lambda: collect_fear_greed(),
        "econ_calendar":  lambda: collect_econ_calendar(),
        "oi":             lambda: collect_oi(),
    }
    if not args.no_cot:
        tasks["cot"]    = lambda: collect_cot()
    if not args.no_whales:
        tasks["whales"] = lambda: collect_whales()

    with ThreadPoolExecutor(max_workers=5) as pool:
        future_to_name: dict[Future, str] = {
            pool.submit(fn): name for name, fn in tasks.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                ctx[name] = future.result()
                fg_display = ""
                if name == "fear_greed" and isinstance(ctx[name], dict):
                    sc = ctx[name].get("score")
                    lb = ctx[name].get("label", "")
                    fg_display = f" ({sc}/100 — {lb})" if sc else ""
                console.print(f"  [green]✓[/green] {name}{fg_display}")
            except Exception as e:
                ctx[name] = "N/A"
                console.print(f"  [red]✗[/red] {name}: {e}")

    # News (blogwatcher — potentially slow + uses Firecrawl credits)
    if not args.no_news:
        console.print("  [dim]Pobieranie newsów (blogwatcher)…[/dim]", end="  ")
        from_cache = getattr(args, "from_cache", None)
        articles, ctx["asset_impact"] = collect_news(
            positions_file=args.positions,
            from_cache=from_cache,
        )
        console.print(f"[green]✓[/green] news — {len(articles)} artykułów, "
                      f"{len(ctx.get('asset_impact', {}))} aktywów z impaktem")
    else:
        ctx["asset_impact"] = {}
        console.print("  [yellow]–[/yellow] news pominięty (--no-news)")

    # ── Phase 2: LLM synthesis ────────────────────────────────────────────────
    llm_output = ""
    if not skip_llm:
        console.print(f"\n[bold]Phase 2 — LLM synthesis[/bold] [dim]({args.model})[/dim]")
        llm_output = llm_synthesize(ctx, articles, model=args.model)
        if llm_output.startswith("_["):
            console.print(f"  [red]✗[/red] {llm_output}")
        else:
            lines_count = llm_output.count("\n")
            console.print(f"  [green]✓[/green] synthesis — {lines_count} linii")
    else:
        console.print("\n[yellow]Phase 2 — LLM pominięty (--dry-run / --no-llm)[/yellow]")

    # ── Phase 3: Render ───────────────────────────────────────────────────────
    console.print("\n[bold]Phase 3 — Render[/bold]")

    brief_md = render_brief(ctx, llm_output, articles)

    # Print to terminal (markup=False prevents Rich from misinterpreting markdown brackets)
    fg  = ctx.get("fear_greed", {})
    pos = ctx.get("positions", [])
    console.print(Rule("[bold cyan]DAILY ALPHA BRIEF[/bold cyan]"))
    console.print(brief_md, markup=False, highlight=False)
    console.print(Rule())

    # Save to file — reports/YYYY-MM-DD_daily_alpha[_vN].md
    if args.output:
        output_path = args.output
    else:
        reports_dir = ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base = reports_dir / f"{today}_daily_alpha.md"
        if not base.exists():
            output_path = str(base)
        else:
            v = 2
            while (reports_dir / f"{today}_daily_alpha_v{v}.md").exists():
                v += 1
            output_path = str(reports_dir / f"{today}_daily_alpha_v{v}.md")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(brief_md)
    console.print(f"\n[green]Zapisano:[/green] {output_path}")

    # Quick stats summary
    console.print(
        f"\n[bold]Podsumowanie:[/bold] "
        f"{len(pos)} pozycji | "
        f"{len(articles)} news | "
        f"F&G {fg.get('score','?')}/100 | "
        f"assets z impaktem: {len(ctx.get('asset_impact', {}))}"
    )


if __name__ == "__main__":
    main()
