"""
trailing.py - Fungsi murni perhitungan Trailing Stop bertingkat (R-multiple).
Aturan:
- SL awal = SL(rugi), berjarak 1R dari entry.
- Saat profit berjalan mencapai 1.5R, SL pindah ke +1R (level 1).
- Tiap tambahan 1R berikutnya (2.5R, 3.5R, ...), SL naik jadi +2R, +3R, dst.
- SL TIDAK PERNAH mundur.
"""
import math


def calculate_trailing_stop(side: int, entry: float, r: float, fav_profit_r: float, current_level: int, current_sl: float, first_trigger_r: float = 1.5) -> tuple[int, float]:
    """
    Menghitung level trailing dan harga SL baru.
    side: 1 (buy) atau -1 (sell)
    entry: harga masuk
    r: jarak SL awal (1R)
    fav_profit_r: profit maksimum berjalan dalam R
    current_level: level trailing saat ini
    current_sl: harga SL saat ini
    """
    lock_gap = first_trigger_r - 1.0  # e.g., 1.5 - 1.0 = 0.5
    new_level = current_level

    if fav_profit_r >= first_trigger_r:
        calculated_level = int(math.floor(fav_profit_r - lock_gap + 1e-9))
        if calculated_level > current_level:
            new_level = calculated_level

    # Hitung harga SL baru berdasarkan level
    if new_level == 0:
        target_sl = entry - r if side == 1 else entry + r
    else:
        target_sl = entry + side * new_level * r

    # Pastikan SL tidak pernah mundur
    if side == 1:
        final_sl = max(current_sl, target_sl)
    else:
        final_sl = min(current_sl, target_sl)

    return new_level, final_sl
