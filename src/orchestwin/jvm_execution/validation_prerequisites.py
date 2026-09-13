"""Capture pinned recipe rebuilds and compare retained runner filesystems.

No database, project, Docker socket mount or application execution is involved.
Created containers are never exposed on host ports and are removed by exact ID.
"""

import copy
import hashlib
import re
import shutil
import subprocess
import tarfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Timer
from uuid import uuid4

from orchestwin.jvm_execution.operation_governance import content_hash, read_json
from orchestwin.jvm_execution.validation_campaign import write_once
from orchestwin.jvm_execution.validation_verification import require, same
from orchestwin.jvm_execution.workspaces import read_regular_file, regular_path

FILESYSTEM_EXCLUSIONS = ("etc/hostname", "etc/hosts", "etc/resolv.conf", ".dockerenv")
COMPARISON = "CONTENT_TYPE_MODE_UID_GID_SYMLINK_TARGET_WITHOUT_TIMESTAMPS"
OWNER_LABEL = "org.orchestwin.recipe-proof"


def execution_configuration(value):
    """Ignore only the old bootstrap ownership label, never execution settings."""
    result = copy.deepcopy(value)
    labels = result.get("Labels", {})
    owner = labels.pop("org.orchestwin.jvm-bootstrap", None)
    require(
        owner is None or re.fullmatch(r"[0-9a-f]{32}", owner) is not None, "BOOTSTRAP_LABEL_INVALID"
    )
    return result


def filesystem_inventory(stream):
    """Read tar members without extracting any image-controlled path."""
    items, total = {}, 0
    with tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if name in FILESYSTEM_EXCLUSIONS:
                continue
            require(
                name not in items and len(items) < 100_000 and len(name) < 4096,
                "IMAGE_INVENTORY_LIMIT_OR_DUPLICATE",
            )
            total += member.size
            require(0 <= member.size <= 1024**3 and total <= 4 * 1024**3, "IMAGE_BYTES_LIMIT")
            item = dict(
                type=member.type.decode(),
                mode=member.mode,
                uid=member.uid,
                gid=member.gid,
                linkname=member.linkname,
                size=member.size,
            )
            if member.isfile():
                digest = hashlib.sha256()
                with archive.extractfile(member) as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                item["sha256"] = digest.hexdigest()
            items[name] = item
    return items


