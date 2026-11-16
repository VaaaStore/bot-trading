# Analisa Project: Bot Trading XAUUSD

> Dibuat: 2026-11-15  
> Sumber analisa: folder `source_code/`

---

## 1. Gambaran Umum

Bot trading otomatis untuk pasangan **XAUUSD (Emas)** berbasis **MetaTrader 5**, dibangun dengan Python 3.11. Proyek sedang dalam fase pengembangan aktif — fondasi logika sudah matang, namun **bot live belum bisa mengeksekusi order** (masih mode pantau).

---

## 2. Struktur Proyek

```
source_code/
├── main.py                  ← Entry point utama
├── bot/                     ← Modul inti bot live
│   ├── config.py            ← Konfigurasi dari file .env
│   ├── mt5_client.py        ← Wrapper MetaTrader5 (hanya baca data)
│   ├── strategy.py          ← Logika sinyal (EMA + ADX + RSI + ATR)
│   ├── indicators.py        ← Kalkulasi teknikal murni (pure functions)
│   ├── risk.py              ← Risk management (LossLock, spread/jam filter)
│   ├── trailing.py          ← Trailing stop bertingkat (R-multiple)
│   ├── state.py             ← Persistensi state ke data/state.json
│   ├── dashboard.py         ← Tampilan terminal (Rich library)
│   └── logger.py            ← Logging aktivitas bot
├── backtest/                ← Mesin backtest
│   ├── engine.py            ← Simulasi trading historis
│   ├── data.py              ← Load CSV + resample timeframe
│   ├── report.py            ← Laporan metrik backtest
│   ├── run_backtest.py      ← CLI runner backtest
│   └── experiments.py      ← Eksperimen parameter
├── tests/                   ← Unit tests (pytest)
│   ├── test_foundation.py   ← Test trailing, risk, state
│   ├── test_indicators.py   ← Test EMA, RSI, ATR, ADX
│   └── test_engine.py       ← Test mesin backtest
├── data/                    ← Data historis M1 (XAUUSD, BTCUSD)
└── requirements.txt         ← Dependensi: MT5, pandas, numpy, dotenv, rich
```

---

## 3. Strategi Trading

File: `bot/strategy.py`

Strategi menggunakan kombinasi **4 indikator teknikal**. Sinyal dihitung dari candle yang sudah tutup; eksekusi di candle berikutnya.

| Komponen        | Indikator        | Parameter Default | Fungsi                                      |
|-----------------|------------------|-------------------|---------------------------------------------|
| Filter Tren     | EMA Fast / Slow  | 20 / 50           | Konfirmasi arah tren                        |
| Konfirmasi Tren | ADX              | ≥ 30              | Hanya entry jika tren cukup kuat            |
| Pemicu BUY      | RSI              | Period 10, level 40 | Tren naik + RSI rebound dari bawah 40     |
| Pemicu SELL     | RSI              | Period 10, level 60 | Tren turun + RSI rebound dari atas 60     |
| Stop Loss       | ATR              | 14, multiplier 4.0 | Jarak SL = ATR × 4.0 = 1R                 |

**Desain kunci:** semua indikator dihitung murni dengan pandas/numpy (Wilder smoothing) di `bot/indicators.py` — **tidak bergantung MT5**, sehingga hasil backtest dan bot live identik 100%.

---

## 4. Risk Management

File: `bot/risk.py`

| Fitur              | Mekanisme                                                                 |
|--------------------|---------------------------------------------------------------------------|
| **LossLock**       | Berhenti trading setelah N SL rugi berturut-turut (default 3), reset tiap pergantian hari |
| **Filter Spread**  | Entry diblokir jika spread > `MAX_SPREAD` (opsional)                     |
| **Filter Jam**     | Entry hanya diizinkan dalam jendela jam server tertentu (opsional, support melewati tengah malam) |
| **Override Manual** | Pengguna bisa reset kunci LossLock secara manual                        |

---

## 5. Trailing Stop

File: `bot/trailing.py`

Sistem trailing stop **bertingkat berbasis R-multiple**:

```
Level 0 (awal)  : SL = entry − 1R  (SL rugi)
Level 1          : Saat profit ≥ 1.5R → SL pindah ke entry + 1R
Level 2          : Saat profit ≥ 2.5R → SL pindah ke entry + 2R
Level n          : Saat profit ≥ (n + 0.5)R → SL = entry + nR
```

- SL **tidak pernah mundur**
- `first_trigger_r` dapat dikonfigurasi (default 1.5)

---

## 6. Backtest Engine

File: `backtest/engine.py`

Simulasi mengikuti aturan konservatif:

- Entry di **open candle berikutnya** setelah sinyal
- Harga data adalah BID; buy entry pakai **ask = bid + spread**
- **Adverse move diasumsikan lebih dulu** dalam satu candle (konservatif)
- Menggunakan modul `risk.py` dan `trailing.py` yang **sama persis** dengan bot live
- Mendukung filter spread, filter jam, LossLock, resample timeframe, dan date range

### Hasil Backtest (Data 74 hari, Jul–Nov 2026, XAUUSD M1)

| Parameter          | Transaksi | Win Rate | Profit Factor | Max Drawdown | Net     |
|--------------------|-----------|----------|---------------|--------------|---------|
| ATR 1.5, ADX 20    | 452       | —        | —             | 58.3 R       | −47.4 R |
| **ATR 4, ADX 30** *(kandidat live)* | 130 | 42.3% | 1.23 | 11.0 R | **+17.1 R** |
| ATR 3, ADX 25      | 292       | 43.5%    | 1.32          | 13.4 R       | +52.0 R |

