"""Konektor Neo Feeder PDDIKTI Web Service untuk sistem informasi kampus (SIAKAD).

Mendukung komunikasi RPC HTTP (live2.php / sandbox2.php), handshake token otomatis,
retry saat token kedaluwarsa, pagination generator, serta operasi data akademik kampus.
"""

import asyncio
import logging
import os
import threading
from typing import Any, Dict, Generator, List, Optional
from urllib.parse import urlparse
import httpx

from pddikti_feeder.exceptions import (
    FeederAuthError,
    FeederConnectionError,
    FeederException,
)
from pddikti_feeder.models import (
    ProfilPerguruanTinggiFeeder,
    ProgramStudiFeeder,
)

logger = logging.getLogger("pddikti_feeder")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _validate_base_url(url: str) -> str:
    """Memvalidasi base_url agar hanya menggunakan skema HTTP/HTTPS dengan host yang valid."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("base_url harus menggunakan skema http:// atau https:// yang valid.")

    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    if scheme not in ("http", "https") or not hostname:
        raise ValueError("base_url harus menggunakan skema http:// atau https:// yang valid.")

    if scheme == "http" and hostname not in _LOCAL_HOSTS:
        logger.warning(
            "Menggunakan HTTP tanpa enkripsi TLS menuju host non-lokal (%s). "
            "Kredensial dan token dikirim dalam teks biasa.",
            hostname,
        )

    return cleaned


def _validate_timeout(timeout: float) -> float:
    """Memvalidasi nilai timeout harus berupa angka positif."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not (timeout > 0):
        raise ValueError("timeout harus lebih besar dari 0.")
    return float(timeout)


def _validate_act(act: str) -> str:
    """Memvalidasi nama aksi RPC tidak kosong."""
    if not isinstance(act, str) or not act.strip():
        raise ValueError("Parameter 'act' harus berupa string tidak kosong.")
    return act.strip()


def _parse_json_dict(resp: httpx.Response) -> Dict[str, Any]:
    """Mengurai respon HTTP menjadi dict JSON dengan penanganan error yang aman."""
    try:
        data = resp.json()
    except ValueError as exc:
        raise FeederException(
            error_code=502,
            error_desc="Respon dari server Neo Feeder bukan JSON yang valid.",
        ) from exc

    if not isinstance(data, dict):
        raise FeederException(
            error_code=502,
            error_desc="Format respon server Neo Feeder tidak valid (harus berupa objek JSON).",
        )
    return data


def _extract_token_from_response(data: Dict[str, Any]) -> str:
    """Mengekstrak token otentikasi dari respon GetToken dengan aman."""
    error_code = data.get("error_code", 0)
    error_desc = data.get("error_desc", "")

    if error_code != 0:
        raise FeederAuthError(
            error_code=error_code,
            error_desc=f"Autentikasi Feeder gagal: {error_desc}",
        )

    inner_data = data.get("data")
    token_val = inner_data.get("token") if isinstance(inner_data, dict) else None
    if not token_val or not isinstance(token_val, str):
        raise FeederAuthError(
            error_code=101,
            error_desc="Token otentikasi tidak ditemukan dalam respon Feeder.",
        )
    return token_val


def _is_token_expired_response(result: Dict[str, Any]) -> bool:
    """Mendeteksi apakah respon menandakan token sesi sudah kedaluwarsa."""
    error_code = result.get("error_code", 0)
    error_desc = str(result.get("error_desc", "")).lower()
    return error_code in (100, 106) or ("token" in error_desc and "expired" in error_desc)


def _mask_token(token: Optional[str]) -> Optional[str]:
    """Menyamarkan token agar tidak membocorkan informasi sensitif secara utuh."""
    if not token:
        return None
    return f"{token[:4]}...***" if len(token) > 8 else "***"


