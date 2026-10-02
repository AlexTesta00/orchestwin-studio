from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.api import twin_learning as studio_learning
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.cli.api import twin_learning as learning_api
from orchestwin.cli.client import StudioClient
from orchestwin.cli.errors import ApiFailure
from orchestwin.knowledge import state

from .support.terminal import PROJECT_ID, command_context, store_session, terminal
from .support.transports import API, ScriptedTransport

BASE = f"{API}/projects/{PROJECT_ID}"
TWIN_ID = "6b8f0f5e-0000-4000-8000-000000000011"
OTHER_TWIN = "6b8f0f5e-0000-4000-8000-000000000012"
UPDATE_ID = "6b8f0f5e-0000-4000-8000-0000000000a1"
NOT_FOUND = {"detail": "Not Found"}


def entry(
    *,
    twin_id: str = TWIN_ID,
    development: int = 2,
    observations: list[dict[str, object]] | None = None,
    retired: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "twin_id": twin_id,
        "twin_name": "Marta",
        "profile_version_number": 1,
        "development_version_number": development,
        "label": f"1.{development}",
        "observations": [] if observations is None else observations,
        "retired": [] if retired is None else retired,
    }


def observation(code: str, *, update_id: str | None = UPDATE_ID) -> dict[str, object]:
    return {
        "code": code,
        "statement": f"Statement of {code}.",
        "basis": None if update_id is None else "A finding on the acceptance tests.",
        "source": "OWNER" if update_id is None else "TWIN_CRITIQUE",
        "about": {"requirement": "REQ-003", "screen": None},
        "contradicts_profile": None,
        "added_in_version": 1,
        "approved_at": "2026-09-30T10:00:00+00:00",
        "update_id": update_id,
    }


def update(**changes: object) -> dict[str, object]:
    return {
        "id": UPDATE_ID,
        "twin_id": TWIN_ID,
        "twin_name": "Marta",
        "created_at": "2026-09-30T10:00:00+00:00",
        "locale": "en-US",
        "status": "PROPOSED",
        "base": {"profile_version_number": 1, "development_version_number": 0},
        "comment": "From the latest critiques I learned 2 things about my group.",
        "observations": [
            {
                "index": 0,
                "statement": "People read the digits from far away.",
                "basis": "A finding on the commit 1a2b3c4d.",
                "about": {"requirement": "REQ-003", "screen": "SCR-001"},
                "contradicts_profile": None,
            }
        ],
        "material": {"changes": 3, "tests": 1},
        "decision": None,
        "cost_microusd": 150_000,
        **changes,
    }


def client_for(tmp_path: Path, transport: ScriptedTransport) -> StudioClient:
    store_session(tmp_path)
    return command_context(terminal(tmp_path, transport=transport).environment).client()


def test_the_words_and_the_limits_are_the_ones_of_the_studio() -> None:
    assert learning_api.TWIN_LEARNING_KIND == state.TWIN_LEARNING_KIND
    assert learning_api.FEEDBACK_LEARNING == state.FEEDBACK_LEARNING
    assert learning_api.LEARNING_SOURCES == state.LEARNING_SOURCES
    assert learning_api.UPDATE_STATUSES == state.UPDATE_STATUSES
    assert learning_api.UPDATE_DECISIONS == state.UPDATE_DECISIONS
    assert learning_api.OBSERVATION_CODE_PREFIX == state.OBSERVATION_CODE_PREFIX
    assert learning_api.MAX_LEARNED_OBSERVATIONS == state.MAX_LEARNED_OBSERVATIONS
    assert learning_api.MAX_UPDATE_OBSERVATIONS == state.MAX_UPDATE_OBSERVATIONS
    assert learning_api.MAX_OBSERVATION_LENGTH == state.MAX_OBSERVATION_LENGTH
    assert learning_api.MAX_BASIS_LENGTH == state.MAX_BASIS_LENGTH
    assert learning_api.MAX_UPDATE_COMMENT_LENGTH == state.MAX_UPDATE_COMMENT_LENGTH
    assert learning_api.MAX_UPDATE_CHANGES == state.MAX_UPDATE_CHANGES
    assert learning_api.MAX_UPDATE_TESTS == state.MAX_UPDATE_TESTS
    assert learning_api.MAX_REASON_LENGTH == state.MAX_TASK_NOTE_LENGTH


