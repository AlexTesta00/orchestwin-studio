"""Tests for strict and capability-honest CUSTOM_DECLARATIVE profiles."""

from __future__ import annotations

from copy import deepcopy

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.custom_execution_profiles import (
    CustomExecutionProfileIssueCode,
    CustomExecutionProfileValidationStatus,
    validate_custom_execution_profile,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfilePhase,
    ExecutionProfileProjectValidationStatus,
)
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)

_DIGEST = "a" * 64
_IMAGE = "example/custom@sha256:" + "b" * 64


def _command(command_id: str, executable: str, arguments: list[str]) -> dict[str, object]:
    return {
        "command_id": command_id,
        "executable": executable,
        "arguments": arguments,
        "working_directory": ".",
        "allowed_environment_keys": ["CI"],
        "secret_references": [],
        "timeout_seconds": 120,
        "network_mode": "DISABLED",
        "expected_exit_codes": [0],
        "output_parser_id": None,
        "artifact_patterns": ["reports/**/*.xml"],
    }


def _declaration() -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile_id": "custom.example",
        "name": "Custom Example",
        "version": "1.0.0",
        "capability_status": "EXPERIMENTAL_LEVEL_D",
        "indicators": {
            "required_files": ["custom.lock"],
            "required_suffixes": [".custom"],
            "conflicting_files": ["legacy.lock"],
        },
        "runner": {
            "kind": "CONTAINER",
            "base_image": _IMAGE,
        },
        "network": {
            "setup": "DISABLED",
            "static_checks": "DISABLED",
            "build": "DISABLED",
            "test": "DISABLED",
            "run": "DISABLED",
        },
        "resources": {
            "cpu_count": 1.0,
            "memory_mib": 1024,
            "pids_limit": 64,
            "writable_tmpfs_mib": 128,
        },
        "commands": {
            "BUILD": [_command("custom.build", "python", ["-m", "build"])],
            "TEST": [_command("custom.test", "python", ["-m", "pytest", "-q"])],
        },
        "maintainer": "Project owner",
        "license_notes": "Owner-provided toolchain declaration.",
    }


def _inventory(*paths: str) -> SourceTreeInventory:
    entries = tuple(
        sorted(
            (
                SourceInventoryEntry(
                    normalized_path=path,
                    kind=SourceArchiveEntryKind.FILE,
                    classification=SourceInventoryClassification.SOURCE,
                    size_bytes=1,
                    sha256_digest=_DIGEST,
                    disposition=SourceArchiveEntryDisposition.INCLUDE,
                    disposition_reason=None,
                )
                for path in paths
            ),
            key=lambda entry: (entry.normalized_path.casefold(), entry.normalized_path),
        )
    )
    return SourceTreeInventory(archive_sha256="c" * 64, entries=entries)


def test_valid_declaration_creates_an_exact_experimental_profile() -> None:
    """Accept only a schema-valid, policy-valid profile that still needs owner approval."""
    report = validate_custom_execution_profile(_declaration())

    assert report.status is CustomExecutionProfileValidationStatus.ACCEPTED
    assert report.is_accepted
    assert report.requires_owner_approval
    assert report.profile is not None
    assert report.profile.metadata.capability_status is (
        ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D
    )
    assert report.profile.metadata.requires_owner_approval is True
    assert report.profile.image.value == _IMAGE
    assert len(report.declaration_content_hash or "") == 64
    assert all(policy.is_accepted for _, policy in report.profile.policy_reports)


def test_custom_profile_detects_valid_structure_and_returns_safe_plans() -> None:
    """Bind plans to the validated profile and exact structural inventory contract."""
    report = validate_custom_execution_profile(_declaration())
    assert report.profile is not None
    inventory = _inventory("custom.lock", "src/main.custom")

    detection = report.profile.detect(inventory)
    validation = report.profile.validate_project(inventory)
    build = report.profile.create_plan(ExecutionProfilePhase.BUILD, inventory)

    assert detection.confidence == 100
    assert detection.requires_human_decision is False
    assert validation.status is ExecutionProfileProjectValidationStatus.VALID
    assert build is not None
    assert build.profile_id == "custom.example"
    assert build.commands[0].executable == "python"


def test_missing_or_conflicting_indicators_prevent_plan_creation() -> None:
    """Do not let an approved declaration execute against a different project shape."""
    report = validate_custom_execution_profile(_declaration())
    assert report.profile is not None
    incomplete = _inventory("custom.lock")
    conflicting = _inventory("custom.lock", "src/main.custom", "legacy.lock")

    assert report.profile.validate_project(incomplete).status is (
        ExecutionProfileProjectValidationStatus.INVALID
    )
    assert report.profile.create_plan(ExecutionProfilePhase.BUILD, incomplete) is None
    assert report.profile.detect(conflicting).conflicting_indicators == (
        "conflicting-file:legacy.lock",
    )
    assert report.profile.validate_project(conflicting).status is (
        ExecutionProfileProjectValidationStatus.INVALID
    )


