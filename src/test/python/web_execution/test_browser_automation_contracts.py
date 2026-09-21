"""Pure integrity contracts: these tests do not launch Docker or a browser."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from orchestwin.web_execution.browser_automation import (
    BASE_COMMIT,
    AutomationError,
    canonical_hash,
    decode_probe,
    make_probe_arguments,
    validate_lock,
    verify_parent_manifest,
)


def save_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def lockfile():
    return {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"axe-core": "4.13.0", "playwright": "1.62.1"}},
            **{
                f"node_modules/{name}": {
                    "version": version,
                    "resolved": f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz",
                    "integrity": "sha512-" + base64.b64encode(bytes(64)).decode(),
                }
                for name, version in (
                    ("axe-core", "4.13.0"),
                    ("playwright", "1.62.1"),
                    ("playwright-core", "1.62.1"),
                )
            },
        },
    }


def test_lock_requires_exact_versions_and_real_integrity_shape():
    validate_lock(lockfile())
    invalid = lockfile()
    invalid["packages"]["node_modules/playwright"]["version"] = "9.0.0"
    with pytest.raises(AutomationError):
        validate_lock(invalid)


@pytest.mark.parametrize(
    "field,value",
    [
        ("resolved", "https://evil.invalid/a.tgz"),
        ("integrity", "invented"),
        ("integrity", "sha512-YWJj"),
        ("resolved", "http://registry.npmjs.org/a.tgz"),
    ],
)
def test_lock_rejects_unexpected_source_or_bad_integrity(field, value):
    value_lock = lockfile()
    value_lock["packages"]["node_modules/axe-core"][field] = value
    with pytest.raises(AutomationError):
        validate_lock(value_lock)


def parent_fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    evidence = tmp_path / "previous"
    evidence.mkdir()
    recipes = []
    for name in ("Dockerfile.node", "Dockerfile.browser", "bin/static-server.mjs"):
        relative = f"infra/web-runners/{name}"
        p = repo / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"trusted recipe\n")
        recipes.append({"path": relative, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    artifact = evidence / "probe.stdout.log"
    artifact.write_bytes(b"{}")
    data = {
        "report_type": "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE",
        "status": "IMAGES_BUILT_PROBES_RECORDED",
        "platform_commit": BASE_COMMIT,
        "formal_run_started": False,
        "level_d_validated": False,
        "browser_automation_verified": False,
        "recipes": recipes,
        "artifacts": [
            {"path": artifact.name, "size_bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}
        ],
        "runners": [
            {
                "kind": kind,
                "image_id": "sha256:" + digit * 64,
                "image_id_kind": "LOCAL_CONFIG_DIGEST",
                "registry_manifest_digest": None,
                "probe": {"uid": 65532, "static_http": True, "browser_binaries_present": True},
            }
            for kind, digit in (("NODE", "a"), ("BROWSER", "b"))
        ],
    }
    data["content_hash"] = canonical_hash(data)
    manifest = evidence / "manifest.json"
    save_json(manifest, data)
    return repo, manifest, data


def test_parent_hash_logs_and_recipes_are_verified(tmp_path):
    repo, manifest, _ = parent_fixture(tmp_path)
    parent = verify_parent_manifest(manifest, repo)
    assert parent["platform_commit"] == BASE_COMMIT
    (manifest.parent / "probe.stdout.log").write_bytes(b"mutation")
    with pytest.raises(AutomationError):
        verify_parent_manifest(manifest, repo)


@pytest.mark.parametrize("mutation", ["manifest", "recipe", "traversal", "duplicate"])
def test_parent_rejects_corruption_and_unsafe_evidence(tmp_path, mutation):
    repo, manifest, data = parent_fixture(tmp_path)
    if mutation == "manifest":
        data["status"] = "FAILED"
    elif mutation == "recipe":
        (repo / data["recipes"][0]["path"]).write_bytes(b"different")
    elif mutation == "traversal":
        data["artifacts"][0]["path"] = "../escape"
        data.pop("content_hash")
        data["content_hash"] = canonical_hash(data)
    else:
        data["artifacts"].append(data["artifacts"][0])
        data.pop("content_hash")
        data["content_hash"] = canonical_hash(data)
    save_json(manifest, data)
    with pytest.raises(AutomationError):
        verify_parent_manifest(manifest, repo)


def test_probe_invocation_never_exposes_host_storage_or_privileged_mode(tmp_path):
    argv = make_probe_arguments(
        ("docker", "--context", "desktop-linux"),
        "sha256:" + "a" * 64,
        "probe-abc",
        "abc",
        tmp_path / "seccomp.json",
    )
    assert argv[3] == "create"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--user") + 1] == "65532:65532"
    assert "--privileged" not in argv
    assert "--volume" not in argv and "--mount" not in argv
    assert "--publish" not in argv and "-p" not in argv
    assert "--ipc=host" not in argv
    assert "--cap-add" not in argv
    assert "--read-only" in argv
    assert any(value.startswith("seccomp=") for value in argv)


def test_probe_rejects_success_with_no_evidence():
    with pytest.raises(AutomationError):
        decode_probe(json.dumps({"status": "PASSED"}).encode())


def encoded(content):
    if not isinstance(content, bytes):
        content = json.dumps(content).encode()
    return {
        "encoding": "base64",
        "content": base64.b64encode(content).decode(),
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def make_png(width, height):
    import struct
    import zlib

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    pixels = zlib.compress((b"\0" + b"\xff\xff\xff" * width) * height)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def successful_probe():
    from orchestwin.web_execution.browser_automation import CHECKS

    return {
        "schema_version": 1,
        "probe_kind": "TRUSTED_BROWSER_INFRASTRUCTURE_FIXTURE",
        "status": "PASSED",
        "uid": 65532,
        "versions": {"playwright": "1.62.1", "axe_core": "4.13.0", "chromium": "test-double"},
        "checks": dict.fromkeys(CHECKS, True),
        "screens": [
            {
                "name": name,
                "width": width,
                "height": height,
                "pointer": "Activations: 1",
                "keyboard": "Activations: 2",
                "blocked_requests": 1,
                "screenshot": encoded(make_png(width, height)),
                "dom": encoded(b"<!doctype html><html lang='en'></html>"),
                "axe": encoded({"testEngine": {"version": "4.13.0"}, "violations": []}),
            }
            for name, width, height in (("narrow", 390, 844), ("wide", 1280, 800))
        ],
        "negative_axe": encoded(
            {"testEngine": {"version": "4.13.0"}, "violations": [{"id": "button-name"}]}
        ),
        "events": encoded([]),
        "package_lock": encoded(lockfile()),
    }


def test_probe_validates_and_extracts_observed_bytes():
    summary, files = decode_probe(json.dumps(successful_probe()).encode())
    assert len(files) == 9
    assert summary["negative_control_is_a_fixture_not_a_user_finding"] is True
    assert files["wide.png"] == make_png(1280, 800)
    assert json.loads(files["package-lock.observed.json"])["lockfileVersion"] == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-screen",
        "dimension",
        "png",
        "sha",
        "bool",
        "negative-control",
        "keyboard",
        "events",
        "package-version",
    ],
)
def test_probe_never_promotes_partial_or_forged_success(mutation):
    probe = successful_probe()
    if mutation == "missing-screen":
        probe["screens"].pop()
    elif mutation == "dimension":
        probe["screens"][0]["screenshot"] = encoded(make_png(800, 600))
    elif mutation == "png":
        probe["screens"][0]["screenshot"] = encoded(b"not a png")
    elif mutation == "sha":
        probe["screens"][0]["dom"]["sha256"] = "a" * 64
    elif mutation == "bool":
        probe["checks"]["axe_executed"] = 1
    elif mutation == "negative-control":
        probe["negative_axe"] = encoded({"violations": []})
    elif mutation == "keyboard":
        probe["screens"][0]["keyboard"] = "Activations: 1"
    elif mutation == "events":
        probe["events"] = encoded([{}] * 101)
    else:
        probe["versions"]["playwright"] = "latest"
    with pytest.raises(AutomationError):
        decode_probe(json.dumps(probe).encode())


def test_duplicate_json_keys_rejected():
    with pytest.raises(AutomationError, match="DUPLICATE_JSON_KEY"):
        decode_probe(b'{"status":"FAILED","status":"PASSED"}')


def test_nonfinite_json_rejected():
    with pytest.raises(AutomationError, match="NONFINITE_JSON_NUMBER"):
        decode_probe(b'{"value":NaN}')


def test_seccomp_and_javascript_never_use_broad_sandbox_bypasses():
    root = Path(__file__).resolve().parents[4]
    directory = root / "infra/web-runners/browser-automation"
    seccomp = json.loads((directory / "seccomp.json").read_text())
    assert seccomp["defaultAction"] == "SCMP_ACT_ERRNO"
    assert seccomp["architectures"] == ["SCMP_ARCH_X86_64"]
    assert any(
        item.get("errnoRet") == 38 and item["names"] == ["clone3"] for item in seccomp["syscalls"]
    )
    allowed = {
        name
        for item in seccomp["syscalls"]
        if item["action"] == "SCMP_ACT_ALLOW"
        for name in item["names"]
    }
    assert not allowed.intersection({"mount", "bpf", "ptrace", "io_uring_setup", "reboot"})
    js = (directory / "probe.cjs").read_text()
    assert "chromiumSandbox: true" in js
    assert "chromiumSandbox: false" not in js
    assert "process.argv.length === 2" in js
