"""executor.py — warstwa egzekucji bota liquidation-scalp (Bybit perps).

Odpowiada za: sizing wg ryzyka, zaokraglenia do tick/qty, maker limit entry,
OBOWIAZKOWY stop-loss + take-profit, bramki bezpieczenstwa (paper default, cap ryzyka,
max pozycji, kill-switch dziennej straty). Tryb paper = pelna symulacja, zero realnych zlecen.

Zasady (zgodne z CLAUDE.md, nieprzekraczalne):
  - Domyslnie PAPER. Live tylko gdy LIQSCALP_MODE=live.
  - Ryzyko/trade <= 2% equity (twardy cap w config).
  - Kazde wejscie MA stop-loss — bez SL order jest odrzucany.
  - Strata dzienna > 3% -> kill-switch (blokada nowych wejsc).

CLI (test reczny, paper):
    python executor.py paper SOLUSDT long
    python executor.py paper XAUTUSDT short --sl-pct 0.6 --tp-pct 0.4
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bybit_rest import BybitREST          # noqa: E402
from config import Config, load_config     # noqa: E402
from store import Store                    # noqa: E402


def _round_step(value: float, step: float, *, mode: str = "nearest") -> float:
    if step <= 0:
        return value
    n = value / step
    if mode == "down":
        n = math.floor(n)
    elif mode == "up":
        n = math.ceil(n)
    else:
        n = round(n)
    return round(n * step, 10)


@dataclass
class OrderPlan:
    symbol: str
    side: str           # long | short
    qty: float
    entry: float
    sl: float
    tp: float
    risk_usd: float
    notional: float
    leverage: int

    def pretty(self) -> str:
        return (f"{self.side.upper()} {self.symbol} | qty={self.qty} "
                f"entry=${self.entry} SL=${self.sl} TP=${self.tp} "
                f"| ryzyko=${self.risk_usd:.2f} notional=${self.notional:.2f} lev={self.leverage}x")


class Executor:
    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or load_config()
        self.rest = BybitREST()
        self.store = Store()

    # ── plan zlecenia (sizing + zaokraglenia + SL/TP) ─────────────────────────
    def build_plan(self, symbol: str, side: str, *, entry: float | None = None,
                   sl_pct: float | None = None, tp_pct: float | None = None,
                   equity: float | None = None) -> OrderPlan:
        assert side in ("long", "short")
        instr = self.rest.instrument(symbol)
        bid, ask = self.rest.best_bid_ask(symbol)
        if entry is None:
            # maker: long wchodzi na bid, short na ask
            entry = bid if side == "long" else ask
        entry = _round_step(entry, instr["tick_size"])

        sl_pct = self.cfg.sl_pct if sl_pct is None else sl_pct
        tp_pct = self.cfg.tp_pct if tp_pct is None else tp_pct

        if side == "long":
            sl = _round_step(entry * (1 - sl_pct / 100), instr["tick_size"], mode="down")
            tp = _round_step(entry * (1 + tp_pct / 100), instr["tick_size"], mode="up")
        else:
            sl = _round_step(entry * (1 + sl_pct / 100), instr["tick_size"], mode="up")
            tp = _round_step(entry * (1 - tp_pct / 100), instr["tick_size"], mode="down")

        if equity is None:
            equity = self.rest.equity_usd()
        risk_usd = equity * self.cfg.risk_pct / 100.0

        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            raise ValueError("SL distance = 0 — zly entry/sl")
        qty = risk_usd / sl_dist                      # strata przy SL = risk_usd
        qty = _round_step(qty, instr["qty_step"], mode="down")
        if qty < instr["min_qty"]:
            qty = instr["min_qty"]                     # podloga gieldy (uwaga: moze podniesc ryzyko)

        notional = qty * entry
        real_risk = qty * sl_dist
        return OrderPlan(symbol, side, qty, entry, sl, tp, real_risk, notional, self.cfg.leverage)

    # ── bramki bezpieczenstwa ─────────────────────────────────────────────────
    def _preflight(self, plan: OrderPlan, equity: float) -> list[str]:
        errs = []
        if plan.sl <= 0:
            errs.append("brak/zly stop-loss — wejscie ZABRONIONE")
        if plan.risk_usd > equity * 2.0 / 100.0 + 1e-9:
            errs.append(f"ryzyko ${plan.risk_usd:.2f} > 2% equity (${equity*0.02:.2f})")
        if self.store.open_trades_count() >= self.cfg.max_positions:
            errs.append(f"limit pozycji: {self.cfg.max_positions} juz otwarte")
        if self.store.trades_today() >= self.cfg.max_trades_day:
            errs.append(f"limit trade'ow/dzien: {self.cfg.max_trades_day}")
        # kill-switch dziennej straty (tylko live — paper nie ma realnego PnL z gieldy)
        if self.cfg.is_live and equity > 0:
            day_pnl = self.rest.closed_pnl_today()
            if day_pnl < -(equity * self.cfg.daily_loss_halt_pct / 100.0):
                errs.append(f"KILL-SWITCH: strata dzienna ${day_pnl:.2f} "
                            f"> {self.cfg.daily_loss_halt_pct}% equity")
        return errs

    # ── egzekucja ─────────────────────────────────────────────────────────────
    def execute(self, symbol: str, side: str, *, sl_pct: float | None = None,
                tp_pct: float | None = None, signal: dict | None = None) -> dict:
        equity = self.rest.equity_usd()
        plan = self.build_plan(symbol, side, sl_pct=sl_pct, tp_pct=tp_pct, equity=equity)

        print(f"\n{'='*64}\nLIQSCALP {self.cfg.mode.upper()} | {plan.pretty()}\n{'='*64}")

        errs = self._preflight(plan, equity)
        if errs:
            for e in errs:
                print(f"  [BLOK] {e}")
            return {"ok": False, "blocked": errs, "plan": plan.__dict__}

        bybit_side = "Buy" if side == "long" else "Sell"
        trade_row = {
            "ts_open": int(time.time() * 1000), "mode": self.cfg.mode,
            "symbol": symbol, "side": side, "qty": plan.qty, "entry": plan.entry,
            "sl": plan.sl, "tp": plan.tp, "risk_usd": plan.risk_usd,
            "leverage": plan.leverage,
            "signal_json": json.dumps(signal) if signal else None,
        }

        if not self.cfg.is_live:
            # PAPER — zero realnych zlecen, zapisz zamiar
            tid = self.store.open_trade(trade_row)
            print(f"  [PAPER] zapisany trade #{tid} (limit maker @ ${plan.entry}, "
                  f"SL ${plan.sl}, TP ${plan.tp}) - brak realnego zlecenia")
            return {"ok": True, "mode": "paper", "trade_id": tid, "plan": plan.__dict__}

        # LIVE — realne zlecenie maker z dolaczonym SL+TP
        self.rest.set_leverage(symbol, plan.leverage)
        res = self.rest.create_order(
            symbol, bybit_side, str(plan.qty), str(plan.entry),
            order_type="Limit", tif="PostOnly",
            take_profit=str(plan.tp), stop_loss=str(plan.sl))
        ok = res.get("retCode") == 0
        print(f"  [LIVE] create_order retCode={res.get('retCode')} {res.get('retMsg')}")
        if ok:
            tid = self.store.open_trade(trade_row)
            print(f"  [LIVE] trade #{tid} zlozony (maker PostOnly, SL+TP dolaczone)")
            return {"ok": True, "mode": "live", "trade_id": tid,
                    "order": res.get("result"), "plan": plan.__dict__}
        return {"ok": False, "mode": "live", "error": res, "plan": plan.__dict__}


def main() -> None:
    ap = argparse.ArgumentParser(description="LiqScalp executor (test reczny)")
    ap.add_argument("mode", choices=["paper", "live"], help="paper = symulacja")
    ap.add_argument("symbol")
    ap.add_argument("side", choices=["long", "short"])
    ap.add_argument("--sl-pct", type=float, default=None)
    ap.add_argument("--tp-pct", type=float, default=None)
    args = ap.parse_args()

    cfg = load_config()
    # CLI mode nadpisuje .env tylko na ten test
    object.__setattr__(cfg, "mode", args.mode)
    if args.mode == "live":
        print("[UWAGA] tryb LIVE z CLI — realne zlecenie. Ctrl+C aby przerwac.")

    ex = Executor(cfg)
    out = ex.execute(args.symbol, args.side, sl_pct=args.sl_pct, tp_pct=args.tp_pct)
    print("\nWYNIK:", json.dumps({k: v for k, v in out.items() if k != "plan"}, indent=2))


if __name__ == "__main__":
    main()
