"""
data.py - memuat data candle M1.

Mendukung dua format:
  1. CSV dari fetch_data.py (kolom: time,open,high,low,close,tick_volume,spread)
     beserta file .json di sebelahnya (berisi point dan ukuran kontrak).
  2. CSV hasil 'Export Bars' di MT5 (dipisah tab, kolom <DATE> <TIME> ...).
     Untuk format ini point bisa ditebak, tapi ukuran kontrak harus diberikan.
"""
import json
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd


def _infer_point(prices: pd.Series) -> float:
    sample = prices.head(2000)
    decimals = 0
    for x in sample:
        text = f"{float(x):.8f}".rstrip("0")
        d = len(text.split(".")[1]) if "." in text else 0
        decimals = max(decimals, d)
    return 10.0 ** (-decimals)


def load_csv(
    path: str,
    point: Optional[float] = None,
    contract_size: Optional[float] = None,
) -> Tuple[pd.DataFrame, dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File data tidak ditemukan: {p}")

    with open(p, "r", encoding="utf-8-sig") as f:
        header = f.readline()

    if "<DATE>" in header:
        df = pd.read_csv(p, sep="\t", encoding="utf-8-sig")
        df.columns = [c.strip("<>").lower() for c in df.columns]
        df["time"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str),
            format="%Y.%m.%d %H:%M:%S",
        )
        df = df.rename(columns={"tickvol": "tick_volume"})
        if "spread" not in df.columns:
            df["spread"] = 0
    else:
        df = pd.read_csv(p, parse_dates=["time"])

    for col in ("time", "open", "high", "low", "close", "spread"):
        if col not in df.columns:
            raise ValueError(f"Kolom '{col}' tidak ada di {p.name}")

    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)

    meta = {}
    sidecar = p.with_suffix(".json")
    if sidecar.exists():
        meta = json.loads(sidecar.read_text(encoding="utf-8"))

    meta["point"] = point if point is not None else meta.get("point") or _infer_point(df["open"])
    cs = contract_size if contract_size is not None else meta.get("contract_size")
    if cs is None:
        raise ValueError(
            "Ukuran kontrak tidak diketahui. Beri argumen --contract-size "
            "(emas biasanya 100, BTC biasanya 1; lihat panel 'Kontrak' di bot)."
        )
    meta["contract_size"] = float(cs)
    return df, meta


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """
    Gabungkan candle M1 menjadi candle M{minutes}. Hanya untuk backtest.
    Spread diambil rata-rata. Bucket terakhir dibuang kalau belum lengkap.
    """
    if minutes <= 1:
        return df
    t = pd.to_datetime(df["time"])
    work = df.assign(_bucket=t.dt.floor(f"{minutes}min"))
    agg = {
        "open": ("open", "first"),
        "high": ("high", "max"),
        "low": ("low", "min"),
        "close": ("close", "last"),
        "spread": ("spread", "mean"),
        "_n": ("open", "size"),
    }
    if "tick_volume" in df.columns:
        agg["tick_volume"] = ("tick_volume", "sum")
    out = work.groupby("_bucket", sort=True).agg(**agg).reset_index().rename(columns={"_bucket": "time"})
    if len(out) and out["_n"].iloc[-1] < minutes:
        out = out.iloc[:-1]
    out["spread"] = out["spread"].round()
    return out.drop(columns="_n").reset_index(drop=True)
