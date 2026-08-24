"""Deterministic command, network, and resource policies for sandbox plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    StructuredCommand,
)

_ENVIRONMENT_KEY_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WINDOWS_DRIVE_PATTERN: Final = re.compile(r"^[A-Za-z]:")
_SHELL_COMMAND_FLAGS: Final = frozenset({"-c", "--command"})
_CMD_COMMAND_FLAGS: Final = frozenset({"/c", "/k"})
_POWERSHELL_COMMAND_FLAGS: Final = frozenset({"-c", "-command", "/c", "/command"})
_PYTHON_INLINE_FLAGS: Final = frozenset({"-c"})
_NODE_INLINE_FLAGS: Final = frozenset({"-e", "--eval", "-p", "--print"})
_PHP_INLINE_FLAGS: Final = frozenset({"-r"})


class SandboxPolicyValidationStatus(StrEnum):
    """Outcome of deterministic execution-policy evaluation."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SandboxPolicyIssueCode(StrEnum):
    """Stable reasons why a command plan cannot enter a runtime adapter."""

    TOO_MANY_COMMANDS = "TOO_MANY_COMMANDS"
    EXECUTABLE_NOT_ALLOWED = "EXECUTABLE_NOT_ALLOWED"
    SHELL_BRIDGE_FORBIDDEN = "SHELL_BRIDGE_FORBIDDEN"
    INLINE_CODE_FORBIDDEN = "INLINE_CODE_FORBIDDEN"
    WORKING_DIRECTORY_FORBIDDEN = "WORKING_DIRECTORY_FORBIDDEN"
    ENVIRONMENT_KEY_NOT_ALLOWED = "ENVIRONMENT_KEY_NOT_ALLOWED"
    SECRET_REFERENCE_NOT_ALLOWED = "SECRET_REFERENCE_NOT_ALLOWED"
    COMMAND_TIMEOUT_EXCEEDED = "COMMAND_TIMEOUT_EXCEEDED"
    PLAN_TIMEOUT_EXCEEDED = "PLAN_TIMEOUT_EXCEEDED"
    NETWORK_MODE_NOT_ALLOWED = "NETWORK_MODE_NOT_ALLOWED"
    TOO_MANY_ARTIFACT_PATTERNS = "TOO_MANY_ARTIFACT_PATTERNS"
    ARTIFACT_PATTERN_FORBIDDEN = "ARTIFACT_PATTERN_FORBIDDEN"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class SandboxResourceLimits:
    """Requested least-privilege limits for one ephemeral container run."""

    cpu_count: float
    memory_mib: int
    pids_limit: int
    writable_tmpfs_mib: int

    def __post_init__(self) -> None:
        """Reject non-positive or non-finite resource requests."""
        if (
            isinstance(self.cpu_count, bool)
            or self.cpu_count <= 0
            or self.cpu_count == float("inf")
            or self.cpu_count != self.cpu_count
        ):
            raise ValueError("sandbox CPU count must be a positive finite number")

        integer_values = (
            self.memory_mib,
            self.pids_limit,
            self.writable_tmpfs_mib,
        )
        if any(isinstance(value, bool) or value < 1 for value in integer_values):
            raise ValueError("sandbox integer resource limits must be positive")

    def to_snapshot(self) -> dict[str, int | float]:
        """Return portable resource metadata without host-specific values."""
        return {
            "cpu_count": self.cpu_count,
            "memory_mib": self.memory_mib,
            "pids_limit": self.pids_limit,
            "writable_tmpfs_mib": self.writable_tmpfs_mib,
        }


