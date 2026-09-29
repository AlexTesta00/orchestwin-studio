from __future__ import annotations

import hashlib
import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.design_evaluation import (
    DesignEvaluationRun,
    finding_anchor_key,
    finding_key,
)
from orchestwin.artifacts.design_evaluation_persistence import (
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_finding_validation_persistence import (
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_finding_validations import dismissed_finding_keys
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.generated_mockup_document import MockupPin, mockup_document
from orchestwin.artifacts.generated_mockup_styles import FORBIDDEN_CHARACTERS
from orchestwin.artifacts.prototypes import PrototypeScreenState
from orchestwin.evaluation.findings import SyntheticFinding
from orchestwin.identity.domain import UserAccount

DESIGN_REVIEW_PINS_API_PREFIX: Final = "/projects/{project_id}/design/evaluations"
REVIEW_DOCUMENT_SOURCE: Final = "review"
PIN_LABEL_LENGTH: Final = 120
ENTRY_SCREEN_PATTERN: Final = r"^SCR-[0-9]{3}$"
UNDETERMINED_LANGUAGE: Final = "und"
_LEADING_SCREEN: Final = re.compile(r"(SCR-[0-9]{3,6})(?![0-9])")
_LANGUAGE: Final = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,7}")


@dataclass(frozen=True, slots=True)
class ReviewPin:
    number: int
    element_code: str
    screen_code: str
    twin_id: UUID
    finding_id: str
    severity: str
    label: str


@dataclass(frozen=True, slots=True)
class UnanchoredReviewPin:
    number: int
    screen_code: str
    twin_id: UUID
    finding_id: str


@dataclass(frozen=True, slots=True)
class ReviewPins:
    design_version_id: UUID
    pins: tuple[ReviewPin, ...]
    unanchored: tuple[UnanchoredReviewPin, ...]


@dataclass(frozen=True, slots=True)
class ReviewDocumentScreen:
    code: str
    title: str
    state: PrototypeScreenState


@dataclass(frozen=True, slots=True)
class ReviewDocument:
    html: str
    content_hash: str
    alternative_id: UUID
    title: str
    entry_screen: str
    screens: tuple[ReviewDocumentScreen, ...]


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewPinPayload(_Payload):
    number: int
    element_code: str
    screen_code: str
    twin_id: UUID
    finding_id: str
    severity: str
    label: str


class UnanchoredReviewPinPayload(_Payload):
    number: int
    screen_code: str
    twin_id: UUID
    finding_id: str


class ReviewPinsPayload(_Payload):
    design_version_id: UUID
    pins: tuple[ReviewPinPayload, ...]
    unanchored: tuple[UnanchoredReviewPinPayload, ...]

    @classmethod
    def from_domain(cls, value: ReviewPins) -> ReviewPinsPayload:
        return cls(
            design_version_id=value.design_version_id,
            pins=tuple(
                ReviewPinPayload(
                    number=item.number,
                    element_code=item.element_code,
                    screen_code=item.screen_code,
                    twin_id=item.twin_id,
                    finding_id=item.finding_id,
                    severity=item.severity,
                    label=item.label,
                )
                for item in value.pins
            ),
            unanchored=tuple(
                UnanchoredReviewPinPayload(
                    number=item.number,
                    screen_code=item.screen_code,
                    twin_id=item.twin_id,
                    finding_id=item.finding_id,
                )
                for item in value.unanchored
            ),
        )


class ReviewDocumentScreenPayload(_Payload):
    code: str
    title: str
    state: PrototypeScreenState


class ReviewDocumentPayload(_Payload):
    html: str
    content_hash: str
    source: Literal["review"]
    alternative_id: UUID
    title: str
    entry_screen: str
    screens: tuple[ReviewDocumentScreenPayload, ...]

    @classmethod
    def from_domain(cls, value: ReviewDocument) -> ReviewDocumentPayload:
        return cls(
            html=value.html,
            content_hash=value.content_hash,
            source=REVIEW_DOCUMENT_SOURCE,
            alternative_id=value.alternative_id,
            title=value.title,
            entry_screen=value.entry_screen,
            screens=tuple(
                ReviewDocumentScreenPayload(code=item.code, title=item.title, state=item.state)
                for item in value.screens
            ),
        )


def pin_label(finding: SyntheticFinding) -> str:
    text = " ".join(FORBIDDEN_CHARACTERS.sub(" ", finding.summary).split())
    if not text:
        return finding.finding_id
    if len(text) <= PIN_LABEL_LENGTH:
        return text
    return text[: PIN_LABEL_LENGTH - 1].rstrip() + "…"


def _placement(
    finding: SyntheticFinding, elements: dict[str, str], screens: tuple[str, ...]
) -> tuple[str, str | None]:
    key = finding_anchor_key(finding)
    if key is not None:
        screen, _separator, element = key.partition("/")
        if element and elements.get(element) == screen:
            return screen, element
        if screen in screens:
            return screen, None
    match = _LEADING_SCREEN.match(finding.location)
    if match is not None and match[1] in screens:
        return match[1], None
    return screens[0], None


def review_pins(
    run: DesignEvaluationRun,
    version: DesignPackageVersion,
    dismissed: Collection[tuple[UUID, UUID, str]] = frozenset(),
) -> ReviewPins:
    prototype = version.package.prototype
    entry = next(screen for screen in prototype.screens if screen.id == prototype.entry_screen_id)
    screens = (entry.code, *(screen.code for screen in prototype.screens if screen.id != entry.id))
    elements = {
        element.code: screen.code for screen in prototype.screens for element in screen.elements
    }
    pins: list[ReviewPin] = []
    unanchored: list[UnanchoredReviewPin] = []
    number = 0
    for response in run.responses:
        for finding in response.findings:
            if finding_key(run.id, finding) in dismissed:
                continue
            number += 1
            screen, element = _placement(finding, elements, screens)
            if element is None:
                unanchored.append(
                    UnanchoredReviewPin(
                        number=number,
                        screen_code=screen,
                        twin_id=finding.twin_id,
                        finding_id=finding.finding_id,
                    )
                )
            else:
                pins.append(
                    ReviewPin(
                        number=number,
                        element_code=element,
                        screen_code=screen,
                        twin_id=finding.twin_id,
                        finding_id=finding.finding_id,
                        severity=finding.severity.value,
                        label=pin_label(finding),
                    )
                )
    return ReviewPins(
        design_version_id=run.design_version_id, pins=tuple(pins), unanchored=tuple(unanchored)
    )


def _language(locale: str) -> str:
    return locale if _LANGUAGE.fullmatch(locale) is not None else UNDETERMINED_LANGUAGE


class DesignReviewPinsApplication:
    def __init__(self, runtime):
        self.runtime = runtime

    def _sessions(self):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    async def _review(self, owner_user_id, project_id, run_id):
        sessions = self._sessions()
        async with sessions() as session:
            run = await SqlAlchemyDesignEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).get(project_id=project_id, run_id=run_id)
            if run is None:
                raise HTTPException(404, detail={"code": "DESIGN_EVALUATION_NOT_FOUND"})
            version = await SqlAlchemyDesignPackageRepository(
                session, owner_user_id=owner_user_id
            ).get(project_id=project_id, version_id=run.design_version_id)
            validations = await SqlAlchemyFindingValidationRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id)
        if version is None or version.content_hash != run.design_content_hash:
            raise HTTPException(404, detail={"code": "DESIGN_EVALUATION_NOT_FOUND"})
        if version.package.generated_mockup is None:
            raise HTTPException(409, detail={"code": "GENERATED_MOCKUP_REQUIRED"})
        return run, version, review_pins(run, version, dismissed_finding_keys(validations))

    async def pins(self, *, owner_user_id, project_id, run_id) -> ReviewPins:
        _run, _version, pins = await self._review(owner_user_id, project_id, run_id)
        return pins

    async def document(
        self, *, owner_user_id, project_id, run_id, entry_screen: str | None = None
    ) -> ReviewDocument:
        run, version, pins = await self._review(owner_user_id, project_id, run_id)
        bound = version.package.generated_mockup
        mockup = bound.mockup
        entry = mockup.screens[0].code if entry_screen is None else entry_screen
        if entry not in {screen.code for screen in mockup.screens}:
            raise HTTPException(422, detail={"code": "ENTRY_SCREEN_NOT_FOUND"})
        alternative = next(
            item for item in version.package.alternatives if item.id == bound.design_alternative_id
        )
        html = mockup_document(
            mockup,
            tokens=dict(alternative.visual_language.tokens),
            language=_language(run.bundle.scenario.locale),
            pins=tuple(
                MockupPin(element_code=pin.element_code, number=pin.number, label=pin.label)
                for pin in pins.pins
            ),
            entry_screen=entry,
        )
        return ReviewDocument(
            html=html,
            content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
            alternative_id=bound.design_alternative_id,
            title=mockup.title,
            entry_screen=entry,
            screens=tuple(
                ReviewDocumentScreen(code=screen.code, title=screen.title, state=screen.state)
                for screen in mockup.screens
            ),
        )


