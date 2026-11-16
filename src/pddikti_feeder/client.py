"""Konektor Neo Feeder PDDIKTI Web Service untuk sistem informasi kampus (SIAKAD).

Mendukung komunikasi RPC HTTP (live2.php / sandbox2.php), handshake token otomatis,
retry saat token kedaluwarsa, pagination generator, serta operasi data akademik kampus.
"""

import asyncio
import ipaddress
import logging
import os
import re
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
_BLOCKED_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "instance-data",
    "100.100.100.200",
    "fd00:ec2::254",
}
_ACT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_ORDER_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*(\s+(ASC|DESC))?(\s*,\s*[A-Za-z_][A-Za-z0-9_.]*(\s+(ASC|DESC))?)*$",
    re.IGNORECASE,
)
_DANGEROUS_FILTER_SQL_RE = re.compile(
    r"\b(UNION|DROP|ALTER|TRUNCATE|EXEC|EXECUTE|INTO\s+OUTFILE|INTO\s+DUMPFILE|SLEEP|BENCHMARK|PG_SLEEP)\b",
    re.IGNORECASE,
)
_MAX_RESPONSE_BYTES = 50 * 1024 * 1024
_MAX_LIMIT = 10000
_MAX_ERROR_MESSAGE_LEN = 500


def _validate_base_url(url: str) -> str:
    """Memvalidasi base_url agar hanya menggunakan skema HTTP/HTTPS dan bebas risiko SSRF."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("base_url harus menggunakan skema http:// atau https:// yang valid.")

    cleaned = url.strip().rstrip("/")
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("base_url tidak boleh mengandung karakter kontrol.")

    parsed = urlparse(cleaned)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url tidak boleh mengandung kredensial tertanam.")
    if parsed.fragment or parsed.query:
        raise ValueError("base_url tidak boleh mengandung query string atau fragment.")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("base_url memiliki nomor port yang tidak valid.") from exc

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    if scheme not in ("http", "https") or not hostname:
        raise ValueError("base_url harus menggunakan skema http:// atau https:// yang valid.")

    if hostname in _BLOCKED_METADATA_HOSTS:
        raise ValueError(f"base_url mengarah ke host metadata terlarang ({hostname}).")

    host_for_ip = hostname.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(host_for_ip)
    except ValueError:
        ip = None

    if ip is not None:
        ips_to_check = [ip]
        if getattr(ip, "ipv4_mapped", None) is not None:
            ips_to_check.append(ip.ipv4_mapped)
        for addr in ips_to_check:
            if addr.is_link_local or addr.is_unspecified or addr.is_multicast:
                raise ValueError(f"base_url mengarah ke alamat IP terlarang ({hostname}).")

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


def _resolve_verify_ssl(verify_ssl: bool) -> bool:
    """Memvalidasi flag verify_ssl dan mencatat peringatan jika verifikasi TLS dinonaktifkan."""
    enabled = bool(verify_ssl)
    if not enabled:
        logger.warning(
            "Verifikasi sertifikat SSL/TLS dinonaktifkan (verify_ssl=False). "
            "Koneksi rentan terhadap serangan Man-in-the-Middle (MITM)."
        )
    return enabled


def _validate_act(act: str, param_name: str = "act") -> str:
    """Memvalidasi nama aksi RPC atau fungsi tabel agar hanya berisi identifier aman."""
    if not isinstance(act, str) or not act.strip():
        raise ValueError(f"Parameter '{param_name}' harus berupa string tidak kosong.")
    cleaned = act.strip()
    if not _ACT_PATTERN.match(cleaned):
        raise ValueError(
            f"Parameter '{param_name}' hanya boleh berisi huruf, angka, dan underscore (maksimal 128 karakter)."
        )
    return cleaned


def _validate_filter_clause(filter_str: Optional[str]) -> Optional[str]:
    """Memvalidasi klausa filter terhadap karakter kontrol dan pola injeksi SQL berbahaya."""
    if filter_str is None:
        return None
    if not isinstance(filter_str, str):
        raise ValueError("Parameter 'filter' harus berupa string.")
    cleaned = filter_str.strip()
    if not cleaned:
        return None
    if any((ord(c) < 32 and c != "\t") or ord(c) == 127 for c in cleaned):
        raise ValueError("Parameter 'filter' mengandung karakter kontrol yang tidak diizinkan.")
    if ";" in cleaned or "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise ValueError("Parameter 'filter' mengandung urutan karakter SQL yang tidak diizinkan.")
    if _DANGEROUS_FILTER_SQL_RE.search(cleaned):
        raise ValueError("Parameter 'filter' mengandung kata kunci SQL yang tidak diizinkan.")
    return cleaned


def _validate_order_clause(order_str: Optional[str]) -> Optional[str]:
    """Memvalidasi klausa order agar sesuai dengan format nama kolom dan arah urut."""
    if order_str is None:
        return None
    if not isinstance(order_str, str):
        raise ValueError("Parameter 'order' harus berupa string.")
    cleaned = order_str.strip()
    if not cleaned:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("Parameter 'order' mengandung karakter kontrol yang tidak diizinkan.")
    if ";" in cleaned or "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise ValueError("Parameter 'order' mengandung urutan karakter SQL yang tidak diizinkan.")
    if not _ORDER_PATTERN.match(cleaned):
        raise ValueError("Format parameter 'order' tidak valid (contoh valid: 'nim ASC').")
    return cleaned


def _validate_limit(limit: int, field_name: str = "limit") -> int:
    """Memvalidasi nilai limit/chunk_size sebagai bilangan bulat dalam rentang aman."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError(f"{field_name} harus berupa bilangan bulat (integer).")
    if limit < 1 or limit > _MAX_LIMIT:
        raise ValueError(f"{field_name} harus bernilai antara 1 dan {_MAX_LIMIT}.")
    return limit


