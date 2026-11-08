"""Command-Line Interface (CLI) untuk pddikti-sdk-neofeeder.

Menyediakan alat bantu terminal untuk menguji koneksi Feeder, mengeksekusi kueri RPC,
dan melihat skema kamus tabel (GetDictionary).
"""

import argparse
import json
import sys
from typing import List, Optional

from pddikti_feeder import (
    AsyncNeoFeederClient,
    FeederAuthError,
    FeederConnectionError,
    FeederException,
    NeoFeederClient,
    __version__,
)


def handle_test(args: argparse.Namespace) -> int:
    """Menguji koneksi dan login ke server Neo Feeder."""
    client = NeoFeederClient(
        base_url=args.url,
        username=args.user,
        password=args.password,
        timeout=args.timeout,
    )
    if not args.json:
        print(f"Menguji koneksi ke Neo Feeder pada {args.url}...")
    res = client.test_connection()

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print(f"\n=== HASIL KONEKSI NEO FEEDER ===")
    print(f"Status        : {res.get('status').upper()}")
    print(f"Pesan         : {res.get('message')}")
    print(f"Target URL    : {res.get('base_url')}")
    if res.get("token_preview"):
        print(f"Token Sesi    : {res.get('token_preview')}")
    if res.get("data"):
        print(f"Data Respon   : {json.dumps(res.get('data'), ensure_ascii=False)}")
    print()
    return 0 if res.get("status") == "connected" else 1


def handle_query(args: argparse.Namespace) -> int:
    """Mengeksekusi fungsi RPC Feeder."""
    client = NeoFeederClient(
        base_url=args.url,
        username=args.user,
        password=args.password,
        timeout=args.timeout,
    )
    kwargs = {}
    if args.filter:
        kwargs["filter"] = args.filter
    if args.order:
        kwargs["order"] = args.order
    if args.limit:
        kwargs["limit"] = args.limit
    if args.offset:
        kwargs["offset"] = args.offset

    try:
        res = client.execute(args.act, **kwargs)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except FeederException as e:
        print(f"Error [{e.error_code}]: {e.error_desc}", file=sys.stderr)
        return 1


def handle_dict(args: argparse.Namespace) -> int:
    """Mengambil struktur dictionary tabel Feeder."""
    client = NeoFeederClient(
        base_url=args.url,
        username=args.user,
        password=args.password,
        timeout=args.timeout,
    )
    try:
        res = client.get_dictionary(args.table)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except FeederException as e:
        print(f"Error [{e.error_code}]: {e.error_desc}", file=sys.stderr)
        return 1


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pddikti-feeder",
        description="Neo Feeder CLI - Alat Bantu Terminal untuk Integrasi Web Service Neo Feeder PDDIKTI Kampus.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"pddikti-sdk-neofeeder v{__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Perintah yang tersedia")

    # Command: test
    p_test = subparsers.add_parser("test", help="Uji koneksi & login ke server Feeder")
    p_test.add_argument("--url", default="http://localhost:8100/ws/live2.php", help="URL Web Service Feeder")
    p_test.add_argument("-u", "--user", default="", help="Username Feeder")
    p_test.add_argument("-p", "--password", default="", help="Password Feeder")
    p_test.add_argument("--timeout", type=float, default=60.0, help="Batas waktu koneksi (detik)")
    p_test.add_argument("--json", action="store_true", help="Keluarkan output JSON")

    # Command: query
    p_query = subparsers.add_parser("query", help="Panggil fungsi RPC Feeder (misal: GetProfilPT, GetBiodataMahasiswa)")
    p_query.add_argument("act", help="Nama aksi / fungsi Feeder")
    p_query.add_argument("--url", default="http://localhost:8100/ws/live2.php", help="URL Web Service Feeder")
    p_query.add_argument("-u", "--user", default="", help="Username Feeder")
    p_query.add_argument("-p", "--password", default="", help="Password Feeder")
    p_query.add_argument("--filter", help="Klausa filter (misal: \"id_prodi='123'\")")
    p_query.add_argument("--order", help="Klausa order (misal: \"nim ASC\")")
    p_query.add_argument("--limit", type=int, default=20, help="Batas jumlah record (default: 20)")
    p_query.add_argument("--offset", type=int, default=0, help="Offset record (default: 0)")
    p_query.add_argument("--timeout", type=float, default=60.0, help="Batas waktu koneksi (detik)")

    # Command: dict
    p_dict = subparsers.add_parser("dict", help="Ambil kamus data struktur tabel dari GetDictionary")
    p_dict.add_argument("table", help="Nama fungsi data (misal: 'GetBiodataMahasiswa', 'GetDosen')")
    p_dict.add_argument("--url", default="http://localhost:8100/ws/live2.php", help="URL Web Service Feeder")
    p_dict.add_argument("-u", "--user", default="", help="Username Feeder")
    p_dict.add_argument("-p", "--password", default="", help="Password Feeder")
    p_dict.add_argument("--timeout", type=float, default=60.0, help="Batas waktu koneksi (detik)")

    return parser


def main(args: Optional[List[str]] = None) -> int:
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if not parsed_args.command:
        parser.print_help()
        return 0

    if parsed_args.command == "test":
        return handle_test(parsed_args)
    elif parsed_args.command == "query":
        return handle_query(parsed_args)
    elif parsed_args.command == "dict":
        return handle_dict(parsed_args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
