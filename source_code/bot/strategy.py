"""
strategy.py - aturan sinyal buy/sell dari gabungan indikator.

TITIK AWAL (bisa diubah lewat StrategyParams atau argumen backtest):

  Filter tren   : EMA cepat vs EMA lambat + posisi harga, dan ADX >= batas
                  (hanya trading kalau tren cukup kuat)
  Pemicu (BUY)  : dalam tren naik, RSI turun di bawah level beli lalu naik
                  menembus kembali (pullback selesai)
  Pemicu (SELL) : dalam tren turun, RSI naik di atas level jual lalu turun
                  menembus kembali
  SL            : jarak = ATR x pengali  (ini yang menjadi 1R)

Sinyal dihitung dari candle yang SUDAH TUTUP. Eksekusi baru terjadi di
candle berikutnya.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import adx, atr, ema, rsi


@dataclass
class StrategyParams:
    ema_fast: int = 20
    ema_slow: int = 50
    adx_period: int = 14
    adx_min: float = 20.0
    rsi_period: int = 10
    rsi_buy_level: float = 40.0
    rsi_sell_level: float = 60.0
    atr_period: int = 14
    atr_mult: float = 1.5


def generate_signals(df: pd.DataFrame, p: StrategyParams = None) -> pd.DataFrame:
    """
    Tambahkan kolom indikator dan 'signal' (+1 buy, -1 sell, 0 tidak ada)
    serta 'sl_distance' (jarak SL dalam satuan harga) ke salinan df.
    df wajib punya kolom: open, high, low, close.
    """
    p = p or StrategyParams()
    out = df.copy().reset_index(drop=True)

    out["ema_fast"] = ema(out["close"], p.ema_fast)
    out["ema_slow"] = ema(out["close"], p.ema_slow)
    out["rsi"] = rsi(out["close"], p.rsi_period)
    out["adx"] = adx(out["high"], out["low"], out["close"], p.adx_period)
    out["atr"] = atr(out["high"], out["low"], out["close"], p.atr_period)
    out["sl_distance"] = out["atr"] * p.atr_mult

    strong = out["adx"] >= p.adx_min
    bull = (out["ema_fast"] > out["ema_slow"]) & (out["close"] > out["ema_slow"]) & strong
    bear = (out["ema_fast"] < out["ema_slow"]) & (out["close"] < out["ema_slow"]) & strong

    prev = out["rsi"].shift(1)
    buy_trigger = (prev < p.rsi_buy_level) & (out["rsi"] >= p.rsi_buy_level)
    sell_trigger = (prev > p.rsi_sell_level) & (out["rsi"] <= p.rsi_sell_level)

    signal = np.where(bull & buy_trigger, 1, np.where(bear & sell_trigger, -1, 0))

    # abaikan bagian awal data sampai indikator stabil
    warmup = 3 * max(p.ema_slow, p.adx_period, p.atr_period, p.rsi_period)
    signal[:warmup] = 0
    out["signal"] = signal.astype(int)
    return out
