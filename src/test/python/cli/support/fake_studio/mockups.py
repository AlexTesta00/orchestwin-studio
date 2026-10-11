from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.generated_mockup_structure import nodes_text
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockup,
    generated_mockup_from_snapshot,
    screen_trees,
)
from orchestwin.models.output_language import dominant_language

from .common import (
    _by_id,
    _change_target,
    _copy,
    _digest,
    _error,
    _mockup_warnings,
    _screen_list,
    _tokens,
    _with_targeted,
)
from .fields import _Fields
from .texts import COSTS
from .values import (
    APPROACHES,
    MAX_OWNER_ASSERTION,
    MAX_OWNER_ASSERTIONS,
    MODEL,
    _Answer,
    _Invalid,
    _iso,
    _JobFailure,
    _Refusal,
)

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject
    from .values import _Job


MAX_ITERATION_REQUEST = 1000
MAX_NEW_ASSERTIONS = 5
DOCUMENT_LANGUAGE = "en"
ITERATION_FIELDS = (
    "design_version_id",
    "design_content_hash",
    "request",
    "assertions",
    "target",
    "critique_source_id",
)
ITERATION_CHANGES = {
    "it": (
        "Il titolo della prima schermata invita a calcolare subito",
        "Il pulsante principale è più grande",
    ),
    "en": (
        "The first screen title invites an immediate calculation",
        "The main button is larger",
    ),
}


