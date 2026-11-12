"""
engine.py - mesin backtest yang meniru aturan bot kita.

Aturan yang ditiru:
  * satu posisi sekali waktu
  * entry di pembukaan candle berikutnya setelah sinyal (harga ask untuk
    buy, bid untuk sell, jadi spread ikut terhitung)
  * SL awal = SL(rugi) berjarak 1R. Saat profit mencapai 1,5R, SL pindah ke
    +1R (SL profit1); tiap tambahan 1R, SL naik 1R (SL profit2, dst).
    SL tidak pernah mundur.
  * berhenti trading sampai pergantian hari setelah N kali SL(rugi) berturut-turut
  * filter spread (opsional) dan filter jam trading (opsional, jam server)

Asumsi konservatif di dalam satu candle: pergerakan yang merugikan
dianggap terjadi LEBIH DULU daripada yang menguntungkan. Jadi SL dicek
dengan SL lama sebelum trailing diperbarui oleh candle yang sama.

Data candle MT5 adalah harga BID. Harga ask = bid + spread.
Hari dihitung memakai waktu server broker.
"""
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from bot.risk import LossLock
from bot.trailing import calculate_trailing_stop


@dataclass
class BacktestConfig:
    point: float                    # ukuran 1 poin (emas 2 desimal = 0.01)
    contract_size: float            # unit per 1 lot (emas 100, BTC 1)
    lot: float = 0.01
    max_spread_points: Optional[float] = None
    max_consecutive_loss: int = 3
    first_trigger_r: float = 1.5    # profit (dalam R) yang memicu SL pertama pindah ke +1R
    hour_start: Optional[int] = None  # jam server (0-23) mulai boleh entry, None = tanpa filter
    hour_end: Optional[int] = None    # jam server berhenti entry (tidak termasuk); boleh melewati tengah malam


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    signals_total: int
    skipped_busy: int
    skipped_spread: int
    skipped_locked: int
    locked_days: int
    skipped_hours: int = 0


def in_trading_hours(hour: int, start: Optional[int], end: Optional[int]) -> bool:
    """True kalau jam server berada di jendela [start, end). Jendela boleh melewati tengah malam."""
    if start is None or end is None:
        return True
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


REQUIRED_COLUMNS = ["time", "open", "high", "low", "close", "spread", "signal", "sl_distance"]


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig) -> BacktestResult:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Kolom berikut tidak ada di data: {', '.join(missing)}")

    df = df.reset_index(drop=True)
    n = len(df)
    time = pd.to_datetime(df["time"])
    days = time.dt.date.to_numpy()
    hours = time.dt.hour.to_numpy()
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    spr_pts = df["spread"].to_numpy(dtype=float)
    spr = spr_pts * cfg.point
    sig = df["signal"].fillna(0).to_numpy(dtype=int)
    sld = df["sl_distance"].to_numpy(dtype=float)

    lock = LossLock(max_consecutive_loss=cfg.max_consecutive_loss)
    trades = []
    pos = None
    recorded_locked_days = set()
    skipped_busy = skipped_spread = skipped_locked = skipped_hours = 0

    def close_trade(i: int, exit_price: float, label: str) -> None:
        nonlocal pos
        side = pos["side"]
        r = pos["r"]
        pnl_r = side * (exit_price - pos["entry"]) / r
        trades.append(
            {
                "entry_time": pos["time"],
                "exit_time": time.iloc[i],
                "side": "BUY" if side == 1 else "SELL",
                "entry_price": pos["entry"],
                "sl_awal": pos["sl0"],
                "r_price": r,
                "exit_price": exit_price,
                "label": label,
                "level": pos["level"],
                "pnl_r": pnl_r,
                "pnl_usd": pnl_r * r * cfg.contract_size * cfg.lot,
                "max_profit_r": pos["mfe"],
                "spread_points": pos["spread_pts"],
                "spread_r": pos["spread_price"] / r,
                "bars_held": i - pos["idx"] + 1,
            }
        )
        pos = None

    for i in range(n):
        current_date = days[i]

        # ---- 1. entry di pembukaan candle ini, berdasarkan sinyal candle sebelumnya
        s = int(sig[i - 1]) if i > 0 else 0
        if s != 0:
            r = sld[i - 1]
            if pos is not None:
                skipped_busy += 1
            elif lock.is_locked(current_date):
                skipped_locked += 1
            elif not in_trading_hours(int(hours[i]), cfg.hour_start, cfg.hour_end):
                skipped_hours += 1
            elif cfg.max_spread_points is not None and spr_pts[i] > cfg.max_spread_points:
                skipped_spread += 1
            elif not (np.isfinite(r) and r > 0):
                pass
            else:
                entry = o[i] + spr[i] if s == 1 else o[i]
                sl = entry - r if s == 1 else entry + r
                pos = {
                    "side": s, "entry": entry, "sl": sl, "sl0": sl, "r": r,
                    "level": 0, "idx": i, "time": time.iloc[i],
                    "spread_pts": spr_pts[i], "spread_price": spr[i], "mfe": 0.0,
                }

        # ---- 2. kelola posisi memakai candle ini
        if pos is not None:
            side, entry, r = pos["side"], pos["entry"], pos["r"]
            if side == 1:
                hit = l[i] <= pos["sl"]
                exit_price = min(pos["sl"], o[i])           # gap menembus SL: keluar di open
                fav_profit_r = (h[i] - entry) / r
            else:
                hit = (h[i] + spr[i]) >= pos["sl"]
                exit_price = max(pos["sl"], o[i] + spr[i])
                fav_profit_r = (entry - (l[i] + spr[i])) / r

            if hit:
                level = pos["level"]
                label = "SL rugi" if level == 0 else f"SL profit{level}"
                close_trade(i, exit_price, label)
                is_loss_sl = (level == 0)
                is_now_locked = lock.record_trade_result(is_loss_sl, current_date)
                if is_now_locked:
                    recorded_locked_days.add(current_date)
            else:
                pos["mfe"] = max(pos["mfe"], fav_profit_r)
                new_level, new_sl = calculate_trailing_stop(
                    side=side,
                    entry=entry,
                    r=r,
                    fav_profit_r=fav_profit_r,
                    current_level=pos["level"],
                    current_sl=pos["sl"],
                    first_trigger_r=cfg.first_trigger_r,
                )
                pos["level"] = new_level
                pos["sl"] = new_sl

    # posisi yang masih terbuka di akhir data ditutup di harga terakhir
    if pos is not None:
        last = n - 1
        exit_price = c[last] if pos["side"] == 1 else c[last] + spr[last]
        close_trade(last, exit_price, "Akhir data")

    return BacktestResult(
        trades=pd.DataFrame(trades),
        signals_total=int(np.count_nonzero(sig)),
        skipped_busy=skipped_busy,
        skipped_spread=skipped_spread,
        skipped_locked=skipped_locked,
        locked_days=len(recorded_locked_days),
        skipped_hours=skipped_hours,
    )
