from marketmind_ai.dataflows.config import dataflow_context
from marketmind_ai.dataflows.sec_filings import _sec_get_text


def test_raw_capture_keeps_actual_mime_provenance_and_redacts_secrets(monkeypatch):
    class Response:
        headers = {'Content-Type': 'application/xml; charset=UTF-8'}
        def read(self):
            return b'<source>api_key=private-secret</source>'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: Response())
    with dataflow_context({'data_mode': 'live'}) as audit:
        audit.capture_context = ('get_instrument_metadata', 'sec', 'attempt-a')
        body = _sec_get_text('https://source.test/document?apikey=private-key')
        assert 'private-secret' in body
        captured = audit.raw_captures[0]
        assert captured['content_type'] == 'application/xml; charset=UTF-8'
        assert captured['provider'] == 'sec' and captured['attempt_id'] == 'attempt-a'
        assert 'private-secret' not in captured['body']
        assert 'private-key' not in captured['source_url']
