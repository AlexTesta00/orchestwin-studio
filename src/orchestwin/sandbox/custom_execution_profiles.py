"""Strict CUSTOM_DECLARATIVE profile parsing and deterministic safety validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    SecretReference,
    StructuredCommand,
)
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    SandboxExecutionPolicy,
    SandboxPolicyReport,
    SandboxResourceLimits,
    validate_sandbox_plan,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileDetection,
    ExecutionProfileMetadata,
    ExecutionProfileNetworkPolicy,
    ExecutionProfilePhase,
    ExecutionProfileProjectIssue,
    ExecutionProfileProjectIssueCode,
    ExecutionProfileProjectValidation,
    ExecutionProfileProjectValidationStatus,
    ExecutionTarget,
    create_execution_profile_metadata,
)
from orchestwin.sandbox.source_inventory import SourceTreeInventory

_CUSTOM_PROFILE_SCHEMA_VERSION: Final = 1
_TOP_LEVEL_KEYS: Final = frozenset(
    {
        "schema_version",
        "profile_id",
        "name",
        "version",
        "capability_status",
        "indicators",
        "runner",
        "network",
        "resources",
        "commands",
        "maintainer",
        "license_notes",
    }
)
_INDICATOR_KEYS: Final = frozenset({"required_files", "required_suffixes", "conflicting_files"})
_RUNNER_KEYS: Final = frozenset({"kind", "base_image"})
_NETWORK_KEYS: Final = frozenset({"setup", "static_checks", "build", "test", "run"})
_RESOURCE_KEYS: Final = frozenset({"cpu_count", "memory_mib", "pids_limit", "writable_tmpfs_mib"})
_COMMAND_KEYS: Final = frozenset(
    {
        "command_id",
        "executable",
        "arguments",
        "working_directory",
        "allowed_environment_keys",
        "secret_references",
        "timeout_seconds",
        "network_mode",
        "expected_exit_codes",
        "output_parser_id",
        "artifact_patterns",
    }
)
_SECRET_KEYS: Final = frozenset({"reference_id", "environment_key"})
_REQUIRED_PHASES: Final = frozenset({ExecutionProfilePhase.BUILD, ExecutionProfilePhase.TEST})


class CustomExecutionProfileValidationStatus(StrEnum):
    """Outcome of parsing and policy-checking one custom declaration."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CustomExecutionProfileIssueCode(StrEnum):
    """Stable reasons why a custom declaration cannot enter the registry."""

    SCHEMA_INVALID = "SCHEMA_INVALID"
    UNSUPPORTED_SCHEMA_VERSION = "UNSUPPORTED_SCHEMA_VERSION"
    CAPABILITY_STATUS_INVALID = "CAPABILITY_STATUS_INVALID"
    PROFILE_ID_INVALID = "PROFILE_ID_INVALID"
    INDICATORS_INVALID = "INDICATORS_INVALID"
    RUNNER_INVALID = "RUNNER_INVALID"
    NETWORK_INVALID = "NETWORK_INVALID"
    RESOURCES_INVALID = "RESOURCES_INVALID"
    COMMAND_INVALID = "COMMAND_INVALID"
    REQUIRED_PHASE_MISSING = "REQUIRED_PHASE_MISSING"
    PHASE_NETWORK_MISMATCH = "PHASE_NETWORK_MISMATCH"
    COMMAND_POLICY_REJECTED = "COMMAND_POLICY_REJECTED"


