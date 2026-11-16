# Hasil Uji Bersih — XAUUSD.vx M1

> **Status:** Kandidat ATR4/ADX30 **TIDAK TERBUKTI** unggul. Data gabungan menunjukkan rata-rata R negatif.
> Semua hasil di halaman ini direkam apa adanya; tidak ada yang dihilangkan.

---

## Deskripsi Uji

- **Instrumen:** XAUUSD.vx (Valetax), data M1 dari MT5
- **Lot:** 0,01 | **Kontrak:** 100 per lot | **1 poin = 0,01**
- **Spread:** dari data (skala 1,0 — spread nyata)
- **Trailing:** bertingkat R-multiple, `first_trigger_r = 1.5`
- **Pengunci:** berhenti setelah 3 SL rugi berturut-turut; reset pergantian hari
- **Kriteria lulus (ditetapkan sebelum melihat hasil):** ≥ 100 transaksi, rata-rata R > 0, PF > 1, WR ≥ 40%
- **Metodologi:** parameter dipilih pada data pengembangan; uji bersih dilakukan SEKALI pada data yang belum pernah dilihat

---

## Tabel Hasil

| ID | Parameter | Jam | Periode | Candle | Transaksi | WR | Rata-rata R | PF | Max DD (R) | Status |
|----|-----------|-----|---------|--------|-----------|----|--------------|----|------------|--------|
| Uji 1 | ATR 3, ADX 20 | Seharian | 2025-09-24 .. 2026-07-28 | ~267 hari | 1.232 | 37,9% | −0,000 R | 1,00 | 54,7 R | ❌ Gagal (WR < 40%, R = 0) |
| Uji 2 | ATR 4, ADX 30 | Seharian | 2025-09-24 .. 2026-07-28 | ~217 hari | 398 | 39,7% | +0,085 R | 1,14 | 22,1 R | ❌ Gagal tipis (WR < 40%) |
| Uji 3 | ATR 4, ADX 20 | 09–18 server | 2025-09-24 .. 2026-07-28 | ~217 hari | 569 | 35,1% | −0,114 R | 0,83 | — | ❌ Gagal |
| Uji 4 (panjang) | ATR 4, ADX 30 | Seharian | 2024-05-01 .. 2025-09-23 | ~217 hari | 655 | 35,6% | −0,110 R | 0,83 | 87,2 R | ❌ Gagal |
| **Gabungan Uji 2+4** | ATR 4, ADX 30 | Seharian | 2024-05-01 .. 2026-07-28 | ~434 hari | ~1.053 | — | **≈ −0,04 R** | — | — | ❌ **Tidak terbukti** |

---

## Kesimpulan

1. **ATR4/ADX30** menunjukkan hasil positif kecil di data pendek (2025-09-24..2026-07-28, +0,085 R, PF 1,14),
   tetapi hasil menghilang di data lebih panjang. Kombinasi data 2024-2026 menghasilkan sekitar −0,04 R.
2. **ATR3/ADX20** tidak menunjukkan keunggulan (rata-rata 0 R, PF 1,00 pada 1.232 transaksi).
3. **Filter jam 09-18** tidak membantu; justru memperburuk hasil (Uji 3 PF 0,83).
4. Tidak ada kombinasi yang memenuhi semua kriteria lulus secara konsisten.

**Implikasi untuk bot live:**
- Default bot: `MODE=signal_only` (tidak ada order nyata tanpa keputusan eksplisit pengguna)
- Kandidat ATR4/ADX30 tetap sebagai default parameter (lebih rendah DD dibanding ATR3),
  dengan peringatan jelas bahwa keunggulannya **belum terbukti secara statistik**
- Langkah selanjutnya: forward test di akun demo untuk membuktikan mekanisme dan mengukur biaya nyata (slippage, spread aktual)

---

## Keterbatasan

- Jumlah transaksi (398–1.232) belum cukup untuk membuktikan keunggulan kecil secara statistik (kesalahan baku ~1/√n)
- Strategi berbasis indikator klasik (EMA+ADX+RSI) rentan terhadap perubahan regime pasar
- Backtest mengasumsikan eksekusi di open candle berikutnya; slippage nyata bisa lebih buruk
- Data ini bukan rekomendasi investasi

---

*Dokumen ini adalah catatan ilmiah internal proyek. Diperbarui: 2026-11-16.*
