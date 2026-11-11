"""
logger.py - Logging terstruktur dengan rotasi file dan pencatatan transaksi CSV.
"""
import csv
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "bot.log"
TRADES_CSV = LOGS_DIR / "trades.csv"


def setup_logger() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bot_trade")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def log_trade_csv(trade_data: dict) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = TRADES_CSV.exists()
    headers = [
        "entry_time", "exit_time", "side", "entry_price", "exit_price",
        "label", "level", "pnl_r", "pnl_usd", "spread_points"
    ]
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_data)