@dataclass(frozen=True, slots=True)
class CustomExecutionProfileIssue:
    """One inspectable custom-profile declaration or policy issue."""

    code: CustomExecutionProfileIssueCode
    message: str
    path: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("custom execution profile issue message must be normalized")
        if not self.path or self.path != self.path.strip():
            raise ValueError("custom execution profile issue path must be normalized")

    def to_snapshot(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class CustomDeclarativeExecutionProfile:
    """Owner-approval-required profile produced only from a strict declaration."""

    metadata: ExecutionProfileMetadata
    image: ContainerImageReference
    required_files: tuple[str, ...]
    required_suffixes: tuple[str, ...]
    conflicting_files: tuple[str, ...]
    plans: tuple[tuple[ExecutionProfilePhase, CommandPlan], ...]
    policy_reports: tuple[tuple[ExecutionProfilePhase, SandboxPolicyReport], ...]
    declaration_content_hash: str

    def __post_init__(self) -> None:
        if self.metadata.capability_status is not (ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D):
            raise ValueError("custom declarative profiles must remain experimental")
        if not self.metadata.requires_owner_approval:
            raise ValueError("custom declarative profiles require owner approval")
        if self.metadata.supported_targets != (ExecutionTarget.CUSTOM_DECLARATIVE,):
            raise ValueError("custom declarative profile target must be explicit")
        if self.metadata.base_images != (self.image,):
            raise ValueError("custom profile image must match metadata")
        _validate_digest(self.declaration_content_hash)

        plan_phases = tuple(phase for phase, _ in self.plans)
        report_phases = tuple(phase for phase, _ in self.policy_reports)
        if plan_phases != tuple(sorted(plan_phases, key=_phase_order)):
            raise ValueError("custom profile plans must use canonical phase order")
        if plan_phases != report_phases:
            raise ValueError("custom profile policy reports must match plan phases")
        if len(plan_phases) != len(set(plan_phases)):
            raise ValueError("custom profile plan phases must be unique")
        if not set(plan_phases) >= _REQUIRED_PHASES:
            raise ValueError("custom profile requires build and test plans")

        for phase, plan in self.plans:
            if (
                plan.profile_id != self.metadata.profile_id
                or plan.profile_version != self.metadata.version
            ):
                raise ValueError("custom command plans must target exact profile metadata")
            report = dict(self.policy_reports)[phase]
            if not report.is_accepted or report.plan_content_hash != plan.content_hash:
                raise ValueError("custom profile requires accepted exact policy reports")

    def detect(self, inventory: SourceTreeInventory) -> ExecutionProfileDetection:
        paths = tuple(entry.normalized_path.casefold() for entry in inventory.included_entries)
        file_names = frozenset(PurePosixPath(path).name for path in paths)

        matched_files = tuple(
            f"required-file:{name}" for name in self.required_files if name in file_names
        )
        matched_suffixes = tuple(
            f"required-suffix:{suffix}"
            for suffix in self.required_suffixes
            if any(path.endswith(suffix) for path in paths)
        )
        conflicts = tuple(
            f"conflicting-file:{name}" for name in self.conflicting_files if name in file_names
        )
        positives = tuple(sorted((*matched_files, *matched_suffixes)))
        conflicts = tuple(sorted(conflicts))
        required_count = len(self.required_files) + len(self.required_suffixes)
        confidence = 0 if not positives else round(100 * len(positives) / required_count)

        return ExecutionProfileDetection(
            profile_reference=self.metadata.reference,
            detected_targets=((ExecutionTarget.CUSTOM_DECLARATIVE,) if positives else ()),
            confidence=confidence,
            positive_indicators=positives,
            conflicting_indicators=conflicts,
            missing_tools=(),
            requires_human_decision=bool(conflicts or confidence < 100),
        )

    def validate_project(
        self,
        inventory: SourceTreeInventory,
    ) -> ExecutionProfileProjectValidation:
        detection = self.detect(inventory)
        positives = frozenset(detection.positive_indicators)
        issues: list[ExecutionProfileProjectIssue] = []

        for name in self.required_files:
            indicator = f"required-file:{name}"
            if indicator not in positives:
                issues.append(
                    ExecutionProfileProjectIssue(
                        code=(ExecutionProfileProjectIssueCode.MISSING_REQUIRED_INDICATOR),
                        message="A required custom profile file indicator is missing.",
                        path=name,
                    )
                )
        for suffix in self.required_suffixes:
            indicator = f"required-suffix:{suffix}"
            if indicator not in positives:
                issues.append(
                    ExecutionProfileProjectIssue(
                        code=(ExecutionProfileProjectIssueCode.MISSING_REQUIRED_INDICATOR),
                        message="A required custom profile suffix indicator is missing.",
                        path=suffix,
                    )
                )
        for conflict in detection.conflicting_indicators:
            issues.append(
                ExecutionProfileProjectIssue(
                    code=ExecutionProfileProjectIssueCode.CONFLICTING_INDICATOR,
                    message="A conflicting custom profile file requires human review.",
                    path=conflict.removeprefix("conflicting-file:"),
                )
            )

        return ExecutionProfileProjectValidation(
            profile_reference=self.metadata.reference,
            inventory_content_hash=inventory.content_hash,
            status=(
                ExecutionProfileProjectValidationStatus.INVALID
                if issues
                else ExecutionProfileProjectValidationStatus.VALID
            ),
            issues=tuple(issues),
        )

    def create_plan(
        self,
        phase: ExecutionProfilePhase,
        inventory: SourceTreeInventory,
    ) -> CommandPlan | None:
        if not self.validate_project(inventory).is_valid:
            return None
        return dict(self.plans).get(phase)


@dataclass(frozen=True, slots=True)
class CustomExecutionProfileValidationReport:
    """Strict validation result with no partially usable profile object."""

    status: CustomExecutionProfileValidationStatus
    declaration_content_hash: str | None
    profile: CustomDeclarativeExecutionProfile | None
    issues: tuple[CustomExecutionProfileIssue, ...]

    def __post_init__(self) -> None:
        if self.declaration_content_hash is not None:
            _validate_digest(self.declaration_content_hash)
        if self.status is CustomExecutionProfileValidationStatus.ACCEPTED:
            if self.profile is None or self.issues or self.declaration_content_hash is None:
                raise ValueError("accepted custom profile report requires only a profile")
            if self.profile.declaration_content_hash != self.declaration_content_hash:
                raise ValueError("custom profile report hash must match the profile")
        elif self.profile is not None or not self.issues:
            raise ValueError("rejected custom profile report requires only issues")

    @property
    def is_accepted(self) -> bool:
        return self.status is CustomExecutionProfileValidationStatus.ACCEPTED

    @property
    def requires_owner_approval(self) -> bool:
        return self.profile is not None and self.profile.metadata.requires_owner_approval

    def to_snapshot(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "declaration_content_hash": self.declaration_content_hash,
            "profile_reference": (
                None if self.profile is None else self.profile.metadata.reference.to_snapshot()
            ),
            "requires_owner_approval": self.requires_owner_approval,
            "issues": [issue.to_snapshot() for issue in self.issues],
        }


def validate_custom_execution_profile(
    declaration: object,
    *,
    execution_policy: SandboxExecutionPolicy = DEFAULT_SANDBOX_EXECUTION_POLICY,
) -> CustomExecutionProfileValidationReport:
    """Parse one strict declaration and validate every plan before registration."""
    try:
        root = _mapping(declaration, path="$")
        parsed = _parse_declaration(root)
    except _DeclarationError as error:
        return _rejected(error.issue)

    policy_reports: list[tuple[ExecutionProfilePhase, SandboxPolicyReport]] = []
    issues: list[CustomExecutionProfileIssue] = []
    for phase, plan in parsed.plans:
        expected_network = parsed.network_policy.mode_for(phase)
        if any(command.network_mode is not expected_network for command in plan.commands):
            issues.append(
                CustomExecutionProfileIssue(
                    code=CustomExecutionProfileIssueCode.PHASE_NETWORK_MISMATCH,
                    message="Command network mode differs from its declared phase policy.",
                    path=f"commands.{phase.value}",
                )
            )
            continue

        report = validate_sandbox_plan(
            plan,
            resources=parsed.resources,
            policy=execution_policy,
        )
        if not report.is_accepted:
            issues.append(
                CustomExecutionProfileIssue(
                    code=CustomExecutionProfileIssueCode.COMMAND_POLICY_REJECTED,
                    message="A custom command plan violates the sandbox execution policy.",
                    path=f"commands.{phase.value}",
                )
            )
        policy_reports.append((phase, report))

    if issues:
        return CustomExecutionProfileValidationReport(
            status=CustomExecutionProfileValidationStatus.REJECTED,
            declaration_content_hash=None,
            profile=None,
            issues=tuple(issues),
        )

    try:
        metadata = create_execution_profile_metadata(
            profile_id=parsed.profile_id,
            name=parsed.name,
            version=parsed.version,
            capability_status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
            supported_targets=(ExecutionTarget.CUSTOM_DECLARATIVE,),
            file_indicators=(
                *(f"required-file:{name}" for name in parsed.required_files),
                *(f"required-suffix:{suffix}" for suffix in parsed.required_suffixes),
                *(f"conflicting-file:{name}" for name in parsed.conflicting_files),
            ),
            required_runners=("container.docker",),
            base_images=(parsed.image,),
            network_policy=parsed.network_policy,
            resource_defaults=parsed.resources,
            maintainer=parsed.maintainer,
            license_notes=parsed.license_notes,
            requires_owner_approval=True,
        )
    except (TypeError, ValueError):
        return _rejected(
            CustomExecutionProfileIssue(
                code=CustomExecutionProfileIssueCode.SCHEMA_INVALID,
                message="Custom profile metadata violates the execution profile contract.",
                path="$",
            )
        )
    normalized = {
        "metadata": metadata.to_snapshot(),
        "image": parsed.image.value,
        "required_files": list(parsed.required_files),
        "required_suffixes": list(parsed.required_suffixes),
        "conflicting_files": list(parsed.conflicting_files),
        "plans": [
            {"phase": phase.value, "plan": plan.to_snapshot()} for phase, plan in parsed.plans
        ],
        "policy_hash": execution_policy.content_hash,
    }
    declaration_hash = hashlib.sha256(_canonical_json_bytes(normalized)).hexdigest()
    profile = CustomDeclarativeExecutionProfile(
        metadata=metadata,
        image=parsed.image,
        required_files=parsed.required_files,
        required_suffixes=parsed.required_suffixes,
        conflicting_files=parsed.conflicting_files,
        plans=parsed.plans,
        policy_reports=tuple(policy_reports),
        declaration_content_hash=declaration_hash,
    )
    return CustomExecutionProfileValidationReport(
        status=CustomExecutionProfileValidationStatus.ACCEPTED,
        declaration_content_hash=declaration_hash,
        profile=profile,
        issues=(),
    )


@dataclass(frozen=True, slots=True)
class _ParsedDeclaration:
    profile_id: str
    name: str
    version: str
    required_files: tuple[str, ...]
    required_suffixes: tuple[str, ...]
    conflicting_files: tuple[str, ...]
    image: ContainerImageReference
    network_policy: ExecutionProfileNetworkPolicy
    resources: SandboxResourceLimits
    plans: tuple[tuple[ExecutionProfilePhase, CommandPlan], ...]
    maintainer: str
    license_notes: str


class _DeclarationError(ValueError):
    def __init__(self, issue: CustomExecutionProfileIssue) -> None:
        super().__init__(issue.message)
        self.issue = issue


def _parse_declaration(declaration: Mapping[str, object]) -> _ParsedDeclaration:
    _exact_keys(
        declaration,
        _TOP_LEVEL_KEYS,
        path="$",
        code=CustomExecutionProfileIssueCode.SCHEMA_INVALID,
    )
    schema_version = _integer(declaration["schema_version"], path="schema_version")
    if schema_version != _CUSTOM_PROFILE_SCHEMA_VERSION:
        _fail(
            CustomExecutionProfileIssueCode.UNSUPPORTED_SCHEMA_VERSION,
            "Unsupported custom execution profile schema version.",
            "schema_version",
        )

    capability_status = _text(declaration["capability_status"], path="capability_status")
    if capability_status != ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D.value:
        _fail(
            CustomExecutionProfileIssueCode.CAPABILITY_STATUS_INVALID,
            "Custom declarative profiles must declare EXPERIMENTAL_LEVEL_D.",
            "capability_status",
        )

    profile_id = _text(declaration["profile_id"], path="profile_id")
    if not profile_id.startswith("custom.") or profile_id == "custom.":
        _fail(
            CustomExecutionProfileIssueCode.PROFILE_ID_INVALID,
            "Custom profile IDs must use the reserved custom namespace.",
            "profile_id",
        )
    name = _text(declaration["name"], path="name")
    version = _text(declaration["version"], path="version")
    maintainer = _text(declaration["maintainer"], path="maintainer")
    license_notes = _text(declaration["license_notes"], path="license_notes")

    indicators = _mapping(declaration["indicators"], path="indicators")
    _exact_keys(
        indicators,
        _INDICATOR_KEYS,
        path="indicators",
        code=CustomExecutionProfileIssueCode.INDICATORS_INVALID,
    )
    required_files = _portable_names(
        indicators["required_files"],
        path="indicators.required_files",
    )
    required_suffixes = _suffixes(
        indicators["required_suffixes"],
        path="indicators.required_suffixes",
    )
    conflicting_files = _portable_names(
        indicators["conflicting_files"],
        path="indicators.conflicting_files",
        allow_empty=True,
    )
    if not required_files and not required_suffixes:
        _fail(
            CustomExecutionProfileIssueCode.INDICATORS_INVALID,
            "Custom profiles require at least one source indicator.",
            "indicators",
        )
    if set(required_files) & set(conflicting_files):
        _fail(
            CustomExecutionProfileIssueCode.INDICATORS_INVALID,
            "A file cannot be both required and conflicting.",
            "indicators",
        )

    runner = _mapping(declaration["runner"], path="runner")
    _exact_keys(
        runner,
        _RUNNER_KEYS,
        path="runner",
        code=CustomExecutionProfileIssueCode.RUNNER_INVALID,
    )
    if _text(runner["kind"], path="runner.kind") != "CONTAINER":
        _fail(
            CustomExecutionProfileIssueCode.RUNNER_INVALID,
            "Custom profiles currently support only the constrained container runner.",
            "runner.kind",
        )
    try:
        image = ContainerImageReference(_text(runner["base_image"], path="runner.base_image"))
    except ValueError:
        _fail(
            CustomExecutionProfileIssueCode.RUNNER_INVALID,
            "Custom profile base image must be pinned by SHA-256 digest.",
            "runner.base_image",
        )

    network = _mapping(declaration["network"], path="network")
    _exact_keys(
        network,
        _NETWORK_KEYS,
        path="network",
        code=CustomExecutionProfileIssueCode.NETWORK_INVALID,
    )
    network_policy = ExecutionProfileNetworkPolicy(
        setup=_network_mode(network["setup"], path="network.setup"),
        static_checks=_network_mode(
            network["static_checks"],
            path="network.static_checks",
        ),
        build=_network_mode(network["build"], path="network.build"),
        test=_network_mode(network["test"], path="network.test"),
        run=_network_mode(network["run"], path="network.run"),
    )

    resource_values = _mapping(declaration["resources"], path="resources")
    _exact_keys(
        resource_values,
        _RESOURCE_KEYS,
        path="resources",
        code=CustomExecutionProfileIssueCode.RESOURCES_INVALID,
    )
    try:
        resources = SandboxResourceLimits(
            cpu_count=_number(resource_values["cpu_count"], path="resources.cpu_count"),
            memory_mib=_integer(resource_values["memory_mib"], path="resources.memory_mib"),
            pids_limit=_integer(resource_values["pids_limit"], path="resources.pids_limit"),
            writable_tmpfs_mib=_integer(
                resource_values["writable_tmpfs_mib"],
                path="resources.writable_tmpfs_mib",
            ),
        )
    except ValueError:
        _fail(
            CustomExecutionProfileIssueCode.RESOURCES_INVALID,
            "Custom profile resources must be positive and finite.",
            "resources",
        )

    commands = _mapping(declaration["commands"], path="commands")
    allowed_phase_keys = frozenset(phase.value for phase in ExecutionProfilePhase)
    if not set(commands) <= allowed_phase_keys:
        _fail(
            CustomExecutionProfileIssueCode.SCHEMA_INVALID,
            "Custom profile commands contain an unsupported phase.",
            "commands",
        )

    plans: list[tuple[ExecutionProfilePhase, CommandPlan]] = []
    for phase in ExecutionProfilePhase:
        raw_commands = commands.get(phase.value, [])
        command_values = _sequence(raw_commands, path=f"commands.{phase.value}")
        if not command_values:
            if phase in _REQUIRED_PHASES:
                _fail(
                    CustomExecutionProfileIssueCode.REQUIRED_PHASE_MISSING,
                    "Custom profiles require non-empty build and test phases.",
                    f"commands.{phase.value}",
                )
            continue
        structured = tuple(
            _parse_command(value, path=f"commands.{phase.value}[{index}]")
            for index, value in enumerate(command_values)
        )
        try:
            plan = CommandPlan(
                plan_id=f"{profile_id}.{phase.value.lower()}",
                profile_id=profile_id,
                profile_version=version,
                commands=structured,
            )
        except (TypeError, ValueError):
            _fail(
                CustomExecutionProfileIssueCode.COMMAND_INVALID,
                "Custom command plan violates the structured command contract.",
                f"commands.{phase.value}",
            )
        plans.append((phase, plan))

    return _ParsedDeclaration(
        profile_id=profile_id,
        name=name,
        version=version,
        required_files=required_files,
        required_suffixes=required_suffixes,
        conflicting_files=conflicting_files,
        image=image,
        network_policy=network_policy,
        resources=resources,
        plans=tuple(plans),
        maintainer=maintainer,
        license_notes=license_notes,
    )


def _parse_command(value: object, *, path: str) -> StructuredCommand:
    mapping = _mapping(value, path=path)
    _exact_keys(
        mapping,
        _COMMAND_KEYS,
        path=path,
        code=CustomExecutionProfileIssueCode.COMMAND_INVALID,
    )
    secret_values = _sequence(mapping["secret_references"], path=f"{path}.secret_references")
    secrets: list[SecretReference] = []
    for index, secret_value in enumerate(secret_values):
        secret_path = f"{path}.secret_references[{index}]"
        secret = _mapping(secret_value, path=secret_path)
        _exact_keys(
            secret,
            _SECRET_KEYS,
            path=secret_path,
            code=CustomExecutionProfileIssueCode.COMMAND_INVALID,
        )
        try:
            secrets.append(
                SecretReference(
                    reference_id=_text(secret["reference_id"], path=f"{secret_path}.reference_id"),
                    environment_key=_text(
                        secret["environment_key"],
                        path=f"{secret_path}.environment_key",
                    ),
                )
            )
        except (TypeError, ValueError):
            _fail(
                CustomExecutionProfileIssueCode.COMMAND_INVALID,
                "Custom secret reference is invalid.",
                secret_path,
            )

    try:
        return StructuredCommand(
            command_id=_text(mapping["command_id"], path=f"{path}.command_id"),
            executable=_text(mapping["executable"], path=f"{path}.executable"),
            arguments=tuple(
                _text(item, path=f"{path}.arguments")
                for item in _sequence(mapping["arguments"], path=f"{path}.arguments")
            ),
            working_directory=_text(
                mapping["working_directory"],
                path=f"{path}.working_directory",
            ),
            allowed_environment_keys=frozenset(
                _text(item, path=f"{path}.allowed_environment_keys")
                for item in _sequence(
                    mapping["allowed_environment_keys"],
                    path=f"{path}.allowed_environment_keys",
                )
            ),
            secret_references=frozenset(secrets),
            timeout_seconds=_integer(
                mapping["timeout_seconds"],
                path=f"{path}.timeout_seconds",
            ),
            network_mode=_network_mode(
                mapping["network_mode"],
                path=f"{path}.network_mode",
            ),
            expected_exit_codes=frozenset(
                _integer(item, path=f"{path}.expected_exit_codes")
                for item in _sequence(
                    mapping["expected_exit_codes"],
                    path=f"{path}.expected_exit_codes",
                )
            ),
            output_parser_id=(
                None
                if mapping["output_parser_id"] is None
                else _text(mapping["output_parser_id"], path=f"{path}.output_parser_id")
            ),
            artifact_patterns=frozenset(
                _text(item, path=f"{path}.artifact_patterns")
                for item in _sequence(
                    mapping["artifact_patterns"],
                    path=f"{path}.artifact_patterns",
                )
            ),
        )
    except (TypeError, ValueError):
        _fail(
            CustomExecutionProfileIssueCode.COMMAND_INVALID,
            "Custom command violates the structured command contract.",
            path,
        )


def _exact_keys(
    mapping: Mapping[str, object],
    expected: frozenset[str],
    *,
    path: str,
    code: CustomExecutionProfileIssueCode,
) -> None:
    if set(mapping) != expected:
        _fail(code, "Declaration object has missing or additional fields.", path)


def _mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _fail(
            CustomExecutionProfileIssueCode.SCHEMA_INVALID,
            "Declaration field must be an object with string keys.",
            path,
        )
    return value


def _sequence(value: object, *, path: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail(
            CustomExecutionProfileIssueCode.SCHEMA_INVALID,
            "Declaration field must be an array.",
            path,
        )
    return value


def _text(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(
            CustomExecutionProfileIssueCode.SCHEMA_INVALID,
            "Declaration field must be a normalized non-empty string.",
            path,
        )
    return value


def _integer(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(
            CustomExecutionProfileIssueCode.SCHEMA_INVALID,
            "Declaration field must be an integer.",
            path,
        )
    return value


def _number(value: object, *, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(
            CustomExecutionProfileIssueCode.SCHEMA_INVALID,
            "Declaration field must be a number.",
            path,
        )
    return value


def _network_mode(value: object, *, path: str) -> CommandNetworkMode:
    raw = _text(value, path=path)
    try:
        return CommandNetworkMode(raw)
    except ValueError:
        _fail(
            CustomExecutionProfileIssueCode.NETWORK_INVALID,
            "Declaration network mode is not supported.",
            path,
        )


def _portable_names(
    value: object,
    *,
    path: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    names = tuple(
        sorted({_text(item, path=path).casefold() for item in _sequence(value, path=path)})
    )
    if not names and not allow_empty:
        return ()
    if any(
        "/" in name or "\\" in name or name in {".", ".."} or PurePosixPath(name).name != name
        for name in names
    ):
        _fail(
            CustomExecutionProfileIssueCode.INDICATORS_INVALID,
            "File indicators must be portable file names.",
            path,
        )
    return names


def _suffixes(value: object, *, path: str) -> tuple[str, ...]:
    suffixes = tuple(
        sorted({_text(item, path=path).casefold() for item in _sequence(value, path=path)})
    )
    if any(not suffix.startswith(".") or "/" in suffix or "\\" in suffix for suffix in suffixes):
        _fail(
            CustomExecutionProfileIssueCode.INDICATORS_INVALID,
            "Suffix indicators must be portable lowercase extensions.",
            path,
        )
    return suffixes


def _phase_order(phase: ExecutionProfilePhase) -> int:
    return tuple(ExecutionProfilePhase).index(phase)


def _fail(code: CustomExecutionProfileIssueCode, message: str, path: str) -> None:
    raise _DeclarationError(CustomExecutionProfileIssue(code=code, message=message, path=path))


def _rejected(issue: CustomExecutionProfileIssue) -> CustomExecutionProfileValidationReport:
    return CustomExecutionProfileValidationReport(
        status=CustomExecutionProfileValidationStatus.REJECTED,
        declaration_content_hash=None,
        profile=None,
        issues=(issue,),
    )


def _validate_digest(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("custom execution profile hash must be lowercase SHA-256")


def _canonical_json_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
