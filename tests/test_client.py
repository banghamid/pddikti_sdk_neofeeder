import asyncio
import logging
from unittest.mock import MagicMock, patch
import httpx
import pytest

from pddikti_feeder import (
    AsyncNeoFeederClient,
    FeederAuthError,
    FeederConnectionError,
    FeederException,
    NeoFeederClient,
    ProfilPerguruanTinggiFeeder,
    ProgramStudiFeeder,
)
from pddikti_feeder.client import _MAX_RESPONSE_BYTES


def test_feeder_client_init():
    client = NeoFeederClient(
        base_url="http://localhost:8100/ws/live2.php",
        username="admin_feeder",
        password="secret_password",
        timeout=30.0,
    )
    assert client.base_url == "http://localhost:8100/ws/live2.php"
    assert client.username == "admin_feeder"
    assert client.timeout == 30.0


def test_feeder_get_token_success():
    client = NeoFeederClient(username="user1", password="pass1")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "error_code": 0,
        "error_desc": "",
        "data": {"token": "token_berhasil_123"},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_resp):
        token = client.get_token()
        assert token == "token_berhasil_123"


def test_feeder_get_token_auth_failed():
    client = NeoFeederClient(username="bad_user", password="bad_password")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "error_code": 102,
        "error_desc": "Kredensial salah",
        "data": None,
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(FeederAuthError) as exc_info:
            client.get_token(force_refresh=True)
        assert exc_info.value.error_code == 102


def test_feeder_execute_and_token_refresh():
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "token_lama_expired"

    resp_expired = MagicMock()
    resp_expired.json.return_value = {
        "error_code": 100,
        "error_desc": "Token expired",
        "data": None,
    }
    resp_expired.raise_for_status = MagicMock()

    resp_token = MagicMock()
    resp_token.json.return_value = {
        "error_code": 0,
        "error_desc": "",
        "data": {"token": "token_baru_segar"},
    }
    resp_token.raise_for_status = MagicMock()

    resp_success = MagicMock()
    resp_success.json.return_value = {
        "error_code": 0,
        "error_desc": "",
        "data": [{"nama_perguruan_tinggi": "Politeknik Negeri", "kode_perguruan_tinggi": "005001"}],
    }
    resp_success.raise_for_status = MagicMock()

    with patch("httpx.Client.post", side_effect=[resp_expired, resp_token, resp_success]):
        result = client.execute("GetProfilPT")
        assert result["error_code"] == 0
        assert client._token == "token_baru_segar"


def test_feeder_get_profil_pt():
    client = NeoFeederClient()
    mock_data = {
        "error_code": 0,
        "data": [{"nama_perguruan_tinggi": "Universitas Indonesia", "kode_perguruan_tinggi": "001001"}],
    }
    with patch.object(client, "execute", return_value=mock_data):
        pt = client.get_profil_pt()
        assert pt is not None
        assert isinstance(pt, ProfilPerguruanTinggiFeeder)
        assert pt.nama_perguruan_tinggi == "Universitas Indonesia"
        assert pt.kode_perguruan_tinggi == "001001"


def test_feeder_iter_records():
    client = NeoFeederClient()
    client._token = "valid_token"

    chunk_1 = {"error_code": 0, "data": [{"id": 1}, {"id": 2}]}
    chunk_2 = {"error_code": 0, "data": [{"id": 3}]}
    chunk_3 = {"error_code": 0, "data": []}

    with patch.object(client, "execute", side_effect=[chunk_1, chunk_2, chunk_3]):
        records = list(client.iter_records("GetBiodataMahasiswa", chunk_size=2))
        assert len(records) == 3
        assert records[0]["id"] == 1
        assert records[2]["id"] == 3