@dataclass(frozen=True, slots=True)
class SandboxExecutionPolicy:
    """Allowlist and upper bounds applied before any container invocation."""

    allowed_executables: frozenset[str]
    allowed_environment_keys: frozenset[str]
    allowed_secret_reference_ids: frozenset[str]
    allowed_network_modes: frozenset[CommandNetworkMode]
    prohibited_workspace_components: frozenset[str]
    maximum_commands: int
    maximum_command_timeout_seconds: int
    maximum_plan_timeout_seconds: int
    maximum_artifact_patterns_per_command: int
    maximum_artifact_pattern_length: int
    maximum_cpu_count: float
    maximum_memory_mib: int
    maximum_pids: int
    maximum_writable_tmpfs_mib: int

    def __post_init__(self) -> None:
        """Reject ambiguous policy values that could weaken enforcement."""
        if not self.allowed_executables:
            raise ValueError("sandbox policy must allow at least one executable")
        for executable in self.allowed_executables:
            if (
                not executable
                or executable != executable.strip()
                or any(character in executable for character in ("\x00", "\r", "\n"))
            ):
                raise ValueError("sandbox allowed executables must be normalized")

        for key in self.allowed_environment_keys:
            if not _ENVIRONMENT_KEY_PATTERN.fullmatch(key):
                raise ValueError("sandbox allowed environment keys must be portable")

        for reference_id in self.allowed_secret_reference_ids:
            if not reference_id or reference_id != reference_id.strip():
                raise ValueError("sandbox allowed secret references must be normalized")

        if not self.allowed_network_modes or any(
            not isinstance(mode, CommandNetworkMode) for mode in self.allowed_network_modes
        ):
            raise ValueError("sandbox policy must declare valid allowed network modes")

        if not self.prohibited_workspace_components or any(
            not component
            or component != component.casefold()
            or component != component.strip()
            or "/" in component
            or "\\" in component
            for component in self.prohibited_workspace_components
        ):
            raise ValueError("sandbox prohibited workspace components must be lowercase tokens")

        integer_limits = (
            self.maximum_commands,
            self.maximum_command_timeout_seconds,
            self.maximum_plan_timeout_seconds,
            self.maximum_artifact_patterns_per_command,
            self.maximum_artifact_pattern_length,
            self.maximum_memory_mib,
            self.maximum_pids,
            self.maximum_writable_tmpfs_mib,
        )
        if any(isinstance(value, bool) or value < 1 for value in integer_limits):
            raise ValueError("sandbox policy integer limits must be positive")

        if self.maximum_command_timeout_seconds > self.maximum_plan_timeout_seconds:
            raise ValueError("command timeout maximum must not exceed plan timeout maximum")

        if (
            isinstance(self.maximum_cpu_count, bool)
            or self.maximum_cpu_count <= 0
            or self.maximum_cpu_count == float("inf")
            or self.maximum_cpu_count != self.maximum_cpu_count
        ):
            raise ValueError("sandbox policy CPU maximum must be positive and finite")

    @property
    def content_hash(self) -> str:
        """Return a digest covering every executable, capability, and bound."""
        return hashlib.sha256(_canonical_json_bytes(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic policy metadata suitable for audit and replay."""
        return {
            "allowed_executables": sorted(self.allowed_executables),
            "allowed_environment_keys": sorted(self.allowed_environment_keys),
            "allowed_secret_reference_ids": sorted(self.allowed_secret_reference_ids),
            "allowed_network_modes": sorted(mode.value for mode in self.allowed_network_modes),
            "prohibited_workspace_components": sorted(self.prohibited_workspace_components),
            "maximum_commands": self.maximum_commands,
            "maximum_command_timeout_seconds": self.maximum_command_timeout_seconds,
            "maximum_plan_timeout_seconds": self.maximum_plan_timeout_seconds,
            "maximum_artifact_patterns_per_command": self.maximum_artifact_patterns_per_command,
            "maximum_artifact_pattern_length": self.maximum_artifact_pattern_length,
            "maximum_cpu_count": self.maximum_cpu_count,
            "maximum_memory_mib": self.maximum_memory_mib,
            "maximum_pids": self.maximum_pids,
            "maximum_writable_tmpfs_mib": self.maximum_writable_tmpfs_mib,
        }


@dataclass(frozen=True, slots=True)
class SandboxPolicyIssue:
    """One inspectable policy violation tied to an optional command."""

    code: SandboxPolicyIssueCode
    message: str
    command_id: str | None = None

    def __post_init__(self) -> None:
        """Keep issue details normalized for API and audit output."""
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("sandbox policy issue message must be normalized")
        if self.command_id is not None and not self.command_id:
            raise ValueError("sandbox policy issue command ID must not be empty")

    def to_snapshot(self) -> dict[str, str | None]:
        """Return stable issue metadata."""
        return {
            "code": self.code.value,
            "message": self.message,
            "command_id": self.command_id,
        }


@dataclass(frozen=True, slots=True)
class SandboxPolicyReport:
    """Policy decision bound to an exact command plan and resource request."""

    status: SandboxPolicyValidationStatus
    policy_content_hash: str
    plan_content_hash: str
    resources: SandboxResourceLimits
    issues: tuple[SandboxPolicyIssue, ...]

    def __post_init__(self) -> None:
        """Protect accepted and rejected report shapes."""
        _validate_sha256(
            self.policy_content_hash,
            label="sandbox policy report policy hash",
        )
        _validate_sha256(
            self.plan_content_hash,
            label="sandbox policy report plan hash",
        )

        if self.status is SandboxPolicyValidationStatus.ACCEPTED:
            if self.issues:
                raise ValueError("accepted sandbox policy report must not contain issues")
        elif not self.issues:
            raise ValueError("rejected sandbox policy report requires at least one issue")

    @property
    def is_accepted(self) -> bool:
        """Return whether the exact plan and resources may enter an adapter."""
        return self.status is SandboxPolicyValidationStatus.ACCEPTED

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic policy evidence suitable for persistence."""
        return {
            "status": self.status.value,
            "policy_content_hash": self.policy_content_hash,
            "plan_content_hash": self.plan_content_hash,
            "resources": self.resources.to_snapshot(),
            "issues": [issue.to_snapshot() for issue in self.issues],
        }


DEFAULT_SANDBOX_RESOURCE_LIMITS: Final = SandboxResourceLimits(
    cpu_count=2.0,
    memory_mib=4096,
    pids_limit=256,
    writable_tmpfs_mib=512,
)

DEFAULT_SANDBOX_EXECUTION_POLICY: Final = SandboxExecutionPolicy(
    allowed_executables=frozenset(
        {
            "./gradlew",
            "./mvnw",
            "composer",
            "gradle",
            "java",
            "javac",
            "kotlin",
            "kotlinc",
            "mvn",
            "node",
            "npm",
            "npx",
            "php",
            "pip",
            "pip3",
            "pnpm",
            "pytest",
            "python",
            "python3",
            "ruff",
            "sbt",
            "scala",
            "scalac",
            "uv",
            "yarn",
        }
    ),
    allowed_environment_keys=frozenset(
        {
            "CI",
            "HOME",
            "LANG",
            "LC_ALL",
            "NODE_ENV",
            "PATH",
            "PYTHONUNBUFFERED",
            "TMPDIR",
            "TZ",
        }
    ),
    allowed_secret_reference_ids=frozenset(),
    allowed_network_modes=frozenset({CommandNetworkMode.DISABLED}),
    prohibited_workspace_components=frozenset(
        {
            ".git",
            ".orchestwin",
            ".ssh",
        }
    ),
    maximum_commands=32,
    maximum_command_timeout_seconds=600,
    maximum_plan_timeout_seconds=3600,
    maximum_artifact_patterns_per_command=32,
    maximum_artifact_pattern_length=240,
    maximum_cpu_count=2.0,
    maximum_memory_mib=4096,
    maximum_pids=256,
    maximum_writable_tmpfs_mib=512,
)


def validate_sandbox_plan(
    plan: CommandPlan,
    *,
    resources: SandboxResourceLimits = DEFAULT_SANDBOX_RESOURCE_LIMITS,
    policy: SandboxExecutionPolicy = DEFAULT_SANDBOX_EXECUTION_POLICY,
) -> SandboxPolicyReport:
    """Evaluate one exact structured plan without executing side effects."""
    issues: list[SandboxPolicyIssue] = []

    if len(plan.commands) > policy.maximum_commands:
        issues.append(
            SandboxPolicyIssue(
                code=SandboxPolicyIssueCode.TOO_MANY_COMMANDS,
                message="Command plan exceeds the allowed command count.",
            )
        )

    if plan.total_timeout_seconds > policy.maximum_plan_timeout_seconds:
        issues.append(
            SandboxPolicyIssue(
                code=SandboxPolicyIssueCode.PLAN_TIMEOUT_EXCEEDED,
                message="Command plan exceeds the total timeout policy.",
            )
        )

    issues.extend(_validate_resources(resources, policy=policy))

    for command in plan.commands:
        issues.extend(_validate_command(command, policy=policy))

    return SandboxPolicyReport(
        status=(
            SandboxPolicyValidationStatus.REJECTED
            if issues
            else SandboxPolicyValidationStatus.ACCEPTED
        ),
        policy_content_hash=policy.content_hash,
        plan_content_hash=plan.content_hash,
        resources=resources,
        issues=tuple(issues),
    )


def _validate_resources(
    resources: SandboxResourceLimits,
    *,
    policy: SandboxExecutionPolicy,
) -> tuple[SandboxPolicyIssue, ...]:
    """Compare requested resources against non-negotiable maxima."""
    exceeded = (
        resources.cpu_count > policy.maximum_cpu_count
        or resources.memory_mib > policy.maximum_memory_mib
        or resources.pids_limit > policy.maximum_pids
        or resources.writable_tmpfs_mib > policy.maximum_writable_tmpfs_mib
    )
    if not exceeded:
        return ()

    return (
        SandboxPolicyIssue(
            code=SandboxPolicyIssueCode.RESOURCE_LIMIT_EXCEEDED,
            message="Requested sandbox resources exceed the execution policy.",
        ),
    )


def _validate_command(
    command: StructuredCommand,
    *,
    policy: SandboxExecutionPolicy,
) -> tuple[SandboxPolicyIssue, ...]:
    """Evaluate one command against allowlists and bounded operation rules."""
    issues: list[SandboxPolicyIssue] = []

    if command.executable not in policy.allowed_executables:
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.EXECUTABLE_NOT_ALLOWED,
                "Command executable is not allowed by the execution policy.",
                command,
            )
        )

    if _is_shell_command_bridge(command):
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.SHELL_BRIDGE_FORBIDDEN,
                "Shell command-string bridges are forbidden.",
                command,
            )
        )

    if _is_inline_code_bridge(command):
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.INLINE_CODE_FORBIDDEN,
                "Inline interpreter code is forbidden by the execution policy.",
                command,
            )
        )

    working_parts = tuple(
        part.casefold() for part in PurePosixPath(command.working_directory).parts if part != "."
    )
    if any(part in policy.prohibited_workspace_components for part in working_parts):
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.WORKING_DIRECTORY_FORBIDDEN,
                "Command working directory targets a protected workspace path.",
                command,
            )
        )

    forbidden_environment = command.allowed_environment_keys - policy.allowed_environment_keys
    if forbidden_environment:
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.ENVIRONMENT_KEY_NOT_ALLOWED,
                "Command requests environment keys outside the policy allowlist.",
                command,
            )
        )

    secret_reference_ids = {reference.reference_id for reference in command.secret_references}
    if not secret_reference_ids <= policy.allowed_secret_reference_ids:
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.SECRET_REFERENCE_NOT_ALLOWED,
                "Command requests secret references without policy authorization.",
                command,
            )
        )

    if command.timeout_seconds > policy.maximum_command_timeout_seconds:
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.COMMAND_TIMEOUT_EXCEEDED,
                "Command timeout exceeds the execution policy.",
                command,
            )
        )

    if command.network_mode not in policy.allowed_network_modes:
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.NETWORK_MODE_NOT_ALLOWED,
                "Command network mode is not allowed by the execution policy.",
                command,
            )
        )

    if len(command.artifact_patterns) > policy.maximum_artifact_patterns_per_command:
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.TOO_MANY_ARTIFACT_PATTERNS,
                "Command requests too many artifact collection patterns.",
                command,
            )
        )

    if any(
        not _is_allowed_artifact_pattern(pattern, policy=policy)
        for pattern in command.artifact_patterns
    ):
        issues.append(
            _command_issue(
                SandboxPolicyIssueCode.ARTIFACT_PATTERN_FORBIDDEN,
                "Command artifact pattern can escape or inspect protected paths.",
                command,
            )
        )

    return tuple(issues)


