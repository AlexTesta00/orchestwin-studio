from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import zlib
from functools import partial
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from orchestwin.api import design_critique
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_critique import (
    MAX_PAGE_CHARACTERS,
    MAX_UPLOAD_BYTES,
    DesignCritiqueApplication,
    DesignCritiqueRequest,
    DesignCritiqueStatus,
    run_payload,
)
from orchestwin.api.validation import request_validation_error
from orchestwin.artifacts.design_critique import (
    MAX_SHOT_BYTES,
    critique_anchors,
    critique_source_view,
)
from orchestwin.artifacts.design_critique_persistence import DesignCritiqueWriteStatus
from orchestwin.evaluation.critique_evaluator import CRITIQUE_PURPOSE, INVALID_CRITIQUE_OUTPUT
from orchestwin.evaluation.proposer_evaluator import TWIN_REVIEW_TASK
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.proposal_evidence import begin_model_generation, retain_provider_result
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import SectionState
from orchestwin.projects.sections_service import SectionsFailure
from src.test.python.api import test_design_loop_api as loop
from src.test.python.artifacts import design_fixtures

OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
OTHER_PROJECT = UUID("00000000-0000-4000-8000-000000004410")
FIRST_TWIN = design_fixtures.TWIN_ID
SECOND_TWIN = loop.SECOND_TWIN_ID
PATH = f"/projects/{PROJECT}/design/critiques"
SOURCES = f"{PATH}/sources"
ADDRESS = "https://example.com/booking"
PRICE = 1500
BRIEF = "A booking tool for the front desk of a small hotel."
CLAUDE_CODE = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
PAGE = {
    "url": ADDRESS,
    "title": "Hotel booking page",
    "text": "Book a room. Arrival date. Search rooms.",
    "hidden_text": "",
    "elements": [
        {"index": 0, "role": "textbox", "name": "Arrival date", "value": ""},
        {"index": 1, "role": "button", "name": "Search rooms"},
    ],
}


