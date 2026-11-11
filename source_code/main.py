"""
main.py - titik masuk bot.

TAHAP 1: koneksi MT5, layar welcome, pemeriksaan siap-jalan, mode pantau.
Belum ada logika sinyal, entry, atau trailing.

Jalankan:  python main.py
"""
import sys
import time

from rich.live import Live

from bot import dashboard
from bot.config import ConfigError, load_config
from bot.mt5_client import MT5Client, MT5Error


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
            if dashboard.ask_menu() == "1":
                monitor(client, cfg)
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