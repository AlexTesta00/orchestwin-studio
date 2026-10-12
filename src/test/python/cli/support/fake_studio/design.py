from __future__ import annotations

import copy
import html
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.artifacts.bound_mockups import create_bound_mockup, markup_requirement_codes
from orchestwin.artifacts.design_distance import design_distance_report
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockup,
    create_generated_mockup,
    generated_mockup_from_snapshot,
)
from orchestwin.artifacts.visual_catalog import VisualChoices
from orchestwin.artifacts.visual_directions import (
    AXIS_BINDINGS,
    DIRECTION_AXES,
    DIRECTION_CANDIDATES,
    DirectionAxes,
    VisualDirection,
    create_visual_direction,
)
from orchestwin.artifacts.visual_language import TwinFit, create_visual_language
from orchestwin.knowledge.state import MAX_DESIGN_REQUEST_LENGTH
from orchestwin.models.design_systems import APPLE_HIG, system_direction
from orchestwin.models.fake_design import (
    _ALTERNATIVE_TEMPLATES,
    FAKE_DESIGN_PROVIDER_ID,
    FAKE_DESIGN_PROVIDER_VERSION,
)

from .common import (
    _blank_to_none,
    _bounded,
    _by_id,
    _change_target,
    _checked_target,
    _digest,
    _error,
    _event_payload,
    _fake_design,
    _gate_payload,
    _identifiers,
    _plain_reference,
    _stamp,
    _with_targeted,
)
from .fields import _Fields, _gate_decision
from .texts import (
    ALIGNMENT_TEXTS,
    ALTERNATIVES,
    CRITIQUES,
    DESIGN_TEXTS,
    DIRECTED_ALTERNATIVES,
    DIRECTION_TEXTS,
    LANDMARK_SCREENS,
    MOCKUP_STYLES,
    SCREENS,
    SYSTEM_ALTERNATIVES,
    WORKFLOW_STEPS,
)
from .values import (
    GATE_ACTIONS,
    MAX_OWNER_ASSERTION,
    MAX_OWNER_ASSERTIONS,
    _Answer,
    _Invalid,
    _Refusal,
)

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject
    from .values import _Account


DESIGNER = "UX_UI_DESIGNER"
DESIGN_CHANGE_FIELDS = ("request", "target")
DESIGN_OPEN_QUESTIONS = (
    "Which proposed direction should the owner select for declarative prototyping?",
    "Which trade-offs require validation with target users before implementation?",
)
DESIGN_TRUST_CONCERN = (
    "The proposal does not establish how real users will interpret or trust this design."
)
DESIGN_CRITIQUE_RATIONALE = (
    "This deterministic critique translates approved User Twin observations into a design "
    "hypothesis. It is simulated feedback, not empirical evidence."
)
ITERATED_HEADING = {"it": "Calcola la mancia in un tocco", "en": "Work out the tip in one tap"}


