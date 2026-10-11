from __future__ import annotations

from typing import Final, Literal

from pydantic import Field

from orchestwin.knowledge.schema_models.base import _BriefFieldName, _Record
from orchestwin.projects.briefs import ProjectBrief

_BRIEF_SCHEMA_VERSION: Final = ProjectBrief.SCHEMA_VERSION


class BriefFieldValues(_Record):
    name: str | None = Field(description="Project name, or null when not provided.")
    description: str | None = Field(
        description="Short description of the project, or null when not provided."
    )
    problem: str | None = Field(
        description="Problem the project solves, or null when not provided."
    )
    goals: list[str] | None = Field(description="Project goals, or null when not provided.")
    target_users: list[str] | None = Field(
        description="Intended users of the product, or null when not provided."
    )
    domain: str | None = Field(
        description="Application domain of the project, or null when not provided."
    )
    technical_constraints: list[str] | None = Field(
        description="Technical constraints, or null when not provided."
    )
    temporal_constraints: str | None = Field(
        description="Deadlines and time constraints, or null when not provided."
    )
    budget: str | None = Field(description="Budget of the project, or null when not provided.")
    functional_requirements: list[str] | None = Field(
        description="Functional requirements stated by the owner, or null when not provided."
    )
    non_functional_requirements: list[str] | None = Field(
        description="Non-functional requirements stated by the owner, or null when not provided."
    )
    risks: list[str] | None = Field(
        description="Risks known to the owner, or null when not provided."
    )
    stakeholders: list[str] | None = Field(
        description="Stakeholders of the project, or null when not provided."
    )
    available_artifacts: list[str] | None = Field(
        description="Existing material the project can reuse, or null when not provided."
    )
    definition_of_done: list[str] | None = Field(
        description="Owner's conditions for calling the project done, or null when not provided."
    )


class BriefSnapshot(_Record):
    schema_version: Literal[_BRIEF_SCHEMA_VERSION] = Field(
        description="Version of the project brief format."
    )
    fields: BriefFieldValues = Field(
        description="Owner's answer for every brief field; a field is null when not provided."
    )
    unknown_fields: list[_BriefFieldName] = Field(
        description="Fields the owner explicitly marked as unknown, in alphabetical order."
    )
