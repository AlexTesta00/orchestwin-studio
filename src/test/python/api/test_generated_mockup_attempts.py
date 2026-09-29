from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from orchestwin.api.design_iterations import DesignIterationApplication, IterationRequest
from orchestwin.api.design_mockups import (
    MOCKUP_ATTEMPT,
    MockupRequest,
    MockupStatus,
    ModelMockupApplication,
    job_failure,
    job_payload,
)
from orchestwin.api.generation_jobs import (
    GenerationJobFailure,
    GenerationJobProgress,
    GenerationJobStage,
)
from orchestwin.artifacts.generated_mockups import MAX_SCREENS
from orchestwin.models.generated_mockup_drafts import (
    MOCKUP_QUALITY_REJECTED,
    GeneratedIterationDraft,
    GeneratedMockupDraft,
    GeneratedMockupRejection,
    MockupRejectionReason,
)
from orchestwin.models.generated_mockup_instructions import (
    DESIGN_ITERATION,
    DESIGN_MOCKUP_HTML,
    ITERATION_SENTENCE,
    RETRY_SENTENCE,
    RETRY_WITH_ANSWER_SENTENCE,
)
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from src.test.python.models.test_generated_mockup_binding import iteration_of
from src.test.python.models.test_generated_mockup_support import (
    DASHBOARD,
    DASHBOARD_ID,
    GUIDED_ID,
    OWNER_ID,
    PROJECT_ID,
    DesignVersions,
    MemoryMockupStore,
    ScriptedMockupGenerator,
    answer,
    applied_package,
    draft_payload,
    failure,
    package,
    refusal,
    runtime,
    with_markup,
)
from src.test.python.models.test_hosted_transient_retry import anthropic_generator, overloaded

BROKEN = with_markup(draft_payload(), "<h1>", "<h1>Lorem ipsum ")


class Progress(GenerationJobProgress):
    def __init__(self):
        super().__init__()
        self.updates = []

    def update(self, stage, attempt=None):
        self.updates.append((GenerationJobStage(stage), attempt))


def request_for(versions, alternative_id=GUIDED_ID):
    current = versions.versions[-1]
    return MockupRequest(
        design_version_id=current.id,
        design_content_hash=current.content_hash,
        alternative_id=alternative_id,
    )


def generate(*outcomes, store=None, versions=None, alternative_id=GUIDED_ID, application=None):
    generator = ScriptedMockupGenerator(*outcomes)
    store = MemoryMockupStore() if store is None else store
    versions = DesignVersions(package()) if versions is None else versions
    target = application or ModelMockupApplication
    app = target(runtime(generator, store, versions))
    progress = Progress()

    async def scenario():
        return await app.generate_mockup(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            body=request_for(versions, alternative_id),
            progress=progress,
        )

    try:
        return asyncio.run(scenario()), generator, store, progress
    except Exception as error:
        error.generator, error.store, error.progress = generator, store, progress
        raise


def kinds(store, index):
    return store.kinds(store.order[index])


def test_an_answer_accepted_at_the_first_generation():
    result, generator, store, progress = generate(answer(draft_payload()))
    assert result.status is MockupStatus.GENERATED
    [call] = generator.calls
    assert call["retry_schema_errors"] is False
    assert call["max_output_tokens"] == 32_000
    assert call["output_type"] is GeneratedMockupDraft
    assert call["context"]["purpose"] == DESIGN_MOCKUP_HTML
    assert "previous_answer" not in call["context"] and "rejection" not in call["context"]
    assert call["instruction"].startswith("Role and result:")
    assert kinds(store, 0) == ["PROVIDER_RESULT", "ADAPTER_ACCEPTED", "APPLICATION_RESULT"]
    accepted = store.payload(store.order[0], "ADAPTER_ACCEPTED")
    assert accepted["generated_content_hashes"] == {"DESIGN": [result.package.content_hash]}
    assert "related_generations" not in accepted
    assert accepted["result"]["cost_microusd"] == 410_000
    assert accepted["result"]["approach"] == draft_payload()["approach"]
    assert accepted["result"]["changes"] == []
    assert store.payload(store.order[0], "APPLICATION_RESULT")["status"] == "MOCKUP_GENERATED"
    assert result.generation_id == store.order[0]
    assert result.cost_microusd == 410_000
    assert result.package.owner_selected_alternative_id == GUIDED_ID
    assert result.package.generated_mockup.design_alternative_id == GUIDED_ID
    assert result.package.prototype == result.package.generated_mockup.prototype()
    assert result.warnings == ()
    assert progress.updates == [
        (GenerationJobStage.GENERATING, 1),
        (GenerationJobStage.VALIDATING, 1),
    ]


