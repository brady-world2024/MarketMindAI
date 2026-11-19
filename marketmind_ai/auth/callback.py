"""One bounded OAuth loopback attempt; never echo or log callback data."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .errors import PlanError

_RELEVANT = {"code", "state", "client_id", "error", "error_description", "error_uri", "scope"}


class CallbackAttempt:
    def __init__(self, state: str, timeout_seconds: float):
        self._state = state
        self._deadline = time.monotonic() + timeout_seconds
        self._done = threading.Event()
        self._stop = threading.Event()
        self._used = False
        self._result = None
        self._error = None
        attempt = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path != "/auth/callback":
                    self.reply(404)
                    return
                if attempt._used or time.monotonic() >= attempt._deadline:
                    self.reply(410)
                    return
                # Only consume the exact callback target of this attempt.
                host = self.headers.get_all("Host", [])
                valid_host = host == [f"127.0.0.1:{attempt._server.server_port}"]
                attempt._used = True
                try:
                    values = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=32)
                    if (not valid_host or parsed.scheme or parsed.netloc or
                            any(len(values[key]) != 1 for key in values.keys() & _RELEVANT) or
                            not secrets.compare_digest(values.get("state", [""])[0], attempt._state)):
                        raise PlanError("invalid_callback")
                    if "error" in values:
                        raise PlanError("access_denied" if values["error"] == ["access_denied"] else "authorization_failed")
                    if not values.get("code", [""])[0]:
                        raise PlanError("invalid_callback")
                    attempt._result = {key: values[key][0] for key in ("code", "client_id") if key in values}
                except (ValueError, UnicodeError, TypeError):
                    attempt._error = PlanError("invalid_callback")
                except PlanError as error:
                    attempt._error = error
                self.reply(400 if attempt._error else 200)
                attempt._done.set()

            def do_POST(self):
                self.reply(405)

            def reply(self, status):
                body = b"Authorization received. Return to the app to check the result." if status == 200 else b"Authorization callback was not accepted."
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        class BoundedServer(HTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                # Bound both the request line and header reads, including partial
                # local connections that would otherwise outlive the attempt.
                connection.settimeout(min(0.1, max(0.01, attempt._deadline - time.monotonic())))
                return connection, address

        try:
            self._server = BoundedServer(("127.0.0.1", 0), Handler)
        except OSError:
            raise PlanError("callback_unavailable") from None
        self._server.timeout = 0.1
        self.redirect_uri = f"http://127.0.0.1:{self._server.server_port}/auth/callback"
        self._thread = threading.Thread(target=self._serve, daemon=True, name="chatgpt-oauth-callback")
        self._thread.start()

    def __repr__(self):
        return "<CallbackAttempt>"

    def _serve(self):
        while not self._stop.is_set() and time.monotonic() < self._deadline:
            self._server.handle_request()

    def wait(self):
        if not self._done.wait(max(0, self._deadline - time.monotonic())):
            raise PlanError("authorization_timeout")
        if self._error:
            raise self._error
        return self._result

    def close(self):
        self._stop.set()
        self._done.set()
        self._thread.join(timeout=1)
        self._server.server_close()
