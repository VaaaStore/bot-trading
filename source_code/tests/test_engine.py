import pandas as pd
import pytest

from backtest.engine import BacktestConfig, run_backtest

CFG = BacktestConfig(point=0.01, contract_size=100, lot=0.01)


def make_df(rows, times=None):
    """rows: (open, high, low, close, spread_poin, signal, sl_distance)"""
    cols = ["open", "high", "low", "close", "spread", "signal", "sl_distance"]
    df = pd.DataFrame(rows, columns=cols)
    if times is None:
        times = pd.date_range("2026-01-05 10:00", periods=len(rows), freq="min")
    df.insert(0, "time", times)
    return df


def bar(o=100, h=100.5, l=99.5, c=100, spread=0, sig=0, r=10):
    return (o, h, l, c, spread, sig, r)


def test_buy_hits_initial_sl_is_minus_1r():
    df = make_df([bar(sig=1), bar(), bar(o=100, h=101, l=85, c=88)])
    t = run_backtest(df, CFG).trades
    assert len(t) == 1
    assert t.loc[0, "label"] == "SL rugi"
    assert t.loc[0, "pnl_r"] == pytest.approx(-1.0)


def test_buy_reaches_1_5r_then_stops_at_profit1():
    df = make_df([
        bar(sig=1),
        bar(o=100, h=104, l=99, c=103),
        bar(o=103, h=115, l=102, c=114),   # profit 1.5R -> SL pindah ke +1R (110)
        bar(o=114, h=114, l=109, c=110),   # kena SL profit1
    ])
    t = run_backtest(df, CFG).trades
    assert t.loc[0, "label"] == "SL profit1"
    assert t.loc[0, "pnl_r"] == pytest.approx(1.0)


def test_buy_reaches_2_5r_then_stops_at_profit2():
    df = make_df([
        bar(sig=1),
        bar(o=100, h=104, l=99, c=103),
        bar(o=103, h=125, l=102, c=124),   # profit 2.5R -> SL ke +2R (120)
        bar(o=124, h=124, l=119, c=120),
    ])
    t = run_backtest(df, CFG).trades
    assert t.loc[0, "label"] == "SL profit2"
    assert t.loc[0, "pnl_r"] == pytest.approx(2.0)


def test_sl_never_moves_backwards():
    df = make_df([
        bar(sig=1),
        bar(o=100, h=125, l=99, c=124),    # SL ke +2R (120)
        bar(o=124, h=116, l=115, c=116),   # harga turun ke bawah 120 -> kena SL profit2 (SL tidak mundur ke awal)
    ])
    t = run_backtest(df, CFG).trades
    assert t.loc[0, "label"] == "SL profit2"


def test_same_bar_adverse_move_checked_before_trailing():
    # candle yang sama menyentuh +2,5R dan jatuh ke bawah SL awal:
    # asumsi konservatif -> SL awal kena lebih dulu
    df = make_df([bar(sig=1), bar(o=100, h=125, l=85, c=100)])
    t = run_backtest(df, CFG).trades
    assert t.loc[0, "label"] == "SL rugi"


def test_gap_through_sl_exits_at_open():
    df = make_df([bar(sig=1), bar(), bar(o=80, h=82, l=78, c=79)])
    t = run_backtest(df, CFG).trades
    assert t.loc[0, "pnl_r"] == pytest.approx(-2.0)


def test_sell_uses_ask_for_sl_so_spread_matters():
    # spread 100 poin = 1.0 harga. SELL masuk di bid 100, SL di 110.
    # high bid 109.5 + spread 1.0 = 110.5 >= 110 -> SL kena.
    df = make_df([
        bar(sig=-1, spread=100),
        bar(spread=100),
        bar(o=101, h=109.5, l=100.5, c=109, spread=100),
    ])
    t = run_backtest(df, CFG).trades
    assert len(t) == 1
    assert t.loc[0, "side"] == "SELL"
    assert t.loc[0, "label"] == "SL rugi"


def test_buy_entry_pays_spread():
    df = make_df([bar(sig=1, spread=100), bar(spread=100), bar(o=100, h=101, l=70, c=75, spread=100)])
    t = run_backtest(df, CFG).trades
    assert t.loc[0, "entry_price"] == pytest.approx(101.0)  # open 100 + spread 1.0


