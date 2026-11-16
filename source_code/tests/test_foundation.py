"""
test_foundation.py - Unit test untuk Tahap 3 (trailing, risk, state, logger, config).
"""
import dataclasses
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.logger import setup_logger, log_trade_csv
from bot.risk import (
    LossLock, in_trading_hours, check_spread_filter,
    check_daily_loss, check_drawdown,
)
from bot.state import BotState, load_state, save_state
from bot.trailing import calculate_trailing_stop


# ─────────────────────────────────────────────
# trailing.py
# ─────────────────────────────────────────────

def test_trailing_stop_no_rollback():
    """SL tidak pernah mundur."""
    entry = 2000.0
    r = 10.0

    # Profit 1.0R (belum mencapai first_trigger 1.5R) -> SL tetap SL0 (1990)
    level, sl = calculate_trailing_stop(1, entry, r, 1.0, 0, 1990.0)
    assert level == 0
    assert sl == 1990.0

    # Profit 1.5R -> Level 1 -> SL = 2000 + 1*10 = 2010.0
    level, sl = calculate_trailing_stop(1, entry, r, 1.5, 0, 1990.0)
    assert level == 1
    assert sl == 2010.0

    # Profit turun ke 1.2R -> SL TIDAK BOLEH MUNDUR (tetap 2010.0)
    level, sl = calculate_trailing_stop(1, entry, r, 1.2, 1, 2010.0)
    assert level == 1
    assert sl == 2010.0


def test_trailing_stop_sell():
    """SELL: SL berada di atas entry, naik ke bawah saat profit bertambah."""
    entry = 2000.0
    r = 10.0
    # Profit 1.5R -> Level 1 -> SL = 2000 - 1*10 = 1990.0 (lebih rendah dari SL awal 2010)
    level, sl = calculate_trailing_stop(-1, entry, r, 1.5, 0, 2010.0)
    assert level == 1
    assert sl == 1990.0

    # SL tidak boleh mundur (naik) untuk SELL
    level, sl = calculate_trailing_stop(-1, entry, r, 1.0, 1, 1990.0)
    assert sl == 1990.0


def test_trailing_multiple_levels():
    """Kenaikan level 2 dan 3."""
    entry = 2000.0
    r = 10.0

    level, sl = calculate_trailing_stop(1, entry, r, 2.5, 1, 2010.0)
    assert level == 2
    assert sl == pytest.approx(2020.0)

    level, sl = calculate_trailing_stop(1, entry, r, 3.5, 2, 2020.0)
    assert level == 3
    assert sl == pytest.approx(2030.0)


# ─────────────────────────────────────────────
# risk.py — LossLock
# ─────────────────────────────────────────────

def test_loss_lock_and_reset():
    """3 SL rugi berturut-turut mengunci; hari berikutnya otomatis buka."""
    lock = LossLock(max_consecutive_loss=3)
    today = date(2026, 11, 11)

    assert not lock.record_trade_result(True, today)   # Loss 1
    assert not lock.record_trade_result(True, today)   # Loss 2
    assert lock.record_trade_result(True, today)       # Loss 3 -> Locked!
    assert lock.is_locked(today)

    tomorrow = date(2026, 11, 12)
    assert not lock.is_locked(tomorrow)


def test_loss_lock_reset_by_profit():
    """SL profit1 mereset hitungan ke 0."""
    lock = LossLock(max_consecutive_loss=3)
    today = date(2026, 11, 11)

    lock.record_trade_result(True, today)   # Loss 1
    lock.record_trade_result(True, today)   # Loss 2
    lock.record_trade_result(False, today)  # Profit -> reset ke 0
    assert not lock.is_locked(today)
    assert lock.state.consecutive_losses == 0

    # Harus 3 lagi untuk terkunci
    lock.record_trade_result(True, today)
    lock.record_trade_result(True, today)
    assert not lock.is_locked(today)
    lock.record_trade_result(True, today)
    assert lock.is_locked(today)


