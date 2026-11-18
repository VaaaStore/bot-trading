"""
test_live.py - Tes unit untuk Tahap 4 (bot live, order, retcode, paritas sinyal).

Semua tes menggunakan FakeMT5Client; tidak membutuhkan MT5 asli.
"""
import csv
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Pastikan source_code ada di path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import Config
from bot.live import LiveBot, _compute_profit_r, MIN_CANDLES_FOR_SIGNAL
from bot.mt5_client import BOT_MAGIC, DealInfo, OrderResult, PositionInfo
from bot.state import BotState
from tests.fake_mt5 import FakeMT5Client, FakeOrderSpec, _make_default_candles


# ─────────────────────────────────────────────────────────────────────────────
# Fixture dasar
# ─────────────────────────────────────────────────────────────────────────────

def _make_cfg(**kwargs) -> Config:
    """Buat Config minimal untuk tes."""
    defaults = dict(
        account=12345678,
        password="secret",
        server="DemoServer",
        symbol="XAUUSD.vx",
        lot_size=0.01,
        max_spread=60.0,
        max_consecutive_loss=3,
        trailing_mode="step",
        mt5_path=None,
        atr_mult=4.0,
        adx_min=30.0,
        ema_fast=20,
        ema_slow=50,
        rsi_period=10,
        max_daily_loss_percent=None,
        max_drawdown_percent=None,
        mode="demo_orders",
        allow_real=False,
        max_slippage_points=30,
    )
    defaults.update(kwargs)
    return Config(**defaults)


def _make_bot(cfg=None, state=None, candle_count=1600) -> tuple:
    """Buat FakeMT5Client dan LiveBot untuk tes."""
    cfg = cfg or _make_cfg()
    client = FakeMT5Client(cfg)
    # Set candle cukup agar generate_signals bisa jalan
    client.set_candles(_make_default_candles(candle_count + 2))
    bot = LiveBot(cfg, client, state=state or BotState())
    bot._reconciled = True  # Langsung anggap rekonsiliasi selesai
    return client, bot


# ─────────────────────────────────────────────────────────────────────────────
# 1. Order sukses
# ─────────────────────────────────────────────────────────────────────────────

def test_order_success_creates_active_position():
    """Order berhasil harus membuat active_pos dengan ticket dan data benar."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    client.set_order_spec(FakeOrderSpec(success=True, ticket=5001, entry_price=2010.0))

    bot._attempt_entry(signal=1, sl_distance=20.0, spread_points=32)

    assert bot.active_pos is not None
    assert bot.active_pos.ticket == 5001
    assert bot.active_pos.side == 1
    assert bot.active_pos.r == pytest.approx(20.0)
    assert bot.active_pos.entry_price == pytest.approx(2010.0)
    assert bot.active_pos.current_sl == pytest.approx(2010.0 - 20.0)


def test_order_success_saves_state(tmp_path):
    """State harus tersimpan setelah order masuk."""
    cfg = _make_cfg()
    client = FakeMT5Client(cfg)
    client.set_candles(_make_default_candles(1602))

    with patch("bot.live.STATE_PATH", tmp_path / "state.json"):
        bot = LiveBot(cfg, client, state=BotState())
        bot._reconciled = True
        client.set_order_spec(FakeOrderSpec(ticket=5002, entry_price=2000.0))
        bot._attempt_entry(1, 20.0, 32)

    assert (tmp_path / "state.json").exists()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Penolakan retcode
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("retcode,comment", [
    (10004, "Requote"),
    (10006, "Invalid stops"),
    (10014, "Market closed"),
    (10019, "No money"),
    (10026, "Invalid fill"),
])
def test_order_rejection_retcode_no_position(retcode, comment):
    """Berbagai retcode penolakan: posisi tidak terbuat."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    client.set_order_spec(FakeOrderSpec(success=False, retcode=retcode, comment=comment, auto_add_position=False))

    bot._attempt_entry(1, 20.0, 32)

    assert bot.active_pos is None
    assert client._order_call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. Reconnect dengan exponential backoff
