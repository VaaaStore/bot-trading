# DECISIONS.md

## Catatan Keputusan Arsitektur dan Desain

| Tanggal | Masalah / Topik | Opsi yang Dipertimbangkan | Pilihan | Alasan | Dampak |
|---------|-----------------|---------------------------|---------|--------|--------|
| 11/11/2026 | Lokasi file agen & dokumen proyek | - Simpan di akar workspace<br>- Simpan di folder source_code | Simpan di akar `source_code` sesuai struktur workspace | Agar terbaca otomatis oleh agent dan selaras dengan `AGENT_BRIEF.txt` | Dokumen proyek terpusat |
| 11/11/2026 | Logika trailing & risk management | - Dipisah per modul<br>- Disatukan di engine | Membuat modul murni `bot/trailing.py` dan `bot/risk.py` | Memudahkan unit testing dan memastikan logika sinyal/trailing/pengunci dipakai bersama oleh backtest dan bot live. Catatan: hasil live bisa tetap berbeda karena slippage, spread nyata, dan latensi. | Kode lebih modular dan dapat diuji tanpa MT5 |
| 11/11/2026 | Lingkungan Python | - `.venv` (Python 3.14)<br>- `.venv-1`<br>- `.venv-new` (Python 3.11) | `.venv-new` (Python 3.11) | Python 3.14 terkena pembatasan Smart App Control DLL pandas di Windows, sedangkan `.venv-new` (Python 3.11) berjalan stabil tanpa error DLL load | Digunakan secara konsisten untuk tes (`pytest`), backtest, dan eksekusi bot |
| 16/11/2026 | Duplikasi `in_trading_hours` | - Dua implementasi identik di `backtest/engine.py` dan `bot/risk.py`<br>- Satu implementasi di `bot/risk.py`, diimport oleh engine | Hapus dari `engine.py`, gunakan import dari `bot/risk.py` | Satu sumber kebenaran; tes paritas memastikan fungsi identik | `backtest/engine.py` kini mengimport dari `bot/risk.py`; tes paritas `test_in_trading_hours_parity` ditambahkan |
| 16/11/2026 | TRAILING_MODE selain "step" | - Tolak di config dengan pesan jelas<br>- Terima tapi abaikan | Tolak eksplisit: hanya "step" yang diterima | "continuous" dan "atr" belum diimplementasikan; lebih aman menolak daripada menerima nilai yang tidak berdampak | Pesan error menyebut nilai yang tidak valid dan nilai yang diterima |
| 16/11/2026 | MODE dan ALLOW_REAL di config | - Belum ada di config<br>- Tambahkan sebagai field Config | Tambahkan `mode` (default signal_only) dan `allow_real` (default false) | Diperlukan oleh Tahap 4 (eksekusi live); default aman mencegah order tidak disengaja | `config.py` dan `.env.example` diperbarui |
| 16/11/2026 | Kandidat ATR4/ADX30 tidak terbukti | - Tetap pakai sebagai default dengan peringatan<br>- Ganti default<br>- Tolak pakai | Tetap sebagai default parameter (DD lebih rendah dibanding alternatif); default `MODE=signal_only` mencegah order nyata | Belum ada kandidat yang terbukti unggul; signal_only adalah lapisan keamanan kedua | Default parameter tetap ATR4/ADX30; dokumen jujur di `docs/results/uji_bersih.md` |

