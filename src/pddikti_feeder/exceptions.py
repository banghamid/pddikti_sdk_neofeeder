"""Definisi hierarki exception untuk pddikti-sdk-neofeeder."""

from typing import Any, Optional


class FeederException(Exception):
    """Exception dasar untuk semua kesalahan komunikasi dan respon dari server Neo Feeder."""

    def __init__(self, error_code: int, error_desc: str, data: Any = None) -> None:
        self.error_code = error_code
        self.error_desc = error_desc
        self.data = data
        super().__init__(f"Feeder Error [{error_code}]: {error_desc}")


class FeederAuthError(FeederException):
    """Terjadi ketika otentikasi login / token Neo Feeder ditolak."""
    pass


class FeederConnectionError(FeederException):
    """Terjadi ketika koneksi jaringan ke server Neo Feeder terputus atau timeout."""
    pass