def png(width, height):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(b"\x00" + b"\x20\x40\x60" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def jpeg(width, height):
    marker = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + marker + frame + b"\xff\xd9"


PICTURE = png(120, 260)
WIDE = png(144, 90)
NARROW = jpeg(39, 84)
GIF = b"GIF89a" + bytes(32)


def picture(name="checkout-sketch.png", content=PICTURE, media_type="image/png"):
    return (name, content, media_type)


def twin(twin_id, name):
    return SimpleNamespace(
        twin_id=twin_id,
        version_number=1,
        content_hash="c" * 64,
        profile=SimpleNamespace(name=name),
    )


TWINS = (twin(FIRST_TWIN, "Hotel Receptionist Twin"), twin(SECOND_TWIN, "Night Auditor Twin"))


class CurrentTwins:
    def __init__(self, twins, session, *, owner_user_id):
        self.twins = twins
        self.owner_user_id = owner_user_id

    async def list_current(self, *, project_id):
        return self.twins if (project_id, self.owner_user_id) == (PROJECT, OWNER) else ()


class Stored:
    def __init__(self):
        self.sources = []
        self.runs = []


class MemoryCritiques:
    def __init__(self, stored, session, owner_user_id):
        self.stored = stored
        self.owner_user_id = owner_user_id

    def _owned(self, item, project_id):
        return (item.project_id, item.owner_user_id) == (project_id, self.owner_user_id)

    def _found(self, project_id, source_id):
        return next(
            (
                (source, contents)
                for source, contents in self.stored.sources
                if source.id == source_id and self._owned(source, project_id)
            ),
            (None, {}),
        )

    async def create_source(self, source, contents):
        if not self._owned(source, PROJECT):
            return DesignCritiqueWriteStatus.PROJECT_NOT_FOUND
        self.stored.sources.append((source, dict(contents)))
        return DesignCritiqueWriteStatus.WRITTEN

    async def source(self, project_id, source_id):
        return self._found(project_id, source_id)[0]

    async def sources(self, project_id, limit=50):
        found = [item for item, _ in reversed(self.stored.sources) if self._owned(item, project_id)]
        return tuple(found[:limit])

    async def shot(self, project_id, source_id, code):
        source, contents = self._found(project_id, source_id)
        shots = () if source is None else source.shots
        found = next((item for item in shots if item.code == code), None)
        return None if found is None else (found.media_type, contents[code])

    async def create_run(self, run):
        self.stored.runs.append(run)
        return DesignCritiqueWriteStatus.WRITTEN

    async def runs(self, project_id, limit=50):
        found = [run for run in reversed(self.stored.runs) if self._owned(run, project_id)]
        return tuple(found[:limit])


def sections_of(state):
    async def current(*, owner_user_id, project_id):
        if project_id != PROJECT:
            raise SectionsFailure("PROJECT_NOT_FOUND")
        return SimpleNamespace(
            section=lambda stage: SimpleNamespace(
                state=state if stage is ProjectStage.USER_TWINS else SectionState.FINE
            )
        )

    return SimpleNamespace(current=current)


def projects(description=BRIEF):
    async def get(*, project_id, owner_user_id):
        return SimpleNamespace(display_name="Front desk") if project_id == PROJECT else None

    async def current_brief(*, project_id, owner_user_id):
        return SimpleNamespace(brief=SimpleNamespace(description=description))

    return SimpleNamespace(get=get, current_brief=current_brief)


def priced(cost):
    snapshot = {"success": {"usage": {"cost_microusd": cost}}, "failure": None}
    return SimpleNamespace(success=snapshot["success"], to_snapshot=lambda: snapshot)


class Critic(loop.FakeGenerator):
    def __init__(self, *outcomes, cost=PRICE, provider_kind=CLAUDE_CODE):
        super().__init__(*outcomes, provider_kind=provider_kind)
        self.cost = cost

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        await begin_model_generation(SimpleNamespace(request_id=uuid4(), content_hash="d" * 64))
        await retain_provider_result(priced(self.cost))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return kwargs["output_type"].model_validate(outcome)


def finding(anchor, severity="major"):
    return {
        "anchor": anchor,
        "concern": "The search button is hard to find.",
        "grounds": "At a busy desk I lose time looking for the search.",
        "profile_keys": ["user_twin.role"],
        "quality_criterion": "comprehensibility",
        "recommended_action": "Make the search button larger and darker.",
        "self_confidence": 0.7,
        "severity": severity,
    }


def opinion(*findings):
    return {
        "assessment": "The page mostly works for me.",
        "evidence_gaps": [],
        "findings": list(findings),
        "unable_to_assess": False,
    }


INCONSISTENT = {
    **opinion(finding("SCR-001")),
    "evidence_gaps": ["Nothing to judge."],
    "unable_to_assess": True,
}


def runtime(
    monkeypatch,
    *,
    generator=None,
    evidence=None,
    twins=TWINS,
    state=SectionState.FINE,
    project_service=None,
):
    stored = Stored()
    monkeypatch.setattr(
        design_critique, "SqlAlchemyDesignCritiqueRepository", partial(MemoryCritiques, stored)
    )
    monkeypatch.setattr(
        design_critique, "SqlAlchemyUserTwinVersionRepository", partial(CurrentTwins, twins)
    )
    monkeypatch.setattr(design_critique, "EvaluationUserTwinProfile", loop.ObservedProfile)
    real = (
        None
        if generator is None
        else SimpleNamespace(
            user_modeling=SimpleNamespace(proposal_port=SimpleNamespace(generator=generator))
        )
    )
    return SimpleNamespace(
        database_runtime=SimpleNamespace(session_factory=loop.FakeSession),
        sections_service=sections_of(state),
        project_service=project_service,
        proposal_evidence_store=evidence,
        real_model_runtime=real,
        stored=stored,
    )


def application_of(state):
    application = FastAPI()
    application.state.application_runtime = state
    application.add_exception_handler(RequestValidationError, request_validation_error)
    application.include_router(design_critique.create_design_critique_router())
    application.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=OWNER)
    return application


def client_of(state):
    return TestClient(application_of(state))


def upload(client, *shots, path=SOURCES, **fields):
    return client.post(path, files=[("shots", shot) for shot in shots], data=fields)