def test_loss_lock_override():
    """Override manual mereset hitungan dan membuka kunci."""
    lock = LossLock(max_consecutive_loss=3)
    today = date(2026, 11, 11)

    lock.record_trade_result(True, today)
    lock.record_trade_result(True, today)
    lock.record_trade_result(True, today)
    assert lock.is_locked(today)

    lock.apply_override()
    assert not lock.is_locked(today)
    assert lock.state.consecutive_losses == 0
    assert lock.state.override_active is True


def test_in_trading_hours_normal():
    assert in_trading_hours(10, 9, 18)
    assert not in_trading_hours(18, 9, 18)   # batas akhir tidak termasuk
    assert not in_trading_hours(3, 9, 18)
    assert in_trading_hours(5, None, None)   # tanpa filter = selalu True


def test_in_trading_hours_wraparound():
    assert in_trading_hours(23, 22, 6)       # melewati tengah malam
    assert in_trading_hours(2, 22, 6)
    assert not in_trading_hours(12, 22, 6)


def test_check_spread_filter():
    assert check_spread_filter(30, None)        # tanpa filter
    assert check_spread_filter(30, 60)          # di bawah batas
    assert check_spread_filter(60, 60)          # tepat batas
    assert not check_spread_filter(61, 60)      # di atas batas


def test_check_daily_loss():
    assert check_daily_loss(0, 10000, None)          # filter mati
    assert check_daily_loss(0, 10000, 5.0)           # tidak ada rugi
    assert check_daily_loss(499, 10000, 5.0)         # 4.99% < 5%
    assert not check_daily_loss(500, 10000, 5.0)     # tepat 5% -> blokir
    assert not check_daily_loss(600, 10000, 5.0)     # di atas 5%
    assert check_daily_loss(99, 0, 5.0)              # balance 0 -> tidak aktif


def test_check_drawdown():
    assert check_drawdown(10000, 10000, None)        # filter mati
    assert check_drawdown(10000, 8500, 20.0)         # 15% < 20%
    assert not check_drawdown(10000, 8000, 20.0)     # tepat 20% -> blokir
    assert not check_drawdown(10000, 7000, 20.0)     # di atas 20%
    assert check_drawdown(0, 7000, 20.0)             # peak 0 -> tidak aktif


# ─────────────────────────────────────────────
# state.py
# ─────────────────────────────────────────────

def test_state_atomic_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        state = BotState(consecutive_losses=2, locked_date="2026-11-11")
        save_state(state, state_file)

        loaded = load_state(state_file)
        assert loaded.consecutive_losses == 2
        assert loaded.locked_date == "2026-11-11"


def test_state_load_ignores_unknown_keys():
    """Kunci tak dikenal di JSON tidak boleh menyebabkan error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        data = {
            "consecutive_losses": 1,
            "locked_date": None,
            "override_active": False,
            "open_position": None,
            "last_update": None,
            "kunci_tak_dikenal": "nilai_baru",   # kunci asing
            "versi_lama": 42,
        }
        state_file.write_text(json.dumps(data), encoding="utf-8")

        loaded = load_state(state_file)
        assert loaded.consecutive_losses == 1
        assert not hasattr(loaded, "kunci_tak_dikenal")


def test_state_load_corrupted_file_returns_clean():
    """File rusak harus menghasilkan state bersih, bukan crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        state_file.write_text("{ INVALID JSON !!!", encoding="utf-8")

        loaded = load_state(state_file)
        assert loaded.consecutive_losses == 0
        assert loaded.locked_date is None
        # File asli harus diubah jadi .bak
        assert (Path(tmpdir) / "state.bak").exists()


def test_state_load_non_dict_returns_clean():
    """JSON yang bukan dict (mis. list) harus menghasilkan state bersih."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        state_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        loaded = load_state(state_file)
        assert loaded.consecutive_losses == 0


def test_state_save_creates_intermediate_dirs():
    """Direktori data/ dibuat otomatis jika belum ada."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "subdir" / "nested" / "state.json"
        save_state(BotState(consecutive_losses=5), state_file)
        loaded = load_state(state_file)
        assert loaded.consecutive_losses == 5


# ─────────────────────────────────────────────
# logger.py
# ─────────────────────────────────────────────

