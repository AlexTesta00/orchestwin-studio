from __future__ import annotations

import email.parser
import email.policy
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from orchestwin.artifacts.design_evaluation import anchor_finding
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import SectionState

from .common import _by_id, _canonical, _copy, _digest, _twin_reference
from .fields import _Fields
from .texts import COSTS
from .values import DEFAULT_LOCALE, DISCLAIMER, MAX_LOCALE_LENGTH, MODEL, _Answer, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


CRITIQUE_KINDS = ("IMAGE", "WEB_PAGE")
CRITIQUE_FIELDS = ("source_id", "locale")
CRITIQUE_SHOT_FIELD = "shots"
CRITIQUE_MAX_SHOTS = 2
CRITIQUE_MAX_SHOT_BYTES = 5 * 1024 * 1024
CRITIQUE_MAX_UPLOAD_BYTES = 11 * 1024 * 1024
CRITIQUE_MAX_PAGE_BYTES = 200 * 1024
CRITIQUE_MAX_ELEMENTS = 400
CRITIQUE_MAX_TITLE = 200
CRITIQUE_MAX_URL = 2048
CRITIQUE_MIN_SIDE = 16
CRITIQUE_MAX_SIDE = 8000
CRITIQUE_LIST_LIMIT = 50
CRITIQUE_SCHEMES = ("http", "https")
CRITIQUE_PNG = b"\x89PNG\r\n\x1a\n"
CRITIQUE_JPEG_FRAMES = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
CRITIQUE_VERDICTS = (("BLOCKS", ("critical", "major")), ("SLOWS", ("moderate", "minor")))
CRITIQUE_EVALUATOR = {
    "evaluator_id": "fake-design-critique",
    "evaluator_version": "1",
    "model_config_ref": MODEL,
    "prompt_version_ref": "fake-design-critique-v1",
}
CRITIQUE_TEXTS = {
    "it": {
        "screen": "Schermata {number} · {width} px",
        "image": "Immagine fornita · {width} x {height} px",
        "summary": "Parere simulato di {name} sul design fornito.",
        "rationale": "Il profilo del twin usa il telefono di fretta.",
        "gap": "Una schermata ferma non mostra che cosa succede dopo il tocco.",
        "task": "Capire questo design e usarlo per il tuo scopo abituale con un prodotto come "
        "questo",
        "outcome": "Trovi ciò che ti serve e sai che cosa fare",
        "first": (
            (
                "SCR-001",
                "Il pulsante principale si confonde con il resto della pagina.",
                "major",
                "actionability",
                "Dai al pulsante principale un colore pieno e mettilo in alto.",
            ),
            (
                "SCR-002",
                "Sul telefono le scritte sono piccole.",
                "minor",
                "comprehensibility",
                "Ingrandisci il testo sullo schermo stretto.",
            ),
        ),
        "other": (
            "SCR-001",
            "Capisco subito che cosa offre la pagina.",
            "observation",
            "comprehensibility",
            "Tieni il titolo così chiaro.",
        ),
    },
    "en": {
        "screen": "Screen {number} · {width} px",
        "image": "Supplied image · {width} x {height} px",
        "summary": "Simulated opinion of {name} on the supplied design.",
        "rationale": "The twin profile uses the phone in a hurry.",
        "gap": "A still screen does not show what happens after the tap.",
        "task": "Understand this design and use it for your usual goal with a product like this "
        "one",
        "outcome": "You find what you need and you know what to do",
        "first": (
            (
                "SCR-001",
                "The main button blends in with the rest of the page.",
                "major",
                "actionability",
                "Give the main button a solid colour and put it at the top.",
            ),
            (
                "SCR-002",
                "On the phone the text is small.",
                "minor",
                "comprehensibility",
                "Make the text larger on the narrow screen.",
            ),
        ),
        "other": (
            "SCR-001",
            "I understand at once what the page offers.",
            "observation",
            "comprehensibility",
            "Keep the title this clear.",
        ),
    },
}


