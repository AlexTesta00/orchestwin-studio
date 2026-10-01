from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.artifacts.design import DesignAlternative
from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignPackageVersion,
    create_design_grounding,
)
from orchestwin.artifacts.visual_language import VisualLanguage
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_user_twin_references,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)


class DesignRealignmentIssue(StrEnum):
    ALREADY_ALIGNED = "ALREADY_ALIGNED"
    REQUIREMENT_NO_LONGER_AVAILABLE = "REQUIREMENT_NO_LONGER_AVAILABLE"
    TWIN_SET_CHANGED = "TWIN_SET_CHANGED"


class DesignRealignmentError(Exception):
    def __init__(self, issue: DesignRealignmentIssue) -> None:
        super().__init__(issue.value)
        self.issue = issue
        self.code = issue.value


def _available_items(
    specification: RequirementsSpecification,
) -> tuple[frozenset[UUID], frozenset[UUID], frozenset[UUID]]:
    return (
        frozenset(requirement.id for requirement in specification.requirements),
        frozenset(story.id for story in specification.user_stories),
        frozenset(criterion.id for criterion in specification.acceptance_criteria),
    )


def _cited_items(
    package: DesignExplorationPackage,
) -> tuple[frozenset[UUID], frozenset[UUID], frozenset[UUID]]:
    requirements: set[UUID] = set()
    stories: set[UUID] = set()
    criteria: set[UUID] = set()
    for alternative in package.alternatives:
        requirements.update(alternative.requirement_ids)
        stories.update(alternative.user_story_ids)
        criteria.update(alternative.acceptance_criterion_ids)
        for workflow in alternative.workflows:
            requirements.update(workflow.requirement_ids)
            stories.update(workflow.user_story_ids)
    for concern in package.concerns:
        requirements.update(concern.requirement_ids)
    if package.prototype is not None:
        for screen in package.prototype.screens:
            for traced in (screen, *screen.elements):
                requirements.update(traced.requirement_ids)
                stories.update(traced.user_story_ids)
                criteria.update(traced.acceptance_criterion_ids)
    if package.generated_mockup is not None:
        requirements.update(package.generated_mockup.requirement_ids)
    return frozenset(requirements), frozenset(stories), frozenset(criteria)


def _twin_ids(references: Iterable[UserTwinVersionReference]) -> tuple[UUID, ...]:
    return tuple(
        sorted((reference.twin_id for reference in references), key=lambda value: value.hex)
    )


def design_is_aligned(
    package: DesignExplorationPackage,
    requirements: RequirementsSpecificationVersion,
) -> bool:
    return package.grounding == create_design_grounding(requirements)


def missing_item_ids(
    package: DesignExplorationPackage,
    requirements: RequirementsSpecificationVersion,
) -> frozenset[UUID]:
    return frozenset().union(
        *(
            cited - available
            for cited, available in zip(
                _cited_items(package),
                _available_items(requirements.specification),
                strict=True,
            )
        )
    )


def item_codes(
    specification: RequirementsSpecification,
    identifiers: Iterable[UUID],
) -> tuple[str, ...]:
    wanted = frozenset(identifiers)
    return tuple(
        code
        for items in (
            specification.requirements,
            specification.user_stories,
            specification.acceptance_criteria,
        )
        for code in sorted(item.code for item in items if item.id in wanted)
    )


def uncovered_requirement_codes(
    package: DesignExplorationPackage,
    requirements: RequirementsSpecificationVersion,
) -> tuple[str, ...]:
    if package.prototype is None:
        return ()
    cited = frozenset(
        identifier
        for screen in package.prototype.screens
        for traced in (screen, *screen.elements)
        for identifier in traced.requirement_ids
    )
    return tuple(
        sorted(
            requirement.code
            for requirement in requirements.specification.requirements
            if requirement.id not in cited
        )
    )


def design_realignment_issue(
    package: DesignExplorationPackage,
    requirements: RequirementsSpecificationVersion,
) -> DesignRealignmentIssue | None:
    if design_is_aligned(package, requirements):
        return DesignRealignmentIssue.ALREADY_ALIGNED
    if missing_item_ids(package, requirements):
        return DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE
    if _twin_ids(package.grounding.user_twin_references) != _twin_ids(
        requirements.specification.user_twin_references
    ):
        return DesignRealignmentIssue.TWIN_SET_CHANGED
    return None


def _realigned_language(
    language: VisualLanguage | None,
    current: Mapping[UUID, UserTwinVersionReference],
) -> VisualLanguage | None:
    if language is None:
        return None
    return replace(
        language,
        twin_fit=tuple(
            replace(fit, name=current[fit.twin_id].name) if fit.twin_id in current else fit
            for fit in language.twin_fit
        ),
    )


def _realigned_alternative(
    alternative: DesignAlternative,
    current: Mapping[UUID, UserTwinVersionReference],
) -> DesignAlternative:
    return replace(
        alternative,
        user_twin_references=canonical_user_twin_references(
            (current[reference.twin_id] for reference in alternative.user_twin_references),
            require_items=True,
        ),
        visual_language=_realigned_language(alternative.visual_language, current),
    )


def realign_design(
    package: DesignExplorationPackage,
    requirements: RequirementsSpecificationVersion,
) -> DesignExplorationPackage:
    if package.project_id != requirements.project_id:
        raise ValueError("the design and the requirements must belong to the same project")
    issue = design_realignment_issue(package, requirements)
    if issue is not None:
        raise DesignRealignmentError(issue)
    grounding = create_design_grounding(requirements)
    current = {reference.twin_id: reference for reference in grounding.user_twin_references}
    return replace(
        package,
        grounding=grounding,
        alternatives=tuple(
            _realigned_alternative(alternative, current) for alternative in package.alternatives
        ),
        critiques=tuple(
            replace(critique, user_twin_reference=current[critique.user_twin_reference.twin_id])
            for critique in package.critiques
        ),
    )


def realigned_design_version(
    version: DesignPackageVersion,
    requirements: RequirementsSpecificationVersion,
    *,
    version_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
) -> DesignPackageVersion:
    package = realign_design(version.package, requirements)
    return DesignPackageVersion(
        id=version_id,
        project_id=version.project_id,
        version_number=version.version_number + 1,
        based_on_version_number=version.version_number,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=created_by_user_id,
        created_at=created_at,
    )


__all__ = [
    "DesignRealignmentError",
    "DesignRealignmentIssue",
    "design_is_aligned",
    "design_realignment_issue",
    "item_codes",
    "missing_item_ids",
    "realign_design",
    "realigned_design_version",
    "uncovered_requirement_codes",
]
