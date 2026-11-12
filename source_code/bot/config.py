"""
config.py - membaca pengaturan dari file .env
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

TRAILING_MODES = ("step", "continuous", "atr")


class ConfigError(Exception):
    """Dilempar kalau isi .env salah atau kurang."""


@dataclass(frozen=True)
class Config:
    account: int
    password: str
    server: str
    symbol: str
    lot_size: float
    max_spread: Optional[float]
    max_consecutive_loss: int
    trailing_mode: str
    mt5_path: Optional[str]
    atr_mult: float
    adx_min: float
    ema_fast: int
    ema_slow: int
    rsi_period: int
    max_daily_loss_percent: Optional[float]
    max_drawdown_percent: Optional[float]


def _get(name: str) -> Optional[str]:
    """Ambil nilai env; string kosong dianggap tidak diisi."""
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def load_config() -> Config:
    if not ENV_PATH.exists():
        raise ConfigError(
            f"File .env tidak ditemukan di:\n  {ENV_PATH}\n"
            "Salin .env.example menjadi .env lalu isi datanya."
        )
    load_dotenv(ENV_PATH, override=True)

    problems: List[str] = []

    # --- wajib diisi ---
    account_raw = _get("ACCOUNT")
    password = _get("PASSWORD")
    server = _get("SERVER")
    symbol = _get("SYMBOL") or "XAUUSD"

    account = 0
    if not account_raw:
        problems.append("ACCOUNT belum diisi")
    else:
        try:
            account = int(account_raw)
        except ValueError:
            problems.append("ACCOUNT harus berupa angka saja")
    if not password:
        problems.append("PASSWORD belum diisi")
    if not server:
        problems.append("SERVER belum diisi")

    # --- angka ---
    lot_size = 0.01
    lot_raw = _get("LOT_SIZE")
    if lot_raw:
        try:
            lot_size = float(lot_raw)
            if lot_size <= 0:
                problems.append("LOT_SIZE harus lebih dari 0")
        except ValueError:
            problems.append("LOT_SIZE harus berupa angka, contoh 0.01")

    max_spread: Optional[float] = None
    spread_raw = _get("MAX_SPREAD")
    if spread_raw:
        try:
            max_spread = float(spread_raw)
            if max_spread <= 0:
                problems.append("MAX_SPREAD harus lebih dari 0 (atau kosongkan)")
        except ValueError:
            problems.append("MAX_SPREAD harus berupa angka (atau kosongkan)")

    max_loss = 3
    loss_raw = _get("MAX_CONSECUTIVE_LOSS")
    if loss_raw:
        try:
            max_loss = int(loss_raw)
            if max_loss < 1:
                problems.append("MAX_CONSECUTIVE_LOSS minimal 1")
        except ValueError:
            problems.append("MAX_CONSECUTIVE_LOSS harus berupa bilangan bulat")

    trailing_mode = (_get("TRAILING_MODE") or "step").lower()
    if trailing_mode not in TRAILING_MODES:
        problems.append(f"TRAILING_MODE harus salah satu dari: {', '.join(TRAILING_MODES)}")
    # --- Parameter strategi & risiko (default kandidat: ATR 4, ADX 30) ---
    atr_mult = 4.0
    atr_raw = _get("ATR_MULT")
    if atr_raw:
        try:
            atr_mult = float(atr_raw)
            if atr_mult <= 0:
                problems.append("ATR_MULT harus lebih dari 0")
        except ValueError:
            problems.append("ATR_MULT harus berupa angka")

    adx_min = 30.0
    adx_raw = _get("ADX_MIN")
    if adx_raw:
        try:
            adx_min = float(adx_raw)
            if adx_min < 0:
                problems.append("ADX_MIN minimal 0")
        except ValueError:
            problems.append("ADX_MIN harus berupa angka")

    ema_fast = 20
    ef_raw = _get("EMA_FAST")
    if ef_raw:
        try:
            ema_fast = int(ef_raw)
            if ema_fast < 1:
                problems.append("EMA_FAST minimal 1")
        except ValueError:
            problems.append("EMA_FAST harus berupa bilangan bulat")

    ema_slow = 50
    es_raw = _get("EMA_SLOW")
    if es_raw:
        try:
            ema_slow = int(es_raw)
            if ema_slow < 1:
                problems.append("EMA_SLOW minimal 1")
        except ValueError:
            problems.append("EMA_SLOW harus berupa bilangan bulat")

    rsi_period = 10
    rsi_raw = _get("RSI_PERIOD")
    if rsi_raw:
        try:
            rsi_period = int(rsi_raw)
            if rsi_period < 1:
                problems.append("RSI_PERIOD minimal 1")
        except ValueError:
            problems.append("RSI_PERIOD harus berupa bilangan bulat")

    max_daily_loss_percent: Optional[float] = None
    mdl_raw = _get("MAX_DAILY_LOSS_PERCENT")
    if mdl_raw:
        try:
            max_daily_loss_percent = float(mdl_raw)
            if max_daily_loss_percent <= 0:
                problems.append("MAX_DAILY_LOSS_PERCENT harus lebih dari 0")
        except ValueError:
            problems.append("MAX_DAILY_LOSS_PERCENT harus berupa angka")

    max_drawdown_percent: Optional[float] = None
    mdd_raw = _get("MAX_DRAWDOWN_PERCENT")
    if mdd_raw:
        try:
            max_drawdown_percent = float(mdd_raw)
            if max_drawdown_percent <= 0:
                problems.append("MAX_DRAWDOWN_PERCENT harus lebih dari 0")
        except ValueError:
            problems.append("MAX_DRAWDOWN_PERCENT harus berupa angka")


    if problems:
        raise ConfigError("Isi .env belum benar:\n  - " + "\n  - ".join(problems))

    return Config(
        account=account,
        password=password,  # type: ignore[arg-type]
        server=server,  # type: ignore[arg-type]
        symbol=symbol,
        lot_size=lot_size,
        max_spread=max_spread,
        max_consecutive_loss=max_loss,
        trailing_mode=trailing_mode,
        mt5_path=_get("MT5_PATH"),
        atr_mult=atr_mult,
        adx_min=adx_min,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_period=rsi_period,
        max_daily_loss_percent=max_daily_loss_percent,
        max_drawdown_percent=max_drawdown_percent,
    )