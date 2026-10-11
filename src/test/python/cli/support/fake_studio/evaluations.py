from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.artifacts.design_evaluation import (
    ANCHOR_LABEL_LENGTH,
    DESIGN_EVALUATION_SCOPE_INVALID,
    MATCH_SIMILARITY,
    anchor_element,
    anchor_finding,
    finding_similarity,
    synthetic_finding_from_snapshot,
)
from orchestwin.artifacts.generated_mockup_document import MockupPin, mockup_document
from orchestwin.artifacts.generated_mockup_styles import FORBIDDEN_CHARACTERS
from orchestwin.artifacts.generated_mockups import generated_mockup_from_snapshot
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.evaluation.proposer_evaluator import (
    SCOPED_TWIN_REVIEW_PROMPT_VERSION,
    scoped_prompt_version,
)

from .common import _by_id, _digest, _error, _model_rule, _screen_list, _tokens
from .fields import _Fields
from .values import DISCLAIMER, ELEMENT_CODE, MODEL, SCREEN_CODE, _Answer, _Invalid, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


ANCHOR_KINDS = {
    "action": ("SCR-001", ("LINK", "BUTTON"), True),
    "result": ("SCR-002", ("STATUS", "TEXT", "LIST", "CARD"), False),
    "title": ("SCR-002", ("HEADING",), False),
}
PIN_LABEL_LENGTH = 120
REVIEW_LANGUAGE = "und"
ENTRY_SCREEN_PATTERN = re.compile(r"SCR-[0-9]{3}")
LEADING_SCREEN = re.compile(r"(SCR-[0-9]{3,6})(?![0-9])")
LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,7}")
EVALUATION_FIELDS = ("design_version_id", "design_content_hash", "locale", "mode", "scope")
SCOPE_FIELDS = ("screen_code", "element_code")
EVALUATOR = {
    "evaluator_id": "fake-twin-reviewer",
    "evaluator_version": "1",
    "model_config_ref": MODEL,
    "prompt_version_ref": "fake-twin-review-v1",
}
FINDINGS = {
    "it": {
        "first": (
            (
                (
                    "action",
                    "Il pulsante principale è in fondo: al tavolo lo cerco ogni volta.",
                    "major",
                    "actionability",
                ),
                (
                    "result",
                    "Il risultato è scritto piccolo sul telefono.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "Non vedo come dividere il conto tra più persone.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "later": (
            (
                (
                    "result",
                    "Il risultato è ancora un po' piccolo sul telefono.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "Non vedo come dividere il conto tra più persone.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "other": (
            "title",
            "Il titolo del risultato è chiaro.",
            "observation",
            "comprehensibility",
        ),
        "rationale": "Il profilo del twin usa il telefono al tavolo.",
        "action": "Rendere l'azione principale più visibile.",
        "summary": "Revisione simulata di {name}.",
        "scenario": (
            "Revisione del design",
            "Valutare il mockup scelto al tavolo",
            "Il twin capisce come calcolare la mancia",
        ),
    },
    "en": {
        "first": (
            (
                (
                    "action",
                    "The main button is at the bottom: at the table I look for it every time.",
                    "major",
                    "actionability",
                ),
                (
                    "result",
                    "The result is written small on the phone.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "I cannot see how to split the bill among several people.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "later": (
            (
                (
                    "result",
                    "The result is still a little small on the phone.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "I cannot see how to split the bill among several people.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "other": (
            "title",
            "The title of the result is clear.",
            "observation",
            "comprehensibility",
        ),
        "rationale": "The twin profile uses a phone at the table.",
        "action": "Make the main action more visible.",
        "summary": "Simulated review by {name}.",
        "scenario": (
            "Design review",
            "Assess the chosen mockup at the table",
            "The twin understands how to work out the tip",
        ),
    },
}
SCOPED_FINDINGS = {
    "it": (
        "La modifica mi aiuta: ora trovo subito questo elemento al tavolo.",
        "observation",
        "actionability",
        "Prova con un blu più scuro per farlo risaltare ancora di più.",
    ),
    "en": (
        "The change helps me: now I find this element at once at the table.",
        "observation",
        "actionability",
        "Try a darker blue to make it stand out even more.",
    ),
}


class _EvaluationRoutes:
    def _route_evaluation(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), EVALUATION_FIELDS)
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        locale = fields.text("locale", required=False, minimum=2, maximum=20, default="it-IT")
        mode = fields.choice("mode", ("TWIN_REVIEW", "STATIC_CHECK"), required=False, nullable=True)
        scope = _review_scope(fields)
        _model_rule(fields, lambda: _scope_of_a_twin_review(scope, mode))
        fields.check()
        body = {
            "design_version_id": version_id,
            "design_content_hash": content_hash,
            "locale": locale,
            "mode": mode,
            **({} if scope is None else {"scope": scope}),
        }
        return self._later(
            call,
            "DESIGN_EVALUATION",
            body,
            lambda: self._evaluated(
                call, str(version_id), str(content_hash), str(locale), mode, scope
            ),
        )

    def _evaluated(
        self,
        call: _Call,
        version_id: str,
        content_hash: str,
        locale: str,
        mode: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> _Answer:
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if (current["id"], current["content_hash"]) != (version_id, content_hash):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        if mode == "STATIC_CHECK" or (mode is None and scope is None and not self.hosted):
            raise _Refusal(503, {"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"})
        package = current["package"]
        if package["owner_selected_alternative_id"] is None or package["prototype"] is None:
            raise _Refusal(409, {"code": "DESIGN_PROTOTYPE_REQUIRED"})
        scoped = None if scope is None else _scope_anchor(package["prototype"], scope)
        twins = [dict(item) for item in package["grounding"]["user_twin_references"]]
        for twin in twins:
            known = project.twins.get(str(twin["twin_id"]))
            if not known or not any(
                version["version_number"] == twin["version_number"]
                and version["content_hash"] == twin["content_hash"]
                for version in known
            ):
                raise _Refusal(409, {"code": "USER_TWIN_CONTEXT_CHANGED"})
        started = self._now()
        for _ in twins:
            self._record(project, "DESIGN_EVALUATION")
        run = self._run(project, current, twins, locale, started, scoped)
        project.runs.insert(0, run)
        return _Answer(201, run)

    def _run(
        self,
        project: FakeProject,
        version: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        started: datetime,
        scoped: tuple[str, str] | None = None,
    ) -> dict[str, object]:
        texts = FINDINGS[self.language]
        evaluator = dict(EVALUATOR)
        if scoped is not None:
            evaluator["prompt_version_ref"] = scoped_prompt_version(EVALUATOR["prompt_version_ref"])
        run_id = self._new_id()
        package = version["package"]
        alternative = _by_id(package["alternatives"], str(package["owner_selected_alternative_id"]))
        if alternative is None:
            raise RuntimeError("the review needs the chosen alternative")
        scenario_name, task, outcome = texts["scenario"]
        document = f"{version['id']}:{version['content_hash']}".encode()
        bundle = {
            "id": self._new_id(),
            "project_id": project.id,
            "workflow_run_id": version["id"],
            "scenario": {
                "id": self._new_id(),
                "name": scenario_name,
                "task": task,
                "locale": locale,
                "expected_outcomes": [outcome],
            },
            "artifacts": [
                {
                    "artifact_id": version["id"],
                    "version_number": version["version_number"],
                    "kind": "DOM_SNAPSHOT",
                    "modality": "STRUCTURAL",
                    "media_type": "text/html",
                    "sha256_digest": hashlib.sha256(document).hexdigest(),
                    "size_bytes": len(document),
                    "storage_key": f"sha256/{hashlib.sha256(document).hexdigest()[:2]}/{hashlib.sha256(document).hexdigest()}",
                    "location": "design/mockup.html",
                }
            ],
            "modalities": ["STRUCTURAL"],
            "is_multimodal": False,
            "created_at": _iso(started),
        }
        bundle["content_hash"] = _digest(
            {key: bundle[key] for key in ("project_id", "workflow_run_id", "scenario", "artifacts")}
        )
        earlier = len(project.runs)
        anchors = _anchors(package["prototype"])
        responses = []
        for position, twin in enumerate(twins):
            if position < 2:
                templates = texts["first" if earlier == 0 else "later"][position]
            else:
                templates = (texts["other"],)
            placed = [
                (anchors[template[0]], template[1:], texts["action"]) for template in templates
            ]
            if scoped is not None:
                summary, severity, criterion, action = SCOPED_FINDINGS[self.language]
                placed.insert(0, (scoped, (summary, severity, criterion), action))
            findings = [
                self._finding(
                    number,
                    twin,
                    version,
                    anchor,
                    template,
                    action=action,
                    evaluator=evaluator,
                    scoped=scoped is not None,
                )
                for number, (anchor, template, action) in enumerate(placed, start=1)
            ]
            response = {
                "evaluation_run_id": run_id,
                "artifact_bundle_id": bundle["id"],
                "artifact_bundle_hash": bundle["content_hash"],
                "twin_id": twin["twin_id"],
                "twin_version": twin["version_number"],
                "evaluator": dict(evaluator),
                "findings": findings,
                "summary": texts["summary"].format(name=twin["name"]),
                "evidence_gaps": [],
                "is_simulated_feedback": True,
            }
            response["content_hash"] = _digest(response)
            response["completed_at"] = _iso(self._now())
            response["disclaimer"] = DISCLAIMER
            responses.append(response)
        responses.sort(key=lambda item: str(item["twin_id"]))
        run = {
            "schema_version": 1,
            "id": run_id,
            "project_id": project.id,
            "owner_user_id": project.account.id,
            "design_version_id": version["id"],
            "design_version_number": version["version_number"],
            "design_content_hash": version["content_hash"],
            "alternative_id": alternative["id"],
            "alternative_code": alternative["code"],
            "bundle": bundle,
            "responses": responses,
            "started_at": _iso(started),
            "completed_at": _iso(self._now()),
        }
        run["content_hash"] = _digest(run)
        return run

    def _finding(
        self,
        number: int,
        twin: Mapping[str, object],
        version: Mapping[str, object],
        anchor: tuple[str, str],
        template: Sequence[str],
        *,
        action: str | None = None,
        evaluator: Mapping[str, str] = EVALUATOR,
        scoped: bool = False,
    ) -> dict[str, object]:
        texts = FINDINGS[self.language]
        key, location = anchor
        summary, severity, criterion = template
        finding = create_synthetic_finding(
            finding_id=f"UTF-{number:03d}",
            twin_id=UUID(str(twin["twin_id"])),
            twin_version=int(twin["version_number"]),
            artifact_id=UUID(str(version["id"])),
            artifact_version=int(version["version_number"]),
            location=" ".join(location.split()),
            summary=summary,
            rationale=texts["rationale"],
            criterion=SyntheticFindingCriterion(criterion),
            severity=SyntheticFindingSeverity(severity),
            epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            evidence_refs=(f"artifact:{version['id']}:v{version['version_number']}",),
            confidence=0.6,
            recommended_action=texts["action"] if action is None else action,
            requires_human_validation=True,
            model_config_ref=evaluator["model_config_ref"],
            prompt_version_ref=evaluator["prompt_version_ref"],
        )
        element = anchor_element(key) if scoped else None
        return anchor_finding(finding, key, element).to_snapshot()

    def _route_evaluations(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.runs))

    def _route_comparison(self, call: _Call) -> _Answer:
        project = self._owned(call)
        runs = [] if project is None else [run for run in project.runs if not _scoped_run(run)]
        if not runs:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"})
        head = runs[0]
        evaluator = head["responses"][0]["evaluator"]["evaluator_id"]
        base = next(
            (
                run
                for run in runs[1:]
                if run["responses"][0]["evaluator"]["evaluator_id"] == evaluator
            ),
            None,
        )
        if base is None:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"})
        remaining = _run_findings(head)
        resolved = []
        persisting = []
        for finding in _run_findings(base):
            earlier = synthetic_finding_from_snapshot(finding)
            best, score = None, 0.0
            for candidate in remaining:
                similarity = finding_similarity(earlier, synthetic_finding_from_snapshot(candidate))
                if similarity > score:
                    best, score = candidate, similarity
            if best is not None and score >= MATCH_SIMILARITY:
                remaining.remove(best)
                persisting.append({"before": finding, "after": best})
            else:
                resolved.append(finding)
        return _Answer(
            200,
            {
                "base_run_id": base["id"],
                "head_run_id": head["id"],
                "resolved": resolved,
                "persisting": persisting,
                "introduced": remaining,
                "counts": {
                    "base": len(resolved) + len(persisting),
                    "head": len(remaining) + len(persisting),
                    "resolved": len(resolved),
                    "persisting": len(persisting),
                    "introduced": len(remaining),
                    "dismissed": 0,
                },
            },
        )

    def _review(self, call: _Call) -> tuple[dict[str, object], dict[str, object]]:
        project = self._owned(call)
        run = None if project is None else _by_id(project.runs, call.params["run_id"])
        if project is None or run is None:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_NOT_FOUND"})
        version = _by_id(project.designs, str(run["design_version_id"]))
        if version is None or version["content_hash"] != run["design_content_hash"]:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_NOT_FOUND"})
        if version["package"].get("generated_mockup") is None:
            raise _Refusal(409, {"code": "GENERATED_MOCKUP_REQUIRED"})
        return run, version

    def _route_review_pins(self, call: _Call) -> _Answer:
        run, version = self._review(call)
        return _Answer(200, _pins(run, version))

    def _route_review_document(self, call: _Call) -> _Answer:
        entry_screen = call.value("entry_screen")
        if entry_screen is not None and ENTRY_SCREEN_PATTERN.fullmatch(entry_screen) is None:
            raise _Invalid([_error(("query", "entry_screen"), "string_pattern_mismatch")])
        run, version = self._review(call)
        pins = _pins(run, version)
        bound = version["package"]["generated_mockup"]
        snapshot = bound["mockup"]
        codes = [screen["code"] for screen in snapshot["screens"]]
        entry = codes[0] if entry_screen is None else entry_screen
        if entry not in codes:
            raise _Refusal(422, {"code": "ENTRY_SCREEN_NOT_FOUND"})
        tokens = _tokens(version["package"], str(snapshot["design_alternative_id"]))
        mockup = generated_mockup_from_snapshot(snapshot, token_names=tokens)
        locale = str(run["bundle"]["scenario"]["locale"])
        document = mockup_document(
            mockup,
            tokens=tokens,
            language=locale if LANGUAGE_TAG.fullmatch(locale) else REVIEW_LANGUAGE,
            pins=tuple(
                MockupPin(
                    element_code=pin["element_code"], number=pin["number"], label=pin["label"]
                )
                for pin in pins["pins"]
            ),
            entry_screen=entry,
        )
        return _Answer(
            200,
            {
                "html": document,
                "content_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
                "source": "review",
                "alternative_id": snapshot["design_alternative_id"],
                "title": mockup.title,
                "entry_screen": entry,
                "screens": _screen_list(snapshot),
            },
        )


def _anchor_label(text: str) -> str:
    return text if len(text) <= ANCHOR_LABEL_LENGTH else text[: ANCHOR_LABEL_LENGTH - 1] + "…"


def _anchors(prototype: Mapping[str, object]) -> dict[str, tuple[str, str]]:
    screens = {str(screen["code"]): screen for screen in prototype["screens"]}
    places = {
        code: f"{code} {_anchor_label(str(screen['title']))}" for code, screen in screens.items()
    }
    anchors = {code: (code, place) for code, place in places.items()}
    for role, (code, kinds, last) in ANCHOR_KINDS.items():
        chosen = [item for item in screens[code]["elements"] if item["kind"] in kinds]
        if not chosen:
            anchors[role] = anchors[code]
            continue
        element = chosen[-1] if last else chosen[0]
        label = _anchor_label(str(element["accessible_name"] or element["content"]))
        anchors[role] = (
            f"{code}/{element['code']}",
            f"{places[code]} · {element['code']} {label}",
        )
    return anchors


def _label(summary: str, finding_id: str) -> str:
    text = " ".join(FORBIDDEN_CHARACTERS.sub(" ", summary).split())
    if not text:
        return finding_id
    if len(text) <= PIN_LABEL_LENGTH:
        return text
    return text[: PIN_LABEL_LENGTH - 1].rstrip() + "…"


def _run_findings(run: Mapping[str, object]) -> list[dict[str, object]]:
    return [finding for response in run["responses"] for finding in response["findings"]]


def _placement(
    finding: Mapping[str, object], elements: Mapping[str, str], screens: Sequence[str]
) -> tuple[str, str | None]:
    key = finding.get("anchor_key")
    if isinstance(key, str):
        screen, _, element = key.partition("/")
        if element and elements.get(element) == screen:
            return screen, element
        if screen in screens:
            return screen, None
    match = LEADING_SCREEN.match(str(finding["location"]))
    if match is not None and match[1] in screens:
        return match[1], None
    return screens[0], None


def _pins(run: Mapping[str, object], version: Mapping[str, object]) -> dict[str, object]:
    prototype = version["package"]["prototype"]
    entry = next(
        screen["code"]
        for screen in prototype["screens"]
        if screen["id"] == prototype["entry_screen_id"]
    )
    screens = [
        entry,
        *(screen["code"] for screen in prototype["screens"] if screen["code"] != entry),
    ]
    elements = {
        element["code"]: screen["code"]
        for screen in prototype["screens"]
        for element in screen["elements"]
    }
    pins = []
    unanchored = []
    for number, finding in enumerate(_run_findings(run), start=1):
        screen, element = _placement(finding, elements, screens)
        if element is None:
            unanchored.append(
                {
                    "number": number,
                    "screen_code": screen,
                    "twin_id": finding["twin_id"],
                    "finding_id": finding["finding_id"],
                }
            )
            continue
        pins.append(
            {
                "number": number,
                "element_code": element,
                "screen_code": screen,
                "twin_id": finding["twin_id"],
                "finding_id": finding["finding_id"],
                "severity": finding["severity"],
                "label": _label(str(finding["summary"]), str(finding["finding_id"])),
            }
        )
    return {"design_version_id": run["design_version_id"], "pins": pins, "unanchored": unanchored}


def _review_scope(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("scope", SCOPE_FIELDS, required=False, nullable=True)
    if child is None:
        return None
    screen = child.pattern("screen_code", SCREEN_CODE)
    element = child.pattern("element_code", ELEMENT_CODE, required=False, nullable=True)
    valid = not child.errors
    fields.adopt(child)
    return {"screen_code": screen, "element_code": element} if valid else None


def _scope_of_a_twin_review(scope: Mapping[str, object] | None, mode: str | None) -> None:
    if scope is not None and mode == "STATIC_CHECK":
        raise ValueError("a scope belongs only to the review of the twins")


def _scope_anchor(prototype: Mapping[str, object], scope: Mapping[str, object]) -> tuple[str, str]:
    refusal = _Refusal(422, {"code": DESIGN_EVALUATION_SCOPE_INVALID})
    screen = next(
        (item for item in prototype["screens"] if item["code"] == scope["screen_code"]), None
    )
    if screen is None:
        raise refusal
    place = f"{screen['code']} {_anchor_label(str(screen['title']))}"
    code = scope["element_code"]
    if code is None:
        return str(screen["code"]), place
    element = next((item for item in screen["elements"] if item["code"] == code), None)
    if element is None:
        raise refusal
    label = _anchor_label(str(element["accessible_name"] or element["content"]))
    return f"{screen['code']}/{code}", f"{place} · {code} {label}"


def _scoped_run(run: Mapping[str, object]) -> bool:
    evaluator = run["responses"][0]["evaluator"]
    return str(evaluator["prompt_version_ref"]).endswith(f"+{SCOPED_TWIN_REVIEW_PROMPT_VERSION}")