def _command_issue(
    code: SandboxPolicyIssueCode,
    message: str,
    command: StructuredCommand,
) -> SandboxPolicyIssue:
    """Create one command-scoped issue without duplicating identifiers."""
    return SandboxPolicyIssue(
        code=code,
        message=message,
        command_id=command.command_id,
    )


def _is_shell_command_bridge(command: StructuredCommand) -> bool:
    """Detect known interpreters that evaluate one arbitrary command string."""
    executable_name = PurePosixPath(command.executable.replace("\\", "/")).name.casefold()
    first_argument = command.arguments[0].casefold() if command.arguments else None

    if executable_name in {"sh", "bash", "dash", "ksh", "zsh"}:
        return first_argument in _SHELL_COMMAND_FLAGS
    if executable_name in {"cmd", "cmd.exe"}:
        return first_argument in _CMD_COMMAND_FLAGS
    if executable_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return first_argument in _POWERSHELL_COMMAND_FLAGS
    return False


def _is_inline_code_bridge(command: StructuredCommand) -> bool:
    """Reject interpreter flags that evaluate an arbitrary inline code string."""
    executable_name = PurePosixPath(command.executable.replace("\\", "/")).name.casefold()
    first_argument = command.arguments[0].casefold() if command.arguments else None

    if executable_name in {"python", "python3", "python.exe", "python3.exe"}:
        return first_argument in _PYTHON_INLINE_FLAGS
    if executable_name in {"node", "node.exe"}:
        return first_argument in _NODE_INLINE_FLAGS
    if executable_name in {"php", "php.exe"}:
        return first_argument in _PHP_INLINE_FLAGS
    return False


def _is_allowed_artifact_pattern(
    pattern: str,
    *,
    policy: SandboxExecutionPolicy,
) -> bool:
    """Accept only relative workspace globs that cannot target protected paths."""
    if (
        len(pattern) > policy.maximum_artifact_pattern_length
        or pattern in {".", ".."}
        or pattern.startswith(("/", "//", "~"))
        or _WINDOWS_DRIVE_PATTERN.match(pattern)
        or ":" in pattern
    ):
        return False

    parts = pattern.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False

    literal_components = tuple(
        part.casefold()
        for part in parts
        if not any(character in part for character in ("*", "?", "[", "]"))
    )
    return not any(
        component in policy.prohibited_workspace_components for component in literal_components
    )


def _validate_sha256(value: str, *, label: str) -> None:
    """Require one lowercase hexadecimal SHA-256 value."""
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _canonical_json_bytes(value: dict[str, object]) -> bytes:
    """Serialize policy metadata deterministically for integrity hashing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
