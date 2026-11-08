import asyncio
from unittest.mock import MagicMock, patch
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
