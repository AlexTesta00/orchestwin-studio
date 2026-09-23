from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "var/studio/cloud"
REST = "https://rest.runpod.io/v1"
KEY_FILE = Path.home() / ".ssh/orchestwin_runpod_ed25519"
CLOUD_ROOT = "/workspace/orchestwin-studio"
CLOUD_PYTHON = "/opt/orchestwin/training-venv/bin/python"
CLOUD_HF_HOME = "/workspace/hf-cache"
SERVING_ROOT = "/workspace/serving"
DEFAULT_GPUS = ("NVIDIA A100 80GB PCIe", "NVIDIA RTX PRO 6000 Blackwell Server Edition")
DEFAULT_IMAGE = "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
DEFAULT_CUDA = ()
CREDENTIAL_KEYS = (
    "ORCHESTWIN_RUNPOD_API_KEY",
    "ORCHESTWIN_SMTP_USER",
    "ORCHESTWIN_SMTP_PASSWORD",
    "ORCHESTWIN_NOTIFY_TO",
)
SYNC_PATHS = ("environments/training", "src/orchestwin", "pyproject.toml")
CONTAINER_ENVIRONMENT = "set -a && . /etc/rp_environment && set +a"


class CloudError(RuntimeError):
    pass


def api(method, path, body=None):
    token = os.environ.get("ORCHESTWIN_RUNPOD_API_KEY")
    if not token:
        raise CloudError("ORCHESTWIN_RUNPOD_API_KEY is required")
    request = urllib.request.Request(
        REST + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OrchesTwin-Cloud-Proposer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw.decode(errors="replace")


def expect(status, payload, *accepted):
    if status not in accepted:
        raise CloudError(f"RUNPOD_API_{status}: {json.dumps(payload)[:800]}")
    return payload


def receipt_path(pod_id):
    return STATE_ROOT / pod_id / "receipt.json"


def load_receipt(pod_id):
    path = receipt_path(pod_id)
    if not path.is_file():
        raise CloudError(f"no receipt for pod {pod_id}; run wait first")
    return json.loads(path.read_text(encoding="utf-8"))


def save_receipt(pod_id, values):
    path = receipt_path(pod_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
    return values


def redact(pod):
    pod = dict(pod)
    if isinstance(pod.get("env"), dict):
        pod["env"] = sorted(pod["env"])
    return pod


def ssh_command(receipt, remote=None, *, tty=False):
    command = [
        "ssh",
        "-i",
        str(KEY_FILE),
        "-p",
        str(receipt["ssh_port"]),
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={STATE_ROOT / 'known_hosts'}",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=4",
    ]
    if not tty:
        command.append("-T")
    command.append(f"root@{receipt['ssh_host']}")
    if remote is not None:
        command.append(remote)
    return command


def run_remote(receipt, script, *, check=True, capture=True):
    completed = subprocess.run(
        ssh_command(receipt, "bash -lc " + json.dumps(script)),
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        raise CloudError(f"remote command failed ({completed.returncode}): {completed.stderr}")
    return completed


def command_create(args):
    public_key = (KEY_FILE.with_suffix(".pub")).read_text(encoding="ascii").strip()
    env = {"PUBLIC_KEY": public_key}
    for key in CREDENTIAL_KEYS:
        value = os.environ.get(key)
        if not value:
            raise CloudError(f"{key} is required for the pod supervisor")
        env[key] = value
    body = {
        "name": args.name,
        "imageName": args.image,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": list(args.gpu),
        "gpuCount": 1,
        "dataCenterIds": [args.center],
        "networkVolumeId": args.volume,
        "volumeMountPath": "/workspace",
        "containerDiskInGb": args.disk,
        "ports": ["22/tcp"],
        "env": env,
        "supportPublicIp": True,
    }
    if args.cuda:
        body["allowedCudaVersions"] = list(args.cuda)
    pod = expect(*api("POST", "/pods", body), 200, 201)
    save_receipt(
        pod["id"],
        {
            "pod_id": pod["id"],
            "name": pod.get("name"),
            "created_at": pod.get("createdAt"),
            "cost_per_hour": pod.get("costPerHr"),
            "center": args.center,
            "volume": args.volume,
        },
    )
    print(json.dumps(redact(pod), indent=2))
    return pod["id"]


def port_mapping(pod):
    mappings = pod.get("portMappings") or {}
    if isinstance(mappings, dict):
        for key, value in mappings.items():
            if str(key).startswith("22"):
                return int(value)
    return None


def command_wait(args):
    deadline = time.time() + args.timeout
    while True:
        pod = expect(*api("GET", f"/pods/{args.pod}"), 200)
        host, port = pod.get("publicIp"), port_mapping(pod)
        if pod.get("desiredStatus") == "RUNNING" and host and port:
            receipt = load_receipt(args.pod) if receipt_path(args.pod).is_file() else {}
            receipt.update(
                pod_id=args.pod,
                name=pod.get("name"),
                ssh_host=host,
                ssh_port=port,
                cost_per_hour=pod.get("costPerHr"),
                gpu=(pod.get("machine") or {}).get("gpuTypeId"),
            )
            save_receipt(args.pod, receipt)
            print(json.dumps(receipt, indent=2))
            return
        if time.time() > deadline:
            raise CloudError(f"pod {args.pod} not reachable: {json.dumps(redact(pod))[:600]}")
        time.sleep(10)


def command_sync(args):
    receipt = load_receipt(args.pod)
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", *SYNC_PATHS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    files = [name for name in listed if name and Path(ROOT, name).is_file()]
    manifest = STATE_ROOT / args.pod / "sync-files.txt"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("\n".join(files) + "\n", encoding="utf-8")
    remote = f"mkdir -p {CLOUD_ROOT} && tar -xz -C {CLOUD_ROOT}"
    archive = subprocess.Popen(
        ["tar", "-cz", "-C", str(ROOT), "-T", str(manifest)],
        stdout=subprocess.PIPE,
    )
    upload = subprocess.run(ssh_command(receipt, remote), stdin=archive.stdout)
    archive.stdout.close()
    if archive.wait() != 0 or upload.returncode != 0:
        raise CloudError("sync failed")
    print(f"synced {len(files)} files to {receipt['ssh_host']}:{CLOUD_ROOT}")


def command_bootstrap(args):
    receipt = load_receipt(args.pod)
    log = f"{SERVING_ROOT}/bootstrap.log"
    script = (
        f"mkdir -p {SERVING_ROOT} && "
        f"ORCHESTWIN_CLOUD_MODEL={json.dumps(args.model)} "
        f"ORCHESTWIN_CLOUD_REVISION={json.dumps(args.revision)} "
        f"nohup bash {CLOUD_ROOT}/environments/training/bootstrap_cloud_serving.sh "
        f"> {log} 2>&1 < /dev/null & echo started"
    )
    run_remote(receipt, script)
    deadline = time.time() + args.timeout
    while True:
        time.sleep(30)
        tail = run_remote(receipt, f"tail -n 3 {log}; pgrep -f bootstrap_cloud_serving.sh || true")
        lines = [line for line in tail.stdout.splitlines() if line.strip()]
        print(" | ".join(lines[-3:])[:300], flush=True)
        if any(line.strip() == "BOOTSTRAP_COMPLETE" for line in lines):
            return
        if not any(line.strip().isdigit() for line in lines):
            raise CloudError(f"bootstrap exited without completion marker; see {log}")
        if time.time() > deadline:
            raise CloudError("bootstrap timeout")


def remote_state(receipt, output):
    state = run_remote(
        receipt, f"cat {output}/supervisor-state.json 2>/dev/null || true", check=False
    ).stdout.strip()
    if not state:
        return None
    try:
        return json.loads(state)
    except ValueError:
        return None


def remote_health(receipt, port):
    probe = run_remote(
        receipt,
        f"curl -s -m 5 -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{port}/health",
        check=False,
    )
    return probe.stdout.strip() in {"200", "401", "403"}


def command_serve(args):
    receipt = load_receipt(args.pod)
    output = f"{SERVING_ROOT}/{args.pod}"
    supervisor = f"{CLOUD_ROOT}/environments/training/run_cloud_serving_job.py"
    python = CLOUD_PYTHON
    current = remote_state(receipt, output)
    alive = run_remote(
        receipt,
        "grep -l '[r]un_cloud_serving_job' /proc/[0-9]*/cmdline 2>/dev/null | head -n 1 | grep -q proc && echo alive || true",
        check=False,
    ).stdout.strip()
    if current is not None and current.get("stage") == "SERVING" and alive == "alive":
        print("supervisor already serving; reusing it", flush=True)
    else:
        launch = (
            f"( {CONTAINER_ENVIRONMENT}; cd {CLOUD_ROOT}/environments/training; "
            f"exec {python} {supervisor} --repo {CLOUD_ROOT} --output {output} --python {python} "
            f"--hf-home {CLOUD_HF_HOME} "
            f"--port {args.port} --idle-minutes {args.idle_minutes} --max-hours {args.max_hours} "
            f"--keepalive-seconds {args.keepalive_seconds} "
            f"--model-repository {json.dumps(args.model)} "
            f"--model-revision {json.dumps(args.revision)} --precision {args.precision} "
            f"--engine {args.engine} --failure-hold-minutes {args.failure_hold_minutes} )"
        )
        run_remote(
            receipt,
            f"mkdir -p {output} && rm -f {output}/stop.request {output}/supervisor-state.json "
            f"&& setsid -f bash -c '{launch}' > {output}/nohup.log 2>&1 < /dev/null && echo started",
        )
    deadline = time.time() + args.timeout
    while True:
        current = remote_state(receipt, output)
        stage = None if current is None else current.get("stage")
        print(f"stage={stage}", flush=True)
        if stage == "SERVING" and remote_health(receipt, args.port):
            break
        if stage in ("STOPPED", "POD_STOP_CONFIRMED", "POD_STOP_UNCONFIRMED", "DIAGNOSTIC_HOLD"):
            raise CloudError(f"supervisor stopped early; see {output}/supervisor.log")
        if time.time() > deadline:
            raise CloudError("serving startup timeout")
        time.sleep(20)
    runtime_file = (
        current.get("runtime_file")
        or run_remote(receipt, f"ls -d {output}/proposal-*/runtime.json | tail -n 1").stdout.strip()
    )
    if not runtime_file:
        raise CloudError("runtime file not found on the pod")
    token_file = runtime_file.rsplit("/", 1)[0] + "/access-token.secret"
    local_dir = STATE_ROOT / args.pod
    runtime = json.loads(run_remote(receipt, f"cat {runtime_file}").stdout)
    token = run_remote(receipt, f"cat {token_file}").stdout.strip()
    local_token = local_dir / "access-token.secret"
    local_token.write_text(token, encoding="ascii")
    runtime["base_url"] = f"http://127.0.0.1:{args.local_port}"
    runtime["token_file"] = str(local_token).replace("\\", "/")
    runtime["timeout_seconds"] = min(1200, int(runtime.get("timeout_seconds", 600)))
    remote_config = local_dir / "proposal-remote.json"
    remote_config.write_text(json.dumps(runtime, indent=2, sort_keys=True), encoding="utf-8")
    receipt.update(
        serving_output=output,
        remote_runtime_file=runtime_file,
        remote_port=args.port,
        local_port=args.local_port,
        proposal_config_file=str(remote_config).replace("\\", "/"),
    )
    save_receipt(args.pod, receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != "env"}, indent=2))


def tunnel_command(receipt):
    keepalive = f"{receipt['serving_output']}/keepalive"
    loop = f"while true; do touch {keepalive}; sleep 300; done"
    return [
        *ssh_command(receipt, tty=False)[:-1],
        "-L",
        f"127.0.0.1:{receipt['local_port']}:127.0.0.1:{receipt['remote_port']}",
        "-o",
        "ExitOnForwardFailure=yes",
        f"root@{receipt['ssh_host']}",
        loop,
    ]


def command_tunnel(args):
    receipt = load_receipt(args.pod)
    if "serving_output" not in receipt:
        raise CloudError("run serve before tunnel")
    command = tunnel_command(receipt)
    if args.print_command:
        print(subprocess.list2cmdline(command))
        return
    process = subprocess.Popen(command)
    save_receipt(args.pod, {**receipt, "tunnel_pid": process.pid})
    print(f"tunnel pid {process.pid} on 127.0.0.1:{receipt['local_port']}")
    if not args.background:
        process.wait()


def command_status(args):
    if args.pod:
        pod = expect(*api("GET", f"/pods/{args.pod}"), 200)
        print(json.dumps(redact(pod), indent=2))
        return
    pods = expect(*api("GET", "/pods"), 200)
    for pod in pods:
        print(
            f"{pod['id']} | {pod.get('name')} | {pod.get('desiredStatus')} | "
            f"{(pod.get('machine') or {}).get('gpuTypeId')} | {pod.get('costPerHr')} USD/h"
        )


def command_stop(args):
    if receipt_path(args.pod).is_file():
        receipt = load_receipt(args.pod)
        if "serving_output" in receipt and "ssh_host" in receipt:
            run_remote(receipt, f"touch {receipt['serving_output']}/stop.request", check=False)
    status, payload = api("POST", f"/pods/{args.pod}/stop")
    print(status, json.dumps(redact(payload))[:300] if isinstance(payload, dict) else status)
    expect(status, payload, 200, 201, 204)


def command_start(args):
    status, payload = api("POST", f"/pods/{args.pod}/start")
    print(status, json.dumps(redact(payload))[:300] if isinstance(payload, dict) else status)
    expect(status, payload, 200, 201, 204)


def command_terminate(args):
    status, payload = api("DELETE", f"/pods/{args.pod}")
    print(status, json.dumps(redact(payload))[:300] if isinstance(payload, dict) else status)
    expect(status, payload, 200, 204)


def build_parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--center", default="CA-MTL-3")
    create.add_argument("--volume", required=True)
    create.add_argument("--gpu", nargs="+", default=list(DEFAULT_GPUS))
    create.add_argument("--image", default=DEFAULT_IMAGE)
    create.add_argument("--disk", type=int, default=40)
    create.add_argument("--cuda", nargs="*", default=list(DEFAULT_CUDA))
    wait = commands.add_parser("wait")
    wait.add_argument("--pod", required=True)
    wait.add_argument("--timeout", type=int, default=900)
    sync = commands.add_parser("sync")
    sync.add_argument("--pod", required=True)
    bootstrap = commands.add_parser("bootstrap")
    bootstrap.add_argument("--pod", required=True)
    bootstrap.add_argument("--model", default="Qwen/Qwen3-Coder-30B-A3B-Instruct")
    bootstrap.add_argument("--revision", default="b2cff646eb4bb1d68355c01b18ae02e7cf42d120")
    bootstrap.add_argument("--timeout", type=int, default=3600)
    serve = commands.add_parser("serve")
    serve.add_argument("--pod", required=True)
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--local-port", type=int, default=8791)
    serve.add_argument("--idle-minutes", type=int, default=30)
    serve.add_argument("--max-hours", type=float, default=6)
    serve.add_argument("--keepalive-seconds", type=int, default=900)
    serve.add_argument("--model", default="Qwen/Qwen3-Coder-30B-A3B-Instruct")
    serve.add_argument("--revision", default="b2cff646eb4bb1d68355c01b18ae02e7cf42d120")
    serve.add_argument("--precision", choices=("4bit", "bf16"), default="bf16")
    serve.add_argument("--engine", choices=("hf", "vllm"), default="vllm")
    serve.add_argument("--failure-hold-minutes", type=int, default=0)
    serve.add_argument("--timeout", type=int, default=2700)
    tunnel = commands.add_parser("tunnel")
    tunnel.add_argument("--pod", required=True)
    tunnel.add_argument("--background", action="store_true")
    tunnel.add_argument("--print-command", action="store_true")
    status = commands.add_parser("status")
    status.add_argument("--pod")
    stop = commands.add_parser("stop")
    stop.add_argument("--pod", required=True)
    terminate = commands.add_parser("terminate")
    terminate.add_argument("--pod", required=True)
    start = commands.add_parser("start")
    start.add_argument("--pod", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handler = globals()["command_" + args.command]
    try:
        handler(args)
    except CloudError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
