"""Audit real WEB_STATIC generation on supplied synthetic cases without publication.

Freeze independent oracles locally before inference. Native output, including
rejected files, is retained unchanged. Execute diagnostics only in isolated Docker.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.proposal_evidence import evidence_application  # noqa: E402
from orchestwin.models.proposal_generation import (  # noqa: E402
    DirectProposalTransport,
    ProposalGenerationError,
    build_proposal_generator,
    wire_value,
)
from orchestwin.models.source_proposals import ModelSourceProposalAdapter  # noqa: E402
from orchestwin.projects.requirements_primitives import snapshot_content_hash  # noqa: E402

IMAGE = "docker.io/library/node:26.7.0-bookworm-slim@sha256:4db36457f406501e6f608802e5da617e5fbd0e80b75901b6a09de1ae5a667d32"
SOURCE_PATHS = {"app.js", "app.test.cjs", "index.html"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(wire_value(value), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def read_cases(path):
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not 1 <= len(cases) <= 8:
        raise ValueError("Provide one to eight synthetic cases")
    ids = set()
    for case in cases:
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,79}", case["id"]) or case["id"] in ids:
            raise ValueError("Unique portable case IDs required")
        ids.add(case["id"])
        if not case["requirements"] or not case["prototype"]["screens"] or not case["oracle"]:
            raise ValueError("Requirements, prototype and independent oracle required")
    return cases


def context(case):
    contents = {
        "requirements": {
            "requirements": [
                {
                    "code": f"REQ-{i + 1:03}",
                    "kind": "FUNCTIONAL",
                    "priority": "MUST",
                    "title": f"Behavior {i + 1}",
                    "statement": statement,
                }
                for i, statement in enumerate(case["requirements"])
            ]
        },
        "design": {"prototype": case["prototype"]},
        "architecture": {
            "style": "Vanilla static browser application; shared business core in app.js, Node tests, inline CSS in index.html. No external dependencies.",
            "locale": case["locale"],
        },
    }
    return {
        "project_id": str(uuid4()),
        "target_selection": {"target": "WEB_STATIC"},
        "fixed_files": [],
        **{kind: {"content": content} for kind, content in contents.items()},
        "provenance_references": [
            {
                "kind": kind.upper(),
                "reference_id": str(uuid4()),
                "version_number": 1,
                "content_hash": snapshot_content_hash(content),
            }
            for kind, content in contents.items()
        ],
    }


class FileEvidence:
    def __init__(self, path):
        self.path, self.requests = path, []

    async def begin(self, *, request, **scope):
        folder = self.path / str(request.request_id)
        folder.mkdir()
        save(folder / "request.json", request.to_snapshot())
        self.requests.append(folder)

    async def append(self, *, generation_id, kind, payload, raw_body=None, **scope):
        folder = self.path / str(generation_id)
        event = {"kind": kind, "payload": payload}
        if raw_body is not None:
            with (folder / (kind + ".bin")).open("xb") as stream:
                stream.write(raw_body)
            event["raw_sha256"] = hashlib.sha256(raw_body).hexdigest()
        save(folder / (kind + ".json"), event)


class Operation:
    def __init__(self, store, adapter, payload):
        self._proposal_evidence_store, self.adapter, self.payload = store, adapter, payload

    @evidence_application
    async def run(self, *, owner_user_id, project_id):
        return await self.adapter.propose_files(task="web-source", context=self.payload)


class DeadlineTransport(DirectProposalTransport):
    def __init__(self, deadline):
        self.deadline = deadline

    async def post_json(self, **kwargs):
        remaining = self.deadline - time.monotonic()
        if remaining < 30:
            raise ProposalGenerationError("BENCHMARK_TIME_BUDGET_EXHAUSTED")
        kwargs["timeout_seconds"] = min(kwargs["timeout_seconds"], remaining)
        return await super().post_json(**kwargs)


def copy_native_sources(store, destination):
    """Select the last complete native attempt per path, never repair its bytes."""
    selected = {}
    for folder in store.requests:
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        step = json.loads(request["input_payload_json"])["context"].get("source_step")
        raw = folder / "HTTP_RESPONSE.bin"
        if not step or not raw.exists():
            continue
        path = step["file"]["normalized_path"]
        if path not in SOURCE_PATHS:
            raise ValueError("Native path outside static diagnostic scope")
        try:
            response = json.loads(raw.read_bytes())
            content = json.loads(response["choices"][0]["message"]["content"])["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if isinstance(content, str):
            selected[path] = (folder, content)
    destination.mkdir()
    rows = []
    for path, (folder, content) in sorted(selected.items()):
        with (destination / path).open("xb") as stream:
            stream.write(content.encode("utf-8"))
        rows.append(
            {
                "path": path,
                "generation_id": folder.name,
                "source_sha256": sha(destination / path),
                "native_response_sha256": sha(folder / "HTTP_RESPONSE.bin"),
            }
        )
    return rows


def docker_test(folder, target):
    name = "ow-proposer-probe-" + uuid4().hex[:16]
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--mount",
        f"type=bind,source={folder.resolve()},target=/app,readonly",
        "--workdir",
        "/app",
        IMAGE,
        "node",
        "--test",
        target,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=35, encoding="utf-8", errors="replace"
        )
        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        cleanup = subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        return {
            "command": command,
            "exit_code": None,
            "timeout_seconds": 35,
            "cleanup_exit_code": cleanup.returncode,
        }


async def run(args):
    cases = read_cases(args.cases)
    args.output.mkdir(parents=True, exist_ok=False)
    files = [Path(__file__), *sorted((ROOT / "src/orchestwin/models").glob("*.py"))]
    protocol = {
        "scope": "SYNTHETIC_SOURCE_DIAGNOSTIC_NOT_FORMAL_THESIS_QUALIFICATION",
        "created_at": datetime.now(UTC).isoformat(),
        "cases": cases,
        "client_inference_deadline_seconds": args.deadline_seconds,
        "client_timeout_is_not_hard_gpu_preemption": True,
        "inference_location": args.inference_location,
        "oracles_sent_to_model": False,
        "database_writes": 0,
        "source_publication": False,
        "production_promotion": False,
        "source_hashes": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in files},
        "cases_sha256": sha(args.cases),
        "node_image": IMAGE,
    }
    save(args.output / "protocol.json", protocol)
    started = time.monotonic()
    generator = build_proposal_generator(
        args.runtime_config.resolve(), transport=DeadlineTransport(started + args.deadline_seconds)
    )
    outcomes = []
    for case in cases:
        case_started = time.monotonic()
        folder = args.output / case["id"]
        folder.mkdir()
        payload = context(case)
        save(folder / "context.json", payload)
        store = FileEvidence(folder)
        print(
            json.dumps({"case": case["id"], "event": "START", "at": datetime.now(UTC).isoformat()}),
            flush=True,
        )
        result = None
        try:
            result = await Operation(store, ModelSourceProposalAdapter(generator), payload).run(
                owner_user_id=uuid4(), project_id=UUID(payload["project_id"])
            )
            outcome = "SOURCE_ACCEPTED"
        except Exception as error:
            outcome = getattr(error, "code", type(error).__name__)
        row = {
            "case": case["id"],
            "outcome": outcome,
            "generation_seconds": round(time.monotonic() - case_started, 2),
            "model_calls": len(store.requests),
            "source_published": False,
            "browser_behavior_verified": False,
            "model_tests_quality": "MANUAL_REVIEW_REQUIRED",
        }
        if result:
            save(folder / "proposal.json", result)
        native = folder / "diagnostic-only-native"
        row["native_files"] = copy_native_sources(store, native)
        if (native / "app.js").exists():
            with (native / "independent.test.cjs").open(
                "x", encoding="utf-8", newline="\n"
            ) as stream:
                stream.write(case["oracle"])
            independent = docker_test(native, "independent.test.cjs")
            save(folder / "independent-tests.json", independent)
            row["independent_tests_exit"] = independent["exit_code"]
            if (native / "app.test.cjs").exists():
                own = docker_test(native, "app.test.cjs")
                save(folder / "model-tests.json", own)
                row["model_tests_exit"] = own["exit_code"]
        save(folder / "result.json", row)
        outcomes.append(row)
        print(json.dumps({"case": case["id"], "event": "END", **row}), flush=True)
    report = {
        "started_at": protocol["created_at"],
        "finished_at": datetime.now(UTC).isoformat(),
        "model_identity": generator.configuration.identity.to_snapshot(),
        "temperature": generator.configuration.temperature,
        "outcomes": outcomes,
        "total_elapsed_seconds": round(time.monotonic() - started, 2),
        "inference_location": args.inference_location,
        "runpod_compute_cost_usd": 0 if args.inference_location == "local" else None,
        "billing_observation": (
            "NO_RUNPOD_INFERENCE"
            if args.inference_location == "local"
            else "REQUIRES_SEPARATE_CLOUD_BILLING_RECEIPT"
        ),
        "database_writes": 0,
        "production_promotion": False,
        "browser_behavior_verified": False,
    }
    save(args.output / "report.json", report)
    manifest = {
        "files": [
            {
                "path": str(p.relative_to(args.output)).replace("\\", "/"),
                "sha256": sha(p),
                "bytes": p.stat().st_size,
            }
            for p in sorted(args.output.rglob("*"))
            if p.is_file()
        ]
    }
    save(args.output / "evidence-manifest.json", manifest)
    print(json.dumps({"complete": True, "report": str(args.output / "report.json")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--inference-location", choices=("local", "runpod"), default="local")
    parser.add_argument(
        "--deadline-seconds", type=int, default=1200, choices=range(30, 1201), metavar="30..1200"
    )
    args = parser.parse_args()
    os.environ["PATH"] = str(args.node.resolve().parent) + os.pathsep + os.environ["PATH"]
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
