"""Provision and remove explicitly owned, bounded Docker dependency networks.

The immutable report records provisioning observations, never profile validation.
Application setup containers join the internal bridge. Only the restricted proxy
also joins the dedicated egress bridge. No host ports are published.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from orchestwin.api.governed_web_context import CONTROLLED_GOVERNED_WEB_EXECUTION_POLICY
from orchestwin.sandbox.host_process import run_bounded_host_process
from orchestwin.web_execution.local_runners import CommandOutput
from orchestwin.web_execution.phase_runner import load_phase_runner_identity
from orchestwin.web_execution.phase_runtime import ControlledWebNetwork

RECIPE_PATH = "infra/web-runners/dependency-network/Dockerfile"
PROXY_PATH = "infra/web-runners/dependency-network/proxy.mjs"
PROBE_PATH = "infra/web-runners/dependency-network/probe.mjs"
INPUT_PATHS = (
    RECIPE_PATH,
    PROXY_PATH,
    PROBE_PATH,
    "src/orchestwin/web_execution/dependency_network.py",
    "scripts/sprint12_bootstrap_web_dependency_network.py",
)
PROXY_HOST = "owdep-proxy"
PROXY_PORT = 3128
PROBE_CHECKS = (
    "allowed_npm_tls",
    "unknown_host_denied",
    "literal_ip_denied",
    "metadata_ip_denied",
    "invalid_port_denied",
    "forward_http_denied",
    "direct_egress_denied",
)
ALLOWED_HOSTS = (
    "api.github.com",
    "codeload.github.com",
    "registry.npmjs.org",
    "repo.packagist.org",
)
OWNER_LABEL = "org.orchestwin.dependency-owner"
ROLE_LABEL = "org.orchestwin.dependency-role"
POLICY_LABEL = "org.orchestwin.egress-policy"
DEPENDENCY_POLICY_LABEL = "org.orchestwin.dependency-policy"
REPORT_TYPE = "CONTROLLED_DEPENDENCY_NETWORK_NOT_PROFILE_VALIDATION"
_ID = re.compile(r"[0-9a-f]{64}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_CONTEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_MAX_BYTES = 8 * 1024 * 1024
_PROXY_VARIABLES = tuple(
    name
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY")
    for name in (key, key.lower())
)


class DependencyNetworkError(RuntimeError):
    """Operator-safe stable code; diagnostics remain in bounded local artifacts."""


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(content, object_pairs_hook=pairs)
    except (UnicodeError, ValueError, TypeError):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_INVALID_JSON") from None


def _safe_path(path, *, must_exist=False):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_PATH_NOT_ABSOLUTE_CANONICAL")
    if any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_PATH_REDIRECTED")
    if must_exist and not path.exists():
        raise DependencyNetworkError("DEPENDENCY_NETWORK_INPUT_MISSING")
    return path


def _read(path, limit=_MAX_BYTES):
    path = _safe_path(path, must_exist=True)
    if not path.is_file() or path.stat().st_size > limit:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_INPUT_INVALID")
    with path.open("rb") as source:
        value = source.read(limit + 1)
    if len(value) > limit:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_INPUT_TOO_LARGE")
    return value


def _write(path, value):
    result = {**value, "content_hash": _hash(value)}
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


async def _run(argv, *, timeout, limit, stdin_bytes=None):
    result = await run_bounded_host_process(
        argv,
        timeout_seconds=timeout,
        maximum_output_bytes_per_stream=limit,
        environment_overrides={"GIT_OPTIONAL_LOCKS": "0"},
        stdin_bytes=stdin_bytes,
    )
    return CommandOutput(
        -1 if result.exit_code is None else result.exit_code,
        result.stdout,
        result.stderr,
        result.status,
    )


class _Commands:
    def __init__(self, context, runner):
        if not isinstance(context, str) or not _CONTEXT.fullmatch(context):
            raise DependencyNetworkError("DEPENDENCY_NETWORK_CONTEXT_INVALID")
        self.context = context
        self.docker = ("docker", "--context", context)
        self.runner = runner or _run
        self.output = None
        self.artifacts = []
        self.sequence = 0

    async def command(
        self, argv, label, *, timeout=30, stdin_bytes=None, required=True, sensitive=False
    ):
        self.sequence += 1
        result = await self.runner(
            tuple(argv), timeout=timeout, limit=_MAX_BYTES, stdin_bytes=stdin_bytes
        )
        if self.output is not None:
            for stream in ("stdout", "stderr"):
                # Untrusted removal manifests can point at unrelated containers.
                # Inspect in memory before ownership verification; never persist Env.
                content = (
                    b"INSPECTION_CONTENT_NOT_RECORDED\n" if sensitive else getattr(result, stream)
                )
                name = f"{self.sequence:04d}_{label}.{stream}.log"
                with (self.output / name).open("xb") as target:
                    target.write(content)
                self.artifacts.append(
                    {
                        "path": name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                        "transport_status": result.transport_status,
                        "exit_code": result.exit_code,
                    }
                )
        if required and (result.exit_code != 0 or result.transport_status != "COMPLETED"):
            raise DependencyNetworkError(f"DEPENDENCY_NETWORK_{label}_FAILED")
        return result

    async def docker_command(self, *args, label, **kwargs):
        return await self.command((*self.docker, *args), label, **kwargs)

    async def environment(self, *, build=False):
        observed = _json(
            (
                await self.docker_command(
                    "context", "inspect", self.context, label="CONTEXT_INSPECT"
                )
            ).stdout
        )
        try:
            endpoint = observed[0]["Endpoints"]["docker"]["Host"]
        except (KeyError, TypeError, IndexError):
            raise DependencyNetworkError("DEPENDENCY_NETWORK_CONTEXT_INVALID") from None
        if (
            len(observed) != 1
            or observed[0].get("Name") != self.context
            or not isinstance(endpoint, str)
            or not (
                re.fullmatch(r"npipe:/{4}\./pipe/[A-Za-z0-9_.-]+", endpoint)
                or re.fullmatch(r"unix:///[A-Za-z0-9_./-]+", endpoint)
            )
        ):
            raise DependencyNetworkError("DEPENDENCY_NETWORK_LOCAL_DOCKER_CONTEXT_REQUIRED")
        info = _json(
            (
                await self.docker_command(
                    "info",
                    "--format",
                    '{"os":{{json .OSType}},"arch":{{json .Architecture}}}',
                    label="ENGINE_INSPECT",
                )
            ).stdout
        )
        if (
            not isinstance(info, dict)
            or info.get("os") != "linux"
            or info.get("arch") not in {"amd64", "x86_64"}
        ):
            raise DependencyNetworkError("DEPENDENCY_NETWORK_LINUX_AMD64_REQUIRED")
        if build:
            builder = (
                await self.docker_command(
                    "buildx", "inspect", self.context, label="BUILDER_INSPECT"
                )
            ).stdout.decode("utf-8")
            if re.findall(r"^Driver:\s*(\S+)\s*$", builder, re.MULTILINE) != [
                "docker"
            ] or re.findall(r"^Endpoint:\s*(\S+)\s*$", builder, re.MULTILINE) != [self.context]:
                raise DependencyNetworkError("DEPENDENCY_NETWORK_LOCAL_DOCKER_BUILDER_REQUIRED")
        return {"docker_context": self.context, "endpoint": endpoint, "platform": "linux/amd64"}


async def _checkout(commands, root, sources, *, development, expected=None):
    _verify_runtime_checkout(root)
    head = (
        (await commands.command(("git", "-C", str(root), "rev-parse", "HEAD"), "GIT_HEAD"))
        .stdout.decode("ascii")
        .strip()
    )
    if not re.fullmatch(r"[0-9a-f]{40}", head) or (expected is not None and head != expected):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_COMMIT_CHANGED_OR_INVALID")
    dirty = (
        await commands.command(
            ("git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"),
            "GIT_STATUS",
        )
    ).stdout.strip()
    if dirty and not development:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_WORKING_TREE_NOT_CLEAN_COMMIT_FIRST")
    for path, content in sources.items():
        if _read(root / path) != content:
            raise DependencyNetworkError("DEPENDENCY_NETWORK_SOURCE_CHANGED")
        if not development:
            committed = await commands.command(
                ("git", "-C", str(root), "show", f"{head}:{path}"), "GIT_SOURCE"
            )
            if committed.stdout != content:
                raise DependencyNetworkError("DEPENDENCY_NETWORK_COMMITTED_SOURCE_MISMATCH")
    return head


def _verify_runtime_checkout(root):
    package = root / "src" / "orchestwin"
    if Path(__file__).absolute() != package / "web_execution" / "dependency_network.py":
        raise DependencyNetworkError("DEPENDENCY_NETWORK_RUNTIME_CHECKOUT_MISMATCH")
    for name, module in tuple(sys.modules.items()):
        if name == "orchestwin" or name.startswith("orchestwin."):
            location = getattr(module, "__file__", None)
            if location is not None:
                loaded = _safe_path(Path(location).absolute(), must_exist=True)
                if package not in loaded.parents:
                    raise DependencyNetworkError("DEPENDENCY_NETWORK_RUNTIME_CHECKOUT_MISMATCH")


def _labels(manifest, role):
    return {
        OWNER_LABEL: manifest["owner_id"],
        ROLE_LABEL: role,
        POLICY_LABEL: manifest["execution_policy_hash"],
        DEPENDENCY_POLICY_LABEL: manifest["dependency_policy_hash"],
    }


def _label_arguments(manifest, role):
    return tuple(
        part
        for key, value in _labels(manifest, role).items()
        for part in ("--label", f"{key}={value}")
    )


def _resource(owner, role):
    return {
        "id": None,
        "name": f"owdep-{owner}-{role}",
        "kind": "network" if role in {"internal", "egress"} else "container",
    }


async def _inspect_resource(
    commands, manifest, role, *, hardened=False, allow_absent=False, prestart=False
):
    resource = manifest["resources"][role]
    identifier = resource["id"] or resource["name"]
    response = await commands.docker_command(
        resource["kind"],
        "inspect",
        identifier,
        label=f"INSPECT_{role.upper()}",
        sensitive=resource["kind"] == "container",
        required=False,
    )
    if response.exit_code != 0 or response.transport_status != "COMPLETED":
        if allow_absent:
            flags = ("--all",) if resource["kind"] == "container" else ()
            selection = f"id={identifier}" if resource["id"] else f"name={identifier}"
            listing = await commands.docker_command(
                resource["kind"],
                "ls",
                *flags,
                "--no-trunc",
                "--filter",
                selection,
                "--format",
                "{{.ID}}",
                label=f"CONFIRM_ABSENCE_{role.upper()}",
            )
            if not listing.stdout.strip():
                return None
        raise DependencyNetworkError("DEPENDENCY_NETWORK_RESOURCE_INSPECT_FAILED")
    observed = _json(response.stdout)
    if not isinstance(observed, list) or len(observed) != 1 or not isinstance(observed[0], dict):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_RESOURCE_INSPECT_INVALID")
    item = observed[0]
    if resource["kind"] == "container" and commands.output is not None:
        projection = _inspection_projection(item)
        content = json.dumps(projection, indent=2, sort_keys=True).encode() + b"\n"
        name = f"{commands.sequence:04d}_INSPECT_{role.upper()}.observation.json"
        with (commands.output / name).open("xb") as output:
            output.write(content)
        commands.artifacts.append(
            {
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    if not isinstance(item.get("Id"), str) or not _ID.fullmatch(item["Id"]):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_RESOURCE_ID_INVALID")
    labels = (
        item.get("Labels")
        if resource["kind"] == "network"
        else item.get("Config", {}).get("Labels")
    )
    if (
        (resource["id"] is not None and item["Id"] != resource["id"])
        or item.get("Name", "").removeprefix("/") != resource["name"]
        or not isinstance(labels, dict)
        or any(labels.get(key) != value for key, value in _labels(manifest, role).items())
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_RESOURCE_OWNERSHIP_MISMATCH")
    if hardened:
        if resource["kind"] == "network":
            if item.get("Driver") != "bridge" or item.get("Internal") is not (role == "internal"):
                raise DependencyNetworkError("DEPENDENCY_NETWORK_BRIDGE_CONFINEMENT_MISMATCH")
        else:
            _verify_container(item, manifest, role, prestart=prestart)
    return item


def _environment_cleared(environment):
    return isinstance(environment, list) and all(
        [entry for entry in environment if isinstance(entry, str) and entry.startswith(f"{key}=")]
        == [f"{key}="]
        for key in _PROXY_VARIABLES
    )


def _inspection_projection(item):
    """Persist only bounded identities and security booleans, never arbitrary Env/labels."""

    def token(value):
        return (
            value
            if isinstance(value, str) and re.fullmatch(r"(?:sha256:)?[A-Za-z0-9_.-]{1,128}", value)
            else "UNEXPECTED_OR_EMPTY"
        )

    config = item.get("Config") or {}
    host = item.get("HostConfig") or {}
    settings = item.get("NetworkSettings") or {}
    return {
        "container_id": token(item.get("Id")),
        "image_id": token(item.get("Image")),
        "user_65532": config.get("User") == "65532:65532",
        "proxy_environment_cleared": _environment_cleared(config.get("Env")),
        "read_only": host.get("ReadonlyRootfs") is True,
        "privileged": host.get("Privileged") is True,
        "capabilities_dropped": host.get("CapDrop") == ["ALL"] and not host.get("CapAdd"),
        "no_new_privileges": host.get("SecurityOpt") == ["no-new-privileges"],
        "logging_disabled": host.get("LogConfig") == {"Type": "none", "Config": {}},
        "host_ports_bound": bool(host.get("PortBindings")),
        "host_mounts_present": bool(host.get("Binds") or host.get("Mounts") or item.get("Mounts")),
        "network_mode": token(host.get("NetworkMode")),
        "running": (item.get("State") or {}).get("Running") is True,
        "networks": [
            {
                "name": token(name),
                "network_id": token(network.get("NetworkID")),
                "proxy_alias_present": PROXY_HOST in (network.get("Aliases") or []),
            }
            for name, network in (settings.get("Networks") or {}).items()
        ],
    }


def _verify_container(item, manifest, role, *, prestart=False):
    config, host, settings = (
        item.get("Config", {}),
        item.get("HostConfig", {}),
        item.get("NetworkSettings", {}),
    )
    expected_image = (
        manifest["proxy_image_id"] if role == "proxy" else manifest["node_runner"]["image_id"]
    )
    if not _environment_cleared(config.get("Env", [])):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_INHERITED_PROXY_ENVIRONMENT")
    if (
        item.get("Image") != expected_image
        or config.get("User") != "65532:65532"
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("CapDrop") != ["ALL"]
        or host.get("CapAdd")
        or host.get("LogConfig") != {"Type": "none", "Config": {}}
        or host.get("SecurityOpt") != ["no-new-privileges"]
        or any(host.get(field) for field in ("PortBindings", "Binds", "Mounts"))
        or item.get("Mounts")
        or any(settings.get("Ports", {}).values())
        or host.get("Memory") != 268435456
        or host.get("MemorySwap") != 268435456
        or host.get("NanoCpus") != 500000000
        or host.get("PidsLimit") != 64
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_CONTAINER_SECURITY_MISMATCH")
    expected_roles = ("internal", "egress") if role == "proxy" else ("internal",)
    expected = {
        manifest["resources"][name]["name"]: manifest["resources"][name]["id"]
        for name in expected_roles
    }
    networks = settings.get("Networks", {})
    internal_id = manifest["resources"]["internal"]["id"]
    if host.get("NetworkMode") != internal_id:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_CONTAINER_ATTACHMENTS_MISMATCH")
    if prestart:
        # Docker create has not allocated endpoint IDs yet. Its exact NetworkMode
        # selects the internal bridge; the actual ID is checked again after start.
        if (
            role != "probe"
            or len(networks) != 1
            or not set(networks).issubset({internal_id, manifest["resources"]["internal"]["name"]})
            or any(
                network.get("NetworkID") not in {"", internal_id} for network in networks.values()
            )
        ):
            raise DependencyNetworkError("DEPENDENCY_NETWORK_CONTAINER_ATTACHMENTS_MISMATCH")
        return
    if set(networks) != set(expected) or any(
        networks[name].get("NetworkID") != identity for name, identity in expected.items()
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_CONTAINER_ATTACHMENTS_MISMATCH")
    if role == "proxy" and (
        PROXY_HOST not in networks[manifest["resources"]["internal"]["name"]].get("Aliases", [])
        or item.get("State", {}).get("Running") is not True
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_PROXY_NOT_READY")


def _security_arguments():
    return (
        "--pull=never",
        "--user",
        "65532:65532",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "64",
        "--log-driver",
        "none",
        *(part for key in _PROXY_VARIABLES for part in ("--env", f"{key}=")),
    )


async def _image(commands, identity):
    if not isinstance(identity, str) or not _IMAGE.fullmatch(identity):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_IMAGE_ID_INVALID")
    observed = _json(
        (await commands.docker_command("image", "inspect", identity, label="IMAGE_INSPECT")).stdout
    )
    if (
        not isinstance(observed, list)
        or len(observed) != 1
        or observed[0].get("Id") != identity
        or observed[0].get("Os") != "linux"
        or observed[0].get("Architecture") != "amd64"
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_IMAGE_IDENTITY_MISMATCH")


async def _cleanup(commands, manifest):
    failures = []
    for role in ("probe", "proxy", "internal", "egress"):
        if role not in manifest["resources"]:
            continue
        try:
            item = await _inspect_resource(commands, manifest, role, allow_absent=True)
            if item is None:
                manifest["resources"].pop(role)
                continue
            args = (
                ("rm", "--force", item["Id"])
                if role in {"probe", "proxy"}
                else ("network", "rm", item["Id"])
            )
            await commands.docker_command(*args, label=f"REMOVE_{role.upper()}")
            manifest["resources"].pop(role)
        except (DependencyNetworkError, OSError, ValueError, TypeError) as error:
            failures.append(
                {
                    "role": role,
                    "code": str(error)
                    if isinstance(error, DependencyNetworkError)
                    else type(error).__name__,
                }
            )
    return failures


async def _complete_cleanup(commands, manifest):
    task = asyncio.create_task(_cleanup(commands, manifest))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


async def create_dependency_network(
    *, repo_root, runner_manifest, output_root, docker_context, development=False, runner=None
):
    """Create fresh owned resources, verify positive/negative probes and retain receipts."""
    if type(development) is not bool:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_DEVELOPMENT_FLAG_INVALID")
    root = _safe_path(repo_root, must_exist=True)
    output = _safe_path(output_root)
    if output == root or root in output.parents or output in root.parents:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_OUTPUT_MUST_BE_OUTSIDE_REPOSITORY")
    if output.exists():
        raise DependencyNetworkError("DEPENDENCY_NETWORK_OUTPUT_ALREADY_EXISTS")
    sources = {path: _read(root / path) for path in INPUT_PATHS}
    recipe = sources[RECIPE_PATH].decode("utf-8")
    references = re.findall(
        r"^FROM\s+(docker\.io/library/node:[\w.-]+@sha256:[0-9a-f]{64})\s*$", recipe, re.MULTILINE
    )
    if (
        len(references) != 1
        or len(re.findall(r"^FROM\s", recipe, re.MULTILINE | re.IGNORECASE)) != 1
        or re.search(r"^\s*(?:RUN|ADD|ONBUILD|ARG)\s", recipe, re.MULTILINE | re.IGNORECASE)
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_OFFLINE_PINNED_RECIPE_REQUIRED")
    identity = load_phase_runner_identity(Path(runner_manifest), repo_root=root, kind="NODE")
    commands = _Commands(docker_context, runner)
    commit = await _checkout(commands, root, sources, development=development)
    environment = await commands.environment(build=True)
    await _image(commands, identity.image_id)
    owner = uuid4().hex
    policy = {
        "allowed_hosts": list(ALLOWED_HOSTS),
        "allowed_port": 443,
        "method": "CONNECT",
        "resolution": "PUBLIC_IPV4_PINNED",
        "tls_inspection": False,
        "proxy_sha256": hashlib.sha256(sources[PROXY_PATH]).hexdigest(),
    }
    manifest = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "status": "PROVISIONING",
        "created_at": datetime.now(UTC).isoformat(),
        "owner_id": owner,
        "platform_commit": commit,
        "development": development,
        "committed_sources_verified": not development,
        "level_d_validated": False,
        "environment": environment,
        "execution_policy_hash": CONTROLLED_GOVERNED_WEB_EXECUTION_POLICY.content_hash,
        "dependency_policy": policy,
        "dependency_policy_hash": _hash(policy),
        "sources": [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for path, content in sources.items()
        ],
        "node_runner": asdict(identity),
        "proxy_image_id": None,
        "resources": {},
        "controlled_network": None,
        "probes": None,
        "artifacts": commands.artifacts,
        "cleanup_failures": [],
    }
    output.mkdir(parents=True)
    commands.output = output
    snapshot_number = 0

    def snapshot():
        nonlocal snapshot_number
        snapshot_number += 1
        _write(output / f"progress-{snapshot_number:04d}.json", manifest)

    snapshot()
    try:
        with tempfile.TemporaryDirectory(prefix="build-", dir=output) as folder:
            build_root = Path(folder)
            (build_root / "Dockerfile").write_bytes(sources[RECIPE_PATH])
            (build_root / "proxy.mjs").write_bytes(sources[PROXY_PATH])
            iidfile = output / "proxy-image.id"
            await commands.docker_command(
                "buildx",
                "build",
                "--builder",
                docker_context,
                "--load",
                "--network=none",
                "--platform",
                "linux/amd64",
                "--pull=false",
                *(part for key in _PROXY_VARIABLES for part in ("--build-arg", f"{key}=")),
                "--iidfile",
                str(iidfile),
                str(build_root),
                label="BUILD_PROXY",
                timeout=300,
            )
            image_id = _read(iidfile, 1024).decode("ascii").strip()
        await _image(commands, image_id)
        manifest["proxy_image_id"] = image_id
        for role in ("internal", "egress"):
            resource = _resource(owner, role)
            manifest["resources"][role] = resource
            snapshot()
            flags = ("--internal",) if role == "internal" else ()
            result = await commands.docker_command(
                "network",
                "create",
                "--driver",
                "bridge",
                *flags,
                *_label_arguments(manifest, role),
                resource["name"],
                label=f"CREATE_{role.upper()}",
            )
            identifier = result.stdout.decode("ascii").strip()
            if not _ID.fullmatch(identifier):
                raise DependencyNetworkError("DEPENDENCY_NETWORK_CREATED_ID_INVALID")
            resource["id"] = identifier
            await _inspect_resource(commands, manifest, role, hardened=True)
            snapshot()
        proxy = _resource(owner, "proxy")
        manifest["resources"]["proxy"] = proxy
        snapshot()
        result = await commands.docker_command(
            "create",
            "--name",
            proxy["name"],
            *_security_arguments(),
            *_label_arguments(manifest, "proxy"),
            "--network",
            manifest["resources"]["internal"]["id"],
            "--network-alias",
            PROXY_HOST,
            image_id,
            label="CREATE_PROXY",
        )
        proxy["id"] = result.stdout.decode("ascii").strip()
        if not _ID.fullmatch(proxy["id"]):
            proxy["id"] = None
            raise DependencyNetworkError("DEPENDENCY_NETWORK_CREATED_ID_INVALID")
        snapshot()
        await commands.docker_command(
            "network",
            "connect",
            manifest["resources"]["egress"]["id"],
            proxy["id"],
            label="CONNECT_EGRESS",
        )
        await commands.docker_command("start", proxy["id"], label="START_PROXY")
        await _inspect_resource(commands, manifest, "proxy", hardened=True)
        probe = _resource(owner, "probe")
        manifest["resources"]["probe"] = probe
        snapshot()
        result = await commands.docker_command(
            "create",
            "--interactive",
            "--name",
            probe["name"],
            *_security_arguments(),
            *_label_arguments(manifest, "probe"),
            "--network",
            manifest["resources"]["internal"]["id"],
            "--env",
            f"PROXY_HOST={PROXY_HOST}",
            "--env",
            f"PROXY_PORT={PROXY_PORT}",
            "--entrypoint",
            "node",
            identity.image_id,
            "--input-type=module",
            label="CREATE_PROBE",
        )
        probe["id"] = result.stdout.decode("ascii").strip()
        if not _ID.fullmatch(probe["id"]):
            probe["id"] = None
            raise DependencyNetworkError("DEPENDENCY_NETWORK_CREATED_ID_INVALID")
        snapshot()
        await _inspect_resource(commands, manifest, "probe", hardened=True, prestart=True)
        result = await commands.docker_command(
            "start",
            "--attach",
            "--interactive",
            probe["id"],
            label="PROBE",
            timeout=60,
            stdin_bytes=sources[PROBE_PATH],
        )
        observed = _json(result.stdout)
        if (
            not isinstance(observed, dict)
            or set(observed) != {"schema_version", "passed", "checks"}
            or type(observed["schema_version"]) is not int
            or observed["schema_version"] != 1
            or observed["passed"] is not True
            or not isinstance(observed["checks"], dict)
            or set(observed["checks"]) != set(PROBE_CHECKS)
            or any(value is not True for value in observed["checks"].values())
        ):
            raise DependencyNetworkError("DEPENDENCY_NETWORK_PROBE_CHECKS_FAILED")
        manifest["probes"] = observed
        await _inspect_resource(commands, manifest, "probe", hardened=True)
        await commands.docker_command("rm", "--force", probe["id"], label="REMOVE_PROBE")
        manifest["resources"].pop("probe")
        await _checkout(commands, root, sources, development=development, expected=commit)
        for role in ("internal", "egress", "proxy"):
            observation = await _inspect_resource(commands, manifest, role, hardened=True)
            if role in {"internal", "egress"} and set(observation.get("Containers", {})) != {
                proxy["id"]
            }:
                raise DependencyNetworkError("DEPENDENCY_NETWORK_UNEXPECTED_NETWORK_MEMBER")
        manifest["controlled_network"] = asdict(
            ControlledWebNetwork(
                name=manifest["resources"]["internal"]["name"],
                network_id=manifest["resources"]["internal"]["id"],
                policy_hash=manifest["execution_policy_hash"],
                proxy_host=PROXY_HOST,
                proxy_port=PROXY_PORT,
            )
        )
        manifest["status"] = "READY"
        return _write(output / "manifest.json", manifest)
    except BaseException as error:
        manifest["status"] = "FAILED"
        manifest["failure_code"] = (
            str(error) if isinstance(error, DependencyNetworkError) else type(error).__name__
        )
        manifest["cleanup_failures"], _ = await _complete_cleanup(commands, manifest)
        _write(output / "manifest.json", manifest)
        raise


def _load_manifest(path):
    manifest = _json(_read(path, 2 * 1024 * 1024))
    if not isinstance(manifest, dict):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_INVALID")
    content = {key: value for key, value in manifest.items() if key != "content_hash"}
    if (
        manifest.get("content_hash") != _hash(content)
        or manifest.get("schema_version") != 1
        or manifest.get("report_type") != REPORT_TYPE
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_INTEGRITY_INVALID")
    owner = manifest.get("owner_id")
    try:
        if not isinstance(owner, str) or UUID(hex=owner).hex != owner:
            raise ValueError("owner")
    except (ValueError, AttributeError):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_OWNER_INVALID") from None
    resources = manifest.get("resources")
    if not isinstance(resources, dict) or not set(resources).issubset(
        {"internal", "egress", "proxy", "probe"}
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_RESOURCES_INVALID")
    for role, resource in resources.items():
        expected = _resource(owner, role)
        if (
            not isinstance(resource, dict)
            or set(resource) != set(expected)
            or resource.get("name") != expected["name"]
            or resource.get("kind") != expected["kind"]
            or (
                resource.get("id") is not None
                and (not isinstance(resource["id"], str) or not _ID.fullmatch(resource["id"]))
            )
        ):
            raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_RESOURCES_INVALID")
    ids = [r["id"] for r in resources.values() if r["id"] is not None]
    if (
        len(ids) != len(set(ids))
        or any(
            not isinstance(manifest.get(field), str) or not _ID.fullmatch(manifest[field])
            for field in ("execution_policy_hash", "dependency_policy_hash")
        )
        or not isinstance(manifest.get("environment"), dict)
    ):
        raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_POLICY_INVALID")
    return manifest


async def remove_dependency_network(manifest_path, *, docker_context, runner=None):
    """Preflight every identity and ownership label before removing exact Docker IDs."""
    path = _safe_path(manifest_path, must_exist=True)
    manifest = _load_manifest(path)
    if manifest["environment"].get("docker_context") != docker_context:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_CONTEXT_MISMATCH")
    commands = _Commands(docker_context, runner)
    environment = await commands.environment()
    if environment != manifest["environment"]:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_MANIFEST_ENDPOINT_CHANGED")
    for role in tuple(manifest["resources"]):
        if await _inspect_resource(commands, manifest, role, allow_absent=True) is None:
            manifest["resources"].pop(role)
    output = path.parent / f"removal-{uuid4().hex}"
    output.mkdir()
    commands.output = output
    failures, cancelled = await _complete_cleanup(commands, manifest)
    result = _write(
        output / "manifest.json",
        {
            **{key: value for key, value in manifest.items() if key != "content_hash"},
            "status": "REMOVAL_FAILED" if failures else "REMOVED",
            "source_manifest_hash": manifest["content_hash"],
            "controlled_network": None,
            "cleanup_failures": failures,
            "artifacts": commands.artifacts,
        },
    )
    if cancelled:
        raise asyncio.CancelledError
    if failures:
        raise DependencyNetworkError("DEPENDENCY_NETWORK_REMOVAL_INCOMPLETE")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("create")
    for name in ("repo-root", "runner-manifest", "output-root"):
        create.add_argument(f"--{name}", required=True, type=Path)
    create.add_argument("--docker-context", required=True)
    create.add_argument(
        "--development",
        action="store_true",
        help="Explicit development diagnostics; never verifies committed provisioning sources.",
    )
    remove = commands.add_parser("remove")
    remove.add_argument("--manifest", required=True, type=Path)
    remove.add_argument("--docker-context", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            result = asyncio.run(
                create_dependency_network(
                    repo_root=args.repo_root,
                    runner_manifest=args.runner_manifest,
                    output_root=args.output_root,
                    docker_context=args.docker_context,
                    development=args.development,
                )
            )
        else:
            result = asyncio.run(
                remove_dependency_network(args.manifest, docker_context=args.docker_context)
            )
    except (DependencyNetworkError, OSError, ValueError) as error:
        print(
            str(error)
            if isinstance(error, DependencyNetworkError)
            else f"DEPENDENCY_NETWORK_{type(error).__name__.upper()}"
        )
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "content_hash": result["content_hash"],
                "level_d_validated": False,
            },
            sort_keys=True,
        )
    )
    return 0