def web_page(client):
    answer = upload(
        client,
        picture("booking-1440.png", WIDE),
        picture("booking-390.jpg", NARROW, "image/jpeg"),
        kind="WEB_PAGE",
        url=ADDRESS,
        page=json.dumps(PAGE),
        viewport_widths=json.dumps([1440, 390]),
    )
    assert answer.status_code == 201, answer.json()
    return answer.json()["source"]


def stored_source(state):
    answer = upload(client_of(state), picture())
    assert answer.status_code == 201, answer.json()
    return UUID(answer.json()["source"]["id"])


def critique(state, source_id, locale="en-US"):
    body = DesignCritiqueRequest(source_id=source_id, locale=locale)
    return asyncio.run(
        DesignCritiqueApplication(state).critique(
            owner_user_id=OWNER, project_id=PROJECT, body=body
        )
    )


def refused(code, status=422):
    return status, {"detail": {"code": code}}


def test_an_uploaded_image_becomes_a_source_kept_without_its_bytes(monkeypatch):
    state = runtime(monkeypatch)
    client = client_of(state)
    answer = upload(client, picture(media_type="application/octet-stream"))
    assert answer.status_code == 201
    [(source, contents)] = state.stored.sources
    assert answer.json() == {"source": source.to_snapshot()}
    snapshot = answer.json()["source"]
    assert (snapshot["kind"], snapshot["title"], snapshot["url"], snapshot["page"]) == (
        "IMAGE",
        "checkout-sketch",
        None,
        None,
    )
    assert snapshot["shots"] == [
        {
            "code": "SCR-001",
            "media_type": "image/png",
            "byte_size": len(PICTURE),
            "sha256": hashlib.sha256(PICTURE).hexdigest(),
            "width": 120,
            "height": 260,
            "viewport_width": None,
        }
    ]
    assert (source.project_id, source.owner_user_id, contents) == (
        PROJECT,
        OWNER,
        {"SCR-001": PICTURE},
    )
    assert client.get(SOURCES).json() == {"items": [snapshot]}
    shot = client.get(f"{SOURCES}/{source.id}/shots/SCR-001")
    assert (shot.status_code, shot.content) == (200, PICTURE)
    assert shot.headers["content-type"] == "image/png"
    assert shot.headers["cache-control"] == "private, max-age=0"


def test_a_captured_page_keeps_its_two_widths_its_address_and_its_text(monkeypatch):
    state = runtime(monkeypatch)
    client = client_of(state)
    snapshot = web_page(client)
    assert (snapshot["kind"], snapshot["title"], snapshot["url"], snapshot["page"]) == (
        "WEB_PAGE",
        "Hotel booking page",
        ADDRESS,
        PAGE,
    )
    assert [
        (item["code"], item["media_type"], item["width"], item["height"], item["viewport_width"])
        for item in snapshot["shots"]
    ] == [("SCR-001", "image/png", 144, 90, 1440), ("SCR-002", "image/jpeg", 39, 84, 390)]
    narrow = client.get(f"{SOURCES}/{snapshot['id']}/shots/SCR-002")
    assert (narrow.content, narrow.headers["content-type"]) == (NARROW, "image/jpeg")
    second = upload(client, picture(), title="Checkout")
    assert client.get(SOURCES).json() == {"items": [second.json()["source"], snapshot]}


@pytest.mark.parametrize(
    ("shots", "fields", "title"),
    [
        ((picture(),), {"title": "  Il  mio\tcheckout "}, "Il mio checkout"),
        ((picture("photo.final.jpg"),), {}, "photo.final"),
        ((picture(".png"),), {}, "IMAGE"),
        ((picture(),), {"kind": "WEB_PAGE", "url": ADDRESS}, "example.com"),
        (
            (picture(),),
            {"kind": "WEB_PAGE", "url": ADDRESS, "page": json.dumps({**PAGE, "title": ""})},
            "example.com",
        ),
    ],
)
def test_a_source_without_a_title_takes_the_page_the_address_or_the_file_name(
    monkeypatch, shots, fields, title
):
    answer = upload(client_of(runtime(monkeypatch)), *shots, **fields)
    assert answer.status_code == 201, answer.json()
    assert answer.json()["source"]["title"] == title


ONE = (picture(),)


