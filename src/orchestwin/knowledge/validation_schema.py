from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Uuid = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Reference(Record):
    artifact_id: str
    version_number: Version
    content_hash: Hash


class Citation(Record):
    source_id: Uuid
    source_version: Version
    content_hash: Hash
    quote: Annotated[str, Field(min_length=1, max_length=1000)]
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]
    start_line: Version
    end_line: Version

    @model_validator(mode="after")
    def interval(self):
        if (
            self.end != self.start + len(self.quote)
            or "\r" in self.quote
            or self.end_line - self.start_line != self.quote[:-1].count("\n")
        ):
            raise ValueError("citation interval must match its exact LF quotation")
        return self


class MockupReference(Record):
    key: str
    reference: Reference
    mockup: dict[str, object]


class Hypothesis(Record):
    id: Uuid
    code: Annotated[str, Field(pattern=r"^HYP-[0-9]{3,6}$")]
    version_number: Version
    based_on_version_number: Version | None
    project_id: Uuid
    owner_user_id: Uuid
    origin_key: str
    origin_reference: Reference
    origin_kind: str
    twin_key: str
    twin_reference: Reference
    scenario_key: str
    scenario_reference: Reference
    design_key: str
    design_reference: Reference
    alternative_id: str | None
    anchor_keys: list[str]
    mockup_references: list[MockupReference]
    question: Text | None
    task: Text | None
    observe: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(min_length=1, max_length=24),
    ]
    limitations: Text
    created_at: Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$")]
    content_hash: Hash

    @model_validator(mode="after")
    def question_or_task(self):
        if not ((self.question and self.question.strip()) or (self.task and self.task.strip())):
            raise ValueError("an operational hypothesis requires its completed question or task")
        if (self.version_number == 1 and self.based_on_version_number is not None) or (
            self.version_number > 1 and self.based_on_version_number != self.version_number - 1
        ):
            raise ValueError("hypothesis lineage must preserve its exact previous version")
        if len(self.anchor_keys) != len(set(self.anchor_keys)) or self.anchor_keys != [
            item.key for item in self.mockup_references
        ]:
            raise ValueError("anchor keys must match the preserved mockup references")
        return self


class Outcome(Record):
    id: Uuid
    code: Annotated[str, Field(pattern=r"^HVO-[0-9]{3,6}$")]
    project_id: Uuid
    owner_user_id: Uuid
    hypothesis_id: Uuid
    hypothesis_version_number: Version
    hypothesis_content_hash: Hash
    session_ref: Annotated[str, Field(pattern=r"^(?:SES|SESSION|SYN|TEST)-[A-Za-z0-9_.:-]{1,70}$")]
    session_kind: Literal["HUMAN_SESSION", "SYNTHETIC_EXERCISE"]
    outcome: Literal["CONFIRMED", "REFUTED", "UNCERTAIN"]
    coverage: Literal["COMPLETE", "PARTIAL"]
    limitations: Text
    evidence_id: Uuid
    evidence_version: Version
    evidence_content_hash: Hash
    citation: Citation
    recorded_at: Annotated[str, Field(pattern=r"^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$")]
    content_hash: Hash


class ValidationRecords(Record):
    kind: Literal["orchestwin.validation-records"]
    schema_version: Literal[1]
    project_id: Uuid
    hypotheses: list[Hypothesis]
    outcomes: list[Outcome]
    omitted_sections: list[dict[str, object]]
    limits: list[str]
