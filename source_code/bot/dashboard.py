"""
dashboard.py - tampilan terminal memakai library rich.
Tahap 4: tambah panel live trading (posisi, sinyal, pengunci, status mode).
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
            "[dim]PERINGATAN: Strategi belum terbukti. Bukan nasihat investasi.[/dim]",
            border_style="cyan",
        )
    )


def print_error(message: str) -> None:
    console.print(Panel(message, title="Kesalahan", border_style="red"))


def account_panel(acc: AccountSummary, cfg: Config) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    mode_style = "green" if acc.mode == "DEMO" else "bold red on white"
    table.add_row("Akun", f"***{str(acc.login)[-4:]} ({acc.name})")
    table.add_row("Server", acc.server)
    table.add_row("Jenis", f"[{mode_style}]{acc.mode}[/{mode_style}]  |  {acc.margin_mode}")
    table.add_row("Saldo", f"{acc.balance:,.2f} {acc.currency}")
    table.add_row("Equity", f"{acc.equity:,.2f} {acc.currency}")
    table.add_row("Leverage", f"1:{acc.leverage}")
    table.add_row("Simbol", cfg.symbol)
    table.add_row("Lot", f"{cfg.lot_size:g}")
    table.add_row("Stop setelah", f"{cfg.max_consecutive_loss}x SL(rugi) berturut-turut")
    table.add_row("Trailing", cfg.trailing_mode)
    table.add_row("Mode", f"[bold]{cfg.mode}[/bold]")
    table.add_row("Strategi", "[yellow]BELUM TERBUKTI[/yellow]")
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


def live_status_panel(
    sym: SymbolSummary,
    cfg: Config,
    consecutive_losses: int = 0,
    is_locked: bool = False,
    active_pos: Optional[dict] = None,
    last_trade: Optional[dict] = None,
    no_signal_reason: str = "Menunggu sinyal...",
) -> Panel:
    """Panel status live trading."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()

    # Mode dan jenis akun
    mode_style = "green" if cfg.mode == "signal_only" else "bold yellow"
    table.add_row("Mode", f"[{mode_style}]{cfg.mode}[/{mode_style}]")

    # Pengunci
    lock_color = "red" if is_locked else "green"
    lock_text = f"[{lock_color}]{'TERKUNCI' if is_locked else 'Aktif'}[/{lock_color}]"
    table.add_row("SL rugi beruntun", f"{consecutive_losses}/{cfg.max_consecutive_loss}  {lock_text}")

    # Posisi berjalan
    if active_pos:
        ticket = active_pos.get("ticket", "-")
        side = "BUY" if active_pos.get("side", 0) == 1 else "SELL"
        ep = active_pos.get("entry_price", 0.0)
        sl = active_pos.get("current_sl", 0.0)
        level = active_pos.get("trailing_level", 0)
        label_sl = f"SL profit{level}" if level > 0 else "SL rugi"
        r = active_pos.get("r", 1.0)

        # Hitung profit berjalan
        if active_pos.get("side", 0) == 1:
            profit_r = (sym.bid - ep) / r if r > 0 else 0.0
        else:
            profit_r = (ep - sym.ask) / r if r > 0 else 0.0
        profit_usd = profit_r * r * cfg.lot_size * 100.0

        profit_color = "green" if profit_r >= 0 else "red"
        table.add_row("Posisi", f"#{ticket} {side} ep={ep:.2f}")
        table.add_row("SL aktif", f"{sl:.2f}  [{profit_color}]{label_sl}[/{profit_color}]")
        table.add_row("Profit", f"[{profit_color}]{profit_r:+.2f}R  ({profit_usd:+.2f} USD)[/{profit_color}]")
    else:
        table.add_row("Posisi", "[dim]tidak ada[/dim]")
        table.add_row("Status", f"[dim]{no_signal_reason}[/dim]")

    # Transaksi terakhir
    if last_trade:
        label = last_trade.get("label", "-")
        pnl_r = last_trade.get("pnl_r", 0.0)
        pnl_usd = last_trade.get("pnl_usd", 0.0)
        pnl_color = "green" if pnl_r >= 0 else "red"
        table.add_row("Terakhir", f"[{pnl_color}]{label} {pnl_r:+.2f}R ({pnl_usd:+.2f} USD)[/{pnl_color}]")

    return Panel(table, title="Status Trading Live", border_style="magenta")


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
    console.print("  [cyan]1[/cyan]  Start (mode pantau)")
    console.print("  [cyan]2[/cyan]  Start Bot Live (signal_only / demo_orders sesuai .env)")
    console.print("  [cyan]3[/cyan]  Keluar")
    return Prompt.ask("Pilih", choices=["1", "2", "3"], default="1")


def ask_override_menu() -> str:
    """Menu override saat bot terkunci (3 SL rugi)."""
    console.print()
    console.print(
        Panel(
            "[bold red]BOT TERKUNCI[/bold red] - 3 SL rugi berturut-turut hari ini.\n"
            "  [cyan]1[/cyan]  Stop (tetap terkunci, lanjut besok)\n"
            "  [cyan]2[/cyan]  Override (ketik LANJUT untuk konfirmasi - reset ke 0, dicatat)",
            border_style="red",
        )
    )
    choice = Prompt.ask("Pilih", choices=["1", "2"], default="1")
    if choice == "2":
        confirm = Prompt.ask("Ketik [bold]LANJUT[/bold] untuk konfirmasi")
        if confirm.strip().upper() == "LANJUT":
            return "override"
        else:
            console.print("[yellow]Konfirmasi tidak sesuai. Tetap terkunci.[/yellow]")
            return "stop"
    return "stop"
