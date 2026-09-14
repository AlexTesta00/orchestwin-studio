"""Scoped, offline probes for diagnostic outputs; never publish generated files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from diagnose_source_generation import CASES, read, save, sha

NODE_IMAGE = "sha256:a976b10bab71af1d0fc82aedc4e8ca08eb2242e6e3c16b37b1b87c8ead3c8419"
JAVA_IMAGE = "sha256:956b59834e53d678a077800e26c612da325d22216e95a2eb1c192cd5e38630da"
NODE_PROBE = """const checks = {};
let app;
try { app = require('./app.js'); checks.importWithoutDOM = true; }
catch (error) { checks.importWithoutDOM = false; checks.importError = error.name; }
checks.createReservationExport = typeof app?.createReservation === 'function';
if (checks.createReservationExport) {
  try {
    const a = app.createReservation('Ada');
    const b = app.createReservation('Ada');
    checks.validReservation = typeof a?.id === 'string' && a.id.length > 0 && a.guestName === 'Ada';
    checks.distinctIds = !!a?.id && !!b?.id && a.id !== b.id;
  } catch (error) { checks.validReservation = false; checks.validError = error.name; }
  for (const [label, value] of [['empty', ''], ['whitespace', '   ']]) {
    try { const result = app.createReservation(value); checks[label + 'Rejected'] = !result; }
    catch (error) { checks[label + 'Rejected'] = error instanceof Error; }
  }
}
process.stdout.write(JSON.stringify(checks));
"""
JAVA_COMMAND = (
    "mkdir -p /tmp/classes && "
    "javac -d /tmp/classes src/main/java/org/orchestwin/greeting/*.java && "
    "java -cp /tmp/classes org.orchestwin.greeting.Main"
)


def docker(*args, timeout=30):
    return subprocess.run(
        ["docker", "--context", "desktop-linux", *args],
        capture_output=True,
        check=True,
        timeout=timeout,
    ).stdout


def isolated(folder, workspace, image, command):
    token = uuid4().hex
    container = None
    report = {"image_id": image, "command": command, "network": "none", "read_only_source": True}
    cache_mount = (
        ["--tmpfs", "/home/gradle/.gradle:rw,nosuid,nodev,noexec,size=16m"]
        if image == JAVA_IMAGE
        else []
    )
    try:
        container = (
            docker(
                "create",
                "--pull",
                "never",
                "--name",
                "ow-phase6-diagnosis-" + token,
                "--label",
                "org.orchestwin.phase6-diagnosis-owner=" + token,
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                "65532:65532",
                "--cpus",
                "1",
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=128m",
                *cache_mount,
                "--mount",
                "type=bind,source=" + str(workspace) + ",target=/workspace,readonly",
                "--workdir",
                "/workspace",
                "--log-driver",
                "json-file",
                "--log-opt",
                "max-size=128k",
                "--log-opt",
                "max-file=1",
                "--entrypoint",
                command[0],
                image,
                *command[1:],
            )
            .decode()
            .strip()
        )
        report["container_id"] = container
        inspect = json.loads(docker("inspect", container))[0]
        assert inspect["Image"] == image
        assert inspect["Config"]["Labels"]["org.orchestwin.phase6-diagnosis-owner"] == token
        assert inspect["HostConfig"]["NetworkMode"] == "none"
        assert inspect["HostConfig"]["ReadonlyRootfs"] is True
        assert inspect["Config"]["User"] == "65532:65532"
        binds = [mount for mount in inspect["Mounts"] if mount["Type"] == "bind"]
        assert len(binds) == 1 and binds[0]["RW"] is False
        assert binds[0]["Destination"] == "/workspace"
        assert all(mount["Type"] in {"bind", "tmpfs"} for mount in inspect["Mounts"])
        report["verified_mounts"] = [
            {"type": mount["Type"], "destination": mount["Destination"], "writable": mount["RW"]}
            for mount in inspect["Mounts"]
        ]
        docker("start", container)
        try:
            report["exit_code"] = int(docker("wait", container, timeout=45))
            report["status"] = "COMPLETED"
        except subprocess.TimeoutExpired:
            docker("kill", container)
            report["status"] = "TIMEOUT"
        logs = subprocess.run(
            ["docker", "--context", "desktop-linux", "logs", "--tail", "200", container],
            capture_output=True,
            check=True,
            timeout=15,
        )
        for name, raw in (("stdout", logs.stdout), ("stderr", logs.stderr)):
            if len(raw) > 262144:
                raise ValueError("probe output exceeds retention bound")
            (folder / (name + ".log")).write_bytes(raw)
            report[name + "_sha256"] = hashlib.sha256(raw).hexdigest()
    finally:
        if container:
            inspect = json.loads(docker("inspect", container))[0]
            assert inspect["Config"]["Labels"]["org.orchestwin.phase6-diagnosis-owner"] == token
            docker("rm", "--force", "--volumes", container)
            assert not docker(
                "container", "ls", "--all", "--filter", "id=" + container, "--format", "{{.ID}}"
            ).strip()
            report["container_removed"] = True
        save(folder / "container.json", report)
    return report


def materialize_original(external, target, workspace):
    incoming = external / CASES[target][0]
    snapshot = read(incoming / "source-response.json")["body"]["snapshot"]
    content_root = incoming / ("web" if target == "WEB_STATIC" else "jvm")
    files = []
    for entry in snapshot["files"]:
        # Java diagnostic needs only the original domain/service/Main, no build scripts.
        if target == "JVM_JAVA" and not entry["normalized_path"].startswith("src/main/java/"):
            continue
        if target == "WEB_STATIC" and entry["normalized_path"] != "app.js":
            continue
        raw = (content_root / entry["storage_key"]).read_bytes()
        if (
            len(raw) != entry["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != entry["sha256_digest"]
        ):
            raise ValueError("original source differs from retained artifact")
        destination = (workspace / entry["normalized_path"]).resolve()
        if workspace.resolve() not in destination.parents:
            raise ValueError("source outside disposable diagnostic workspace")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        files.append(entry)
    return files


def check_one(external, folder, target, source):
    folder.mkdir()
    report = {
        "target": target,
        "full_application_qualified": False,
        "source_modified_after_generation": False,
    }
    if target in {"WEB_STATIC", "JVM_JAVA"}:
        workspace = folder / "source"
        workspace.mkdir()
        originals = materialize_original(external, target, workspace)
        report["fixed_original_sources"] = originals
        if source is not None:
            raw = source.read_bytes()
            (workspace / CASES[target][1]).write_bytes(raw)
            report["experimental_single_file_substitution_sha256"] = hashlib.sha256(raw).hexdigest()
        if target == "WEB_STATIC":
            (workspace / "diagnostic-probe.cjs").write_text(NODE_PROBE, encoding="utf-8")
            receipt = isolated(folder, workspace, NODE_IMAGE, ["node", "diagnostic-probe.cjs"])
            if receipt.get("exit_code") == 0:
                report["checks"] = read(folder / "stdout.log")
            report["probe_scope"] = "NODE_CORE_ONLY_NOT_BROWSER_OR_GENERATED_TEST_SUITE"
        else:
            receipt = isolated(folder, workspace, JAVA_IMAGE, ["sh", "-c", JAVA_COMMAND])
            stdout = (folder / "stdout.log").read_text(encoding="utf-8", errors="replace")
            report["checks"] = {
                "compile_and_zero_argument_exit_0": receipt.get("exit_code") == 0,
                "printed_uuid": bool(
                    re.search(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", stdout, re.I)
                ),
                "printed_usage": "usage" in stdout.lower(),
            }
            report["probe_scope"] = "JAVAC_AND_ZERO_ARGUMENT_MAIN_ONLY_NOT_JUNIT"
    else:
        text = source.read_text(encoding="utf-8")
        report["probe_scope"] = "STATIC_TEXT_OBSERVATIONS_ONLY_NO_COMPILATION_CLAIM"
        if target == "JVM_SCALA":
            report["checks"] = {
                "explicit_main_signature": bool(
                    re.search(r"def\s+main\s*\(\s*args\s*:\s*Array\[String\]\s*\)\s*:\s*Unit", text)
                ),
                "extends_app_present": bool(re.search(r"extends\s+App\b", text)),
                "other_top_level_declarations_present": bool(
                    re.search(r"\b(?:class|object)\s+(?:Reservation|ReservationService)\b", text)
                ),
            }
        else:
            report["checks"] = {
                "calls_nonexistent_factory_generateUniqueId": "ReservationFactory.generateUniqueId"
                in text,
                "calls_existing_factory_createReservation": "ReservationFactory.createReservation"
                in text,
                "imports_factory": bool(
                    re.search(
                        r"import\s+org\.orchestwin\.calculator\.domain\.(ReservationFactory|\*)",
                        text,
                    )
                ),
                "imports_reservation": bool(
                    re.search(
                        r"import\s+org\.orchestwin\.calculator\.domain\.(Reservation|\*)", text
                    )
                ),
            }
        report["source_sha256"] = sha(source)
    save(folder / "checks.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--external", type=Path, required=True)
    parser.add_argument("--checks-name", default="checks")
    args = parser.parse_args()
    output, external = args.output.resolve(), args.external.resolve()
    protocol = read(output / "protocol.json")
    inference = read(output / "inference-summary.json")
    if inference["completed_trials"] != inference["planned_trials"]:
        raise ValueError("complete inference matrix required before aggregate checks")
    if not re.fullmatch(r"checks(?:-[a-z0-9]+)*", args.checks_name):
        parser.error("invalid checks directory name")
    checks = output / args.checks_name
    checks.mkdir()
    save(
        checks / "probe-contract.json",
        {
            "source_sha256": sha(Path(__file__)),
            "node_probe": NODE_PROBE,
            "java_command": JAVA_COMMAND,
            "scope": "ISOLATED_DIAGNOSTIC_PROBES_NOT_LEVEL_D",
            "node_invalid_semantics": "An exception or falsy result counts as rejection; error type is not constrained.",
        },
    )
    (checks / Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    results = []
    for target in ("WEB_STATIC", "JVM_JAVA"):
        results.append(
            {
                "id": "HISTORICAL-" + target,
                **check_one(external, checks / ("HISTORICAL-" + target), target, None),
            }
        )
    for trial in protocol["trials"]:
        source = output / trial["id"] / "source.txt"
        if not source.exists():
            continue
        if sha(source) != read(source.parent / "result.json")["source_sha256"]:
            raise ValueError("diagnostic source digest mismatch")
        result = check_one(external, checks / trial["id"], trial["target"], source)
        results.append({"id": trial["id"], "arm": trial["arm"], **result})
        print(json.dumps({"id": trial["id"], "checks": result.get("checks")}), flush=True)
    save(checks / "summary.json", results)


if __name__ == "__main__":
    main()