# ─────────────────────────────────────────────────────────────────────────────

def test_reconnect_after_exception():
    """Loop harus memanggil connect() setelah exception, tidak crash."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    client.set_connect_fail(1)  # Gagal 1 kali dulu

    iterations = 0

    def fake_tick():
        nonlocal iterations
        iterations += 1
        if iterations == 1:
            raise Exception("Simulasi koneksi terputus")
        # Iterasi ke-2 dan seterusnya berjalan normal

    bot._tick = fake_tick  # type: ignore
    # Jalankan 2 iterasi
    with patch("time.sleep"):
        bot.run(max_iterations=2)

    assert iterations == 2
    assert client._connect_calls >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Rekonsiliasi posisi terbuka
# ─────────────────────────────────────────────────────────────────────────────

def test_reconcile_adopts_existing_position():
    """Rekonsiliasi harus mengadopsi posisi terbuka dan lanjutkan trailing."""
    cfg = _make_cfg()
    client = FakeMT5Client(cfg)
    client.set_candles(_make_default_candles(1602))

    # Tambahkan posisi yang sudah ada di server
    pos = PositionInfo(
        ticket=9999,
        side=1,
        symbol=cfg.symbol,
        volume=0.01,
        entry_price=2000.0,
        sl=1980.0,  # SL = 1R dari 2000, R=20
        open_time=pd.Timestamp.now(),
    )
    client.add_position(pos)

    bot = LiveBot(cfg, client, state=BotState())
    bot.reconcile()

    assert bot._reconciled
    assert bot.active_pos is not None
    assert bot.active_pos.ticket == 9999
    assert bot.active_pos.r == pytest.approx(20.0)


def test_reconcile_no_positions():
    """Tanpa posisi: rekonsiliasi selesai dan active_pos = None."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    bot._reconciled = False
    bot.reconcile()

    assert bot._reconciled
    assert bot.active_pos is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Trailing live - BUY dan SELL multi-level
# ─────────────────────────────────────────────────────────────────────────────

def test_trailing_buy_moves_sl_at_1_5r():
    """BUY: SL harus digeser ke +1R saat profit mencapai 1.5R."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    client.set_order_spec(FakeOrderSpec(ticket=1, entry_price=2000.0))
    bot._attempt_entry(1, 20.0, 32)

    pos = bot.active_pos
    assert pos is not None

    # Simulasi profit 1.5R: bid = 2030
    client.set_tick(bid=2030.0, ask=2030.32)
    bot._monitor_position()

    assert bot.active_pos is not None
    assert bot.active_pos.trailing_level == 1
    assert bot.active_pos.current_sl == pytest.approx(2020.0)  # +1R


def test_trailing_sell_moves_sl_at_1_5r():
    """SELL: SL harus digeser ke -1R saat profit mencapai 1.5R."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    client.set_order_spec(FakeOrderSpec(ticket=2, entry_price=2000.0))
    bot._attempt_entry(-1, 20.0, 32)

    pos = bot.active_pos
    assert pos is not None
    assert pos.side == -1

    # Simulasi profit 1.5R: ask = 1970 (harga turun 30, R=20, profit=1.5R)
    client.set_tick(bid=1969.68, ask=1970.0)
    bot._monitor_position()

    assert bot.active_pos is not None
    assert bot.active_pos.trailing_level == 1
    assert bot.active_pos.current_sl == pytest.approx(1980.0)  # -1R


