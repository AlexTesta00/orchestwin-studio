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
DEFAULT_GPUS = ("NVIDIA A100 80GB PCIe", "NVIDIA RTX PRO 6000 Blackwell Server Edition")
DEFAULT_IMAGE = "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
DEFAULT_CUDA = ()
CREDENTIAL_KEYS = (
    "ORCHESTWIN_RUNPOD_API_KEY",
    "ORCHESTWIN_SMTP_USER",
    "ORCHESTWIN_SMTP_PASSWORD",
    "ORCHESTWIN_NOTIFY_TO",
)


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
