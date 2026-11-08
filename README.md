# PDDikti SDK Neo Feeder

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-e92063.svg)](https://docs.pydantic.dev/)

**PDDikti SDK Neo Feeder** adalah pustaka Python modern dan klien web service resmi untuk berkomunikasi dengan aplikasi **Neo Feeder PDDIKTI Kemendikbudristek** (`live2.php` dan `sandbox2.php`). 

Dirancang khusus untuk **Pengembang SIAKAD**, **Biro Akademik (BAAK)**, dan **Tim IT Perguruan Tinggi** di Indonesia guna mengotomatisasi sinkronisasi data mahasiswa, dosen, kurikulum, KRS, dan nilai perkuliahan.

---

## 🎯 Fitur Utama

1. **🔐 Auto-Handshake & Auto-Token Refresh:**
   - Melakukan otentikasi awal secara otomatis (`GetToken`).
   - Mendeteksi otomatis token sesi kedaluwarsa (error `100`, `106`, `expired`) dan me-refresh token baru tanpa menghentikan proses sinkronisasi (*transparent retry*).
2. **🌊 Streaming Generator Ramah Memori (`iter_records`):**
   - Mengambil data berukuran raksasa (puluhan ribu mahasiswa/KRS) secara bertahap (*batching/chunking*) menggunakan Python Generator sehingga konsumsi RAM server tetap rendah.
3. **⚡ Sinkron & Asinkron:**
   - Menyediakan `NeoFeederClient` (Sync) dan `AsyncNeoFeederClient` (Async via `httpx`) untuk integrasi dengan FastAPI, Celery, atau cron job.
4. **🛡️ Validasi Skema Model (Pydantic V2):**
   - Parsing otomatis data profil PT (`ProfilPerguruanTinggiFeeder`), Program Studi (`ProgramStudiFeeder`), Mahasiswa, dan Dosen.
5. **💻 Antarmuka Terminal (CLI `pddikti-feeder` / `neofeeder`):**
   - Uji koneksi, kueri data RPC, dan pembacaan kamus struktur tabel langsung dari terminal.

---

## 📦 Instalasi

```bash
pip install pddikti-sdk-neofeeder
```

Atau instalasi untuk development:

```bash
git clone https://github.com/banghamid/pddikti_sdk_neofeeder.git
cd pddikti_sdk_neofeeder
pip install -e .
```

---

## 💻 Penggunaan CLI (`pddikti-feeder`)

```bash
# 1. Bantuan perintah
pddikti-feeder --help

# 2. Uji koneksi & login ke server Neo Feeder lokal (default port 8100)
pddikti-feeder test -u operator_siakad -p password_rahasia

# 3. Uji koneksi dengan URL Feeder kustom (misal sandbox atau IP server lokal)
pddikti-feeder test --url http://192.168.1.100:8100/ws/live2.php -u admin -p rahasia

# 4. Kueri data (GetProfilPT, GetBiodataMahasiswa, dll)
pddikti-feeder query GetProfilPT -u operator_siakad -p password_rahasia
pddikti-feeder query GetBiodataMahasiswa --filter "id_prodi='...'" --limit 50 -u admin -p rahasia

# 5. Cek kamus struktur kolom tabel Feeder
pddikti-feeder dict GetBiodataMahasiswa -u operator_siakad -p password_rahasia
```

---

## 🚀 Panduan Penggunaan Python

### 1. Inisialisasi & Pengujian Koneksi

```python
from pddikti_feeder import NeoFeederClient

# Default base_url mengarah ke 'http://localhost:8100/ws/live2.php'
feeder = NeoFeederClient(
    username="operator_siakad",
    password="password_rahasia",
)

# Uji koneksi
status = feeder.test_connection()
print(f"Status Koneksi: {status['status'].upper()}")
```

### 2. Mengambil Profil Institusi & Program Studi

```python
# Profil perguruan tinggi terdaftar dalam model Pydantic
profil = feeder.get_profil_pt()
if profil:
    print(f"Kampus: {profil.nama_perguruan_tinggi} ({profil.kode_perguruan_tinggi})")

# Daftar seluruh program studi
daftar_prodi = feeder.get_daftar_prodi()
for prodi in daftar_prodi:
    print(f"[{prodi.kode_program_studi}] {prodi.nama_program_studi} ({prodi.nama_jenjang_pendidikan})")
```

### 3. Streaming Ribuan Data Mahasiswa / Nilai (Aman Memori)

```python
# Mengambil seluruh data mahasiswa secara bertahap 100 record per chunk
for mhs in feeder.iter_records("GetBiodataMahasiswa", chunk_size=100, max_records=1000):
    print(f"Nama: {mhs['nama_mahasiswa']} | NIK: {mhs.get('nik')}")
```

### 4. Eksekusi Asinkron (FastAPI / Asynchronous Pipeline)

```python
import asyncio
from pddikti_feeder import AsyncNeoFeederClient

async def main():
    async_feeder = AsyncNeoFeederClient(
        username="operator_siakad",
        password="password_rahasia",
    )
    res = await async_feeder.execute("GetProfilPT")
    print(res)

asyncio.run(main())
```

---

## 📁 Struktur Repositori

```text
pddikti_sdk_neofeeder/
├── src/
│   └── pddikti_feeder/
│       ├── __init__.py          # Export publik & versi modul
│       ├── client.py            # NeoFeederClient & AsyncNeoFeederClient
│       ├── exceptions.py        # FeederException, FeederAuthError, FeederConnectionError
│       ├── models.py            # Pydantic v2 data models
│       └── cli.py               # CLI tool pddikti-feeder & neofeeder
├── tests/
│   ├── test_client.py
│   └── test_cli.py
├── examples/
│   └── quickstart_feeder.py
├── pyproject.toml
└── README.md
```

---

## 🧪 Pengujian Unit

```bash
pytest -v
```

---

## 📄 Lisensi

Didistribusikan di bawah lisensi [MIT License](LICENSE). Hak Cipta (c) 2026 banghamid.
