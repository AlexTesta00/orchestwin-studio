"""Protocol bytes and half-close behavior without a database or credentials."""

import importlib.util
import socket
import threading
from pathlib import Path


def test_bridge_preserves_bytes_and_half_close_without_protocol_interpretation():
    path = Path(__file__).resolve().parents[4] / "scripts/model_database_bridge.py"
    spec = importlib.util.spec_from_file_location("model_bridge_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client, inbound = socket.socketpair()
    outbound, upstream = socket.socketpair()
    thread = threading.Thread(target=module.relay, args=(inbound, outbound), daemon=True)
    thread.start()
    try:
        client.settimeout(2)
        upstream.settimeout(2)
        request = b"\x00\x00\x00\x08\x04\xd2\x16\x2f"
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        assert upstream.recv(4096) == request
        assert upstream.recv(4096) == b""
        upstream.sendall(b"N")
        upstream.shutdown(socket.SHUT_WR)
        assert client.recv(4096) == b"N"
        assert client.recv(4096) == b""
        thread.join(2)
        assert not thread.is_alive()
    finally:
        for stream in (client, inbound, outbound, upstream):
            stream.close()