class RunnerPrerequisiteCollector:
    def __init__(self, *, repo_root, output_root, images, docker_context):
        self.repo, self.root = Path(repo_root).absolute(), Path(output_root).absolute()
        for path in (self.repo, self.root):
            regular_path(path)
        require(
            set(images) == {"gradle", "sbt"}
            and all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in images.values()),
            "PINNED_RUNNERS_REQUIRED",
        )
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", docker_context) is not None,
            "DOCKER_CONTEXT_INVALID",
        )
        self.images, self.command = images, ["docker", "--context", docker_context]

    def docker(self, arguments, *, timeout=60):
        result = subprocess.run(
            [*self.command, *arguments], capture_output=True, timeout=timeout, check=False
        )
        require(
            len(result.stdout) + len(result.stderr) <= 8 * 1024 * 1024, "PREREQUISITE_OUTPUT_LIMIT"
        )
        return result

    def image(self, identifier):
        result = self.docker(["image", "inspect", identifier])
        require(result.returncode == 0, "IMAGE_INSPECT_FAILED")
        item = read_json(result.stdout)[0]
        require(
            item["Id"] == identifier and item["Os"] == "linux" and item["Architecture"] == "amd64",
            "IMAGE_IDENTITY_INVALID",
        )
        return {key: item[key] for key in ("Id", "Os", "Architecture", "RootFS", "Config")}

    @contextmanager
    def owned_container(self, arguments):
        owner = uuid4().hex
        result = self.docker(
            ["create", "--pull", "never", "--label", f"{OWNER_LABEL}={owner}", *arguments]
        )
        require(result.returncode == 0, "EXPORT_CONTAINER_CREATE_FAILED")
        identifier = result.stdout.decode().strip()
        require(
            re.fullmatch(r"[0-9a-f]{64}", identifier) is not None, "EXPORT_CONTAINER_ID_INVALID"
        )
        try:
            yield identifier
        finally:
            observed = self.docker(
                [
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "' + OWNER_LABEL + '"}}',
                    identifier,
                ]
            )
            require(
                observed.returncode == 0 and observed.stdout.decode().strip() == owner,
                "EXPORT_CONTAINER_OWNERSHIP_MISMATCH",
            )
            require(
                self.docker(["rm", "--force", "--volumes", identifier]).returncode == 0,
                "EXPORT_CONTAINER_CLEANUP_FAILED",
            )

    def filesystem(self, image):
        with self.owned_container(
            ["--network", "none", "--read-only", "--entrypoint", "java", image, "-version"]
        ) as identifier:
            with subprocess.Popen(
                [*self.command, "export", identifier],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as process:
                deadline = Timer(120, process.kill)
                deadline.daemon = True
                deadline.start()
                try:
                    inventory = filesystem_inventory(process.stdout)
                    process.stdout.close()
                    error = process.stderr.read(8192)
                    require(process.wait(timeout=60) == 0 and not error, "IMAGE_EXPORT_FAILED")
                except BaseException:
                    process.kill()
                    process.wait(timeout=15)
                    raise
                finally:
                    deadline.cancel()
            return inventory

    def capture(self):
        require(not self.root.exists(), "PREREQUISITE_OUTPUT_ALREADY_EXISTS")
        self.root.mkdir(parents=True)
        result = self.docker(["info", "--format", "{{json .}}"])
        require(result.returncode == 0, "DAEMON_OBSERVATION_FAILED")
        daemon = read_json(result.stdout)
        write_once(
            self.root / "environment.json",
            {
                key: daemon[key]
                for key in (
                    "ID",
                    "ServerVersion",
                    "OperatingSystem",
                    "OSType",
                    "Architecture",
                    "KernelVersion",
                    "NCPU",
                    "MemTotal",
                    "CgroupDriver",
                    "CgroupVersion",
                )
            },
        )
        for family in ("gradle", "sbt"):
            folder = self.root / family
            context = folder / "context"
            context.mkdir(parents=True)
            paths = [f"infra/jvm-runners/Dockerfile.{family}"]
            if family == "gradle":
                paths.append("infra/jvm-runners/resolve-dependencies.gradle.kts")
            inputs = {}
            for path in [*paths, "infra/jvm-runners/images.lock.json"]:
                data = read_regular_file(self.repo / path, maximum_bytes=1024 * 1024)
                inputs[path] = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
                if path in paths:
                    destination = context / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.repo / path, destination)
                    require(destination.read_bytes() == data, "BUILD_INPUT_CHANGED")
            started = datetime.now(UTC).isoformat()
            result = self.docker(
                [
                    "build",
                    "--pull=false",
                    "--provenance=false",
                    "--progress=plain",
                    "--iidfile",
                    str(folder / "image.txt"),
                    "-f",
                    str(context / paths[0]),
                    str(context),
                ],
                timeout=600,
            )
            log = result.stdout + result.stderr
            (folder / "build.log").write_bytes(log)
            require(result.returncode == 0, "RECIPE_BUILD_FAILED")
            rebuilt = read_regular_file(folder / "image.txt", maximum_bytes=128).decode().strip()
            image = self.images[family]
            built_image, retained_image = self.image(rebuilt), self.image(image)
            same(
                execution_configuration(built_image["Config"]),
                execution_configuration(retained_image["Config"]),
                "REBUILT_IMAGE_CONFIGURATION_MISMATCH",
            )
            write_once(folder / "rebuilt-image.json", built_image)
            write_once(folder / "image.json", retained_image)
            first, second = self.filesystem(image), self.filesystem(rebuilt)
            write_once(folder / "filesystem-0.json", first)
            write_once(folder / "filesystem-1.json", second)
            same(first, second, "REBUILT_FILESYSTEM_MISMATCH")
            with self.owned_container(
                [
                    "--network",
                    "none",
                    "--read-only",
                    "--user",
                    "65532:65532",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--memory",
                    "128m",
                    "--cpus",
                    "0.25",
                    "--pids-limit",
                    "32",
                    "--tmpfs",
                    "/home/gradle/.gradle:rw,nosuid,nodev,size=1m",
                    "--entrypoint",
                    "java",
                    image,
                    "-version",
                ]
            ) as identifier:
                toolchain = self.docker(["start", "--attach", identifier])
            require(toolchain.returncode == 0, "JDK_OBSERVATION_FAILED")
            java_log = toolchain.stdout + toolchain.stderr
            (folder / "java-version.log").write_bytes(java_log)
            write_once(
                folder / "build.json",
                dict(
                    family=family,
                    inputs=inputs,
                    image_id=image,
                    rebuilt_image_id=rebuilt,
                    filesystem_comparison={
                        "verified": True,
                        "inventory_hash": content_hash(first),
                        "entries": len(first),
                        "comparison": COMPARISON,
                        "excluded_docker_injected_files": list(FILESYSTEM_EXCLUSIONS),
                        "containers_removed": True,
                    },
                    image_id_kind="LOCAL_CONFIG_DIGEST",
                    exit_code=result.returncode,
                    started_at=started,
                    completed_at=datetime.now(UTC).isoformat(),
                    log_sha256=hashlib.sha256(log).hexdigest(),
                    toolchain_exit_code=toolchain.returncode,
                    toolchain_sha256=hashlib.sha256(java_log).hexdigest(),
                ),
            )
        return {"runner_prerequisites_captured": True, "level_d_validated": False}