class NeoFeederClient:
    """Klien sinkron untuk berinteraksi dengan Neo Feeder PDDIKTI Web Service.

    Attributes:
        base_url: URL web service Neo Feeder (default: 'http://localhost:8100/ws/live2.php').
        username: Kode pengguna web service Feeder.
        password: Password pengguna web service Feeder.
        timeout: Batas waktu permintaan HTTP dalam detik (default: 60 detik).
        verify_ssl: Apakah sertifikat TLS/SSL diverifikasi pada koneksi HTTPS (default: True).
    """

    DEFAULT_BASE_URL = "http://localhost:8100/ws/live2.php"

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 60.0,
        verify_ssl: bool = True,
    ) -> None:
        raw_url = (os.environ.get("NEOFEEDER_URL") or self.DEFAULT_BASE_URL) if base_url is None else base_url
        self.base_url = _validate_base_url(raw_url)
        self.username = os.environ.get("NEOFEEDER_USER", "") if username is None else username
        self.password = os.environ.get("NEOFEEDER_PASSWORD", "") if password is None else password
        self.timeout = _validate_timeout(timeout)
        self.verify_ssl = bool(verify_ssl)
        self._token: Optional[str] = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(base_url={self.base_url!r}, "
            f"username={self.username!r}, password='***', "
            f"timeout={self.timeout!r}, verify_ssl={self.verify_ssl!r}, "
            f"token={'***' if self._token else None!r})"
        )

    def get_token(self, force_refresh: bool = False) -> str:
        """Mengambil atau memperbarui auth token Neo Feeder dengan thread-safety."""
        with self._lock:
            if self._token and not force_refresh:
                return self._token

            payload = {
                "act": "GetToken",
                "username": self.username,
                "password": self.password,
            }

            try:
                with httpx.Client(
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                    follow_redirects=False,
                ) as client:
                    resp = client.post(
                        self.base_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                    data = _parse_json_dict(resp)
                    self._token = _extract_token_from_response(data)
                    logger.info("Berhasil memperoleh token otentikasi Neo Feeder.")
                    return self._token

            except FeederException:
                raise
            except httpx.HTTPStatusError as exc:
                raise FeederConnectionError(
                    error_code=exc.response.status_code,
                    error_desc=(
                        f"Server Neo Feeder mengembalikan status HTTP "
                        f"{exc.response.status_code} ({self.base_url})."
                    ),
                ) from exc
            except httpx.RequestError as exc:
                raise FeederConnectionError(
                    error_code=503,
                    error_desc=f"Gagal terhubung ke Neo Feeder pada {self.base_url}: {str(exc)}",
                ) from exc

    def execute(self, act: str, **kwargs: Any) -> Dict[str, Any]:
        """Menjalankan aksi RPC Neo Feeder dengan auto-retry saat token kedaluwarsa.

        Args:
            act: Nama fungsi RPC Feeder (misal: 'GetProfilPT', 'GetBiodataMahasiswa', 'InsertRecord').
            **kwargs: Parameter filter, order, limit, offset, record, key.

        Returns:
            Dict respon resmi Feeder dengan format: {'error_code': int, 'error_desc': str, 'data': Any}.
        """
        act = _validate_act(act)

        if act == "GetToken":
            token = self.get_token(force_refresh=True)
            return {"error_code": 0, "error_desc": "", "data": {"token": token}}

        token = self.get_token()
        payload = {**kwargs, "act": act, "token": token}

        try:
            with httpx.Client(
                timeout=self.timeout,
                verify=self.verify_ssl,
                follow_redirects=False,
            ) as client:
                resp = client.post(
                    self.base_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                result = _parse_json_dict(resp)

                # Deteksi token expired (kode 100, 106, atau deskripsi expired)
                if _is_token_expired_response(result):
                    logger.warning("Token Feeder kedaluwarsa, memperbarui token dan mencoba ulang...")
                    new_token = self.get_token(force_refresh=True)
                    payload["token"] = new_token
                    retry_resp = client.post(
                        self.base_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    retry_resp.raise_for_status()
                    result = _parse_json_dict(retry_resp)

                return result

        except FeederException:
            raise
        except httpx.HTTPStatusError as exc:
            raise FeederConnectionError(
                error_code=exc.response.status_code,
                error_desc=(
                    f"Server Neo Feeder mengembalikan status HTTP "
                    f"{exc.response.status_code} ({self.base_url})."
                ),
            ) from exc
        except httpx.RequestError as exc:
            raise FeederConnectionError(
                error_code=503,
                error_desc=f"Koneksi ke Neo Feeder terputus ({self.base_url}): {str(exc)}",
            ) from exc
        except Exception as exc:
            raise FeederException(
                error_code=500,
                error_desc=f"Kesalahan klien Feeder: {str(exc)}",
            ) from exc

    def test_connection(self) -> Dict[str, Any]:
        """Menguji konektivitas dan validitas login ke server Neo Feeder."""
        try:
            token = self.get_token(force_refresh=True)
            res = self.execute("GetProfilPT", limit=1)
            return {
                "status": "connected",
                "message": "Koneksi dan otentikasi ke Neo Feeder berhasil.",
                "base_url": self.base_url,
                "token_preview": _mask_token(token),
                "data": res.get("data"),
            }
        except FeederException as fe:
            return {
                "status": "error",
                "message": fe.error_desc,
                "base_url": self.base_url,
                "error_code": fe.error_code,
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "base_url": self.base_url,
                "error_code": 500,
            }

    def get_profil_pt(self) -> Optional[ProfilPerguruanTinggiFeeder]:
        """Mengambil data profil perguruan tinggi dari Feeder dalam model bertipe."""
        res = self.execute("GetProfilPT")
        data = res.get("data")
        if isinstance(data, list):
            raw = data[0] if data and isinstance(data[0], dict) else {}
        elif isinstance(data, dict):
            raw = data
        else:
            raw = {}
        if raw:
            return ProfilPerguruanTinggiFeeder.model_validate(raw)
        return None

    def get_daftar_prodi(self, filter: Optional[str] = None) -> List[ProgramStudiFeeder]:
        """Mengambil daftar seluruh program studi yang terdaftar di Feeder kampus."""
        kwargs: Dict[str, Any] = {}
        if filter:
            kwargs["filter"] = filter
        res = self.execute("GetProdi", **kwargs)
        raw_list = res.get("data")
        if not isinstance(raw_list, list):
            return []
        return [ProgramStudiFeeder.model_validate(item) for item in raw_list]

    def get_mahasiswa(
        self,
        filter: Optional[str] = None,
        order: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Mengambil data biodata / list mahasiswa terdaftar."""
        if limit < 1:
            raise ValueError("limit harus lebih besar atau sama dengan 1.")
        if offset < 0:
            raise ValueError("offset tidak boleh bernilai negatif.")
        kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
        if filter:
            kwargs["filter"] = filter
        if order:
            kwargs["order"] = order
        res = self.execute("GetBiodataMahasiswa", **kwargs)
        data = res.get("data")
        return data if isinstance(data, list) else []

    def get_dosen(
        self,
        filter: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Mengambil data dosen terdaftar di Feeder."""
        if limit < 1:
            raise ValueError("limit harus lebih besar atau sama dengan 1.")
        if offset < 0:
            raise ValueError("offset tidak boleh bernilai negatif.")
        kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
        if filter:
            kwargs["filter"] = filter
        res = self.execute("GetDosen", **kwargs)
        data = res.get("data")
        return data if isinstance(data, list) else []

    def get_dictionary(self, fungsi: str) -> Dict[str, Any]:
        """Mengambil kamus struktur kolom tabel Feeder (fungsi: misal 'GetBiodataMahasiswa')."""
        if not isinstance(fungsi, str) or not fungsi.strip():
            raise ValueError("Parameter 'fungsi' harus berupa string tidak kosong.")
        res = self.execute("GetDictionary", fungsi=fungsi.strip())
        data = res.get("data")
        return data if isinstance(data, dict) else {}

    def iter_records(
        self,
        act: str,
        filter: Optional[str] = None,
        order: Optional[str] = None,
        chunk_size: int = 100,
        max_records: Optional[int] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Generator untuk streaming data tabel secara bertahap tanpa membebani memori."""
        if chunk_size <= 0:
            raise ValueError("chunk_size harus lebih besar dari 0")
        if max_records is not None and max_records <= 0:
            return

        offset = 0
        total_yielded = 0

        while True:
            limit = chunk_size
            if max_records is not None:
                sisa = max_records - total_yielded
                if sisa <= 0:
                    break
                limit = min(chunk_size, sisa)

            kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
            if filter:
                kwargs["filter"] = filter
            if order:
                kwargs["order"] = order

            res = self.execute(act, **kwargs)
            if res.get("error_code", 0) != 0:
                raise FeederException(
                    error_code=res.get("error_code", 500),
                    error_desc=str(res.get("error_desc", "Gagal mengambil data pada iter_records.")),
                    data=res.get("data"),
                )

            records = res.get("data")
            if not isinstance(records, list) or not records:
                break

            for rec in records:
                yield rec
                total_yielded += 1
                if max_records is not None and total_yielded >= max_records:
                    return

            if len(records) < limit:
                break

            offset += len(records)


class AsyncNeoFeederClient:
    """Klien asinkron untuk berinteraksi dengan Neo Feeder (untuk integrasi FastAPI/async framework)."""

    DEFAULT_BASE_URL = "http://localhost:8100/ws/live2.php"

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 60.0,
        verify_ssl: bool = True,
    ) -> None:
        raw_url = (os.environ.get("NEOFEEDER_URL") or self.DEFAULT_BASE_URL) if base_url is None else base_url
        self.base_url = _validate_base_url(raw_url)
        self.username = os.environ.get("NEOFEEDER_USER", "") if username is None else username
        self.password = os.environ.get("NEOFEEDER_PASSWORD", "") if password is None else password
        self.timeout = _validate_timeout(timeout)
        self.verify_ssl = bool(verify_ssl)
        self._token: Optional[str] = None
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(base_url={self.base_url!r}, "
            f"username={self.username!r}, password='***', "
            f"timeout={self.timeout!r}, verify_ssl={self.verify_ssl!r}, "
            f"token={'***' if self._token else None!r})"
        )

    async def get_token(self, force_refresh: bool = False) -> str:
        """Mengambil atau memperbarui auth token Neo Feeder secara asinkron dengan lock."""
        async with self._lock:
            if self._token and not force_refresh:
                return self._token

            payload = {"act": "GetToken", "username": self.username, "password": self.password}
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                    follow_redirects=False,
                ) as client:
                    resp = await client.post(
                        self.base_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                    data = _parse_json_dict(resp)
                    self._token = _extract_token_from_response(data)
                    logger.info("Berhasil memperoleh token otentikasi Neo Feeder (async).")
                    return self._token

            except FeederException:
                raise
            except httpx.HTTPStatusError as exc:
                raise FeederConnectionError(
                    error_code=exc.response.status_code,
                    error_desc=(
                        f"Server Neo Feeder mengembalikan status HTTP "
                        f"{exc.response.status_code} ({self.base_url})."
                    ),
                ) from exc
            except httpx.RequestError as exc:
                raise FeederConnectionError(
                    error_code=503,
                    error_desc=f"Gagal terhubung ke Neo Feeder pada {self.base_url}: {str(exc)}",
                ) from exc

    async def execute(self, act: str, **kwargs: Any) -> Dict[str, Any]:
        """Menjalankan aksi RPC Neo Feeder secara asinkron dengan auto-retry saat token kedaluwarsa."""
        act = _validate_act(act)

        if act == "GetToken":
            token = await self.get_token(force_refresh=True)
            return {"error_code": 0, "error_desc": "", "data": {"token": token}}

        token = await self.get_token()
        payload = {**kwargs, "act": act, "token": token}

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                verify=self.verify_ssl,
                follow_redirects=False,
            ) as client:
                resp = await client.post(
                    self.base_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                result = _parse_json_dict(resp)

                if _is_token_expired_response(result):
                    logger.warning("Token Feeder kedaluwarsa (async), memperbarui token dan mencoba ulang...")
                    new_token = await self.get_token(force_refresh=True)
                    payload["token"] = new_token
                    retry_resp = await client.post(
                        self.base_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    retry_resp.raise_for_status()
                    result = _parse_json_dict(retry_resp)

                return result

        except FeederException:
            raise
        except httpx.HTTPStatusError as exc:
            raise FeederConnectionError(
                error_code=exc.response.status_code,
                error_desc=(
                    f"Server Neo Feeder mengembalikan status HTTP "
                    f"{exc.response.status_code} ({self.base_url})."
                ),
            ) from exc
        except httpx.RequestError as exc:
            raise FeederConnectionError(
                error_code=503,
                error_desc=f"Koneksi ke Neo Feeder terputus ({self.base_url}): {str(exc)}",
            ) from exc
        except Exception as exc:
            raise FeederException(
                error_code=500,
                error_desc=f"Kesalahan klien Feeder: {str(exc)}",
            ) from exc
