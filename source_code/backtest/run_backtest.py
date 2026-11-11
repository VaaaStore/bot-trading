"""
run_backtest.py - jalankan backtest strategi pada data M1.

Contoh (dari folder source_code, venv aktif):
  python backtest/run_backtest.py --csv data/raw/XAUUSD.vx_M1.csv --split 0.7
  python backtest/run_backtest.py --csv data/raw/XAUUSD.vx_M1.csv --split 0.7 --hours 9-18
  python backtest/run_backtest.py --csv data/raw/XAUUSD.vx_M1.csv --split 0.7 --timeframe 5
  python backtest/run_backtest.py --csv data/raw/XAUUSD.vx_M1.csv --split 0.7 --atr-mult 3 --spread-scale 0
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.strategy import StrategyParams, generate_signals  # noqa: E402
from backtest.data import load_csv, resample  # noqa: E402
from backtest.engine import BacktestConfig, run_backtest  # noqa: E402
from backtest.report import console, print_report, summarize  # noqa: E402


def parse_hours(text):
    """'9-18' -> (9, 18). Kosong atau 'all' -> (None, None)."""
    if not text or text.lower() == "all":
        return None, None
    try:
        a, b = text.split("-")
        a, b = int(a), int(b)
    except ValueError:
        raise SystemExit("Format --hours salah. Contoh: --hours 9-18 (jam server)")
    if not (0 <= a <= 23 and 0 <= b <= 24):
        raise SystemExit("--hours harus berada di rentang 0-24")
    return a, b % 24 if b == 24 else b


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Backtest bot XAUUSD (M1)")
    ap.add_argument("--csv", required=True, help="file data M1")
    ap.add_argument("--point", type=float, default=None, help="ukuran 1 poin (otomatis dari data bila kosong)")
    ap.add_argument("--contract-size", type=float, default=None, help="unit per 1 lot (otomatis dari file .json bila ada)")
    ap.add_argument("--lot", type=float, default=0.01)
    ap.add_argument("--max-spread", type=float, default=None, help="batas spread dalam poin")
    ap.add_argument("--max-loss", type=int, default=3, help="berhenti setelah N SL rugi berturut-turut")
    ap.add_argument("--first-trigger", type=float, default=1.5, help="profit (R) yang memicu SL pindah ke +1R")
    ap.add_argument("--split", type=float, default=None, help="bagi data, mis. 0.7 = 70%% awal dan 30%% akhir")
    ap.add_argument("--save", default="data/backtest_trades.csv", help="simpan daftar transaksi ke CSV")
    ap.add_argument("--spread-scale", type=float, default=1.0,
                    help="kalikan spread data (1 = apa adanya, 0 = tanpa spread)")
    ap.add_argument("--hours", default=None, help="jam entry dalam waktu SERVER, mis. 9-18 (tanpa isi = sepanjang hari)")
    ap.add_argument("--from", dest="date_from", default=None, help="hanya pakai data mulai tanggal ini (YYYY-MM-DD, waktu server)")
    ap.add_argument("--to", dest="date_to", default=None, help="hanya pakai data SEBELUM tanggal ini (YYYY-MM-DD)")
    ap.add_argument("--timeframe", type=int, default=1, help="gabungkan M1 jadi M{n} (mis. 5 atau 15); hanya untuk backtest")

    d = StrategyParams()
    ap.add_argument("--ema-fast", type=int, default=d.ema_fast)
    ap.add_argument("--ema-slow", type=int, default=d.ema_slow)
    ap.add_argument("--adx-period", type=int, default=d.adx_period)
    ap.add_argument("--adx-min", type=float, default=d.adx_min)
    ap.add_argument("--rsi-period", type=int, default=d.rsi_period)
    ap.add_argument("--rsi-buy", type=float, default=d.rsi_buy_level)
    ap.add_argument("--rsi-sell", type=float, default=d.rsi_sell_level)
    ap.add_argument("--atr-period", type=int, default=d.atr_period)
    ap.add_argument("--atr-mult", type=float, default=d.atr_mult)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        df, meta = load_csv(args.csv, point=args.point, contract_size=args.contract_size)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return 1

    df["spread"] = df["spread"] * args.spread_scale
    if args.timeframe > 1:
        df = resample(df, args.timeframe)
    h_start, h_end = parse_hours(args.hours)

    params = StrategyParams(
        ema_fast=args.ema_fast, ema_slow=args.ema_slow,
        adx_period=args.adx_period, adx_min=args.adx_min,
        rsi_period=args.rsi_period, rsi_buy_level=args.rsi_buy, rsi_sell_level=args.rsi_sell,
        atr_period=args.atr_period, atr_mult=args.atr_mult,
    )
    cfg = BacktestConfig(
        point=meta["point"], contract_size=meta["contract_size"], lot=args.lot,
        max_spread_points=args.max_spread, max_consecutive_loss=args.max_loss,
        first_trigger_r=args.first_trigger, hour_start=h_start, hour_end=h_end,
    )

    hours_text = "sepanjang hari" if h_start is None else f"{h_start:02d}-{h_end:02d} (jam server)"
    console.print(
        f"[bold]Data:[/bold] {Path(args.csv).name} | M{args.timeframe} | {len(df):,} candle | "
        f"{df['time'].iloc[0]:%Y-%m-%d %H:%M} sampai {df['time'].iloc[-1]:%Y-%m-%d %H:%M} (waktu server)\n"
        f"[bold]Poin:[/bold] {cfg.point:g} | [bold]Kontrak:[/bold] {cfg.contract_size:g} | "
        f"[bold]Lot:[/bold] {cfg.lot:g} | [bold]Skala spread:[/bold] {args.spread_scale:g} | "
        f"[bold]Jam entry:[/bold] {hours_text} | [bold]Batas spread:[/bold] "
        f"{'tidak dipakai' if cfg.max_spread_points is None else f'{cfg.max_spread_points:g} poin'}\n"
    )

    sig_df = generate_signals(df, params)   # indikator dihitung pada seluruh data (pemanasan), baru dipotong

    if args.date_from or args.date_to:
        t = pd.to_datetime(sig_df["time"])
        mask = pd.Series(True, index=sig_df.index)
        if args.date_from:
            mask &= t >= pd.Timestamp(args.date_from)
        if args.date_to:
            mask &= t < pd.Timestamp(args.date_to)
        sig_df = sig_df[mask].reset_index(drop=True)
        if sig_df.empty:
            console.print("[red]Tidak ada data pada rentang tanggal itu.[/red]")
            return 1
        console.print(
            f"[bold]Rentang dipakai:[/bold] {sig_df['time'].iloc[0]:%Y-%m-%d %H:%M} sampai "
            f"{sig_df['time'].iloc[-1]:%Y-%m-%d %H:%M} | {len(sig_df):,} candle\n"
        )

    if args.split and 0.1 < args.split < 0.95:
        k = int(len(sig_df) * args.split)
        segments = [("BAGIAN AWAL (untuk memilih parameter)", sig_df.iloc[:k]),
                    ("BAGIAN AKHIR (belum 'dilihat', penguji sebenarnya)", sig_df.iloc[k:])]
    else:
        segments = [("SELURUH DATA", sig_df)]

    all_trades = []
    for title, seg in segments:
        res = run_backtest(seg, cfg)
        print_report(title, summarize(res, seg, cfg), cfg)
        if not res.trades.empty:
            all_trades.append(res.trades)

    if all_trades and args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(all_trades).to_csv(out, index=False)
        console.print(f"[dim]Daftar transaksi disimpan ke {out}[/dim]")

    console.print(
        "\n[dim]Ingat: backtest bukan jaminan hasil nyata. Parameter yang terlalu disesuaikan "
        "dengan data lama biasanya gagal di data baru. Gunakan --split dan lanjutkan ke akun demo.[/dim]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
