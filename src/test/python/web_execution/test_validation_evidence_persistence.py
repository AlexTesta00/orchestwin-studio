"""Persistence codecs must preserve exact evidence and reject damaged records."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from orchestwin.web_execution.targets import WebImplementationLanguage, WebLanguageConfiguration
from orchestwin.web_execution.validation_evidence import (
    WebProfileValidationEvidence,
    WebProfileValidationEvidenceCatalog,
    WebProfileValidationEvidenceKind,
)
from orchestwin.web_execution.validation_evidence_persistence import (
    canonical_web_validation_evidence,
    web_validation_evidence_from_record,
    web_validation_evidence_to_record,
)


def evidence_fixture(**changes: object) -> WebProfileValidationEvidence:
    """Synthetic storage fixture; never production profile-validation evidence."""
    return replace(
        WebProfileValidationEvidence(
            evidence_id="test.storage.contract",
            kind=WebProfileValidationEvidenceKind.CONTRACT_TESTS,
            profile_id="web.static",
            profile_version="1.0.0",
            baseline_scope_hash="a" * 64,
            language_configuration=None,
            execution_runner_image_digest="b" * 64,
            browser_runner_image_digest="c" * 64,
            artifact_content_hash="d" * 64,
            reference="test.storage.artifact",
            recorded_at=datetime(2026, 9, 12, 14, 30, tzinfo=timezone(timedelta(hours=2))),
            passed=True,
        ),
        **changes,
    )


@pytest.mark.parametrize("configured", [False, True])
def test_round_trip_preserves_exact_snapshot_hash_and_original_timezone(configured: bool) -> None:
    evidence = evidence_fixture()
    if configured:
        evidence = replace(
            evidence,
            kind=WebProfileValidationEvidenceKind.VALID_FIXTURE_RUN,
            language_configuration=WebLanguageConfiguration(
                frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
            ),
        )
    row = web_validation_evidence_to_record(evidence)
    # PostgreSQL TIMESTAMPTZ changes the displayed offset, not the snapshot identity.
    row["recorded_at"] = evidence.recorded_at.astimezone(UTC)
    restored = web_validation_evidence_from_record(row)
    assert restored.to_snapshot() == evidence.to_snapshot()
    assert restored.content_hash == evidence.content_hash


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("evidence_id", "test.different"),
        ("kind", "RUNNER_BUILD"),
        ("profile_id", "web.vue"),
        ("profile_version", "2.0.0"),
        ("baseline_scope_hash", "e" * 64),
        ("language_configuration", {"frontend": "STATIC_ASSETS", "backend": None}),
        ("execution_runner_image_digest", "e" * 64),
        ("browser_runner_image_digest", None),
        ("artifact_content_hash", "e" * 64),
        ("reference", "test.different"),
        ("recorded_at", datetime(2026, 9, 11, tzinfo=UTC)),
        ("passed", False),
        ("passed", 1),
        ("content_hash", "e" * 64),
    ],
)
def test_every_relational_projection_is_verified(field: str, bad_value: object) -> None:
    row = web_validation_evidence_to_record(evidence_fixture())
    row[field] = bad_value
    with pytest.raises(ValueError):
        web_validation_evidence_from_record(row)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("artifact_content_hash", "not-a-digest"),
        ("reference", "../untrusted path"),
        ("profile_version", 1),
        ("passed", "false"),
        ("passed", 1),
        ("recorded_at", "2026-09-12T14:30:00"),
        ("language_configuration", {}),
        ("kind", "UNSUPPORTED"),
    ],
)
def test_corrupted_snapshot_is_never_coerced_to_valid_evidence(
    field: str, bad_value: object
) -> None:
    row = web_validation_evidence_to_record(evidence_fixture())
    row["evidence_snapshot"][field] = bad_value
    with pytest.raises(ValueError):
        web_validation_evidence_from_record(row)


@pytest.mark.parametrize("shape", ["extra", "missing", "not-object"])
def test_snapshot_schema_is_exact(shape: str) -> None:
    row = web_validation_evidence_to_record(evidence_fixture())
    if shape == "extra":
        row["evidence_snapshot"]["unverified"] = True
    elif shape == "missing":
        del row["evidence_snapshot"]["browser_runner_image_digest"]
    else:
        row["evidence_snapshot"] = []
    with pytest.raises(ValueError):
        web_validation_evidence_from_record(row)


def test_configuration_shape_and_language_types_are_not_silently_discarded() -> None:
    evidence = evidence_fixture(
        kind=WebProfileValidationEvidenceKind.VALID_FIXTURE_RUN,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.JAVASCRIPT, backend=None
        ),
    )
    for extra in ({"hidden": True}, {"frontend": 1}):
        row = deepcopy(web_validation_evidence_to_record(evidence))
        row["evidence_snapshot"]["language_configuration"].update(extra)
        with pytest.raises(ValueError):
            web_validation_evidence_from_record(row)


def test_canonical_order_is_domain_order_and_retains_stale_failed_conflicting_records() -> None:
    records = (
        evidence_fixture(evidence_id="test.z", profile_id="web.vue"),
        evidence_fixture(evidence_id="test.b", passed=False),
        evidence_fixture(evidence_id="test.a", baseline_scope_hash="f" * 64),
        evidence_fixture(evidence_id="test.c", execution_runner_image_digest="f" * 64),
    )
    ordered = canonical_web_validation_evidence(records)
    assert tuple(record.evidence_id for record in ordered) == (
        "test.a",
        "test.b",
        "test.c",
        "test.z",
    )
    assert WebProfileValidationEvidenceCatalog(ordered).records == ordered
    assert set(ordered) == set(records)


def test_duplicate_evidence_ids_cannot_become_a_catalog() -> None:
    with pytest.raises(ValueError, match="unique"):
        canonical_web_validation_evidence((evidence_fixture(), evidence_fixture(passed=False)))
