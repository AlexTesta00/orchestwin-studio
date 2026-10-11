from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, model_validator

from orchestwin.knowledge.schema_models.base import _OPTIONAL, Uuid, _Record


class WhyReference(_Record):
    artifact_id: str
    version_number: int | None
    content_hash: str | None


class WhyRationale(_Record):
    text: str
    origin: Literal["MODEL", "OWNER", "SYSTEM", "UNKNOWN"]
    version_number: int | None
    content_hash: str | None


class WhyGap(_Record):
    code: Literal[
        "MISSING_NEED",
        "MISSING_SCENARIO",
        "MISSING_TWIN",
        "MISSING_CLAIM",
        "MISSING_SOURCE",
        "MISSING_SOURCE_VERSION",
        "MISSING_RATIONALE",
        "SOURCE_RETIRED",
        "SOURCE_TEXT_UNAVAILABLE",
        "OMITTED_SECTION",
        "CONTEXT_OUTDATED",
        "VALIDATION_REFERENCE_UNAVAILABLE",
        "DECLARED_MISSING",
        "MISSING_REQUIREMENT_ANCHOR",
        "PROVIDED_PROTOTYPE_CODE_UNAVAILABLE",
        "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE",
        "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE",
        "PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE",
        "PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE",
    ]
    node_key: str
    related_code: str | None
    stage: str | None


class WhyContext(_Record):
    perspectives: list[dict[str, object]]


class WhyNode(_Record):
    key: str
    code: str
    kind: str
    title: str
    display_status: Literal["EVIDENCED", "INFERRED", "HYPOTHESIZED", "CONTESTED", "UNKNOWN"]
    reference: WhyReference
    current: bool
    rationale: WhyRationale | None
    citations: list[dict[str, object]]
    validation_required: bool
    gaps: list[WhyGap]
    declared_context: WhyContext


class WhyLink(_Record):
    source: str
    target: str
    kind: str


class WhyDocument(_Record):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["orchestwin.why"]
    schema_version: Literal[1]
    project_id: Uuid
    nodes: list[WhyNode]
    links: list[WhyLink]
    omitted_sections: list[str]
    workflow_records: Annotated[dict[str, object] | None, _OPTIONAL] = None

    @model_validator(mode="after")
    def _references(self):
        keys = {node.key for node in self.nodes}
        if len(keys) != len(self.nodes):
            raise ValueError("why node keys must be unique")
        if any(link.source not in keys or link.target not in keys for link in self.links):
            raise ValueError("why links must reference existing nodes")
        if any(gap.node_key != node.key for node in self.nodes for gap in node.gaps):
            raise ValueError("why gaps must reference their node")
        return self
