# BLOCKERS.md

## Daftar Kendala / Hambatan

| Tanggal | Gejala / Masalah | Yang Sudah Dicoba | Dugaan / Analisis | Saran / Tindakan yang Diperlukan |
|---------|------------------|-------------------|-------------------|----------------------------------|
| - | Belum ada kendala kritis | - | - | - |
| 16/11/2026 | pytest via 9router timeout | Tes lokal jalan normal. Kendala ini hanya di lingkungan 9router, bukan di project. | Jalankan tes langsung: `..\.venv-new\Scripts\python.exe -m pytest -q` | Gunakan tes lokal; jangan menggantungkan validasi pada 9router |
