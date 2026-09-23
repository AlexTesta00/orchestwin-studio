import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def serving(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "environments/training"))
    return importlib.import_module("run_cloud_serving_job")


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("cloud_proposer")


def test_established_connections_counts_only_matching_port(serving, tmp_path):
    table = tmp_path / "tcp"
    table.write_text(
        "  sl  local_address rem_address   st\n"
        "   0: 0100007F:2253 0100007F:A1B2 01\n"
        "   1: 0100007F:2253 0100007F:A1B3 06\n"
        "   2: 0100007F:1F90 0100007F:A1B4 01\n",
        encoding="ascii",
    )
    assert serving.established_connections(8787, (str(table),)) == 1
    assert serving.established_connections(8080, (str(table),)) == 1
    assert serving.established_connections(9999, (str(table), str(tmp_path / "missing"))) == 0


def test_activity_requires_new_generation_connection_or_fresh_keepalive(serving):
    assert serving.activity_observed(3, 4, 0, None, 900)
    assert serving.activity_observed(3, 3, 1, None, 900)
    assert serving.activity_observed(3, 3, 0, 10.0, 900)
    assert not serving.activity_observed(3, 3, 0, 901.0, 900)
    assert not serving.activity_observed(3, None, 0, None, 900)


def test_stop_reason_prefers_lease_over_idle(serving):
    assert serving.stop_reason(100.0, 0.0, 90.0, 6, 30) is None
    assert serving.stop_reason(6 * 3600 + 1, 0.0, 6 * 3600, 6, 30) == "MAX_HOURS_REACHED"
    assert serving.stop_reason(2000.0, 0.0, 100.0, 6, 30) == "IDLE_TIMEOUT"


def test_keepalive_age_is_none_without_file(serving, tmp_path):
    assert serving.keepalive_age(tmp_path / "keepalive") is None
    (tmp_path / "keepalive").touch()
    assert serving.keepalive_age(tmp_path / "keepalive") < 5


def test_stop_pod_retries_until_confirmed(serving, monkeypatch):
    calls = []
    states = iter(["RUNNING", "RUNNING", "RUNNING", "EXITED"])

    def request(pod_id, token, *, stop=False):
        calls.append(stop)
        if len(calls) == 1:
            raise OSError("transient")
        return {"status": next(states)}

    monkeypatch.setattr(serving, "pod_request", request)
    monkeypatch.setattr(serving.time, "sleep", lambda seconds: None)
    assert serving.stop_pod("pod", "token", lambda message: None)
    assert calls == [False, False, True, False, True]


def test_summary_reports_reason_and_cost(serving):
    args = SimpleNamespace(
        model_repository="m",
        model_revision="r",
        precision="bf16",
        idle_minutes=30,
        max_hours=6,
        hourly_usd=2.0,
        engine="vllm",
    )
    text = serving.summary(args, {"name": "p", "id": "x", "cost": 2.0}, 0.0, 5, "IDLE_TIMEOUT")
    assert "IDLE_TIMEOUT" in text and "Generazioni completate: 5" in text and "USD 2.00/ora" in text


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