def test_the_status_words_and_the_codes_are_the_ones_of_the_routes() -> None:
    assert (
        learning_api.PROPOSED,
        learning_api.DECIDED,
        learning_api.LEARNED,
        learning_api.RETIRED,
    ) == (
        studio_learning.PROPOSED,
        studio_learning.DECIDED,
        studio_learning.LEARNED,
        studio_learning.RETIRED,
    )
    assert GenerationOperation.TWIN_UPDATE.value == learning_api.UPDATE_OPERATION
    assert {
        learning_api.PROJECT_NOT_FOUND,
        learning_api.USER_MODELING_APPROVAL_REQUIRED,
        learning_api.USER_TWIN_NOT_FOUND,
        learning_api.REQUIREMENTS_APPROVAL_REQUIRED,
        learning_api.DESIGN_APPROVAL_REQUIRED,
        learning_api.UPDATE_PENDING,
        learning_api.NOTHING_NEW,
        learning_api.NO_UPDATE_MODEL,
        learning_api.UPDATE_NOT_FOUND,
        learning_api.ALREADY_DECIDED,
        learning_api.CONTEXT_CHANGED,
        learning_api.OBSERVATIONS_LIMIT,
        learning_api.OBSERVATION_NOT_FOUND,
    } == {
        studio_learning.PROJECT_NOT_FOUND,
        studio_learning.USER_MODELING_APPROVAL_REQUIRED,
        studio_learning.USER_TWIN_NOT_FOUND,
        studio_learning.REQUIREMENTS_APPROVAL_REQUIRED,
        studio_learning.DESIGN_APPROVAL_REQUIRED,
        studio_learning.TWIN_UPDATE_PENDING,
        studio_learning.TWIN_UPDATE_NOTHING_NEW,
        studio_learning.TWIN_UPDATE_MODEL_NOT_CONFIGURED,
        studio_learning.TWIN_UPDATE_NOT_FOUND,
        studio_learning.TWIN_UPDATE_ALREADY_DECIDED,
        studio_learning.TWIN_UPDATE_CONTEXT_CHANGED,
        studio_learning.TWIN_OBSERVATIONS_LIMIT,
        studio_learning.TWIN_OBSERVATION_NOT_FOUND,
    }


def test_the_paths_and_the_bodies_of_the_six_routes() -> None:
    project = f"/projects/{PROJECT_ID}"

    assert learning_api.learning_path(PROJECT_ID) == f"{project}/twin-learning"
    assert learning_api.propose_path(PROJECT_ID, TWIN_ID) == (
        f"{project}/user-twins/{TWIN_ID}/updates"
    )
    assert learning_api.update_path(PROJECT_ID, UPDATE_ID) == f"{project}/twin-updates/{UPDATE_ID}"
    assert learning_api.decision_path(PROJECT_ID, UPDATE_ID) == (
        f"{project}/twin-updates/{UPDATE_ID}/decision"
    )
    assert learning_api.observations_path(PROJECT_ID, TWIN_ID) == (
        f"{project}/user-twins/{TWIN_ID}/observations"
    )
    assert learning_api.retire_path(PROJECT_ID, TWIN_ID, "OBS-002") == (
        f"{project}/user-twins/{TWIN_ID}/observations/OBS-002/retire"
    )
    assert learning_api.propose_body("it-IT") == {"locale": "it-IT"}
    assert learning_api.decision_body(
        "APPROVE", [learning_api.Kept(0), learning_api.Kept(2, "Edited.")]
    ) == {
        "decision": "APPROVE",
        "kept": [{"index": 0, "statement": None}, {"index": 2, "statement": "Edited."}],
        "reason": None,
    }
    assert learning_api.decision_body("REJECT", reason="Not true.") == {
        "decision": "REJECT",
        "kept": [],
        "reason": "Not true.",
    }
    assert learning_api.learn_body("People stand.") == {"statement": "People stand.", "about": None}
    assert learning_api.learn_body("People stand.", {"requirement": "REQ-001", "screen": None}) == {
        "statement": "People stand.",
        "about": {"requirement": "REQ-001", "screen": None},
    }
    assert learning_api.retire_body() == {"reason": None}
    assert learning_api.retire_body("Wrong.") == {"reason": "Wrong."}