class _DesignRoutes:
    def _design_package(self, project: FakeProject) -> dict[str, object]:
        requirements = project.specification
        team = project.team
        snapshot = project.snapshot
        if requirements is None or team is None or snapshot is None:
            raise RuntimeError("design needs requirements, team and twins")
        twins = sorted(
            (dict(item) for item in requirements["specification"]["user_twin_references"]),
            key=lambda twin: str(twin["twin_id"]),
        )
        grounding = _grounding(requirements, team, snapshot, twins)
        if self.hosted:
            return self._hosted_package(project, twins, grounding)
        return self._deterministic_package(project, requirements, twins, grounding)

    def _deterministic_package(
        self,
        project: FakeProject,
        requirements: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        grounding: Mapping[str, object],
    ) -> dict[str, object]:
        specification = requirements["specification"]
        stories = list(specification["user_stories"])
        goal = _bounded(str(stories[0]["goal"]))
        references = [
            (grounding[key], summary)
            for key, summary in (
                ("requirements_reference", "Approved Requirements baseline used by design."),
                ("agent_team_reference", "Approved Agent Team used by design."),
                ("user_modeling_reference", "Approved User Modeling state used by design."),
            )
        ]
        alternatives: list[dict[str, object]] = []
        critiques: list[dict[str, object]] = []
        concerns: list[dict[str, object]] = []
        for ordinal, template in enumerate(_ALTERNATIVE_TEMPLATES, start=1):
            approach = template.approach.value
            direction = approach.casefold().replace("_", " ")
            code = f"DES-{ordinal:03d}"
            language = create_visual_language(
                choices=template.visual,
                product_name=template.product_name,
                rationale=template.visual_rationale,
                twin_fit=tuple(
                    TwinFit(
                        twin_id=UUID(str(twin["twin_id"])),
                        name=str(twin["name"]),
                        statement=f"{template.product_name} keeps the {direction} direction "
                        f"legible and predictable for {twin['name']}.",
                    )
                    for twin in twins
                ),
            )
            alternative_id = self._new_id()
            alternatives.append(
                {
                    "id": alternative_id,
                    "code": code,
                    "approach": approach,
                    "title": f"{template.title_prefix}: {goal}",
                    "summary": template.summary,
                    "rationale": template.rationale,
                    "requirement_ids": list(grounding["requirement_ids"]),
                    "user_story_ids": list(grounding["user_story_ids"]),
                    "acceptance_criterion_ids": list(grounding["acceptance_criterion_ids"]),
                    "user_twin_references": copy.deepcopy(list(twins)),
                    "workflows": [
                        {
                            "id": self._new_id(),
                            "code": f"FLOW-{index:03d}",
                            "title": f"{template.title_prefix}: {_bounded(str(story['goal']))}",
                            "steps": [
                                step.format(code=story["code"]) for step in WORKFLOW_STEPS[approach]
                            ],
                            "requirement_ids": list(story["requirement_ids"]),
                            "user_story_ids": [story["id"]],
                        }
                        for index, story in enumerate(stories, start=1)
                    ],
                    "information_architecture": list(template.information_architecture),
                    "accessibility_considerations": list(template.accessibility_considerations),
                    "security_considerations": list(template.security_considerations),
                    "advantages": list(template.advantages),
                    "trade_offs": list(template.trade_offs),
                    "assumptions": [],
                    "open_questions": [template.open_question],
                    "visual_language": language.to_snapshot(),
                }
            )
            for twin in twins:
                observations = self._twin_observations(project, twin)
                grounded = next(
                    item
                    for item in observations
                    if item["value"]["kind"] in ("TEXT", "ITEMS")
                    and item["epistemic_status"] != "UNSUPPORTED_ASSUMPTION"
                )
                context = (
                    grounded["value"]["text"] or twin["name"]
                    if grounded["value"]["kind"] == "TEXT"
                    else grounded["value"]["items"][0]
                )
                provenance = [
                    dict(reference) for item in observations for reference in item["provenance"]
                ]
                for reference, summary in references:
                    evidence = {
                        "source_kind": "SYSTEM_ARTIFACT",
                        "source_id": reference["artifact_id"],
                        "source_version": reference["version_number"],
                        "content_hash": reference["content_hash"],
                        "locator": str(reference["kind"]).casefold(),
                        "summary": summary,
                    }
                    provenance.append(evidence)
                provenance.append(
                    {
                        "source_kind": "MODEL_OUTPUT",
                        "source_id": FAKE_DESIGN_PROVIDER_ID,
                        "source_version": FAKE_DESIGN_PROVIDER_VERSION,
                        "content_hash": None,
                        "locator": f"alternatives.{code}.user_twins.{twin['twin_id']}"
                        f".v{twin['version_number']}",
                        "summary": "Deterministic synthetic design critique generated from "
                        "governed inputs.",
                    }
                )
                critiques.append(
                    {
                        "id": self._new_id(),
                        "code": f"CRQ-{len(critiques) + 1:03d}",
                        "kind": "SYNTHETIC_USER_TWIN",
                        "design_alternative_id": alternative_id,
                        "user_twin_reference": dict(twin),
                        "strengths": [
                            f"The {direction} direction keeps every proposed workflow linked "
                            "to approved requirements and user stories."
                        ],
                        "concerns": [
                            f"The main trade-off remains hypothetical for {twin['name']}: "
                            f"{template.trade_offs[0]}"
                        ],
                        "unmet_needs": [
                            "The approved profile does not provide concrete content for "
                            f"{item['observation_key']}."
                            for item in observations
                            if item["value"]["kind"] in ("UNKNOWN", "ABSTAINED")
                        ],
                        "accessibility_observations": [template.accessibility_considerations[0]],
                        "trust_concerns": [DESIGN_TRUST_CONCERN],
                        "questions": [
                            f"During human validation, does this direction support "
                            f"{twin['name']} without contradicting the approved profile "
                            f"context: {_bounded(str(context), 180)}?"
                        ],
                        "suggested_changes": [template.concern_mitigation],
                        "provenance": _unique(provenance),
                        "confidence": 0.6,
                        "epistemic_status": "MODEL_INFERRED",
                        "human_validation": "REQUIRED",
                        "rationale": DESIGN_CRITIQUE_RATIONALE,
                        "verdict": None,
                        "quote": None,
                    }
                )
            concerns.append(
                {
                    "id": self._new_id(),
                    "code": f"DRK-{ordinal:03d}",
                    "summary": template.concern_summary,
                    "mitigation": template.concern_mitigation,
                    "requirement_ids": list(grounding["requirement_ids"]),
                    "design_alternative_ids": [alternative_id],
                }
            )
        return {
            "schema_version": 1,
            "project_id": project.id,
            "grounding": copy.deepcopy(dict(grounding)),
            "alternatives": alternatives,
            "critiques": critiques,
            "recommended_alternative_id": alternatives[0]["id"],
            "owner_selected_alternative_id": None,
            "prototype": None,
            "concerns": concerns,
            "open_questions": list(DESIGN_OPEN_QUESTIONS),
            "generated_mockup": None,
            "owner_assertions": [],
        }

    def _twin_observations(
        self, project: FakeProject, twin: Mapping[str, object]
    ) -> list[Mapping[str, object]]:
        for version in project.twins.get(str(twin["twin_id"]), []):
            if version["version_number"] == twin["version_number"]:
                return list(version["profile"]["observations"])
        raise RuntimeError("the design needs the twins of its grounding")

    def _hosted_package(
        self,
        project: FakeProject,
        twins: Sequence[Mapping[str, object]],
        grounding: Mapping[str, object],
    ) -> dict[str, object]:
        requirement_ids = list(grounding["requirement_ids"])
        story_ids = list(grounding["user_story_ids"])
        criterion_ids = list(grounding["acceptance_criterion_ids"])
        texts = DESIGN_TEXTS[self.language]
        workflow_title, workflow_steps = texts["workflow"]
        alternatives = []
        fits = tuple(
            TwinFit(
                twin_id=UUID(str(twin["twin_id"])),
                name=str(twin["name"]),
                statement=texts["fit"].format(name=twin["name"]),
            )
            for twin in twins
        )
        system = SYSTEM_ALTERNATIVES[self.language] if self.design_system else None
        for spec in (*ALTERNATIVES[self.language], *(() if system is None else (system,))):
            if spec is system:
                direction = system_direction(APPLE_HIG)
            elif self.directions:
                direction = self._direction(spec["code"])
            else:
                direction = None
            language = create_visual_language(
                choices=VisualChoices.from_snapshot(_choices(spec, direction)),
                product_name=spec["product_name"],
                rationale=spec["rationale"],
                twin_fit=fits,
                direction=direction,
                design_system=APPLE_HIG if spec is system else None,
            )
            alternatives.append(
                {
                    "id": self._new_id(),
                    "code": spec["code"],
                    "approach": spec["approach"],
                    "title": spec["title"],
                    "summary": spec["summary"],
                    "rationale": spec["rationale"],
                    "requirement_ids": list(requirement_ids),
                    "user_story_ids": list(story_ids),
                    "acceptance_criterion_ids": list(criterion_ids),
                    "user_twin_references": copy.deepcopy(list(twins)),
                    "workflows": [
                        {
                            "id": self._new_id(),
                            "code": "FLOW-001",
                            "title": workflow_title,
                            "steps": list(workflow_steps),
                            "requirement_ids": requirement_ids[:2],
                            "user_story_ids": story_ids[:1],
                        }
                    ],
                    "information_architecture": list(texts["architecture"]),
                    "accessibility_considerations": list(texts["accessibility"]),
                    "security_considerations": list(texts["security"]),
                    "advantages": list(texts["advantages"]),
                    "trade_offs": list(texts["trade_offs"]),
                    "assumptions": list(texts["assumptions"]),
                    "open_questions": list(texts["questions"]),
                    "visual_language": language.to_snapshot(),
                }
            )
        critiques = []
        for alternative in alternatives:
            verdicts = CRITIQUES[self.language][alternative["code"]]
            for index, twin in enumerate(twins):
                verdict, quote = verdicts[index % len(verdicts)]
                critiques.append(
                    {
                        "id": self._new_id(),
                        "code": f"CRQ-{len(critiques) + 1:03d}",
                        "kind": "SYNTHETIC_USER_TWIN",
                        "design_alternative_id": alternative["id"],
                        "user_twin_reference": dict(twin),
                        "strengths": [texts["strength"]],
                        "concerns": [quote],
                        "unmet_needs": [],
                        "accessibility_observations": [],
                        "trust_concerns": [],
                        "questions": [],
                        "suggested_changes": [texts["suggestion"]],
                        "provenance": [
                            {
                                "source_kind": "MODEL_OUTPUT",
                                "source_id": alternative["id"],
                                "source_version": None,
                                "content_hash": None,
                                "locator": alternative["code"],
                                "summary": None,
                            }
                        ],
                        "confidence": 0.6,
                        "epistemic_status": "MODEL_INFERRED",
                        "human_validation": "REQUIRED",
                        "rationale": texts["rationale"],
                        "verdict": verdict,
                        "quote": quote,
                    }
                )
        concern, mitigation = texts["concern"]
        return {
            "schema_version": 1,
            "project_id": project.id,
            "grounding": copy.deepcopy(dict(grounding)),
            "alternatives": alternatives,
            "critiques": critiques,
            "recommended_alternative_id": alternatives[1]["id"],
            "owner_selected_alternative_id": None,
            "prototype": None,
            "concerns": [
                {
                    "id": self._new_id(),
                    "code": "DRK-001",
                    "summary": concern,
                    "mitigation": mitigation,
                    "requirement_ids": requirement_ids[-1:],
                    "design_alternative_ids": [alternatives[1]["id"]],
                }
            ],
            "open_questions": list(texts["questions"]),
            "generated_mockup": None,
            "owner_assertions": [],
        }

    def _direction(self, code: str) -> VisualDirection:
        axes, typicality = DIRECTED_ALTERNATIVES[code]
        name, concept, rules = DIRECTION_TEXTS[self.language][code]
        return create_visual_direction(
            name=name,
            concept=concept,
            rules=rules,
            axes=DirectionAxes(**axes),
            typicality=typicality,
            candidates=DIRECTION_CANDIDATES,
        )

    def _append_design(
        self, project: FakeProject, package: dict[str, object], account: _Account
    ) -> dict[str, object]:
        previous = project.design
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_design(package).content_hash,
            "package": package,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "ready_for_gate": package["owner_selected_alternative_id"] is not None
            and package["prototype"] is not None,
        }
        project.designs.append(version)
        return version

    def _screens(self, code: str, variant: int) -> list[dict[str, object]]:
        screens = []
        screens_of = SCREENS[self.language]
        drawn = (
            LANDMARK_SCREENS[self.language]
            if self.landmarks
            else screens_of.get(code) or screens_of["DES-001"]
        )
        for index, (screen, title, state, heading, markup) in enumerate(drawn):
            shown = ITERATED_HEADING[self.language] if index == 0 and variant > 0 else heading
            screens.append(
                {
                    "code": screen,
                    "title": title,
                    "state": state,
                    "markup": markup.format(heading=html.escape(shown, quote=False)),
                }
            )
        return screens

    def _generated(
        self,
        alternative: Mapping[str, object],
        variant: int,
        specification: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        language = alternative["visual_language"]
        identifiers = {
            str(item["code"]): UUID(str(item["id"])) for item in specification["requirements"]
        }

        def current_codes(match):
            codes = [code for code in match.group(2).split() if code in identifiers]
            if not codes:
                codes = [next(iter(identifiers))]
            return f" data-req={match.group(1)}{' '.join(codes)}{match.group(1)}" if codes else ""

        screens = self._screens(str(alternative["code"]), variant)
        for screen in screens:
            screen["markup"] = re.sub(r" data-req=([\"'])(.*?)\1", current_codes, screen["markup"])
        mockup = create_generated_mockup(
            design_alternative_id=UUID(str(alternative["id"])),
            title=str(language["product_name"]),
            styles=MOCKUP_STYLES,
            screens=screens,
            token_names=language["tokens"],
        )
        bound = create_bound_mockup(
            mockup=mockup,
            requirement_ids_by_code={
                code: identifiers[code] for code in markup_requirement_codes(mockup)
            },
        )
        return bound.to_snapshot(), bound.prototype().to_snapshot()

    def _mockup_package(
        self,
        project: FakeProject,
        package: Mapping[str, object],
        alternative_id: str,
        assertions: Sequence[str],
    ) -> dict[str, object]:
        result = copy.deepcopy(dict(package))
        alternative = _by_id(result["alternatives"], alternative_id)
        requirements = project.specification
        if alternative is None or requirements is None:
            raise RuntimeError("the mockup needs its alternative and requirements")
        bound, prototype = self._generated(
            alternative, project.variant, requirements["specification"]
        )
        result["owner_selected_alternative_id"] = alternative_id
        result["prototype"] = prototype
        result["generated_mockup"] = bound if self.hosted else None
        result["owner_assertions"] = list(assertions)
        return result

    def _governed_design(self, call: _Call) -> tuple[FakeProject, dict[str, object]]:
        project = self._owned(call)
        design = None if project is None else project.design
        if project is None or design is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        return project, design

    def _route_design_proposal(self, call: _Call) -> _Answer:
        return self._later(call, "DESIGN_PROPOSAL", {}, lambda: self._generated_design(call))

    def _generated_design(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        if not self._approvals(project)["requirements"]:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if project.design is not None:
            raise _Refusal(409, {"code": "DESIGN_PACKAGE_ALREADY_EXISTS"})
        if not self._has_designer(project):
            self._refuse_without_designer()
            raise _Refusal(
                409, {"code": "PROPOSAL_REJECTED", "proposal_issue": "UX_DESIGNER_REQUIRED"}
            )
        self._record_directions(project)
        self._record(project, "DESIGN_PROPOSAL")
        version = self._append_design(project, self._design_package(project), call.account)
        return _Answer(201, _generation_payload("CREATED", version, None))

    def _record_directions(self, project: FakeProject) -> None:
        if self.directions:
            self._record(project, "DESIGN_DIRECTIONS")

    def _has_designer(self, project: FakeProject) -> bool:
        team = project.team
        return team is not None and DESIGNER in team["selected_agent_ids"]

    def _refuse_without_designer(self) -> None:
        if self.hosted:
            raise _Refusal(502, {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"})

    def _route_design_regeneration(self, call: _Call) -> _Answer:
        return self._later(call, "DESIGN_REGENERATION", {}, lambda: self._regenerated(call))

    def _regenerated(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            return _Answer(201, _generation_payload("REJECTED", None, "PROJECT_NOT_FOUND"))
        if not self._approvals(project)["requirements"]:
            return _Answer(
                201, _generation_payload("REJECTED", None, "REQUIREMENTS_APPROVAL_REQUIRED")
            )
        if project.design is None:
            return _Answer(201, _generation_payload("REJECTED", None, "DESIGN_PACKAGE_NOT_FOUND"))
        if not self._has_designer(project):
            self._refuse_without_designer()
            return _Answer(
                201,
                _generation_payload(
                    "REJECTED", None, "PROPOSAL_REJECTED", proposal_issue="UX_DESIGNER_REQUIRED"
                ),
            )
        self._record_directions(project)
        self._record(project, "DESIGN_REGENERATION")
        version = self._append_design(project, self._design_package(project), call.account)
        return _Answer(201, _generation_payload("CREATED", version, None))

    def _route_design_current(self, call: _Call) -> _Answer:
        return _Answer(200, self._governed_design(call)[1])

    def _route_design_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.designs))

    def _route_design_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        version = None if project is None else project.design
        gate = None if project is None else project.gates.get("design")
        approved = (
            project is not None and version is not None and self._approvals(project)["design"]
        )
        if version is None:
            status = "DESIGN_REQUIRED"
        elif not version["ready_for_gate"]:
            status = "DESIGN_REVIEW_REQUIRED"
        elif approved:
            status = "READY_FOR_ARCHITECTURE_PLANNING"
        else:
            status = "DESIGN_APPROVAL_REQUIRED"
        return _Answer(
            200,
            {
                "status": status,
                "version": version,
                "gate": None if gate is None else _gate_payload(gate),
                "has_package": version is not None,
                "package_ready_for_gate": version is not None and bool(version["ready_for_gate"]),
                "approved_current_package": bool(approved),
            },
        )

    def _route_design_distance(self, call: _Call) -> _Answer:
        from orchestwin.api.design_distance import DesignDistancePayload

        project, design = self._governed_design(call)
        version = _design_version(design)
        report = design_distance_report(version, _kept_mockups(project, design))
        return _Answer(200, DesignDistancePayload.model_validate(report).model_dump(mode="json"))

    def _route_design_revision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("package",))
        package = fields.value("package")
        fields.check()
        _check_package(package)
        assert isinstance(package, dict)
        if str(UUID(str(package["project_id"]))) != call.project_id:
            raise _Refusal(422, {"code": "DESIGN_PROJECT_MISMATCH"})
        if not _coherent_package(package):
            raise _Refusal(422, {"code": "INVALID_DESIGN_PACKAGE"})
        package["project_id"] = call.project_id
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "PACKAGE_NOT_FOUND"})
        diff = self._design_diff(project, current, package, call.account)
        return _Answer(201, _design_revision_payload("CREATED", diff, None))

    def _pending_design_diff(self, project: FakeProject) -> dict[str, object] | None:
        current = project.design
        return next(
            (
                diff
                for diff in project.design_diffs
                if current is not None
                and diff["status"] == "PROPOSED"
                and diff["base_version_id"] == current["id"]
            ),
            None,
        )

    def _route_design_change(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), DESIGN_CHANGE_FIELDS)
        request = fields.text("request")
        target = _change_target(fields)
        fields.check()
        text = (request or "").strip()
        if not 1 <= len(text) <= MAX_DESIGN_REQUEST_LENGTH:
            raise _Invalid([_error(("body", "request"), "value_error")])
        return self._later(
            call,
            "DESIGN_CHANGE",
            {"request": text, "target": target},
            lambda: self._changed_design(call, text, target),
        )

    def _changed_design(
        self, call: _Call, text: str, target: Mapping[str, object] | None = None
    ) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        design = project.design
        if design is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        package = design["package"]
        selected = package["owner_selected_alternative_id"]
        chosen = None if selected is None else _by_id(package["alternatives"], str(selected))
        if chosen is None:
            raise _Refusal(409, {"code": "DESIGN_ALTERNATIVE_NOT_CHOSEN"})
        if self._pending_design_diff(project) is not None:
            raise _Refusal(409, {"code": "DESIGN_REVISION_PENDING"})
        if project.specification is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"})
        if not self.hosted:
            raise _Refusal(503, {"code": "DESIGN_CHANGE_MODEL_NOT_CONFIGURED"})
        _checked_target(package, target)
        self._record(project, "DESIGN_CHANGE")
        sentence = " ".join(text.split())
        proposed = copy.deepcopy(package)
        changed = _by_id(proposed["alternatives"], str(selected))
        if changed is None or sentence in str(changed["summary"]):
            raise _Refusal(409, {"code": "DESIGN_UNCHANGED"})
        changed["summary"] = f"{changed['summary']} {sentence}"
        diff = self._design_diff(project, design, proposed, call.account)
        changes = _with_targeted(
            [
                ALIGNMENT_TEXTS[self.language]["design_change"].format(
                    title=changed["title"], request=sentence
                )
            ],
            self.language,
            target,
        )
        return _Answer(
            201, {"revision": _design_revision_payload("CREATED", diff, None), "changes": changes}
        )

    def _design_diff(
        self,
        project: FakeProject,
        current: Mapping[str, object],
        package: dict[str, object],
        account: _Account,
    ) -> dict[str, object]:
        if self._pending_design_diff(project) is not None:
            raise _Refusal(409, {"code": "DIFF_ALREADY_PENDING"})
        before = current["package"]
        if sorted(str(item["id"]) for item in before["alternatives"]) != sorted(
            str(item.get("id")) for item in package["alternatives"]
        ):
            raise _Refusal(409, {"code": "IDENTIFIER_CHANGED"})
        changes = _design_changes(before, package)
        if not changes:
            raise _Refusal(409, {"code": "NO_CHANGES"})
        diff = {
            "id": self._new_id(),
            "project_id": project.id,
            "owner_user_id": account.id,
            "base_version_id": current["id"],
            "base_version_number": current["version_number"],
            "base_content_hash": current["content_hash"],
            "proposed_package": package,
            "proposal_hash": _digest(package),
            "changes": changes,
            "status": "PROPOSED",
            "created_at": _stamp(self._now()),
            "decided_by_user_id": None,
            "decided_at": None,
            "decision_reason": None,
            "applied_version_id": None,
        }
        diff["content_hash"] = _digest(diff)
        project.design_diffs.append(diff)
        return diff

    def _route_design_revisions(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.design_diffs))

    def _route_design_revision_view(self, call: _Call) -> _Answer:
        project = self._owned(call)
        diff = _by_id([] if project is None else project.design_diffs, call.params["diff_id"])
        if diff is None:
            raise _Refusal(404, {"code": "DESIGN_DIFF_NOT_FOUND"})
        return _Answer(200, diff)

    def _route_design_revision_decision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("decision", "reason"))
        decision = fields.choice("decision", ("APPROVE", "REJECT"))
        reason = fields.text("reason", required=False, nullable=True)
        fields.check()
        project = self._owned(call)
        diff = _by_id([] if project is None else project.design_diffs, call.params["diff_id"])
        if project is None or diff is None:
            raise _Refusal(404, {"code": "DIFF_NOT_FOUND"})
        current = project.design
        if current is None:
            raise _Refusal(404, {"code": "PACKAGE_NOT_FOUND"})
        if (current["id"], current["version_number"], current["content_hash"]) != (
            diff["base_version_id"],
            diff["base_version_number"],
            diff["base_content_hash"],
        ):
            raise _Refusal(409, {"code": "CONTEXT_CHANGED"})
        if diff["status"] != "PROPOSED":
            raise _Refusal(409, {"code": "DIFF_ALREADY_DECIDED"})
        normalized = _blank_to_none(reason)
        if decision == "REJECT" and normalized is None:
            raise _Refusal(409, {"code": "REASON_REQUIRED"})
        version = None
        if decision == "APPROVE":
            version = self._append_design(
                project, copy.deepcopy(diff["proposed_package"]), call.account
            )
            diff["applied_version_id"] = version["id"]
        diff["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
        diff["decided_by_user_id"] = call.account.id
        diff["decided_at"] = _stamp(self._now())
        diff["decision_reason"] = normalized
        diff["content_hash"] = _digest(
            {key: value for key, value in diff.items() if key != "content_hash"}
        )
        return _Answer(200, _design_revision_payload("APPLIED", diff, version))

    def _route_design_restore(self, call: _Call) -> _Answer:
        from orchestwin.api.design import DESIGN_RESTORED, RESTORE_NOTES

        fields = _Fields(call.json(), ("version_number", "locale"))
        number = fields.integer("version_number", minimum=1)
        locale = fields.text("locale", required=False, minimum=2, maximum=20, default="it-IT")
        fields.check()
        assert number is not None and locale is not None
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "PACKAGE_NOT_FOUND"})
        if number == current["version_number"]:
            raise _Refusal(409, {"code": "DESIGN_RESTORE_CURRENT"})
        restored = next(
            (item for item in project.designs if item["version_number"] == number), None
        )
        if restored is None:
            raise _Refusal(404, {"code": "DESIGN_VERSION_NOT_FOUND"})
        if self._pending_design_diff(project) is not None:
            raise _Refusal(409, {"code": "DIFF_ALREADY_PENDING"})
        package = copy.deepcopy(restored["package"])
        package["grounding"] = copy.deepcopy(current["package"]["grounding"])
        if _fake_design(package).content_hash == current["content_hash"]:
            raise _Refusal(409, {"code": "DESIGN_RESTORE_CURRENT"})
        language = "en" if locale.strip().lower().startswith("en") else "it"
        note = RESTORE_NOTES[language].format(number=number)
        changes = _design_changes(current["package"], package)
        version = self._append_design(project, package, call.account)
        moment = _stamp(self._now())
        diff = {
            "id": self._new_id(),
            "project_id": project.id,
            "owner_user_id": call.account.id,
            "base_version_id": current["id"],
            "base_version_number": current["version_number"],
            "base_content_hash": current["content_hash"],
            "proposed_package": copy.deepcopy(package),
            "proposal_hash": _digest(package),
            "changes": changes,
            "status": "APPROVED",
            "created_at": moment,
            "decided_by_user_id": call.account.id,
            "decided_at": moment,
            "decision_reason": note,
            "applied_version_id": version["id"],
        }
        diff["content_hash"] = _digest(diff)
        project.design_diffs.append(diff)
        return _Answer(
            201,
            {
                "reason": DESIGN_RESTORED,
                "restored_version_number": number,
                "note": note,
                "revision": _design_revision_payload("APPLIED", diff, version),
            },
        )

    def _route_design_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        design = None if project is None else project.design
        if project is None or design is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if not design["ready_for_gate"]:
            raise _Refusal(409, {"code": "PACKAGE_NOT_READY"})
        status, gate, events, issue = self._submit_gate(
            project, "design", self._require_reference(project, "design")
        )
        if status not in {"SUBMITTED", "ALREADY_PENDING", "ALREADY_APPROVED"}:
            raise _Refusal(409, {"code": status})
        return _Answer(
            200,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "issue": issue,
            },
        )

    def _route_design_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, GATE_ACTIONS, literal=False, maximum=None)
        project = self._owned(call)
        if project is None or project.design is None:
            raise _Refusal(404, {"code": "PACKAGE_NOT_FOUND"})
        return self._stage_decision(project, "design", action, reason)

    def _route_design_gate_current(self, call: _Call) -> _Answer:
        return self._stage_gate(call, "design", "DESIGN_GATE_NOT_FOUND")

    def _route_design_gate_events(self, call: _Call) -> _Answer:
        return self._stage_events(call, "design", "DESIGN_GATE_NOT_FOUND")


