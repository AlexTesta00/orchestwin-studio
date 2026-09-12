"""Trusted preparation and real phase composition for governed Web API execution."""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_EXECUTION_POLICY
from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import WebDetectionSnapshot, WebTextFile
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_browser_executor import GovernedWebBrowserExecutor
from orchestwin.web_execution.phase_executor import GovernedWebPhaseExecutor
from orchestwin.web_execution.phase_runner import load_phase_runner_identity
from orchestwin.web_execution.phase_runtime import ControlledWebNetwork
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_contracts import WebProfileRunnerSet
from orchestwin.web_execution.verified_browser_runner import read_regular
from orchestwin.web_execution.workspaces import (
    _read_object,
    _regular_parents,
    materialize_web_source_snapshot,
)
from orchestwin.workflow.web_execution import (
    LocalGovernedWebExecutionService,
    WebExecutionRequest,
    _rerun_issue,
)


class GovernedWebSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_GOVERNED_WEB_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )
    enabled: bool = False
    repo_root: Path | None = None
    runner_manifest: Path | None = None
    workspaces_root: Path | None = None
    docker_context: str = "desktop-linux"
    controlled_network: ControlledWebNetwork | None = None

    @model_validator(mode="after")
    def validate_runtime_paths(self):
        if self.enabled and any(
            path is None or not path.is_absolute() or ".." in path.parts
            for path in (self.repo_root, self.runner_manifest, self.workspaces_root)
        ):
            raise ValueError("enabled governed Web runtime requires absolute trusted paths")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.docker_context) is None:
            raise ValueError("governed Web Docker context is invalid")
        if (
            self.controlled_network is not None
            and self.controlled_network.policy_hash != DEFAULT_SANDBOX_EXECUTION_POLICY.content_hash
        ):
            raise ValueError("controlled Web network must bind the current execution policy")
        return self


@dataclass(frozen=True)
class PreparedApiWebExecution:
    revision: object
    command: object
    registry: object
    snapshot: object
    locks: object
    contract: object
    execution_identity: object
    browser_identity: object
    request: WebExecutionRequest
    payload: dict


class _Clock:
    def now(self):
        return datetime.now(UTC)


class _AttemptId:
    def __init__(self, value):
        self.value = value

    def new_id(self):
        return self.value