def test_logger_creates_log_file():
    """setup_logger() harus membuat file log di LOGS_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "bot.log"
        from logging.handlers import RotatingFileHandler
        import logging

        logger = logging.getLogger("bot_trade_test")
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(log_file, maxBytes=1024, backupCount=1, encoding="utf-8")
        logger.addHandler(handler)
        logger.info("test pesan")
        handler.close()
        logger.removeHandler(handler)

        assert log_file.exists()
        assert "test pesan" in log_file.read_text(encoding="utf-8")


def test_log_trade_csv_creates_file_with_slippage():
    """log_trade_csv harus membuat file CSV dengan kolom slippage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trades_file = Path(tmpdir) / "trades.csv"
        trade = {
            "entry_time": "2026-11-01 10:00",
            "exit_time": "2026-11-01 11:00",
            "side": "BUY",
            "entry_price": 2000.0,
            "exit_price": 2010.0,
            "label": "SL profit1",
            "level": 1,
            "pnl_r": 1.0,
            "pnl_usd": 10.0,
            "spread_points": 32,
            # tanpa slippage -> harus diisi 0.0 otomatis
        }
        # Patch TRADES_CSV ke file sementara
        import bot.logger as logger_mod
        orig = logger_mod.TRADES_CSV
        logger_mod.TRADES_CSV = trades_file
        try:
            log_trade_csv(trade)
        finally:
            logger_mod.TRADES_CSV = orig

        content = trades_file.read_text(encoding="utf-8")
        assert "slippage" in content
        assert "0.0" in content


# ─────────────────────────────────────────────
# config.py
# ─────────────────────────────────────────────

def _make_env(tmp_path, overrides=None):
    """Buat .env sementara untuk pengujian config."""
    defaults = {
        "ACCOUNT": "12345678",
        "PASSWORD": "secret",
        "SERVER": "BrokerDemo",
    }
    if overrides:
        defaults.update(overrides)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{k}={v}" for k, v in defaults.items()),
        encoding="utf-8",
    )
    return env_file


def _run_config_with_env(tmp_path, overrides=None):
    """
    Jalankan load_config() dengan env sementara.
    Patch ENV_PATH DAN bersihkan variabel OS agar .env aktual tidak bocor ke tes.
    """
    import os
    from bot.config import load_config

    env_file = _make_env(tmp_path, overrides)
    # Kunci yang mungkin di-set dari .env aktual pengguna
    keys_to_clear = [
        "ACCOUNT", "PASSWORD", "SERVER", "SYMBOL", "LOT_SIZE", "MAX_SPREAD",
        "MAX_CONSECUTIVE_LOSS", "TRAILING_MODE", "MT5_PATH", "MODE", "ALLOW_REAL",
        "ATR_MULT", "ADX_MIN", "EMA_FAST", "EMA_SLOW", "RSI_PERIOD",
        "MAX_DAILY_LOSS_PERCENT", "MAX_DRAWDOWN_PERCENT",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys_to_clear}
    try:
        with patch("bot.config.ENV_PATH", env_file):
            return load_config()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_config_trailing_mode_invalid_rejected(tmp_path):
    """TRAILING_MODE yang bukan 'step' harus ditolak dengan pesan jelas."""
    from bot.config import ConfigError

    with pytest.raises(ConfigError) as exc_info:
        _run_config_with_env(tmp_path, {"TRAILING_MODE": "continuous"})
    assert "step" in str(exc_info.value)
    assert "continuous" in str(exc_info.value)


def test_config_mode_default_signal_only(tmp_path):
    """MODE default harus 'signal_only'."""
    cfg = _run_config_with_env(tmp_path)
    assert cfg.mode == "signal_only"


def test_config_mode_invalid_rejected(tmp_path):
    """MODE yang tidak dikenal harus ditolak."""
    from bot.config import ConfigError

    with pytest.raises(ConfigError) as exc_info:
        _run_config_with_env(tmp_path, {"MODE": "live_orders"})
    assert "MODE" in str(exc_info.value)


def test_config_allow_real_default_false(tmp_path):
    """ALLOW_REAL default harus False."""
    cfg = _run_config_with_env(tmp_path)
    assert cfg.allow_real is False
