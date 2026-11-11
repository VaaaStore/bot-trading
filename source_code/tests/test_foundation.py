"""
test_foundation.py - Unit test untuk Tahap 3 (trailing, risk, state, logger).
"""
import tempfile
from datetime import date
from pathlib import Path

from bot.logger import setup_logger
from bot.risk import LossLock
from bot.state import BotState, load_state, save_state
from bot.trailing import calculate_trailing_stop


def test_trailing_stop_no_rollback():
    # Test Buy position trailing
    entry = 2000.0
    r = 10.0
    
    # 1. Profit 1.0R (belum mencapai first_trigger 1.5R) -> SL tetap SL0 (1990)
    level, sl = calculate_trailing_stop(1, entry, r, 1.0, 0, 1990.0)
    assert level == 0
    assert sl == 1990.0

    # 2. Profit 1.5R -> Level 1 -> SL = 2000 + 1*10 = 2010.0
    level, sl = calculate_trailing_stop(1, entry, r, 1.5, 0, 1990.0)
    assert level == 1
    assert sl == 2010.0

    # 3. Profit turun ke 1.2R -> SL TIDAK BOLEH MUNDUR (tetap 2010.0)
    level, sl = calculate_trailing_stop(1, entry, r, 1.2, 1, 2010.0)
    assert level == 1
    assert sl == 2010.0


def test_loss_lock_and_reset():
    lock = LossLock(max_consecutive_loss=3)
    today = date(2026, 11, 11)
    
    assert not lock.record_trade_result(True, today)   # Loss 1
    assert not lock.record_trade_result(True, today)   # Loss 2
    assert lock.record_trade_result(True, today)       # Loss 3 -> Locked!
    assert lock.is_locked(today)

    # Hari berikutnya -> otomatis unlock
    tomorrow = date(2026, 11, 12)
    assert not lock.is_locked(tomorrow)


def test_state_atomic_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "state.json"
        state = BotState(consecutive_losses=2, locked_date="2026-11-11")
        save_state(state, state_file)
        
        loaded = load_state(state_file)
        assert loaded.consecutive_losses == 2
        assert loaded.locked_date == "2026-11-11"
