from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from orchestwin.artifacts.design_change_opinions import (
    MAX_LOCALE_LENGTH,
    MIN_LOCALE_LENGTH,
    change_opinion_contrast,
    normalize_owner_request,
)

from .common import _change_target, _checked_target, _colour_mode, _target_snapshot
from .fields import _Fields
from .texts import COLOUR_WORDS, COSTS, OPINION_TEXTS
from .values import _Answer, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


OPINION = "DESIGN_CHANGE_OPINION"
OPINION_FIELDS = ("design_version_id", "design_content_hash", "request", "target", "locale")
PROFILE_KEYS = ("user_twin.goals",)
CONFIDENCE = 0.6
CLASHING_COLOURS = 2
NAMED_COLOUR = re.compile(rf"\b(?:{'|'.join(COLOUR_WORDS)})\b", re.IGNORECASE)


class _OpinionRoutes:
    def _route_opinion(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), OPINION_FIELDS)
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        request = fields.text("request")
        if request is not None:
            fields.normalized("request", request, normalize_owner_request)
        target = _change_target(fields, required=True)
        locale = fields.text(
            "locale",
            required=False,
            minimum=MIN_LOCALE_LENGTH,
            maximum=MAX_LOCALE_LENGTH,
            default="it-IT",
        )
        fields.check()
        body = {
            "design_version_id": version_id,
            "design_content_hash": content_hash,
            "request": request,
            "target": target,
            "locale": locale,
        }
        return self._later(call, OPINION, body, lambda: self._opinion(call, body))

    def _opinion(self, call: _Call, body: Mapping[str, object]) -> _Answer:
        project = self._owned(call)
        current = self._checked_design(
            project, body["design_version_id"], body["design_content_hash"]
        )
        assert project is not None
        package = current["package"]
        if package.get("generated_mockup") is None:
            raise _Refusal(409, {"code": "GENERATED_MOCKUP_REQUIRED"})
        _checked_target(package, body["target"])
        twins = self._grounded_twins(project, package)
        if not self.hosted:
            raise _Refusal(503, {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"})
        requested_at = _iso(self._now())
        request = normalize_owner_request(str(body["request"]))
        opinions = [
            self._twin_opinion(project, position, twin, request)
            for position, twin in enumerate(twins)
        ]
        run = {
            "run_id": self._new_id(),
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "design_version_number": current["version_number"],
            "request": request,
            "target": _target_snapshot(body["target"]),
            "locale": body["locale"],
            "requested_at": requested_at,
            "opinions": opinions,
            "contrast": change_opinion_contrast(_colour_mode(package)).to_snapshot(),
            "cost_microusd": COSTS[OPINION] * len(opinions),
        }
        project.opinions.insert(0, run)
        return _Answer(201, run)

    def _twin_opinion(
        self, project: FakeProject, position: int, twin: Mapping[str, object], request: str
    ) -> dict[str, object]:
        texts = OPINION_TEXTS[self.language]
        verdict = _verdict(position, request)
        return {
            "twin_id": twin["twin_id"],
            "twin_version": twin["version_number"],
            "twin_name": twin["name"],
            "verdict": verdict,
            "why": texts[verdict],
            "what_to_do": texts["what_to_do"],
            "try_this": texts["try_this"] if position == 0 else None,
            "profile_keys": list(PROFILE_KEYS),
            "confidence": CONFIDENCE,
            "generation_id": self._record(project, OPINION),
        }

    def _route_opinions(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, {"items": [] if project is None else list(project.opinions)})


def _verdict(position: int, request: str) -> str:
    if position > 0:
        return "HELPS"
    named = {word.casefold() for word in NAMED_COLOUR.findall(request)}
    return "BLOCKS" if len(named) >= CLASHING_COLOURS else "SLOWS"
