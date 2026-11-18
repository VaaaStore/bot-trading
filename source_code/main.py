"""
main.py - titik masuk bot.

Tahap 4: koneksi MT5, layar welcome, pemeriksaan siap-jalan, mode pantau,
         dan mode live (signal_only / demo_orders).

Jalankan:  python main.py
Keamanan:
  - MODE=signal_only (default): tampilkan sinyal, tidak ada order.
  - MODE=demo_orders: hanya akun DEMO, butuh Algo Trading aktif di MT5.
  - Akun REAL ditolak kecuali ALLOW_REAL=true (tidak pernah di-set oleh agent).
"""
import sys
import time

from rich.live import Live

from bot import dashboard
from bot.config import ConfigError, load_config
from bot.live import LiveBot
from bot.mt5_client import MT5Client, MT5Error
from bot.state import BotState, load_state


def show_status(client: MT5Client, cfg) -> None:
    acc = client.get_account()
    sym = client.get_symbol()
    candles = client.get_candles(15)
    checks = client.run_checks(acc, sym, candles)
    dashboard.console.print(dashboard.status_view(acc, sym, candles, checks, cfg))


def monitor(client: MT5Client, cfg) -> None:
    """Tampilan harga live. Tidak mengirim order apa pun."""
    try:
        with Live(console=dashboard.console, refresh_per_second=2, screen=False) as live:
            while True:
                sym = client.get_symbol()
                candles = client.get_candles(15)
                live.update(dashboard.live_view(sym, candles, cfg))
                time.sleep(1)
    except KeyboardInterrupt:
        dashboard.console.print("\n[dim]Kembali ke menu.[/dim]")
    except MT5Error as e:
        dashboard.print_error(str(e))


def run_live(client: MT5Client, cfg) -> None:
    """
    Jalankan bot live (signal_only atau demo_orders).
    Keluar dengan Ctrl+C.
    """
    dashboard.console.print(
        f"\n[bold]Memulai bot live[/bold]  [dim](MODE={cfg.mode})[/dim]\n"
        "[dim]Ctrl+C untuk berhenti.[/dim]\n"
    )

    # Periksa penguncian dari state tersimpan
    from bot.state import STATE_PATH
    state = load_state(STATE_PATH)

    # Jika terkunci: tampilkan menu Override
    from bot.risk import LossLock
    from datetime import date
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore
    from datetime import datetime, timezone

    tz = ZoneInfo("Asia/Jakarta")
    today = datetime.now(tz).date()
    lock_check = LossLock(max_consecutive_loss=cfg.max_consecutive_loss)
    if state.locked_date:
        try:
            lock_check.state.locked_date = date.fromisoformat(state.locked_date)
            lock_check.state.consecutive_losses = state.consecutive_losses
        except (ValueError, TypeError):
            pass

    if lock_check.is_locked(today):
        choice = dashboard.ask_override_menu()
        if choice == "override":
            state.consecutive_losses = 0
            state.override_active = True
            from bot.state import save_state, STATE_PATH as sp
            save_state(state, sp)
            dashboard.console.print("[yellow]Override aktif: hitungan direset ke 0.[/yellow]")
        else:
            dashboard.console.print("[dim]Bot terkunci. Kembali ke menu.[/dim]")
            return

    bot = LiveBot(cfg, client, state=state)
    try:
        bot.run()
    except KeyboardInterrupt:
        dashboard.console.print("\n[dim]Bot live dihentikan. Kembali ke menu.[/dim]")


def main() -> int:
    dashboard.print_welcome()

    try:
        cfg = load_config()
    except ConfigError as e:
        dashboard.print_error(str(e))
        return 1

    client = MT5Client(cfg)
    try:
        client.connect()
        client.prepare_symbol()
    except MT5Error as e:
        dashboard.print_error(str(e))
        return 1

    try:
        show_status(client, cfg)
        while True:
            choice = dashboard.ask_menu()
            if choice == "1":
                monitor(client, cfg)
                show_status(client, cfg)
            elif choice == "2":
                run_live(client, cfg)
                show_status(client, cfg)
            else:
                break
    except MT5Error as e:
        dashboard.print_error(str(e))
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        client.shutdown()
        dashboard.console.print("[dim]Bot ditutup.[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
