from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api import design_loop, design_opinions
from orchestwin.api.design_opinions import (
    DESIGN_CHANGE_OPINION_FAILED,
    RUN_PAYLOAD_KEYS,
    DesignOpinionRequest,
)
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import request_key
from orchestwin.api.services import ApplicationRuntime
from orchestwin.evaluation.change_opinion import (
    CHANGE_OPINION_PURPOSE,
    CHANGE_OPINION_TASK,
    HOSTED_INSTRUCTION,
    INVALID_CHANGE_OPINION_OUTPUT,
)
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_user_twin_references,
    snapshot_content_hash,
)
from src.test.python.api import test_design_loop_api as loop
from src.test.python.api.test_generation_requests_operations import (
    ASYNC,
    PROJECT_PATH,
    application_for,
    in_process,
)
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts.test_design_change_opinions48 import OPINION_KEYS
from src.test.python.artifacts.test_design_package_extension import (
    extended_version,
    fixture_package,
)
from src.test.python.models.test_generated_mockup_support import (
    MemoryMockupStore,
    ScriptedMockupGenerator,
    answer,
)

OPINIONS = "/design/opinions"
LISTED = f"{PROJECT_PATH}{OPINIONS}"
COST = 410_000
REQUEST = "  Fai la barra   rossa con il testo blu "
TARGET = {"screen_code": "SCR-001", "element_code": "ELM-012", "label": "Sollecita i 9 ritardi"}
SUGGESTION = "Fai la barra rossa con il testo bianco."
ENGLISH = "The red bar with the blue text would be hard to read for me at the desk."
RECORDED = {"status": "DESIGN_CHANGE_OPINION_RECORDED", "issue": None}
TARGET_INVALID = {"detail": {"code": "DESIGN_CHANGE_TARGET_INVALID"}}
BLANK_REQUEST = {
    "detail": "invalid_request",
    "errors": [{"loc": ["body", "request"], "type": "value_error"}],
}
SECOND = UserTwinVersionReference(
    twin_id=UUID("00000000-0000-4000-8000-000000004831"),
    version_number=1,
    content_hash="c" * 64,
    name="Volontaria del sabato",
)
THIRD = UserTwinVersionReference(
    twin_id=UUID("00000000-0000-4000-8000-000000004832"),
    version_number=3,
    content_hash="d" * 64,
    name="Lettore con la lente",
)


class Versions:
    def __init__(self, version):
        self.version = version

    async def current(self, *, owner_user_id, project_id):
        return self.version

    async def history(self, *, owner_user_id, project_id):
        return (self.version,)


class OpinionStore(MemoryMockupStore):
    def record(self, generation_id):
        return {
            "generation_id": str(generation_id),
            "recorded_at": self.times[generation_id].isoformat(),
            "context": self.context(generation_id),
            "events": {kind: payload for kind, payload, _raw in self.events[generation_id]},
        }

    async def design_change_opinion_generations(self, *, owner_user_id, project_id, limit=200):
        return [
            self.record(generation_id)
            for generation_id in reversed(self.order)
            if self.owned(generation_id, owner_user_id, project_id)
            and self.context(generation_id)["purpose"] == CHANGE_OPINION_PURPOSE
        ][:limit]

    async def get_owned(self, *, owner_user_id, project_id, generation_id):
        return {
            "observations": [
                {"kind": kind, "payload": payload}
                for kind, payload, _raw in self.events[generation_id]
            ]
        }


def single_version():
    return extended_version(fixture_package())


def twins_version():
    package = fixture_package()
    pairs = [
        (reference, critique) for reference in (SECOND, THIRD) for critique in package.critiques
    ]
    added = tuple(
        replace(
            critique,
            id=UUID(int=4840 + offset),
            code=f"CRQ-{len(package.critiques) + offset + 1:03d}",
            user_twin_reference=reference,
        )
        for offset, (reference, critique) in enumerate(pairs)
    )
    references = canonical_user_twin_references(
        (*package.grounding.user_twin_references, SECOND, THIRD), require_items=True
    )
    return extended_version(
        replace(
            package,
            grounding=replace(package.grounding, user_twin_references=references),
            critiques=tuple(sorted((*package.critiques, *added), key=lambda item: item.code)),
        )
    )


def runtime(version, generator=None):
    return ApplicationRuntime(
        identity_service=object(),
        database_runtime=SimpleNamespace(session_factory=loop.FakeSession),
        design_query_service=Versions(version),
        proposal_evidence_store=OpinionStore(),
        real_model_runtime=None
        if generator is None
        else SimpleNamespace(
            user_modeling=SimpleNamespace(proposal_port=SimpleNamespace(generator=generator))
        ),
    )


