from dataclasses import replace

import pytest
from pydantic import ValidationError

from orchestwin.api.requirements import (
    RequirementsArtifactEnvelope,
    RequirementsSpecificationPayload,
    UserNeedPayload,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsArtifactKind,
    propose_requirements_diff,
)
from src.test.python.api.test_requirements_api import (
    DIFF_ID,
    NOW,
    USER_ID,
    client_fixture,
    path,
    specification_version,
)
from src.test.python.projects.test_requirements_needs import enriched_specification


def test_definition_api_payload_roundtrips_all_new_content_and_sources():
    specification = enriched_specification()
    payload = RequirementsSpecificationPayload.from_domain(specification)
    decoded = RequirementsSpecificationPayload.model_validate_json(payload.model_dump_json())
    assert decoded.to_domain() == specification
    assert decoded.schema_version == 2
    assert decoded.needs[0].sources[0].to_domain() == specification.needs[0].sources[0]
    assert decoded.scenarios[0].criticalities == specification.scenarios[0].criticalities


def test_legacy_api_input_defaults_to_schema_one_without_inventing_needs():
    specification = specification_version().specification
    payload = RequirementsSpecificationPayload.from_domain(specification).model_dump(mode="json")
    payload.pop("schema_version")
    payload.pop("needs")
    for value in (*payload["requirements"], *payload["user_stories"]):
        value.pop("need_ids")
    for scenario in payload["scenarios"]:
        for field in ("context", "goal", "criticalities", "sources"):
            scenario.pop(field)
    decoded = RequirementsSpecificationPayload.model_validate(payload).to_domain()
    assert decoded == specification
    assert decoded.schema_version == 1
    assert decoded.needs == ()
    assert decoded.content_hash == specification.content_hash


@pytest.mark.parametrize("schema_version", (True, 2.0, "2", 0, 3))
def test_api_schema_version_rejects_coercion_and_unsupported_versions(schema_version):
    payload = RequirementsSpecificationPayload.from_domain(enriched_specification()).model_dump()
    payload["schema_version"] = schema_version
    with pytest.raises(ValidationError):
        RequirementsSpecificationPayload.model_validate(payload)


def test_need_envelope_accepts_only_its_typed_need_payload():
    need = enriched_specification().needs[0]
    envelope = RequirementsArtifactEnvelope.from_domain(need)
    assert envelope.kind is RequirementsArtifactKind.NEED
    assert envelope.need.to_domain() == need
    assert RequirementsArtifactEnvelope.model_validate_json(envelope.model_dump_json()) == envelope
    with pytest.raises(ValidationError, match="selected payload"):
        RequirementsArtifactEnvelope(
            kind=RequirementsArtifactKind.REQUIREMENT, need=UserNeedPayload.from_domain(need)
        )


def test_current_traceability_and_diff_endpoints_expose_definition_two():
    client, _generation, queries, revisions, _gates = client_fixture()
    written = specification_version()
    specification = enriched_specification(written.specification)
    queries.version = replace(
        written, specification=specification, content_hash=specification.content_hash
    )
    proposal = propose_requirements_diff(
        base_version=written,
        proposed_specification=specification,
        diff_id=DIFF_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
    )
    assert proposal.diff is not None
    revisions.diff = proposal.diff
    queries.diffs = [proposal.diff]
    with client:
        current = client.get(path("/current"))
        graph = client.get(path("/traceability"))
        diff = client.get(path(f"/revisions/{DIFF_ID}"))
    assert current.status_code == 200
    current_payload = current.json()["specification"]
    assert (
        RequirementsSpecificationPayload.model_validate(current_payload).to_domain()
        == specification
    )
    assert graph.status_code == 200
    assert any(node["reference"]["kind"] == "NEED" for node in graph.json()["nodes"])
    assert diff.status_code == 200
    needs = [
        operation for operation in diff.json()["operations"] if operation["artifact_kind"] == "NEED"
    ]
    assert needs[0]["after"]["kind"] == "NEED"
    assert needs[0]["after"]["need"]["scenario_ids"] == [str(specification.scenarios[0].id)]


def test_explicit_revision_accepts_schema_two_and_rejects_invalid_chain():
    client, _generation, _queries, revisions, _gates = client_fixture()
    specification = enriched_specification(specification_version().specification)
    payload = RequirementsSpecificationPayload.from_domain(specification).model_dump(mode="json")
    with client:
        response = client.post(path("/revisions"), json={"specification": payload})
        assert response.status_code == 201
        assert revisions.proposed == specification
        payload["requirements"][0]["need_ids"] = []
        refused = client.post(path("/revisions"), json={"specification": payload})
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "INVALID_REQUIREMENTS_SPECIFICATION"