def test_warnings_of_the_review_and_of_the_coverage_reach_the_result():
    result, *_ = generate(answer(draft_payload(DASHBOARD)), alternative_id=DASHBOARD_ID)
    assert result.warnings == (
        {"code": "REQUIREMENTS_NOT_COVERED", "screen_code": None, "detail": "REQ-007"},
    )


def test_a_rejected_answer_is_corrected_by_a_second_generation():
    result, generator, store, progress = generate(
        answer(BROKEN, cost=300_000), answer(draft_payload(), cost=420_000)
    )
    first, second = generator.calls
    assert first["context"]["command_id"] == second["context"]["command_id"]
    assert second["context"]["previous_answer"] == BROKEN
    assert second["context"]["rejection"]["code"] == MOCKUP_QUALITY_REJECTED
    assert second["context"]["rejection"]["reasons"][0]["code"] == "PLACEHOLDER_TEXT"
    assert second["instruction"].endswith(RETRY_WITH_ANSWER_SENTENCE)
    assert kinds(store, 0) == ["PROVIDER_RESULT", "ADAPTER_REJECTED", "APPLICATION_RESULT"]
    rejected = store.payload(store.order[0], "ADAPTER_REJECTED")
    assert rejected["code"] == MOCKUP_QUALITY_REJECTED
    assert rejected["reason"].startswith("PLACEHOLDER_TEXT SCR-")
    assert store.payload(store.order[0], "APPLICATION_RESULT") == {
        "status": MOCKUP_QUALITY_REJECTED,
        "role": MOCKUP_ATTEMPT,
    }
    assert kinds(store, 1) == ["PROVIDER_RESULT", "ADAPTER_ACCEPTED", "APPLICATION_RESULT"]
    accepted = store.payload(store.order[1], "ADAPTER_ACCEPTED")
    [related] = accepted["related_generations"]
    assert related["role"] == MOCKUP_ATTEMPT
    assert related["generation_id"] == str(store.order[0])
    assert related["code"] == MOCKUP_QUALITY_REJECTED
    assert result.cost_microusd == 720_000
    assert accepted["result"]["cost_microusd"] == 720_000
    assert result.generation_id == store.order[1]
    assert [stage for stage, _attempt in progress.updates] == [
        GenerationJobStage.GENERATING,
        GenerationJobStage.VALIDATING,
        GenerationJobStage.RETRYING,
        GenerationJobStage.VALIDATING,
    ]
    assert progress.updates[-1] == (GenerationJobStage.VALIDATING, 2)


def test_the_second_attempt_of_an_iteration_keeps_the_limits_of_an_iteration():
    versions = DesignVersions(package(), applied_package())
    broken = {**BROKEN, "changes": ["Il riepilogo mostra la sede di ritiro."]}
    seven = iteration_of(7)
    generator = ScriptedMockupGenerator(answer(broken), answer(seven))
    app = DesignIterationApplication(runtime(generator, MemoryMockupStore(), versions))
    current = versions.versions[-1]
    body = IterationRequest(
        design_version_id=current.id,
        design_content_hash=current.content_hash,
        request="Aggiungi i passi per verificare i dati del lettore.",
    )
    result = asyncio.run(
        app.generate_iteration(owner_user_id=OWNER_ID, project_id=PROJECT_ID, body=body)
    )
    first, second = generator.calls
    limits = f"The mockup has between 3 and {MAX_SCREENS} screens."
    for call in (first, second):
        assert call["output_type"] is GeneratedIterationDraft
        assert call["context"]["purpose"] == DESIGN_ITERATION
        assert "current_mockup" in call["context"]
        assert call["instruction"].count(limits) == 1
        assert call["instruction"].count(ITERATION_SENTENCE) == 1
        assert "Draw between" not in call["instruction"]
    assert second["context"]["rejection"]["code"] == MOCKUP_QUALITY_REJECTED
    assert second["instruction"].endswith(RETRY_WITH_ANSWER_SENTENCE)
    assert len(result.package.generated_mockup.mockup.screens) == 7
    assert result.warnings == ()
    assert result.changes == tuple(seven["changes"])


def test_an_answer_rejected_twice_fails_the_command_with_the_code_of_the_rejection():
    with pytest.raises(GeneratedMockupRejection) as rejected:
        generate(answer(BROKEN), answer(BROKEN))
    error = rejected.value
    assert error.code == MOCKUP_QUALITY_REJECTED
    assert len(error.generator.calls) == 2
    store = error.store
    assert len(store.order) == 2
    assert kinds(store, 1) == ["PROVIDER_RESULT", "ADAPTER_REJECTED", "APPLICATION_RESULT"]
    assert store.payload(store.order[1], "APPLICATION_RESULT") == {
        "status": "FAILED",
        "code": MOCKUP_QUALITY_REJECTED,
    }
    assert not any("ADAPTER_ACCEPTED" in store.kinds(item) for item in store.order)


