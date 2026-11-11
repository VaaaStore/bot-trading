"""
report.py - ringkasan hasil backtest.
"""
import numpy as np
import pandas as pd
from rich import box
from rich.console import Console
from rich.table import Table

from .engine import BacktestConfig, BacktestResult

console = Console()


def _max_streak(flags: np.ndarray) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def summarize(res: BacktestResult, df: pd.DataFrame, cfg: BacktestConfig) -> dict:
    t = res.trades
    n_days = max(1, pd.to_datetime(df["time"]).dt.date.nunique())
    stats = {
        "bars": len(df),
        "days": n_days,
        "signals_total": res.signals_total,
        "signals_per_day": res.signals_total / n_days,
        "skipped_busy": res.skipped_busy,
        "skipped_spread": res.skipped_spread,
        "skipped_locked": res.skipped_locked,
        "skipped_hours": res.skipped_hours,
        "locked_days": res.locked_days,
        "trades": len(t),
        "trades_per_day": len(t) / n_days,
    }
    if t.empty:
        return stats

    pnl_r = t["pnl_r"].to_numpy()
    pnl_usd = t["pnl_usd"].to_numpy()
    wins = pnl_r[pnl_r > 0]
    losses = pnl_r[pnl_r <= 0]
    eq_r = np.cumsum(pnl_r)
    eq_usd = np.cumsum(pnl_usd)

    stats.update(
        {
            "win_rate": len(wins) / len(pnl_r),
            "net_r": float(pnl_r.sum()),
            "net_usd": float(pnl_usd.sum()),
            "avg_r": float(pnl_r.mean()),
            "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf"),
            "max_dd_r": float((np.maximum.accumulate(eq_r) - eq_r).max()),
            "max_dd_usd": float((np.maximum.accumulate(eq_usd) - eq_usd).max()),
            "longest_loss_streak": _max_streak(pnl_r <= 0),
            "avg_spread_r": float(t["spread_r"].mean()),
            "avg_risk_usd": float(t["r_price"].mean() * cfg.contract_size * cfg.lot),
            "label_counts": t["label"].value_counts().to_dict(),
        }
    )
    return stats


def print_report(title: str, stats: dict, cfg: BacktestConfig) -> None:
    tb = Table(title=title, box=box.SIMPLE_HEAD, title_justify="left")
    tb.add_column("Metrik")
    tb.add_column("Nilai", justify="right")

    tb.add_row("Jumlah candle / hari data", f"{stats['bars']:,} / {stats['days']}")
    tb.add_row("Sinyal total (per hari)", f"{stats['signals_total']} ({stats['signals_per_day']:.1f})")
    tb.add_row("Sinyal dilewati: posisi masih terbuka", str(stats["skipped_busy"]))
    if cfg.hour_start is not None:
        tb.add_row(f"Sinyal dilewati: di luar jam {cfg.hour_start:02d}-{cfg.hour_end:02d} server", str(stats["skipped_hours"]))
    tb.add_row("Sinyal dilewati: spread terlalu lebar", str(stats["skipped_spread"]))
    tb.add_row("Sinyal dilewati: terkunci (3 SL rugi)", f"{stats['skipped_locked']} ({stats['locked_days']} hari terkunci)")
    tb.add_row("Transaksi (per hari)", f"{stats['trades']} ({stats['trades_per_day']:.1f})")

    if stats["trades"] > 0:
        pf = stats["profit_factor"]
        tb.add_row("Win rate (hasil > 0)", f"{stats['win_rate'] * 100:.1f}%")
        tb.add_row("Rata-rata hasil per transaksi", f"{stats['avg_r']:+.3f} R")
        tb.add_row("Total hasil", f"{stats['net_r']:+.1f} R  |  {stats['net_usd']:+,.2f} USD (lot {cfg.lot:g})")
        tb.add_row("Profit factor", "tak hingga" if pf == float("inf") else f"{pf:.2f}")
        tb.add_row("Drawdown maksimum", f"{stats['max_dd_r']:.1f} R  |  {stats['max_dd_usd']:,.2f} USD")
        tb.add_row("Rugi beruntun terpanjang", str(stats["longest_loss_streak"]))
        tb.add_row("Rata-rata 1R (risiko per transaksi)", f"{stats['avg_risk_usd']:,.2f} USD")
        tb.add_row("Rata-rata spread dibanding 1R", f"{stats['avg_spread_r'] * 100:.1f}%")
    console.print(tb)

    if stats["trades"] > 0:
        lt = Table(title="Hasil per jenis keluar", box=box.SIMPLE_HEAD, title_justify="left")
        lt.add_column("Jenis")
        lt.add_column("Jumlah", justify="right")
        lt.add_column("Porsi", justify="right")
        order = sorted(stats["label_counts"].items(), key=lambda kv: (kv[0] != "SL rugi", kv[0]))
        for label, cnt in order:
            lt.add_row(label, str(cnt), f"{cnt / stats['trades'] * 100:.1f}%")
        console.print(lt)

        if stats["trades"] < 30:
            console.print("[yellow]Sampel sangat kecil (<30 transaksi): hasil belum bermakna.[/yellow]")
        elif stats["trades"] < 100:
            console.print("[yellow]Sampel masih kecil (<100 transaksi): hati-hati menarik kesimpulan.[/yellow]")
    else:
        console.print("[yellow]Tidak ada transaksi. Longgarkan filter atau pakai data lebih panjang.[/yellow]")
