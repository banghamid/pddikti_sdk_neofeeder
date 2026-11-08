"""Panduan Mulai Cepat (Quickstart) integrasi Neo Feeder PDDIKTI Kampus."""

from pddikti_feeder import NeoFeederClient


def main():
    print("=== QUICKSTART INTEGRASI NEO FEEDER KAMPUS ===\n")

    # Inisialisasi client Feeder (default port 8100)
    feeder = NeoFeederClient(
        base_url="http://localhost:8100/ws/live2.php",
        username="user_siakad",
        password="password_rahasia",
        timeout=60.0,
    )

    print(f"Server Target : {feeder.base_url}")
    print(f"Username      : {feeder.username}\n")

    # 1. Uji koneksi dan periksa sesi
    status = feeder.test_connection()
    print("Hasil Uji Koneksi:")
    print(f"- Status  : {status['status'].upper()}")
    print(f"- Pesan   : {status['message']}")
    if status.get("token_preview"):
        print(f"- Token   : {status['token_preview']}")

    # 2. Contoh pemanggilan kueri saat server online:
    # try:
    #     profil = feeder.get_profil_pt()
    #     print("Profil Kampus:", profil)
    #
    #     prodi = feeder.get_daftar_prodi()
    #     print(f"Total Prodi: {len(prodi)}")
    # except Exception as e:
    #     print("Gagal mengambil data:", e)


if __name__ == "__main__":
    main()
