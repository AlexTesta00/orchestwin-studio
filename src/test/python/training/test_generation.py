"""Contract tests for provider-independent dataset generation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from orchestwin.training.dataset_examples import (
    DatasetExampleSourceKind,
    DatasetLanguage,
    EvaluatorDatasetExample,
)
from orchestwin.training.generation import (
    DatasetGenerationFailure,
    DatasetGenerationFailureKind,
    DatasetGenerationRequest,
    DeterministicDatasetExampleGenerator,
)


def _request(**overrides: object) -> DatasetGenerationRequest:
    values: dict[str, object] = {
        "request_id": "generation-request-001",
        "scenario_family_id": "generic-operations-time-pressure",
        "language": DatasetLanguage.ENGLISH,
        "target_count": 1,
        "seed": 42,
        "context_hash": "f" * 64,
        "allowed_evidence_refs": (
            "REQ-NFR-012",
            "ut-profile-v3.operational_constraints[0]",
        ),
        "prompt_version_ref": "dataset-teacher-v1",
        "model_configuration_ref": "fake-teacher-v1",
    }
    values.update(overrides)
    return DatasetGenerationRequest(**values)  # type: ignore[arg-type]


def test_deterministic_adapter_returns_typed_repeatable_success(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    candidate = example_factory(
        source_kind=DatasetExampleSourceKind.SYNTHETIC_GENERATED,
        generation_ref="generation-request-001",
    )
    adapter = DeterministicDatasetExampleGenerator(
        adapter_id="fake-dataset-generator-v1",
        candidates=(candidate,),
    )

    first = asyncio.run(adapter.generate(_request()))
    second = asyncio.run(adapter.generate(_request()))

    assert first.succeeded is True
    assert first.candidates == (candidate,)
    assert first.metadata == second.metadata
    assert first.metadata is not None
    assert first.metadata.adapter_id == "fake-dataset-generator-v1"
    assert first.metadata.request_hash == _request().content_hash
    assert adapter.requests == [_request(), _request()]


def test_generation_failure_is_explicit_and_has_no_fallback_candidate(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    candidate = example_factory(
        source_kind=DatasetExampleSourceKind.SYNTHETIC_GENERATED,
        generation_ref="generation-request-001",
    )
    failure = DatasetGenerationFailure(
        DatasetGenerationFailureKind.BUDGET_EXHAUSTED,
        "The approved teacher-model budget is exhausted.",
        False,
    )
    adapter = DeterministicDatasetExampleGenerator(
        adapter_id="fake-dataset-generator-v1",
        candidates=(candidate,),
        failures_by_request_id={"generation-request-001": failure},
    )

    result = asyncio.run(adapter.generate(_request()))

    assert result.succeeded is False
    assert result.failure == failure
    assert result.metadata is None
    assert result.candidates == ()


def test_adapter_rejects_candidate_outside_evidence_allowlist(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    candidate = example_factory(
        source_kind=DatasetExampleSourceKind.SYNTHETIC_GENERATED,
        generation_ref="generation-request-001",
    )
    adapter = DeterministicDatasetExampleGenerator(
        adapter_id="fake-dataset-generator-v1",
        candidates=(candidate,),
    )

    request = _request(allowed_evidence_refs=("REQ-NFR-012",))

    try:
        asyncio.run(adapter.generate(request))
    except ValueError as error:
        assert "outside the request allowlist" in str(error)
    else:
        raise AssertionError("the adapter accepted unauthorized evidence")