> ⚠️ **Peringatan:** Hasil backtest bukan jaminan performa nyata. Parameter yang disesuaikan dengan data lama biasanya gagal di data baru. Bot live menggunakan default **ATR 4 / ADX 30** dengan status belum terbukti di data out-of-sample.

---

## 7. Konfigurasi (.env)

File: `bot/config.py` — semua parameter dibaca dari `.env`

| Variabel                  | Default  | Keterangan                                      |
|---------------------------|----------|-------------------------------------------------|
| `ACCOUNT`                 | —        | Nomor akun MT5 (wajib)                          |
| `PASSWORD`                | —        | Password akun (wajib)                           |
| `SERVER`                  | —        | Nama server broker (wajib)                      |
| `SYMBOL`                  | XAUUSD   | Simbol yang diperdagangkan                      |
| `LOT_SIZE`                | 0.01     | Ukuran lot per transaksi                        |
| `MAX_SPREAD`              | (nonaktif) | Batas spread maksimum dalam poin             |
| `MAX_CONSECUTIVE_LOSS`    | 3        | LossLock: jumlah SL rugi sebelum pause          |
| `ATR_MULT`                | 4.0      | Pengali ATR untuk jarak SL                      |
| `ADX_MIN`                 | 30.0     | Batas minimum ADX untuk entry                   |
| `EMA_FAST`                | 20       | Period EMA cepat                                |
| `EMA_SLOW`                | 50       | Period EMA lambat                               |
| `RSI_PERIOD`              | 10       | Period RSI                                      |
| `TRAILING_MODE`           | step     | Mode trailing: `step` / `continuous` / `atr`   |
| `MAX_DAILY_LOSS_PERCENT`  | (nonaktif) | Batas kerugian harian dalam %               |
| `MAX_DRAWDOWN_PERCENT`    | (nonaktif) | Batas drawdown total dalam %                |

---

## 8. Status Tahapan

| Tahap | Status | Keterangan |
|-------|--------|------------|
| **Tahap 1** — Koneksi + Monitor Live | ✅ Selesai | MT5 connect, dashboard Rich, mode pantau harga live |
| **Tahap 3** — Fondasi Keandalan | ✅ Selesai | Modul risk, trailing, state, logger, unit test (23 passed) |
| **Tahap 2** — Eksekusi Order | ❌ Belum | `mt5_client.py` belum punya fungsi kirim order ke MT5 |
| **Tahap 4** — Bot Loop Live | ❌ Belum | `main.py` belum memanggil `strategy.py`; tidak ada loop sinyal |
| **Tahap 5** — Deployment & Monitoring | ❌ Belum | Belum ada restart otomatis, alerting, monitoring produksi |

---

## 9. Temuan & Catatan Teknis

### ✅ Kekuatan

- **Modularitas tinggi** — logika murni (indicators, risk, trailing) dipisah dari MT5, memudahkan unit testing
- **Backtest realistis** — engine menggunakan modul yang persis sama dengan bot live; spread ikut dihitung
- **Konfigurasi fleksibel** — semua parameter diekspos lewat `.env` tanpa perlu ubah kode
- **State persisten** — `state.py` menyimpan posisi dan status LossLock ke JSON secara atomik (write-to-tmp lalu rename)
- **Unit test** sudah mencakup komponen inti (23 tests passed)

### ⚠️ Gap & Isu yang Ditemukan

1. **Bot belum bisa trading** — `strategy.py` sudah lengkap tapi belum dipanggil dari `main.py` sama sekali; `mt5_client.py` juga belum punya method untuk kirim order
2. **`TRAILING_MODE` "continuous" dan "atr" belum diimplementasikan** — `config.py` menerima nilai tersebut tapi `trailing.py` hanya mengimplementasikan logika "step"
3. **Duplikasi fungsi `in_trading_hours()`** — ada di `backtest/engine.py` dan `bot/risk.py` dengan isi identik; sebaiknya dikonsolidasi
4. **Minor bug di `state.py`** — `load_state()` memanggil `dataclasses_fields(BotState)` pada baris 42, padahal fungsi `dataclasses_fields()` didefinisikan di bawahnya (baris 53); tidak crash karena ada guard `hasattr`, tapi alur kode tidak konsisten

---

## 10. Lingkungan & Dependensi

| Item | Detail |
|------|--------|
| Python | 3.11 (`.venv-new`) — 3.14 bermasalah DLL pandas di Windows |
| Dependensi utama | `MetaTrader5`, `pandas`, `numpy`, `python-dotenv`, `rich` |
| Testing | `pytest` |
| Data historis | XAUUSD M1 & BTCUSD M1 (CSV + JSON metadata) |
| Platform | Windows (diperlukan untuk MetaTrader5) |

---

## 11. Rekomendasi Langkah Berikutnya

1. **Implementasi `send_order()` di `mt5_client.py`** — fungsi untuk kirim market order buy/sell beserta SL ke MT5
2. **Integrasikan `strategy.py` ke `main.py`** — tambahkan trading loop yang membaca candle, generate sinyal, dan eksekusi order
3. **Implementasi trailing mode "continuous" dan "atr"** di `trailing.py` atau hapus opsi dari config jika tidak direncanakan
4. **Konsolidasi `in_trading_hours()`** — pindahkan ke satu tempat (misal `bot/risk.py`) dan import dari sana
5. **Tambah test out-of-sample** — jalankan backtest pada data yang belum digunakan untuk optimasi parameter
6. **Setup akun demo** — validasi end-to-end di akun demo MT5 sebelum live

---

*Dokumen ini dibuat otomatis dari analisa kode sumber. Perbarui seiring perubahan proyek.*