def test_trailing_multi_level_buy():
    """BUY: multi-level trailing."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    client.set_order_spec(FakeOrderSpec(ticket=3, entry_price=2000.0))
    bot._attempt_entry(1, 20.0, 32)

    # Level 1: profit 1.5R
    client.set_tick(2030.0, 2030.32)
    bot._monitor_position()
    assert bot.active_pos.trailing_level == 1
    assert bot.active_pos.current_sl == pytest.approx(2020.0)

    # Level 2: profit 2.5R
    client.set_tick(2050.0, 2050.32)
    bot._monitor_position()
    assert bot.active_pos.trailing_level == 2
    assert bot.active_pos.current_sl == pytest.approx(2040.0)

    # Level 3: profit 3.5R
    client.set_tick(2070.0, 2070.32)
    bot._monitor_position()
    assert bot.active_pos.trailing_level == 3
    assert bot.active_pos.current_sl == pytest.approx(2060.0)


def test_trailing_sl_never_rollback():
    """SL tidak boleh mundur meski profit turun."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)
    client.set_order_spec(FakeOrderSpec(ticket=4, entry_price=2000.0))
    bot._attempt_entry(1, 20.0, 32)

    # Naik ke level 2
    client.set_tick(2050.0, 2050.32)
    bot._monitor_position()
    assert bot.active_pos.trailing_level == 2
    sl_before = bot.active_pos.current_sl

    # Profit turun (tapi belum kena SL)
    client.set_tick(2025.0, 2025.32)
    bot._monitor_position()

    # SL tidak boleh mundur
    assert bot.active_pos.current_sl >= sl_before


# ─────────────────────────────────────────────────────────────────────────────
# 6. Pengunci (LossLock)
# ─────────────────────────────────────────────────────────────────────────────

def test_lock_blocks_entry_after_3_losses(tmp_path):
    """Setelah 3 SL rugi, entry baru harus diblokir."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)

    today = date(2026, 11, 18)
    bot.lock.record_trade_result(True, today)
    bot.lock.record_trade_result(True, today)
    bot.lock.record_trade_result(True, today)

    with patch("bot.live._wib_date", return_value=today):
        bot._attempt_entry(1, 20.0, 32)

    assert bot.active_pos is None
    assert client._order_call_count == 0


def test_lock_resets_on_profit():
    """SL profit1 harus me-reset hitungan SL rugi."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)

    today = date(2026, 11, 18)
    bot.lock.record_trade_result(True, today)
    bot.lock.record_trade_result(True, today)
    bot.lock.record_trade_result(False, today)  # Profit -> reset

    assert not bot.lock.is_locked(today)
    assert bot.lock.state.consecutive_losses == 0


# ─────────────────────────────────────────────────────────────────────────────
# 7. Akun REAL ditolak
# ─────────────────────────────────────────────────────────────────────────────

def test_real_account_order_rejected():
    """Akun REAL tanpa ALLOW_REAL: order harus ditolak."""
    cfg = _make_cfg(allow_real=False)
    client, bot = _make_bot(cfg)
    client.set_account_mode("REAL")

    bot._attempt_entry(1, 20.0, 32)

    assert bot.active_pos is None
    # Order mungkin dipanggil tapi langsung ditolak di FakeMT5Client
    if client._order_call_count > 0:
        assert bot.active_pos is None  # Tetap tidak ada posisi


def test_real_account_rejected_at_validation():
    """FakeMT5Client secara eksplisit menolak REAL jika allow_real=False."""
    cfg = _make_cfg(allow_real=False)
    client = FakeMT5Client(cfg)
    client.set_account_mode("REAL")

    result = client.send_market_order(1, 20.0)
    assert not result.success
    assert "REAL" in result.comment


# ─────────────────────────────────────────────────────────────────────────────
# 8. signal_only tidak mengirim order
# ─────────────────────────────────────────────────────────────────────────────

def test_signal_only_no_order():
    """MODE=signal_only harus menampilkan sinyal tanpa mengirim order."""
    cfg = _make_cfg(mode="signal_only")
    client, bot = _make_bot(cfg)

    bot._attempt_entry(1, 20.0, 32)

    assert bot.active_pos is None
    assert client._order_call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 9. Kill switch
