"""
experiments.py - jalankan DAFTAR UJI yang sudah ditentukan di muka.

Aturan mainnya (supaya tidak terkecoh hasil kebetulan):
  1. Daftar uji (GRID di bawah) ditetapkan SEBELUM melihat hasil.
  2. Pemilihan hanya memakai BAGIAN AWAL data.
  3. BAGIAN AKHIR hanya dibuka SEKALI, untuk satu pilihan, lewat --reveal.
  4. Pilih WILAYAH yang stabil (tetangganya juga bagus), bukan satu angka tertinggi.
     Dengan banyak kombinasi, yang tertinggi sering hanya kebetulan.

Contoh:
  python backtest/experiments.py --csv data/raw/XAUUSD.vx_M1.csv
  python backtest/experiments.py --csv data/raw/XAUUSD.vx_M1.csv --reveal 7
"""
import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich import box  # noqa: E402
from rich.table import Table  # noqa: E402

from bot.strategy import StrategyParams, generate_signals  # noqa: E402
from backtest.data import load_csv, resample  # noqa: E402
from backtest.engine import BacktestConfig, run_backtest  # noqa: E402
from backtest.report import console, print_report, summarize  # noqa: E402

# ---- DAFTAR UJI (jam dalam waktu server) ----
GRID = {
    "timeframe": [1, 5],
    "hours": [None, (9, 18)],
    "atr_mult": [2.0, 3.0, 4.0],
    "adx_min": [20.0, 30.0],
}
MIN_TRADES = 100      # di bawah ini hasil dianggap terlalu sedikit untuk dipercaya
TARGET_WR = 0.40      # target win rate minimal


def make_configs():
    keys = list(GRID.keys())
    combos = []
    for values in itertools.product(*[GRID[k] for k in keys]):
        combos.append(dict(zip(keys, values)))
    return combos


def hours_label(h):
    return "sepanjang hari" if h is None else f"{h[0]:02d}-{h[1]:02d}"


def run_one(base_df, meta, combo, lot, part, split):
    """part = 'awal' atau 'akhir'."""
    df = resample(base_df, combo["timeframe"])
    params = StrategyParams(atr_mult=combo["atr_mult"], adx_min=combo["adx_min"])
    sig = generate_signals(df, params)
    k = int(len(sig) * split)
    seg = sig.iloc[:k] if part == "awal" else sig.iloc[k:]
    h = combo["hours"]
    cfg = BacktestConfig(
        point=meta["point"], contract_size=meta["contract_size"], lot=lot,
        hour_start=None if h is None else h[0], hour_end=None if h is None else h[1],
    )
    res = run_backtest(seg, cfg)
    return seg, cfg, summarize(res, seg, cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Daftar uji strategi (hanya bagian awal data)")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--point", type=float, default=None)
    ap.add_argument("--contract-size", type=float, default=None)
    ap.add_argument("--lot", type=float, default=0.01)
    ap.add_argument("--split", type=float, default=0.7)
    ap.add_argument("--reveal", type=int, default=None, help="nomor kombinasi yang BAGIAN AKHIR-nya dibuka (sekali saja)")
    args = ap.parse_args()

    try:
        df, meta = load_csv(args.csv, point=args.point, contract_size=args.contract_size)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        return 1

    combos = make_configs()

    if args.reveal is not None:
        if not (0 <= args.reveal < len(combos)):
            console.print(f"[red]Nomor harus 0-{len(combos) - 1}[/red]")
            return 1
        c = combos[args.reveal]
        console.print(
            f"[bold yellow]MEMBUKA BAGIAN AKHIR untuk kombinasi #{args.reveal}:[/bold yellow] "
            f"M{c['timeframe']} | jam {hours_label(c['hours'])} | ATR x{c['atr_mult']:g} | ADX>={c['adx_min']:g}"
        )
        seg, cfg, stats = run_one(df, meta, c, args.lot, "akhir", args.split)
        print_report("BAGIAN AKHIR", stats, cfg)
        console.print("[dim]Setelah dibuka, bagian akhir tidak boleh dipakai lagi untuk memilih parameter.[/dim]")
        return 0

    rows = []
    for idx, c in enumerate(combos):
        seg, cfg, st = run_one(df, meta, c, args.lot, "awal", args.split)
        rows.append((idx, c, st))

    # kombinasi dengan transaksi cukup banyak diletakkan di atas; sisanya (sampel kecil) di bawah
    rows.sort(key=lambda r: (r[2].get("trades", 0) >= MIN_TRADES, r[2].get("avg_r", -99)), reverse=True)

    tb = Table(title=f"BAGIAN AWAL ({args.split * 100:.0f}% data) - {len(combos)} kombinasi", box=box.SIMPLE_HEAD,
               title_justify="left")
    for col, j in (("#", "right"), ("TF", "left"), ("Jam server", "left"), ("ATR", "right"), ("ADX", "right"),
                   ("Transaksi", "right"), ("Win rate", "right"), ("Rata2 R", "right"), ("PF", "right"),
                   ("DD (R)", "right"), ("Spread/1R", "right"), ("Lolos", "center")):
        tb.add_column(col, justify=j)

    for idx, c, st in rows:
        if st.get("trades", 0) == 0:
            tb.add_row(str(idx), f"M{c['timeframe']}", hours_label(c["hours"]), f"{c['atr_mult']:g}",
                       f"{c['adx_min']:g}", "0", "-", "-", "-", "-", "-", "-")
            continue
        ok = st["trades"] >= MIN_TRADES and st["win_rate"] >= TARGET_WR and st["avg_r"] > 0 and st["profit_factor"] > 1
        pf = st["profit_factor"]
        tb.add_row(
            str(idx), f"M{c['timeframe']}", hours_label(c["hours"]), f"{c['atr_mult']:g}", f"{c['adx_min']:g}",
            str(st["trades"]), f"{st['win_rate'] * 100:.1f}%", f"{st['avg_r']:+.3f}",
            "inf" if pf == float("inf") else f"{pf:.2f}", f"{st['max_dd_r']:.1f}",
            f"{st['avg_spread_r'] * 100:.0f}%", "[green]ya[/green]" if ok else "[dim]tidak[/dim]",
        )
    console.print(tb)
    console.print(
        f"[dim]Lolos = transaksi >= {MIN_TRADES}, win rate >= {TARGET_WR * 100:.0f}%, rata-rata R > 0, profit factor > 1.\n"
        "Jangan langsung ambil baris teratas: cari kelompok baris yang berdekatan dan sama-sama bagus.\n"
        "Setelah memilih SATU kombinasi, buka bagian akhirnya sekali: --reveal NOMOR[/dim]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