def studio(monkeypatch, *answers, version, profile=loop.ObservedProfile):
    references = version.package.grounding.user_twin_references
    monkeypatch.setattr(loop.MemoryTwins, "references", {item.twin_id: item for item in references})
    monkeypatch.setattr(design_loop, "SqlAlchemyUserTwinVersionRepository", loop.MemoryTwins)
    monkeypatch.setattr(design_opinions, "EvaluationUserTwinProfile", profile)
    generator = ScriptedMockupGenerator(*answers) if answers else None
    settings = runtime(version, generator)
    return application_for(settings), generator, settings.proposal_evidence_store


def said(verdict, **changes):
    return answer(
        {
            "verdict": verdict,
            "why": "Al banco leggo in fretta e una barra rossa con il testo blu mi fermerebbe.",
            "what_to_do": "Tieni il testo scuro e usa il rosso solo per il bordo della barra.",
            "try_this": SUGGESTION,
            "profile_keys": ["user_twin.role"],
            "self_confidence": 0.7,
            **changes,
        },
        cost=COST,
    )


def body(version, **changes):
    return {
        "design_version_id": str(version.id),
        "design_content_hash": version.content_hash,
        "request": REQUEST,
        "target": TARGET,
        "locale": "it-IT",
        **changes,
    }


def asked(application, *bodies, headers=None):
    return in_process(application, [(OPINIONS, item, headers or {}) for item in bodies])


def without_time(run):
    return {key: value for key, value in run.items() if key != "requested_at"}


def test_the_job_key_of_an_opinion_reads_the_request_as_the_owner_wrote_it():
    version = single_version()
    written = DesignOpinionRequest.model_validate(body(version))
    tidy = DesignOpinionRequest.model_validate(
        body(version, request="Fai la barra rossa con il testo blu")
    )
    assert tuple(DesignOpinionRequest.model_fields) == (
        "design_version_id",
        "design_content_hash",
        "request",
        "target",
        "locale",
    )
    assert written.model_dump(mode="json")["request"] == REQUEST
    keys = {
        request_key(
            GenerationOperation.DESIGN_CHANGE_OPINION, {"project_id": version.project_id}, item
        )
        for item in (written, tidy)
    }
    assert len(keys) == 2
    assert all(key.startswith("DESIGN_CHANGE_OPINION:") for key in keys)


def test_three_twins_give_their_opinion_and_the_run_comes_back_without_envelope(monkeypatch):
    version = twins_version()
    application, generator, store = studio(
        monkeypatch,
        said("BLOCKS"),
        said("SLOWS", try_this=None),
        said("HELPS"),
        version=version,
    )
    [answered] = asked(application, body(version))
    run = answered.json()
    references = version.package.grounding.user_twin_references
    assert answered.status_code == 201, run
    assert list(run) == list(RUN_PAYLOAD_KEYS)
    assert [list(item) for item in run["opinions"]] == [OPINION_KEYS] * 3
    assert [
        (item["twin_id"], item["twin_version"], item["twin_name"], item["verdict"])
        for item in run["opinions"]
    ] == [
        (str(reference.twin_id), reference.version_number, reference.name, verdict)
        for reference, verdict in zip(references, ("BLOCKS", "SLOWS", "HELPS"), strict=True)
    ]
    assert [item["try_this"] for item in run["opinions"]] == [SUGGESTION, None, SUGGESTION]
    generations = [str(item) for item in store.order]
    assert [item["generation_id"] for item in run["opinions"]] == generations
    assert {key: run[key] for key in RUN_PAYLOAD_KEYS[1:7]} == {
        "design_version_id": str(version.id),
        "design_content_hash": version.content_hash,
        "design_version_number": version.version_number,
        "request": "Fai la barra rossa con il testo blu",
        "target": TARGET,
        "locale": "it-IT",
    }
    assert run["contrast"] == {
        "mode": "LIGHT",
        "text_threshold": 4.5,
        "large_text_threshold": 3.0,
        "control_border_threshold": 3.0,
    }
    assert run["cost_microusd"] == 3 * COST
    assert [call["task"] for call in generator.calls] == [CHANGE_OPINION_TASK] * 3
    assert {call["instruction"] for call in generator.calls} == {HOSTED_INSTRUCTION}


