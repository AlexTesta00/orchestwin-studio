from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from orchestwin.artifacts.design_critique import (
    CAPTURE_WIDTHS,
    DESIGN_CRITIQUE_IMAGE_INVALID,
    DESIGN_CRITIQUE_IMAGE_TOO_LARGE,
    DESIGN_CRITIQUE_INVALID,
    DESIGN_CRITIQUE_PAGE_INVALID,
    DESIGN_CRITIQUE_SOURCE_INVALID,
    DESIGN_CRITIQUE_URL_INVALID,
    MAX_IMAGE_SIDE,
    MAX_PAGE_ELEMENTS,
    MAX_PAGE_TEXT_LENGTH,
    MAX_SHOT_BYTES,
    MAX_URL_LENGTH,
    MIN_IMAGE_SIDE,
    VERDICT_BLOCKS,
    VERDICT_SLOWS,
    VERDICT_WORKS,
    DesignCritiqueError,
    DesignCritiqueSourceKind,
    create_design_critique_run,
    create_design_critique_source,
    critique_anchors,
    critique_attachments,
    critique_bundle,
    critique_scenario,
    critique_source_view,
    design_critique_run_from_snapshot,
    design_critique_run_hash,
    design_critique_source_from_snapshot,
    image_dimensions,
    image_media_type,
    is_web_url,
    page_from_document,
    verdict_of,
)
from orchestwin.artifacts.design_evaluation import anchor_finding
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.models.structured_generation import GenerationAttachment
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

from . import design_fixtures

NOW = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)
PROJECT_ID = design_fixtures.PROJECT_ID
OWNER_ID = design_fixtures.OWNER_ID
IMAGE_SOURCE_ID = UUID("00000000-0000-4000-8000-000000004401")
PAGE_SOURCE_ID = UUID("00000000-0000-4000-8000-000000004402")
RUN_ID = UUID("00000000-0000-4000-8000-000000004411")
BUNDLE_ID = UUID("00000000-0000-4000-8000-000000004412")
TWIN_A = UUID("00000000-0000-4000-8000-000000004421")
TWIN_B = UUID("00000000-0000-4000-8000-000000004422")
URL = "https://example.com/prenota"
CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="proposer-design-critique",
    evaluator_version="1.0.0",
    model_config_ref="c" * 64,
    prompt_version_ref="s44-design-critique-v1",
)
TWINS = ((TWIN_B, 1, "Bruno  il  cameriere"), (TWIN_A, 1, "Ada la cliente"))
PAGE_SNAPSHOT = {
    "url": URL,
    "title": "Prenota un tavolo",
    "text": "Prenota un tavolo per stasera",
    "hidden_text": "",
    "elements": [
        {"index": 0, "role": "heading", "name": "Prenota un tavolo"},
        {"index": 1, "role": "combobox", "name": "Persone", "value": "2", "options": ["1", "2"]},
        {"index": 2, "role": "button", "name": "Conferma", "state": "disabled"},
    ],
}
SOURCE_KEYS = [
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
ELEMENT = {"index": 0, "role": "text", "name": "x"}


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width: int, height: int, *, pixels: bool = True) -> bytes:
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    rows = b"".join(b"\x00" + bytes(3 * width) for _ in range(height)) if pixels else b""
    body = chunk(b"IDAT", zlib.compress(rows)) if pixels else b""
    return b"\x89PNG\r\n\x1a\n" + header + body + chunk(b"IEND", b"")