def test_async_feeder_execute():
    client = AsyncNeoFeederClient()
    client._token = "valid_async_token"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error_code": 0, "data": [{"nama_program_studi": "Teknik Informatika"}]}
    mock_resp.raise_for_status = MagicMock()

    async def _runner():
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            res = await client.execute("GetProdi")
            assert res["data"][0]["nama_program_studi"] == "Teknik Informatika"

    asyncio.run(_runner())


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "ftp://feeder.example.ac.id/ws/live2.php",
        "javascript:alert(1)",
        "",
        "   ",
        "http://",
        "localhost:8100/ws/live2.php",
    ],
)
def test_reject_unsafe_or_invalid_base_url(bad_url):
    with pytest.raises(ValueError):
        NeoFeederClient(base_url=bad_url)
    with pytest.raises(ValueError):
        AsyncNeoFeederClient(base_url=bad_url)


def test_repr_masks_credentials_and_token():
    client = NeoFeederClient(
        base_url="https://feeder.kampus.ac.id/ws/live2.php",
        username="admin_feeder",
        password="super_secret_password_123",
    )
    client._token = "secret_token_value_999"
    rendered = repr(client)

    assert "password='***'" in rendered
    assert "super_secret_password_123" not in rendered
    assert "secret_token_value_999" not in rendered

    async_client = AsyncNeoFeederClient(
        base_url="https://feeder.kampus.ac.id/ws/live2.php",
        username="admin_async",
        password="async_secret_password_456",
    )
    async_client._token = "async_secret_token_888"
    async_rendered = repr(async_client)

    assert "password='***'" in async_rendered
    assert "async_secret_password_456" not in async_rendered
    assert "async_secret_token_888" not in async_rendered


def test_get_token_malformed_null_data_raises_auth_error():
    client = NeoFeederClient(username="user1", password="pass1")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error_code": 0, "error_desc": "", "data": None}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(FeederAuthError) as exc_info:
            client.get_token(force_refresh=True)
        assert exc_info.value.error_code == 101


def test_execute_prevents_token_overwrite_via_kwargs():
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "real_session_token"

    captured_payloads = []

    def fake_post(self_client, url, json=None, headers=None):
        captured_payloads.append(json)
        resp = MagicMock()
        resp.json.return_value = {"error_code": 0, "error_desc": "", "data": []}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("httpx.Client.post", new=fake_post):
        client.execute("GetProfilPT", token="hijacked_token", limit=5)

    assert len(captured_payloads) == 1
    assert captured_payloads[0]["act"] == "GetProfilPT"
    assert captured_payloads[0]["token"] == "real_session_token"
    assert captured_payloads[0]["limit"] == 5


def test_iter_records_rejects_non_positive_chunk_size():
    client = NeoFeederClient()
    with pytest.raises(ValueError):
        list(client.iter_records("GetBiodataMahasiswa", chunk_size=0))
    with pytest.raises(ValueError):
        list(client.iter_records("GetBiodataMahasiswa", chunk_size=-10))


def test_async_feeder_connection_error():
    client = AsyncNeoFeederClient(username="user1", password="pass1")

    async def _runner():
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
            with pytest.raises(FeederConnectionError) as exc_info:
                await client.get_token(force_refresh=True)
            assert exc_info.value.error_code == 503

    asyncio.run(_runner())


def test_test_connection_masks_token_preview():
    client = NeoFeederClient(username="user1", password="pass1")
    with patch.object(client, "get_token", return_value="abcdef1234567890"):
        with patch.object(client, "execute", return_value={"error_code": 0, "data": []}):
            res = client.test_connection()
    assert res["status"] == "connected"
    assert res["token_preview"] == "abcd...***"
    assert "abcdef1234567890" not in res["token_preview"]


def test_env_variable_fallback_and_timeout_validation(monkeypatch):
    monkeypatch.setenv("NEOFEEDER_URL", "https://feeder.kampus.ac.id/ws/live2.php")
    monkeypatch.setenv("NEOFEEDER_USER", "env_user")
    monkeypatch.setenv("NEOFEEDER_PASSWORD", "env_pass")

    client = NeoFeederClient()
    assert client.base_url == "https://feeder.kampus.ac.id/ws/live2.php"
    assert client.username == "env_user"
    assert client.password == "env_pass"

    with pytest.raises(ValueError):
        NeoFeederClient(timeout=0)
    with pytest.raises(ValueError):
        NeoFeederClient(timeout=-5)


