import json
from unittest.mock import MagicMock, patch
from pddikti_feeder.cli import create_parser, main


def test_cli_help(capsys):
    ret = main([])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "pddikti-feeder" in captured
    assert "test" in captured
    assert "query" in captured
    assert "dict" in captured


def test_cli_test_connection_json(capsys):
    mock_res = {
        "status": "connected",
        "message": "Sukses",
        "base_url": "http://localhost:8100/ws/live2.php",
        "token_preview": "token1234...",
    }
    with patch("pddikti_feeder.client.NeoFeederClient.test_connection", return_value=mock_res):
        ret = main(["test", "--json"])
        assert ret == 0
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["status"] == "connected"
        assert "token_preview" in data


def test_cli_query_json(capsys):
    mock_res = {"error_code": 0, "error_desc": "", "data": [{"kode": "01"}]}
    with patch("pddikti_feeder.client.NeoFeederClient.execute", return_value=mock_res):
        ret = main(["query", "GetProfilPT"])
        assert ret == 0
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["error_code"] == 0


def test_cli_test_connection_json_error_returns_nonzero(capsys):
    mock_res = {
        "status": "error",
        "message": "Kredensial salah",
        "base_url": "http://localhost:8100/ws/live2.php",
        "error_code": 102,
    }
    with patch("pddikti_feeder.client.NeoFeederClient.test_connection", return_value=mock_res):
        ret = main(["test", "--json"])
        assert ret == 1
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "error"


def test_cli_test_none_status_no_crash(capsys):
    mock_res = {
        "status": None,
        "message": "Respon tidak dikenal",
        "base_url": "http://localhost:8100/ws/live2.php",
    }
    with patch("pddikti_feeder.client.NeoFeederClient.test_connection", return_value=mock_res):
        ret = main(["test"])
        assert ret == 1
        out = capsys.readouterr().out
        assert "ERROR" in out


def test_cli_invalid_url_handled_safely(capsys):
    ret = main(["query", "GetProfilPT", "--url", "ftp://invalid.host/ws/live2.php"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error [400]" in err


def test_cli_env_fallback(monkeypatch, capsys):
    monkeypatch.setenv("NEOFEEDER_URL", "https://feeder.kampus.ac.id/ws/live2.php")
    monkeypatch.setenv("NEOFEEDER_USER", "env_operator")
    monkeypatch.setenv("NEOFEEDER_PASSWORD", "env_secret")

    mock_res = {"error_code": 0, "error_desc": "", "data": [{"ok": True}]}
    with patch("pddikti_feeder.client.NeoFeederClient.execute", return_value=mock_res):
        ret = main(["query", "GetProfilPT"])
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["error_code"] == 0

    parser = create_parser()
    parsed = parser.parse_args(["test"])
    assert parsed.url == "https://feeder.kampus.ac.id/ws/live2.php"
    assert parsed.user == "env_operator"
    assert parsed.password == "env_secret"


def test_cli_query_get_token_masks_token(capsys):
    mock_res = {
        "error_code": 0,
        "error_desc": "",
        "data": {"token": "rahasia_token_panjang_999"},
    }
    with patch("pddikti_feeder.client.NeoFeederClient.execute", return_value=mock_res):
        ret = main(["query", "GetToken"])
        assert ret == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["data"]["token"] == "raha...***"
        assert "rahasia_token_panjang_999" not in out
        assert mock_res["data"]["token"] == "rahasia_token_panjang_999"


def test_cli_password_interactive_prompt(capsys):
    mock_res = {"error_code": 0, "error_desc": "", "data": []}
    with patch("getpass.getpass", return_value="prompted_secret") as mock_getpass:
        with patch("pddikti_feeder.client.NeoFeederClient.execute", return_value=mock_res):
            ret = main(["query", "GetProfilPT", "-u", "admin", "-p"])
            assert ret == 0
            mock_getpass.assert_called_once_with("Password Feeder: ")


def test_cli_query_rejects_sql_injection_filter(capsys):
    ret = main(["query", "GetBiodataMahasiswa", "--filter", "id_prodi='1'; DROP TABLE mhs"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error [400]" in err


def test_cli_query_rejects_invalid_limit(capsys):
    ret = main(["query", "GetProfilPT", "--limit", "-5"])
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error [400]" in err