def jpeg(width: int, height: int, *, frame: int = 0xC0, before: bytes = b"") -> bytes:
    application = (
        b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    start = bytes([0xFF, frame]) + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + application + before + start + b"\xff\xd9"


def page_document(**changes) -> dict[str, object]:
    document: dict[str, object] = {
        "url": URL,
        "title": "  Prenota   un tavolo ",
        "text": "Prenota un tavolo\n per stasera",
        "hidden_text": "",
        "elements": [
            {
                "index": 0,
                "role": "heading",
                "name": "Prenota un tavolo",
                "value": None,
                "state": None,
                "options": None,
            },
            {
                "index": 1,
                "role": "combobox",
                "name": "Persone",
                "value": "2",
                "state": None,
                "options": ["1", " 2 ", ""],
            },
            {
                "index": 2,
                "role": "button",
                "name": "Conferma",
                "value": None,
                "state": "disabled",
                "options": None,
            },
        ],
    }
    document.update(changes)
    return document


def image_source(**changes):
    values = {
        "source_id": IMAGE_SOURCE_ID,
        "project_id": PROJECT_ID,
        "owner_user_id": OWNER_ID,
        "kind": DesignCritiqueSourceKind.IMAGE,
        "title": "Schermata del concorrente",
        "url": None,
        "page": None,
        "shots": [(png(1170, 2532, pixels=False), None)],
        "created_at": NOW,
    }
    values.update(changes)
    return create_design_critique_source(**values)


def page_source(**changes):
    values = {
        "source_id": PAGE_SOURCE_ID,
        "project_id": PROJECT_ID,
        "owner_user_id": OWNER_ID,
        "kind": "WEB_PAGE",
        "title": "Prenota un tavolo",
        "url": URL,
        "page": page_document(),
        "shots": [(png(1440, 900, pixels=False), 1440), (jpeg(390, 844), 390)],
        "created_at": NOW,
    }
    values.update(changes)
    return create_design_critique_source(**values)


def finding(twin_id: UUID, number: int, anchor: str, severity: SyntheticFindingSeverity):
    return anchor_finding(
        create_synthetic_finding(
            finding_id=f"UTF-{number:03d}",
            twin_id=twin_id,
            twin_version=1,
            artifact_id=PAGE_SOURCE_ID,
            artifact_version=1,
            location=f"{anchor} Schermata",
            summary="Il pulsante di conferma resta spento.",
            rationale="Al bancone non capisco perché non posso confermare.",
            criterion=SyntheticFindingCriterion.ACTIONABILITY,
            severity=severity,
            epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            evidence_refs=(
                f"artifact:{PAGE_SOURCE_ID}:v1",
                f"user-twin:{twin_id}:v1#user_twin.role",
            ),
            confidence=0.7,
            recommended_action="Spiega accanto al pulsante che cosa manca.",
            requires_human_validation=True,
            model_config_ref=CONFIGURATION.model_config_ref,
            prompt_version_ref=CONFIGURATION.prompt_version_ref,
        ),
        anchor,
    )


def response(bundle, twin_id: UUID, findings, *, run_id: UUID = RUN_ID):
    values = {
        "evaluation_run_id": run_id,
        "artifact_bundle_id": bundle.id,
        "artifact_bundle_hash": bundle.content_hash,
        "twin_id": twin_id,
        "twin_version": 1,
        "evaluator": CONFIGURATION,
        "findings": tuple(findings),
        "summary": "Capisco il design ma mi fermo alla conferma.",
        "evidence_gaps": (),
    }
    return UserTwinEvaluationResponse(
        **values,
        completed_at=NOW + timedelta(seconds=30),
        content_hash=user_twin_evaluation_response_hash(**values),
    )


def critique_run(source=None, contents=None, **changes):
    if source is None:
        source, contents = page_source()
    bundle = critique_bundle(source, contents, locale="it-IT", created_at=NOW, bundle_id=BUNDLE_ID)
    values = {
        "run_id": RUN_ID,
        "owner_user_id": OWNER_ID,
        "source": source,
        "bundle": bundle,
        "twins": TWINS,
        "responses": (
            response(
                bundle,
                TWIN_B,
                (
                    finding(TWIN_B, 1, "SCR-001", SyntheticFindingSeverity.CRITICAL),
                    finding(TWIN_B, 2, "SCR-002", SyntheticFindingSeverity.OBSERVATION),
                ),
            ),
            response(
                bundle, TWIN_A, (finding(TWIN_A, 1, "SCR-002", SyntheticFindingSeverity.MODERATE),)
            ),
        ),
        "started_at": NOW,
        "completed_at": NOW + timedelta(seconds=40),
    }
    values.update(changes)
    return create_design_critique_run(**values)


def refused_code(function, *args, **kwargs) -> str:
    with pytest.raises(DesignCritiqueError) as refused:
        function(*args, **kwargs)
    return refused.value.code


def test_image_headers_give_the_media_type_and_the_dimensions():
    small = png(64, 64)
    assert image_media_type(small) == "image/png"
    assert image_dimensions(small) == (64, 64)
    assert image_dimensions(bytearray(small)) == (64, 64)
    assert image_dimensions(png(1170, 2532, pixels=False)) == (1170, 2532)
    photo = jpeg(390, 844)
    assert image_media_type(photo) == "image/jpeg"
    assert image_dimensions(photo) == (390, 844)
    table = b"\xff\xc4" + struct.pack(">H", 5) + b"\x00\x01\x02"
    progressive = jpeg(1440, 900, frame=0xC2, before=table + b"\xff\xff")
    assert image_dimensions(progressive) == (1440, 900)


def test_unknown_or_truncated_images_are_refused():
    for content in (
        b"",
        "not bytes",
        b"GIF89a" + bytes(32),
        b"\x89PNG\r\n\x1a\n",
        png(64, 64)[:20],
        png(64, 64).replace(b"IHDR", b"IHDX"),
        png(0, 64, pixels=False),
        b"\xff\xd8\xff\xd9",
        jpeg(390, 844).replace(b"\xff\xc0", b"\xff\xda"),
        jpeg(390, 844)[:-12],
    ):
        assert refused_code(image_dimensions, content) == DESIGN_CRITIQUE_IMAGE_INVALID


def test_images_too_large_or_too_small_are_refused_when_a_source_is_created():
    small = png(64, 64)
    cases = (
        (small + bytes(MAX_SHOT_BYTES), DESIGN_CRITIQUE_IMAGE_TOO_LARGE),
        (png(MAX_IMAGE_SIDE + 1, 20, pixels=False), DESIGN_CRITIQUE_IMAGE_TOO_LARGE),
        (jpeg(20, MAX_IMAGE_SIDE + 1), DESIGN_CRITIQUE_IMAGE_TOO_LARGE),
        (png(MIN_IMAGE_SIDE - 1, 64, pixels=False), DESIGN_CRITIQUE_IMAGE_INVALID),
        (b"GIF89a" + bytes(64), DESIGN_CRITIQUE_IMAGE_INVALID),
        (b"", DESIGN_CRITIQUE_IMAGE_INVALID),
    )
    for content, code in cases:
        assert refused_code(image_source, shots=[(content, None)]) == code
    widest, _contents = image_source(
        shots=[(png(MAX_IMAGE_SIDE, MIN_IMAGE_SIDE, pixels=False), None)]
    )
    assert (widest.shots[0].width, widest.shots[0].height) == (MAX_IMAGE_SIDE, MIN_IMAGE_SIDE)
    heaviest = small + bytes(MAX_SHOT_BYTES - len(small))
    full, contents = image_source(shots=[(heaviest, None)])
    assert full.shots[0].byte_size == MAX_SHOT_BYTES
    assert contents == {"SCR-001": heaviest}


def test_an_uploaded_image_becomes_a_source_with_one_screen_and_no_address():
    source, contents = image_source(title="  Schermata   del concorrente ")
    content = png(1170, 2532, pixels=False)
    assert source.kind is DesignCritiqueSourceKind.IMAGE
    assert source.title == "Schermata del concorrente"
    assert (source.url, source.page) == (None, None)
    assert [shot.to_snapshot() for shot in source.shots] == [
        {
            "code": "SCR-001",
            "media_type": "image/png",
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "width": 1170,
            "height": 2532,
            "viewport_width": None,
        }
    ]
    assert contents == {"SCR-001": content}
    assert source.content_hash == snapshot_content_hash(source.semantic_snapshot())
    assert image_source(url="   ")[0] == source


def test_a_web_page_becomes_a_source_with_two_screens_its_address_and_its_page():
    source, contents = page_source()
    assert source.kind is DesignCritiqueSourceKind.WEB_PAGE
    assert source.url == URL
    assert [shot.code for shot in source.shots] == ["SCR-001", "SCR-002"]
    assert [shot.media_type for shot in source.shots] == ["image/png", "image/jpeg"]
    assert [shot.viewport_width for shot in source.shots] == list(CAPTURE_WIDTHS)
    assert [(shot.width, shot.height) for shot in source.shots] == [(1440, 900), (390, 844)]
    assert contents == {"SCR-001": png(1440, 900, pixels=False), "SCR-002": jpeg(390, 844)}
    assert source.page.to_snapshot() == PAGE_SNAPSHOT
    assert page_source(page=None)[0].page is None
    assert page_source(url=f"  {URL}  ")[0] == source
    assert page_source(page=page_from_document(page_document()))[0] == source


def test_addresses_kinds_titles_and_shots_are_checked():
    assert is_web_url(URL) and is_web_url("http://127.0.0.1:5173/")
    for url in (
        None,
        "",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "mailto:someone@example.com",
        "https://",
        "https://example.com/a b",
        "https://example.com/" + "a" * MAX_URL_LENGTH,
    ):
        assert not is_web_url(url)
        assert refused_code(page_source, url=url) == DESIGN_CRITIQUE_URL_INVALID
    for changes in (
        {"url": URL},
        {"page": page_document()},
        {"kind": "VIDEO"},
        {"shots": []},
        {"shots": [(png(64, 64), None)] * 3},
        {"shots": [png(64, 64)]},
        {"shots": [(png(64, 64), 0)]},
        {"shots": [(png(64, 64), True)]},
        {"shots": [(png(64, 64), MAX_IMAGE_SIDE + 1)]},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": None},
        {"created_at": datetime(2026, 10, 9, 15, 0)},
    ):
        assert refused_code(image_source, **changes) == DESIGN_CRITIQUE_SOURCE_INVALID


def test_pages_are_compacted_bounded_and_round_trip():
    page = page_from_document(page_document())
    assert page.to_snapshot() == PAGE_SNAPSHOT
    assert page_from_document(page.to_snapshot()) == page
    assert page_from_document({"url": URL}).to_snapshot() == {
        "url": URL,
        "title": "",
        "text": "",
        "hidden_text": "",
        "elements": [],
    }
    full = page_document(elements=[{**ELEMENT, "index": i} for i in range(MAX_PAGE_ELEMENTS)])
    assert len(page_from_document(full).elements) == MAX_PAGE_ELEMENTS
    for document in (
        "not a page",
        page_document(url="file:///tmp/page.html"),
        page_document(url=None),
        page_document(elements=[{**ELEMENT, "index": i} for i in range(MAX_PAGE_ELEMENTS + 1)]),
        page_document(elements=[{**ELEMENT, "index": 1}]),
        page_document(elements=[{**ELEMENT, "index": True}]),
        page_document(elements=[{**ELEMENT, "state": "pressed"}]),
        page_document(elements=[{**ELEMENT, "role": ""}]),
        page_document(elements=[{**ELEMENT, "name": "n" * 201}]),
        page_document(elements=[{**ELEMENT, "value": 7}]),
        page_document(elements=[{**ELEMENT, "options": [str(i) for i in range(21)]}]),
        page_document(elements=[{**ELEMENT, "options": "uno"}]),
        page_document(elements=["text"]),
        page_document(elements={}),
        page_document(text="t" * (MAX_PAGE_TEXT_LENGTH + 1)),
        page_document(title=None),
    ):
        assert refused_code(page_from_document, document) == DESIGN_CRITIQUE_PAGE_INVALID
    crowded = page_document(elements=[{**ELEMENT, "index": i} for i in range(401)])
    assert refused_code(page_source, page=crowded) == DESIGN_CRITIQUE_PAGE_INVALID


def test_source_snapshots_carry_no_bytes_and_round_trip():
    for source, _contents in (image_source(), page_source()):
        snapshot = source.to_snapshot()
        assert list(snapshot) == SOURCE_KEYS
        assert snapshot["created_at"] == "2026-10-09T15:00:00+00:00"
        stored = json.loads(json.dumps(snapshot))
        assert design_critique_source_from_snapshot(stored) == source
    source, _contents = page_source()
    snapshot = source.to_snapshot()
    for tampered in (
        {**snapshot, "title": "Altro"},
        {**snapshot, "schema_version": 2},
        {**snapshot, "shots": []},
        {key: value for key, value in snapshot.items() if key != "page"},
        "not a snapshot",
    ):
        assert (
            refused_code(design_critique_source_from_snapshot, tampered)
            == DESIGN_CRITIQUE_SOURCE_INVALID
        )
    shifted, _contents = page_source(created_at=NOW.astimezone(timezone(timedelta(hours=2))))
    assert shifted.content_hash == source.content_hash
    assert shifted == source


def test_shots_and_sources_refuse_inconsistent_fields():
    source, _contents = page_source()
    shot = source.shots[0]
    for changes in (
        {"code": "SCR-003"},
        {"media_type": "image/gif"},
        {"byte_size": 0},
        {"sha256": "A" * 64},
        {"width": MAX_IMAGE_SIDE + 1},
        {"viewport_width": 0},
    ):
        assert refused_code(replace, shot, **changes) == DESIGN_CRITIQUE_SOURCE_INVALID
    assert refused_code(replace, source, title="Altro titolo") == DESIGN_CRITIQUE_SOURCE_INVALID
    assert refused_code(replace, source, shots=source.shots[::-1]) == (
        DESIGN_CRITIQUE_SOURCE_INVALID
    )
    assert refused_code(replace, source, url="ftp://example.com/") == DESIGN_CRITIQUE_URL_INVALID


def test_anchors_and_views_name_each_screen_in_both_languages():
    image, _contents = image_source()
    page, _contents = page_source()
    assert critique_anchors(image, "it") == {"SCR-001": "SCR-001 Immagine fornita · 1170 x 2532 px"}
    assert critique_anchors(image, "en") == {"SCR-001": "SCR-001 Supplied image · 1170 x 2532 px"}
    assert critique_anchors(page, "it-IT") == {
        "SCR-001": "SCR-001 Schermata 1 · 1440 px",
        "SCR-002": "SCR-002 Schermata 2 · 390 px",
    }
    assert critique_anchors(page, "en") == {
        "SCR-001": "SCR-001 Screen 1 · 1440 px",
        "SCR-002": "SCR-002 Screen 2 · 390 px",
    }
    assert critique_anchors(page, "fr") == critique_anchors(page, "en")
    assert critique_source_view(page, "it") == {
        "kind": "WEB_PAGE",
        "title": "Prenota un tavolo",
        "url": URL,
        "page": PAGE_SNAPSHOT,
        "screens": [
            {
                "code": "SCR-001",
                "file": "screenshot-001.png",
                "label": "Schermata 1 · 1440 px",
                "width": 1440,
                "height": 900,
                "viewport_width": 1440,
            },
            {
                "code": "SCR-002",
                "file": "screenshot-002.jpg",
                "label": "Schermata 2 · 390 px",
                "width": 390,
                "height": 844,
                "viewport_width": 390,
            },
        ],
    }
    view = critique_source_view(image, "en")
    assert view == {
        "kind": "IMAGE",
        "title": "Schermata del concorrente",
        "url": None,
        "page": None,
        "screens": [
            {
                "code": "SCR-001",
                "file": "screenshot-001.png",
                "label": "Supplied image · 1170 x 2532 px",
                "width": 1170,
                "height": 2532,
                "viewport_width": None,
            }
        ],
    }
    assert json.loads(json.dumps(view)) == view


def test_attachments_carry_each_screen_under_its_file_name():
    source, contents = page_source()
    attachments = critique_attachments(source, contents)
    assert all(isinstance(item, GenerationAttachment) for item in attachments)
    assert [(item.name, item.media_type) for item in attachments] == [
        ("screenshot-001.png", "image/png"),
        ("screenshot-002.jpg", "image/jpeg"),
    ]
    assert [item.content for item in attachments] == [contents["SCR-001"], contents["SCR-002"]]
    assert [item.sha256 for item in attachments] == [shot.sha256 for shot in source.shots]
    for broken in (
        {"SCR-001": contents["SCR-001"]},
        {**contents, "SCR-002": contents["SCR-001"]},
        {**contents, "SCR-002": "not bytes"},
    ):
        assert refused_code(critique_attachments, source, broken) == DESIGN_CRITIQUE_SOURCE_INVALID


def test_the_scenario_is_stable_for_a_source_and_follows_the_language():
    page, _contents = page_source()
    image, _contents = image_source()
    italian = critique_scenario(page, "it-IT")
    english = critique_scenario(page, "en-US")
    assert italian.id == english.id == critique_scenario(page_source()[0], "it-IT").id
    assert critique_scenario(image, "it-IT").id != italian.id
    assert (italian.name, italian.locale, english.locale) == ("Prenota un tavolo", "it-IT", "en-US")
    assert italian.task == (
        "Capire questo design e usarlo per il tuo scopo abituale con un prodotto come questo"
    )
    assert italian.expected_outcomes == ("Trovi ciò che ti serve e sai che cosa fare",)
    assert english.task == (
        "Understand this design and use it for your usual goal with a product like this one"
    )
    assert english.expected_outcomes == ("You find what you need and you know what to do",)


def test_the_bundle_holds_one_screenshot_per_screen_and_the_page():
    page, contents = page_source()
    bundle = critique_bundle(page, contents, locale="it-IT", created_at=NOW, bundle_id=BUNDLE_ID)
    assert (bundle.id, bundle.project_id, bundle.workflow_run_id) == (
        BUNDLE_ID,
        PROJECT_ID,
        PAGE_SOURCE_ID,
    )
    assert [
        (item.kind, item.version_number, item.location, item.media_type)
        for item in bundle.artifacts
    ] == [
        (EvaluationArtifactKind.DOM_SNAPSHOT, 1, "critique/page.json", "application/json"),
        (EvaluationArtifactKind.SCREENSHOT, 1, "critique/SCR-001.png", "image/png"),
        (EvaluationArtifactKind.SCREENSHOT, 2, "critique/SCR-002.jpg", "image/jpeg"),
    ]
    assert {item.artifact_id for item in bundle.artifacts} == {PAGE_SOURCE_ID}
    document = canonical_json(PAGE_SNAPSHOT).encode("utf-8")
    assert [item.sha256_digest for item in bundle.artifacts] == [
        hashlib.sha256(document).hexdigest(),
        page.shots[0].sha256,
        page.shots[1].sha256,
    ]
    assert bundle.is_multimodal
    assert bundle.scenario == critique_scenario(page, "it-IT")
    again = critique_bundle(page, contents, locale="it-IT", created_at=NOW + timedelta(minutes=1))
    assert again.content_hash == bundle.content_hash
    assert again.id != bundle.id
    image, image_contents = image_source()
    alone = critique_bundle(image, image_contents, locale="en", created_at=NOW)
    assert [item.kind for item in alone.artifacts] == [EvaluationArtifactKind.SCREENSHOT]
    assert not alone.is_multimodal
    partial = {"SCR-001": contents["SCR-001"]}
    assert (
        refused_code(critique_bundle, page, partial, locale="it-IT", created_at=NOW)
        == DESIGN_CRITIQUE_SOURCE_INVALID
    )


def test_verdicts_follow_the_worst_severity_of_each_twin_on_each_screen():
    assert verdict_of(()) == VERDICT_WORKS
    assert verdict_of([SyntheticFindingSeverity.OBSERVATION]) == VERDICT_WORKS
    assert verdict_of(["minor"]) == VERDICT_SLOWS
    assert verdict_of(["observation", "moderate"]) == VERDICT_SLOWS
    assert verdict_of(["major"]) == VERDICT_BLOCKS
    assert verdict_of(["minor", "critical"]) == VERDICT_BLOCKS
    assert critique_run().verdicts() == (
        {"twin_id": str(TWIN_A), "anchor_key": "SCR-001", "verdict": VERDICT_WORKS},
        {"twin_id": str(TWIN_A), "anchor_key": "SCR-002", "verdict": VERDICT_SLOWS},
        {"twin_id": str(TWIN_B), "anchor_key": "SCR-001", "verdict": VERDICT_BLOCKS},
        {"twin_id": str(TWIN_B), "anchor_key": "SCR-002", "verdict": VERDICT_WORKS},
    )


def test_a_run_collects_one_response_per_twin_and_round_trips():
    critique = critique_run()
    assert critique.project_id == PROJECT_ID
    assert [item.twin_id for item in critique.responses] == [TWIN_A, TWIN_B]
    assert critique.twins == ((TWIN_A, 1, "Ada la cliente"), (TWIN_B, 1, "Bruno il cameriere"))
    assert len(critique.findings) == 3
    assert critique.evaluator == CONFIGURATION
    assert critique.content_hash == design_critique_run_hash(critique)
    snapshot = critique.to_snapshot()
    assert snapshot["schema_version"] == 1
    assert snapshot["source"] == critique.source.to_snapshot()
    assert snapshot["twins"] == [
        {"twin_id": str(TWIN_A), "version_number": 1, "name": "Ada la cliente"},
        {"twin_id": str(TWIN_B), "version_number": 1, "name": "Bruno il cameriere"},
    ]
    stored = json.loads(json.dumps(snapshot))
    assert design_critique_run_from_snapshot(stored) == critique
    moved = json.loads(json.dumps(snapshot))
    moved["responses"][0]["findings"][0]["anchor_key"] = "SCR-001"
    for broken in (
        moved,
        {**stored, "schema_version": 2},
        {**stored, "twins": stored["twins"][:1]},
        {**stored, "started_at": "yesterday"},
        {**stored, "content_hash": "0" * 64},
        "not a snapshot",
    ):
        assert refused_code(design_critique_run_from_snapshot, broken) == DESIGN_CRITIQUE_INVALID
    assert refused_code(replace, critique, twins=critique.twins[::-1]) == DESIGN_CRITIQUE_INVALID
    late = NOW - timedelta(seconds=1)
    assert refused_code(replace, critique, completed_at=late) == DESIGN_CRITIQUE_INVALID


def test_a_run_refuses_repeated_twins_foreign_bundles_and_unknown_screens():
    source, contents = page_source()
    bundle = critique_bundle(source, contents, locale="it-IT", created_at=NOW, bundle_id=BUNDLE_ID)
    first = response(bundle, TWIN_A, ())
    twice = response(
        bundle, TWIN_A, (finding(TWIN_A, 1, "SCR-001", SyntheticFindingSeverity.MINOR),)
    )

    def attempt(**changes):
        values = {
            "run_id": RUN_ID,
            "owner_user_id": OWNER_ID,
            "source": source,
            "bundle": bundle,
            "twins": ((TWIN_A, 1, "Ada la cliente"),),
            "responses": (first,),
            "started_at": NOW,
            "completed_at": NOW + timedelta(seconds=5),
        }
        values.update(changes)
        return create_design_critique_run(**values)

    assert [item["verdict"] for item in attempt().verdicts()] == [VERDICT_WORKS, VERDICT_WORKS]
    other, other_contents = image_source()
    foreign = critique_bundle(other, other_contents, locale="it-IT", created_at=NOW)
    minor = SyntheticFindingSeverity.MINOR
    for changes in (
        {"responses": (first, twice)},
        {"bundle": foreign, "responses": (response(foreign, TWIN_A, ()),)},
        {"twins": ((TWIN_B, 1, "Bruno"),)},
        {"twins": ((TWIN_A, 1, "Ada"), (TWIN_A, 1, "Ada"))},
        {"twins": ((TWIN_A, 2, "Ada"),)},
        {"twins": ((TWIN_A, 1, " "),)},
        {"twins": ((TWIN_A, 1),)},
        {"responses": (response(bundle, TWIN_A, (finding(TWIN_A, 1, "SCR-003", minor),)),)},
        {"responses": (response(bundle, TWIN_A, (finding(TWIN_A, 1, "SCR-001/ELM-001", minor),)),)},
        {"responses": (response(bundle, TWIN_A, (), run_id=BUNDLE_ID),)},
        {"responses": ()},
        {"owner_user_id": TWIN_B},
        {"started_at": datetime(2026, 10, 9, 15, 0)},
    ):
        assert refused_code(attempt, **changes) == DESIGN_CRITIQUE_INVALID