@pytest.mark.parametrize(
    ("shots", "fields", "expected"),
    [
        pytest.param(
            (picture("animation.gif", GIF, "image/gif"),),
            {},
            refused("DESIGN_CRITIQUE_IMAGE_INVALID"),
            id="gif",
        ),
        pytest.param(
            (picture("dot.png", png(8, 8)),),
            {},
            refused("DESIGN_CRITIQUE_IMAGE_INVALID"),
            id="tiny",
        ),
        pytest.param(
            (picture("strip.png", png(8001, 16)),),
            {},
            refused("DESIGN_CRITIQUE_IMAGE_TOO_LARGE", 413),
            id="side",
        ),
        pytest.param(
            (picture("heavy.png", PICTURE + bytes(MAX_SHOT_BYTES)),),
            {},
            refused("DESIGN_CRITIQUE_IMAGE_TOO_LARGE", 413),
            id="bytes",
        ),
        pytest.param((), {}, refused("DESIGN_CRITIQUE_SOURCE_INVALID"), id="none"),
        pytest.param(ONE * 3, {}, refused("DESIGN_CRITIQUE_SOURCE_INVALID"), id="three"),
        pytest.param(ONE, {"kind": "VIDEO"}, refused("DESIGN_CRITIQUE_SOURCE_INVALID"), id="kind"),
        pytest.param(
            ONE, {"title": "x" * 201}, refused("DESIGN_CRITIQUE_SOURCE_INVALID"), id="title"
        ),
        pytest.param(
            ONE, {"url": ADDRESS}, refused("DESIGN_CRITIQUE_SOURCE_INVALID"), id="image-url"
        ),
        pytest.param(
            ONE, {"kind": "WEB_PAGE"}, refused("DESIGN_CRITIQUE_URL_INVALID"), id="no-url"
        ),
        pytest.param(
            ONE,
            {"kind": "WEB_PAGE", "url": "ftp://example.com/page"},
            refused("DESIGN_CRITIQUE_URL_INVALID"),
            id="scheme",
        ),
        pytest.param(
            ONE,
            {"kind": "WEB_PAGE", "url": ADDRESS, "page": "{not json"},
            refused("DESIGN_CRITIQUE_PAGE_INVALID"),
            id="page-json",
        ),
        pytest.param(
            ONE,
            {"kind": "WEB_PAGE", "url": ADDRESS, "page": json.dumps({**PAGE, "title": 7})},
            refused("DESIGN_CRITIQUE_PAGE_INVALID"),
            id="page-shape",
        ),
        pytest.param(
            ONE,
            {"kind": "WEB_PAGE", "url": ADDRESS, "page": " " * (MAX_PAGE_CHARACTERS + 1)},
            refused("DESIGN_CRITIQUE_PAGE_INVALID"),
            id="page-length",
        ),
        pytest.param(
            ONE,
            {"viewport_widths": "[1440, 390]"},
            refused("DESIGN_CRITIQUE_SOURCE_INVALID"),
            id="widths-count",
        ),
        pytest.param(
            ONE,
            {"viewport_widths": "wide"},
            refused("DESIGN_CRITIQUE_SOURCE_INVALID"),
            id="widths-json",
        ),
        pytest.param(
            ONE,
            {"viewport_widths": "[8]"},
            refused("DESIGN_CRITIQUE_SOURCE_INVALID"),
            id="widths-range",
        ),
    ],
)
def test_a_source_outside_the_contract_is_refused_with_its_code(
    monkeypatch, shots, fields, expected
):
    state = runtime(monkeypatch)
    answer = upload(client_of(state), *shots, **fields)
    assert (answer.status_code, answer.json()) == expected
    assert state.stored.sources == []