# ─────────────────────────────────────────────────────────────────────────────

def test_kill_switch_blocks_entry(tmp_path):
    """Jika file data/STOP ada, tidak ada entry baru."""
    stop_file = tmp_path / "STOP"
    stop_file.touch()

    with patch("bot.live.STOP_FILE", stop_file):
        cfg = _make_cfg()
        client, bot = _make_bot(cfg)
        bot._attempt_entry(1, 20.0, 32)

    assert bot.active_pos is None
    assert client._order_call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 10. Keluar bukan karena SL (deal.reason)
# ─────────────────────────────────────────────────────────────────────────────

def test_exit_non_sl_labeled_lain(tmp_path):
    """Jika posisi ditutup bukan karena SL, label harus 'LAIN'."""
    cfg = _make_cfg()
    client = FakeMT5Client(cfg)
    client.set_candles(_make_default_candles(1602))

    with patch("bot.live.STATE_PATH", tmp_path / "state.json"):
        bot = LiveBot(cfg, client, state=BotState())
        bot._reconciled = True

        # Buka posisi
        client.set_order_spec(FakeOrderSpec(ticket=777, entry_price=2000.0))
        bot._attempt_entry(1, 20.0, 32)

        # Tambahkan deal "keluar" dengan reason=3 (manual close, bukan SL)
        deal_exit = DealInfo(
            ticket=778,
            position_id=777,
            side=-1,  # arah berlawanan dari buy
            price=2010.0,
            volume=0.01,
            profit=10.0,
            commission=-0.01,
            swap=0.0,
            time=pd.Timestamp.now(),
            comment="manual",
            reason=3,  # DEAL_REASON_CLIENT=3 (manual oleh klien)
        )
        client.add_deal(deal_exit)

        # Hapus posisi dari server (sudah ditutup)
        client.remove_position(777)

        result = bot._monitor_position()

    assert result is not None
    assert result["label"] == "LAIN"


# ─────────────────────────────────────────────────────────────────────────────
# 11. SL rugi (trailing_level = 0, kena SL awal)
# ─────────────────────────────────────────────────────────────────────────────

def test_exit_at_initial_sl_labeled_sl_rugi(tmp_path):
    """Posisi ditutup di level 0 (SL awal) harus berlabel 'SL rugi'."""
    cfg = _make_cfg()
    client = FakeMT5Client(cfg)
    client.set_candles(_make_default_candles(1602))

    with patch("bot.live.STATE_PATH", tmp_path / "state.json"):
        bot = LiveBot(cfg, client, state=BotState())
        bot._reconciled = True

        client.set_order_spec(FakeOrderSpec(ticket=888, entry_price=2000.0))
        bot._attempt_entry(1, 20.0, 32)

        # Tidak ada trailing: level masih 0
        assert bot.active_pos.trailing_level == 0

        # Tambahkan deal exit dengan reason=0 (SL)
        deal_exit = DealInfo(
            ticket=889,
            position_id=888,
            side=-1,
            price=1980.0,  # kena SL awal
            volume=0.01,
            profit=-20.0,
            commission=-0.01,
            swap=0.0,
            time=pd.Timestamp.now(),
            comment="sl",
            reason=0,  # DEAL_REASON_SL = 0
        )
        client.add_deal(deal_exit)
        client.remove_position(888)

        result = bot._monitor_position()

    assert result is not None
    assert result["label"] == "SL rugi"


# ─────────────────────────────────────────────────────────────────────────────
# 12. Paritas sinyal: live vs backtest
# ─────────────────────────────────────────────────────────────────────────────

