from __future__ import annotations

import hashlib
import struct
import urllib.error
import urllib.request
import uuid
import zlib
from collections.abc import Mapping, Sequence

import pytest

from orchestwin.artifacts.design_evaluation import synthetic_finding_from_snapshot
from orchestwin.cli.api import design_critique as critique_api

from .support.fake_studio import (
    COSTS,
    CRITIQUE_FIELDS,
    CRITIQUE_TEXTS,
    ITERATION_FIELDS,
    PREFIX,
    FakeProject,
    FakeStudio,
)
from .test_fake_studio_routes import EMAIL, _Client, invalid, signed

ADDRESS = "https://shop.example.test/checkout"
PAGE = {
    "url": ADDRESS,
    "title": "Checkout",
    "text": "Basket Pay now",
    "hidden_text": "",
    "elements": [
        {"index": 0, "role": "button", "name": "Pay now", "value": None, "state": None},
        {"index": 1, "role": "link", "name": "Basket", "value": None, "state": None},
    ],
}
GIF = b"GIF89a" + bytes(40)
SOURCES = "/design/critiques/sources"
CRITIQUES = "/design/critiques"
NOT_FOUND = {"detail": {"code": "DESIGN_CRITIQUE_SOURCE_NOT_FOUND"}}


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x30\x60\x90" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def jpeg(width: int, height: int) -> bytes:
    application = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = (
        b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return (
        b"\xff\xd8\xff\xe0"
        + (len(application) + 2).to_bytes(2, "big")
        + application
        + b"\xff\xc0"
        + (len(frame) + 2).to_bytes(2, "big")
        + frame
        + b"\xff\xd9"
    )


WIDE = png(144, 90)
NARROW = jpeg(39, 84)


def website(
    client: _Client, project: FakeProject, *, title: str | None = None
) -> tuple[int, object]:
    content_type, body = critique_api.source_form(
        kind=critique_api.WEB_PAGE,
        title=title,
        url=ADDRESS,
        page=PAGE,
        shots=[
            ("screenshot-1440.png", "image/png", WIDE, 1440),
            ("screenshot-390.png", "image/jpeg", NARROW, 390),
        ],
    )
    return client.call(
        "POST", f"/projects/{project.id}{SOURCES}", content=body, content_type=content_type
    )


def upload(
    client: _Client,
    project: FakeProject,
    fields: Mapping[str, str],
    files: Sequence[tuple[str, str, bytes]],
) -> tuple[int, object]:
    content_type, body = critique_api.form(fields, files)
    return client.call(
        "POST", f"/projects/{project.id}{SOURCES}", content=body, content_type=content_type
    )


def fetch(studio: FakeStudio, client: _Client, path: str) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        studio.address + PREFIX + path, headers={"Authorization": f"Bearer {client.token}"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            headers = {name.lower(): value for name, value in response.headers.items()}
            return response.status, headers, response.read()
    except urllib.error.HTTPError as error:
        with error:
            headers = {name.lower(): value for name, value in error.headers.items()}
            return error.code, headers, error.read()


def severity_verdict(severities: Sequence[str]) -> str:
    if {"critical", "major"} & set(severities):
        return "BLOCKS"
    if {"moderate", "minor"} & set(severities):
        return "SLOWS"
    return "WORKS"


def test_the_fields_of_the_critique_and_of_the_iteration_follow_the_contract() -> None:
    assert CRITIQUE_FIELDS == ("source_id", "locale")
    assert ITERATION_FIELDS[-1] == "critique_source_id"
    assert critique_api.critiques_path("p") == "/projects/p/design/critiques"
    assert critique_api.sources_path("p") == "/projects/p/design/critiques/sources"
    assert critique_api.shot_path("p", "s", "SCR-002") == (
        "/projects/p/design/critiques/sources/s/shots/SCR-002"
    )


def test_a_website_with_two_screenshots_is_stored_and_its_shots_are_served() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        base = f"/projects/{project.id}"
        status, created = website(client, project)
        source = created["source"]
        _, listed = client.call("GET", base + SOURCES)
        wide = fetch(studio, client, critique_api.shot_path(project.id, source["id"], "SCR-001"))
        narrow = fetch(studio, client, critique_api.shot_path(project.id, source["id"], "SCR-002"))
        missing = fetch(studio, client, critique_api.shot_path(project.id, source["id"], "SCR-003"))
        unknown = fetch(
            studio, client, critique_api.shot_path(project.id, str(uuid.uuid4()), "SCR-001")
        )
        stored = list(project.critique_sources)
        assert studio.errors == []

    assert status == 201, created
    assert list(source) == [
        "schema_version",
        "id",
        "project_id",
        "owner_user_id",
        "kind",
        "title",
        "url",
        "page",
        "shots",
        "created_at",
        "content_hash",
    ]
    assert (source["project_id"], source["kind"], source["title"], source["url"]) == (
        project.id,
        "WEB_PAGE",
        "Checkout",
        ADDRESS,
    )
    assert source["page"] == PAGE
    assert source["shots"] == [
        {
            "code": "SCR-001",
            "media_type": "image/png",
            "byte_size": len(WIDE),
            "sha256": hashlib.sha256(WIDE).hexdigest(),
            "width": 144,
            "height": 90,
            "viewport_width": 1440,
        },
        {
            "code": "SCR-002",
            "media_type": "image/jpeg",
            "byte_size": len(NARROW),
            "sha256": hashlib.sha256(NARROW).hexdigest(),
            "width": 39,
            "height": 84,
            "viewport_width": 390,
        },
    ]
    assert len(source["content_hash"]) == 64
    assert listed == {"items": [source]}
    assert stored == [source]
    assert wide[0] == 200
    assert (wide[1]["content-type"], wide[1]["cache-control"], wide[2]) == (
        "image/png",
        "private, max-age=0",
        WIDE,
    )
    assert (narrow[0], narrow[1]["content-type"], narrow[2]) == (200, "image/jpeg", NARROW)
    for answer in (missing, unknown):
        assert answer[0] == 404
        assert b"DESIGN_CRITIQUE_SOURCE_NOT_FOUND" in answer[2]


def test_an_image_takes_its_title_from_the_file_or_keeps_the_one_given() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        status, named = upload(
            client, project, {"kind": "IMAGE"}, [("basket.png", "image/png", WIDE)]
        )
        again, given = upload(
            client,
            project,
            {"title": "  Cassa   più rapida "},
            [("basket.png", "image/png", WIDE)],
        )
        stored = [item["title"] for item in project.critique_sources]
        assert studio.errors == []

    assert (status, again) == (201, 201)
    first, second = named["source"], given["source"]
    assert (first["kind"], first["title"], first["url"], first["page"]) == (
        "IMAGE",
        "basket",
        None,
        None,
    )
    assert first["shots"][0]["viewport_width"] is None
    assert (second["kind"], second["title"]) == ("IMAGE", "Cassa più rapida")
    assert stored == ["Cassa più rapida", "basket"]


@pytest.mark.parametrize(
    ("fields", "files", "status", "code"),
    [
        (
            {"kind": "IMAGE"},
            [("big.png", "image/png", png(16, 16) + bytes(5 * 1024 * 1024))],
            413,
            "DESIGN_CRITIQUE_IMAGE_TOO_LARGE",
        ),
        ({"kind": "IMAGE"}, [("anim.gif", "image/gif", GIF)], 422, "DESIGN_CRITIQUE_IMAGE_INVALID"),
        (
            {"kind": "IMAGE"},
            [("tiny.png", "image/png", png(8, 8))],
            422,
            "DESIGN_CRITIQUE_IMAGE_INVALID",
        ),
        (
            {"kind": "IMAGE"},
            [("long.png", "image/png", png(8001, 16))],
            413,
            "DESIGN_CRITIQUE_IMAGE_TOO_LARGE",
        ),
        ({"kind": "IMAGE"}, [], 422, "DESIGN_CRITIQUE_SOURCE_INVALID"),
        (
            {"kind": "IMAGE"},
            [("a.png", "image/png", WIDE)] * 3,
            422,
            "DESIGN_CRITIQUE_SOURCE_INVALID",
        ),
        ({"kind": "VIDEO"}, [("a.png", "image/png", WIDE)], 422, "DESIGN_CRITIQUE_SOURCE_INVALID"),
        (
            {"kind": "IMAGE", "url": ADDRESS},
            [("a.png", "image/png", WIDE)],
            422,
            "DESIGN_CRITIQUE_SOURCE_INVALID",
        ),
        (
            {"kind": "IMAGE", "title": "x" * 201},
            [("a.png", "image/png", WIDE)],
            422,
            "DESIGN_CRITIQUE_SOURCE_INVALID",
        ),
        (
            {"kind": "IMAGE", "viewport_widths": "[1440, 390]"},
            [("a.png", "image/png", WIDE)],
            422,
            "DESIGN_CRITIQUE_SOURCE_INVALID",
        ),
        ({"kind": "WEB_PAGE"}, [("a.png", "image/png", WIDE)], 422, "DESIGN_CRITIQUE_URL_INVALID"),
        (
            {"kind": "WEB_PAGE", "url": "ftp://shop.example.test/"},
            [("a.png", "image/png", WIDE)],
            422,
            "DESIGN_CRITIQUE_URL_INVALID",
        ),
        (
            {"kind": "WEB_PAGE", "url": "https://"},
            [("a.png", "image/png", WIDE)],
            422,
            "DESIGN_CRITIQUE_URL_INVALID",
        ),
        (
            {"kind": "WEB_PAGE", "url": ADDRESS, "page": "not json"},
            [("a.png", "image/png", WIDE)],
            422,
            "DESIGN_CRITIQUE_PAGE_INVALID",
        ),
        (
            {"kind": "WEB_PAGE", "url": ADDRESS, "page": "[]"},
            [("a.png", "image/png", WIDE)],
            422,
            "DESIGN_CRITIQUE_PAGE_INVALID",
        ),
    ],
    ids=[
        "shot-over-five-megabytes",
        "gif",
        "too-small",
        "too-long",
        "no-shot",
        "three-shots",
        "unknown-kind",
        "image-with-url",
        "long-title",
        "widths-not-matching",
        "page-without-url",
        "ftp-url",
        "url-without-host",
        "page-not-json",
        "page-not-an-object",
    ],
)
def test_uploads_outside_the_contract_are_refused_and_nothing_is_stored(
    fields: dict[str, str], files: list[tuple[str, str, bytes]], status: int, code: str
) -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        answer = upload(client, project, fields, files)
        stored = (list(project.critique_sources), dict(project.critique_shots))
        assert studio.errors == []

    assert answer == (status, {"detail": {"code": code}})
    assert stored == ([], {})


def test_a_request_over_eleven_megabytes_is_refused_before_it_is_read() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        answer = client.call(
            "POST",
            f"/projects/{project.id}{SOURCES}",
            content=bytes(11 * 1024 * 1024 + 1),
            content_type="multipart/form-data; boundary=fake-boundary-not-real",
        )
        stored = list(project.critique_sources)
        assert studio.errors == []

    assert answer == (413, {"detail": {"code": "DESIGN_CRITIQUE_IMAGE_TOO_LARGE"}})
    assert stored == []


def test_without_approved_twins_neither_the_upload_nor_the_critique_starts() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        early = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="team")
        refused = website(client, early)
        ready = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        status, created = website(client, ready)
        ready.seed_perspective_change("SECURITY_REVIEWER")
        states = {item["key"]: item["state"] for item in ready.sections()["sections"]}
        behind = client.call(
            "POST",
            f"/projects/{ready.id}{CRITIQUES}",
            {"source_id": created["source"]["id"], "locale": "it-IT"},
        )
        spent = (ready.spent_microusd, list(ready.critique_runs))
        assert studio.errors == []

    twins_required = {"detail": {"code": "DESIGN_CRITIQUE_TWINS_REQUIRED"}}
    assert refused == (409, twins_required)
    assert status == 201
    assert states["USER_TWINS"] not in ("FINE", "UPDATE_AVAILABLE")
    assert behind == (409, twins_required)
    assert spent == (0, [])


@pytest.mark.parametrize("language", ["it", "en"])
def test_a_critique_gives_one_opinion_per_twin_and_verdicts_from_the_severities(
    language: str,
) -> None:
    with FakeStudio(language=language, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        base = f"/projects/{project.id}"
        _, created = website(client, project)
        source = created["source"]
        before = studio.spent_microusd
        status, answer = client.call(
            "POST", base + CRITIQUES, {"source_id": source["id"], "locale": "en-US"}
        )
        _, listed = client.call("GET", base + CRITIQUES)
        usage = [item for item in project.usage if item["purpose"] == "DESIGN_CRITIQUE"]
        spent = studio.spent_microusd - before
        twins = project.current("twins")["snapshot"]["twin_versions"]
        assert studio.errors == []

    texts = CRITIQUE_TEXTS[language]
    assert status == 201, answer
    assert answer["status"] == "DESIGN_CRITIQUE_RECORDED"
    run = answer["run"]
    assert listed == {"items": [run]}
    assert run["source"] == source
    assert run["project_id"] == project.id
    assert run["twins"] == [
        {
            "twin_id": twin["twin_id"],
            "version_number": twin["version_number"],
            "name": twin["profile"]["name"],
        }
        for twin in twins
    ]
    assert sorted(response["twin_id"] for response in run["responses"]) == sorted(
        twin["twin_id"] for twin in twins
    )
    findings = [finding for response in run["responses"] for finding in response["findings"]]
    assert findings
    for finding in findings:
        assert synthetic_finding_from_snapshot(finding).to_snapshot() == finding
        assert finding["artifact_id"] == source["id"]
        assert finding["anchor_key"] in ("SCR-001", "SCR-002")
        assert finding["location"].startswith(finding["anchor_key"] + " ")
    expected = [
        {
            "twin_id": response["twin_id"],
            "anchor_key": code,
            "verdict": severity_verdict(
                [item["severity"] for item in response["findings"] if item["anchor_key"] == code]
            ),
        }
        for response in run["responses"]
        for code in ("SCR-001", "SCR-002")
    ]
    assert run["verdicts"] == expected
    assert {item["verdict"] for item in run["verdicts"]} == {"BLOCKS", "SLOWS", "WORKS"}
    assert run["cost_microusd"] == spent == 2 * COSTS["DESIGN_CRITIQUE"]
    assert [(item["task"], item["cost_microusd"]) for item in usage] == [
        ("user-twin-evaluation", COSTS["DESIGN_CRITIQUE"])
    ] * 2
    assert run["duration_seconds"] > 0
    assert run["started_at"] < run["completed_at"]
    bundle = run["bundle"]
    assert bundle["workflow_run_id"] == source["id"]
    assert bundle["scenario"]["locale"] == "en-US"
    assert (bundle["scenario"]["task"], bundle["scenario"]["expected_outcomes"]) == (
        texts["task"],
        [texts["outcome"]],
    )
    assert [item["kind"] for item in bundle["artifacts"]] == [
        "SCREENSHOT",
        "SCREENSHOT",
        "DOM_SNAPSHOT",
    ]
    assert any(texts["gap"] in response["evidence_gaps"] for response in run["responses"])


def test_on_the_subscription_the_critique_costs_nothing() -> None:
    with FakeStudio(job_polls=0, billing="SUBSCRIPTION") as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        _, created = upload(client, project, {"kind": "IMAGE"}, [("cart.png", "image/png", WIDE)])
        status, answer = client.call(
            "POST",
            f"/projects/{project.id}{CRITIQUES}",
            {"source_id": created["source"]["id"]},
        )
        assert studio.errors == []

    run = answer["run"]
    assert status == 201
    assert (run["cost_microusd"], studio.spent_microusd, project.usage) == (0, 0, [])
    assert run["bundle"]["scenario"]["locale"] == "it-IT"
    assert {item["anchor_key"] for item in run["verdicts"]} == {"SCR-001"}


def test_a_critique_needs_a_valid_body_a_known_source_and_a_model() -> None:
    with FakeStudio(job_polls=0) as studio, FakeStudio(job_polls=0, hosted=False) as plain:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        path = f"/projects/{project.id}{CRITIQUES}"
        answers = [
            client.call("POST", path, {}),
            client.call("POST", path, {"source_id": "not-a-uuid"}),
            client.call("POST", path, {"source_id": str(uuid.uuid4()), "scope": "all"}),
            client.call("POST", path, {"source_id": str(uuid.uuid4())}),
        ]
        local = signed(plain)
        offline = plain.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        _, created = upload(local, offline, {"kind": "IMAGE"}, [("cart.png", "image/png", WIDE)])
        without_model = local.call(
            "POST", f"/projects/{offline.id}{CRITIQUES}", {"source_id": created["source"]["id"]}
        )
        assert studio.errors == []
        assert plain.errors == []

    assert answers == [
        (422, invalid(["body", "source_id"], "missing")),
        (422, invalid(["body", "source_id"], "uuid_parsing")),
        (422, invalid(["body", "scope"], "extra_forbidden")),
        (404, NOT_FOUND),
    ]
    assert without_model == (503, {"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}})


def test_an_iteration_carries_the_critique_source_and_lists_it() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        _, created = upload(client, project, {"kind": "IMAGE"}, [("cart.png", "image/png", WIDE)])
        source_id = created["source"]["id"]
        current = project.current("design")
        body = {
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "request": "Redraw the mockup like the supplied design",
        }
        unknown = client.call(
            "POST",
            base + "/design/iterations/jobs",
            {**body, "critique_source_id": str(uuid.uuid4())},
        )
        wrong = client.call(
            "POST", base + "/design/iterations/jobs", {**body, "critique_source_id": "cart"}
        )
        status, started = client.call(
            "POST", base + "/design/iterations/jobs", {**body, "critique_source_id": source_id}
        )
        _, job = client.call("GET", f"{base}/design/iterations/jobs/{started['job_id']}")
        plain_status, plain = client.call("POST", base + "/design/iterations/jobs", body)
        client.call("GET", f"{base}/design/iterations/jobs/{plain['job_id']}")
        _, listed = client.call("GET", base + "/design/iterations")
        assert studio.errors == []

    assert unknown == (404, NOT_FOUND)
    assert wrong == (422, invalid(["body", "critique_source_id"], "uuid_parsing"))
    assert (status, job["status"], plain_status) == (202, "SUCCEEDED", 202)
    latest, earlier = listed["items"]
    assert list(earlier)[:5] == [
        "generation_id",
        "requested_at",
        "request",
        "target",
        "critique_source_id",
    ]
    assert (earlier["critique_source_id"], earlier["request"]) == (source_id, body["request"])
    assert latest["critique_source_id"] is None
