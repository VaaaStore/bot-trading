"""
risk.py - Kelas dan fungsi murni pengunci kerugian (LossLock) dan filter risiko/jam.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class LossLockState:
    consecutive_losses: int = 0
    locked_date: Optional[date] = None
    override_active: bool = False


class LossLock:
    def __init__(self, max_consecutive_loss: int = 3):
        self.max_consecutive_loss = max_consecutive_loss
        self.state = LossLockState()

    def record_trade_result(self, is_loss_sl: bool, trade_date: date) -> bool:
        """
        Mencatat hasil trade. Jika SL rugi berturut-turut >= max, tandai terkunci untuk trade_date.
        Return True jika sistem terkunci.
        """
        if self.is_locked(trade_date):
            return True

        if is_loss_sl:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= self.max_consecutive_loss:
                self.state.locked_date = trade_date
                self.state.override_active = False
                return True
        else:
            self.state.consecutive_losses = 0

        return False

    def is_locked(self, current_date: date) -> bool:
        """
        Cek apakah sistem sedang terkunci pada tanggal tertentu.
        Jika tanggal berganti, kunci ter-reset otomatis.
        """
        if self.state.locked_date is not None:
            if current_date > self.state.locked_date:
                # Pergantian hari: reset kunci
                self.state.locked_date = None
                self.state.consecutive_losses = 0
                self.state.override_active = False
                return False
            elif current_date == self.state.locked_date:
                return not self.state.override_active

        return False

    def apply_override(self) -> None:
        """Mengaktifkan override manual pengguna (reset ke 0 jatah)."""
        self.state.consecutive_losses = 0
        self.state.override_active = True


def in_trading_hours(hour: int, start: Optional[int], end: Optional[int]) -> bool:
    """True kalau jam server berada di jendela [start, end). Jendela boleh melewati tengah malam."""
    if start is None or end is None:
        return True
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def check_spread_filter(spread_points: float, max_spread: Optional[float]) -> bool:
    """True kalau spread di bawah atau sama dengan max_spread (atau max_spread mati/None)."""
    if max_spread is None:
        return True
    return spread_points <= max_spread

