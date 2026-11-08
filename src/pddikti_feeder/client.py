"""Konektor Neo Feeder PDDIKTI Web Service untuk sistem informasi kampus (SIAKAD).

Mendukung komunikasi RPC HTTP (live2.php / sandbox2.php), handshake token otomatis,
retry saat token kedaluwarsa, pagination generator, serta operasi data akademik kampus.
"""

import logging
import threading
from typing import Any, Dict, Generator, List, Optional, Union
import httpx

from pddikti_feeder.exceptions import (
    FeederAuthError,
    FeederConnectionError,
    FeederException,
)
from pddikti_feeder.models import (
    DosenFeeder,
    FeederResponse,
    MahasiswaFeeder,
    ProfilPerguruanTinggiFeeder,
    ProgramStudiFeeder,
)

logger = logging.getLogger("pddikti_feeder")


class NeoFeederClient:
    """Klien sinkron untuk berinteraksi dengan Neo Feeder PDDIKTI Web Service.

    Attributes:
        base_url: URL web service Neo Feeder (default: 'http://localhost:8100/ws/live2.php').
        username: Kode pengguna web service Feeder.
        password: Password pengguna web service Feeder.
        timeout: Batas waktu permintaan HTTP dalam detik (default: 60 detik).
    """

    DEFAULT_BASE_URL = "http://localhost:8100/ws/live2.php"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        username: str = "",
        password: str = "",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token: Optional[str] = None
        self._lock = threading.Lock()

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
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        self.base_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    error_code = data.get("error_code", 0)
                    error_desc = data.get("error_desc", "")

                    if error_code != 0:
                        raise FeederAuthError(
                            error_code=error_code,
                            error_desc=f"Autentikasi Feeder gagal: {error_desc}",
                        )

                    token_val = data.get("data", {}).get("token")
                    if not token_val:
                        raise FeederAuthError(
                            error_code=101,
                            error_desc="Token otentikasi tidak ditemukan dalam respon Feeder.",
                        )

                    self._token = token_val
                    logger.info("Berhasil memperoleh token otentikasi Neo Feeder.")
                    return self._token

            except httpx.RequestError as exc:
                raise FeederConnectionError(
                    error_code=503,
                    error_desc=f"Gagal terhubung ke Neo Feeder pada {self.base_url}: {str(exc)}",
                )

    def execute(self, act: str, **kwargs: Any) -> Dict[str, Any]:
        """Menjalankan aksi RPC Neo Feeder dengan auto-retry saat token kedaluwarsa.

        Args:
            act: Nama fungsi RPC Feeder (misal: 'GetProfilPT', 'GetBiodataMahasiswa', 'InsertRecord').
            **kwargs: Parameter filter, order, limit, offset, record, key.

        Returns:
            Dict respon resmi Feeder dengan format: {'error_code': int, 'error_desc': str, 'data': Any}.
        """
        if act == "GetToken":
            token = self.get_token(force_refresh=True)
            return {"error_code": 0, "error_desc": "", "data": {"token": token}}

        token = self.get_token()
        payload = {"act": act, "token": token, **kwargs}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.base_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                result = resp.json()

                error_code = result.get("error_code", 0)
                error_desc = str(result.get("error_desc", "")).lower()

                # Deteksi token expired (kode 100, 106, atau deskripsi expired)
                if error_code in (100, 106) or ("token" in error_desc and "expired" in error_desc):
                    logger.warning("Token Feeder kedaluwarsa, memperbarui token dan mencoba ulang...")
                    new_token = self.get_token(force_refresh=True)
                    payload["token"] = new_token
                    retry_resp = client.post(
                        self.base_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    retry_resp.raise_for_status()
                    result = retry_resp.json()

                return result

        except FeederException:
            raise
        except httpx.RequestError as exc:
            raise FeederConnectionError(
                error_code=503,
                error_desc=f"Koneksi ke Neo Feeder terputus ({self.base_url}): {str(exc)}",
            )
        except Exception as exc:
            raise FeederException(
                error_code=500,
                error_desc=f"Kesalahan klien Feeder: {str(exc)}",
            )

    def test_connection(self) -> Dict[str, Any]:
        """Menguji konektivitas dan validitas login ke server Neo Feeder."""
        try:
            token = self.get_token(force_refresh=True)
            res = self.execute("GetProfilPT", limit=1)
            return {
                "status": "connected",
                "message": "Koneksi dan otentikasi ke Neo Feeder berhasil.",
                "base_url": self.base_url,
                "token_preview": f"{token[:10]}..." if token else None,
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
        raw = data[0] if isinstance(data, list) and data else (data or {})
        if raw:
            return ProfilPerguruanTinggiFeeder.model_validate(raw)
        return None

    def get_daftar_prodi(self, filter: Optional[str] = None) -> List[ProgramStudiFeeder]:
        """Mengambil daftar seluruh program studi yang terdaftar di Feeder kampus."""
        kwargs: Dict[str, Any] = {}
        if filter:
            kwargs["filter"] = filter
        res = self.execute("GetProdi", **kwargs)
        raw_list = res.get("data", []) or []
        return [ProgramStudiFeeder.model_validate(item) for item in raw_list]

    def get_mahasiswa(
        self,
        filter: Optional[str] = None,
        order: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Mengambil data biodata / list mahasiswa terdaftar."""
        kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
        if filter:
            kwargs["filter"] = filter
        if order:
            kwargs["order"] = order
        res = self.execute("GetBiodataMahasiswa", **kwargs)
        return res.get("data", []) or []

    def get_dosen(
        self,
        filter: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Mengambil data dosen terdaftar di Feeder."""
        kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
        if filter:
            kwargs["filter"] = filter
        res = self.execute("GetDosen", **kwargs)
        return res.get("data", []) or []

    def get_dictionary(self, fungsi: str) -> Dict[str, Any]:
        """Mengambil kamus struktur kolom tabel Feeder (fungsi: misal 'GetBiodataMahasiswa')."""
        res = self.execute("GetDictionary", fungsi=fungsi)
        return res.get("data", {}) or {}

    def iter_records(
        self,
        act: str,
        filter: Optional[str] = None,
        order: Optional[str] = None,
        chunk_size: int = 100,
        max_records: Optional[int] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Generator untuk streaming data tabel secara bertahap tanpa membebani memori."""
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
            records = res.get("data", []) or []
            if not records:
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
        base_url: str = DEFAULT_BASE_URL,
        username: str = "",
        password: str = "",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token: Optional[str] = None

    async def get_token(self, force_refresh: bool = False) -> str:
        if self._token and not force_refresh:
            return self._token

        payload = {"act": "GetToken", "username": self.username, "password": self.password}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.base_url, json=payload, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            data = resp.json()

            error_code = data.get("error_code", 0)
            if error_code != 0:
                raise FeederAuthError(error_code=error_code, error_desc=f"Autentikasi Feeder gagal: {data.get('error_desc')}")

            token = data.get("data", {}).get("token")
            if not token:
                raise FeederAuthError(error_code=101, error_desc="Token tidak ditemukan dalam respon Feeder.")

            self._token = token
            return self._token

    async def execute(self, act: str, **kwargs: Any) -> Dict[str, Any]:
        if act == "GetToken":
            token = await self.get_token(force_refresh=True)
            return {"error_code": 0, "error_desc": "", "data": {"token": token}}

        token = await self.get_token()
        payload = {"act": act, "token": token, **kwargs}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.base_url, json=payload, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            result = resp.json()

            error_code = result.get("error_code", 0)
            error_desc = str(result.get("error_desc", "")).lower()

            if error_code in (100, 106) or ("token" in error_desc and "expired" in error_desc):
                new_token = await self.get_token(force_refresh=True)
                payload["token"] = new_token
                retry_resp = await client.post(self.base_url, json=payload, headers={"Content-Type": "application/json"})
                retry_resp.raise_for_status()
                result = retry_resp.json()

            return result