def test_schema_is_strict_and_requires_build_and_test_phases() -> None:
    """Reject additional fields and declarations that cannot plausibly reach Level D."""
    extra = _declaration()
    extra["unexpected"] = True
    missing_test = _declaration()
    commands = missing_test["commands"]
    assert isinstance(commands, dict)
    del commands["TEST"]

    extra_report = validate_custom_execution_profile(extra)
    phase_report = validate_custom_execution_profile(missing_test)

    assert extra_report.issues[0].code is CustomExecutionProfileIssueCode.SCHEMA_INVALID
    assert phase_report.issues[0].code is (CustomExecutionProfileIssueCode.REQUIRED_PHASE_MISSING)


def test_custom_namespace_and_indicator_roles_cannot_be_ambiguous() -> None:
    """Prevent custom declarations from impersonating built-ins or self-conflicting."""
    built_in_name = _declaration()
    built_in_name["profile_id"] = "WEB_STATIC"

    overlap = _declaration()
    indicators = overlap["indicators"]
    assert isinstance(indicators, dict)
    indicators["conflicting_files"] = ["custom.lock"]

    namespace_report = validate_custom_execution_profile(built_in_name)
    overlap_report = validate_custom_execution_profile(overlap)

    assert namespace_report.issues[0].code is (CustomExecutionProfileIssueCode.PROFILE_ID_INVALID)
    assert overlap_report.issues[0].code is (CustomExecutionProfileIssueCode.INDICATORS_INVALID)


def test_moving_images_shell_bridges_and_inline_code_are_rejected() -> None:
    """Keep custom profiles from becoming an arbitrary command or moving-image escape hatch."""
    moving_image = _declaration()
    runner = moving_image["runner"]
    assert isinstance(runner, dict)
    runner["base_image"] = "example/custom:latest"

    shell = _declaration()
    commands = shell["commands"]
    assert isinstance(commands, dict)
    commands["BUILD"] = [_command("custom.build", "bash", ["-c", "rm -rf /"])]

    inline = _declaration()
    inline_commands = inline["commands"]
    assert isinstance(inline_commands, dict)
    inline_commands["BUILD"] = [_command("custom.build", "python", ["-c", "print(1)"])]

    assert validate_custom_execution_profile(moving_image).issues[0].code is (
        CustomExecutionProfileIssueCode.RUNNER_INVALID
    )
    assert validate_custom_execution_profile(shell).issues[0].code is (
        CustomExecutionProfileIssueCode.COMMAND_POLICY_REJECTED
    )
    assert validate_custom_execution_profile(inline).issues[0].code is (
        CustomExecutionProfileIssueCode.COMMAND_POLICY_REJECTED
    )


def test_network_and_secret_capabilities_require_an_explicit_stronger_policy() -> None:
    """Reject undeclared high-impact capabilities under the default policy."""
    declaration = _declaration()
    network = declaration["network"]
    commands = declaration["commands"]
    assert isinstance(network, dict)
    assert isinstance(commands, dict)
    network["build"] = "CONTROLLED"
    build_commands = commands["BUILD"]
    assert isinstance(build_commands, list)
    command = build_commands[0]
    assert isinstance(command, dict)
    command["network_mode"] = "CONTROLLED"

    report = validate_custom_execution_profile(declaration)

    assert report.status is CustomExecutionProfileValidationStatus.REJECTED
    assert report.issues[0].code is (CustomExecutionProfileIssueCode.COMMAND_POLICY_REJECTED)


def test_invalid_metadata_returns_a_typed_rejection_instead_of_escaping() -> None:
    """Keep malformed human-readable metadata inside the expected result boundary."""
    invalid = _declaration()
    invalid["name"] = "Custom   Example"

    report = validate_custom_execution_profile(invalid)

    assert report.status is CustomExecutionProfileValidationStatus.REJECTED
    assert report.profile is None
    assert report.issues[0].code is CustomExecutionProfileIssueCode.SCHEMA_INVALID
    assert report.issues[0].path == "$"


def test_semantically_equivalent_declaration_order_produces_the_same_hash() -> None:
    """Make profile identity independent from mapping and set-like list ordering."""
    first = _declaration()
    second = deepcopy(first)
    indicators = second["indicators"]
    assert isinstance(indicators, dict)
    indicators["required_files"] = list(reversed(indicators["required_files"]))
    second = dict(reversed(tuple(second.items())))

    first_report = validate_custom_execution_profile(first)
    second_report = validate_custom_execution_profile(second)

    assert first_report.is_accepted
    assert second_report.is_accepted
    assert first_report.declaration_content_hash == second_report.declaration_content_hash
    assert first_report.profile is not None
    assert second_report.profile is not None
    assert first_report.profile.metadata.reference == second_report.profile.metadata.reference