def _validate_offset(offset: int) -> int:
    """Memvalidasi nilai offset sebagai bilangan bulat non-negatif."""
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ValueError("offset harus berupa bilangan bulat (integer).")
    if offset < 0:
        raise ValueError("offset tidak boleh bernilai negatif.")
    return offset


def _prepare_execute_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Memvalidasi argumen RPC umum sebelum dikirim ke server Neo Feeder."""
    validated = dict(kwargs)
    if "filter" in validated:
        cleaned_filter = _validate_filter_clause(validated["filter"])
        if cleaned_filter is None:
            validated.pop("filter")
        else:
            validated["filter"] = cleaned_filter
    if "order" in validated:
        cleaned_order = _validate_order_clause(validated["order"])
        if cleaned_order is None:
            validated.pop("order")
        else:
            validated["order"] = cleaned_order
    if "limit" in validated and validated["limit"] is not None:
        validated["limit"] = _validate_limit(validated["limit"])
    if "offset" in validated and validated["offset"] is not None:
        validated["offset"] = _validate_offset(validated["offset"])
    return validated


def _sanitize_error_message(message: str, *secrets: Optional[str]) -> str:
    """Menyamarkan nilai rahasia pada pesan error dan membatasi panjang pesan."""
    sanitized = str(message)
    for secret in secrets:
        if secret and isinstance(secret, str):
            sanitized = sanitized.replace(secret, "***")
    if len(sanitized) > _MAX_ERROR_MESSAGE_LEN:
        return f"{sanitized[:_MAX_ERROR_MESSAGE_LEN]}..."
    return sanitized


def _parse_json_dict(resp: httpx.Response) -> Dict[str, Any]:
    """Mengurai respon HTTP menjadi dict JSON dengan pembatasan ukuran respon."""
    headers = getattr(resp, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        content_length = headers.get("Content-Length") or headers.get("content-length")
        if isinstance(content_length, str) and content_length.strip():
            try:
                if int(content_length.strip()) > _MAX_RESPONSE_BYTES:
                    raise FeederException(
                        error_code=502,
                        error_desc="Ukuran respon dari server Neo Feeder melebihi batas maksimum yang diizinkan.",
                    )
            except ValueError:
                pass

    raw_content = getattr(resp, "content", None)
    if isinstance(raw_content, (bytes, bytearray)) and len(raw_content) > _MAX_RESPONSE_BYTES:
        raise FeederException(
            error_code=502,
            error_desc="Ukuran respon dari server Neo Feeder melebihi batas maksimum yang diizinkan.",
        )

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
    token_str = str(token)
    return f"{token_str[:4]}...***" if len(token_str) > 8 else "***"


def _build_http_status_error(exc: httpx.HTTPStatusError, base_url: str) -> FeederConnectionError:
    """Membungkus httpx.HTTPStatusError menjadi FeederConnectionError yang aman."""
    return FeederConnectionError(
        error_code=exc.response.status_code,
        error_desc=(
            f"Server Neo Feeder mengembalikan status HTTP "
            f"{exc.response.status_code} ({base_url})."
        ),
    )


def _build_request_error(
    context_msg: str,
    exc: httpx.RequestError,
    *secrets: Optional[str],
) -> FeederConnectionError:
    """Membungkus httpx.RequestError menjadi FeederConnectionError dengan pesan tersanitasi."""
    return FeederConnectionError(
        error_code=503,
        error_desc=f"{context_msg}: {_sanitize_error_message(str(exc), *secrets)}",
    )


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
        self.verify_ssl = _resolve_verify_ssl(verify_ssl)
        self._token: Optional[str] = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(base_url={self.base_url!r}, "
            f"username={self.username!r}, password='***', "
            f"timeout={self.timeout!r}, verify_ssl={self.verify_ssl!r}, "
            f"token={'***' if self._token else None!r})"
        )

    def get_token(self, force_refresh: bool = False, stale_token: Optional[str] = None) -> str:
        """Mengambil atau memperbarui auth token Neo Feeder dengan thread-safety."""
        with self._lock:
            if stale_token is not None and self._token and self._token != stale_token:
                return self._token
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
                raise _build_http_status_error(exc, self.base_url) from exc
            except httpx.RequestError as exc:
                raise _build_request_error(
                    f"Gagal terhubung ke Neo Feeder pada {self.base_url}",
                    exc,
                    self.password,
                    self._token,
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
        validated_kwargs = _prepare_execute_kwargs(kwargs)

        if act == "GetToken":
            token = self.get_token(force_refresh=True)
            return {"error_code": 0, "error_desc": "", "data": {"token": token}}

        token = self.get_token()
        payload = {**validated_kwargs, "act": act, "token": token}

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
                    new_token = self.get_token(force_refresh=True, stale_token=token)
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
            raise _build_http_status_error(exc, self.base_url) from exc
        except httpx.RequestError as exc:
            raise _build_request_error(
                f"Koneksi ke Neo Feeder terputus ({self.base_url})",
                exc,
                self.password,
                self._token,
                token,
            ) from exc
        except Exception as exc:
            raise FeederException(
                error_code=500,
                error_desc=f"Kesalahan klien Feeder: {_sanitize_error_message(str(exc), self.password, self._token, token)}",
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
                "message": _sanitize_error_message(fe.error_desc, self.password, self._token),
                "base_url": self.base_url,
                "error_code": fe.error_code,
            }
        except Exception as e:
            return {
                "status": "error",
                "message": _sanitize_error_message(str(e), self.password, self._token),
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
        validated_filter = _validate_filter_clause(filter)
        kwargs: Dict[str, Any] = {}
        if validated_filter:
            kwargs["filter"] = validated_filter
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
        validated_limit = _validate_limit(limit)
        validated_offset = _validate_offset(offset)
        validated_filter = _validate_filter_clause(filter)
        validated_order = _validate_order_clause(order)
        kwargs: Dict[str, Any] = {"limit": validated_limit, "offset": validated_offset}
        if validated_filter:
            kwargs["filter"] = validated_filter
        if validated_order:
            kwargs["order"] = validated_order
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
        validated_limit = _validate_limit(limit)
        validated_offset = _validate_offset(offset)
        validated_filter = _validate_filter_clause(filter)
        kwargs: Dict[str, Any] = {"limit": validated_limit, "offset": validated_offset}
        if validated_filter:
            kwargs["filter"] = validated_filter
        res = self.execute("GetDosen", **kwargs)
        data = res.get("data")
        return data if isinstance(data, list) else []

    def get_dictionary(self, fungsi: str) -> Dict[str, Any]:
        """Mengambil kamus struktur kolom tabel Feeder (fungsi: misal 'GetBiodataMahasiswa')."""
        cleaned_fungsi = _validate_act(fungsi, param_name="fungsi")
        res = self.execute("GetDictionary", fungsi=cleaned_fungsi)
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
        validated_act = _validate_act(act)
        validated_chunk_size = _validate_limit(chunk_size, field_name="chunk_size")
        if max_records is not None:
            if isinstance(max_records, bool) or not isinstance(max_records, int):
                raise ValueError("max_records harus berupa bilangan bulat (integer).")
            if max_records <= 0:
                return
        validated_filter = _validate_filter_clause(filter)
        validated_order = _validate_order_clause(order)

        offset = 0
        total_yielded = 0

        while True:
            limit = validated_chunk_size
            if max_records is not None:
                sisa = max_records - total_yielded
                if sisa <= 0:
                    break
                limit = min(validated_chunk_size, sisa)

            kwargs: Dict[str, Any] = {"limit": limit, "offset": offset}
            if validated_filter:
                kwargs["filter"] = validated_filter
            if validated_order:
                kwargs["order"] = validated_order

            res = self.execute(validated_act, **kwargs)
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
        self.verify_ssl = _resolve_verify_ssl(verify_ssl)
        self._token: Optional[str] = None
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(base_url={self.base_url!r}, "
            f"username={self.username!r}, password='***', "
            f"timeout={self.timeout!r}, verify_ssl={self.verify_ssl!r}, "
            f"token={'***' if self._token else None!r})"
        )

    async def get_token(self, force_refresh: bool = False, stale_token: Optional[str] = None) -> str:
        """Mengambil atau memperbarui auth token Neo Feeder secara asinkron dengan lock."""
        async with self._lock:
            if stale_token is not None and self._token and self._token != stale_token:
                return self._token
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
                raise _build_http_status_error(exc, self.base_url) from exc
            except httpx.RequestError as exc:
                raise _build_request_error(
                    f"Gagal terhubung ke Neo Feeder pada {self.base_url}",
                    exc,
                    self.password,
                    self._token,
                ) from exc

    async def execute(self, act: str, **kwargs: Any) -> Dict[str, Any]:
        """Menjalankan aksi RPC Neo Feeder secara asinkron dengan auto-retry saat token kedaluwarsa."""
        act = _validate_act(act)
        validated_kwargs = _prepare_execute_kwargs(kwargs)

        if act == "GetToken":
            token = await self.get_token(force_refresh=True)
            return {"error_code": 0, "error_desc": "", "data": {"token": token}}

        token = await self.get_token()
        payload = {**validated_kwargs, "act": act, "token": token}

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
                    new_token = await self.get_token(force_refresh=True, stale_token=token)
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
            raise _build_http_status_error(exc, self.base_url) from exc
        except httpx.RequestError as exc:
            raise _build_request_error(
                f"Koneksi ke Neo Feeder terputus ({self.base_url})",
                exc,
                self.password,
                self._token,
                token,
            ) from exc
        except Exception as exc:
            raise FeederException(
                error_code=500,
                error_desc=f"Kesalahan klien Feeder: {_sanitize_error_message(str(exc), self.password, self._token, token)}",
            ) from exc