def test_the_overview_is_read_as_the_studio_answers(tmp_path: Path) -> None:
    document = {
        "project_id": PROJECT_ID,
        "update_available": True,
        "twins": [
            {
                **entry(observations=[observation("OBS-001")]),
                "pending_update": update(),
                "new_material": {"changes": 2, "tests": 0},
            },
            "not a twin",
        ],
    }
    transport = ScriptedTransport().expect("GET", f"{BASE}/twin-learning", body=document)
    client = client_for(tmp_path, transport)

    found = learning_api.overview(client, PROJECT_ID)
    learning = learning_api.learning_of(found)

    assert found == document
    assert learning.update_available is True
    assert [item["twin_id"] for item in learning.entries] == [TWIN_ID]
    assert learning.entry(TWIN_ID) == document["twins"][0]
    assert learning.entry(OTHER_TWIN) is None
    assert learning.learned_anything() is True
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "body"),
    [(404, NOT_FOUND), (405, {"detail": "Method Not Allowed"}), (500, b"boom"), (503, None)],
)
def test_a_studio_older_than_this_sprint_gives_no_overview(
    tmp_path: Path, status: int, body: object
) -> None:
    transport = ScriptedTransport().expect("GET", f"{BASE}/twin-learning", status=status, body=body)

    assert learning_api.overview(client_for(tmp_path, transport), PROJECT_ID) is None
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "code"),
    [(404, "PROJECT_NOT_FOUND"), (403, "FORBIDDEN"), (422, "invalid_request")],
)
def test_other_refusals_of_the_overview_are_raised(tmp_path: Path, status: int, code: str) -> None:
    body = {"detail": code} if code == "invalid_request" else {"detail": {"code": code}}
    transport = ScriptedTransport().expect("GET", f"{BASE}/twin-learning", status=status, body=body)

    with pytest.raises(ApiFailure) as caught:
        learning_api.overview(client_for(tmp_path, transport), PROJECT_ID)

    assert (caught.value.code, caught.value.http_status) == (code, status)