class WebExecutionBackend:
    def __init__(self, *, config, content_root, evidence_root, resources):
        self.config = config
        self.content_root = Path(content_root).absolute()
        self.evidence_root = Path(evidence_root).absolute()
        self.resources = resources
        self.policy = DEFAULT_SANDBOX_EXECUTION_POLICY

    def prepare(self, revision, *, command, registry, previous):
        """Read source objects and bootstrap lineage; no workspace or process is created."""
        if not self.config.enabled:
            raise ValueError("WEB_EXECUTION_RUNTIME_DISABLED")
        for path in (
            self.config.repo_root,
            self.config.runner_manifest,
            self.config.workspaces_root,
            self.content_root,
            self.evidence_root,
        ):
            _regular_parents(path)
        roots = (self.content_root, self.evidence_root, self.config.workspaces_root)
        if any(
            left == right or left in right.parents or right in left.parents
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise ValueError("WEB_EXECUTION_STORAGE_ROOTS_OVERLAP")
        if (
            revision.id != command.source_revision_id
            or command.policy_content_hash != self.policy.content_hash
        ):
            raise ValueError("WEB_EXECUTION_POLICY_OR_SOURCE_MISMATCH")
        text_files = []
        if (
            len(revision.files) > 1000
            or sum(item.size_bytes for item in revision.files) > 20 * 1024 * 1024
        ):
            raise ValueError("WEB_EXECUTION_SOURCE_BUDGET_EXCEEDED")
        for entry in sorted(revision.files, key=lambda item: item.normalized_path):
            content = _read_object(self.content_root, entry.to_snapshot())
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            text_files.append(WebTextFile(entry.normalized_path, text, entry.sha256_digest))
        snapshot = WebDetectionSnapshot(
            revision.source_tree_hash,
            tuple(sorted(item.normalized_path for item in revision.files)),
            tuple(text_files),
        )
        locks = validate_web_dependency_locks(snapshot, selection=revision.target_selection)
        profile = registry.find(command.profile_id, command.profile_version)
        if profile is None or profile.scope.target != revision.target_selection.target:
            raise ValueError("WEB_EXECUTION_PROFILE_MISMATCH")
        validation = profile.validate(
            snapshot, selection=revision.target_selection, lock_report=locks
        )
        if not validation.is_ready:
            raise ValueError("WEB_EXECUTION_PROFILE_INPUT_INVALID")
        kind = "PHP" if revision.target_selection.target.value == "WEB_PHP" else "NODE"
        identity = load_phase_runner_identity(
            self.config.runner_manifest, repo_root=self.config.repo_root, kind=kind
        )
        browser = None
        if revision.target_selection.target.value != "WEB_NODE_EXPRESS":
            browser = load_phase_runner_identity(
                self.config.runner_manifest, repo_root=self.config.repo_root, kind="BROWSER"
            )
        runners = WebProfileRunnerSet(
            identity.image_id.removeprefix("sha256:"),
            None if browser is None else browser.image_id.removeprefix("sha256:"),
        )
        if (command.execution_runner_image_digest, command.browser_runner_image_digest) != (
            runners.execution_runner_image_digest,
            runners.browser_runner_image_digest,
        ):
            raise ValueError("WEB_EXECUTION_RUNNER_MISMATCH")
        if (
            browser is not None
            and browser.bootstrap_manifest_hash != identity.bootstrap_manifest_hash
        ):
            raise ValueError("WEB_EXECUTION_BOOTSTRAP_MISMATCH")
        routes = tuple(
            WebBrowserRouteSpec(item.route_id, item.path) for item in command.declared_routes
        )
        contract = profile.create_contract(
            snapshot,
            selection=revision.target_selection,
            lock_report=locks,
            source_revision_content_hash=revision.content_hash,
            source_tree_hash=revision.source_tree_hash,
            runners=runners,
            declared_routes=routes,
        )
        request = WebExecutionRequest(
            project_id=revision.project_id,
            owner_user_id=revision.created_by_user_id,
            source_revision=revision,
            snapshot=snapshot,
            selection=revision.target_selection,
            lock_report=locks,
            profile_id=command.profile_id,
            profile_version=command.profile_version,
            runners=runners,
            policy_content_hash=self.policy.content_hash,
            purpose=command.purpose,
            trigger=command.trigger,
            authorization=None,
            rerun_phases=command.rerun_phases,
            declared_routes=routes,
        )
        issue = _rerun_issue(request, current=previous)
        if issue:
            raise ValueError("WEB_EXECUTION_RERUN_INVALID")
        if previous is None and command.trigger.value != (
            "PROFILE_VALIDATION" if command.purpose.value == "PROFILE_VALIDATION" else "INITIAL"
        ):
            raise ValueError("WEB_EXECUTION_TRIGGER_INVALID")
        if self.config.controlled_network is None and any(
            command.network_mode.value == "CONTROLLED"
            for phase in contract.execution_plan.phases
            for plan in phase.command_plans
            for command in plan.commands
        ):
            raise ValueError("WEB_EXECUTION_CONTROLLED_NETWORK_REQUIRED")
        interactions = getattr(command, "browser_interactions", ())
        if browser is None and interactions:
            raise ValueError("WEB_EXECUTION_BROWSER_NOT_APPLICABLE")
        harness_hash = seccomp_hash = None
        if browser is not None:
            from orchestwin.web_execution.phase_browser_evidence import create_browser_job

            harness_hash = hashlib.sha256(
                read_regular(
                    self.config.repo_root / "infra/web-runners/phase-browser/inspect.cjs", 30000
                )
            ).hexdigest()
            seccomp_hash = hashlib.sha256(
                read_regular(
                    self.config.repo_root / "infra/web-runners/browser-automation/seccomp.json",
                    2 * 1024 * 1024,
                )
            ).hexdigest()
            if seccomp_hash != "c178b6b5777fbec3e392e49eb928a9a552db7ee8e90aa4da4d6788d78a2f7192":
                raise ValueError("WEB_EXECUTION_SECCOMP_MISMATCH")
            # Validate route/action semantics before presenting any approval request.
            create_browser_job(
                contract.browser_evidence_request,
                execution_attempt_id=revision.id,
                operation_id="0" * 32,
                harness_sha256=harness_hash,
                interactions=interactions,
            )

        def runner(value):
            return (
                None
                if value is None
                else {
                    "kind": value.kind,
                    "image_id": value.image_id,
                    "bootstrap_manifest_hash": value.bootstrap_manifest_hash,
                    "recipe_content_hash": value.recipe_content_hash,
                }
            )

        payload = {
            "schema_version": 1,
            "purpose": command.purpose.value,
            "command": execution_command_snapshot(command),
            "project_id": str(revision.project_id),
            "owner_user_id": str(revision.created_by_user_id),
            "source_revision": revision.reference.to_snapshot(),
            "source_tree_hash": revision.source_tree_hash,
            "contract": contract.to_snapshot(),
            "execution_policy": self.policy.to_snapshot(),
            "resources": self.resources.to_snapshot(),
            "execution_runner": runner(identity),
            "browser_runner": runner(browser),
            "browser_harness_sha256": harness_hash,
            "browser_seccomp_sha256": seccomp_hash,
            "browser_interactions": [item.to_snapshot() for item in interactions],
            "trigger": command.trigger.value,
            "previous_attempt": None
            if previous is None
            else {"id": str(previous.id), "content_hash": previous.content_hash},
            "requested_rerun_phases": None
            if command.rerun_phases is None
            else [item.value for item in command.rerun_phases],
            # Every API execution gets a fresh workspace. Dependencies/build output cannot be reused.
            "effective_phases": [phase.value for phase in WebExecutionPhase],
            "controlled_network": None
            if self.config.controlled_network is None
            else {
                "network_id": self.config.controlled_network.network_id,
                "policy_hash": self.config.controlled_network.policy_hash,
                "proxy_host": self.config.controlled_network.proxy_host,
                "proxy_port": self.config.controlled_network.proxy_port,
            },
        }
        return PreparedApiWebExecution(
            revision,
            command,
            registry,
            snapshot,
            locks,
            contract,
            identity,
            browser,
            request,
            payload,
        )

    async def execute(self, context, *, operation, authorization, attempts):
        from dataclasses import replace

        root = self.config.workspaces_root
        _regular_parents(root)
        root.mkdir(parents=True, exist_ok=True)
        # Only immutable prepared inputs live here; generated sources have their own lifecycle.
        with tempfile.TemporaryDirectory(prefix="api-web-input-", dir=root) as private:
            prepared = materialize_web_source_snapshot(
                context.revision.to_snapshot(),
                content_root=self.content_root,
                workspaces_root=Path(private) / "prepared",
            )
            store = FileSystemSandboxEvidenceStore(self.evidence_root)
            browser = (
                None
                if context.browser_identity is None
                else GovernedWebBrowserExecutor(
                    runner_identity=context.browser_identity,
                    repo_root=self.config.repo_root,
                    evidence_store=store,
                    interactions=getattr(context.command, "browser_interactions", ()),
                    expected_harness_sha256=context.payload["browser_harness_sha256"],
                    expected_seccomp_sha256=context.payload["browser_seccomp_sha256"],
                )
            )
            executor = GovernedWebPhaseExecutor(
                contract=context.contract,
                prepared_workspace=prepared,
                snapshot=context.snapshot,
                lock_report=context.locks,
                runner_identity=context.execution_identity,
                execution_policy=self.policy,
                resources=self.resources,
                workspaces_root=root / "mutable",
                evidence_store=store,
                docker_context=self.config.docker_context,
                controlled_network=self.config.controlled_network,
                browser_executor=browser,
            )
            service = LocalGovernedWebExecutionService(
                registry=context.registry,
                attempts=attempts,
                phase_executor=executor,
                phase_lifecycle=executor,
                phase_attempt_binding=executor,
                clock=_Clock(),
                ids=_AttemptId(operation.id),
            )
            request = replace(
                context.request,
                authorization=authorization,
                rerun_phases=None
                if context.request.rerun_phases is None
                else tuple(WebExecutionPhase),
            )
            return await service.execute(request)


def execution_command_snapshot(command):
    """Exact public input projection, excluding the pointer to its approval record."""
    return {
        "source_revision_id": str(command.source_revision_id),
        "profile_id": command.profile_id,
        "profile_version": command.profile_version,
        "policy_content_hash": command.policy_content_hash,
        "execution_runner_image_digest": command.execution_runner_image_digest,
        "browser_runner_image_digest": command.browser_runner_image_digest,
        "purpose": command.purpose.value,
        "trigger": command.trigger.value,
        "rerun_phases": None
        if command.rerun_phases is None
        else [item.value for item in command.rerun_phases],
        "declared_routes": [
            {"route_id": item.route_id, "path": item.path} for item in command.declared_routes
        ],
        "browser_interactions": [
            item.to_snapshot() for item in getattr(command, "browser_interactions", ())
        ],
    }
