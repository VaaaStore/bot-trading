# DECISIONS.md

## Catatan Keputusan Arsitektur dan Desain

| Tanggal | Masalah / Topik | Opsi yang Dipertimbangkan | Pilihan | Alasan | Dampak |
|---------|-----------------|---------------------------|---------|--------|--------|
| 11/11/2026 | Lokasi file agen & dokumen proyek | - Simpan di akar workspace<br>- Simpan di folder source_code | Simpan di akar `source_code` sesuai struktur workspace | Agar terbaca otomatis oleh agent dan selaras dengan `AGENT_BRIEF.txt` | Dokumen proyek terpusat |
| 11/11/2026 | Logika trailing & risk management | - Dipisah per modul<br>- Disatukan di engine | Membuat modul murni `bot/trailing.py` dan `bot/risk.py` | Menjamin paritas 100% antara backtest dan bot live serta memudahkan unit testing | Kode lebih modular dan dapat diuji tanpa MT5 |
| 11/11/2026 | Lingkungan Python | - `.venv` (Python 3.14)<br>- `.venv-1`<br>- `.venv-new` (Python 3.11) | `.venv-new` (Python 3.11) | Python 3.14 terkena pembatasan Smart App Control DLL pandas di Windows, sedangkan `.venv-new` (Python 3.11) berjalan stabil tanpa error DLL load | Digunakan secara konsisten untuk tes (`pytest`), backtest, dan eksekusi bot |

