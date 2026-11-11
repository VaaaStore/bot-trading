import numpy as np
import pandas as pd

from bot.indicators import adx, atr, ema, rsi


def test_ema_of_constant_is_constant():
    s = pd.Series([100.0] * 50)
    assert np.allclose(ema(s, 10), 100.0)


def test_rsi_all_up_is_100_and_all_down_is_0():
    up = pd.Series(np.arange(1.0, 60.0))
    down = pd.Series(np.arange(60.0, 1.0, -1.0))
    assert rsi(up, 10).iloc[-1] == 100.0
    assert abs(rsi(down, 10).iloc[-1]) < 1e-9


def test_rsi_stays_between_0_and_100():
    rng = np.random.default_rng(1)
    s = pd.Series(100 + rng.normal(0, 1, 500).cumsum())
    r = rsi(s, 10).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_atr_of_fixed_range_equals_range():
    n = 100
    close = pd.Series(np.full(n, 100.0))
    high = close + 1.0
    low = close - 1.0
    assert abs(atr(high, low, close, 14).iloc[-1] - 2.0) < 1e-6


def test_adx_high_in_steady_trend_low_in_flat_noise():
    n = 300
    base = pd.Series(np.arange(n, dtype=float))
    trend = adx(base + 0.5, base - 0.5, base, 14).iloc[-1]
    rng = np.random.default_rng(2)
    flat = pd.Series(100 + rng.normal(0, 0.2, n))
    noisy = adx(flat + 0.3, flat - 0.3, flat, 14).iloc[-1]
    assert trend > 40
    assert noisy < trend
