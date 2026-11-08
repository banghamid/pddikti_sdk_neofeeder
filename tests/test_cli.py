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
