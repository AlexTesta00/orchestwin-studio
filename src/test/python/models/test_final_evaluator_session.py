from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from orchestwin.models.final_evaluator_session import (
    FinalEvaluatorSessionError,
    check_final_health,
    load_final_session,
    session_http,
)

from .final_session_support import health, make_session, record


def test_session_is_private_and_immutable(tmp_path):
    session = make_session(tmp_path)
    assert "b" * 64 not in repr(session)
    identity = session.identity
    identity["adapter_id"] = "tampered"
    assert session.identity["adapter_id"] == "s67-final-user-twin-evaluator"
    session.assert_unchanged()


@pytest.mark.parametrize("marker", ["stopped.json", "failure.json"])
def test_terminated_session_cannot_be_loaded(tmp_path, marker):
    session = make_session(tmp_path)
    (tmp_path / marker).write_text("{}")
    with pytest.raises(FinalEvaluatorSessionError):
        session.assert_unchanged()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("host", "0.0.0.0"),
        ("port", True),
        ("port", 80),
        ("credential_file", "../secret"),
        ("model_name", "other"),
        ("training_executed", True),
    ],
)
def test_ready_scope_is_not_relaxed(tmp_path, key, value):
    make_session(tmp_path)
    path = tmp_path / "ready.json"
    payload = json.loads(path.read_text())
    del payload["content_hash"]
    payload[key] = value
    record(path, payload)
    with pytest.raises(FinalEvaluatorSessionError):
        load_final_session(path)


def test_changed_token_is_detected(tmp_path):
    session = make_session(tmp_path)
    (tmp_path / "access-token.secret").write_text("c" * 64)
    with pytest.raises(FinalEvaluatorSessionError, match="CHANGED"):
        session.assert_unchanged()


def test_corrupt_hash_rejected(tmp_path):
    make_session(tmp_path)
    path = tmp_path / "ready.json"
    payload = json.loads(path.read_text())
    payload["port"] += 1
    path.write_text(json.dumps(payload))
    with pytest.raises(FinalEvaluatorSessionError):
        load_final_session(path)


@pytest.mark.parametrize(
    ("method", "path"),
    [("DELETE", "/health"), ("GET", "/v1/chat/completions"), ("POST", "https://example.com")],
)
def test_only_fixed_local_operations_allowed(tmp_path, method, path):
    with pytest.raises(ValueError):
        session_http(make_session(tmp_path), method, path)


@pytest.mark.parametrize("status", [200, 302, 401])
def test_real_loopback_http_health_and_no_redirect(tmp_path, status):
    calls = []
    session = None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            assert self.headers.get("Authorization") == "Bearer " + "b" * 64
            raw = json.dumps(health(session)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Location", "http://127.0.0.1:9/unreachable")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, _format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    session = make_session(tmp_path, port=server.server_port)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    try:
        if status == 200:
            assert check_final_health(session)["completed_generation_count"] == 2
        else:
            with pytest.raises(ValueError):
                check_final_health(session)
        assert calls == ["/health"]
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()