@pytest.mark.parametrize(
    "ssrf_or_unsafe_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://100.100.100.200/latest/meta-data/",
        "http://0.0.0.0:8100/ws/live2.php",
        "http://[fe80::1]:8100/ws/live2.php",
        "http://[::ffff:169.254.169.254]/ws/live2.php",
        "http://224.0.0.1/ws/live2.php",
        "https://user:secret@feeder.kampus.ac.id/ws/live2.php",
        "https://feeder.kampus.ac.id/ws/live2.php?debug=1",
        "https://feeder.kampus.ac.id/ws/live2.php#frag",
        "https://feeder.kampus.ac.id/ws/live2.php\r\nX-Injected: 1",
    ],
)
def test_reject_ssrf_metadata_embedded_creds_and_url_smuggling(ssrf_or_unsafe_url):
    with pytest.raises(ValueError):
        NeoFeederClient(base_url=ssrf_or_unsafe_url)
    with pytest.raises(ValueError):
        AsyncNeoFeederClient(base_url=ssrf_or_unsafe_url)


@pytest.mark.parametrize(
    "bad_act",
    [
        "GetProfilPT; DROP TABLE mahasiswa",
        "../etc/passwd",
        "GetProfilPT --",
        "123InvalidAct",
        "Get Profil PT",
    ],
)
def test_reject_invalid_act_and_dictionary_fungsi(bad_act):
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "valid_token"

    with pytest.raises(ValueError):
        client.execute(bad_act)
    with pytest.raises(ValueError):
        client.get_dictionary(bad_act)
    with pytest.raises(ValueError):
        list(client.iter_records(bad_act))

    async_client = AsyncNeoFeederClient(username="user1", password="pass1")
    async_client._token = "valid_token"

    async def _runner():
        with pytest.raises(ValueError):
            await async_client.execute(bad_act)

    asyncio.run(_runner())


@pytest.mark.parametrize(
    "malicious_filter",
    [
        "id_prodi='1'; DROP TABLE mhs--",
        "1=1 UNION SELECT * FROM users",
        "id_prodi='1' /* comment */",
        "id_prodi='1'\x00",
        "id_prodi='1' OR SLEEP(5)",
    ],
)
def test_reject_sql_injection_in_filter(malicious_filter):
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "valid_token"

    with pytest.raises(ValueError):
        client.execute("GetBiodataMahasiswa", filter=malicious_filter)
    with pytest.raises(ValueError):
        client.get_mahasiswa(filter=malicious_filter)
    with pytest.raises(ValueError):
        client.get_daftar_prodi(filter=malicious_filter)
    with pytest.raises(ValueError):
        client.get_dosen(filter=malicious_filter)


@pytest.mark.parametrize(
    "malicious_order",
    [
        "nim ASC; SELECT 1",
        "nim --",
        "nim /* comment */",
        "nim ASC UNION SELECT 1",
    ],
)
def test_reject_sql_injection_in_order(malicious_order):
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "valid_token"

    with pytest.raises(ValueError):
        client.execute("GetBiodataMahasiswa", order=malicious_order)
    with pytest.raises(ValueError):
        client.get_mahasiswa(order=malicious_order)


def test_accept_valid_filter_and_order_clauses():
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "valid_token"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error_code": 0, "data": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_resp):
        rows = client.get_mahasiswa(
            filter="id_prodi='123' AND nama_mahasiswa LIKE '%Budi%'",
            order="nama_mahasiswa DESC, nim ASC",
            limit=50,
            offset=10,
        )
    assert rows == []