@pytest.mark.parametrize(
    ("state", "twins", "project", "expected"),
    [
        (SectionState.IN_PROGRESS, TWINS, PROJECT, refused("DESIGN_CRITIQUE_TWINS_REQUIRED", 409)),
        (SectionState.TO_UPDATE, TWINS, PROJECT, refused("DESIGN_CRITIQUE_TWINS_REQUIRED", 409)),
        (SectionState.FINE, (), PROJECT, refused("DESIGN_CRITIQUE_TWINS_REQUIRED", 409)),
        (SectionState.FINE, TWINS, OTHER_PROJECT, refused("PROJECT_NOT_FOUND", 404)),
    ],
)
def test_a_source_needs_the_approved_twins_before_its_fields_are_checked(
    monkeypatch, state, twins, project, expected
):
    prepared = runtime(monkeypatch, twins=twins, state=state)
    gif = picture("animation.gif", GIF, "image/gif")
    path = f"/projects/{project}/design/critiques/sources"
    answer = upload(client_of(prepared), gif, gif, gif, path=path, kind="VIDEO")
    assert (answer.status_code, answer.json()) == expected
    assert prepared.stored.sources == []


def test_twins_with_an_update_available_can_still_receive_a_source(monkeypatch):
    state = runtime(monkeypatch, state=SectionState.UPDATE_AVAILABLE)
    assert upload(client_of(state), picture()).status_code == 201


def test_a_declared_length_beyond_the_limit_is_refused_before_the_form_is_read(monkeypatch):
    state = runtime(monkeypatch)
    application = application_of(state)
    received = []

    async def counted(scope: Scope, receive: Receive, send: Send) -> None:
        async def counted_receive() -> Message:
            message = await receive()
            received.append(message["type"])
            return message

        await application(scope, counted_receive, send)

    api = TestClient(counted)
    files = [("shots", picture())]
    too_long = api.post(SOURCES, files=files, headers={"Content-Length": str(MAX_UPLOAD_BYTES + 1)})
    unread = list(received)
    accepted = api.post(SOURCES, files=files, headers={"Content-Length": str(MAX_UPLOAD_BYTES)})
    assert MAX_UPLOAD_BYTES == 2 * MAX_SHOT_BYTES + 1024 * 1024
    assert (too_long.status_code, too_long.json()) == refused(
        "DESIGN_CRITIQUE_IMAGE_TOO_LARGE", 413
    )
    assert unread == []
    assert accepted.status_code == 201
    assert len(state.stored.sources) == 1


def test_an_unknown_source_or_screen_is_not_found(monkeypatch):
    state = runtime(monkeypatch)
    client = client_of(state)
    source = upload(client, picture()).json()["source"]
    for path in (
        f"{SOURCES}/{uuid4()}/shots/SCR-001",
        f"{SOURCES}/{source['id']}/shots/SCR-002",
        f"/projects/{OTHER_PROJECT}/design/critiques/sources/{source['id']}/shots/SCR-001",
    ):
        answer = client.get(path)
        assert (answer.status_code, answer.json()) == refused(
            "DESIGN_CRITIQUE_SOURCE_NOT_FOUND", 404
        )
    assert client.get(f"/projects/{OTHER_PROJECT}/design/critiques/sources").json() == {"items": []}


