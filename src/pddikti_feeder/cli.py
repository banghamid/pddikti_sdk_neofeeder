"""Command-Line Interface (CLI) untuk pddikti-sdk-neofeeder.

Menyediakan alat bantu terminal untuk menguji koneksi Feeder, mengeksekusi kueri RPC,
dan melihat skema kamus tabel (GetDictionary).
"""

import argparse
import json
import os
import sys
from typing import List, Optional

from pddikti_feeder import (
    FeederException,
    NeoFeederClient,
    __version__,
)


def _create_client(args: argparse.Namespace) -> NeoFeederClient:
    """Membuat instance NeoFeederClient dari argumen CLI."""
    return NeoFeederClient(
        base_url=args.url,
        username=args.user,
        password=args.password,
        timeout=args.timeout,
    )


def _print_cli_error(exc: Exception) -> None:
    """Mencetak pesan error aman ke stderr tanpa stack trace."""
    if isinstance(exc, FeederException):
        print(f"Error [{exc.error_code}]: {exc.error_desc}", file=sys.stderr)
    else:
        print(f"Error [400]: {exc}", file=sys.stderr)


def _add_connection_arguments(subparser: argparse.ArgumentParser) -> None:
    """Menambahkan argumen koneksi standar dengan fallback environment variable."""
    default_url = os.environ.get("NEOFEEDER_URL") or NeoFeederClient.DEFAULT_BASE_URL
    default_user = os.environ.get("NEOFEEDER_USER", "")
    default_password = os.environ.get("NEOFEEDER_PASSWORD", "")

    subparser.add_argument(
        "--url",
        default=default_url,
        help="URL Web Service Feeder (atau env NEOFEEDER_URL)",
    )
    subparser.add_argument(
        "-u",
        "--user",
        default=default_user,
        help="Username Feeder (atau env NEOFEEDER_USER)",
    )
    subparser.add_argument(
        "-p",
        "--password",
        default=default_password,
        help="Password Feeder (disarankan gunakan env NEOFEEDER_PASSWORD)",
    )
    subparser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Batas waktu koneksi (detik)",
    )


def handle_test(args: argparse.Namespace) -> int:
    """Menguji koneksi dan login ke server Neo Feeder."""
    try:
        client = _create_client(args)
        if not args.json:
            print(f"Menguji koneksi ke Neo Feeder pada {client.base_url}...")
        res = client.test_connection()
    except (FeederException, ValueError) as exc:
        if args.json:
            err_payload = {
                "status": "error",
                "message": exc.error_desc if isinstance(exc, FeederException) else str(exc),
                "base_url": args.url,
                "error_code": exc.error_code if isinstance(exc, FeederException) else 400,
            }
            print(json.dumps(err_payload, indent=2, ensure_ascii=False))
        else:
            _print_cli_error(exc)
        return 1

    exit_code = 0 if res.get("status") == "connected" else 1

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return exit_code

    status_text = str(res.get("status", "error") or "error").upper()
    print("\n=== HASIL KONEKSI NEO FEEDER ===")
    print(f"Status        : {status_text}")
    print(f"Pesan         : {res.get('message')}")
    print(f"Target URL    : {res.get('base_url')}")
    if res.get("token_preview"):
        print(f"Token Sesi    : {res.get('token_preview')}")
    if res.get("data"):
        print(f"Data Respon   : {json.dumps(res.get('data'), ensure_ascii=False)}")
    print()
    return exit_code


def handle_query(args: argparse.Namespace) -> int:
    """Mengeksekusi fungsi RPC Feeder."""
    kwargs = {}
    if args.filter:
        kwargs["filter"] = args.filter
    if args.order:
        kwargs["order"] = args.order
    if args.limit is not None:
        kwargs["limit"] = args.limit
    if args.offset is not None:
        kwargs["offset"] = args.offset

    try:
        client = _create_client(args)
        res = client.execute(args.act, **kwargs)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except (FeederException, ValueError) as exc:
        _print_cli_error(exc)
        return 1


def handle_dict(args: argparse.Namespace) -> int:
    """Mengambil struktur dictionary tabel Feeder."""
    try:
        client = _create_client(args)
        res = client.get_dictionary(args.table)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    except (FeederException, ValueError) as exc:
        _print_cli_error(exc)
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
    _add_connection_arguments(p_test)
    p_test.add_argument("--json", action="store_true", help="Keluarkan output JSON")

    # Command: query
    p_query = subparsers.add_parser("query", help="Panggil fungsi RPC Feeder (misal: GetProfilPT, GetBiodataMahasiswa)")
    p_query.add_argument("act", help="Nama aksi / fungsi Feeder")
    _add_connection_arguments(p_query)
    p_query.add_argument("--filter", help="Klausa filter (misal: \"id_prodi='123'\")")
    p_query.add_argument("--order", help="Klausa order (misal: \"nim ASC\")")
    p_query.add_argument("--limit", type=int, default=20, help="Batas jumlah record (default: 20)")
    p_query.add_argument("--offset", type=int, default=0, help="Offset record (default: 0)")

    # Command: dict
    p_dict = subparsers.add_parser("dict", help="Ambil kamus data struktur tabel dari GetDictionary")
    p_dict.add_argument("table", help="Nama fungsi data (misal: 'GetBiodataMahasiswa', 'GetDosen')")
    _add_connection_arguments(p_dict)

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