def _grounding(
    requirements: Mapping[str, object],
    team: Mapping[str, object],
    snapshot: Mapping[str, object],
    twins: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    specification = requirements["specification"]
    return {
        "requirements_reference": {
            "kind": "REQUIREMENTS_SPECIFICATION",
            **_plain_reference(requirements),
        },
        "agent_team_reference": {"kind": "AGENT_TEAM", **_plain_reference(team)},
        "user_modeling_reference": {"kind": "USER_MODELING", **_plain_reference(snapshot)},
        "catalog": {"version": AGENT_CATALOG_VERSION, "content_hash": AGENT_CATALOG_CONTENT_HASH},
        "requirement_ids": _identifiers(specification["requirements"]),
        "user_story_ids": _identifiers(specification["user_stories"]),
        "acceptance_criterion_ids": _identifiers(specification["acceptance_criteria"]),
        "user_twin_references": [dict(twin) for twin in twins],
    }


def _unique(items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    unique: list[dict[str, object]] = []
    for item in items:
        if dict(item) not in unique:
            unique.append(dict(item))
    return unique


def _design_version(design: Mapping[str, object]) -> DesignPackageVersion:
    return DesignPackageVersion(
        id=UUID(str(design["id"])),
        project_id=UUID(str(design["project_id"])),
        version_number=int(design["version_number"]),
        package=_fake_design(design["package"]),
        content_hash=str(design["content_hash"]),
        created_by_user_id=UUID(str(design["created_by_user_id"])),
        created_at=datetime.fromisoformat(str(design["created_at"])),
        based_on_version_number=design["based_on_version_number"],
    )


def _kept_mockups(
    project: FakeProject, design: Mapping[str, object]
) -> dict[UUID, GeneratedMockup]:
    package = design["package"]
    applied = package.get("generated_mockup")
    mockups: dict[UUID, GeneratedMockup] = {}
    for alternative in package["alternatives"]:
        identifier = str(alternative["id"])
        bound = applied
        if bound is None or str(bound["mockup"]["design_alternative_id"]) != identifier:
            stored = project.mockups.get(identifier)
            bound = None if stored is None else stored["package"].get("generated_mockup")
        language = alternative.get("visual_language")
        if bound is None or language is None:
            continue
        mockups[UUID(identifier)] = generated_mockup_from_snapshot(
            bound["mockup"], token_names=language["tokens"]
        )
    return mockups


def _design_revision_payload(
    status: str, diff: Mapping[str, object], version: Mapping[str, object] | None
) -> dict[str, object]:
    return {
        "status": status,
        "diff": diff,
        "version": version,
        "issue": None,
        "domain_issue": None,
        "diff_persistence_status": None,
        "version_persistence_status": None,
    }


def _generation_payload(
    status: str,
    version: Mapping[str, object] | None,
    issue: str | None,
    *,
    proposal_issue: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "version": version,
        "issue": issue,
        "proposal_issue": proposal_issue,
        "persistence_status": "APPENDED" if version is not None else None,
    }


def _choices(spec: Mapping[str, str], direction: VisualDirection | None = None) -> dict[str, str]:
    choices = _plain_choices(spec)
    if direction is None:
        return choices
    for axis in DIRECTION_AXES:
        for dimension, allowed in AXIS_BINDINGS[axis][getattr(direction.axes, axis)].items():
            values = [item.value for item in allowed]
            if choices[dimension] not in values:
                choices[dimension] = values[0]
    return choices


def _plain_choices(spec: Mapping[str, str]) -> dict[str, str]:
    return {
        "archetype": spec["archetype"],
        "hue_family": spec["hue"],
        "color_scheme": "ANALOGOUS",
        "color_mode": spec["mode"],
        "saturation": "BALANCED",
        "surface_tone": "NEUTRAL",
        "heading_family": "HUMANIST_SANS",
        "body_family": "HUMANIST_SANS",
        "type_scale": "REGULAR",
        "heading_case": "SENTENCE",
        "heading_weight": "SEMIBOLD",
        "corners": "SOFT",
        "density": "COMFORTABLE",
        "buttons": "FILLED",
        "inputs": "BOXED",
        "elevation": "SUBTLE",
        "borders": "HAIRLINE",
        "navigation": "NONE",
        "header": "MINIMAL",
        "background": "PLAIN",
        "emphasis": "BALANCED",
        "tone": spec["tone"],
    }


PACKAGE_KEYS = (
    "schema_version",
    "project_id",
    "grounding",
    "alternatives",
    "critiques",
    "recommended_alternative_id",
    "owner_selected_alternative_id",
    "prototype",
    "concerns",
    "open_questions",
)
OPTIONAL_PACKAGE_KEYS = ("generated_mockup", "owner_assertions")


def _check_package(package: object) -> None:
    location = ("body", "package")
    if not isinstance(package, dict):
        raise _Invalid([_error(location, "model_type")])
    errors = [_error((*location, key), "missing") for key in PACKAGE_KEYS if key not in package]
    errors.extend(
        _error((*location, key), "extra_forbidden")
        for key in package
        if key not in PACKAGE_KEYS and key not in OPTIONAL_PACKAGE_KEYS
    )
    for key in ("alternatives", "critiques", "concerns", "open_questions"):
        if key in package and not isinstance(package[key], list):
            errors.append(_error((*location, key), "tuple_type"))
    if "owner_assertions" in package and not isinstance(package["owner_assertions"], list):
        errors.append(_error((*location, "owner_assertions"), "tuple_type"))
    for key in ("grounding",):
        if key in package and not isinstance(package[key], dict):
            errors.append(_error((*location, key), "model_type"))
    for key in ("prototype", "generated_mockup"):
        if package.get(key) is not None and not isinstance(package[key], dict):
            errors.append(_error((*location, key), "model_type"))
    for key in ("project_id", "recommended_alternative_id", "owner_selected_alternative_id"):
        value = package.get(key)
        if value is None and key != "project_id":
            continue
        try:
            UUID(str(value))
        except ValueError:
            errors.append(_error((*location, key), "uuid_parsing"))
    if errors:
        raise _Invalid(errors)


def _coherent_package(package: Mapping[str, object]) -> bool:
    alternatives = package["alternatives"]
    if not all(isinstance(item, dict) and "id" in item for item in alternatives):
        return False
    identifiers = {str(item["id"]) for item in alternatives}
    selected = package["owner_selected_alternative_id"]
    if selected is not None and str(selected) not in identifiers:
        return False
    prototype = package["prototype"]
    if prototype is not None and str(prototype.get("design_alternative_id")) != str(selected):
        return False
    bound = package.get("generated_mockup")
    if bound is not None:
        mockup = bound.get("mockup") if isinstance(bound, dict) else None
        if not isinstance(mockup, dict) or str(mockup.get("design_alternative_id")) != str(
            selected
        ):
            return False
    assertions = package.get("owner_assertions") or []
    return len(assertions) <= MAX_OWNER_ASSERTIONS and all(
        isinstance(item, str) and 1 <= len(item) <= MAX_OWNER_ASSERTION for item in assertions
    )


def _design_changes(
    before: Mapping[str, object], after: Mapping[str, object]
) -> list[dict[str, object]]:
    changes = []
    old_selection = before["owner_selected_alternative_id"]
    new_selection = after["owner_selected_alternative_id"]
    if old_selection != new_selection:
        changes.append(
            {
                "kind": "REPLACE" if old_selection and new_selection else "ADD",
                "artifact_kind": "SELECTION",
                "artifact_id": new_selection or old_selection,
                "before": None if old_selection is None else {"alternative_id": old_selection},
                "after": None if new_selection is None else {"alternative_id": new_selection},
            }
        )
    for key, kind, identifier in (
        ("prototype", "PROTOTYPE", "id"),
        ("generated_mockup", "GENERATED_MOCKUP", None),
    ):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        source = new if new is not None else old
        artifact_id = (
            source[identifier]
            if identifier is not None
            else source["mockup"]["design_alternative_id"]
        )
        changes.append(
            {
                "kind": "ADD" if old is None else "REMOVE" if new is None else "REPLACE",
                "artifact_kind": kind,
                "artifact_id": artifact_id,
                "before": None if old is None else {"id": artifact_id},
                "after": None if new is None else {"id": artifact_id},
            }
        )
    old_assertions = list(before.get("owner_assertions") or [])
    new_assertions = list(after.get("owner_assertions") or [])
    for text in new_assertions:
        if text not in old_assertions:
            changes.append(_assertion_change("ADD", text))
    for text in old_assertions:
        if text not in new_assertions:
            changes.append(_assertion_change("REMOVE", text))
    for key, kind in (
        ("alternatives", "ALTERNATIVE"),
        ("critiques", "CRITIQUE"),
        ("concerns", "CONCERN"),
        ("open_questions", "OPEN_QUESTIONS"),
    ):
        if before[key] != after[key]:
            changes.append(
                {
                    "kind": "REPLACE",
                    "artifact_kind": kind,
                    "artifact_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{kind}:{_digest(after[key])}")
                    ),
                    "before": None,
                    "after": None,
                }
            )
    return changes


def _assertion_change(kind: str, text: str) -> dict[str, object]:
    identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, f"assertion:{text}"))
    return {
        "kind": kind,
        "artifact_kind": "OWNER_ASSERTION",
        "artifact_id": identifier,
        "before": None if kind == "ADD" else {"text": text},
        "after": {"text": text} if kind == "ADD" else None,
    }