def test_the_twins_judge_a_captured_page_from_its_screenshots(monkeypatch):
    generator = Critic(
        opinion(finding("SCR-001", "major"), finding("SCR-002", "minor")),
        opinion(finding("SCR-001", "observation")),
    )
    evidence = loop.MemoryEvidence()
    state = runtime(monkeypatch, generator=generator, evidence=evidence, project_service=projects())
    client = client_of(state)
    snapshot = web_page(client)
    answer = client.post(PATH, json={"source_id": snapshot["id"], "locale": "en-US"})
    assert answer.status_code == 201, answer.json()
    [run] = state.stored.runs
    body = answer.json()
    assert body == {"status": "DESIGN_CRITIQUE_RECORDED", "run": run_payload(run, 2 * PRICE)}
    payload = body["run"]
    assert payload["source"] == snapshot
    assert payload["twins"] == [
        {"twin_id": str(FIRST_TWIN), "version_number": 1, "name": "Hotel Receptionist Twin"},
        {"twin_id": str(SECOND_TWIN), "version_number": 1, "name": "Night Auditor Twin"},
    ]
    assert payload["verdicts"] == [
        {"twin_id": str(FIRST_TWIN), "anchor_key": "SCR-001", "verdict": "BLOCKS"},
        {"twin_id": str(FIRST_TWIN), "anchor_key": "SCR-002", "verdict": "SLOWS"},
        {"twin_id": str(SECOND_TWIN), "anchor_key": "SCR-001", "verdict": "WORKS"},
        {"twin_id": str(SECOND_TWIN), "anchor_key": "SCR-002", "verdict": "WORKS"},
    ]
    assert isinstance(payload["duration_seconds"], float)
    assert payload["duration_seconds"] >= 0
    assert payload["cost_microusd"] == 2 * PRICE
    assert sorted((item["kind"], item["location"]) for item in payload["bundle"]["artifacts"]) == [
        ("DOM_SNAPSHOT", "critique/page.json"),
        ("SCREENSHOT", "critique/SCR-001.png"),
        ("SCREENSHOT", "critique/SCR-002.jpg"),
    ]
    source = state.stored.sources[0][0]
    anchors = critique_anchors(source, "en")
    assert [item["location"] for item in payload["responses"][0]["findings"]] == [
        anchors["SCR-001"],
        anchors["SCR-002"],
    ]
    assert [call["task"] for call in generator.calls] == [TWIN_REVIEW_TASK] * 2
    assert [call["context"]["user_twin"]["twin_id"] for call in generator.calls] == [
        str(FIRST_TWIN),
        str(SECOND_TWIN),
    ]
    for call in generator.calls:
        assert call["context"]["purpose"] == CRITIQUE_PURPOSE
        assert call["context"]["design"] == critique_source_view(source, "en")
        assert call["context"]["project"] == {"name": "Front desk", "brief": BRIEF}
        assert [(item.name, item.media_type, item.content) for item in call["attachments"]] == [
            ("screenshot-001.png", "image/png", WIDE),
            ("screenshot-002.jpg", "image/jpeg", NARROW),
        ]
    assert evidence.kinds() == [
        (0, "PROVIDER_RESULT"),
        (0, "ADAPTER_ACCEPTED"),
        (0, "APPLICATION_RESULT"),
        (1, "PROVIDER_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert [event for _, kind, event in evidence.events if kind == "APPLICATION_RESULT"] == [
        {"status": "TWIN_REVIEWED", "evaluation_run_id": str(run.id)},
        {"status": "DESIGN_CRITIQUE_RECORDED", "issue": None},
    ]
    assert client.get(PATH).json() == {"items": [{**payload, "cost_microusd": 0}]}


def test_an_uploaded_image_is_judged_in_italian_on_its_only_screenshot(monkeypatch):
    generator = Critic(opinion(finding("SCR-001", "moderate")), opinion())
    state = runtime(monkeypatch, generator=generator, evidence=loop.MemoryEvidence())
    client = client_of(state)
    snapshot = upload(client, picture()).json()["source"]
    answer = client.post(PATH, json={"source_id": snapshot["id"]})
    assert answer.status_code == 201, answer.json()
    run = answer.json()["run"]
    scenario = run["bundle"]["scenario"]
    assert (scenario["locale"], scenario["name"], scenario["task"]) == (
        "it-IT",
        "checkout-sketch",
        "Capire questo design e usarlo per il tuo scopo abituale con un prodotto come questo",
    )
    assert [item["kind"] for item in run["bundle"]["artifacts"]] == ["SCREENSHOT"]
    assert run["responses"][0]["findings"][0]["location"] == (
        "SCR-001 Immagine fornita · 120 x 260 px"
    )
    assert run["verdicts"] == [
        {"twin_id": str(FIRST_TWIN), "anchor_key": "SCR-001", "verdict": "SLOWS"},
        {"twin_id": str(SECOND_TWIN), "anchor_key": "SCR-001", "verdict": "WORKS"},
    ]
    assert [len(call["attachments"]) for call in generator.calls] == [1, 1]
    assert all("project" not in call["context"] for call in generator.calls)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            "  A booking tool \n for hotels. ",
            {"name": "Front desk", "brief": "A booking tool for hotels."},
        ),
        ("word " * 600, {"name": "Front desk", "brief": ("word " * 400).strip()}),
        (None, {"name": "Front desk"}),
    ],
)
def test_the_twins_hear_what_the_owner_is_building_from_the_current_brief(
    monkeypatch, description, expected
):
    generator = Critic(opinion())
    state = runtime(
        monkeypatch,
        generator=generator,
        evidence=loop.MemoryEvidence(),
        twins=TWINS[:1],
        project_service=projects(description),
    )
    critique(state, stored_source(state))
    [call] = generator.calls
    assert call["context"]["project"] == expected
    assert len(call["context"]["project"].get("brief", "")) <= 2000