def test_each_twin_leaves_the_evidence_of_its_generation_with_the_hash_of_its_opinion(
    monkeypatch,
):
    version = twins_version()
    application, _generator, store = studio(
        monkeypatch, said("BLOCKS"), said("SLOWS"), said("HELPS"), version=version
    )
    [answered] = asked(application, body(version))
    run = answered.json()
    given = {"status": "TWIN_OPINION_GIVEN", "opinion_run_id": run["run_id"]}
    contexts = [store.context(item) for item in store.order]
    assert [(context["purpose"], context["command_id"]) for context in contexts] == [
        (CHANGE_OPINION_PURPOSE, run["run_id"])
    ] * 3
    assert [context["user_twin"]["twin_id"] for context in contexts] == [
        item["twin_id"] for item in run["opinions"]
    ]
    assert [store.kinds(item) for item in store.order] == [
        ["PROVIDER_RESULT", "ADAPTER_ACCEPTED", "APPLICATION_RESULT"]
    ] * 3
    for generation_id, opinion in zip(store.order, run["opinions"], strict=True):
        accepted = store.payload(generation_id, "ADAPTER_ACCEPTED")
        assert accepted["result"] == opinion
        assert accepted["generated_content_hashes"] == {
            CHANGE_OPINION_PURPOSE: [snapshot_content_hash(opinion)]
        }
    assert [store.payload(item, "APPLICATION_RESULT") for item in store.order] == [
        given,
        given,
        RECORDED,
    ]


def test_an_opinion_asked_as_a_job_is_followed_to_its_run(monkeypatch):
    version = single_version()
    application, _generator, store = studio(monkeypatch, said("SLOWS"), version=version)
    [job] = asked(application, body(version), headers=ASYNC)
    payload = job.json()
    assert (payload["kind"], payload["operation"], payload["status"]) == (
        "REQUEST",
        "DESIGN_CHANGE_OPINION",
        "SUCCEEDED",
    )
    response = payload["response"]
    assert response["status_code"] == 201
    assert list(response["body"]) == list(RUN_PAYLOAD_KEYS)
    [opinion] = response["body"]["opinions"]
    assert opinion["generation_id"] == str(store.order[0])
    assert store.payload(store.order[0], "APPLICATION_RESULT") == RECORDED


@pytest.mark.parametrize(
    ("changes", "status_code", "refusal"),
    [
        ({"request": " \n "}, 422, BLANK_REQUEST),
        ({"target": {"screen_code": "SCR-001", "element_code": "ELM-099"}}, 422, TARGET_INVALID),
        ({"target": {"screen_code": "SCR-001", "element_code": "ZON-099"}}, 422, TARGET_INVALID),
        ({"target": {"screen_code": "SCR-009"}}, 422, TARGET_INVALID),
        ({"design_content_hash": "f" * 64}, 409, {"detail": {"code": "DESIGN_CONTEXT_CHANGED"}}),
    ],
)
def test_a_request_that_cannot_be_judged_is_refused_before_any_generation(
    monkeypatch, changes, status_code, refusal
):
    version = single_version()
    application, generator, store = studio(monkeypatch, said("SLOWS"), version=version)
    [answered] = asked(application, body(version, **changes))
    assert (answered.status_code, answered.json()) == (status_code, refusal)
    assert (generator.calls, store.order) == ([], [])


def test_a_zone_or_several_parts_are_judged_and_come_back_as_the_owner_sent_them(monkeypatch):
    version = single_version()
    zone = {"screen_code": "SCR-001", "element_code": "ZON-006", "label": "Filtri"}
    parts = {
        "screen_code": "SCR-001",
        "elements": [
            {"element_code": "ZON-006", "label": "Filtri"},
            {"element_code": "ELM-012", "label": "Sollecita i 9 ritardi"},
        ],
    }
    application, generator, _store = studio(
        monkeypatch, said("SLOWS"), said("HELPS"), version=version
    )
    answers = asked(application, body(version, target=zone), body(version, target=parts))
    assert [item.status_code for item in answers] == [201, 201]
    assert [item.json()["target"] for item in answers] == [zone, parts]
    held, several = (call["context"]["change"]["target"] for call in generator.calls)
    assert (held["element_code"], held["holds"]) == ("ZON-006", ["ELM-018", "ELM-019"])
    assert [item["element_code"] for item in several["elements"]] == ["ELM-012", "ZON-006"]


