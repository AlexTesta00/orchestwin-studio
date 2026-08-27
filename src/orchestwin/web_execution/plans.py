"""Structured phase plans for the five Sprint 08 Web target families."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    StructuredCommand,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.detection import WebDetectionSnapshot
from orchestwin.web_execution.lockfiles import WebDependencyLockReport
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebTargetSelection,
    web_scope_for,
)

_COMMAND_TIMEOUT_SECONDS: Final = 600


class WebExecutionPhase(StrEnum):
    """Explicit Web execution phases preserved in reports and evidence."""

    VALIDATE = "VALIDATE"
    SETUP = "SETUP"
    STATIC_CHECK = "STATIC_CHECK"
    BUILD = "BUILD"
    TEST = "TEST"
    RUN = "RUN"
    HEALTH_CHECK = "HEALTH_CHECK"
    BROWSER_EVIDENCE = "BROWSER_EVIDENCE"
    COLLECT_ARTIFACTS = "COLLECT_ARTIFACTS"


class WebPhaseExecutionKind(StrEnum):
    """How one phase is carried out without inventing an executed command."""

    COMMAND_PLANS = "COMMAND_PLANS"
    ADAPTER_ACTION = "ADAPTER_ACTION"
    NO_OP = "NO_OP"


@dataclass(frozen=True, slots=True)
class WebPhasePlan:
    """One explicit phase represented by commands, an adapter action, or a no-op."""

    phase: WebExecutionPhase
    execution_kind: WebPhaseExecutionKind
    command_plans: tuple[CommandPlan, ...]
    adapter_action_id: str | None
    no_op_reason: str | None

    def __post_init__(self) -> None:
        if self.execution_kind is WebPhaseExecutionKind.COMMAND_PLANS:
            if not self.command_plans or self.adapter_action_id is not None or self.no_op_reason:
                raise ValueError("command-backed Web phase requires only command plans")
        elif self.execution_kind is WebPhaseExecutionKind.ADAPTER_ACTION:
            if self.command_plans or not self.adapter_action_id or self.no_op_reason:
                raise ValueError("adapter-backed Web phase requires only an action ID")
        elif self.command_plans or self.adapter_action_id is not None or not self.no_op_reason:
            raise ValueError("no-op Web phase requires only an inspectable reason")
        plan_ids = tuple(plan.plan_id for plan in self.command_plans)
        if len(plan_ids) != len(set(plan_ids)):
            raise ValueError("Web phase command-plan IDs must be unique")
        if self.no_op_reason is not None and self.no_op_reason != " ".join(
            self.no_op_reason.split()
        ):
            raise ValueError("Web phase no-op reason must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "execution_kind": self.execution_kind.value,
            "command_plans": [plan.to_snapshot() for plan in self.command_plans],
            "adapter_action_id": self.adapter_action_id,
            "no_op_reason": self.no_op_reason,
        }


@dataclass(frozen=True, slots=True)
class WebExecutionPlanBundle:
    """Complete phase plan bound to one inventory and profile version."""

    inventory_content_hash: str
    selection: WebTargetSelection
    profile_id: str
    profile_version: str
    phases: tuple[WebPhasePlan, ...]

    def __post_init__(self) -> None:
        scope = web_scope_for(self.selection.target)
        self.selection.validate_against(scope)
        if self.profile_id != scope.profile_id or self.profile_version != scope.profile_version:
            raise ValueError("Web execution plan profile does not match the selected scope")
        expected = tuple(WebExecutionPhase)
        actual = tuple(phase.phase for phase in self.phases)
        if actual != expected:
            raise ValueError("Web execution plan must contain every phase in canonical order")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def phase(self, phase: WebExecutionPhase) -> WebPhasePlan:
        return next(item for item in self.phases if item.phase is phase)

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "inventory_content_hash": self.inventory_content_hash,
            "selection": self.selection.to_snapshot(),
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "phases": [phase.to_snapshot() for phase in self.phases],
        }


def create_structured_web_phase_plans(
    snapshot: WebDetectionSnapshot,
    *,
    selection: WebTargetSelection,
    lock_report: WebDependencyLockReport,
) -> WebExecutionPlanBundle:
    """Create a shell-free phase bundle only after deterministic lock validation."""
    if lock_report.inventory_content_hash != snapshot.inventory_content_hash:
        raise ValueError("Web lock report targets another source inventory")
    if not lock_report.is_valid:
        raise ValueError("Web phase planning requires a valid dependency lock report")
    scope = web_scope_for(selection.target)
    selection.validate_against(scope)

    phases = (
        _adapter_phase(WebExecutionPhase.VALIDATE, "web.project.validate.v1"),
        _setup_phase(snapshot, selection=selection),
        _static_check_phase(snapshot, selection=selection),
        _build_phase(snapshot, selection=selection),
        _test_phase(selection=selection),
        _run_phase(selection=selection),
        _adapter_phase(WebExecutionPhase.HEALTH_CHECK, "web.health.check.v1"),
        _browser_phase(selection=selection),
        _adapter_phase(WebExecutionPhase.COLLECT_ARTIFACTS, "web.artifacts.collect.v1"),
    )
    return WebExecutionPlanBundle(
        inventory_content_hash=snapshot.inventory_content_hash,
        selection=selection,
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        phases=phases,
    )


def _setup_phase(
    snapshot: WebDetectionSnapshot,
    *,
    selection: WebTargetSelection,
) -> WebPhasePlan:
    del snapshot
    if selection.target is ExecutionTarget.WEB_STATIC:
        return _no_op_phase(
            WebExecutionPhase.SETUP,
            "Static projects have no validated dependency installation phase.",
        )
    roots = _dependency_roots(selection.target)
    plans = tuple(
        _single_command_plan(
            phase=WebExecutionPhase.SETUP,
            selection=selection,
            root=root,
            command=(
                _composer_setup_command(root)
                if selection.target is ExecutionTarget.WEB_PHP
                else _npm_setup_command(root)
            ),
        )
        for root in roots
    )
    return _command_phase(WebExecutionPhase.SETUP, plans)


def _static_check_phase(
    snapshot: WebDetectionSnapshot,
    *,
    selection: WebTargetSelection,
) -> WebPhasePlan:
    if selection.target is ExecutionTarget.WEB_STATIC:
        return _adapter_phase(WebExecutionPhase.STATIC_CHECK, "web.static.validate.v1")
    if selection.target is ExecutionTarget.WEB_PHP:
        return _command_phase(
            WebExecutionPhase.STATIC_CHECK,
            (
                _single_command_plan(
                    phase=WebExecutionPhase.STATIC_CHECK,
                    selection=selection,
                    root=".",
                    command=_command(
                        command_id="php.lint",
                        executable="php",
                        arguments=("/opt/orchestwin/bin/php-lint.php", "."),
                        working_directory=".",
                        parser="php.lint.v1",
                    ),
                ),
            ),
        )

    plans: list[CommandPlan] = []
    for root, language in _javascript_roots(selection):
        commands = [
            _command(
                command_id=f"{_root_token(root)}.lint",
                executable="npm",
                arguments=("run", "lint", "--if-present"),
                working_directory=root,
                parser="npm.v1",
            )
        ]
        if language is WebImplementationLanguage.TYPESCRIPT:
            commands.append(
                _command(
                    command_id=f"{_root_token(root)}.typescript",
                    executable="npx",
                    arguments=("--no-install", "tsc", "--noEmit"),
                    working_directory=root,
                    parser="typescript.v1",
                )
            )
        plans.append(
            _command_plan(
                plan_id=f"web.static-check.{_root_token(root)}",
                selection=selection,
                commands=tuple(commands),
            )
        )
    del snapshot
    return _command_phase(WebExecutionPhase.STATIC_CHECK, tuple(plans))


def _build_phase(
    snapshot: WebDetectionSnapshot,
    *,
    selection: WebTargetSelection,
) -> WebPhasePlan:
    del snapshot
    if selection.target in {ExecutionTarget.WEB_STATIC, ExecutionTarget.WEB_PHP}:
        return _no_op_phase(
            WebExecutionPhase.BUILD,
            "The selected validated baseline has no compilation phase.",
        )
    plans: list[CommandPlan] = []
    for root, language in _javascript_roots(selection):
        is_vue_root = selection.target is ExecutionTarget.WEB_VUE or root == "frontend"
        if not is_vue_root and language is WebImplementationLanguage.JAVASCRIPT:
            continue
        plans.append(
            _single_command_plan(
                phase=WebExecutionPhase.BUILD,
                selection=selection,
                root=root,
                command=_command(
                    command_id=f"{_root_token(root)}.build",
                    executable="npm",
                    arguments=("run", "build"),
                    working_directory=root,
                    parser="npm.v1",
                    artifacts=frozenset({"dist/**"}),
                ),
            )
        )
    if not plans:
        return _no_op_phase(
            WebExecutionPhase.BUILD,
            "JavaScript Express projects may execute directly without compilation.",
        )
    return _command_phase(WebExecutionPhase.BUILD, tuple(plans))


def _test_phase(*, selection: WebTargetSelection) -> WebPhasePlan:
    if selection.target is ExecutionTarget.WEB_STATIC:
        return _adapter_phase(WebExecutionPhase.TEST, "web.static.smoke.v1")
    if selection.target is ExecutionTarget.WEB_PHP:
        return _command_phase(
            WebExecutionPhase.TEST,
            (
                _single_command_plan(
                    phase=WebExecutionPhase.TEST,
                    selection=selection,
                    root=".",
                    command=_command(
                        command_id="php.phpunit",
                        executable="php",
                        arguments=("vendor/bin/phpunit",),
                        working_directory=".",
                        parser="phpunit.v1",
                        artifacts=frozenset({"coverage/**", "reports/**"}),
                    ),
                ),
            ),
        )
    plans = tuple(
        _single_command_plan(
            phase=WebExecutionPhase.TEST,
            selection=selection,
            root=root,
            command=_command(
                command_id=f"{_root_token(root)}.test",
                executable="npm",
                arguments=("test", "--", "--run"),
                working_directory=root,
                parser="vitest.v1",
                artifacts=frozenset({"coverage/**", "reports/**"}),
            ),
        )
        for root, _language in _javascript_roots(selection)
    )
    return _command_phase(WebExecutionPhase.TEST, plans)


def _run_phase(*, selection: WebTargetSelection) -> WebPhasePlan:
    if selection.target is ExecutionTarget.WEB_STATIC:
        commands = (
            (
                ".",
                _command(
                    command_id="static.serve",
                    executable="node",
                    arguments=(
                        "/opt/orchestwin/bin/static-server.mjs",
                        "--root",
                        ".",
                        "--port",
                        "4173",
                    ),
                    working_directory=".",
                    parser="process.v1",
                ),
            ),
        )
    elif selection.target is ExecutionTarget.WEB_VUE:
        commands = (
            (
                ".",
                _command(
                    command_id="root.preview",
                    executable="npm",
                    arguments=("run", "preview", "--", "--host", "0.0.0.0", "--port", "4173"),
                    working_directory=".",
                    parser="process.v1",
                ),
            ),
        )
    elif selection.target is ExecutionTarget.WEB_NODE_EXPRESS:
        commands = (
            (
                ".",
                _command(
                    command_id="root.start",
                    executable="npm",
                    arguments=("start",),
                    working_directory=".",
                    parser="process.v1",
                ),
            ),
        )
    elif selection.target is ExecutionTarget.WEB_PHP:
        commands = (
            (
                ".",
                _command(
                    command_id="php.serve",
                    executable="php",
                    arguments=("-S", "0.0.0.0:8080", "-t", "public"),
                    working_directory=".",
                    parser="process.v1",
                ),
            ),
        )
    else:
        commands = (
            (
                "backend",
                _command(
                    command_id="backend.start",
                    executable="npm",
                    arguments=("start",),
                    working_directory="backend",
                    parser="process.v1",
                ),
            ),
            (
                "frontend",
                _command(
                    command_id="frontend.preview",
                    executable="npm",
                    arguments=("run", "preview", "--", "--host", "0.0.0.0", "--port", "4173"),
                    working_directory="frontend",
                    parser="process.v1",
                ),
            ),
        )
    plans = tuple(
        _single_command_plan(
            phase=WebExecutionPhase.RUN,
            selection=selection,
            root=root,
            command=command,
        )
        for root, command in commands
    )
    return _command_phase(WebExecutionPhase.RUN, plans)


def _browser_phase(*, selection: WebTargetSelection) -> WebPhasePlan:
    scope = web_scope_for(selection.target)
    if not scope.requires_browser_evidence:
        return _no_op_phase(
            WebExecutionPhase.BROWSER_EVIDENCE,
            "API-only Express projects do not require browser evidence.",
        )
    return _adapter_phase(WebExecutionPhase.BROWSER_EVIDENCE, "web.browser.evidence.v1")


def _dependency_roots(target: ExecutionTarget) -> tuple[str, ...]:
    if target is ExecutionTarget.WEB_VUE_NODE:
        return ("backend", "frontend")
    return (".",)


def _javascript_roots(
    selection: WebTargetSelection,
) -> tuple[tuple[str, WebImplementationLanguage], ...]:
    configuration = selection.language_configuration
    if selection.target is ExecutionTarget.WEB_VUE_NODE:
        assert configuration.frontend is not None
        assert configuration.backend is not None
        return (
            ("backend", configuration.backend),
            ("frontend", configuration.frontend),
        )
    language = configuration.frontend or configuration.backend
    if language not in {
        WebImplementationLanguage.JAVASCRIPT,
        WebImplementationLanguage.TYPESCRIPT,
    }:
        raise ValueError("selected Web target does not define a JavaScript-family language")
    return ((".", language),)


def _npm_setup_command(root: str) -> StructuredCommand:
    return _command(
        command_id=f"{_root_token(root)}.npm-ci",
        executable="npm",
        arguments=("ci", "--ignore-scripts", "--no-audit", "--no-fund"),
        working_directory=root,
        parser="npm.v1",
        network=CommandNetworkMode.CONTROLLED,
    )


def _composer_setup_command(root: str) -> StructuredCommand:
    return _command(
        command_id="php.composer-install",
        executable="composer",
        arguments=(
            "install",
            "--no-interaction",
            "--no-ansi",
            "--no-progress",
            "--no-scripts",
            "--no-plugins",
            "--prefer-dist",
        ),
        working_directory=root,
        parser="composer.v1",
        network=CommandNetworkMode.CONTROLLED,
    )


def _command(
    *,
    command_id: str,
    executable: str,
    arguments: tuple[str, ...],
    working_directory: str,
    parser: str,
    artifacts: frozenset[str] = frozenset(),
    network: CommandNetworkMode = CommandNetworkMode.DISABLED,
) -> StructuredCommand:
    return StructuredCommand(
        command_id=command_id,
        executable=executable,
        arguments=arguments,
        working_directory=working_directory,
        allowed_environment_keys=frozenset({"CI", "NODE_ENV"}),
        secret_references=frozenset(),
        timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        network_mode=network,
        expected_exit_codes=frozenset({0}),
        output_parser_id=parser,
        artifact_patterns=artifacts,
    )


def _single_command_plan(
    *,
    phase: WebExecutionPhase,
    selection: WebTargetSelection,
    root: str,
    command: StructuredCommand,
) -> CommandPlan:
    return _command_plan(
        plan_id=f"web.{phase.value.casefold().replace('_', '-')}.{_root_token(root)}",
        selection=selection,
        commands=(command,),
    )


def _command_plan(
    *,
    plan_id: str,
    selection: WebTargetSelection,
    commands: tuple[StructuredCommand, ...],
) -> CommandPlan:
    scope = web_scope_for(selection.target)
    return CommandPlan(
        plan_id=plan_id,
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        commands=commands,
    )


def _command_phase(
    phase: WebExecutionPhase,
    plans: tuple[CommandPlan, ...],
) -> WebPhasePlan:
    return WebPhasePlan(
        phase=phase,
        execution_kind=WebPhaseExecutionKind.COMMAND_PLANS,
        command_plans=plans,
        adapter_action_id=None,
        no_op_reason=None,
    )


def _adapter_phase(phase: WebExecutionPhase, action_id: str) -> WebPhasePlan:
    return WebPhasePlan(
        phase=phase,
        execution_kind=WebPhaseExecutionKind.ADAPTER_ACTION,
        command_plans=(),
        adapter_action_id=action_id,
        no_op_reason=None,
    )


def _no_op_phase(phase: WebExecutionPhase, reason: str) -> WebPhasePlan:
    return WebPhasePlan(
        phase=phase,
        execution_kind=WebPhaseExecutionKind.NO_OP,
        command_plans=(),
        adapter_action_id=None,
        no_op_reason=reason,
    )


def _root_token(root: str) -> str:
    return "root" if root == "." else root


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
