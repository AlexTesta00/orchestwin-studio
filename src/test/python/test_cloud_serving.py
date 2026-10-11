import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("cloud_proposer")


def test_port_mapping_and_redaction(controller):
    assert controller.port_mapping({"portMappings": {"22": "40123"}}) == 40123
    assert controller.port_mapping({"portMappings": {}}) is None
    assert controller.port_mapping({}) is None
    redacted = controller.redact({"id": "x", "env": {"PUBLIC_KEY": "k", "SECRET": "s"}})
    assert redacted["env"] == ["PUBLIC_KEY", "SECRET"]


def test_tunnel_command_forwards_loopback_port_and_keeps_alive(controller):
    receipt = {
        "ssh_host": "1.2.3.4",
        "ssh_port": 2222,
        "local_port": 8791,
        "remote_port": 8787,
        "serving_output": "/workspace/serving/pod",
    }
    command = controller.tunnel_command(receipt)
    assert command[0] == "ssh"
    assert "127.0.0.1:8791:127.0.0.1:8787" in command
    assert command[-2] == "root@1.2.3.4"
    assert "touch /workspace/serving/pod/keepalive" in command[-1]
    assert "-p" in command and command[command.index("-p") + 1] == "2222"


def test_expect_rejects_unexpected_status(controller):
    assert controller.expect(200, {"ok": True}, 200, 201) == {"ok": True}
    with pytest.raises(controller.CloudError):
        controller.expect(500, {"error": "boom"}, 200)