class _CritiqueRoutes:
    def _critique_twins(self, project: FakeProject) -> list[dict[str, object]]:
        state = self._project_sections(project).section(ProjectStage.USER_TWINS).state
        snapshot = project.snapshot
        if snapshot is None or state not in (SectionState.FINE, SectionState.UPDATE_AVAILABLE):
            raise _Refusal(409, {"code": "DESIGN_CRITIQUE_TWINS_REQUIRED"})
        return [_twin_reference(twin) for twin in snapshot["snapshot"]["twin_versions"]]

    def _route_critique_upload(self, call: _Call) -> _Answer:
        declared = call.headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > CRITIQUE_MAX_UPLOAD_BYTES:
            raise _Refusal(413, {"code": "DESIGN_CRITIQUE_IMAGE_TOO_LARGE"})
        project = self._code_project(call)
        self._critique_twins(project)
        parts = _multipart_many(call.headers.get("content-type", ""), call.raw)
        fields = {
            name: content.decode("utf-8", "replace")
            for name, file_name, content in parts
            if file_name is None
        }
        files = [
            (file_name, content)
            for name, file_name, content in parts
            if name == CRITIQUE_SHOT_FIELD and file_name is not None
        ]
        kind = fields.get("kind") or CRITIQUE_KINDS[0]
        if kind not in CRITIQUE_KINDS or not 1 <= len(files) <= CRITIQUE_MAX_SHOTS:
            raise _Refusal(422, {"code": "DESIGN_CRITIQUE_SOURCE_INVALID"})
        url = fields.get("url")
        page = None
        if kind == "WEB_PAGE":
            if url is None or not _critique_address(url):
                raise _Refusal(422, {"code": "DESIGN_CRITIQUE_URL_INVALID"})
            page = _critique_page(fields.get("page"))
        elif url is not None or "page" in fields:
            raise _Refusal(422, {"code": "DESIGN_CRITIQUE_SOURCE_INVALID"})
        widths = _critique_widths(fields.get("viewport_widths"), len(files))
        source_id = self._new_id()
        shots = []
        contents = []
        for number, ((_, content), width) in enumerate(zip(files, widths, strict=True), start=1):
            if len(content) > CRITIQUE_MAX_SHOT_BYTES:
                raise _Refusal(413, {"code": "DESIGN_CRITIQUE_IMAGE_TOO_LARGE"})
            found = _critique_image(content)
            if found is None:
                raise _Refusal(422, {"code": "DESIGN_CRITIQUE_IMAGE_INVALID"})
            media_type, image_width, image_height = found
            if max(image_width, image_height) > CRITIQUE_MAX_SIDE:
                raise _Refusal(413, {"code": "DESIGN_CRITIQUE_IMAGE_TOO_LARGE"})
            if min(image_width, image_height) < CRITIQUE_MIN_SIDE:
                raise _Refusal(422, {"code": "DESIGN_CRITIQUE_IMAGE_INVALID"})
            shots.append(
                {
                    "code": f"SCR-{number:03d}",
                    "media_type": media_type,
                    "byte_size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "width": image_width,
                    "height": image_height,
                    "viewport_width": width,
                }
            )
            contents.append(content)
        given = fields.get("title")
        title = " ".join((given or "").split())
        if given is not None and len(title) > CRITIQUE_MAX_TITLE:
            raise _Refusal(422, {"code": "DESIGN_CRITIQUE_SOURCE_INVALID"})
        if not title and page is not None:
            title = " ".join(str(page.get("title") or "").split())
        if not title:
            title = str(urlsplit(url).hostname) if url else files[0][0].rsplit(".", 1)[0]
        source = {
            "schema_version": 1,
            "id": source_id,
            "project_id": project.id,
            "owner_user_id": project.account.id,
            "kind": kind,
            "title": title[:CRITIQUE_MAX_TITLE].strip() or kind,
            "url": url,
            "page": page,
            "shots": shots,
            "created_at": _iso(self._now()),
        }
        source["content_hash"] = _digest(
            {key: source[key] for key in ("kind", "title", "url", "page", "shots")}
        )
        for shot, content in zip(shots, contents, strict=True):
            project.critique_shots[(source_id, str(shot["code"]))] = (
                str(shot["media_type"]),
                content,
            )
        project.critique_sources.insert(0, source)
        return _Answer(201, {"source": _copy(source)})

    def _route_critique_sources(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, {"items": _copy(project.critique_sources[:CRITIQUE_LIST_LIMIT])})

    def _route_critique_shot(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        stored = project.critique_shots.get((call.params["source_id"], call.params["code"]))
        if stored is None:
            raise _Refusal(404, {"code": "DESIGN_CRITIQUE_SOURCE_NOT_FOUND"})
        media_type, content = stored
        return _Answer(
            200,
            raw=content,
            content_type=media_type,
            headers={"Cache-Control": "private, max-age=0"},
        )

    def _route_critique_run(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), CRITIQUE_FIELDS)
        source_id = fields.identifier("source_id")
        locale = fields.text(
            "locale",
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        fields.check()
        project = self._code_project(call)
        source = _by_id(project.critique_sources, str(source_id))
        if source is None:
            raise _Refusal(404, {"code": "DESIGN_CRITIQUE_SOURCE_NOT_FOUND"})
        twins = self._critique_twins(project)
        if not self.hosted:
            raise _Refusal(503, {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"})
        self._require_budget(project)
        started = self._now()
        cost = 0
        if self.billing != "SUBSCRIPTION":
            for _ in twins:
                self._record(project, "DESIGN_CRITIQUE")
            cost = len(twins) * COSTS["DESIGN_CRITIQUE"]
        run = self._critique_run(project, source, twins, str(locale), started, cost)
        project.critique_runs.insert(0, run)
        return _Answer(201, {"status": "DESIGN_CRITIQUE_RECORDED", "run": _copy(run)})

    def _route_critique_runs(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, {"items": _copy(project.critique_runs[:CRITIQUE_LIST_LIMIT])})

    def _critique_run(
        self,
        project: FakeProject,
        source: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        started: datetime,
        cost: int,
    ) -> dict[str, object]:
        texts = CRITIQUE_TEXTS[self.language]
        run_id = self._new_id()
        anchors = _critique_anchors(source, texts)
        artifacts = [
            {
                "artifact_id": source["id"],
                "version_number": number,
                "kind": "SCREENSHOT",
                "modality": "VISUAL",
                "media_type": shot["media_type"],
                "sha256_digest": shot["sha256"],
                "size_bytes": shot["byte_size"],
                "storage_key": f"sha256/{str(shot['sha256'])[:2]}/{shot['sha256']}",
                "location": f"critique/{shot['code']}.png",
            }
            for number, shot in enumerate(source["shots"], start=1)
        ]
        if source["page"] is not None:
            document = _canonical(source["page"]).encode("utf-8")
            digest = hashlib.sha256(document).hexdigest()
            artifacts.append(
                {
                    "artifact_id": source["id"],
                    "version_number": len(artifacts) + 1,
                    "kind": "DOM_SNAPSHOT",
                    "modality": "STRUCTURAL",
                    "media_type": "application/json",
                    "sha256_digest": digest,
                    "size_bytes": len(document),
                    "storage_key": f"sha256/{digest[:2]}/{digest}",
                    "location": "critique/page.json",
                }
            )
        modalities = sorted({str(item["modality"]) for item in artifacts})
        bundle = {
            "id": self._new_id(),
            "project_id": project.id,
            "workflow_run_id": source["id"],
            "scenario": {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"design-critique:{source['id']}")),
                "name": source["title"],
                "task": texts["task"],
                "locale": locale,
                "expected_outcomes": [texts["outcome"]],
            },
            "artifacts": artifacts,
            "modalities": modalities,
            "is_multimodal": len(modalities) > 1,
            "created_at": _iso(started),
        }
        bundle["content_hash"] = _digest(
            {key: bundle[key] for key in ("project_id", "workflow_run_id", "scenario", "artifacts")}
        )
        responses = []
        for position, twin in enumerate(twins):
            templates = texts["first"] if position == 0 else (texts["other"],)
            placed = [item for item in templates if item[0] in anchors]
            findings = [
                self._critique_finding(number, twin, source, anchors[item[0]], item, texts)
                for number, item in enumerate(placed, start=1)
            ]
            response = {
                "evaluation_run_id": run_id,
                "artifact_bundle_id": bundle["id"],
                "artifact_bundle_hash": bundle["content_hash"],
                "twin_id": twin["twin_id"],
                "twin_version": twin["version_number"],
                "evaluator": dict(CRITIQUE_EVALUATOR),
                "findings": findings,
                "summary": texts["summary"].format(name=twin["name"]),
                "evidence_gaps": [texts["gap"]] if position == 0 else [],
                "is_simulated_feedback": True,
            }
            response["content_hash"] = _digest(response)
            response["completed_at"] = _iso(self._now())
            response["disclaimer"] = DISCLAIMER
            responses.append(response)
        responses.sort(key=lambda item: str(item["twin_id"]))
        completed = self._now()
        run = {
            "schema_version": 1,
            "id": run_id,
            "project_id": project.id,
            "owner_user_id": project.account.id,
            "source": _copy(source),
            "bundle": bundle,
            "twins": [
                {
                    "twin_id": twin["twin_id"],
                    "version_number": twin["version_number"],
                    "name": twin["name"],
                }
                for twin in twins
            ],
            "responses": responses,
            "started_at": _iso(started),
            "completed_at": _iso(completed),
        }
        run["content_hash"] = _digest(run)
        verdicts = [
            {
                "twin_id": response["twin_id"],
                "anchor_key": code,
                "verdict": _critique_verdict(
                    [
                        str(finding["severity"])
                        for finding in response["findings"]
                        if finding["anchor_key"] == code
                    ]
                ),
            }
            for response in responses
            for code in anchors
        ]
        return {
            **run,
            "verdicts": verdicts,
            "duration_seconds": (completed - started).total_seconds(),
            "cost_microusd": cost,
        }

    def _critique_finding(
        self,
        number: int,
        twin: Mapping[str, object],
        source: Mapping[str, object],
        location: str,
        template: Sequence[str],
        texts: Mapping[str, object],
    ) -> dict[str, object]:
        key, summary, severity, criterion, action = template
        finding = create_synthetic_finding(
            finding_id=f"UTF-{number:03d}",
            twin_id=UUID(str(twin["twin_id"])),
            twin_version=int(twin["version_number"]),
            artifact_id=UUID(str(source["id"])),
            artifact_version=1,
            location=location,
            summary=summary,
            rationale=str(texts["rationale"]),
            criterion=SyntheticFindingCriterion(criterion),
            severity=SyntheticFindingSeverity(severity),
            epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            evidence_refs=(f"artifact:{source['id']}:v1",),
            confidence=0.6,
            recommended_action=action,
            requires_human_validation=True,
            model_config_ref=CRITIQUE_EVALUATOR["model_config_ref"],
            prompt_version_ref=CRITIQUE_EVALUATOR["prompt_version_ref"],
        )
        return anchor_finding(finding, key, None).to_snapshot()


def _multipart_many(content_type: str, body: bytes) -> list[tuple[str, str | None, bytes]]:
    if not content_type.lower().startswith("multipart/form-data"):
        return []
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body
    )
    if not message.is_multipart():
        return []
    parts: list[tuple[str, str | None, bytes]] = []
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str):
            continue
        payload = part.get_payload(decode=True)
        parts.append((name, part.get_filename(), payload if isinstance(payload, bytes) else b""))
    return parts