class _MockupRoutes:
    def _route_mockup_capabilities(self, call: _Call) -> _Answer:
        return _Answer(
            200,
            {
                "generated_mockups": self.hosted,
                "iterations": self.hosted,
                "model": MODEL if self.hosted else None,
                "paid": self.billing != "SUBSCRIPTION",
                "static_check": False,
            },
        )

    def _route_mockup_generate(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(), ("design_version_id", "design_content_hash", "alternative_id")
        )
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        alternative_id = fields.identifier("alternative_id")
        fields.check()
        current = self._checked_design(self._owned(call), version_id, content_hash)
        if _by_id(current["package"]["alternatives"], str(alternative_id)) is None:
            raise _Refusal(422, {"code": "DESIGN_ALTERNATIVE_NOT_FOUND"})
        self._require_mockup_model()
        raise _Refusal(409, {"code": "GENERATED_MOCKUP_PATH_ACTIVE"})

    def _route_mockup_latest(self, call: _Call) -> _Answer:
        alternative_id = _query_identifier(call, "alternative_id")
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        stored = project.mockups.get(alternative_id)
        if stored is None or _by_id(current["package"]["alternatives"], alternative_id) is None:
            return _Answer(200, None)
        package = copy.deepcopy(stored["package"])
        if stored["design_content_hash"] != current["content_hash"]:
            package = _rebased(current["package"], package)
        if package["owner_selected_alternative_id"] != alternative_id:
            return _Answer(200, None)
        return _Answer(200, {**copy.deepcopy(stored), "package": package})

    def _checked_design(
        self, project: FakeProject | None, version_id: str | None, content_hash: str | None
    ) -> dict[str, object]:
        current = None if project is None else project.design
        if current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if (current["id"], current["content_hash"]) != (version_id, content_hash):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        return current

    def _grounded(self, project: FakeProject, design: Mapping[str, object]) -> bool:
        requirements = project.specification
        reference = design["package"]["grounding"]["requirements_reference"]
        return requirements is not None and (
            requirements["id"],
            requirements["content_hash"],
        ) == (reference["artifact_id"], reference["content_hash"])

    def _require_mockup_model(self) -> None:
        if not self.hosted:
            raise _Refusal(503, {"code": "REAL_MOCKUP_MODEL_NOT_CONFIGURED"})

    def _route_mockup_job(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(), ("design_version_id", "design_content_hash", "alternative_id")
        )
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        alternative_id = fields.identifier("alternative_id")
        fields.check()
        project = self._owned(call)
        current = self._checked_design(project, version_id, content_hash)
        assert project is not None
        alternative = _by_id(current["package"]["alternatives"], str(alternative_id))
        if alternative is None:
            raise _Refusal(422, {"code": "DESIGN_ALTERNATIVE_NOT_FOUND"})
        if alternative.get("visual_language") is None:
            raise _Refusal(422, {"code": "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE"})
        self._require_mockup_model()
        if not self._grounded(project, current):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        self._require_budget(project)
        job = self._start_job(
            call,
            kind="MOCKUP",
            operation="MOCKUP",
            key=f"{content_hash}:{alternative_id}",
            alternative_id=alternative_id,
            work=lambda _job: self._mockup_work(
                project, str(version_id), str(content_hash), str(alternative_id)
            ),
        )
        return _Answer(202, job.payload())

    def _mockup_work(
        self, project: FakeProject, version_id: str, content_hash: str, alternative_id: str
    ) -> dict[str, object]:
        current = project.design
        if current is None or (current["id"], current["content_hash"]) != (
            version_id,
            content_hash,
        ):
            raise _JobFailure("DESIGN_CONTEXT_CHANGED")
        if _by_id(current["package"]["alternatives"], alternative_id) is None:
            raise _JobFailure("DESIGN_ALTERNATIVE_NOT_FOUND")
        if not self._grounded(project, current):
            raise _JobFailure("DESIGN_CONTEXT_CHANGED")
        try:
            generation = self._record(project, "MOCKUP")
        except _Refusal as refusal:
            raise _JobFailure("GENERATION_BUDGET_EXCEEDED") from refusal
        package = self._mockup_package(
            project,
            current["package"],
            alternative_id,
            list(current["package"]["owner_assertions"]),
        )
        result = {
            "status": "MOCKUP_GENERATED",
            "generation_id": generation,
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "package": package,
            "approach": APPROACHES[self.language][0],
            "changes": [],
            "warnings": _mockup_warnings(package, project.specification["specification"]),
            "cost_microusd": COSTS["MOCKUP"],
        }
        project.mockups[alternative_id] = result
        return result

    def _route_mockup_job_view(self, call: _Call) -> _Answer:
        return self._read_job(call, "MOCKUP")

    def _route_mockup_document(self, call: _Call) -> _Answer:
        alternative_id = _query_identifier(call, "alternative_id")
        source = call.value("source") or "latest"
        entry_screen = call.value("entry_screen")
        if source not in ("applied", "latest"):
            raise _Invalid([_error(("query", "source"), "enum")])
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if source == "applied":
            package = current["package"]
            bound = package.get("generated_mockup")
            if bound is None or bound["mockup"]["design_alternative_id"] != alternative_id:
                raise _Refusal(404, {"code": "GENERATED_MOCKUP_NOT_FOUND"})
        else:
            stored = project.mockups.get(alternative_id)
            if stored is None or _by_id(current["package"]["alternatives"], alternative_id) is None:
                raise _Refusal(404, {"code": "GENERATED_MOCKUP_NOT_FOUND"})
            package = stored["package"]
            bound = package.get("generated_mockup")
            if bound is None:
                raise _Refusal(404, {"code": "GENERATED_MOCKUP_NOT_FOUND"})
        codes = [screen["code"] for screen in bound["mockup"]["screens"]]
        entry = codes[0] if entry_screen is None else entry_screen
        if entry not in codes:
            raise _Refusal(422, {"code": "MOCKUP_ENTRY_SCREEN_INVALID"})
        tokens = _tokens(package, alternative_id)
        mockup = generated_mockup_from_snapshot(bound["mockup"], token_names=tokens)
        document = mockup_document(
            mockup, tokens=tokens, language=_document_language(mockup), entry_screen=entry
        )
        return _Answer(
            200,
            {
                "html": document,
                "content_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
                "source": source,
                "alternative_id": alternative_id,
                "title": mockup.title,
                "entry_screen": entry,
                "screens": _screen_list(bound["mockup"]),
            },
        )

    def _route_iteration_job(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ITERATION_FIELDS)
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        request = fields.text("request")
        assertions = fields.texts("assertions", nullable=False, default=[]) or []
        target = _change_target(fields)
        critique_source_id = fields.identifier("critique_source_id", required=False, nullable=True)
        fields.check()
        text, added = _normalized_iteration(request or "", assertions)
        project = self._owned(call)
        current = self._checked_design(project, version_id, content_hash)
        assert project is not None
        if (
            critique_source_id is not None
            and _by_id(project.critique_sources, critique_source_id) is None
        ):
            raise _Refusal(404, {"code": "DESIGN_CRITIQUE_SOURCE_NOT_FOUND"})
        package = current["package"]
        bound = package.get("generated_mockup")
        if bound is None:
            raise _Refusal(409, {"code": "GENERATED_MOCKUP_REQUIRED"})
        _merged_assertions(package["owner_assertions"], added)
        self._require_mockup_model()
        if not self._grounded(project, current):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        self._require_budget(project)
        alternative_id = str(bound["mockup"]["design_alternative_id"])
        job = self._start_job(
            call,
            kind="ITERATION",
            operation="ITERATION",
            key=str(content_hash),
            alternative_id=alternative_id,
            work=lambda job: self._iteration_work(
                job, project, str(version_id), str(content_hash), added, target
            ),
        )
        if not any(record["job_id"] == job.id for record in project.iterations):
            project.iterations.insert(
                0,
                {
                    "job_id": job.id,
                    "generation_id": None,
                    "requested_at": _iso(job.started_at),
                    "request": text,
                    "target": _target_snapshot(target),
                    "critique_source_id": critique_source_id,
                    "assertions": [
                        item for item in added if item not in package["owner_assertions"]
                    ],
                    "changes": [],
                    "failed": None,
                    "package_hash": None,
                    "base_design_version_number": current["version_number"],
                    "cost_microusd": 0,
                },
            )
        return _Answer(202, job.payload())

    def _iteration_work(
        self,
        job: _Job,
        project: FakeProject,
        version_id: str,
        content_hash: str,
        added: Sequence[str],
        target: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        current = project.design
        if current is None or (current["id"], current["content_hash"]) != (
            version_id,
            content_hash,
        ):
            raise _JobFailure("DESIGN_CONTEXT_CHANGED")
        package = current["package"]
        bound = package.get("generated_mockup")
        if bound is None:
            raise _JobFailure("GENERATED_MOCKUP_REQUIRED")
        try:
            merged = _merged_assertions(package["owner_assertions"], added)
        except _Refusal as refusal:
            raise _JobFailure("ITERATION_REQUEST_INVALID") from refusal
        try:
            generation = self._record(project, "ITERATION")
        except _Refusal as refusal:
            raise _JobFailure("GENERATION_BUDGET_EXCEEDED") from refusal
        project.variant += 1
        alternative_id = str(bound["mockup"]["design_alternative_id"])
        proposed = self._mockup_package(project, package, alternative_id, merged)
        changes = _with_targeted(list(ITERATION_CHANGES[self.language]), self.language, target)
        for record in project.iterations:
            if record["job_id"] == job.id:
                record["generation_id"] = generation
                record["changes"] = changes
                record["package_hash"] = _digest(proposed)
                record["cost_microusd"] = COSTS["ITERATION"]
        result = {
            "status": "MOCKUP_GENERATED",
            "generation_id": generation,
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "package": proposed,
            "approach": APPROACHES[self.language][1],
            "changes": changes,
            "warnings": _mockup_warnings(proposed, project.specification["specification"]),
            "cost_microusd": COSTS["ITERATION"],
        }
        project.mockups[alternative_id] = result
        return result

    def _route_iteration_job_view(self, call: _Call) -> _Answer:
        return self._read_job(call, "ITERATION")

    def _route_iterations(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            return _Answer(200, {"items": []})
        applied: dict[str, int] = {}
        for version in project.designs:
            applied.setdefault(str(version["content_hash"]), int(version["version_number"]))
        items = []
        for record in project.iterations:
            if record["generation_id"] is None and record["failed"] is None:
                continue
            number = applied.get(str(record["package_hash"]))
            if record["failed"] is not None:
                status = record["failed"]
            elif number is not None:
                status = "APPLIED"
            else:
                status = "PROPOSED"
            items.append(
                {
                    "generation_id": record["generation_id"],
                    "requested_at": record["requested_at"],
                    "request": record["request"],
                    "target": _copy(record.get("target")),
                    "critique_source_id": record.get("critique_source_id"),
                    "assertions": list(record["assertions"]),
                    "changes": list(record["changes"]),
                    "status": status,
                    "base_design_version_number": record["base_design_version_number"],
                    "applied_design_version_number": number if status == "APPLIED" else None,
                    "cost_microusd": record["cost_microusd"],
                }
            )
        return _Answer(200, {"items": items})


def _query_identifier(call: _Call, name: str) -> str:
    value = call.value(name)
    if value is None:
        raise _Invalid([_error(("query", name), "missing")])
    try:
        return str(UUID(value))
    except ValueError as error:
        raise _Invalid([_error(("query", name), "uuid_parsing")]) from error


def _document_language(mockup: GeneratedMockup) -> str:
    trees = screen_trees(mockup)
    return (
        dominant_language(nodes_text(trees[screen.code]) for screen in mockup.screens)
        or DOCUMENT_LANGUAGE
    )


def _control(text: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) < 160 for character in text)


def _normalized_iteration(request: str, assertions: Sequence[str]) -> tuple[str, list[str]]:
    invalid = _Refusal(422, {"code": "ITERATION_REQUEST_INVALID"})
    text = " ".join(request.split())
    if not 1 <= len(text) <= MAX_ITERATION_REQUEST or _control(text):
        raise invalid
    if len(assertions) > MAX_NEW_ASSERTIONS:
        raise invalid
    added: list[str] = []
    for item in assertions:
        normalized = " ".join(item.split())
        if not 1 <= len(normalized) <= MAX_OWNER_ASSERTION or _control(normalized):
            raise invalid
        if normalized not in added:
            added.append(normalized)
    return text, added


def _rebased(current: Mapping[str, object], package: Mapping[str, object]) -> dict[str, object]:
    kept = list(current["owner_assertions"])
    assertions = [*kept, *(item for item in package["owner_assertions"] if item not in kept)]
    return {
        **copy.deepcopy(dict(current)),
        "owner_selected_alternative_id": package["owner_selected_alternative_id"],
        "prototype": copy.deepcopy(package["prototype"]),
        "generated_mockup": copy.deepcopy(package["generated_mockup"]),
        "owner_assertions": assertions if len(assertions) <= MAX_OWNER_ASSERTIONS else kept,
    }


def _merged_assertions(current: Sequence[str], added: Sequence[str]) -> list[str]:
    merged = [*current, *(item for item in added if item not in current)]
    if len(merged) > MAX_OWNER_ASSERTIONS:
        raise _Refusal(422, {"code": "ITERATION_REQUEST_INVALID"})
    return merged


def _target_snapshot(target: Mapping[str, object] | None) -> dict[str, object] | None:
    if target is None:
        return None
    return {name: value for name, value in target.items() if value is not None}