def test_reject_boolean_and_out_of_bounds_numeric_params():
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "valid_token"

    for bad_limit in (True, False, 0, -1, 10001, "10"):
        with pytest.raises(ValueError):
            client.get_mahasiswa(limit=bad_limit)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            client.get_dosen(limit=bad_limit)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            client.execute("GetProfilPT", limit=bad_limit)
        with pytest.raises(ValueError):
            list(client.iter_records("GetBiodataMahasiswa", chunk_size=bad_limit))  # type: ignore[arg-type]

    for bad_offset in (True, False, -1, "0"):
        with pytest.raises(ValueError):
            client.get_mahasiswa(offset=bad_offset)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            client.execute("GetProfilPT", offset=bad_offset)

    with pytest.raises(ValueError):
        list(client.iter_records("GetBiodataMahasiswa", max_records=True))  # type: ignore[arg-type]


def test_reject_oversized_response_by_header_and_content():
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "valid_token"

    resp_oversized_header = MagicMock()
    resp_oversized_header.headers = {"Content-Length": str(_MAX_RESPONSE_BYTES + 1)}
    resp_oversized_header.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=resp_oversized_header):
        with pytest.raises(FeederException) as exc_info:
            client.execute("GetProfilPT")
        assert exc_info.value.error_code == 502

    resp_oversized_body = MagicMock()
    resp_oversized_body.headers = {}
    resp_oversized_body.content = b"x" * (_MAX_RESPONSE_BYTES + 1)
    resp_oversized_body.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=resp_oversized_body):
        with pytest.raises(FeederException) as exc_info:
            client.execute("GetProfilPT")
        assert exc_info.value.error_code == 502


def test_sanitize_secrets_in_connection_errors():
    secret_pw = "super_rahasia_987"
    secret_tok = "tok_rahasia_xyz_123"
    client = NeoFeederClient(username="user1", password=secret_pw)
    client._token = secret_tok

    err = httpx.ConnectError(f"Connection failed with {secret_pw} and {secret_tok}")
    with patch("httpx.Client.post", side_effect=err):
        with pytest.raises(FeederConnectionError) as exc_info:
            client.execute("GetProfilPT")
        assert secret_pw not in exc_info.value.error_desc
        assert secret_tok not in exc_info.value.error_desc
        assert "***" in exc_info.value.error_desc

    async_client = AsyncNeoFeederClient(username="user1", password=secret_pw)
    async_client._token = secret_tok

    async def _runner():
        with patch("httpx.AsyncClient.post", side_effect=err):
            with pytest.raises(FeederConnectionError) as exc_info_async:
                await async_client.execute("GetProfilPT")
            assert secret_pw not in exc_info_async.value.error_desc
            assert secret_tok not in exc_info_async.value.error_desc

    asyncio.run(_runner())


def test_get_token_prevents_refresh_race_condition():
    client = NeoFeederClient(username="user1", password="pass1")
    client._token = "token_baru_sudah_diperbarui"

    with patch("httpx.Client.post") as mock_post:
        token = client.get_token(force_refresh=True, stale_token="token_lama")
        assert token == "token_baru_sudah_diperbarui"
        mock_post.assert_not_called()

    async_client = AsyncNeoFeederClient(username="user1", password="pass1")
    async_client._token = "async_token_baru"

    async def _runner():
        with patch("httpx.AsyncClient.post") as mock_async_post:
            tok = await async_client.get_token(force_refresh=True, stale_token="async_token_lama")
            assert tok == "async_token_baru"
            mock_async_post.assert_not_called()

    asyncio.run(_runner())


def test_verify_ssl_false_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="pddikti_feeder"):
        NeoFeederClient(base_url="https://feeder.kampus.ac.id/ws/live2.php", verify_ssl=False)
        AsyncNeoFeederClient(base_url="https://feeder.kampus.ac.id/ws/live2.php", verify_ssl=False)

    assert caplog.text.count("verify_ssl=False") == 2
