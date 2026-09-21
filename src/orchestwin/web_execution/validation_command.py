"""Explicit operator command for clean-commit, governed Web validation campaigns."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from uuid import UUID, uuid4

import orchestwin
from orchestwin.api.governed_web_context import GovernedWebSettings, WebExecutionBackend
from orchestwin.api.governed_web_execution_runtime import SqlAlchemyGovernedWebExecutionApiService
from orchestwin.api.web_repair_runtime import SqlAlchemyWebRepairApiService
from orchestwin.persistence.config import DatabaseSettings
from orchestwin.persistence.database import create_database_runtime
from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.host_process import run_bounded_host_process
from orchestwin.web_execution.browser_automation import _json, _read, _safe_path
from orchestwin.web_execution.operation_persistence import SqlAlchemyWebOperationStore
from orchestwin.web_execution.phase_runner import load_phase_runner_identity
from orchestwin.web_execution.phase_runtime import ControlledWebNetwork
from orchestwin.web_execution.profile_loader import build_web_profile_catalog_loader
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.reports import WebEvidenceReference
from orchestwin.web_execution.static_browser_jobs import canonical_bytes, content_hash
from orchestwin.web_execution.validation_campaign import (
    CampaignError,
    ValidationCampaign,
    checked_commit,
    create_campaign_plan,
    verify_campaign_plan,
)
from orchestwin.web_execution.validation_ci import GitHubCiVerifier
from orchestwin.web_execution.validation_evidence_persistence import (
    SqlAlchemyWebValidationEvidenceUnitOfWork,
)
from orchestwin.web_execution.validation_fixtures import (
    FIXTURE_IDS,
    load_repository_validation_fixtures,
)
from orchestwin.web_execution.validation_governance import ValidationGovernance
from orchestwin.web_execution.validation_harvest import (
    ContractTestReceipt,
    HarvestFixture,
    HarvestInputs,
    HarvestJourney,
    publish_validation_batch,
    verify_validation_harvest,
)

_CONFIG_FIELDS = {
    "repo_root",
    "runner_manifest",
    "workspaces_root",
    "source_root",
    "evidence_root",
    "docker_context",
    "controlled_network",
    "resources",
    "github_repository",
}
_PATH_FIELDS = ("repo_root", "runner_manifest", "workspaces_root", "source_root", "evidence_root")
_CONTRACT_FILES = (
    "test_validation_fixtures.py",
    "test_profile_fixture_matrix.py",
    "test_static_profile.py",
    "test_vue_profile.py",
    "test_express_profile.py",
    "test_php_profile.py",
    "test_vue_node_profile.py",
)


def load_configuration(path, campaign_dir):
    config = _json(_read(path))
    if not isinstance(config, dict) or set(config) != _CONFIG_FIELDS:
        raise CampaignError("WEB_VALIDATION_CONFIGURATION_FIELDS_INVALID")
    for name in _PATH_FIELDS:
        value = Path(config[name])
        if not value.is_absolute() or ".." in value.parts:
            raise CampaignError("WEB_VALIDATION_ABSOLUTE_PATH_REQUIRED")
        _safe_path(value)
    _safe_path(campaign_dir)
    repo = Path(config["repo_root"]).resolve()
    # No campaign-generated object may dirty the source checkout or overwrite a fixture.
    outputs = [
        Path(config[name]).resolve() for name in ("workspaces_root", "source_root", "evidence_root")
    ]
    outputs.append(campaign_dir.resolve())
    if any(path == repo or repo in path.parents or path in repo.parents for path in outputs):
        raise CampaignError("WEB_VALIDATION_OUTPUT_INSIDE_CHECKOUT")
    if any(
        left == right or left in right.parents or right in left.parents
        for index, left in enumerate(outputs)
        for right in outputs[index + 1 :]
    ):
        raise CampaignError("WEB_VALIDATION_OUTPUT_ROOTS_OVERLAP")
    if config["controlled_network"] is None:
        raise CampaignError("WEB_VALIDATION_CONTROLLED_SETUP_NETWORK_REQUIRED")
    runtime = GovernedWebSettings(
        _env_file=None,
        enabled=True,
        repo_root=repo,
        runner_manifest=Path(config["runner_manifest"]),
        workspaces_root=Path(config["workspaces_root"]),
        docker_context=config["docker_context"],
        controlled_network=ControlledWebNetwork(**config["controlled_network"]),
    )
    resources = SandboxResourceLimits(**config["resources"])
    return config, runtime, resources


def write_receipt(path, value):
    """Write a new immutable receipt. Existing bytes must match exactly."""
    data = canonical_bytes(value) + b"\n"
    _safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _read(path, limit=32 * 1024 * 1024) != data:
            raise CampaignError("WEB_VALIDATION_RECEIPT_ALREADY_EXISTS")
        return
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def harvest_recorded_at(directory, *, campaign_hash, completed_at):
    """Keep one immutable receipt origin after all campaign attempts complete.

    Re-harvesting obtains new provider/test observations, whose own timestamps
    remain in their receipts. Stable proofs retain the original campaign timestamp
    and therefore cannot conflict with their previously persisted evidence IDs.
    """
    now = datetime.now(UTC)
    if (
        not isinstance(campaign_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", campaign_hash) is None
        or not isinstance(completed_at, datetime)
        or completed_at.utcoffset() is None
        or completed_at > now
    ):
        raise CampaignError("WEB_VALIDATION_HARVEST_ORIGIN_INVALID")
    path = directory / "harvest-origin.json"
    _safe_path(path)
    if not path.exists():
        write_receipt(
            path,
            {
                "schema_version": 1,
                "campaign_hash": campaign_hash,
                "recorded_at": now.isoformat(),
            },
        )
    try:
        value = _json(_read(path))
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "campaign_hash", "recorded_at"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["campaign_hash"] != campaign_hash
        ):
            raise ValueError
        recorded_at = datetime.fromisoformat(value["recorded_at"])
        if (
            recorded_at.utcoffset() is None
            or value["recorded_at"] != recorded_at.astimezone(UTC).isoformat()
            or not completed_at <= recorded_at <= now
        ):
            raise ValueError
    except (OSError, TypeError, ValueError):
        raise CampaignError("WEB_VALIDATION_HARVEST_ORIGIN_INVALID") from None
    return recorded_at


def promotion_decision_snapshot(decision):
    """Serialize the actual promotion dataclass into ordinary JSON values."""
    return json.loads(canonical_bytes(asdict(decision)))


def verify_runtime_checkout(repo_root):
    """Reject an installed/loaded engine from another checkout before recording its commit."""
    package = (Path(repo_root) / "src" / "orchestwin").resolve()
    try:
        if Path(orchestwin.__file__).resolve() != package / "__init__.py":
            raise ValueError
        for name, module in tuple(sys.modules.items()):
            if module is None or not (name == "orchestwin" or name.startswith("orchestwin.")):
                continue
            origin = getattr(module, "__file__", None)
            if not isinstance(origin, (str, os.PathLike)) or not Path(
                origin
            ).resolve().is_relative_to(package):
                raise ValueError
    except (OSError, TypeError, ValueError):
        raise CampaignError("WEB_VALIDATION_RUNTIME_CHECKOUT_MISMATCH") from None


@contextmanager
def campaign_lock(directory):
    """Hold an OS lock on a persistent file; process death releases ownership.

    Keeping the inode/file prevents an unlock/unlink/recreate race from allowing
    two independent locks on the same campaign path.
    """
    _safe_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "active.lock"
    _safe_path(lock)
    with lock.open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            acquire = partial(msvcrt.locking, handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = partial(msvcrt.locking, handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            acquire = partial(fcntl.flock, handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = partial(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError:
            raise CampaignError("WEB_VALIDATION_CAMPAIGN_ALREADY_ACTIVE") from None
        try:
            yield
        finally:
            handle.seek(0)
            release()


def store_bytes(store, body, media_type="application/json"):
    item = store.store_artifact(
        run_id=UUID(int=0),
        command_id="web-validation",
        normalized_path="receipt.json",
        content=body,
        media_type=media_type,
    )
    return WebEvidenceReference(item.storage_key, item.sha256_digest, item.size_bytes, media_type)


def read_bytes(store, reference):
    data = store.read(reference.storage_key)
    if (
        data is None
        or len(data) != reference.size_bytes
        or hashlib.sha256(data).hexdigest() != reference.sha256_digest
    ):
        raise CampaignError("WEB_VALIDATION_ARTIFACT_UNAVAILABLE")
    return data


async def contract_receipt(repo, output, store):
    verify_runtime_checkout(repo)
    output.mkdir(parents=True)
    junit = output / "contracts.xml"
    argv = (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-c",
        str(repo / "pyproject.toml"),
        f"--rootdir={repo}",
        *(str(repo / "src/test/python/web_execution" / name) for name in _CONTRACT_FILES),
        f"--junitxml={junit}",
        f"--basetemp={output / 'tmp'}",
    )
    observed = await run_bounded_host_process(
        argv,
        timeout_seconds=300,
        maximum_output_bytes_per_stream=4 * 1024 * 1024,
        environment_overrides={
            "PYTHONPATH": str(repo / "src"),
            "PYTHONSAFEPATH": "1",
            "PYTEST_ADDOPTS": "",
            "PYTEST_PLUGINS": "",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
    )
    result = HostProcessResult(
        HostProcessStatus(observed.status),
        observed.exit_code,
        observed.stdout,
        observed.stderr,
        observed.failure_message,
    )
    stdout = store_bytes(store, result.stdout, "text/plain")
    stderr = store_bytes(store, result.stderr, "text/plain")
    xml = store_bytes(
        store, _read(junit, limit=4 * 1024 * 1024) if junit.exists() else b"", "application/xml"
    )
    required = tuple(
        f"src.test.python.web_execution.test_validation_fixtures.test_repository_fixture_contract[{name}]"
        for name in FIXTURE_IDS
    )
    write_receipt(
        output / "process.json",
        {
            "argv": list(argv),
            "status": result.status.value,
            "exit_code": result.exit_code,
            "stdout": stdout.to_snapshot(),
            "stderr": stderr.to_snapshot(),
            "junit": xml.to_snapshot(),
            "required_test_ids": list(required),
        },
    )
    return ContractTestReceipt(argv, result, stdout, stderr, xml, required)


async def harvest(campaign, *, config, runtime, resources, sessions, directory, publish):
    campaign.guard()
    store = FileSystemSandboxEvidenceStore(Path(config["evidence_root"]))
    attempt_reader = partial(read_bytes, store)
    journeys = []
    for fixture in campaign.fixtures.values():
        roles = {
            row["role"]: row
            for row in campaign.plan["cases"]
            if row["fixture_id"] == fixture.fixture_id
        }
        receipts = {}
        repair_receipt = None
        for role, row in roles.items():
            kwargs, _, operations = await campaign._state(row)
            executions = [item for item in operations if item.kind == "EXECUTION"]
            repairs = [item for item in operations if item.kind == "REPAIR"]
            if len(executions) != (2 if role == "failed" else 1) or any(
                item.state != "COMPLETED" for item in operations
            ):
                raise CampaignError("WEB_VALIDATION_CAMPAIGN_NOT_COMPLETE")
            receipts[role] = await campaign.governance.harvest_attempt(
                **kwargs, attempt_id=executions[0].id
            )
            if role == "failed":
                if len(repairs) != 1:
                    raise CampaignError("WEB_VALIDATION_REPAIR_MISSING")
                repair_receipt = await campaign.governance.harvest_repair(
                    **kwargs, operation_id=repairs[0].id
                )
                receipts["rerun"] = await campaign.governance.harvest_attempt(
                    **kwargs, attempt_id=executions[-1].id
                )
        journeys.append(
            HarvestJourney(
                fixture.fixture_id,
                receipts["valid"],
                receipts["repeated"],
                receipts["failed"],
                *repair_receipt,
                receipts["rerun"],
            )
        )
    recorded_at = harvest_recorded_at(
        directory,
        campaign_hash=campaign.plan["content_hash"],
        completed_at=max(
            receipt.attempt.completed_at
            for journey in journeys
            for receipt in (journey.valid, journey.repeated, journey.failed, journey.rerun)
        ),
    )
    output = directory / f"harvest-{uuid4()}"
    tests = await contract_receipt(runtime.repo_root, output, store)
    campaign.guard()
    manifest = _json(_read(runtime.runner_manifest))
    manifest_ref = store_bytes(store, _read(runtime.runner_manifest))
    bootstrap_refs = tuple(
        store_bytes(
            store,
            _read(runtime.runner_manifest.parent / item["path"], limit=8 * 1024 * 1024),
            "text/plain",
        )
        for item in manifest["artifacts"]
    )
    scopes = [
        profile.scope.to_snapshot() for profile in create_sprint08_web_profile_registry().profiles
    ]
    limitations = store_bytes(
        store,
        canonical_bytes(
            {
                "schema_version": 1,
                "platform_commit": campaign.plan["platform_commit"],
                "profiles": scopes,
            }
        ),
    )
    ci = await asyncio.to_thread(
        GitHubCiVerifier(
            config["github_repository"],
            campaign.plan["platform_commit"],
            repo_root=runtime.repo_root,
            token=os.environ.get("GITHUB_TOKEN"),
        ).verify
    )
    for response in ci.responses:
        store_bytes(store, response.body)
    write_receipt(output / "ci.json", ci.to_snapshot())
    campaign.guard()
    inputs = HarvestInputs(
        platform_commit=campaign.plan["platform_commit"],
        recorded_at=recorded_at,
        fixtures=tuple(
            HarvestFixture(
                item.fixture_id,
                item.profile_id,
                item.profile_version,
                item.selection.language_configuration,
                item.source_tree_hash(),
                item.source_tree_hash(defective=True),
                item.expected_failure_phase,
                item.fixture_bundle_hash,
                item.expected_failure_marker,
            )
            for item in campaign.fixtures.values()
        ),
        journeys=tuple(journeys),
        runner_identities=tuple(
            load_phase_runner_identity(
                runtime.runner_manifest, repo_root=runtime.repo_root, kind=kind
            )
            for kind in ("NODE", "PHP", "BROWSER")
        ),
        bootstrap_manifest_ref=manifest_ref,
        contract_tests=tests,
        limitations_ref=limitations,
        bootstrap_artifacts=bootstrap_refs,
        ci_observation=ci,
    )
    batch = verify_validation_harvest(inputs, read_artifact=attempt_reader)
    for reference, body in batch.artifacts:
        if store_bytes(store, body, reference.media_type) != reference:
            raise CampaignError("WEB_VALIDATION_PROOF_STORAGE_MISMATCH")
    value = {
        "schema_version": 1,
        "campaign_hash": campaign.plan["content_hash"],
        "platform_commit": inputs.platform_commit,
        "recorded_at": inputs.recorded_at.isoformat(),
        "content_hash": batch.content_hash,
        "status": "ELIGIBLE" if batch.is_complete else "INCOMPLETE",
        "published": False,
        "environment": manifest["environment"],
        "resources": resources.to_snapshot(),
        "profiles": scopes,
        "runner_identities": [asdict(item) for item in inputs.runner_identities],
        "fixtures": [
            {
                "fixture_id": item.fixture_id,
                "fixture_bundle_hash": item.fixture_bundle_hash,
                "valid_source_tree_hash": item.source_tree_hash(),
                "failure_source_tree_hash": item.source_tree_hash(defective=True),
            }
            for item in campaign.fixtures.values()
        ],
        "evidence": [item.to_snapshot() for item in batch.records],
        "artifacts": [reference.to_snapshot() for reference, _ in batch.artifacts],
        "promotion_decisions": [
            promotion_decision_snapshot(item) for item in batch.promotion_decisions
        ],
        "ci": ci.to_snapshot(),
    }
    write_receipt(output / "manifest.json", value)
    if publish:
        campaign.guard()
        publication = await publish_validation_batch(
            batch,
            unit_of_work_factory=partial(SqlAlchemyWebValidationEvidenceUnitOfWork, sessions),
            read_artifact=attempt_reader,
        )
        write_receipt(output / "publication.json", asdict(publication))
    return {
        "manifest": str(output / "manifest.json"),
        "status": value["status"],
        "published": bool(publish),
        "evidence_count": len(batch.records),
    }


async def run(args):
    directory = args.campaign_dir.absolute()
    config, runtime, resources = load_configuration(args.config, directory)
    verify_runtime_checkout(runtime.repo_root)
    commit = checked_commit(runtime.repo_root)
    GitHubCiVerifier(config["github_repository"], commit, repo_root=runtime.repo_root)
    if not os.environ.get("ORCHESTWIN_DATABASE_URL"):
        raise CampaignError("WEB_VALIDATION_EXPLICIT_DATABASE_REQUIRED")
    database = DatabaseSettings(_env_file=None)
    configuration_hash = content_hash(
        {
            "configuration": config,
            "database_identity": database.sqlalchemy_url.render_as_string(hide_password=True),
        }
    )
    fixtures = load_repository_validation_fixtures(runtime.repo_root)
    tracked = subprocess.run(
        (
            "git",
            "-C",
            str(runtime.repo_root),
            "ls-files",
            "-z",
            "--",
            "src/test/fixtures/web_level_d",
        ),
        capture_output=True,
        timeout=30,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    expected_paths = {"src/test/fixtures/web_level_d/matrix.json"} | {
        f"src/test/fixtures/web_level_d/{fixture.fixture_id}/{item.path}"
        for fixture in fixtures
        for item in fixture.files
    }
    if tracked.returncode or not expected_paths <= set(tracked.stdout.decode("utf-8").split("\0")):
        raise CampaignError("WEB_VALIDATION_FIXTURE_NOT_COMMITTED")
    runners = tuple(
        load_phase_runner_identity(runtime.runner_manifest, repo_root=runtime.repo_root, kind=kind)
        for kind in ("NODE", "PHP", "BROWSER")
    )
    with campaign_lock(directory):
        if (directory / "tainted.json").exists():
            raise CampaignError("WEB_VALIDATION_CAMPAIGN_TAINTED")
        plan_path = directory / "plan.json"
        if plan_path.exists():
            plan = _json(_read(plan_path))
        else:
            if args.action != "prepare" or args.owner_id is None:
                raise CampaignError("WEB_VALIDATION_PREPARE_OWNER_REQUIRED")
            plan = create_campaign_plan(
                owner_user_id=args.owner_id,
                commit=commit,
                configuration_hash=configuration_hash,
                fixtures=fixtures,
            )
            write_receipt(plan_path, plan)
        verify_campaign_plan(
            plan, commit=commit, configuration_hash=configuration_hash, fixtures=fixtures
        )
        if args.owner_id is not None and str(args.owner_id) != plan["owner_user_id"]:
            raise CampaignError("WEB_VALIDATION_OWNER_MISMATCH")

        def guard():
            try:
                checked_commit(runtime.repo_root, expected=plan["platform_commit"])
            except (CampaignError, OSError, subprocess.TimeoutExpired):
                write_receipt(
                    directory / "tainted.json", {"reason": "SOURCE_TREE_CHANGED_DURING_CAMPAIGN"}
                )
                raise

        db = create_database_runtime(database)
        try:
            sessions = db.session_factory
            operations = SqlAlchemyWebOperationStore(sessions)
            backend = WebExecutionBackend(
                config=runtime,
                content_root=Path(config["source_root"]),
                evidence_root=Path(config["evidence_root"]),
                resources=resources,
            )
            execution = SqlAlchemyGovernedWebExecutionApiService(
                sessions,
                operation_store=operations,
                backend=backend,
                catalog_loader=build_web_profile_catalog_loader(sessions),
            )
            repairs = SqlAlchemyWebRepairApiService(
                sessions, operation_store=operations, content_root=Path(config["source_root"])
            )
            governance = ValidationGovernance(
                sessions,
                operation_store=operations,
                execution_service=execution,
                repair_service=repairs,
                read_service=execution.reads,
                content_root=Path(config["source_root"]),
            )
            campaign = ValidationCampaign(
                plan=plan,
                fixtures=fixtures,
                governance=governance,
                runner_identities=runners,
                guard=guard,
                policy_content_hash=backend.policy.content_hash,
            )
            if args.action == "prepare":
                result = await campaign.prepare()
            elif args.action == "advance":
                if args.decisions is not None:
                    await campaign.approve(_json(_read(args.decisions)))
                result = await campaign.advance()
            elif args.action == "review":
                result = await campaign.review()
            else:
                return await harvest(
                    campaign,
                    config=config,
                    runtime=runtime,
                    resources=resources,
                    sessions=sessions,
                    directory=directory,
                    publish=args.publish,
                )
            path = directory / f"review-{uuid4()}.json"
            write_receipt(path, result)
            return {"review": str(path), "campaign": str(plan_path), "published": False}
        finally:
            try:
                guard()
            finally:
                await db.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "review", "advance", "harvest"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--owner-id", type=UUID)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    if (args.decisions is not None and args.action != "advance") or (
        args.publish and args.action != "harvest"
    ):
        parser.error("decisions require advance; publish requires harvest")
    try:
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                result = runner.run(run(args))
        else:
            result = asyncio.run(run(args))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status", "ELIGIBLE") == "ELIGIBLE" else 2
    except Exception as error:
        # Driver/network errors can include credentials. Stable domain codes are safe.
        message = str(error)
        code = message.split(":", 1)[0] if message.startswith("WEB_") else type(error).__name__
        print(json.dumps({"status": "STOPPED", "code": code}), file=sys.stderr)
        return 1