def test_an_overview_that_is_not_an_object_is_an_api_failure(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect("GET", f"{BASE}/twin-learning", body=["twins"])

    with pytest.raises(ApiFailure) as caught:
        learning_api.overview(client_for(tmp_path, transport), PROJECT_ID)

    assert caught.value.code == "API_FAILURE"


def test_a_decision_sends_the_kept_observations_and_answers_the_twin(tmp_path: Path) -> None:
    decided = update(status="APPROVED")
    answer = {"status": "DECIDED", "update": decided, "twin": entry(development=1)}
    transport = ScriptedTransport().expect(
        "POST", f"{BASE}/twin-updates/{UPDATE_ID}/decision", body=answer
    )
    client = client_for(tmp_path, transport)

    found = learning_api.decide(
        client,
        PROJECT_ID,
        UPDATE_ID,
        "APPROVE",
        kept=[learning_api.Kept(0, "People read far away.")],
    )

    assert found == answer
    assert learning_api.twin_of(found) == answer["twin"]
    assert transport.sent[-1].json() == {
        "decision": "APPROVE",
        "kept": [{"index": 0, "statement": "People read far away."}],
        "reason": None,
    }


def test_a_rejection_sends_the_reason(tmp_path: Path) -> None:
    answer = {"status": "DECIDED", "update": update(status="REJECTED"), "twin": entry()}
    transport = ScriptedTransport().expect(
        "POST", f"{BASE}/twin-updates/{UPDATE_ID}/decision", body=answer
    )

    learning_api.decide(
        client_for(tmp_path, transport), PROJECT_ID, UPDATE_ID, "REJECT", reason="Not so."
    )

    assert transport.sent[-1].json() == {"decision": "REJECT", "kept": [], "reason": "Not so."}


@pytest.mark.parametrize(
    ("status", "detail", "values"),
    [
        (409, {"code": "TWIN_UPDATE_PENDING", "update_id": UPDATE_ID}, {"update_id": UPDATE_ID}),
        (409, {"code": "TWIN_UPDATE_PENDING", "update_id": None}, {}),
        (409, {"code": "TWIN_OBSERVATIONS_LIMIT"}, {}),
        (404, {"code": "USER_TWIN_NOT_FOUND"}, {}),
        (409, {"code": "USER_MODELING_APPROVAL_REQUIRED"}, {}),
    ],
)
def test_the_refusals_of_an_observation_carry_what_the_sentences_need(
    tmp_path: Path, status: int, detail: dict[str, object], values: dict[str, object]
) -> None:
    transport = ScriptedTransport().expect(
        "POST",
        f"{BASE}/user-twins/{TWIN_ID}/observations",
        status=status,
        body={"detail": detail},
    )

    with pytest.raises(ApiFailure) as caught:
        learning_api.learn(client_for(tmp_path, transport), PROJECT_ID, TWIN_ID, "People stand.")

    failure = caught.value
    assert (failure.code, failure.http_status, failure.detail) == (detail["code"], status, detail)
    assert dict(failure.values) == {"code": detail["code"], "http_status": status, **values}
    assert transport.sent[-1].json() == {"statement": "People stand.", "about": None}


def test_learning_and_retiring_answer_the_whole_twin(tmp_path: Path) -> None:
    learned = entry(development=1, observations=[observation("OBS-004", update_id=None)])
    retired = entry(
        development=2,
        retired=[
            {
                "code": "OBS-004",
                "statement": "Statement of OBS-004.",
                "retired_in_version": 2,
                "retired_at": "2026-09-30T11:00:00+00:00",
                "reason": "Wrong.",
            }
        ],
    )
    transport = (
        ScriptedTransport()
        .expect(
            "POST",
            f"{BASE}/user-twins/{TWIN_ID}/observations",
            status=201,
            body={"status": "LEARNED", "twin": learned},
        )
        .expect(
            "POST",
            f"{BASE}/user-twins/{TWIN_ID}/observations/OBS-004/retire",
            body={"status": "RETIRED", "twin": retired},
        )
    )
    client = client_for(tmp_path, transport)

    first = learning_api.learn(
        client,
        PROJECT_ID,
        TWIN_ID,
        "People stand.",
        about={"requirement": None, "screen": "SCR-002"},
    )
    second = learning_api.retire(client, PROJECT_ID, TWIN_ID, "OBS-004", reason="Wrong.")

    assert (first, second) == (learned, retired)
    assert [request.json() for request in transport.sent] == [
        {"statement": "People stand.", "about": {"requirement": None, "screen": "SCR-002"}},
        {"reason": "Wrong."},
    ]
    transport.assert_done()


def test_an_answer_without_the_twin_is_an_api_failure(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST",
        f"{BASE}/user-twins/{TWIN_ID}/observations/OBS-004/retire",
        body={"status": "RETIRED"},
    )

    with pytest.raises(ApiFailure) as caught:
        learning_api.retire(client_for(tmp_path, transport), PROJECT_ID, TWIN_ID, "OBS-004")

    assert (caught.value.code, caught.value.http_status) == ("API_FAILURE", 200)


def test_one_update_is_read_and_a_missing_one_is_refused(tmp_path: Path) -> None:
    path = f"{BASE}/twin-updates/{UPDATE_ID}"
    transport = (
        ScriptedTransport()
        .expect("GET", path, body=update())
        .expect("GET", path, status=404, body={"detail": {"code": "TWIN_UPDATE_NOT_FOUND"}})
    )
    client = client_for(tmp_path, transport)

    found = learning_api.update_of(client, PROJECT_ID, UPDATE_ID)
    with pytest.raises(ApiFailure) as caught:
        learning_api.update_of(client, PROJECT_ID, UPDATE_ID)

    assert found == update()
    assert caught.value.code == "TWIN_UPDATE_NOT_FOUND"


def test_the_failure_of_a_job_names_its_code_and_the_waiting_proposal() -> None:
    job = {"job_id": "job-1", "status": "FAILED", "failure": {"code": "GENERATION_JOB_EXPIRED"}}
    pending = {"detail": {"code": "TWIN_UPDATE_PENDING", "update_id": UPDATE_ID}}

    assert learning_api.failure(502, job).code == "GENERATION_JOB_EXPIRED"
    assert learning_api.failure(409, pending).values["update_id"] == UPDATE_ID
    assert learning_api.failure(500, "Internal Server Error").code == "API_FAILURE"
    assert learning_api.failure(500, None).detail is None
    assert learning_api.code_of({"detail": "invalid_request"}) == "invalid_request"
    assert learning_api.code_of([]) is None


def test_the_readers_of_a_twin_entry() -> None:
    active = [observation("OBS-001"), observation("OBS-003", update_id=None), "not one"]
    found = {
        **entry(observations=active, retired=[{"code": "OBS-002"}]),
        "pending_update": update(),
        "new_material": {"changes": 2, "tests": True},
    }
    empty = entry(development=0)

    assert learning_api.label_of(found) == "1.2"
    assert learning_api.label_of(None, 3) == "3"
    assert learning_api.label_of({"label": " "}, None) == "-"
    assert learning_api.development_version(found) == 2
    assert learning_api.development_version({"development_version_number": True}) == 0
    assert learning_api.learned_count(found) == 2
    assert learning_api.observation_codes(found) == ["OBS-001", "OBS-003"]
    assert learning_api.learned_codes(found, UPDATE_ID) == ["OBS-001"]
    assert learning_api.learned_codes(found, "") == []
    assert [item["code"] for item in learning_api.retired_observations(found)] == ["OBS-002"]
    assert learning_api.learned_anything(found) is True
    assert learning_api.learned_anything(empty) is False
    assert learning_api.learned_anything(None) is False
    assert learning_api.pending_update(found) == update()
    assert learning_api.pending_update(empty) is None
    assert learning_api.new_material(found) == (2, 0)
    assert learning_api.has_new_material(found) is True
    assert learning_api.has_new_material(empty) is False
    assert learning_api.learning_of("not an overview") == learning_api.Learning()


def test_the_readers_of_an_update() -> None:
    proposal = update()
    odd = {"id": 7, "status": None, "comment": ["no"], "material": None, "cost_microusd": -1}

    assert learning_api.proposal_of({"status": "PROPOSED", "update": proposal}) == proposal
    assert learning_api.proposal_of({"status": "PROPOSED"}) is None
    assert learning_api.update_id_of(proposal) == UPDATE_ID
    assert learning_api.update_status(proposal) == "PROPOSED"
    assert learning_api.update_comment(proposal) == (
        "From the latest critiques I learned 2 things about my group."
    )
    assert learning_api.update_material(proposal) == (3, 1)
    assert learning_api.update_cost(proposal) == 150_000
    assert [learning_api.update_id_of(odd), learning_api.update_status(odd)] == ["", ""]
    assert (learning_api.update_comment(odd), learning_api.update_material(odd)) == ("", (0, 0))
    assert learning_api.update_cost(odd) == 0
    first = learning_api.proposed_observations(proposal)[0]
    assert learning_api.observation_index(first, 5) == 0
    assert learning_api.observation_index({"index": "0"}, 5) == 5
    assert learning_api.observation_about(first) == ("REQ-003", "SCR-001")
    assert learning_api.observation_about({"about": "REQ-003"}) == (None, None)


@pytest.mark.parametrize(
    ("typed", "code", "number"),
    [
        ("OBS-001", "OBS-001", 1),
        ("obs-0002", "OBS-0002", 2),
        (" Obs-123456 ", "OBS-123456", 123456),
        ("OBS-1", None, None),
        ("OBS-1234567", None, None),
        ("TSK-001", None, None),
        ("OBS 001", None, None),
    ],
)
def test_an_observation_code_is_obs_and_three_to_six_digits(
    typed: str, code: str | None, number: int | None
) -> None:
    assert learning_api.observation_code(typed) == code
    assert learning_api.code_number(typed) == number


def test_a_kept_observation_is_written_as_the_route_reads_it() -> None:
    kept = learning_api.Kept(3, "Edited.")

    assert json.dumps(kept.document()) == '{"index": 3, "statement": "Edited."}'
    assert learning_api.Kept(1).document() == {"index": 1, "statement": None}