def test_a_retryable_failure_of_the_provider_is_retried_once_without_the_answer():
    result, generator, store, _progress = generate(
        failure("RATE_LIMITED", retryable=True, cost=None), answer(draft_payload())
    )
    second = generator.calls[1]["context"]
    assert "previous_answer" not in second and "rejection" not in second
    assert kinds(store, 0) == ["PROVIDER_RESULT", "APPLICATION_RESULT"]
    assert store.payload(store.order[0], "APPLICATION_RESULT") == {
        "status": "RATE_LIMITED",
        "role": MOCKUP_ATTEMPT,
    }
    assert result.cost_microusd == 410_000


def test_a_retryable_failure_twice_fails_the_command():
    with pytest.raises(ProposalGenerationError) as failed:
        generate(
            failure("PROVIDER_UNAVAILABLE", retryable=True),
            failure("PROVIDER_UNAVAILABLE", retryable=True),
        )
    assert failed.value.code == "PROVIDER_UNAVAILABLE"
    assert len(failed.value.generator.calls) == 2


def test_an_overloaded_provider_gets_at_most_two_generations_for_one_mockup():
    generator, client, pauses = anthropic_generator(*(overloaded() for _ in range(4)))
    store = MemoryMockupStore()
    versions = DesignVersions(package())
    app = ModelMockupApplication(runtime(generator, store, versions))
    with pytest.raises(ProposalGenerationError) as failed:
        asyncio.run(
            app.generate_mockup(
                owner_user_id=OWNER_ID, project_id=PROJECT_ID, body=request_for(versions)
            )
        )
    assert failed.value.code == "PROVIDER_UNAVAILABLE"
    assert len(client.messages.calls) == 2 and pauses.calls == []
    assert [kinds(store, index) for index in range(len(store.order))] == [
        ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT", "APPLICATION_RESULT"],
        ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT", "APPLICATION_RESULT"],
    ]
    assert [store.payload(item, "APPLICATION_RESULT") for item in store.order] == [
        {"status": "PROVIDER_UNAVAILABLE", "role": MOCKUP_ATTEMPT},
        {"status": "FAILED", "code": "PROVIDER_UNAVAILABLE"},
    ]


def test_a_failure_that_is_not_retryable_ends_the_command_at_once():
    with pytest.raises(ProposalGenerationError) as failed:
        generate(
            failure("INCOMPLETE_OUTPUT", retryable=False, cost=950_000), answer(draft_payload())
        )
    assert failed.value.code == "INCOMPLETE_OUTPUT"
    assert len(failed.value.generator.calls) == 1
    store = failed.value.store
    assert store.payload(store.order[0], "APPLICATION_RESULT") == {
        "status": "FAILED",
        "code": "INCOMPLETE_OUTPUT",
    }


def test_an_answer_that_breaks_the_schema_is_answered_again_with_the_reasons():
    message = (
        "The hosted model answer violates the output schema at $.screens[0].markup (maxLength)."
    )
    result, generator, _store, _progress = generate(
        failure("RESPONSE_SCHEMA_ERROR", retryable=False, cost=800_000, message=message),
        answer(draft_payload()),
    )
    second = generator.calls[1]
    assert "previous_answer" not in second["context"]
    assert second["context"]["rejection"] == {
        "code": "RESPONSE_SCHEMA_ERROR",
        "reasons": [{"code": "RESPONSE_SCHEMA_ERROR", "screen_code": None, "detail": message}],
    }
    assert second["instruction"].endswith(RETRY_SENTENCE)
    assert result.cost_microusd == 1_210_000


def test_an_answer_that_breaks_the_draft_model_is_answered_again():
    result, generator, _store, _progress = generate(
        answer({**draft_payload(), "approach": ""}), answer(draft_payload())
    )
    assert generator.calls[1]["context"]["rejection"]["code"] == "INVALID_PROVIDER_OUTPUT"
    assert result.cost_microusd == 820_000


def test_a_budget_refusal_happens_before_any_generation():
    with pytest.raises(ProposalGenerationError) as refused:
        generate(refusal("GENERATION_BUDGET_EXCEEDED"), answer(draft_payload()))
    assert refused.value.code == "GENERATION_BUDGET_EXCEEDED"
    assert len(refused.value.generator.calls) == 1
    assert refused.value.store.order == []


