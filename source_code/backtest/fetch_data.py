"""
fetch_data.py - tarik data candle M1 dari MT5 dan simpan ke CSV.

Contoh (dari folder source_code, MT5 terbuka dan login):
  python backtest/fetch_data.py
  python backtest/fetch_data.py --bars 200000
  python backtest/fetch_data.py --symbol XAUUSD.vx

Hanya MEMBACA data. Tidak ada order.
Jumlah candle yang tersedia bergantung pada riwayat broker dan pengaturan
MT5: Tools > Options > Charts > "Max bars in chart" (pilih Unlimited).
"""
import argparse
import dataclasses
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import MetaTrader5 as mt5  # noqa: E402
import pandas as pd  # noqa: E402
from rich.console import Console  # noqa: E402

from bot.config import BASE_DIR, ConfigError, load_config  # noqa: E402
from bot.mt5_client import MT5Client, MT5Error  # noqa: E402

console = Console()


def main() -> int:
    ap = argparse.ArgumentParser(description="Tarik data M1 dari MT5")
    ap.add_argument("--bars", type=int, default=100000, help="jumlah candle yang diminta")
    ap.add_argument("--symbol", default=None, help="timpa SYMBOL di .env")
    args = ap.parse_args()

    try:
        cfg = load_config()
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        return 1
    if args.symbol:
        cfg = dataclasses.replace(cfg, symbol=args.symbol)

    client = MT5Client(cfg)
    try:
        client.connect()
        client.prepare_symbol()
        info = mt5.symbol_info(cfg.symbol)

        rates = None
        for _ in range(4):  # panggilan pertama kadang masih memuat riwayat
            rates = mt5.copy_rates_from_pos(cfg.symbol, mt5.TIMEFRAME_M1, 0, args.bars)
            if rates is not None and len(rates) > 100:
                break
            time.sleep(2)
        if rates is None or len(rates) == 0:
            console.print(f"[red]Tidak ada data M1 untuk {cfg.symbol}: {mt5.last_error()}[/red]")
            return 1

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]
        df = df.iloc[:-1]  # buang candle yang masih berjalan

        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", cfg.symbol)
        out_dir = BASE_DIR / "data" / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"{safe}_M1.csv"
        df.to_csv(csv_path, index=False)

        meta = {
            "symbol": cfg.symbol,
            "point": info.point,
            "digits": info.digits,
            "contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_step": info.volume_step,
            "bars": len(df),
            "first": str(df["time"].iloc[0]),
            "last": str(df["time"].iloc[-1]),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }
        csv_path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        console.print(f"[green]Tersimpan:[/green] {csv_path}")
        console.print(
            f"{len(df):,} candle | {df['time'].iloc[0]:%Y-%m-%d %H:%M} sampai "
            f"{df['time'].iloc[-1]:%Y-%m-%d %H:%M} (waktu server)"
        )
        console.print(
            f"Spread rata-rata: {df['spread'].mean():.0f} poin | median: {df['spread'].median():.0f} poin "
            f"(1 poin = {info.point:g})"
        )
        if len(df) < args.bars * 0.5:
            console.print(
                "[yellow]Data yang tersedia jauh lebih sedikit dari yang diminta. Di MT5: Tools > Options > "
                "Charts > Max bars in chart = Unlimited, restart MT5, lalu coba lagi.[/yellow]"
            )
        return 0
    except MT5Error as e:
        console.print(f"[red]{e}[/red]")
        return 1
    finally:
        client.shutdown()


if __name__ == "__main__":
    sys.exit(main())