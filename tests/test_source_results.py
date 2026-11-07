import importlib.util
import json
from datetime import datetime


def test_result_contracts_are_json_safe_and_preserve_zero(monkeypatch):
    assert importlib.util.find_spec("marketmind_ai.dataflows.results") is not None
    from marketmind_ai.dataflows.results import SourceAttempt, SourceMaterial, VendorResult
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "private-token")
    attempt = SourceAttempt(attempt_id="a", method="price", provider="yfinance", data_mode="live", status="success", started_at=datetime.now().astimezone(), finished_at=datetime.now().astimezone(), item_count=0)
    material = SourceMaterial(method="price", provider="yfinance", data_mode="live", retrieved_at=attempt.finished_at, content={"zero": 0, "missing": None, "apikey": "private-token", "url": "https://example.test/?apikey=private-token"}, attempt_id="a")
    result = VendorResult(value=0, provider="yfinance", data_mode="live", status="success", attempts=[attempt], materials=[material])
    encoded = json.dumps(result.model_dump())
    assert result.available
    assert "private-token" not in encoded
    assert result.to_dict()["materials"][0]["content"]["zero"] == 0
    assert result.to_dict()["materials"][0]["content"]["missing"] is None
    assert datetime.fromisoformat(result.to_dict()["attempts"][0]["started_at"]).utcoffset().total_seconds() == 0


def test_material_free_text_removes_authorization_and_json_credentials(monkeypatch):
    from marketmind_ai.dataflows.results import SourceMaterial, safe_json, utc_now
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    for payload in [
        "Authorization: Bearer private-credential",
        "Authorization: Basic private-credential",
        '{"apikey": "private-credential", "zero": 0}',
        '[{"nested": {"api_key": "private-credential"}}]',
        'Response payload: {"apikey": "private-credential"}',
    ]:
        material = SourceMaterial(method="get_news", provider="yfinance", data_mode="live", retrieved_at=utc_now(), content=payload)
        assert "private-credential" not in str(material.content)
        assert "private-credential" not in json.dumps(material.to_dict())
        assert safe_json(material.content) == material.content