def _critique_image(content: bytes) -> tuple[str, int, int] | None:
    if content.startswith(CRITIQUE_PNG):
        if len(content) < 24 or content[12:16] != b"IHDR":
            return None
        width = int.from_bytes(content[16:20], "big")
        height = int.from_bytes(content[20:24], "big")
        return "image/png", width, height
    if not content.startswith(b"\xff\xd8"):
        return None
    index = 2
    while index + 4 <= len(content):
        if content[index] != 0xFF:
            return None
        marker = content[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = int.from_bytes(content[index + 2 : index + 4], "big")
        if marker in CRITIQUE_JPEG_FRAMES:
            if index + 9 > len(content):
                return None
            height = int.from_bytes(content[index + 5 : index + 7], "big")
            width = int.from_bytes(content[index + 7 : index + 9], "big")
            return "image/jpeg", width, height
        if length < 2 or marker in (0xD9, 0xDA):
            return None
        index += 2 + length
    return None


def _critique_address(value: str) -> bool:
    if not 1 <= len(value) <= CRITIQUE_MAX_URL:
        return False
    if not all(character.isprintable() and not character.isspace() for character in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in CRITIQUE_SCHEMES and bool(parts.hostname)


def _critique_page(value: str | None) -> dict[str, object] | None:
    if value is None:
        return None
    invalid = _Refusal(422, {"code": "DESIGN_CRITIQUE_PAGE_INVALID"})
    if len(value.encode("utf-8")) > CRITIQUE_MAX_PAGE_BYTES:
        raise invalid
    try:
        page = json.loads(value)
    except ValueError:
        raise invalid from None
    if (
        not isinstance(page, dict)
        or not all(isinstance(page.get(key), str) for key in ("url", "title", "text"))
        or not isinstance(page.get("elements"), list)
        or len(page["elements"]) > CRITIQUE_MAX_ELEMENTS
    ):
        raise invalid
    return page


def _critique_widths(value: str | None, count: int) -> list[int | None]:
    if value is None:
        return [None] * count
    invalid = _Refusal(422, {"code": "DESIGN_CRITIQUE_SOURCE_INVALID"})
    try:
        widths = json.loads(value)
    except ValueError:
        raise invalid from None
    if (
        not isinstance(widths, list)
        or len(widths) != count
        or not all(
            item is None or (type(item) is int and CRITIQUE_MIN_SIDE <= item <= CRITIQUE_MAX_SIDE)
            for item in widths
        )
    ):
        raise invalid
    return widths


def _critique_anchors(source: Mapping[str, object], texts: Mapping[str, object]) -> dict[str, str]:
    anchors: dict[str, str] = {}
    for number, shot in enumerate(source["shots"], start=1):
        if shot["viewport_width"] is None:
            label = str(texts["image"]).format(width=shot["width"], height=shot["height"])
        else:
            label = str(texts["screen"]).format(number=number, width=shot["viewport_width"])
        anchors[str(shot["code"])] = f"{shot['code']} {label}"
    return anchors


def _critique_verdict(severities: Sequence[str]) -> str:
    for verdict, levels in CRITIQUE_VERDICTS:
        if any(severity in levels for severity in severities):
            return verdict
    return "WORKS"