def test_an_invalid_critique_is_asked_once_more_and_both_answers_are_counted(monkeypatch):
    generator = Critic(INCONSISTENT, opinion(finding("SCR-001", "critical")))
    evidence = loop.MemoryEvidence()
    state = runtime(monkeypatch, generator=generator, evidence=evidence, twins=TWINS[:1])
    result = critique(state, stored_source(state))
    assert result.status is DesignCritiqueStatus.RECORDED
    assert result.cost_microusd == 2 * PRICE
    assert len(generator.calls) == 2
    assert state.stored.runs == [result.run]
    assert [item["verdict"] for item in run_payload(result.run)["verdicts"]] == ["BLOCKS"]
    assert evidence.kinds() == [
        (0, "PROVIDER_RESULT"),
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "PROVIDER_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.events[2][2] == {
        "status": "TWIN_REVIEW_REJECTED",
        "evaluation_run_id": str(result.run.id),
    }


@pytest.mark.parametrize(
    ("outcomes", "code", "calls"),
    [
        ((INCONSISTENT, INCONSISTENT), INVALID_CRITIQUE_OUTPUT, 2),
        (
            (ProposalGenerationError("RESPONSE_SCHEMA_ERROR"),) * 2,
            "RESPONSE_SCHEMA_ERROR",
            2,
        ),
        ((ProposalGenerationError("TIMEOUT"), opinion()), "TIMEOUT", 1),
        ((ProposalGenerationError("IDENTITY_MISMATCH"), opinion()), "IDENTITY_MISMATCH", 1),
    ],
)
def test_a_critique_that_keeps_failing_records_nothing(monkeypatch, outcomes, code, calls):
    generator = Critic(*outcomes)
    evidence = loop.MemoryEvidence()
    state = runtime(monkeypatch, generator=generator, evidence=evidence, twins=TWINS[:1])
    source_id = stored_source(state)
    with pytest.raises(ProposalGenerationError) as failure:
        critique(state, source_id)
    assert failure.value.code == code
    assert len(generator.calls) == calls
    assert state.stored.runs == []
    assert evidence.events[-1][2] == {"status": "FAILED", "code": code}


def test_a_generator_that_refuses_the_screenshots_answers_that_the_provider_is_unsupported(
    monkeypatch,
):
    generator = Critic(ProposalGenerationError("ATTACHMENTS_UNSUPPORTED"), opinion())
    state = runtime(monkeypatch, generator=generator, evidence=loop.MemoryEvidence())
    source_id = stored_source(state)
    with pytest.raises(HTTPException) as failure:
        critique(state, source_id)
    assert (failure.value.status_code, failure.value.detail) == (
        503,
        {"code": "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED"},
    )
    assert len(generator.calls) == 1
    assert state.stored.runs == []


@pytest.mark.parametrize(
    ("provider_kind", "generator", "evidence", "code"),
    [
        (
            StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
            True,
            True,
            "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED",
        ),
        (
            StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            True,
            True,
            "DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED",
        ),
        (CLAUDE_CODE, False, True, "DESIGN_REVIEWER_NOT_CONFIGURED"),
        (CLAUDE_CODE, True, False, "DESIGN_REVIEWER_NOT_CONFIGURED"),
    ],
)
def test_the_critique_needs_the_claude_code_route_of_the_twins(
    monkeypatch, provider_kind, generator, evidence, code
):
    critic = Critic(opinion(), opinion(), provider_kind=provider_kind)
    state = runtime(
        monkeypatch,
        generator=critic if generator else None,
        evidence=loop.MemoryEvidence() if evidence else None,
    )
    client = client_of(state)
    source = upload(client, picture()).json()["source"]
    answer = client.post(PATH, json={"source_id": source["id"]})
    assert (answer.status_code, answer.json()) == refused(code, 503)
    assert critic.calls == []
    assert state.stored.runs == []