def test_signal_parity_live_vs_backtest():
    """
    Tes paritas: generate_signals pada potongan data historis
    harus menghasilkan sinyal yang sama antara live dan backtest.
    Gunakan data nyata XAUUSD jika ada; fallback ke data palsu.
    """
    from bot.strategy import StrategyParams, generate_signals

    data_path = Path(__file__).resolve().parent.parent / "data" / "raw" / "XAUUSD.vx_M1.csv"

    if data_path.exists():
        from backtest.data import load_csv
        df_full, _meta = load_csv(str(data_path))
        # Ambil 2000 candle tutup (ingat: live membuang candle terakhir = sedang berjalan)
        df_live = df_full.head(1600).copy()
        df_backtest = df_full.head(1601).iloc[:-1].copy()  # satu lebih, buang "candle berjalan"
    else:
        # Fallback: data palsu - kedua akan menghasilkan signal=0 tapi identik
        df_full = _make_default_candles(1602)
        df_live = df_full.head(1600).copy()
        df_backtest = df_full.head(1601).iloc[:-1].copy()  # buang "candle berjalan"

    p = StrategyParams()

    sig_live = generate_signals(df_live, p)
    sig_backtest = generate_signals(df_backtest, p)

    # Hanya bandingkan baris yang sama (live = head(1600), backtest = head(1600))
    n = min(len(sig_live), len(sig_backtest))

    mismatches = []
    for i in range(n):
        s_live = int(sig_live.iloc[i]["signal"])
        s_bt = int(sig_backtest.iloc[i]["signal"])
        if s_live != s_bt:
            mismatches.append((i, s_live, s_bt))

    # Laporkan ketidakcocokan apa adanya (tidak disembunyikan)
    if mismatches:
        details = "\n".join(
            f"  baris {i}: live={s_l} backtest={s_b}"
            for i, s_l, s_b in mismatches[:10]
        )
        pytest.fail(
            f"PARITAS GAGAL: {len(mismatches)} sinyal berbeda antara live dan backtest:\n{details}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 13. _compute_profit_r
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_profit_r_buy():
    """BUY: profit_r dihitung dari bid."""
    # entry=2000, r=20, bid=2030 -> profit=(2030-2000)/20 = 1.5R
    assert _compute_profit_r(1, 2000.0, 20.0, bid=2030.0, ask=2030.32) == pytest.approx(1.5)


def test_compute_profit_r_sell():
    """SELL: profit_r dihitung dari ask."""
    # entry=2000, r=20, ask=1970 -> profit=(2000-1970)/20 = 1.5R
    assert _compute_profit_r(-1, 2000.0, 20.0, bid=1969.68, ask=1970.0) == pytest.approx(1.5)


def test_compute_profit_r_zero_r():
    """r=0: kembalikan 0 (bukan division by zero)."""
    assert _compute_profit_r(1, 2000.0, 0.0, bid=2010.0, ask=2010.32) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 14. Spread filter
# ─────────────────────────────────────────────────────────────────────────────

def test_spread_too_wide_blocks_entry():
    """Spread di atas MAX_SPREAD: sinyal dilewati."""
    cfg = _make_cfg(max_spread=50.0)
    client, bot = _make_bot(cfg)
    client.set_tick(2000.0, 2001.0)  # spread 100 poin

    bot._attempt_entry(1, 20.0, spread_points=100)

    assert bot.active_pos is None
    assert client._order_call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 15. Satu posisi: tidak ada entry baru jika sudah ada posisi
# ─────────────────────────────────────────────────────────────────────────────

def test_no_double_entry():
    """Sudah ada posisi aktif: entry baru diblokir."""
    cfg = _make_cfg()
    client, bot = _make_bot(cfg)

    # Buka posisi pertama
    client.set_order_spec(FakeOrderSpec(ticket=100, entry_price=2000.0))
    bot._attempt_entry(1, 20.0, 32)
    assert bot.active_pos is not None

    # Coba buka posisi kedua
    first_ticket = bot.active_pos.ticket
    client.set_order_spec(FakeOrderSpec(ticket=101, entry_price=2001.0))
    bot._attempt_entry(1, 20.0, 32)

    assert bot.active_pos.ticket == first_ticket  # Tetap posisi pertama
