"""
smoke_order_test.py - Tes end-to-end terkontrol di akun DEMO.

Butuh: --yes-demo (flag eksplisit)
Tolak: akun non-demo, MODE bukan demo_orders.

Langkah:
  1. Buka 1 posisi 0.01 lot dengan SL.
  2. Geser SL sekali.
  3. Tutup posisi.
  4. Verifikasi riwayat deal.
  5. Cetak ringkasan.

PERINGATAN: Tes ini membutuhkan MT5 berjalan dan akun DEMO aktif.
Agent TIDAK menjalankan skrip ini secara otomatis.
Jalankan manual: python tools/smoke_order_test.py --yes-demo
"""
import argparse
import sys
from pathlib import Path

# Tambahkan source_code ke path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import ConfigError, load_config
from bot.mt5_client import MT5Client, MT5Error


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test order demo MT5")
    parser.add_argument(
        "--yes-demo",
        action="store_true",
        help="Konfirmasi eksplisit bahwa ini akun DEMO (wajib ada)",
    )
    args = parser.parse_args()

    if not args.yes_demo:
        print("[TOLAK] Harus menyertakan --yes-demo untuk menjalankan tes ini.")
        print("Contoh: python tools/smoke_order_test.py --yes-demo")
        return 1

    # Muat konfigurasi
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"[ERROR] Konfigurasi tidak valid: {e}")
        return 1

    # Cek MODE
    if cfg.mode != "demo_orders":
        print(
            f"[TOLAK] MODE harus 'demo_orders', saat ini '{cfg.mode}'. "
            "Ubah MODE=demo_orders di .env untuk menjalankan smoke test."
        )
        return 1

    # Koneksi
    client = MT5Client(cfg)
    try:
        print("Menghubungkan ke MT5...")
        client.connect()
        client.prepare_symbol()
    except MT5Error as e:
        print(f"[ERROR] Koneksi gagal: {e}")
        return 1

    # Cek akun DEMO
    try:
        acc = client.get_account()
    except MT5Error as e:
        print(f"[ERROR] Gagal membaca akun: {e}")
        client.shutdown()
        return 1

    if acc.mode != "DEMO":
        print(
            f"[TOLAK] Ini akun {acc.mode}, bukan DEMO. "
            "Smoke test hanya berjalan di akun DEMO."
        )
        client.shutdown()
        return 1

    print(f"Akun: ***{str(acc.login)[-4:]} | {acc.mode} | Saldo: {acc.balance:.2f} {acc.currency}")

    sym = client.get_symbol()
    # SL jarak 100 poin dari harga saat ini (lebih dari stops_level)
    sl_distance = max(sym.stops_level * sym.point * 2, 1.0)
    print(f"Simbol: {sym.name} | Bid: {sym.bid:.{sym.digits}f} | SL distance: {sl_distance:.2f}")

    # Langkah 1: Buka posisi BUY
    print("\n--- Langkah 1: Buka posisi BUY 0.01 lot ---")
    result = client.send_market_order(side=1, sl_distance=sl_distance)
    if not result.success:
        print(f"[ERROR] Order gagal: {result.comment} (retcode={result.retcode})")
        client.shutdown()
        return 1
    ticket = result.ticket
    entry_price = result.entry_price
    print(f"Order masuk: ticket={ticket} entry={entry_price:.{sym.digits}f}")

    # Langkah 2: Geser SL
    print("\n--- Langkah 2: Geser SL ---")
    new_sl = round(entry_price - sl_distance * 1.1, sym.digits)  # Geser sedikit
    ok = client.modify_sl(ticket, new_sl)
    if ok:
        print(f"SL digeser ke {new_sl:.{sym.digits}f}: OK")
    else:
        print(f"[WARN] Gagal menggeser SL ke {new_sl:.{sym.digits}f}")

    # Langkah 3: Tutup posisi
    print("\n--- Langkah 3: Tutup posisi ---")
    closed = client.close_position(ticket)
    if closed:
        print(f"Posisi {ticket} ditutup: OK")
    else:
        print(f"[ERROR] Gagal menutup posisi {ticket}")
        client.shutdown()
        return 1

    # Langkah 4: Verifikasi riwayat deal
    print("\n--- Langkah 4: Verifikasi riwayat deal ---")
    deals = client.get_position_deals(ticket)
    if not deals:
        print("[WARN] Tidak ada deal ditemukan dalam riwayat 30 hari.")
    else:
        print(f"Deal ditemukan: {len(deals)} deal")
        for d in deals:
            arah = "BUY" if d.side == 1 else "SELL"
            print(
                f"  deal={d.ticket} {arah} price={d.price:.{sym.digits}f} "
                f"profit={d.profit:.2f} USD reason={d.reason}"
            )

    # Langkah 5: Ringkasan
    print("\n=== RINGKASAN SMOKE TEST ===")
    print(f"Akun  : ***{str(acc.login)[-4:]} | {acc.mode}")
    print(f"Simbol: {sym.name}")
    print(f"Ticket: {ticket}")
    print(f"Entry : {entry_price:.{sym.digits}f}")
    print(f"SL    : {new_sl:.{sym.digits}f}")
    total_profit = sum(d.profit + d.commission + d.swap for d in deals)
    print(f"P/L   : {total_profit:.2f} {acc.currency}")
    print(f"Status: {'LULUS' if deals else 'PERINGATAN (tidak ada deal)'}")

    client.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