def test_a_design_without_its_mockup_or_a_studio_without_a_reviewer_is_refused(monkeypatch):
    plain = design_fixtures.design_version()
    application, generator, _store = studio(monkeypatch, said("SLOWS"), version=plain)
    [answered] = asked(application, body(plain))
    assert (answered.status_code, answered.json()) == (
        409,
        {"detail": {"code": "GENERATED_MOCKUP_REQUIRED"}},
    )
    assert generator.calls == []
    version = single_version()
    silent, _nothing, store = studio(monkeypatch, version=version)
    [answered] = asked(silent, body(version))
    assert (answered.status_code, answered.json()) == (
        503,
        {"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}},
    )
    assert store.order == []


def test_a_provided_prototype_has_no_opinion_of_the_twins():
    version = single_version()

    async def state(**_scope):
        return {"source": "PROVIDED_PROTOTYPE"}

    settings = replace(runtime(version), workflow_inputs_service=SimpleNamespace(state=state))
    [answered] = asked(application_for(settings), body(version))
    assert (answered.status_code, answered.json()) == (
        409,
        {"detail": {"code": "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE"}},
    )


def test_an_answer_in_another_language_is_asked_once_more_and_both_attempts_count(monkeypatch):
    version = single_version()
    application, generator, store = studio(
        monkeypatch, said("SLOWS", why=ENGLISH), said("SLOWS"), version=version
    )
    [answered] = asked(application, body(version))
    run = answered.json()
    rejected, accepted = store.order
    assert answered.status_code == 201, run
    assert len(generator.calls) == 2
    assert store.kinds(rejected) == ["PROVIDER_RESULT", "ADAPTER_REJECTED", "APPLICATION_RESULT"]
    assert store.payload(rejected, "APPLICATION_RESULT") == {
        "status": "TWIN_OPINION_REJECTED",
        "opinion_run_id": run["run_id"],
    }
    assert [item["generation_id"] for item in run["opinions"]] == [str(accepted)]
    assert run["cost_microusd"] == 2 * COST


def test_a_second_answer_in_another_language_fails_the_opinion(monkeypatch):
    version = single_version()
    application, _generator, store = studio(
        monkeypatch,
        said("SLOWS", why=ENGLISH),
        said("SLOWS", what_to_do=ENGLISH),
        version=version,
    )
    [answered] = asked(application, body(version))
    assert (answered.status_code, answered.json()) == (
        502,
        {"detail": {"code": INVALID_CHANGE_OPINION_OUTPUT, "stage": "MODEL_PROPOSAL"}},
    )
    assert store.payload(store.order[-1], "APPLICATION_RESULT") == {
        "status": "FAILED",
        "code": INVALID_CHANGE_OPINION_OUTPUT,
    }


def test_a_twin_without_known_observations_cannot_give_an_opinion(monkeypatch):
    version = single_version()
    application, generator, _store = studio(
        monkeypatch, said("SLOWS"), version=version, profile=loop.StubProfile
    )
    [answered] = asked(application, body(version))
    reason = "twin review requires at least one known profile observation"
    assert (answered.status_code, answered.json()) == (
        502,
        {"detail": {"code": DESIGN_CHANGE_OPINION_FAILED, "reason": reason}},
    )
    assert generator.calls == []


def test_the_runs_are_rebuilt_from_the_evidence_newest_first(monkeypatch):
    version = single_version()
    application, _generator, store = studio(
        monkeypatch, said("SLOWS"), said("BLOCKS"), version=version
    )
    first, second = (
        item.json()
        for item in asked(
            application,
            body(version),
            body(version, request="Rendi più grande il pulsante dei solleciti"),
        )
    )
    listed = TestClient(application).get(LISTED).json()["items"]
    assert [item["run_id"] for item in listed] == [second["run_id"], first["run_id"]]
    assert [without_time(item) for item in listed] == [without_time(second), without_time(first)]
    assert [item["requested_at"] for item in listed] == [
        store.times[item].isoformat() for item in reversed(store.order)
    ]


def test_a_run_that_failed_is_not_listed(monkeypatch):
    version = twins_version()
    application, _generator, _store = studio(
        monkeypatch,
        said("SLOWS"),
        said("SLOWS", why=ENGLISH),
        said("SLOWS", why=ENGLISH),
        version=version,
    )
    [failed] = asked(application, body(version))
    assert failed.status_code == 502
    assert TestClient(application).get(LISTED).json() == {"items": []}


def test_the_list_is_empty_without_evidence_and_unavailable_without_designs():
    settings = runtime(single_version())
    assert TestClient(application_for(settings)).get(LISTED).json() == {"items": []}
    blind = replace(settings, proposal_evidence_store=loop.MemoryEvidence())
    assert TestClient(application_for(blind)).get(LISTED).json() == {"items": []}
    unavailable = TestClient(application_for(replace(settings, design_query_service=None)))
    answered = unavailable.get(LISTED)
    assert (answered.status_code, answered.json()) == (
        503,
        {"detail": {"code": "DESIGN_QUERY_UNAVAILABLE"}},
    )
