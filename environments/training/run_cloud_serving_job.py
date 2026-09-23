#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

from run_cloud_training_job import pod_request, send_email

CREDENTIAL_KEYS = (
    "ORCHESTWIN_RUNPOD_API_KEY",
    "ORCHESTWIN_SMTP_USER",
    "ORCHESTWIN_SMTP_PASSWORD",
    "ORCHESTWIN_NOTIFY_TO",
)
POLL_SECONDS = 30
STARTUP_TIMEOUT_SECONDS = 2400
DEFAULT_PYTHON = "/opt/orchestwin/training-venv/bin/python"


class ServingStop(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def write_state(path, **values):
    with suppress(OSError):
        path.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")


PROC_TCP = ("/proc/net/tcp", "/proc/net/tcp6")


def established_connections(port, sources=PROC_TCP):
    count = 0
    for name in sources:
        with suppress(OSError):
            for line in Path(name).read_text(encoding="ascii").splitlines()[1:]:
                fields = line.split()
                if len(fields) > 3 and fields[3] == "01":
                    local_port = int(fields[1].rsplit(":", 1)[1], 16)
                    if local_port == port:
                        count += 1
    return count


def activity_observed(previous, observed, connections, age, keepalive_seconds):
    if observed is not None and observed != previous:
        return True
    if connections > 0:
        return True
    return age is not None and age < keepalive_seconds


def stop_reason(now, started, last_activity, max_hours, idle_minutes):
    if now - started > max_hours * 3600:
        return "MAX_HOURS_REACHED"
    if now - last_activity > idle_minutes * 60:
        return "IDLE_TIMEOUT"
    return None


def health(port, token):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/health",
        headers={"Authorization": "Bearer " + token, "Connection": "close"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def keepalive_age(path):
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def notification(subject, body, credentials, log):
    try:
        send_email(subject, body, credentials)
        log(f"EMAIL_SENT {subject}")
    except Exception as error:
        log(f"EMAIL_FAILED {type(error).__name__}")


def stop_pod(pod_id, token, log):
    for attempt in range(1, 9):
        try:
            result = pod_request(pod_id, token, stop=False)
            if result["status"] not in ("EXITED", "ERROR"):
                result = pod_request(pod_id, token, stop=True)
            if result["status"] in ("EXITED", "ERROR"):
                log(f"POD_STOP_CONFIRMED attempt={attempt}")
                return True
        except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
            log(f"POD_STOP_RETRY attempt={attempt} {type(error).__name__}")
        time.sleep(min(attempt * 5, 30))
    return False


def log_tail(path, lines=15, width=240):
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(log non disponibile)"
    return "\n".join(line[:width] for line in content[-lines:]) or "(log vuoto)"


def summary(args, pod, started, generations, reason, logs=()):
    hours = (time.time() - started) / 3600
    rate = float(pod.get("cost") or args.hourly_usd)
    text = (
        f"OrchesTwin proposer remoto: {reason}\n"
        f"Pod: {pod.get('name')} ({pod.get('id')})\n"
        f"Modello: {args.model_repository} @ {args.model_revision} ({args.precision})\n"
        f"Motore: {args.engine}\n"
        f"Generazioni completate: {generations}\n"
        f"Ore attive: {hours:.2f} a USD {rate:.2f}/ora, stima USD {hours * rate:.2f}\n"
        f"Politica: arresto dopo {args.idle_minutes} minuti senza attività o dopo "
        f"{args.max_hours} ore totali.\n"
        "La stima non è il saldo Runpod e non include lo storage del volume."
    )
    for label, path in logs:
        text += f"\n\n--- {label} ---\n{log_tail(path)}"
    return text


STARTUP_FAILURES = (
    "UPSTREAM_EXITED_DURING_STARTUP",
    "UPSTREAM_STARTUP_TIMEOUT",
    "SERVER_EXITED_DURING_STARTUP",
    "SERVER_STARTUP_TIMEOUT",
)


def serving_environment(args):
    environment = dict(os.environ)
    environment.update(
        HF_HOME=str(args.hf_home),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        WANDB_DISABLED="true",
        PYTHONUNBUFFERED="1",
        VLLM_USE_FLASHINFER_SAMPLER="0",
    )
    return environment


def spawn(command, log_path, environment):
    with log_path.open("ab") as stream:
        return subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )


def hf_server_command(args, python, directory):
    return [
        str(python),
        str(args.repo / "environments/training/serve_proposal_model.py"),
        "--output-directory",
        str(directory),
        "--port",
        str(args.port),
        "--model-repository",
        args.model_repository,
        "--model-revision",
        args.model_revision,
        "--precision",
        args.precision,
        "--max-sequence-length",
        str(args.max_sequence_length),
        "--max-output-tokens",
        str(args.max_output_tokens),
        "--generation-timeout-seconds",
        str(args.generation_timeout_seconds),
    ]


def vllm_versions(vllm_python):
    output = subprocess.run(
        [
            str(vllm_python),
            "-c",
            "import importlib.metadata as m; print(m.version('vllm'), m.version('llguidance'))",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if len(output) != 2:
        raise ValueError("VLLM_VERSIONS_UNAVAILABLE")
    return output[0], output[1]


def vllm_server_command(args):
    return [
        str(args.vllm_python),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        args.model_repository,
        "--revision",
        args.model_revision,
        "--tokenizer-revision",
        args.model_revision,
        "--served-model-name",
        args.model_repository,
        "--host",
        "127.0.0.1",
        "--port",
        str(args.upstream_port),
        "--dtype",
        "bfloat16",
        "--max-model-len",
        str(args.max_sequence_length),
        "--gpu-memory-utilization",
        str(args.gpu_memory_utilization),
        "--structured-outputs-config",
        json.dumps({"backend": "guidance"}),
        "--moe-backend",
        args.moe_backend,
    ]


def proxy_command(args, python, directory, engine_version, decoder_version):
    return [
        str(python),
        str(args.repo / "environments/training/serve_vllm_proposer.py"),
        "--output-directory",
        str(directory),
        "--port",
        str(args.port),
        "--upstream",
        f"http://127.0.0.1:{args.upstream_port}",
        "--model-repository",
        args.model_repository,
        "--model-revision",
        args.model_revision,
        "--hf-home",
        str(args.hf_home),
        "--precision",
        args.precision,
        "--engine",
        "vllm",
        "--engine-version",
        engine_version,
        "--decoder-version",
        decoder_version,
        "--max-sequence-length",
        str(args.max_sequence_length),
        "--max-output-tokens",
        str(args.max_output_tokens),
        "--generation-timeout-seconds",
        str(args.generation_timeout_seconds),
    ]


def upstream_ready(port):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def launch_server(args, python, directory, log_path):
    environment = serving_environment(args)
    if args.engine == "hf":
        return [spawn(hf_server_command(args, python, directory), log_path, environment)]
    engine_version, decoder_version = vllm_versions(args.vllm_python)
    upstream = spawn(vllm_server_command(args), log_path.with_name("vllm.log"), environment)
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while not upstream_ready(args.upstream_port):
        if upstream.poll() is not None:
            raise ServingStop("UPSTREAM_EXITED_DURING_STARTUP")
        if time.time() > deadline:
            raise ServingStop("UPSTREAM_STARTUP_TIMEOUT")
        time.sleep(5)
    proxy = spawn(
        proxy_command(args, python, directory, engine_version, decoder_version),
        log_path,
        environment,
    )
    return [upstream, proxy]


def any_exited(children):
    return any(child.poll() is not None for child in children)


def wait_for_runtime(children, directory, deadline):
    runtime = directory / "runtime.json"
    while not runtime.is_file():
        if any_exited(children):
            raise ServingStop("SERVER_EXITED_DURING_STARTUP")
        if time.time() > deadline:
            raise ServingStop("SERVER_STARTUP_TIMEOUT")
        time.sleep(5)
    token = (directory / "access-token.secret").read_text(encoding="ascii").strip()
    return json.loads(runtime.read_text(encoding="utf-8")), token


def supervise(args):
    if os.name != "posix":
        raise ValueError("cloud serving supervisor requires a Linux Pod")
    pod_id = os.environ.get("RUNPOD_POD_ID")
    if not pod_id:
        raise ValueError("RUNPOD_POD_ID is required")
    credentials = {key: os.environ[key] for key in CREDENTIAL_KEYS}
    token = credentials["ORCHESTWIN_RUNPOD_API_KEY"]
    args.output.mkdir(parents=True, exist_ok=True)
    state_path = args.output / "supervisor-state.json"
    log_path = args.output / "supervisor.log"
    keepalive = args.output / "keepalive"
    stop_request = args.output / "stop.request"

    def log(message):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n"
        with suppress(OSError), log_path.open("a", encoding="utf-8") as stream:
            stream.write(line)
        print(line, end="", flush=True)

    pod = pod_request(pod_id, token)
    if pod["locked"] or "stop" not in pod["actions"]:
        raise ValueError("Pod cannot be stopped through the API")
    started = time.time()
    keepalive.touch()
    directory = args.output / f"proposal-{int(started)}"
    children = []
    write_state(state_path, stage="SERVER_STARTING", pod_id=pod_id, started_unix=started)
    generations = 0
    reason = "UNKNOWN"

    def terminate(signum, frame):
        raise ServingStop("SIGNAL_" + signal.Signals(signum).name)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        children = launch_server(args, args.python, directory, args.output / "server.log")
        runtime, access = wait_for_runtime(children, directory, started + STARTUP_TIMEOUT_SECONDS)
        log("SERVER_READY " + runtime["identity"]["runtime_id"])
        write_state(
            state_path,
            stage="SERVING",
            pod_id=pod_id,
            started_unix=started,
            runtime_file=str(directory / "runtime.json"),
            port=args.port,
        )
        notification(
            f"OrchesTwin proposer avviato: {pod['name']}",
            summary(args, pod, started, 0, "SERVING_READY")
            + f"\nRuntime: {directory / 'runtime.json'}\nPorta locale del pod: {args.port}",
            credentials,
            log,
        )
        last_activity = time.time()
        while True:
            time.sleep(POLL_SECONDS)
            now = time.time()
            if any_exited(children):
                raise ServingStop("SERVER_EXITED")
            if stop_request.exists():
                raise ServingStop("STOP_REQUESTED")
            observed = None
            with suppress(OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
                observed = int(health(args.port, access)["completed_generation_count"])
            if activity_observed(
                generations,
                observed,
                established_connections(args.port),
                keepalive_age(keepalive),
                args.keepalive_seconds,
            ):
                last_activity = now
            if observed is not None:
                generations = observed
            reason = stop_reason(now, started, last_activity, args.max_hours, args.idle_minutes)
            if reason is not None:
                raise ServingStop(reason)
            write_state(
                state_path,
                stage="SERVING",
                pod_id=pod_id,
                started_unix=started,
                generations=generations,
                idle_seconds=int(now - last_activity),
                port=args.port,
                runtime_file=str(directory / "runtime.json"),
            )
    except ServingStop as stop:
        reason = stop.reason
    except Exception as error:
        reason = "SUPERVISOR_ERROR_" + type(error).__name__
    finally:
        log("STOPPING " + reason)
        with suppress(OSError, ValueError, KeyError, urllib.error.URLError):
            pod = pod_request(pod_id, token)
        logs = (
            ("vllm.log", args.output / "vllm.log"),
            ("server.log", args.output / "server.log"),
        )
        hold = args.failure_hold_minutes if reason in STARTUP_FAILURES else 0
        notification(
            f"OrchesTwin proposer fermato: {reason}"
            + (f" (diagnosi per {hold} minuti)" if hold else ""),
            summary(args, pod, started, generations, reason, logs),
            credentials,
            log,
        )
        if hold:
            write_state(state_path, stage="DIAGNOSTIC_HOLD", reason=reason, pod_id=pod_id)
            deadline = time.time() + hold * 60
            while time.time() < deadline and not stop_request.exists():
                time.sleep(10)
        for child in reversed(children):
            if child.poll() is None:
                with suppress(OSError):
                    child.terminate()
                with suppress(subprocess.TimeoutExpired):
                    child.wait(timeout=60)
        write_state(
            state_path, stage="STOPPED", reason=reason, pod_id=pod_id, generations=generations
        )
        stopped = stop_pod(pod_id, token, log)
        write_state(
            state_path,
            stage="POD_STOP_CONFIRMED" if stopped else "POD_STOP_UNCONFIRMED",
            reason=reason,
            pod_id=pod_id,
            generations=generations,
        )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(DEFAULT_PYTHON))
    parser.add_argument("--hf-home", type=Path, default=Path("/workspace/hf-cache"))
    parser.add_argument("--engine", choices=("hf", "vllm"), default="hf")
    parser.add_argument(
        "--vllm-python", type=Path, default=Path("/opt/orchestwin/vllm-venv/bin/python")
    )
    parser.add_argument("--upstream-port", type=int, default=8100)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.9)
    parser.add_argument("--moe-backend", default="triton")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--model-repository", default="Qwen/Qwen3-Coder-30B-A3B-Instruct")
    parser.add_argument("--model-revision", default="b2cff646eb4bb1d68355c01b18ae02e7cf42d120")
    parser.add_argument("--precision", choices=("4bit", "bf16"), default="bf16")
    parser.add_argument("--max-sequence-length", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--generation-timeout-seconds", type=int, default=540)
    parser.add_argument("--idle-minutes", type=int, default=30)
    parser.add_argument("--max-hours", type=float, default=6)
    parser.add_argument("--keepalive-seconds", type=int, default=900)
    parser.add_argument("--hourly-usd", type=float, default=2.09)
    parser.add_argument("--failure-hold-minutes", type=int, default=0)
    args = parser.parse_args(argv)
    args.repo = args.repo.resolve()
    args.output = args.output.resolve()
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
