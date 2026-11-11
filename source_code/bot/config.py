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
    max_spread: Optional[float]  # dalam poin, sama seperti kolom Spread di MT5
    max_consecutive_loss: int
    trailing_mode: str
    mt5_path: Optional[str]


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
    )