def create_design_review_pins_router():
    router = APIRouter(prefix=DESIGN_REVIEW_PINS_API_PREFIX, tags=["design"])

    @router.get("/{run_id}/pins", response_model=ReviewPinsPayload)
    async def pins(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await DesignReviewPinsApplication(request.app.state.application_runtime).pins(
            owner_user_id=user.id, project_id=project_id, run_id=run_id
        )
        return ReviewPinsPayload.from_domain(result)

    @router.get("/{run_id}/document", response_model=ReviewDocumentPayload)
    async def document(
        project_id: UUID,
        run_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        entry_screen: Annotated[str | None, Query(pattern=ENTRY_SCREEN_PATTERN)] = None,
    ):
        result = await DesignReviewPinsApplication(request.app.state.application_runtime).document(
            owner_user_id=user.id,
            project_id=project_id,
            run_id=run_id,
            entry_screen=entry_screen,
        )
        return ReviewDocumentPayload.from_domain(result)

    return router


__all__ = [
    "DESIGN_REVIEW_PINS_API_PREFIX",
    "ENTRY_SCREEN_PATTERN",
    "PIN_LABEL_LENGTH",
    "REVIEW_DOCUMENT_SOURCE",
    "DesignReviewPinsApplication",
    "ReviewDocument",
    "ReviewDocumentPayload",
    "ReviewDocumentScreen",
    "ReviewDocumentScreenPayload",
    "ReviewPin",
    "ReviewPinPayload",
    "ReviewPins",
    "ReviewPinsPayload",
    "UnanchoredReviewPin",
    "UnanchoredReviewPinPayload",
    "create_design_review_pins_router",
    "pin_label",
    "review_pins",
]