def test_three_losses_lock_the_day_then_resume_next_day():
    loss_bar = bar(o=100, h=100, l=85, sig=1)
    rows = [
        bar(sig=1), bar(),            # 0,1 -> entry bar 1
        loss_bar,                     # 2  rugi #1, sinyal baru
        bar(),                        # 3  entry
        loss_bar,                     # 4  rugi #2
        bar(),                        # 5  entry
        loss_bar,                     # 6  rugi #3 -> terkunci
        bar(sig=1),                   # 7  (hari sama) sinyal dari bar 6 dilewati
        bar(), loss_bar,              # 8,9 hari berikutnya: masuk lagi
    ]
    times = list(pd.date_range("2026-01-05 10:00", periods=8, freq="min")) + \
            list(pd.date_range("2026-01-06 10:00", periods=2, freq="min"))
    res = run_backtest(make_df(rows, times=times), CFG)
    assert len(res.trades) == 4
    assert res.skipped_locked == 1
    assert res.locked_days >= 1


def test_profit_exit_resets_loss_counter():
    loss_bar = bar(o=100, h=100, l=85, sig=1)
    rows = (
        [bar(sig=1), bar(), loss_bar, bar(), loss_bar]   # 2 rugi
        + [bar(o=100, h=115, l=99, c=114), bar(o=114, h=114, l=109, c=110, sig=1)]  # profit1 -> reset
        + [bar(), loss_bar, bar(), loss_bar]             # 2 rugi lagi, belum terkunci
        + [bar(sig=1), bar()]
    )
    res = run_backtest(make_df(rows), CFG)
    assert res.locked_days == 0


def test_spread_filter_skips_entry():
    cfg = BacktestConfig(point=0.01, contract_size=100, max_spread_points=50)
    df = make_df([bar(sig=1, spread=10), bar(spread=500), bar()])
    res = run_backtest(df, cfg)
    assert len(res.trades) == 0
    assert res.skipped_spread == 1


def test_only_one_position_at_a_time():
    df = make_df([bar(sig=1), bar(sig=1), bar(sig=1), bar(o=100, h=101, l=85)])
    res = run_backtest(df, CFG)
    assert len(res.trades) == 1
    assert res.skipped_busy >= 1


# ---------- filter jam & resample ----------
from backtest.engine import in_trading_hours  # noqa: E402
from backtest.data import resample  # noqa: E402


def test_in_trading_hours_normal_and_wraparound():
    assert in_trading_hours(10, 9, 18)
    assert not in_trading_hours(18, 9, 18)   # batas akhir tidak termasuk
    assert not in_trading_hours(3, 9, 18)
    assert in_trading_hours(23, 22, 6)       # melewati tengah malam
    assert in_trading_hours(2, 22, 6)
    assert not in_trading_hours(12, 22, 6)
    assert in_trading_hours(5, None, None)


def test_hours_filter_blocks_entry_outside_window():
    cfg = BacktestConfig(point=0.01, contract_size=100, hour_start=9, hour_end=18)
    rows = [bar(sig=1), bar(), bar(o=100, h=101, l=85)]
    # semua candle jam 03:00 -> di luar jendela
    times = pd.date_range("2026-01-05 03:00", periods=3, freq="min")
    res = run_backtest(make_df(rows, times=times), cfg)
    assert len(res.trades) == 0
    assert res.skipped_hours == 1
    # jam 10:00 -> boleh
    times2 = pd.date_range("2026-01-05 10:00", periods=3, freq="min")
    assert len(run_backtest(make_df(rows, times=times2), cfg).trades) == 1


def test_resample_m5_ohlc():
    t = pd.date_range("2026-01-05 10:00", periods=11, freq="min")
    df = pd.DataFrame({
        "time": t,
        "open": range(100, 111),
        "high": [x + 1 for x in range(100, 111)],
        "low": [x - 1 for x in range(100, 111)],
        "close": [x + 0.5 for x in range(100, 111)],
        "tick_volume": 10,
        "spread": 20,
    })
    out = resample(df, 5)
    # 11 candle -> 2 bucket penuh, bucket ke-3 (1 candle) dibuang
    assert len(out) == 2
    assert out.loc[0, "open"] == 100 and out.loc[0, "close"] == 104.5
    assert out.loc[0, "high"] == 105 and out.loc[0, "low"] == 99
    assert out.loc[0, "tick_volume"] == 50