def test_a_budget_refusal_of_the_second_generation_ends_the_command():
    with pytest.raises(ProposalGenerationError) as refused:
        generate(answer(BROKEN), refusal("GENERATION_BUDGET_EXCEEDED"))
    assert refused.value.code == "GENERATION_BUDGET_EXCEEDED"
    store = refused.value.store
    assert len(store.order) == 1
    assert store.payload(store.order[0], "APPLICATION_RESULT")["role"] == MOCKUP_ATTEMPT


def test_a_design_changed_during_the_generation_is_never_accepted():
    versions = DesignVersions(package())
    body = request_for(versions)

    class Moving(DesignVersions):
        async def current(self, *, owner_user_id, project_id):
            value = await super().current(owner_user_id=owner_user_id, project_id=project_id)
            if self.current_calls == 1:
                self.apply(package(open_questions=("Nuova domanda aperta?",)))
            return value

    moving = Moving(package())
    generator = ScriptedMockupGenerator(answer(draft_payload()))
    store = MemoryMockupStore()
    app = ModelMockupApplication(runtime(generator, store, moving))
    with pytest.raises(HTTPException) as changed:
        asyncio.run(app.generate_mockup(owner_user_id=OWNER_ID, project_id=PROJECT_ID, body=body))
    assert changed.value.status_code == 409
    assert changed.value.detail == {"code": "DESIGN_CONTEXT_CHANGED"}
    assert kinds(store, 0) == ["PROVIDER_RESULT", "APPLICATION_RESULT"]
    assert store.payload(store.order[0], "APPLICATION_RESULT") == {
        "status": "FAILED",
        "code": "DESIGN_CONTEXT_CHANGED",
    }


def test_confirmed_observations_of_the_last_review_reach_the_context():
    observation = {"twin": "Giulia", "summary": "Il riepilogo è lungo."}

    class Reviewed(ModelMockupApplication):
        async def observations(self, owner_user_id, project_id, version, alternative):
            assert alternative.id == GUIDED_ID
            return [observation]

    _result, generator, _store, _progress = generate(answer(draft_payload()), application=Reviewed)
    assert generator.calls[0]["context"]["confirmed_observations"] == [observation]


def test_every_failure_of_a_command_becomes_a_job_failure():
    rejection = GeneratedMockupRejection(
        MOCKUP_QUALITY_REJECTED, [MockupRejectionReason("TABLE_TOO_SHORT", "SCR-001", "2 rows")]
    )
    assert job_failure(rejection).to_snapshot() == {
        "code": MOCKUP_QUALITY_REJECTED,
        "reasons": [{"code": "TABLE_TOO_SHORT", "screen_code": "SCR-001", "detail": "2 rows"}],
    }
    assert job_failure(rejection).rejected is True
    schema = job_failure(ProposalGenerationError("RESPONSE_SCHEMA_ERROR"))
    assert schema.rejected is True and schema.code == "RESPONSE_SCHEMA_ERROR"
    budget = job_failure(ProposalGenerationError("GENERATION_BUDGET_EXCEEDED"))
    assert budget.rejected is False and budget.reasons == ()
    conflict = job_failure(HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"}))
    assert conflict.code == "DESIGN_CONTEXT_CHANGED"
    assert job_failure(ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED")).code == (
        "GENERATION_EVIDENCE_WRITE_FAILED"
    )
    kept = GenerationJobFailure("X")
    assert job_failure(kept) is kept
    assert job_failure(RuntimeError("other")) is None


def test_a_job_payload_is_the_result_payload_or_a_job_failure():
    result, *_ = generate(answer(draft_payload()))

    async def succeeded():
        return result

    payload = asyncio.run(job_payload(succeeded()))
    assert payload["status"] == "MOCKUP_GENERATED"
    assert payload["generation_id"] == str(result.generation_id)
    assert payload["package"]["generated_mockup"]["mockup"]["design_alternative_id"] == str(
        GUIDED_ID
    )
    assert set(payload) == {
        "status",
        "generation_id",
        "design_version_id",
        "design_content_hash",
        "package",
        "approach",
        "changes",
        "warnings",
        "cost_microusd",
    }

    async def rejected():
        raise GeneratedMockupRejection(MOCKUP_QUALITY_REJECTED)

    with pytest.raises(GenerationJobFailure):
        asyncio.run(job_payload(rejected()))

    async def broken():
        raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError):
        asyncio.run(job_payload(broken()))
    assert isinstance(UUID(payload["design_version_id"]), UUID)
