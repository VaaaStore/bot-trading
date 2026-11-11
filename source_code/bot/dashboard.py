"""
dashboard.py - tampilan terminal memakai library rich.
"""
from typing import List, Optional

import pandas as pd
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .config import Config
from .mt5_client import AccountSummary, Check, SymbolSummary

console = Console()

STATUS_LABEL = {
    "ok": ("OK", "green"),
    "warn": ("PERHATIAN", "yellow"),
    "fail": ("GAGAL", "red"),
}


def print_welcome() -> None:
    console.print(
        Panel.fit(
            "[bold]BOT TRADING XAUUSD[/bold]\n"
            "[dim]Tahap 1: fondasi - hanya membaca data, belum ada order[/dim]",
            border_style="cyan",
        )
    )


def print_error(message: str) -> None:
    console.print(Panel(message, title="Kesalahan", border_style="red"))


def account_panel(acc: AccountSummary, cfg: Config) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    mode_style = "green" if acc.mode == "DEMO" else "bold red"
    table.add_row("Akun", f"{acc.login} ({acc.name})")
    table.add_row("Server", acc.server)
    table.add_row("Jenis", f"[{mode_style}]{acc.mode}[/{mode_style}]  |  {acc.margin_mode}")
    table.add_row("Saldo", f"{acc.balance:,.2f} {acc.currency}")
    table.add_row("Equity", f"{acc.equity:,.2f} {acc.currency}")
    table.add_row("Leverage", f"1:{acc.leverage}")
    table.add_row("Simbol", cfg.symbol)
    table.add_row("Lot", f"{cfg.lot_size:g}")
    table.add_row("Stop setelah", f"{cfg.max_consecutive_loss}x SL(rugi) berturut-turut")
    table.add_row("Trailing", cfg.trailing_mode)
    return Panel(table, title="Akun & pengaturan", border_style="cyan")


def checks_panel(checks: List[Check]) -> Panel:
    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column(width=10)
    table.add_column(style="bold")
    table.add_column(style="dim")
    for c in checks:
        label, color = STATUS_LABEL[c.status]
        table.add_row(f"[{color}]{label}[/{color}]", c.name, c.detail)
    return Panel(table, title="Pemeriksaan siap-jalan", border_style="cyan")


def market_panel(sym: SymbolSummary, cfg: Config) -> Panel:
    fmt = f"{{:.{sym.digits}f}}"
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()

    if sym.bid:
        table.add_row("Bid", fmt.format(sym.bid))
        table.add_row("Ask", fmt.format(sym.ask))
    else:
        table.add_row("Bid / Ask", "[yellow]belum ada harga masuk[/yellow]")

    spread_text = f"{sym.spread_points} poin ({sym.spread_points * sym.point:.2f} dalam harga)"
    if cfg.max_spread is not None and sym.spread_points > cfg.max_spread:
        spread_text = f"[red]{spread_text} > batas {cfg.max_spread:g}[/red]"
    table.add_row("Spread", spread_text)

    if sym.tick_time is not None:
        table.add_row("Tick terakhir", f"{sym.tick_time:%Y-%m-%d %H:%M:%S} [dim](waktu server)[/dim]")
    table.add_row("Kontrak", f"{sym.contract_size:g} per 1 lot")
    table.add_row("Jarak SL minimum", f"{sym.stops_level} poin")
    return Panel(table, title=f"Pasar - {sym.name}", border_style="cyan")


def candles_panel(df: pd.DataFrame, digits: int, rows: int = 10) -> Panel:
    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("Waktu server")
    for col in ("Open", "High", "Low", "Close"):
        table.add_column(col, justify="right")
    table.add_column("Vol", justify="right")

    if df.empty:
        table.add_row("[yellow]tidak ada data[/yellow]", "", "", "", "", "")
    else:
        fmt = f"{{:.{digits}f}}"
        for _, r in df.tail(rows).iterrows():
            color = "green" if r["close"] >= r["open"] else "red"
            table.add_row(
                f"{r['time']:%H:%M}",
                fmt.format(r["open"]),
                fmt.format(r["high"]),
                fmt.format(r["low"]),
                f"[{color}]{fmt.format(r['close'])}[/{color}]",
                str(int(r["tick_volume"])),
            )
    return Panel(table, title="Candle M1 terakhir", border_style="cyan")


def status_view(acc: AccountSummary, sym: SymbolSummary, candles: pd.DataFrame,
                checks: List[Check], cfg: Config) -> Group:
    return Group(
        account_panel(acc, cfg),
        checks_panel(checks),
        market_panel(sym, cfg),
        candles_panel(candles, sym.digits),
    )


def live_view(sym: SymbolSummary, candles: pd.DataFrame, cfg: Config) -> Group:
    return Group(
        Panel("[bold]MODE PANTAU[/bold]  [dim]belum ada order | Ctrl+C untuk kembali ke menu[/dim]",
              border_style="magenta"),
        market_panel(sym, cfg),
        candles_panel(candles, sym.digits),
    )


def ask_menu() -> str:
    console.print()
    console.print("[bold]Menu[/bold]")
    console.print("  [cyan]1[/cyan]  Start (mode pantau - Tahap 1 belum entry)")
    console.print("  [cyan]2[/cyan]  Keluar")
    return Prompt.ask("Pilih", choices=["1", "2"], default="1")