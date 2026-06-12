import gzip
import unittest

from marketmind_ai.dataflows.sec_filings import _read_response_bytes


class _FakeResponse:
    def __init__(self, body: bytes, encoding: str = "") -> None:
        self._body = body
        self.headers = {"Content-Encoding": encoding} if encoding else {}

    def read(self) -> bytes:
        return self._body


class SecFilingsTests(unittest.TestCase):
    def test_read_response_bytes_handles_gzip_payloads(self):
        payload = b'{"ticker":"AAPL"}'
        response = _FakeResponse(gzip.compress(payload), "gzip")

        decoded = _read_response_bytes(response)

        self.assertEqual(decoded, payload)


if __name__ == "__main__":
    unittest.main()
