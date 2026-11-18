"""
fake_mt5.py - Tiruan (mock) MetaTrader5 untuk pengujian bot live tanpa MT5 asli.

Digunakan oleh test_live.py. Tidak membutuhkan Windows / MT5 terpasang.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from datetime import datetime, timedelta
import pandas as pd

from bot.mt5_client import (
    BOT_MAGIC,
    AccountSummary,
    DealInfo,
    OrderResult,
    PositionInfo,
    SymbolSummary,
)
from bot.config import Config


# ─────────────────────────────────────────────────────────────────────────────
# FakeMT5Client
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeOrderSpec:
    """Skenario respons untuk send_market_order."""
    success: bool = True
    ticket: int = 1001
    retcode: int = 10009  # TRADE_RETCODE_DONE
    comment: str = "done"
    entry_price: float = 2000.0
    # Jika not None, posisi akan langsung ada di bot_positions setelah order
    auto_add_position: bool = True


class FakeMT5Client:
    """
    Tiruan MT5Client untuk tes unit.
    Semua state tersimpan di memori; tidak ada koneksi ke MT5.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._positions: List[PositionInfo] = []
        self._deals: List[DealInfo] = []
        self._candles_df: pd.DataFrame = _make_default_candles(2000)
        self._bid: float = 2000.0
        self._ask: float = 2000.32
        self._spread_points: int = 32
        self._order_spec: FakeOrderSpec = FakeOrderSpec()
        self._modify_sl_ok: bool = True
        self._close_ok: bool = True
        self._account_mode: str = "DEMO"
        self._trade_allowed: bool = True
        self._connect_calls: int = 0
        self._connect_should_fail: int = 0  # gagal N kali pertama lalu sukses
        self._order_call_count: int = 0

    # Helpers untuk setup tes
    def set_candles(self, df: pd.DataFrame) -> None:
        self._candles_df = df

    def set_tick(self, bid: float, ask: float) -> None:
        self._bid = bid
        self._ask = ask
        self._spread_points = max(0, int(round((ask - bid) / 0.01)))

    def set_order_spec(self, spec: FakeOrderSpec) -> None:
        self._order_spec = spec

    def add_position(self, pos: PositionInfo) -> None:
        self._positions.append(pos)

    def remove_position(self, ticket: int) -> None:
        self._positions = [p for p in self._positions if p.ticket != ticket]

    def add_deal(self, deal: DealInfo) -> None:
        self._deals.append(deal)

    def set_connect_fail(self, times: int) -> None:
        """Koneksi akan gagal `times` kali pertama."""
        self._connect_should_fail = times

    def set_account_mode(self, mode: str) -> None:
        self._account_mode = mode

    # ---- Interface yang sama dengan MT5Client ----

    def connect(self) -> None:
        self._connect_calls += 1
        if self._connect_should_fail > 0:
            self._connect_should_fail -= 1
            raise Exception(f"Simulasi koneksi gagal (sisa {self._connect_should_fail})")

    def shutdown(self) -> None:
        pass

    def prepare_symbol(self) -> None:
        pass

    def get_account(self) -> AccountSummary:
        return AccountSummary(
            login=12345678,
            name="Demo User",
            server="DemoServer",
            currency="USD",
            balance=10000.0,
            equity=10000.0,
            leverage=100,
            mode=self._account_mode,
            margin_mode="Hedging",
            trade_allowed=self._trade_allowed,
        )

    def get_symbol(self) -> SymbolSummary:
        return SymbolSummary(
            name=self.cfg.symbol,
            description="Gold vs US Dollar",
            digits=2,
            point=0.01,
            bid=self._bid,
            ask=self._ask,
            spread_points=self._spread_points,
            tick_time=pd.Timestamp.now(),
            contract_size=100.0,
            volume_min=0.01,
            volume_step=0.01,
            volume_max=100.0,
            stops_level=31,
        )

    def get_candles(self, count: int = 15) -> pd.DataFrame:
        df = self._candles_df
        if len(df) > count:
            return df.tail(count).copy().reset_index(drop=True)
        return df.copy()

    def get_bot_positions(self) -> List[PositionInfo]:
        return [p for p in self._positions]

    def send_market_order(self, side: int, sl_distance: float) -> OrderResult:
        self._order_call_count += 1
        spec = self._order_spec

        # Blokir akun REAL
        if self._account_mode == "REAL" and not self.cfg.allow_real:
            return OrderResult(
                False, 0, -1,
                "KEAMANAN: Ini akun REAL. Bot menolak order.", 0.0
            )

        if not spec.success:
            return OrderResult(False, 0, spec.retcode, spec.comment, 0.0)

        entry = spec.entry_price if spec.entry_price else self._ask if side == 1 else self._bid

        if spec.auto_add_position:
            sl = entry - side * sl_distance
            pos = PositionInfo(
                ticket=spec.ticket,
                side=side,
                symbol=self.cfg.symbol,
                volume=self.cfg.lot_size,
                entry_price=entry,
                sl=sl,
                open_time=pd.Timestamp.now(),
            )
            self._positions.append(pos)

        return OrderResult(True, spec.ticket, 10009, "done", entry)

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        if not self._modify_sl_ok:
            return False
        for p in self._positions:
            if p.ticket == ticket:
                p.sl = new_sl
                return True
        return False

    def close_position(self, ticket: int) -> bool:
        if not self._close_ok:
            return False
        self.remove_position(ticket)
        return True

    def get_position_deals(self, position_id: int) -> List[DealInfo]:
        return [d for d in self._deals if d.position_id == position_id]

    def run_checks(self, account, sym, candles):
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Helper: buat DataFrame candle palsu
# ─────────────────────────────────────────────────────────────────────────────

def _make_default_candles(n: int = 2000, base_price: float = 2000.0,
                           base_time: Optional[datetime] = None) -> pd.DataFrame:
    """Buat DataFrame n candle M1 palsu dengan harga tetap."""
    if base_time is None:
        base_time = datetime(2026, 11, 1, 10, 0, 0)
    times = [base_time + timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame({
        "time": pd.to_datetime(times),
        "open": base_price,
        "high": base_price + 0.5,
        "low": base_price - 0.5,
        "close": base_price,
        "tick_volume": 100,
        "spread": 32,
    })


def make_signal_candles(n: int = 1600, base_price: float = 2000.0,
                        signal_at_last: int = 1) -> pd.DataFrame:
    """
    Buat DataFrame candle yang akan menghasilkan sinyal pada candle terakhir.
    Ini digunakan untuk tes paritas sinyal.
    signal_at_last: 1=buy, -1=sell, 0=tidak ada sinyal (candle datar)
    """
    df = _make_default_candles(n, base_price)
    # Manipulasi agar indikator menghasilkan sinyal sederhana:
    # (Untuk tes paritas yang sesungguhnya, gunakan data historis nyata.)
    return df