def test_the_critique_follows_the_route_of_its_own_purpose(monkeypatch):
    general = loop.FakeGenerator(opinion())
    claude = Critic(opinion(finding("SCR-001", "minor")), cost=0)
    router = RoutingProposalGenerator(
        {"general": general, "critique": claude},
        ModelRoutes(default="general", purposes={CRITIQUE_PURPOSE: "critique"}),
    )
    state = runtime(monkeypatch, generator=router, evidence=loop.MemoryEvidence(), twins=TWINS[:1])
    result = critique(state, stored_source(state))
    assert general.calls == []
    assert len(claude.calls) == 1
    assert result.cost_microusd == 0
    assert result.run.evaluator.model_config_ref == loop.MODEL_HASH


def test_a_critique_needs_a_known_source_and_approved_twins(monkeypatch):
    generator = Critic(opinion(), opinion())
    state = runtime(monkeypatch, generator=generator, evidence=loop.MemoryEvidence())
    client = client_of(state)
    unknown = client.post(PATH, json={"source_id": str(uuid4())})
    assert (unknown.status_code, unknown.json()) == refused("DESIGN_CRITIQUE_SOURCE_NOT_FOUND", 404)
    source = upload(client, picture()).json()["source"]
    state.sections_service = sections_of(SectionState.TO_UPDATE)
    stale = client.post(PATH, json={"source_id": source["id"]})
    assert (stale.status_code, stale.json()) == refused("DESIGN_CRITIQUE_TWINS_REQUIRED", 409)
    assert generator.calls == []
    assert state.stored.runs == []


def test_a_twin_without_known_observations_cannot_judge_the_design(monkeypatch):
    generator = Critic(opinion(), opinion())
    state = runtime(monkeypatch, generator=generator, evidence=loop.MemoryEvidence())
    monkeypatch.setattr(design_critique, "EvaluationUserTwinProfile", loop.StubProfile)
    client = client_of(state)
    source = upload(client, picture()).json()["source"]
    answer = client.post(PATH, json={"source_id": source["id"]})
    assert (answer.status_code, answer.json()) == (
        502,
        {
            "detail": {
                "code": "DESIGN_CRITIQUE_FAILED",
                "reason": "twin review requires at least one known profile observation",
            }
        },
    )
    assert generator.calls == []
    assert state.stored.runs == []


@pytest.mark.parametrize(
    ("body", "location"),
    [
        ({}, ["body", "source_id"]),
        ({"source_id": "not-a-source"}, ["body", "source_id"]),
        ({"source_id": str(UUID(int=7)), "locale": "it IT"}, ["body", "locale"]),
        ({"source_id": str(UUID(int=7)), "locale": "i"}, ["body", "locale"]),
        ({"source_id": str(UUID(int=7)), "kind": "IMAGE"}, ["body", "kind"]),
    ],
)
def test_an_invalid_request_body_is_refused_before_any_work(monkeypatch, body, location):
    generator = Critic(opinion())
    state = runtime(monkeypatch, generator=generator, evidence=loop.MemoryEvidence())
    answer = client_of(state).post(PATH, json=body)
    assert answer.status_code == 422
    assert answer.json()["detail"] == "invalid_request"
    assert [item["loc"] for item in answer.json()["errors"]] == [location]
    assert generator.calls == []


def test_the_request_asks_for_an_italian_critique_by_default():
    request = DesignCritiqueRequest(source_id=UUID(int=7))
    assert (request.source_id, request.locale) == (UUID(int=7), "it-IT")


def test_the_router_serves_the_five_routes_of_the_critique():
    router = design_critique.create_design_critique_router()
    assert sorted((method, route.path) for route in router.routes for method in route.methods) == [
        ("GET", "/projects/{project_id}/design/critiques"),
        ("GET", "/projects/{project_id}/design/critiques/sources"),
        ("GET", "/projects/{project_id}/design/critiques/sources/{source_id}/shots/{code}"),
        ("POST", "/projects/{project_id}/design/critiques"),
        ("POST", "/projects/{project_id}/design/critiques/sources"),
    ]
