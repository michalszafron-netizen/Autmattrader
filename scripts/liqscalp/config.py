"""config.py — ustawienia + TWARDE limity ryzyka bota liquidation-scalp.

Czytane z .env (prefix LIQSCALP_). Domyslnie PAPER. Limity ryzyka sa egzekwowane
w kodzie executora — nie da sie ich obejsc samym .env (np. risk_pct jest twardo
przyciety do 2.0% zgodnie z zasada projektu).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")


def _f(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _i(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# ── TWARDE limity (zasada projektu — nieprzekraczalne) ────────────────────────
HARD_MAX_RISK_PCT = 2.0          # max % equity na pojedynczy trade
HARD_DAILY_LOSS_HALT_PCT = 3.0   # kill-switch: strata dzienna > 3% -> stop


@dataclass(frozen=True)
class Config:
    mode: str                     # "paper" | "live"
    risk_pct: float               # % equity na trade (przyciety do HARD_MAX_RISK_PCT)
    leverage: int
    max_positions: int
    max_trades_day: int
    tp_pct: float                 # cel TP jako % ruchu ceny (placeholder — stroi Faza 0)
    sl_pct: float                 # SL jako % ruchu ceny (placeholder — stroi Faza 0)
    daily_loss_halt_pct: float
    category: str = "linear"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


def load_config() -> Config:
    mode = os.getenv("LIQSCALP_MODE", "paper").strip().lower()
    if mode not in ("paper", "live"):
        mode = "paper"

    risk = min(_f("LIQSCALP_RISK_PCT", 1.0), HARD_MAX_RISK_PCT)  # twardy cap
    halt = min(_f("LIQSCALP_DAILY_LOSS_HALT_PCT", HARD_DAILY_LOSS_HALT_PCT),
               HARD_DAILY_LOSS_HALT_PCT)

    return Config(
        mode=mode,
        risk_pct=risk,
        leverage=_i("LIQSCALP_LEVERAGE", 5),
        max_positions=_i("LIQSCALP_MAX_POSITIONS", 2),
        max_trades_day=_i("LIQSCALP_MAX_TRADES_DAY", 50),
        tp_pct=_f("LIQSCALP_TP_PCT", 0.40),
        sl_pct=_f("LIQSCALP_SL_PCT", 0.50),
        daily_loss_halt_pct=halt,
    )


if __name__ == "__main__":
    c = load_config()
    print("LiqScalp config:")
    for k, v in c.__dict__.items():
        print(f"  {k:20s} = {v}")
    print(f"  is_live              = {c.is_live}")
    print(f"\n  [hard caps] risk<={HARD_MAX_RISK_PCT}%  daily_halt<={HARD_DAILY_LOSS_HALT_PCT}%")
