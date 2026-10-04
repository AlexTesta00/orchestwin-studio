from __future__ import annotations

import copy
import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from orchestwin.api import acceptance_tests as acceptance_api
from orchestwin.api import twin_learning as twin_learning_api
from orchestwin.api.app import create_app
from orchestwin.api.auth import (
    AuthApiSettings,
    AuthenticationResponse,
    UserResponse,
    current_user_dependency,
)
from orchestwin.api.clarification import (
    BriefAssumptionBulkAcceptanceResponse,
    BriefAssumptionDecisionResponse,
    BriefAssumptionResponse,
    HumanGateEventResponse,
    HumanGateResponse,
    ProjectBriefGateDecisionResponse,
    ProjectBriefGateSubmissionResponse,
)
from orchestwin.api.design import (
    DesignGateDecisionPayload,
    DesignGateSubmissionPayload,
    DesignGenerationPayload,
    DesignPackageDiffPayload,
    DesignPackagePayload,
    DesignPackageVersionPayload,
    DesignReadinessPayload,
    DesignRevisionPayload,
)
from orchestwin.api.design_distance import DesignDistancePayload
from orchestwin.api.design_mockups import MockupCapabilities
from orchestwin.api.design_realignment import DesignAlignmentPayload, DesignRealignmentPayload
from orchestwin.api.design_review_pins import ReviewDocumentPayload, ReviewPinsPayload
from orchestwin.api.generation_jobs import GenerationJob, GenerationJobKind, GenerationOperation
from orchestwin.api.generation_requests import request_key
from orchestwin.api.knowledge_packages import (
    KnowledgePackageHistoryPayload,
    KnowledgePackagePublicationPayload,
)
from orchestwin.api.project_imports import ProjectImportOriginPayload, ProjectImportPayload
from orchestwin.api.projects import ProjectBriefVersionResponse, ProjectResponse
from orchestwin.api.requirements import (
    RequirementsGateDecisionPayload,
    RequirementsGateSubmissionPayload,
    RequirementsGenerationPayload,
    RequirementsReadinessPayload,
    RequirementsRevisionPayload,
    RequirementsSpecificationDiffPayload,
    RequirementsSpecificationPayload,
    RequirementsSpecificationVersionPayload,
)
from orchestwin.api.requirements_realignment import (
    RequirementsAlignmentPayload,
    RequirementsRealignmentPayload,
)
from orchestwin.api.sections import ProjectSectionsPayload, SectionsAlignmentPayload
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.teams import (
    AgentCatalogResponse,
    AgentTeamGateDecisionResponse,
    AgentTeamGateSubmissionResponse,
    ProjectReadinessResponse,
    TeamEditResponse,
    TeamProposalGenerationResponse,
    TeamProposalVersionResponse,
)
from orchestwin.api.user_modeling import (
    GateCommandPayload,
    HumanGatePayload,
    PersonaDecisionCommandPayload,
    PersonaProposalCommandPayload,
    PersonaVersionPayload,
    SnapshotGenerationCommandPayload,
    UserModelingReadinessPayload,
    UserModelingSnapshotVersionPayload,
)
from orchestwin.api.user_modeling_realignment import (
    UserModelingAlignmentPayload,
    UserModelingRealignmentPayload,
)
from orchestwin.artifacts.bound_mockups import bound_mockup_from_snapshot
from orchestwin.artifacts.design_distance import design_distance_report
from orchestwin.artifacts.design_evaluation import synthetic_finding_from_snapshot
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.generated_mockup_review import review_generated_mockup
from orchestwin.artifacts.visual_catalog import MODES, VisualChoices
from orchestwin.artifacts.visual_directions import (
    AXIS_BINDINGS,
    DIRECTION_AXES,
    direction_distance,
    visual_direction_from_snapshot,
)
from orchestwin.artifacts.visual_language import visual_language_from_snapshot
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.application import IdentityUnitOfWork, LocalIdentityApplicationService
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.models.design import DesignProposalIssueCode
from orchestwin.projects import acceptance_tests as acceptance_domain
from orchestwin.projects import code_changes as changes_domain
from orchestwin.projects import twin_learning as learning_domain
from orchestwin.projects.code_changes import (
    alignment_verdict_from_snapshot,
    changed_file_from_snapshot,
    twin_critique_from_snapshot,
)

from .support.fake_studio import (
    COSTS,
    EARLIER_FIELDS,
    ELEMENT_FIELDS,
    PLAN_FIELDS,
    PREFIX,
    ROUTES,
    SNAPSHOT_FIELDS,
    FakeProject,
    FakeStudio,
    route_table,
)

HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
EMAIL = "owner@example.com"
PASSWORD = "Test-password-not-real!"
BOUNDARY = "fake-boundary-not-real"
JWT_SECRET = "jwt-secret-not-real-for-the-fake-studio-test"
MOMENT = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
REFUSED_REGISTRATIONS = (
    {"email": "probe@example.test", "password": PASSWORD},
    {"email": "person@localhost", "password": PASSWORD},
    {"email": "probe@example.test", "password": "abcdefgh!"},
    {"email": EMAIL, "password": "abcdefg1!"},
    {"email": EMAIL, "password": "Abcdefg12"},
    {"email": EMAIL, "password": "Abcde1!"},
    {"email": EMAIL, "password": "Ab!" * 342},
    {"email": EMAIL},
    {"email": "a@", "password": PASSWORD},
    {"email": 5, "password": "x" * 1025},
    {"email": EMAIL, "password": PASSWORD, "role": "owner"},
)


@pytest.fixture(scope="module")
def real_routes() -> frozenset[tuple[str, str]]:
    with pytest.MonkeyPatch.context() as patch:
        for name in tuple(os.environ):
            if name.upper().startswith("ORCHESTWIN_"):
                patch.delenv(name, raising=False)
        application = create_app(
            ApplicationSettings(
                application_name="OrchesTwin Fake Studio Route Test",
                environment=RuntimeEnvironment.TEST,
                debug=False,
                log_level=LogLevel.INFO,
                api_prefix=PREFIX,
                _env_file=None,
            ),
            runtime=ApplicationRuntime(),
            auth_settings=AuthApiSettings(_env_file=None),
        )
        document = application.openapi()
    return frozenset(
        (method.upper(), path)
        for path, operations in document["paths"].items()
        for method in operations
        if method.upper() in HTTP_METHODS
    )


def test_every_route_of_the_fake_exists_in_the_real_api(
    real_routes: frozenset[tuple[str, str]],
) -> None:
    missing = [route for route in route_table() if route not in real_routes]

    assert missing == []


def test_the_route_table_has_no_duplicates() -> None:
    table = route_table()

    assert len(set(table)) == len(table)
    assert all(path.startswith(PREFIX + "/") for _, path in table)


def test_only_health_and_the_sign_in_are_open_without_a_token() -> None:
    open_routes = {(route.method, route.template) for route in ROUTES if not route.authenticated}

    assert open_routes == {
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("POST", "/auth/register"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/logout"),
    }


def test_the_fake_serves_every_area_that_the_commands_need(
    real_routes: frozenset[tuple[str, str]],
) -> None:
    project = PREFIX + "/projects/{project_id}"
    needed = {
        ("GET", PREFIX + "/health"),
        ("POST", PREFIX + "/auth/login"),
        ("POST", PREFIX + "/auth/refresh"),
        ("GET", PREFIX + "/model-runtime/budget"),
        ("POST", PREFIX + "/projects"),
        ("POST", project + "/brief-dialogue/answers"),
        ("POST", project + "/brief-assumptions/accept-all"),
        ("POST", project + "/gates/project-brief/decisions"),
        ("PATCH", project + "/team-proposals/current"),
        ("POST", project + "/user-modeling/snapshots/generate"),
        ("POST", project + "/user-twins/{twin_id}/conversation/turns"),
        ("POST", project + "/requirements/change-requests"),
        ("POST", project + "/design/regenerations"),
        ("GET", project + "/design/mockups/document"),
        ("POST", project + "/design/mockups"),
        ("GET", project + "/design/mockups"),
        ("GET", project + "/design/iterations"),
        ("GET", project + "/design/evaluations/{run_id}/pins"),
        ("GET", project + "/generation-jobs/{job_id}"),
        ("GET", project + "/knowledge-packages/{version_number}/archive"),
        ("POST", PREFIX + "/project-imports"),
        ("GET", project + "/model-usage"),
        ("GET", project + "/alignment"),
        ("POST", project + "/code-changes"),
        ("GET", project + "/code-changes"),
        ("GET", project + "/code-changes/{commit}"),
        ("POST", project + "/code-changes/{commit}/reviews"),
        ("GET", project + "/code-changes/{commit}/reviews"),
        ("POST", project + "/code-changes/{commit}/decision"),
        ("GET", project + "/acceptance-tests"),
        ("POST", project + "/test-plans"),
        ("GET", project + "/test-plans"),
        ("GET", project + "/test-plans/{plan_id}"),
        ("POST", project + "/test-runs"),
        ("GET", project + "/test-runs"),
        ("GET", project + "/test-runs/{run_id}"),
        ("POST", project + "/test-runs/{run_id}/reviews"),
        ("GET", project + "/test-runs/{run_id}/reviews"),
        ("GET", project + "/code-tasks"),
        ("POST", project + "/code-tasks"),
        ("POST", project + "/code-tasks/{code}/status"),
        ("GET", project + "/twin-learning"),
        ("GET", project + "/artifacts/why"),
        ("GET", project + "/artifacts/why/document"),
        ("GET", project + "/validation"),
        ("GET", project + "/validation/walkthrough"),
        ("POST", project + "/user-twins/{twin_id}/updates"),
        ("GET", project + "/twin-updates/{update_id}"),
        ("POST", project + "/twin-updates/{update_id}/decision"),
        ("POST", project + "/user-twins/{twin_id}/observations"),
        ("POST", project + "/user-twins/{twin_id}/observations/{code}/retire"),
        ("GET", project + "/sections"),
        ("POST", project + "/sections/alignment"),
        ("GET", project + "/user-modeling/context-alignment"),
        ("POST", project + "/user-modeling/context-alignment"),
        ("GET", project + "/requirements/twin-alignment"),
        ("POST", project + "/requirements/twin-alignment"),
        ("GET", project + "/design/requirements-alignment"),
        ("POST", project + "/design/requirements-alignment"),
        ("GET", project + "/user-modeling/archetypes"),
        ("POST", project + "/user-modeling/archetypes"),
        ("PATCH", project + "/user-modeling/archetypes/{persona_id}"),
        ("DELETE", project + "/user-modeling/archetypes/{persona_id}"),
        ("GET", project + "/team/context-alignment"),
        ("POST", project + "/team/context-alignment"),
        ("GET", project + "/evidence"),
        ("POST", project + "/evidence"),
        ("GET", project + "/evidence/{evidence_id}"),
        ("POST", project + "/evidence/{evidence_id}/versions"),
        ("POST", project + "/evidence/{evidence_id}/retire"),
        ("DELETE", project + "/evidence/{evidence_id}/text"),
        ("PUT", project + "/evidence/{evidence_id}/text"),
    }

    assert needed <= set(route_table())
    assert needed <= real_routes
    assert len(ROUTES) == 161


def test_validation_routes_are_exactly_the_two_authorized_read_only_routes() -> None:
    project = PREFIX + "/projects/{project_id}"
    validation = {route for route in route_table() if route[1].startswith(project + "/validation")}

    assert validation == {
        ("GET", project + "/validation"),
        ("GET", project + "/validation/walkthrough"),
    }


class _Client:
    def __init__(self, studio: FakeStudio) -> None:
        self.base = studio.address + PREFIX
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token: str | None = None
        self.headers: dict[str, str] = {}

    def call(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        content: bytes | None = None,
        content_type: str = "application/json",
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, object]:
        data = content if content is not None else None
        if content is None and body is not None:
            data = json.dumps(body).encode("utf-8")
        sent = {"Content-Type": content_type} if data is not None else {}
        if self.token is not None:
            sent["Authorization"] = f"Bearer {self.token}"
        sent.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, headers=sent, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                self.headers = {name.lower(): value for name, value in response.headers.items()}
                return response.status, _parsed(response.read())
        except urllib.error.HTTPError as error:
            with error:
                self.headers = {name.lower(): value for name, value in error.headers.items()}
                return error.code, _parsed(error.read())


def _parsed(content: bytes) -> object:
    return json.loads(content.decode("utf-8")) if content else None


def fits(model: type[BaseModel], reply: tuple[int, object], status: int = 200) -> dict:
    code, payload = reply
    assert code == status, payload
    assert isinstance(payload, dict)
    expected = set(model.model_fields)
    if (
        model in {ProjectImportPayload, ProjectImportOriginPayload}
        and "omitted_sections" not in payload
    ):
        field = model.model_fields["omitted_sections"]
        assert not field.is_required() and field.default in (None, [], ())
        expected.remove("omitted_sections")
    if model is ProjectSectionsPayload and "workflow_inputs" not in payload:
        field = model.model_fields["workflow_inputs"]
        assert not field.is_required() and field.default is None
        expected.remove("workflow_inputs")
    assert set(payload) == expected, model.__name__
    validated = model.model_validate(payload)
    if "omitted_sections" in model.model_fields and "omitted_sections" not in payload:
        assert validated.omitted_sections in (None, [], ())
    return payload


def items_fit(model: type[BaseModel], reply: tuple[int, object]) -> list:
    code, payload = reply
    assert code == 200
    assert isinstance(payload, list)
    assert payload
    for item in payload:
        assert set(item) == set(model.model_fields), model.__name__
        model.model_validate(item)
    return payload


def test_the_answers_of_the_fake_fit_the_response_models_of_the_real_api() -> None:
    with FakeStudio(job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        client = _Client(studio)
        login = fits(
            AuthenticationResponse,
            client.call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD}),
        )
        client.token = str(login["access_token"])
        fits(UserResponse, client.call("GET", "/auth/me"))
        fits(AgentCatalogResponse, client.call("GET", "/agent-catalog"))
        created = client.call(
            "POST", "/projects", {"display_name": "Calcolo mancia", "mode": "GREENFIELD_GENERATION"}
        )
        base = f"/projects/{fits(ProjectResponse, created, 201)['id']}"

        _, state = client.call("POST", base + "/brief-dialogue", {"statement": "Una pagina."})
        while any(turn["answer"] is None for turn in state["snapshot"]["turns"]):
            count = len(state["snapshot"]["turns"])
            _, state = client.call(
                "POST",
                base + "/brief-dialogue/answers",
                {"kind": "UNKNOWN", "expected_turn_count": count},
            )
        _, synthesis = client.call(
            "POST",
            base + "/brief-dialogue/synthesis",
            {"expected_turn_count": len(state["snapshot"]["turns"])},
        )
        ProjectBriefVersionResponse.model_validate(synthesis["brief_version"])
        proposals = [
            BriefAssumptionResponse.model_validate(item) for item in synthesis["assumptions"]
        ]
        assert len(proposals) == 6
        fits(
            BriefAssumptionDecisionResponse,
            client.call("POST", f"{base}/brief-assumptions/{proposals[0].id}/accept", {}),
        )
        fits(
            BriefAssumptionDecisionResponse,
            client.call(
                "POST", f"{base}/brief-assumptions/{proposals[1].id}/reject", {"reason": "No"}
            ),
        )
        fits(
            BriefAssumptionBulkAcceptanceResponse,
            client.call("POST", base + "/brief-assumptions/accept-all"),
        )
        items_fit(BriefAssumptionResponse, client.call("GET", base + "/brief-assumptions"))
        submitted = fits(
            ProjectBriefGateSubmissionResponse,
            client.call("POST", base + "/gates/project-brief/submit"),
            201,
        )
        fits(
            ProjectBriefGateDecisionResponse,
            client.call("POST", base + "/gates/project-brief/decisions", {"action": "APPROVE"}),
        )
        fits(HumanGateResponse, client.call("GET", base + "/gates/project-brief/current"))
        gate_id = submitted["gate"]["id"]
        items_fit(
            HumanGateEventResponse,
            client.call("GET", f"{base}/gates/project-brief/{gate_id}/events"),
        )
        items_fit(ProjectBriefVersionResponse, client.call("GET", base + "/brief-versions"))

        fits(TeamProposalGenerationResponse, client.call("POST", base + "/team-proposals"), 201)
        team = fits(
            TeamProposalVersionResponse, client.call("GET", base + "/team-proposals/current")
        )
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        fits(
            TeamEditResponse,
            client.call("PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited}),
            201,
        )
        fits(ProjectReadinessResponse, client.call("GET", base + "/readiness"))
        fits(
            AgentTeamGateSubmissionResponse,
            client.call("POST", base + "/gates/agent-team/submit"),
            201,
        )
        fits(
            AgentTeamGateDecisionResponse,
            client.call("POST", base + "/gates/agent-team/decisions", {"action": "APPROVE"}),
        )

        fits(
            PersonaProposalCommandPayload,
            client.call("POST", base + "/user-modeling/personas/proposals"),
        )
        for persona in items_fit(
            PersonaVersionPayload, client.call("GET", base + "/user-modeling/personas")
        ):
            fits(
                PersonaDecisionCommandPayload,
                client.call(
                    "POST",
                    f"{base}/user-modeling/personas/{persona['persona_id']}/decision",
                    {"decision": "CONFIRM"},
                ),
            )
        generated = fits(
            SnapshotGenerationCommandPayload,
            client.call("POST", base + "/user-modeling/snapshots/generate"),
        )
        fits(
            UserModelingSnapshotVersionPayload,
            client.call("GET", base + "/user-modeling/snapshots/current"),
        )
        fits(GateCommandPayload, client.call("POST", base + "/user-modeling/gate/submit"))
        fits(
            GateCommandPayload,
            client.call("POST", base + "/user-modeling/gate/decision", {"action": "APPROVE"}),
        )
        fits(HumanGatePayload, client.call("GET", base + "/user-modeling/gate"))
        fits(UserModelingReadinessPayload, client.call("GET", base + "/user-modeling/readiness"))

        fits(
            RequirementsGenerationPayload,
            client.call("POST", base + "/requirements/proposals"),
            201,
        )
        change = fits(
            RequirementsRevisionPayload,
            client.call(
                "POST", base + "/requirements/change-requests", {"request": "Aggiungi il bis"}
            ),
            201,
        )
        items_fit(
            RequirementsSpecificationDiffPayload,
            client.call("GET", base + "/requirements/revisions"),
        )
        fits(
            RequirementsRevisionPayload,
            client.call(
                "POST",
                f"{base}/requirements/revisions/{change['diff']['id']}/decision",
                {"decision": "APPROVE"},
            ),
        )
        fits(
            RequirementsSpecificationVersionPayload,
            client.call("GET", base + "/requirements/current"),
        )
        fits(
            RequirementsGateSubmissionPayload,
            client.call("POST", base + "/requirements/gate/submit"),
        )
        fits(
            RequirementsGateDecisionPayload,
            client.call("POST", base + "/requirements/gate/decision", {"action": "APPROVE"}),
        )
        fits(RequirementsReadinessPayload, client.call("GET", base + "/requirements/readiness"))

        fits(DesignGenerationPayload, client.call("POST", base + "/design/proposals"), 201)
        current = fits(DesignPackageVersionPayload, client.call("GET", base + "/design/current"))
        fits(MockupCapabilities, client.call("GET", base + "/design/mockups/capabilities"))
        chosen = current["package"]["recommended_alternative_id"]
        _, job = client.call(
            "POST",
            base + "/design/mockups/jobs",
            {
                "design_version_id": current["id"],
                "design_content_hash": current["content_hash"],
                "alternative_id": chosen,
            },
        )
        real_job = GenerationJob(
            job_id=UUID(int=1),
            owner_user_id=UUID(int=2),
            project_id=UUID(int=3),
            kind=GenerationJobKind.MOCKUP,
            operation=GenerationOperation.MOCKUP,
            key="key",
            alternative_id=None,
            started_at=datetime(2026, 9, 29, 8, 0, tzinfo=UTC),
        ).to_payload()
        assert list(job) == list(real_job)
        _, finished = client.call("GET", f"{base}/design/mockups/jobs/{job['job_id']}")
        assert list(finished) == list(real_job)
        package = finished["result"]["package"]
        assert set(package) == set(DesignPackagePayload.model_fields)
        DesignPackagePayload.model_validate(package)
        proposed = fits(
            DesignRevisionPayload,
            client.call("POST", base + "/design/revisions", {"package": package}),
            201,
        )
        fits(DesignPackageDiffPayload, (200, proposed["diff"]))
        decided = fits(
            DesignRevisionPayload,
            client.call(
                "POST",
                f"{base}/design/revisions/{proposed['diff']['id']}/decision",
                {"decision": "APPROVE"},
            ),
        )
        version = decided["version"]
        _, run = client.call(
            "POST",
            base + "/design/evaluations",
            {"design_version_id": version["id"], "design_content_hash": version["content_hash"]},
        )
        fits(ReviewPinsPayload, client.call("GET", f"{base}/design/evaluations/{run['id']}/pins"))
        fits(
            ReviewDocumentPayload,
            client.call("GET", f"{base}/design/evaluations/{run['id']}/document"),
        )
        fits(DesignGateSubmissionPayload, client.call("POST", base + "/design/gate/submit"))
        fits(
            DesignGateDecisionPayload,
            client.call("POST", base + "/design/gate/decision", {"action": "APPROVE"}),
        )
        fits(DesignReadinessPayload, client.call("GET", base + "/design/readiness"))

        published = fits(
            KnowledgePackagePublicationPayload,
            client.call("POST", base + "/knowledge-packages"),
            201,
        )
        fits(KnowledgePackageHistoryPayload, client.call("GET", base + "/knowledge-packages"))
        archive = urllib.request.Request(
            f"{client.base}{base}/knowledge-packages/1/archive",
            headers={"Authorization": f"Bearer {client.token}"},
        )
        with client.opener.open(archive, timeout=10) as response:
            content = response.read()
        assert published["version"]["archive_hash"] == response.headers["X-Content-SHA256"]
        body = (
            (
                f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="archive"; '
                'filename="folder.zip"\r\nContent-Type: application/zip\r\n\r\n'
            ).encode()
            + content
            + f"\r\n--{BOUNDARY}--\r\n".encode()
        )
        imported = fits(
            ProjectImportPayload,
            client.call(
                "POST",
                "/project-imports",
                content=body,
                content_type=f"multipart/form-data; boundary={BOUNDARY}",
            ),
            201,
        )
        copy_base = f"/projects/{imported['project']['id']}"
        fits(ProjectImportOriginPayload, client.call("GET", copy_base + "/import"))
        fits(
            DesignGenerationPayload,
            client.call("POST", copy_base + "/design/regenerations"),
            201,
        )
        assert generated["twin_versions"]
        assert studio.errors == []


def canonical_design(package: dict, codes: list[str]) -> None:
    parsed = DesignPackagePayload.model_validate(package)
    rebuilt = DesignPackagePayload.from_domain(parsed.to_domain())
    assert rebuilt.model_dump(mode="json") == parsed.model_dump(mode="json")
    bound = package["generated_mockup"]
    if bound is None:
        return
    alternative = next(
        item
        for item in package["alternatives"]
        if item["id"] == bound["mockup"]["design_alternative_id"]
    )
    visual = alternative["visual_language"]
    mockup = bound_mockup_from_snapshot(bound, token_names=visual["tokens"])
    assert mockup.prototype().to_snapshot() == package["prototype"]
    report = review_generated_mockup(
        mockup.mockup,
        tokens=visual["tokens"],
        requirement_codes=codes,
        text_contrast_threshold=MODES[
            VisualChoices.from_snapshot(visual["choices"]).color_mode
        ].text_threshold,
    )
    assert report.is_acceptable, report.to_snapshot()


@pytest.mark.parametrize(("language", "hosted"), [("it", True), ("en", True), ("en", False)])
def test_the_artifacts_of_the_fake_pass_the_real_domain_rules(language: str, hosted: bool) -> None:
    with FakeStudio(language=language, hosted=hosted, job_polls=0) as studio:
        studio.add_account(EMAIL, PASSWORD)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        client = _Client(studio)
        _, login = client.call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
        client.token = str(login["access_token"])
        base = f"/projects/{project.id}"
        specification = project.current("requirements")["specification"]
        parsed = RequirementsSpecificationPayload.model_validate(specification)
        rebuilt = RequirementsSpecificationPayload.from_domain(parsed.to_domain())
        assert rebuilt.model_dump(mode="json") == parsed.model_dump(mode="json")
        codes = [item["code"] for item in specification["requirements"]]
        _, history = client.call("GET", base + "/design")
        packages = [version["package"] for version in history]
        current = project.current("design")
        if hosted:
            _, started = client.call(
                "POST",
                base + "/design/iterations/jobs",
                {
                    "design_version_id": current["id"],
                    "design_content_hash": current["content_hash"],
                    "request": "Metti il pulsante in alto",
                },
            )
            _, iteration = client.call("GET", f"{base}/design/iterations/jobs/{started['job_id']}")
            packages.append(iteration["result"]["package"])
            other = next(
                item["id"]
                for item in current["package"]["alternatives"]
                if item["id"] != current["package"]["owner_selected_alternative_id"]
            )
            _, started = client.call(
                "POST",
                base + "/design/mockups/jobs",
                {
                    "design_version_id": current["id"],
                    "design_content_hash": current["content_hash"],
                    "alternative_id": other,
                },
            )
            _, mockup = client.call("GET", f"{base}/design/mockups/jobs/{started['job_id']}")
            packages.append(mockup["result"]["package"])
            status, run = client.call(
                "POST",
                base + "/design/evaluations",
                {
                    "design_version_id": current["id"],
                    "design_content_hash": current["content_hash"],
                },
            )
            assert status == 201
            findings = [
                finding for response in run["responses"] for finding in response["findings"]
            ]
            assert findings
            for finding in findings:
                assert synthetic_finding_from_snapshot(finding).to_snapshot() == finding
        assert len(packages) == (4 if hosted else 2)
        for package in packages:
            canonical_design(package, codes)
        assert studio.errors == []


def signed(studio: FakeStudio) -> _Client:
    studio.add_account(EMAIL, PASSWORD)
    client = _Client(studio)
    _, login = client.call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    client.token = str(login["access_token"])
    return client


def test_the_answers_of_a_studio_without_a_model_fit_the_real_models() -> None:
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed(studio)
        ready = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        created = fits(
            DesignGenerationPayload,
            client.call("POST", f"/projects/{ready.id}/design/proposals"),
            201,
        )
        package = created["version"]["package"]
        DesignPackagePayload.model_validate(package).to_domain()
        assert [item["code"] for item in package["alternatives"]] == [
            "DES-001",
            "DES-002",
            "DES-003",
        ]
        fits(
            MockupCapabilities,
            client.call("GET", f"/projects/{ready.id}/design/mockups/capabilities"),
        )
        old = studio.seed_project(
            owner=EMAIL,
            name="Squadra vecchia",
            through="requirements",
            team_without=["UX_UI_DESIGNER"],
        )
        fits(
            TeamProposalVersionResponse,
            client.call("GET", f"/projects/{old.id}/team-proposals/current"),
        )
        status, refused = client.call("POST", f"/projects/{old.id}/design/proposals")
        assert status == 409
        assert set(refused["detail"]) == {"code", "proposal_issue"}
        assert DesignProposalIssueCode(refused["detail"]["proposal_issue"])
        project = fits(
            ProjectResponse,
            client.call(
                "POST", "/projects", {"display_name": "Archivio", "mode": "GREENFIELD_GENERATION"}
            ),
            201,
        )
        base = f"/projects/{project['id']}"
        fields = {
            "name": "Archivio",
            "description": "Una app con database ma senza backend.",
            "problem": "Le ricette sono sparse.",
            "goals": ["Ritrovare una ricetta"],
            "target_users": ["Cuochi"],
            "functional_requirements": ["Cercare una ricetta"],
            "unknown_fields": [
                "domain",
                "technical_constraints",
                "temporal_constraints",
                "budget",
                "non_functional_requirements",
                "risks",
                "stakeholders",
                "available_artifacts",
                "definition_of_done",
            ],
        }
        assert client.call("POST", base + "/brief-versions", fields)[0] == 201
        assert client.call("POST", base + "/gates/project-brief/submit")[0] == 201
        decided = client.call(
            "POST", base + "/gates/project-brief/decisions", {"action": "APPROVE"}
        )
        assert decided[0] == 200
        contested = fits(
            TeamProposalGenerationResponse, client.call("POST", base + "/team-proposals"), 201
        )
        assert contested["status"] == "CREATED"
        assert contested["issues"] == contested["version"]["constraint_issues"]
        assert contested["issues"]
        fits(TeamProposalVersionResponse, (200, contested["version"]))
        selected = [*contested["version"]["selected_agent_ids"], "BACKEND_ENGINEER"]
        edited = fits(
            TeamEditResponse,
            client.call(
                "PATCH", base + "/team-proposals/current", {"selected_agent_ids": selected}
            ),
            201,
        )
        assert edited["status"] == "UPDATED"
        assert studio.errors == []


def test_the_latest_mockup_has_the_keys_of_the_real_answer() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        chosen = project.current("design")["package"]["owner_selected_alternative_id"]
        status, latest = client.call(
            "GET", f"/projects/{project.id}/design/mockups?alternative_id={chosen}"
        )
        assert status == 200
        assert list(latest) == [
            "status",
            "generation_id",
            "design_version_id",
            "design_content_hash",
            "package",
            "approach",
            "changes",
            "warnings",
            "cost_microusd",
        ]
        DesignPackagePayload.model_validate(latest["package"]).to_domain()
        assert studio.errors == []


def test_the_sections_and_the_re_anchoring_fit_the_real_models() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        fits(ProjectSectionsPayload, client.call("GET", base + "/sections"))
        studio.seed_perspective_change(project.id, "SECURITY_REVIEWER")
        behind = fits(ProjectSectionsPayload, client.call("GET", base + "/sections"))
        assert behind["alignment"]["sections"] == ["USER_TWINS", "REQUIREMENTS", "DESIGN"]

        path = base + "/user-modeling/context-alignment"
        fits(UserModelingAlignmentPayload, client.call("GET", path))
        fits(UserModelingRealignmentPayload, client.call("POST", path), 201)
        fits(GateCommandPayload, client.call("POST", base + "/user-modeling/gate/submit"))
        fits(
            GateCommandPayload,
            client.call("POST", base + "/user-modeling/gate/decision", {"action": "APPROVE"}),
        )
        path = base + "/requirements/twin-alignment"
        fits(RequirementsAlignmentPayload, client.call("GET", path))
        fits(RequirementsRealignmentPayload, client.call("POST", path), 201)
        fits(
            RequirementsGateSubmissionPayload,
            client.call("POST", base + "/requirements/gate/submit"),
        )
        fits(
            RequirementsGateDecisionPayload,
            client.call("POST", base + "/requirements/gate/decision", {"action": "APPROVE"}),
        )
        path = base + "/design/requirements-alignment"
        fits(DesignAlignmentPayload, client.call("GET", path))
        fits(DesignRealignmentPayload, client.call("POST", path), 201)
        status, refused = client.call("POST", path)
        assert (status, refused) == (409, {"detail": {"code": "ALREADY_ALIGNED"}})

        other = studio.seed_project(owner=EMAIL, name="Gesto", through="design")
        other_base = f"/projects/{other.id}"
        studio.seed_requirement_removed(other.id)
        removed = fits(DesignAlignmentPayload, client.call("GET", other_base + path[len(base) :]))
        assert removed["missing_codes"] == ["REQ-004", "AC-004"]
        blocked = fits(
            SectionsAlignmentPayload, client.call("POST", other_base + "/sections/alignment")
        )
        assert [item["outcome"] for item in blocked["results"]] == ["BLOCKED"]

        last = studio.seed_project(owner=EMAIL, name="Requisiti", through="design")
        studio.seed_requirements_change(last.id)
        gesture = fits(
            SectionsAlignmentPayload, client.call("POST", f"/projects/{last.id}/sections/alignment")
        )
        assert gesture["status"] == "ALIGNED"
        fits(
            DesignGateSubmissionPayload,
            client.call("POST", f"/projects/{last.id}/design/gate/submit"),
        )
        nothing = fits(
            SectionsAlignmentPayload, client.call("POST", f"/projects/{last.id}/sections/alignment")
        )
        assert (nothing["status"], nothing["results"]) == ("NOTHING_TO_ALIGN", [])
        assert studio.errors == []


def _closed_unit_of_work() -> IdentityUnitOfWork:
    raise AssertionError("a refused registration opens no transaction")


def _owner() -> UserAccount:
    return UserAccount(
        id=UUID(int=1),
        email=NormalizedEmail(EMAIL),
        password_hash="hash-not-real",
        is_active=True,
        created_at=MOMENT,
        updated_at=MOMENT,
    )


@pytest.fixture
def real_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name, raising=False)
    identity = LocalIdentityApplicationService(
        unit_of_work_factory=_closed_unit_of_work,
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(jwt_secret=SecretStr(JWT_SECRET), _env_file=None)
        ),
    )
    application = create_app(
        ApplicationSettings(
            application_name="OrchesTwin Fake Studio Answer Test",
            environment=RuntimeEnvironment.TEST,
            debug=False,
            log_level=LogLevel.INFO,
            api_prefix=PREFIX,
            _env_file=None,
        ),
        runtime=ApplicationRuntime(identity_service=identity),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    application.dependency_overrides[current_user_dependency] = _owner
    with TestClient(application) as client:
        yield client


def _fake_logout(studio: FakeStudio) -> tuple[int, str | None, bytes, bool]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(studio.address + PREFIX + "/auth/logout", method="POST")
    with opener.open(request, timeout=10) as response:
        headers = {name.lower(): value for name, value in response.headers.items()}
        return (
            response.status,
            headers.get("content-type"),
            response.read(),
            "content-length" in headers,
        )


def test_the_added_routes_answer_like_the_real_application(real_client: TestClient) -> None:
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = _Client(studio)
        for body in REFUSED_REGISTRATIONS:
            real = real_client.post(PREFIX + "/auth/register", json=body)
            assert real.status_code == 422
            assert client.call("POST", "/auth/register", body) == (real.status_code, real.json())
        real_logout = real_client.post(PREFIX + "/auth/logout")
        assert _fake_logout(studio) == (
            real_logout.status_code,
            real_logout.headers.get("content-type"),
            real_logout.content,
            "content-length" in real_logout.headers,
        )
        created = fits(
            AuthenticationResponse,
            client.call(
                "POST", "/auth/register", {"email": "new@example.com", "password": PASSWORD}
            ),
            201,
        )
        client.token = str(created["access_token"])
        real_readiness = real_client.get(PREFIX + "/model-runtime/readiness")
        assert client.call("GET", "/model-runtime/readiness") == (
            real_readiness.status_code,
            real_readiness.json(),
        )
        assert studio.errors == []


OTHER = "other@example.com"
PREFER = {"Prefer": "respond-async"}
CHANGE_KEYS = [
    "commit",
    "parent",
    "committed_at",
    "author",
    "message",
    "files",
    "recorded_at",
    "review",
    "decision",
]
RUN_KEYS = [
    "id",
    "commit",
    "reviewed_at",
    "locale",
    "reference",
    "critiques",
    "alignment",
    "cost_microusd",
]
ALIGNMENT_KEYS = [
    "project_id",
    "reference",
    "aligned",
    "pending_changes",
    "stale_reviews",
    "latest_change",
    "tasks",
    "review_available",
]
FIRST_GOALS = {"it": "Chiudere il conto in fretta", "en": "Settle the bill quickly"}
LOCALE = {"it": "it-IT", "en": "en-US"}
DIFF = "diff --git a/src/app.js b/src/app.js\n+// REQ-999 is not known, REQ-003 splits the bill\n"
FILE = {"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}
LIMITS = (
    ({"commit": "abc123"}, ["body", "commit"], "string_pattern_mismatch"),
    ({"commit": "a" * 65}, ["body", "commit"], "string_pattern_mismatch"),
    ({"commit": "z" * 40}, ["body", "commit"], "string_pattern_mismatch"),
    ({"commit": 7}, ["body", "commit"], "string_type"),
    ({"parent": "not-a-hash"}, ["body", "parent"], "string_pattern_mismatch"),
    ({"committed_at": "2026-09-29T10:15:00"}, ["body", "committed_at"], "timezone_aware"),
    ({"committed_at": "yesterday"}, ["body", "committed_at"], "datetime_from_date_parsing"),
    ({"author": "a" * 201}, ["body", "author"], "string_too_long"),
    ({"author": "Ann\x01"}, ["body", "author"], "value_error"),
    ({"message": ""}, ["body", "message"], "string_too_short"),
    ({"message": " \n "}, ["body", "message"], "value_error"),
    ({"message": "m" * 2001}, ["body", "message"], "string_too_long"),
    ({"files": [{**FILE, "kind": "MOVED"}]}, ["body", "files", 0, "kind"], "enum"),
    ({"files": [{**FILE, "path": ""}]}, ["body", "files", 0, "path"], "string_too_short"),
    ({"files": [{**FILE, "path": "   "}]}, ["body", "files", 0, "path"], "value_error"),
    ({"files": [{**FILE, "path": "p" * 501}]}, ["body", "files", 0, "path"], "string_too_long"),
    ({"files": [{**FILE, "added": -1}]}, ["body", "files", 0, "added"], "greater_than_equal"),
    ({"files": [{**FILE, "lines": 3}]}, ["body", "files", 0, "lines"], "extra_forbidden"),
    ({"files": ["src/app.js"]}, ["body", "files", 0], "model_attributes_type"),
    ({"files": [FILE] * 501}, ["body", "files"], "too_long"),
    ({"files": None}, ["body", "files"], "list_type"),
    ({"diff": "d" * 65537}, ["body", "diff"], "string_too_long"),
    ({"diff": "a\x00b"}, ["body", "diff"], "value_error"),
    ({"branch": "main"}, ["body", "branch"], "extra_forbidden"),
)
FOUND = {"twin_id": "00000000-0000-4000-8000-000000000777", "finding": 0}
REVIEW_REFUSALS = (
    ({"locale": "x"}, ["body", "locale"], "string_too_short"),
    ({"locale": "x" * 21}, ["body", "locale"], "string_too_long"),
    ({"locale": "french"}, ["body", "locale"], "string_pattern_mismatch"),
    ({"again": "maybe"}, ["body", "again"], "bool_parsing"),
    ({"again": [True]}, ["body", "again"], "bool_type"),
    ({"prefer": "sync"}, ["body", "prefer"], "extra_forbidden"),
    (None, ["body"], "missing"),
)
DECISION_REFUSALS = (
    ({}, ["body", "kind"], "missing"),
    ({"kind": "LATER"}, ["body", "kind"], "enum"),
    ({"kind": "CODE_TASKS"}, ["body"], "value_error"),
    ({"kind": "CODE_TASKS", "tasks": []}, ["body"], "value_error"),
    ({"kind": "ALIGNED", "tasks": ["Uno"]}, ["body"], "value_error"),
    ({"kind": "CODE_TASKS", "tasks": ["Uno"] * 11}, ["body", "tasks"], "too_long"),
    ({"kind": "CODE_TASKS", "tasks": [""]}, ["body", "tasks", 0], "string_too_short"),
    ({"kind": "CODE_TASKS", "tasks": ["t" * 301]}, ["body", "tasks", 0], "string_too_long"),
    ({"kind": "CODE_TASKS", "tasks": [" \t "]}, ["body", "tasks"], "value_error"),
    ({"kind": "CODE_TASKS", "tasks": None}, ["body", "tasks"], "list_type"),
    ({"kind": "DISMISSED", "note": "n" * 2001}, ["body", "note"], "string_too_long"),
    ({"kind": "DISMISSED", "note": "a\x00"}, ["body", "note"], "value_error"),
    ({"kind": "DISMISSED", "reason": "x"}, ["body", "reason"], "extra_forbidden"),
    ({"kind": "ALIGNED", "findings": [FOUND]}, ["body"], "value_error"),
    (
        {"kind": "CODE_TASKS", "tasks": ["Uno"] * 6, "findings": [FOUND] * 5},
        ["body"],
        "value_error",
    ),
    ({"kind": "CODE_TASKS", "findings": [FOUND] * 11}, ["body", "findings"], "too_long"),
    ({"kind": "CODE_TASKS", "findings": "x"}, ["body", "findings"], "list_type"),
    ({"kind": "CODE_TASKS", "findings": [1]}, ["body", "findings", 0], "model_attributes_type"),
    (
        {"kind": "CODE_TASKS", "findings": [{**FOUND, "twin_id": "x"}]},
        ["body", "findings", 0, "twin_id"],
        "uuid_parsing",
    ),
    (
        {"kind": "CODE_TASKS", "findings": [{**FOUND, "finding": -1}]},
        ["body", "findings", 0, "finding"],
        "greater_than_equal",
    ),
    (
        {"kind": "CODE_TASKS", "findings": [{**FOUND, "finding": 1.5}]},
        ["body", "findings", 0, "finding"],
        "int_from_float",
    ),
    (
        {"kind": "CODE_TASKS", "findings": [{"twin_id": FOUND["twin_id"]}]},
        ["body", "findings", 0, "finding"],
        "missing",
    ),
    (
        {"kind": "CODE_TASKS", "findings": [{**FOUND, "text": "x"}]},
        ["body", "findings", 0, "text"],
        "extra_forbidden",
    ),
)


def commit_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


def change_body(commit: str, message: str = "Add the split of the bill", **changes: object) -> dict:
    body: dict[str, object] = {
        "commit": commit,
        "parent": None,
        "committed_at": "2026-09-29T10:15:00+02:00",
        "author": "Test Author",
        "message": message,
        "files": [dict(FILE)],
        "diff": DIFF,
    }
    body.update(changes)
    return body


def refused(code: str, **extra: object) -> dict:
    return {"detail": {"code": code, **extra}}


def verdict_task(number: int, text: str, commit: str, moment: str) -> dict[str, object]:
    return {
        "code": f"TSK-{number:03d}",
        "text": text,
        "about": {"requirements": [], "screens": [], "criteria": []},
        "origin": {
            "kind": "CODE_CHANGE",
            "commit": commit,
            "test_run_id": None,
            "twin_id": None,
            "twin_name": None,
            "finding": None,
        },
        "from_commit": commit,
        "created_at": moment,
        "status": "OPEN",
        "closed_at": None,
        "note": None,
    }


def invalid(location: list[object], kind: str) -> dict:
    return {"detail": "invalid_request", "errors": [{"loc": location, "type": kind}]}


def record(
    client: _Client, base: str, commit: str, message: str = "Add the split of the bill", **changes
) -> dict:
    status, created = client.call(
        "POST", base + "/code-changes", change_body(commit, message, **changes)
    )
    assert status == 201, created
    return created["change"]


def stranger(studio: FakeStudio) -> _Client:
    studio.add_account(OTHER, PASSWORD)
    client = _Client(studio)
    _, login = client.call("POST", "/auth/login", {"email": OTHER, "password": PASSWORD})
    client.token = str(login["access_token"])
    return client


def poll(client: _Client, base: str, job_id: str) -> dict:
    for _ in range(10):
        status, job = client.call("GET", f"{base}/generation-jobs/{job_id}")
        assert status == 200, job
        if job["status"] != "RUNNING":
            return job
    raise AssertionError("the job never ended")


def test_a_change_is_recorded_once_and_read_back_by_its_prefix() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        first, second = commit_of("first"), commit_of("second")
        status, created = client.call("POST", base + "/code-changes", change_body(first.upper()))
        change = created["change"]
        assert (status, created["status"], list(change)) == (201, "RECORDED", CHANGE_KEYS)
        assert [changed_file_from_snapshot(item).to_snapshot() for item in change["files"]] == [
            FILE
        ]
        assert change == {
            "commit": first,
            "parent": None,
            "committed_at": "2026-09-29T08:15:00+00:00",
            "author": "Test Author",
            "message": "Add the split of the bill",
            "files": [FILE],
            "recorded_at": change["recorded_at"],
            "review": None,
            "decision": None,
        }
        assert datetime.fromisoformat(change["recorded_at"]).utcoffset() == timedelta(0)
        repeated = client.call("POST", base + "/code-changes", change_body(first, "Other words"))
        assert repeated == (200, {"status": "ALREADY_RECORDED", "change": change})
        later = record(client, base, second, "Show the shares", parent=first.upper())
        assert later["parent"] == first
        assert client.call("GET", base + "/code-changes") == (200, {"items": [later, change]})
        assert project.changes() == [later, change]
        assert client.call("GET", f"{base}/code-changes/{first[:7]}") == (
            200,
            {**change, "diff": DIFF},
        )
        assert client.call("GET", f"{base}/code-changes/{second.upper()}")[1]["commit"] == second
        assert client.call("GET", f"{base}/code-changes/{'0' * 40}") == (
            404,
            refused("CODE_CHANGE_NOT_FOUND"),
        )
        for malformed in ("abc", "not-a-commit", "g" * 40):
            assert client.call("GET", f"{base}/code-changes/{malformed}") == (
                404,
                refused("CODE_CHANGE_NOT_FOUND"),
            )
        similar = ("abcdef1" + "0" * 33, "abcdef1" + "1" * 33)
        for commit in similar:
            record(client, base, commit)
        assert client.call("GET", f"{base}/code-changes/abcdef1") == (
            409,
            refused("CODE_CHANGE_AMBIGUOUS"),
        )
        assert client.call("GET", f"{base}/code-changes/abcdef11")[1]["commit"] == similar[1]
        other = stranger(studio)
        for path in ("/alignment", "/code-changes", f"/code-changes/{first}"):
            assert other.call("GET", base + path) == (404, refused("PROJECT_NOT_FOUND"))
        assert other.call("GET", f"{base}/code-changes/{first}/reviews") == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert other.call("POST", base + "/code-changes", change_body(first)) == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert other.call(
            "POST", f"{base}/code-changes/{first}/decision", {"kind": "DISMISSED"}
        ) == (404, refused("PROJECT_NOT_FOUND"))
        assert studio.errors == []


def test_a_change_outside_the_limits_answers_422() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        commit = commit_of("limits")
        for changes, location, kind in LIMITS:
            reply = client.call("POST", base + "/code-changes", {**change_body(commit), **changes})
            assert reply == (422, invalid(location, kind)), changes
        same = client.call(
            "POST", base + "/code-changes", change_body(commit, parent=commit.upper())
        )
        assert same == (422, invalid(["body"], "value_error"))
        assert client.call("POST", base + "/code-changes") == (422, invalid(["body"], "missing"))
        assert project.changes() == []
        short = {
            key: value
            for key, value in change_body(commit, "  Add the split\n\n").items()
            if key not in {"parent", "author", "diff", "files"}
        }
        status, created = client.call("POST", base + "/code-changes", short)
        assert status == 201
        assert {
            key: created["change"][key] for key in ("parent", "author", "message", "files")
        } == {
            "parent": None,
            "author": None,
            "message": "Add the split",
            "files": [],
        }
        assert client.call("GET", f"{base}/code-changes/{commit}")[1]["diff"] == ""
        spaced = change_body(commit_of("spaced"), author="  Test \t Author  ")
        assert client.call("POST", base + "/code-changes", spaced)[1]["change"]["author"] == (
            "Test Author"
        )
        blank = change_body(commit_of("blank"), author="   ")
        assert client.call("POST", base + "/code-changes", blank)[1]["change"]["author"] is None
        largest = change_body(
            "b" * 64,
            "m" * 2000,
            author="a" * 200,
            files=[{**FILE, "path": "p" * 500}] * 500,
            diff="d" * 65536,
        )
        status, created = client.call("POST", base + "/code-changes", largest)
        assert (status, len(created["change"]["files"])) == (201, 500)
        assert record(client, base, "C" * 7)["commit"] == "c" * 7
        assert [item["commit"] for item in project.changes()] == [
            "c" * 7,
            "b" * 64,
            commit_of("blank"),
            commit_of("spaced"),
            commit,
        ]
        assert studio.errors == []


def test_changes_recorded_at_the_same_moment_are_ordered_like_the_real_list() -> None:
    moment = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    with FakeStudio(now=lambda: moment, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        early, late = "1" * 40, "2" * 40
        record(client, base, late, committed_at="2026-09-29T08:30:00+00:00")
        record(client, base, early, committed_at="2026-09-29T08:00:00+00:00")
        record(client, base, "3" * 40, committed_at="2026-09-29T08:30:00+00:00")
        assert [item["commit"] for item in project.changes()] == ["3" * 40, late, early]
        assert studio.errors == []


@pytest.mark.parametrize("hosted", [True, False])
def test_the_alignment_gives_the_reference_and_the_development_state(hosted: bool) -> None:
    with FakeStudio(hosted=hosted, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        requirements = project.current("requirements")
        design = project.current("design")
        package = design["package"]
        chosen = next(
            item["code"]
            for item in package["alternatives"]
            if item["id"] == package["owner_selected_alternative_id"]
        )
        status, alignment = client.call("GET", base + "/alignment")
        assert (status, list(alignment)) == (200, ALIGNMENT_KEYS)
        assert alignment == {
            "project_id": project.id,
            "reference": {
                "requirements": {
                    "version_id": requirements["id"],
                    "version_number": 1,
                    "content_hash": requirements["content_hash"],
                },
                "design": {
                    "version_id": design["id"],
                    "version_number": 2,
                    "content_hash": design["content_hash"],
                    "alternative_code": chosen,
                },
            },
            "aligned": None,
            "pending_changes": 0,
            "stale_reviews": 0,
            "latest_change": None,
            "tasks": [],
            "review_available": hosted,
        }
        assert chosen == ("DES-002" if hosted else "DES-001")
        record(client, base, commit_of("one"))
        latest = record(client, base, commit_of("two"), "Show the shares")
        _, alignment = client.call("GET", base + "/alignment")
        assert (alignment["pending_changes"], alignment["latest_change"]) == (2, latest)
        for through, present in (("requirements", ["requirements"]), ("brief", [])):
            earlier = studio.seed_project(owner=EMAIL, name=f"Fino a {through}", through=through)
            _, other = client.call("GET", f"/projects/{earlier.id}/alignment")
            assert [stage for stage, value in other["reference"].items() if value] == present
            assert other["review_available"] is hosted
        assert studio.errors == []


@pytest.mark.parametrize(
    ("language", "message", "verdict"),
    [
        ("en", "Add the split of the bill", "ALIGNED"),
        ("it", "Nuova schermata per il design del risultato", "DESIGN_OUTDATED"),
        ("en", "Cover a new Requirement for the tip", "REQUIREMENTS_OUTDATED"),
        ("it", "Aggiunto il requisito del bis", "REQUIREMENTS_OUTDATED"),
        ("en", "Fix the drift of the form", "CODE_DRIFT"),
    ],
)
def test_a_review_follows_the_rules_of_the_fake(language: str, message: str, verdict: str) -> None:
    with FakeStudio(language=language, twins=3, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of(message)
        record(client, base, commit, f"{message}\n\nMore words in the body.")
        status, reviewed = client.call(
            "POST", f"{base}/code-changes/{commit[:10]}/reviews", {"locale": LOCALE[language]}
        )
        assert (status, reviewed["status"]) == (201, "REVIEWED")
        run = reviewed["run"]
        assert list(run) == RUN_KEYS
        assert (run["commit"], run["locale"]) == (commit, LOCALE[language])
        assert run["reference"] == {
            "requirements_version_number": 1,
            "design_version_number": 2,
            "alternative_code": "DES-002",
        }
        twins = project.current("twins")["snapshot"]["twin_versions"]
        critiques = run["critiques"]
        assert [(item["twin_id"], item["twin_name"]) for item in critiques] == [
            (twin["twin_id"], twin["profile"]["name"]) for twin in twins
        ]
        assert [item["verdict"] for item in critiques] == ["CONCERN", "FINE", "FINE"]
        assert [
            [(finding["severity"], finding["about"]) for finding in item["findings"]]
            for item in critiques
        ] == [
            [
                ("MEDIUM", {"requirement": "REQ-003", "screen": None, "file": "src/app.js"}),
                ("LOW", {"requirement": None, "screen": "SCR-001", "file": None}),
            ],
            [("LOW", {"requirement": "REQ-003", "screen": "SCR-001", "file": None})],
            [],
        ]
        for item in critiques:
            assert twin_critique_from_snapshot(item).to_snapshot() == item
            assert FIRST_GOALS[language] in item["summary"]
            assert message in item["summary"]
            assert "More words" not in item["summary"]
            for finding in item["findings"]:
                assert finding["text"] and finding["action"]
        alignment = run["alignment"]
        assert alignment_verdict_from_snapshot(alignment).to_snapshot() == alignment
        assert alignment["status"] == verdict
        assert message in alignment["summary"]
        assert alignment["affected"] == {"requirements": ["REQ-003"], "screens": ["SCR-001"]}
        assert (alignment["design_request"] is not None) is (verdict == "DESIGN_OUTDATED")
        assert (alignment["requirements_request"] is not None) is (
            verdict == "REQUIREMENTS_OUTDATED"
        )
        assert len(alignment["code_tasks"]) == (2 if verdict == "CODE_DRIFT" else 0)
        cost = 3 * COSTS["CODE_CHANGE_REVIEW"] + COSTS["CODE_ALIGNMENT"]
        assert run["cost_microusd"] == cost == 850_000
        assert studio.spent_microusd == project.spent_microusd == cost
        _, usage = client.call("GET", base + "/model-usage")
        assert [(item["purpose"], item["cost_microusd"]) for item in reversed(usage["items"])] == [
            ("CODE_CHANGE_REVIEW", 200_000),
            ("CODE_CHANGE_REVIEW", 200_000),
            ("CODE_CHANGE_REVIEW", 200_000),
            ("CODE_ALIGNMENT", 250_000),
        ]
        assert {item["task"] for item in usage["items"]} == {"user-twin-evaluation"}
        assert project.change_reviews() == [run]
        _, change = client.call("GET", f"{base}/code-changes/{commit}")
        assert change["review"] == {
            "run_id": run["id"],
            "reviewed_at": run["reviewed_at"],
            "verdict": verdict,
            "summary": alignment["summary"],
            "reference": run["reference"],
            "stale": False,
        }
        assert studio.errors == []


@pytest.mark.parametrize(
    ("diff", "requirement"),
    [
        (DIFF, "REQ-003"),
        ("+// REQ-002 and REQ-004 are both here\n", "REQ-002"),
        ("+// REQ-999 is the only code\n", "REQ-001"),
        ("", "REQ-001"),
    ],
)
def test_the_first_finding_cites_the_first_known_requirement_of_the_diff(
    diff: str, requirement: str
) -> None:
    with FakeStudio(language="en", twins=1, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of(diff)
        record(client, base, commit, diff=diff, files=[])
        _, reviewed = client.call(
            "POST", f"{base}/code-changes/{commit}/reviews", {"locale": "en-US"}
        )
        (critique,) = reviewed["run"]["critiques"]
        assert [finding["about"] for finding in critique["findings"]] == [
            {"requirement": requirement, "screen": None, "file": None},
            {"requirement": None, "screen": "SCR-001", "file": None},
        ]
        assert reviewed["run"]["alignment"]["affected"] == {
            "requirements": [requirement],
            "screens": ["SCR-001"],
        }
        assert reviewed["run"]["cost_microusd"] == 450_000


def test_a_second_review_repeats_the_content_in_a_new_run() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("again")
        record(client, base, commit, "Cambia il design del risultato")
        path = f"{base}/code-changes/{commit}/reviews"
        _, first = client.call("POST", path, {"locale": "it-IT"})
        status, second = client.call("POST", path, {"locale": "it-IT", "again": True})
        assert status == 201
        older, newer = first["run"], second["run"]
        assert newer["id"] != older["id"]
        assert datetime.fromisoformat(newer["reviewed_at"]) > datetime.fromisoformat(
            older["reviewed_at"]
        )
        same = ("commit", "locale", "reference", "critiques", "alignment", "cost_microusd")
        assert {key: newer[key] for key in same} == {key: older[key] for key in same}
        assert newer["alignment"]["status"] == "DESIGN_OUTDATED"
        assert client.call("GET", path) == (200, {"items": [newer, older]})
        assert project.change_reviews() == [newer, older]
        _, change = client.call("GET", f"{base}/code-changes/{commit}")
        assert change["review"]["run_id"] == newer["id"]
        assert studio.spent_microusd == 2 * 650_000
        for body, location, kind in REVIEW_REFUSALS:
            assert client.call("POST", path, body) == (422, invalid(location, kind)), body
        assert client.call("POST", path, {}) == (409, refused("CODE_CHANGE_REVIEW_EXISTS"))
        _, french = client.call("POST", path, {"locale": "fr-FR", "again": "yes"})
        _, default = client.call("POST", path, {"again": 1})
        assert (french["run"]["locale"], default["run"]["locale"]) == ("fr-FR", "it-IT")
        assert len(project.change_reviews()) == 4
        assert studio.errors == []


def test_the_refusals_of_a_review_come_in_the_order_of_the_contract() -> None:
    body = {"locale": "it-IT"}
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("refusals")
        record(client, base, commit)
        path = f"{base}/code-changes/{commit}/reviews"
        assert stranger(studio).call("POST", f"{base}/code-changes/{'0' * 40}/reviews", body) == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert client.call("POST", f"{base}/code-changes/{'0' * 40}/reviews", body) == (
            404,
            refused("CODE_CHANGE_NOT_FOUND"),
        )
        for similar in ("abcdef1" + "0" * 33, "abcdef1" + "1" * 33):
            record(client, base, similar)
        assert client.call("POST", f"{base}/code-changes/abcdef1/reviews", body) == (
            409,
            refused("CODE_CHANGE_AMBIGUOUS"),
        )
        assert client.call("POST", path, body)[0] == 201
        assert client.call("POST", path, body) == (409, refused("CODE_CHANGE_REVIEW_EXISTS"))
        _, team = client.call("GET", base + "/team-proposals/current")
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        edit = client.call(
            "PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited}
        )
        assert edit[0] == 201
        assert project.approved("design") and not project.approved("twins")
        assert client.call("POST", path, body) == (409, refused("CODE_CHANGE_REVIEW_EXISTS"))
        assert client.call("POST", path, {**body, "again": True}) == (
            409,
            refused("USER_MODELING_APPROVAL_REQUIRED"),
        )
        assert studio.spent_microusd == 650_000
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed(studio)
        expected = (
            ("twins", 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
            ("requirements", 409, "DESIGN_APPROVAL_REQUIRED"),
            ("design", 503, "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"),
        )
        for through, status, code in expected:
            project = studio.seed_project(owner=EMAIL, name=f"Fino a {through}", through=through)
            base = f"/projects/{project.id}"
            commit = commit_of(through)
            record(client, base, commit)
            path = f"{base}/code-changes/{commit}/reviews"
            assert client.call("POST", path, body) == (status, refused(code))
            started = client.call("POST", path, body, headers=PREFER)
            assert started[0] == 202
            job = poll(client, base, started[1]["job_id"])
            assert (job["status"], job["response"]) == (
                "FAILED",
                {"status_code": status, "body": refused(code)},
            )
            assert project.change_reviews() == []
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_a_review_that_passes_the_ceiling_is_not_stored() -> None:
    exceeded = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
    with FakeStudio(budget_usd=1.0, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("ceiling")
        record(client, base, commit)
        path = f"{base}/code-changes/{commit}/reviews"
        assert client.call("POST", path, {"locale": "it-IT"})[0] == 201
        assert studio.spent_microusd == 650_000
        refused_review = client.call("POST", path, {"locale": "it-IT", "again": True})
        assert refused_review == (402, exceeded)
        assert studio.spent_microusd == 1_000_000 - 150_000
        started = client.call("POST", path, {"locale": "it-IT", "again": True}, headers=PREFER)
        job = poll(client, base, started[1]["job_id"])
        assert (job["status"], job["response"]) == (
            "FAILED",
            {"status_code": 402, "body": exceeded},
        )
        assert len(project.change_reviews()) == 1
        _, usage = client.call("GET", base + "/model-usage")
        assert usage["totals"]["cost_microusd"] == studio.spent_microusd
        assert studio.errors == []


def test_a_review_with_prefer_runs_as_a_request_job() -> None:
    body = {"locale": "en-US", "again": False}
    with FakeStudio(language="en", job_polls=2) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        commits = [commit_of(f"job {index}") for index in range(5)]
        for commit in commits:
            record(client, base, commit)
        path = f"{base}/code-changes/{commits[0]}/reviews"
        status, started = client.call("POST", path, body, headers=PREFER)
        assert (status, client.headers["preference-applied"]) == (202, "respond-async")
        assert (started["kind"], started["operation"], started["status"]) == (
            "REQUEST",
            "CODE_CHANGE_REVIEW",
            "RUNNING",
        )
        assert client.call("POST", path, body, headers=PREFER)[1]["job_id"] == started["job_id"]
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert studio._jobs[started["job_id"]].key == (
            f"CODE_CHANGE_REVIEW:commit={commits[0]}:{digest}"
        )
        again = client.call("POST", path, {**body, "again": True}, headers=PREFER)
        assert again[1]["job_id"] != started["job_id"]
        job_path = f"{base}/generation-jobs/{started['job_id']}"
        statuses = [client.call("GET", job_path)[1]["status"] for _ in range(3)]
        assert statuses == ["RUNNING", "RUNNING", "SUCCEEDED"]
        _, finished = client.call("GET", job_path)
        assert finished["response"] == {
            "status_code": 201,
            "body": {"status": "REVIEWED", "run": project.change_reviews()[0]},
        }
        for commit in commits[1:4]:
            later = client.call(
                "POST", f"{base}/code-changes/{commit}/reviews", body, headers=PREFER
            )
            assert later[0] == 202
        busy = client.call(
            "POST", f"{base}/code-changes/{commits[4]}/reviews", body, headers=PREFER
        )
        assert busy == (429, refused("TOO_MANY_GENERATIONS"))
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("failures")
        record(client, base, commit)
        path = f"{base}/code-changes/{commit}/reviews"
        studio.fail_job("CODE_CHANGE_REVIEW", code="TIMEOUT")
        failed = poll(client, base, client.call("POST", path, body, headers=PREFER)[1]["job_id"])
        assert (failed["status"], failed["response"]) == (
            "FAILED",
            {
                "status_code": 503,
                "body": {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}},
            },
        )
        studio.lose_job("CODE_CHANGE_REVIEW")
        lost = client.call("POST", path, body, headers=PREFER)[1]
        assert client.call("GET", f"{base}/generation-jobs/{lost['job_id']}") == (
            404,
            refused("GENERATION_JOB_NOT_FOUND"),
        )
        assert project.change_reviews() == []
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_decisions_set_the_aligned_point_and_the_tasks() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        first, second, third = (commit_of(name) for name in ("first", "second", "third"))
        for commit in (first, second, third):
            record(client, base, commit)

        def decide(commit: str, body: object) -> tuple[int, object]:
            return client.call("POST", f"{base}/code-changes/{commit}/decision", body)

        assert client.call("POST", f"{base}/code-changes/{first}/reviews", {})[0] == 201
        texts = [
            "  Riportare il codice   in linea con la schermata SCR-002. ",
            "Coprire REQ-003 con un test automatico.",
        ]
        status, decided = decide(
            first[:8], {"kind": "CODE_TASKS", "note": "  Da fare\n", "tasks": texts}
        )
        assert (status, list(decided)) == (200, ["status", "change", "alignment"])
        assert decided["status"] == "DECIDED"
        moment = decided["change"]["decision"]["decided_at"]
        assert decided["change"]["decision"] == {
            "kind": "CODE_TASKS",
            "decided_at": moment,
            "note": "Da fare",
        }
        assert decided["alignment"] == client.call("GET", base + "/alignment")[1]
        subjects = {"requirements": ["REQ-003"], "screens": ["SCR-001"], "criteria": []}
        assert decided["alignment"]["tasks"] == [
            verdict_task(1, "Riportare il codice in linea con la schermata SCR-002.", first, moment)
            | {"about": subjects},
            verdict_task(2, texts[1], first, moment) | {"about": subjects},
        ]
        assert decided["alignment"]["pending_changes"] == 3
        _, aligned = decide(second, {"kind": "ALIGNED"})
        point = {
            "commit": second,
            "decided_at": aligned["change"]["decision"]["decided_at"],
            "requirements_version_number": 1,
            "design_version_number": 2,
        }
        assert aligned["change"]["decision"]["note"] is None
        assert (aligned["alignment"]["aligned"], aligned["alignment"]["pending_changes"]) == (
            point,
            1,
        )
        assert aligned["alignment"]["tasks"] == []
        assert [task["status"] for task in project.tasks()] == ["DONE", "DONE"]
        assert project.aligned() == point
        pending = client.call("GET", base + "/code-changes?pending=true")[1]["items"]
        assert [item["commit"] for item in pending] == [third]
        everything = client.call("GET", base + "/code-changes?pending=0")[1]["items"]
        assert [item["commit"] for item in everything] == [third, second, first]
        assert client.call("GET", base + "/code-changes?pending=maybe") == (
            422,
            {
                "detail": "invalid_request",
                "errors": [{"loc": ["query", "pending"], "type": "bool_parsing"}],
            },
        )
        assert decide(third, {"kind": "ALIGNED"})[1]["alignment"]["pending_changes"] == 0
        _, dismissed = decide(third, {"kind": "DISMISSED", "note": " \n "})
        assert dismissed["change"]["decision"]["note"] is None
        assert dismissed["alignment"]["aligned"] == point
        assert dismissed["alignment"]["pending_changes"] == 1
        for kind in ("DESIGN_CHANGE", "REQUIREMENTS_CHANGE"):
            _, recorded = decide(third, {"kind": kind, "note": "Nuova versione"})
            assert recorded["change"]["decision"]["kind"] == kind
            assert recorded["alignment"]["aligned"] == point
        _, more = decide(third, {"kind": "CODE_TASKS", "tasks": ["Rifare il riepilogo."]})
        assert more["alignment"]["tasks"] == [
            verdict_task(3, "Rifare il riepilogo.", third, more["change"]["decision"]["decided_at"])
        ]
        assert [task["closed_at"] for task in project.tasks()[:2]] == [
            aligned["change"]["decision"]["decided_at"]
        ] * 2
        assert [task["code"] for task in project.tasks()] == ["TSK-001", "TSK-002", "TSK-003"]
        for body, location, kind in DECISION_REFUSALS:
            assert decide(first, body) == (422, invalid(location, kind)), body
        assert decide("0" * 40, {"kind": "ALIGNED"}) == (404, refused("CODE_CHANGE_NOT_FOUND"))
        largest = decide(
            first, {"kind": "CODE_TASKS", "tasks": ["t" * 300] * 10, "note": "n" * 2000}
        )
        assert largest[0] == 200
        assert len(project.tasks()) == 13
        assert project.aligned() == point
        assert studio.spent_microusd == 650_000
        assert studio.errors == []


def test_an_aligned_decision_closes_only_the_tasks_of_that_change_and_older_ones() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        older, middle, newer = (commit_of(name) for name in ("older", "middle", "newer"))
        for commit in (older, middle, newer):
            record(client, base, commit)

        def decide(commit: str, body: object) -> dict:
            status, answer = client.call("POST", f"{base}/code-changes/{commit}/decision", body)
            assert status == 200, answer
            return answer

        def statuses() -> list[tuple[str, str, str]]:
            return [(task["code"], task["from_commit"], task["status"]) for task in project.tasks()]

        for commit, text in ((older, "Primo."), (middle, "Secondo."), (newer, "Terzo.")):
            decide(commit, {"kind": "CODE_TASKS", "tasks": [text]})
        aligned = decide(middle, {"kind": "ALIGNED"})
        assert statuses() == [
            ("TSK-001", older, "DONE"),
            ("TSK-002", middle, "DONE"),
            ("TSK-003", newer, "OPEN"),
        ]
        assert [task["code"] for task in aligned["alignment"]["tasks"]] == ["TSK-003"]
        assert aligned["alignment"]["pending_changes"] == 1
        decide(older, {"kind": "CODE_TASKS", "tasks": ["Quarto."]})
        assert statuses()[3] == ("TSK-004", older, "OPEN")
        again = decide(middle, {"kind": "ALIGNED"})
        assert [task["code"] for task in again["alignment"]["tasks"]] == ["TSK-003"]
        assert statuses()[3] == ("TSK-004", older, "DONE")
        closed = decide(newer, {"kind": "ALIGNED"})
        assert closed["alignment"]["tasks"] == []
        assert [status for _, _, status in statuses()] == ["DONE"] * 4
        assert studio.errors == []


def test_invalid_alignment_requests_answer_like_the_real_application(
    real_client: TestClient,
) -> None:
    commit = commit_of("compared")
    cases = [
        *(("POST", "/code-changes", {**change_body(commit), **item[0]}) for item in LIMITS),
        ("POST", "/code-changes", change_body(commit, parent=commit.upper())),
        ("POST", "/code-changes", None),
        *(("POST", f"/code-changes/{commit}/reviews", item[0]) for item in REVIEW_REFUSALS),
        *(("POST", f"/code-changes/{commit}/decision", item[0]) for item in DECISION_REFUSALS),
        ("GET", "/code-changes?pending=maybe", None),
    ]
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        for method, path, body in cases:
            real = real_client.request(method, PREFIX + base + path, json=body)
            assert real.status_code == 422, (path, body, real.text)
            assert client.call(method, base + path, body) == (422, real.json()), (path, body)
        assert project.changes() == []
        assert studio.errors == []


PLAN_KEYS = [
    "id",
    "created_at",
    "locale",
    "reference",
    "application",
    "criteria",
    "replan_of",
    "paths",
    "not_covered",
    "cost_microusd",
]
TEST_RUN_KEYS = [
    "id",
    "started_at",
    "finished_at",
    "recorded_at",
    "application",
    "browsers",
    "reference",
    "summary",
    "criteria",
    "not_covered",
    "results",
    "critiques",
    "reviewed_at",
    "cost_microusd",
]
TEST_REVIEW_KEYS = ["id", "run_id", "reviewed_at", "locale", "critiques", "cost_microusd"]
OVERVIEW_KEYS = [
    "project_id",
    "reference",
    "plan_available",
    "plans",
    "runs",
    "latest_run",
    "latest_run_stale",
    "latest_review",
]
CRITERIA_CODES = ["AC-001", "AC-002", "AC-003", "AC-004"]
APPLICATION = {"kind": "STATIC", "address": "dist"}
PAGE = "http://127.0.0.1:41234/"
TITLE = "Calcolo mancia"
ELEMENT = {
    "index": 0,
    "role": "heading",
    "name": "Calcolo mancia",
    "value": None,
    "state": None,
    "options": None,
}
COMBOBOX = {
    "index": 2,
    "role": "combobox",
    "name": "Mancia",
    "value": "10%",
    "state": None,
    "options": ["5%", "10%", "15%"],
}
SNAPSHOT = {
    "url": PAGE,
    "title": TITLE,
    "text": "Calcolo mancia Importo Mancia",
    "elements": [
        ELEMENT,
        {
            "index": 1,
            "role": "textbox",
            "name": "Importo",
            "value": "34,50",
            "state": None,
            "options": None,
        },
        COMBOBOX,
    ],
}
CHROME = {"name": "chrome", "version": "151.0.7922.76"}
FIREFOX = {"name": "firefox", "version": "156.0.1"}
REFERENCE = {
    "requirements_version_number": 1,
    "design_version_number": 2,
    "alternative_code": "DES-002",
}
UNKNOWN_ID = "00000000-0000-4000-8000-000000000999"
OTHER_PLAN = "00000000-0000-4000-8000-000000000998"
OPEN_STEP = {"action": "OPEN", "target": None, "value": "/", "expect": None}
CLICK_STEP = {
    "action": "CLICK",
    "target": {"role": "button", "name": "Calcola"},
    "value": None,
    "expect": None,
}
CHECK_STEP = {
    "action": "CHECK",
    "target": None,
    "value": None,
    "expect": {"kind": "TEXT_VISIBLE", "target": None, "text": "Mancia"},
}
PATH = {"code": "TP-001", "heading": "Calcolo", "criteria": ["AC-001"], "steps": [OPEN_STEP]}
EARLIER = {
    **PATH,
    "steps": [OPEN_STEP, CLICK_STEP],
    "blocked_step": 2,
    "detail": "target not found: button: Calcola",
    "snapshot": SNAPSHOT,
}
STEP_RESULT = {
    "index": 1,
    "status": "DONE",
    "detail": None,
    "url": PAGE,
    "title": TITLE,
    "screenshot": "TP-001/chrome/01.png",
}
RESULT = {
    "path": PATH,
    "browser": "chrome",
    "status": "PASSED",
    "seconds": 1.5,
    "steps": [STEP_RESULT],
    "page_text": TITLE,
}
RUN = {
    "plan_id": UNKNOWN_ID,
    "replan_ids": [],
    "started_at": "2026-09-29T10:00:00+02:00",
    "finished_at": "2026-09-29T10:02:30+02:00",
    "application": APPLICATION,
    "browsers": [CHROME],
    "results": [RESULT],
    "not_covered": [],
}
HIDDEN_TEXT_REFUSALS = (
    (None, "string_type"),
    (5, "string_type"),
    (["Totale"], "string_type"),
    ("h" * 100_001, "string_too_long"),
)
PLAN_REFUSALS = (
    ({"locale": "x"}, ["body", "locale"], "string_too_short"),
    ({"locale": "french"}, ["body", "locale"], "string_pattern_mismatch"),
    ({"application": "dist"}, ["body", "application"], "model_attributes_type"),
    ({"application": None}, ["body", "application"], "model_attributes_type"),
    (
        {"application": {"kind": "FILE", "address": "dist"}},
        ["body", "application", "kind"],
        "enum",
    ),
    (
        {"application": {"kind": "URL", "address": ""}},
        ["body", "application", "address"],
        "string_too_short",
    ),
    (
        {"application": {"kind": "URL", "address": "a" * 501}},
        ["body", "application", "address"],
        "string_too_long",
    ),
    (
        {"application": {"kind": "URL", "address": "x", "port": 80}},
        ["body", "application", "port"],
        "extra_forbidden",
    ),
    *(
        (
            {"application": {"kind": kind, "address": address}},
            ["body", "application"],
            "value_error",
        )
        for kind, address in (
            ("URL", "   "),
            ("URL", "http://"),
            ("URL", "ftp://example.com"),
            ("URL", "http://exa mple.com"),
            ("STATIC", "../dist"),
            ("STATIC", "C:/dist"),
            ("STATIC", "dist\\app"),
            ("STATIC", "/dist"),
        )
    ),
    ({"snapshot": None}, ["body", "snapshot"], "model_attributes_type"),
    (
        {"snapshot": {**SNAPSHOT, "text": "t" * 100_001}},
        ["body", "snapshot", "text"],
        "string_too_long",
    ),
    (
        {"snapshot": {**SNAPSHOT, "elements": [ELEMENT] * 151}},
        ["body", "snapshot", "elements"],
        "too_long",
    ),
    (
        {"snapshot": {**SNAPSHOT, "elements": [ELEMENT, ELEMENT]}},
        ["body", "snapshot"],
        "value_error",
    ),
    (
        {"snapshot": {**SNAPSHOT, "elements": [{**ELEMENT, "role": "widget"}]}},
        ["body", "snapshot", "elements", 0, "role"],
        "literal_error",
    ),
    (
        {"snapshot": {**SNAPSHOT, "elements": [{**ELEMENT, "index": -1}]}},
        ["body", "snapshot", "elements", 0, "index"],
        "greater_than_equal",
    ),
    (
        {"snapshot": {**SNAPSHOT, "elements": [{**ELEMENT, "state": "open"}]}},
        ["body", "snapshot", "elements", 0, "state"],
        "literal_error",
    ),
    (
        {"snapshot": {**SNAPSHOT, "elements": [{**ELEMENT, "options": ["5%"]}]}},
        ["body", "snapshot", "elements", 0],
        "value_error",
    ),
    (
        {"snapshot": {**SNAPSHOT, "elements": [{**COMBOBOX, "options": ["o"] * 21}]}},
        ["body", "snapshot", "elements", 0, "options"],
        "too_long",
    ),
    (
        {"snapshot": {key: value for key, value in SNAPSHOT.items() if key != "title"}},
        ["body", "snapshot", "title"],
        "missing",
    ),
    *(
        (
            {"snapshot": {**SNAPSHOT, "hidden_text": value}},
            ["body", "snapshot", "hidden_text"],
            kind,
        )
        for value, kind in HIDDEN_TEXT_REFUSALS
    ),
    (
        {"snapshot": {**SNAPSHOT, "hidden": "Totale"}},
        ["body", "snapshot", "hidden"],
        "extra_forbidden",
    ),
    ({"criteria": []}, ["body", "criteria"], "too_short"),
    ({"criteria": [""]}, ["body", "criteria", 0], "string_too_short"),
    ({"criteria": ["AC 001"]}, ["body", "criteria", 0], "string_pattern_mismatch"),
    ({"criteria": ["AC-001"] * 201}, ["body", "criteria"], "too_long"),
    ({"earlier": [EARLIER] * 6}, ["body", "earlier"], "too_long"),
    ({"earlier": [EARLIER, EARLIER]}, ["body"], "value_error"),
    (
        {"earlier": [{**EARLIER, "code": "P-1"}]},
        ["body", "earlier", 0, "code"],
        "string_pattern_mismatch",
    ),
    (
        {"earlier": [{**EARLIER, "heading": ""}]},
        ["body", "earlier", 0, "heading"],
        "string_too_short",
    ),
    ({"earlier": [{**EARLIER, "heading": "   "}]}, ["body", "earlier", 0], "value_error"),
    (
        {"earlier": [{**EARLIER, "criteria": ["AC-001"] * 7}]},
        ["body", "earlier", 0, "criteria"],
        "too_long",
    ),
    (
        {"earlier": [{**EARLIER, "criteria": ["AC-001", "AC-001"]}]},
        ["body", "earlier", 0],
        "value_error",
    ),
    (
        {"earlier": [{**EARLIER, "criteria": ["XYZ"]}]},
        ["body", "earlier", 0, "criteria", 0],
        "string_pattern_mismatch",
    ),
    (
        {"earlier": [{**EARLIER, "steps": [OPEN_STEP] * 13}]},
        ["body", "earlier", 0, "steps"],
        "too_long",
    ),
    (
        {"earlier": [{**EARLIER, "steps": [CLICK_STEP], "blocked_step": 1}]},
        ["body", "earlier", 0],
        "value_error",
    ),
    ({"earlier": [{**EARLIER, "blocked_step": 3}]}, ["body", "earlier", 0], "value_error"),
    (
        {"earlier": [{**EARLIER, "blocked_step": 0}]},
        ["body", "earlier", 0, "blocked_step"],
        "greater_than_equal",
    ),
    (
        {"earlier": [{**EARLIER, "blocked_step": 13}]},
        ["body", "earlier", 0, "blocked_step"],
        "less_than_equal",
    ),
    (
        {"earlier": [{**EARLIER, "detail": "d" * 100_001}]},
        ["body", "earlier", 0, "detail"],
        "string_too_long",
    ),
    *(
        (
            {"earlier": [{**EARLIER, "snapshot": {**SNAPSHOT, "hidden_text": value}}]},
            ["body", "earlier", 0, "snapshot", "hidden_text"],
            kind,
        )
        for value, kind in HIDDEN_TEXT_REFUSALS
    ),
    (
        {"earlier": [{**EARLIER, "steps": [{**OPEN_STEP, "value": None}], "blocked_step": 1}]},
        ["body", "earlier", 0, "steps", 0],
        "value_error",
    ),
    *(
        (
            {"earlier": [{**EARLIER, "steps": [OPEN_STEP, step]}]},
            ["body", "earlier", 0, "steps", 1],
            "value_error",
        )
        for step in (
            {**CLICK_STEP, "target": None},
            {**CLICK_STEP, "value": "x"},
            {"action": "PRESS", "target": None, "value": "F5", "expect": None},
            {**CHECK_STEP, "expect": None},
            {**CHECK_STEP, "value": "x"},
            {
                "action": "TYPE",
                "target": {"role": "button", "name": "Calcola"},
                "value": "1",
                "expect": None,
            },
            {
                "action": "SELECT",
                "target": {"role": "textbox", "name": "Importo"},
                "value": "5%",
                "expect": None,
            },
            {
                "action": "TYPE",
                "target": {"role": "textbox", "name": "Importo"},
                "value": "  ",
                "expect": None,
            },
            {**OPEN_STEP, "value": "ftp://example.com"},
        )
    ),
    *(
        (
            {"earlier": [{**EARLIER, "steps": [OPEN_STEP, {**CHECK_STEP, "expect": expect}]}]},
            ["body", "earlier", 0, "steps", 1, "expect"],
            "value_error",
        )
        for expect in (
            {"kind": "VALUE_IS", "target": None, "text": "3"},
            {"kind": "TEXT_VISIBLE", "target": {"role": None, "name": "Mancia"}, "text": "Mancia"},
            {"kind": "ELEMENT_VISIBLE", "target": {"role": None, "name": "Mancia"}, "text": "x"},
            {"kind": "TEXT_VISIBLE", "target": None, "text": None},
            {"kind": "TEXT_VISIBLE", "target": None, "text": "   "},
        )
    ),
    (
        {"earlier": [{**EARLIER, "steps": [OPEN_STEP, {**CLICK_STEP, "action": "SWIPE"}]}]},
        ["body", "earlier", 0, "steps", 1, "action"],
        "enum",
    ),
    (
        {"earlier": [{**EARLIER, "steps": [OPEN_STEP, {**CLICK_STEP, "target": {"name": ""}}]}]},
        ["body", "earlier", 0, "steps", 1, "target", "name"],
        "string_too_short",
    ),
    (
        {"earlier": [{**EARLIER, "steps": [OPEN_STEP, {**CLICK_STEP, "target": {"name": "   "}}]}]},
        ["body", "earlier", 0, "steps", 1, "target"],
        "value_error",
    ),
    (
        {
            "earlier": [
                {
                    **EARLIER,
                    "steps": [OPEN_STEP, {**CLICK_STEP, "target": {"role": "widget", "name": "x"}}],
                }
            ]
        },
        ["body", "earlier", 0, "steps", 1, "target", "role"],
        "literal_error",
    ),
    ({"prefer": "sync"}, ["body", "prefer"], "extra_forbidden"),
)
RUN_REFUSALS = (
    ({"plan_id": "plan"}, ["body", "plan_id"], "uuid_parsing"),
    ({"replan_ids": ["x"]}, ["body", "replan_ids", 0], "uuid_parsing"),
    ({"replan_ids": [OTHER_PLAN, OTHER_PLAN]}, ["body"], "value_error"),
    ({"replan_ids": [UNKNOWN_ID]}, ["body"], "value_error"),
    (
        {"replan_ids": [f"00000000-0000-4000-8000-00000000099{index}" for index in range(6)]},
        ["body", "replan_ids"],
        "too_long",
    ),
    ({"started_at": "2026-09-29T10:00:00"}, ["body", "started_at"], "timezone_aware"),
    ({"finished_at": "later"}, ["body", "finished_at"], "datetime_from_date_parsing"),
    ({"finished_at": "2026-09-29T09:00:00+02:00"}, ["body"], "value_error"),
    ({"application": {"kind": "URL"}}, ["body", "application", "address"], "missing"),
    ({"application": {"kind": "STATIC", "address": ".."}}, ["body", "application"], "value_error"),
    ({"browsers": []}, ["body", "browsers"], "too_short"),
    ({"browsers": [CHROME] * 4}, ["body", "browsers"], "too_long"),
    ({"browsers": [CHROME, CHROME]}, ["body"], "value_error"),
    (
        {"browsers": [{"name": "safari", "version": "18"}]},
        ["body", "browsers", 0, "name"],
        "literal_error",
    ),
    (
        {"browsers": [{**CHROME, "version": ""}]},
        ["body", "browsers", 0, "version"],
        "string_too_short",
    ),
    ({"browsers": [{**CHROME, "version": "   "}]}, ["body", "browsers", 0], "value_error"),
    (
        {"browsers": [{**CHROME, "version": "v" * 81}]},
        ["body", "browsers", 0, "version"],
        "string_too_long",
    ),
    ({"results": [RESULT] * 61}, ["body", "results"], "too_long"),
    ({"results": [{**RESULT, "browser": "firefox"}]}, ["body"], "value_error"),
    ({"results": [{**RESULT, "status": "SKIPPED"}]}, ["body", "results", 0, "status"], "enum"),
    (
        {"results": [{**RESULT, "browser": "edge"}]},
        ["body", "results", 0, "browser"],
        "literal_error",
    ),
    (
        {"results": [{**RESULT, "seconds": -1}]},
        ["body", "results", 0, "seconds"],
        "greater_than_equal",
    ),
    (
        {"results": [{**RESULT, "seconds": 86_401}]},
        ["body", "results", 0, "seconds"],
        "less_than_equal",
    ),
    (
        {"results": [{**RESULT, "seconds": "fast"}]},
        ["body", "results", 0, "seconds"],
        "float_parsing",
    ),
    ({"results": [{**RESULT, "seconds": [1]}]}, ["body", "results", 0, "seconds"], "float_type"),
    (
        {"results": [{**RESULT, "page_text": "p" * 100_001}]},
        ["body", "results", 0, "page_text"],
        "string_too_long",
    ),
    (
        {"results": [{**RESULT, "path": {**PATH, "steps": []}}]},
        ["body", "results", 0, "path", "steps"],
        "too_short",
    ),
    (
        {"results": [{**RESULT, "path": {**PATH, "heading": "  "}}]},
        ["body", "results", 0, "path"],
        "value_error",
    ),
    (
        {"results": [{**RESULT, "steps": [{**STEP_RESULT, "index": 2}]}]},
        ["body", "results", 0],
        "value_error",
    ),
    (
        {"results": [{**RESULT, "steps": [STEP_RESULT, {**STEP_RESULT, "index": 2}]}]},
        ["body", "results", 0],
        "value_error",
    ),
    (
        {"results": [{**RESULT, "steps": [{**STEP_RESULT, "status": "PASSED"}]}]},
        ["body", "results", 0, "steps", 0, "status"],
        "enum",
    ),
    (
        {"results": [{**RESULT, "steps": [{**STEP_RESULT, "index": 0}]}]},
        ["body", "results", 0, "steps", 0, "index"],
        "greater_than_equal",
    ),
    (
        {"results": [{**RESULT, "steps": [{**STEP_RESULT, "index": 13}]}]},
        ["body", "results", 0, "steps", 0, "index"],
        "less_than_equal",
    ),
    (
        {"results": [{**RESULT, "steps": [{**STEP_RESULT, "detail": "d" * 100_001}]}]},
        ["body", "results", 0, "steps", 0, "detail"],
        "string_too_long",
    ),
    *(
        (
            {"results": [{**RESULT, "steps": [{**STEP_RESULT, "screenshot": screenshot}]}]},
            ["body", "results", 0, "steps", 0],
            "value_error",
        )
        for screenshot in (
            "/TP-001/chrome/01.png",
            "TP-001\\chrome\\01.png",
            "TP-001/../../01.png",
            "C:/01.png",
            "",
            "./01.png",
            "TP-001//01.png",
            "TP-001/chrome/\x0101.png",
        )
    ),
    (
        {"results": [{**RESULT, "steps": [{**STEP_RESULT, "screenshot": "s" * 201}]}]},
        ["body", "results", 0, "steps", 0, "screenshot"],
        "string_too_long",
    ),
    (
        {"not_covered": [{"criterion": "AC-004", "reason": ""}]},
        ["body", "not_covered", 0, "reason"],
        "string_too_short",
    ),
    (
        {"not_covered": [{"criterion": "AC-004", "reason": "   "}]},
        ["body", "not_covered", 0],
        "value_error",
    ),
    (
        {"not_covered": [{"criterion": "AC-004", "reason": "r" * 301}]},
        ["body", "not_covered", 0, "reason"],
        "string_too_long",
    ),
    (
        {"not_covered": [{"criterion": "XYZ", "reason": "r"}]},
        ["body", "not_covered", 0, "criterion"],
        "string_pattern_mismatch",
    ),
    ({"not_covered": [{"criterion": "AC-004", "reason": "r"}] * 2}, ["body"], "value_error"),
    ({"not_covered": None}, ["body", "not_covered"], "list_type"),
    ({"note": "x"}, ["body", "note"], "extra_forbidden"),
)


def plan_body(**changes: object) -> dict:
    body: dict[str, object] = {
        "locale": "it-IT",
        "application": dict(APPLICATION),
        "snapshot": copy.deepcopy(SNAPSHOT),
        "criteria": None,
        "earlier": None,
    }
    body.update(changes)
    return body


def result(
    path: Mapping[str, object],
    browser: str,
    status: str,
    *,
    done: int | None = None,
    detail: str | None = None,
) -> dict:
    finished = len(path["steps"]) if done is None else done
    steps = []
    for index in range(1, finished + 1):
        last = index == finished and status in ("FAILED", "BLOCKED")
        steps.append(
            {
                "index": index,
                "status": status if last else "DONE",
                "detail": detail if last else None,
                "url": PAGE,
                "title": TITLE,
                "screenshot": f"{path['code']}/{browser}/{index:02d}.png",
            }
        )
    return {
        "path": copy.deepcopy(dict(path)),
        "browser": browser,
        "status": status,
        "seconds": 1.5,
        "steps": steps,
        "page_text": TITLE,
    }


def run_body(plan: Mapping[str, object], results: list, **changes: object) -> dict:
    body: dict[str, object] = {
        "plan_id": plan["id"],
        "replan_ids": [],
        "started_at": "2026-09-29T10:00:00+02:00",
        "finished_at": "2026-09-29T10:02:30+02:00",
        "application": dict(APPLICATION),
        "browsers": [dict(CHROME), dict(FIREFOX)],
        "results": results,
        "not_covered": copy.deepcopy(plan["not_covered"]),
    }
    body.update(changes)
    return body


def earlier_of(path: Mapping[str, object], blocked_step: int = 2) -> dict:
    return {
        **copy.deepcopy(dict(path)),
        "blocked_step": blocked_step,
        "detail": "target not found: button: Calcola",
        "snapshot": copy.deepcopy(SNAPSHOT),
    }


def planned(client: _Client, base: str, **changes: object) -> dict:
    status, answer = client.call("POST", base + "/test-plans", plan_body(**changes))
    assert status == 201, answer
    assert answer["status"] == "PLANNED"
    return answer["plan"]


def recorded_run(client: _Client, base: str, body: Mapping[str, object]) -> dict:
    status, answer = client.call("POST", base + "/test-runs", body)
    assert status == 201, answer
    assert answer["status"] == "RECORDED"
    return answer["run"]


def statements_of(project: FakeProject) -> dict[str, str]:
    specification = project.current("requirements")["specification"]
    return {item["code"]: item["statement"] for item in specification["acceptance_criteria"]}


def digest_of(body: Mapping[str, object]) -> str:
    content = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("language", ["it", "en"])
def test_a_plan_writes_one_path_per_criterion_of_the_specification(language: str) -> None:
    with FakeStudio(language=language, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        statements = statements_of(project)

        status, answer = client.call(
            "POST", base + "/test-plans", plan_body(locale=LOCALE[language])
        )

        plan = answer["plan"]
        assert (status, answer["status"], list(plan)) == (201, "PLANNED", PLAN_KEYS)
        assert datetime.fromisoformat(plan["created_at"]).utcoffset() == timedelta(0)
        assert {key: plan[key] for key in PLAN_KEYS[2:] if key != "paths"} == {
            "locale": LOCALE[language],
            "reference": REFERENCE,
            "application": APPLICATION,
            "criteria": CRITERIA_CODES,
            "replan_of": [],
            "not_covered": [],
            "cost_microusd": 200_000,
        }
        assert plan["paths"] == [
            {
                "code": f"TP-{number:03d}",
                "heading": statement[:60].rstrip(),
                "criteria": [code],
                "steps": [
                    OPEN_STEP,
                    {
                        "action": "CHECK",
                        "target": None,
                        "value": None,
                        "expect": {
                            "kind": "TEXT_VISIBLE",
                            "target": None,
                            "text": " ".join(statement.split()[:3]),
                        },
                    },
                ],
            }
            for number, (code, statement) in enumerate(statements.items(), start=1)
        ]
        assert plan["paths"][0]["steps"][1]["expect"]["text"] == (
            "Con 30 euro" if language == "it" else "With 30 euros"
        )
        assert studio.spent_microusd == project.spent_microusd == COSTS["TEST_PLAN"] == 200_000
        _, usage = client.call("GET", base + "/model-usage")
        assert [
            (item["task"], item["purpose"], item["cost_microusd"]) for item in usage["items"]
        ] == [("requirements", "TEST_PLAN", 200_000)]
        assert project.test_plans() == [plan]
        assert client.call("GET", base + "/test-plans") == (200, {"items": [plan]})
        assert client.call("GET", f"{base}/test-plans/{plan['id']}") == (200, plan)
        assert studio.errors == []


def test_a_criterion_to_check_by_hand_is_not_covered() -> None:
    long_statement = "The   tip appears " + "x" * 41 + " and stays visible after the cut"
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        project.rewrite_criterion("AC-001", long_statement)
        project.rewrite_criterion("AC-004", "The total is compared by a MANUAL count at the till.")

        plan = planned(client, base, locale="en-US", criteria=["AC-004", "AC-001", "AC-004"])

        assert plan["criteria"] == ["AC-001", "AC-004"]
        assert plan["not_covered"] == [{"criterion": "AC-004", "reason": "Needs a manual check"}]
        (path,) = plan["paths"]
        assert (path["code"], path["criteria"]) == ("TP-001", ["AC-001"])
        assert path["heading"] == long_statement[:60].rstrip() == "The   tip appears " + "x" * 41
        assert len(long_statement[:60]) == 60
        assert path["steps"][1]["expect"]["text"] == "The tip appears"
        earlier = studio.seed_project(owner=EMAIL, name="Twins only", through="twins")
        with pytest.raises(ValueError):
            earlier.rewrite_criterion("AC-001", "Anything")
        with pytest.raises(ValueError):
            project.rewrite_criterion("AC-009", "Anything")
    with FakeStudio(language="it", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        project.rewrite_criterion("AC-002", "La mancia si controlla con una verifica manuale.")

        plan = planned(client, f"/projects/{project.id}")

        assert [(path["code"], path["criteria"]) for path in plan["paths"]] == [
            ("TP-001", ["AC-001"]),
            ("TP-002", ["AC-003"]),
            ("TP-003", ["AC-004"]),
        ]
        assert plan["not_covered"] == [
            {"criterion": "AC-002", "reason": "Richiede una verifica manuale"}
        ]
        assert plan["criteria"] == CRITERIA_CODES
        assert studio.errors == []


def test_unknown_criteria_are_refused_with_their_codes() -> None:
    unknown = {"detail": {"code": "ACCEPTANCE_CRITERION_UNKNOWN", "codes": ["AC-009", "XYZ"]}}
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        body = plan_body(criteria=["AC-001", "AC-009", "XYZ", "AC-009"])

        assert client.call("POST", base + "/test-plans", body) == (422, unknown)
        started = client.call("POST", base + "/test-plans", body, headers=PREFER)
        job = poll(client, base, started[1]["job_id"])

        assert (job["status"], job["response"]) == (
            "FAILED",
            {"status_code": 422, "body": unknown},
        )
        assert project.test_plans() == []
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_a_replan_holds_only_the_criteria_of_the_blocked_paths() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        first = planned(client, base)
        blocked = [first["paths"][1], first["paths"][3]]

        second = planned(
            client,
            base,
            criteria=["AC-002", "AC-004"],
            earlier=[earlier_of(path) for path in blocked],
        )
        untitled = planned(
            client,
            base,
            snapshot={**SNAPSHOT, "title": "  "},
            earlier=[earlier_of(first["paths"][0], blocked_step=1)],
        )

        assert (second["criteria"], second["replan_of"]) == (
            ["AC-002", "AC-004"],
            ["TP-002", "TP-004"],
        )
        assert [(path["code"], path["criteria"]) for path in second["paths"]] == [
            ("TP-005", ["AC-002"]),
            ("TP-006", ["AC-004"]),
        ]
        assert [path["code"] for path in untitled["paths"]] == ["TP-007"]
        assert [path["code"] for path in planned(client, base)["paths"]] == [
            "TP-001",
            "TP-002",
            "TP-003",
            "TP-004",
        ]
        title = {
            "action": "CHECK",
            "target": None,
            "value": None,
            "expect": {"kind": "TITLE_CONTAINS", "target": None, "text": "Calcolo"},
        }
        for path, earlier in zip(second["paths"], blocked, strict=True):
            assert path["steps"] == [*earlier["steps"], title]
        assert (untitled["criteria"], untitled["replan_of"]) == (["AC-001"], ["TP-001"])
        assert untitled["paths"][0]["steps"][2]["expect"]["text"] == "a"
        assert [plan["id"] for plan in project.test_plans()[1:]] == [
            untitled["id"],
            second["id"],
            first["id"],
        ]
        assert studio.spent_microusd == 800_000
        assert studio.errors == []


def test_the_refusals_of_a_plan_come_in_the_order_of_the_contract() -> None:
    body = plan_body()
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed(studio)
        expected = (
            ("twins", 409, "REQUIREMENTS_APPROVAL_REQUIRED"),
            ("requirements", 409, "DESIGN_APPROVAL_REQUIRED"),
            ("design", 503, "TEST_MODEL_NOT_CONFIGURED"),
        )
        for through, status, code in expected:
            project = studio.seed_project(owner=EMAIL, name=f"Fino a {through}", through=through)
            base = f"/projects/{project.id}"
            assert client.call("POST", base + "/test-plans", body) == (status, refused(code))
            unknown = plan_body(criteria=["AC-009"])
            assert client.call("POST", base + "/test-plans", unknown) == (status, refused(code))
            started = client.call("POST", base + "/test-plans", body, headers=PREFER)
            assert started[0] == 202
            job = poll(client, base, started[1]["job_id"])
            assert (job["status"], job["response"]) == (
                "FAILED",
                {"status_code": status, "body": refused(code)},
            )
            assert project.test_plans() == []
        other = stranger(studio)
        owner_paths = (
            ("GET", "/acceptance-tests", None),
            ("POST", "/test-plans", body),
            ("GET", "/test-plans", None),
            ("GET", f"/test-plans/{UNKNOWN_ID}", None),
            ("POST", "/test-runs", RUN),
            ("GET", "/test-runs", None),
            ("GET", f"/test-runs/{UNKNOWN_ID}", None),
            ("POST", f"/test-runs/{UNKNOWN_ID}/reviews", {}),
            ("GET", f"/test-runs/{UNKNOWN_ID}/reviews", None),
        )
        for method, path, payload in owner_paths:
            assert other.call(method, base + path, payload) == (
                404,
                refused("PROJECT_NOT_FOUND"),
            ), path
        assert client.call("GET", f"{base}/test-plans/{UNKNOWN_ID}") == (
            404,
            refused("TEST_PLAN_NOT_FOUND"),
        )
        for path, name in (("/test-plans/plan", "plan_id"), ("/test-runs/run", "run_id")):
            assert client.call("GET", base + path) == (422, invalid(["path", name], "uuid_parsing"))
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_a_plan_with_prefer_runs_as_a_request_job() -> None:
    body = plan_body(locale="en-US")
    with FakeStudio(language="en", job_polls=2) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"

        status, started = client.call("POST", base + "/test-plans", body, headers=PREFER)

        assert (status, client.headers["preference-applied"]) == (202, "respond-async")
        assert (started["kind"], started["operation"], started["status"]) == (
            "REQUEST",
            "TEST_PLAN",
            "RUNNING",
        )
        assert (
            client.call("POST", base + "/test-plans", body, headers=PREFER)[1]["job_id"]
            == (started["job_id"])
        )
        empty = plan_body(locale="en-US", snapshot={**SNAPSHOT, "hidden_text": ""})
        assert (
            client.call("POST", base + "/test-plans", empty, headers=PREFER)[1]["job_id"]
            == (started["job_id"])
        )
        assert studio._jobs[started["job_id"]].key == f"TEST_PLAN:{digest_of(empty)}"
        job_path = f"{base}/generation-jobs/{started['job_id']}"
        statuses = [client.call("GET", job_path)[1]["status"] for _ in range(3)]
        assert statuses == ["RUNNING", "RUNNING", "SUCCEEDED"]
        _, finished = client.call("GET", job_path)
        assert finished["response"] == {
            "status_code": 201,
            "body": {"status": "PLANNED", "plan": project.test_plans()[0]},
        }
        for code in CRITERIA_CODES:
            later = client.call(
                "POST", base + "/test-plans", plan_body(criteria=[code]), headers=PREFER
            )
            assert later[0] == 202
        busy = client.call("POST", base + "/test-plans", plan_body(locale="it"), headers=PREFER)
        assert busy == (429, refused("TOO_MANY_GENERATIONS"))
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        studio.fail_job("TEST_PLAN", code="TIMEOUT")
        failed = poll(
            client,
            base,
            client.call("POST", base + "/test-plans", body, headers=PREFER)[1]["job_id"],
        )
        assert (failed["status"], failed["response"]) == (
            "FAILED",
            {
                "status_code": 503,
                "body": {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}},
            },
        )
        studio.lose_job("TEST_PLAN")
        lost = client.call("POST", base + "/test-plans", body, headers=PREFER)[1]
        assert client.call("GET", f"{base}/generation-jobs/{lost['job_id']}") == (
            404,
            refused("GENERATION_JOB_NOT_FOUND"),
        )
        assert project.test_plans() == []
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_a_plan_that_passes_the_ceiling_is_not_stored() -> None:
    exceeded = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
    with FakeStudio(budget_usd=0.3, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        planned(client, base)

        assert client.call("POST", base + "/test-plans", plan_body()) == (402, exceeded)
        assert len(project.test_plans()) == 1
        assert studio.spent_microusd == 200_000
        assert studio.errors == []


def test_a_run_computes_the_status_of_every_criterion() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.rewrite_criterion("AC-004", "Il totale si controlla con una verifica manuale.")
        plan = planned(client, base)
        one, two, three = plan["paths"]
        results = [
            result(one, "chrome", "PASSED"),
            result(one, "firefox", "PASSED"),
            result(two, "chrome", "BLOCKED", done=1, detail="target not found: text: Mancia"),
            result(two, "firefox", "FAILED", detail="TEXT_VISIBLE: L'elenco delle"),
            result(three, "chrome", "BLOCKED", done=1, detail="target not found: text: Con"),
            result(three, "firefox", "PASSED"),
        ]

        run = recorded_run(client, base, run_body(plan, results))

        assert list(run) == TEST_RUN_KEYS
        assert run["criteria"] == [
            {"code": "AC-001", "status": "PASSED", "paths": ["TP-001"]},
            {"code": "AC-002", "status": "FAILED", "paths": ["TP-002"]},
            {"code": "AC-003", "status": "BLOCKED", "paths": ["TP-003"]},
            {"code": "AC-004", "status": "NOT_COVERED", "paths": []},
        ]
        assert run["summary"] == {
            "passed": 1,
            "failed": 1,
            "blocked": 1,
            "not_covered": 1,
            "not_run": 0,
        }
        assert {key: run[key] for key in TEST_RUN_KEYS if key not in ("id", "recorded_at")} == {
            "started_at": "2026-09-29T08:00:00+00:00",
            "finished_at": "2026-09-29T08:02:30+00:00",
            "application": APPLICATION,
            "browsers": [CHROME, FIREFOX],
            "reference": REFERENCE,
            "summary": run["summary"],
            "criteria": run["criteria"],
            "not_covered": plan["not_covered"],
            "results": results,
            "critiques": [],
            "reviewed_at": None,
            "cost_microusd": 200_000,
        }
        assert datetime.fromisoformat(run["recorded_at"]).utcoffset() == timedelta(0)
        partial = recorded_run(
            client,
            base,
            run_body(
                plan,
                [result(one, "chrome", "PASSED"), result(two, "chrome", "NOT_RUN", done=0)],
                browsers=[CHROME],
                not_covered=[*plan["not_covered"], {"criterion": "AC-001", "reason": "Non serve"}],
            ),
        )
        empty = recorded_run(client, base, run_body(plan, [], browsers=[CHROME], not_covered=[]))
        assert [(item["code"], item["status"]) for item in partial["criteria"]] == [
            ("AC-001", "PASSED"),
            ("AC-002", "NOT_RUN"),
            ("AC-003", "NOT_RUN"),
            ("AC-004", "NOT_COVERED"),
        ]
        assert partial["summary"] == {
            "passed": 1,
            "failed": 0,
            "blocked": 0,
            "not_covered": 1,
            "not_run": 2,
        }
        assert empty["summary"] == {
            "passed": 0,
            "failed": 0,
            "blocked": 0,
            "not_covered": 0,
            "not_run": 4,
        }
        assert project.test_runs() == [empty, partial, run]
        assert client.call("GET", base + "/test-runs") == (200, {"items": [empty, partial, run]})
        assert client.call("GET", f"{base}/test-runs/{run['id']}") == (200, run)
        assert client.call("GET", f"{base}/test-runs/{run['id']}/reviews") == (200, {"items": []})
        assert studio.spent_microusd == 200_000
        assert studio.errors == []


def test_a_run_with_a_replan_counts_both_plans() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plan = planned(client, base)
        replan = planned(client, base, criteria=["AC-002"], earlier=[earlier_of(plan["paths"][1])])
        paths = [plan["paths"][0], replan["paths"][0], *plan["paths"][2:]]

        run = recorded_run(
            client,
            base,
            run_body(
                plan,
                [result(path, "chrome", "PASSED") for path in paths],
                browsers=[CHROME],
                replan_ids=[replan["id"]],
            ),
        )
        waiting = recorded_run(
            client,
            base,
            run_body(
                plan,
                [result(plan["paths"][0], "chrome", "PASSED")],
                browsers=[CHROME],
                replan_ids=[replan["id"]],
            ),
        )

        assert replan["paths"][0]["code"] == "TP-005"
        assert run["cost_microusd"] == 400_000
        assert run["reference"] == plan["reference"]
        assert run["criteria"] == [
            {"code": "AC-001", "status": "PASSED", "paths": ["TP-001"]},
            {"code": "AC-002", "status": "PASSED", "paths": ["TP-005"]},
            {"code": "AC-003", "status": "PASSED", "paths": ["TP-003"]},
            {"code": "AC-004", "status": "PASSED", "paths": ["TP-004"]},
        ]
        assert waiting["criteria"][1] == {
            "code": "AC-002",
            "status": "NOT_RUN",
            "paths": ["TP-002", "TP-005"],
        }
        assert studio.spent_microusd == 400_000
        assert studio.errors == []


def test_a_run_that_does_not_match_its_plans_is_refused() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plan = planned(client, base)
        elsewhere = studio.seed_project(owner=EMAIL, name="Altro progetto", through="design")
        foreign = planned(client, f"/projects/{elsewhere.id}")
        for body in (
            run_body({**plan, "id": UNKNOWN_ID}, []),
            run_body(plan, [], replan_ids=[UNKNOWN_ID]),
            run_body(foreign, []),
        ):
            assert client.call("POST", base + "/test-runs", body) == (
                404,
                refused("TEST_PLAN_NOT_FOUND"),
            )
        path = plan["paths"][0]
        longer = {**path, "steps": [*path["steps"], CLICK_STEP]}
        cases = (
            (
                [
                    result(path, "firefox", "PASSED"),
                    result({**path, "code": "TP-009"}, "chrome", "PASSED"),
                ],
                [],
                "result 1 names the path TP-009, which is not in the plan or in its replans",
            ),
            (
                [result(longer, "chrome", "PASSED")],
                [],
                "result 0 holds more steps than its path",
            ),
            (
                [],
                [{"criterion": "AC-009", "reason": "Non serve"}],
                "the not covered criteria AC-009 are not in the plans",
            ),
        )
        for results, not_covered, message in cases:
            body = run_body(plan, results, not_covered=not_covered)
            assert client.call("POST", base + "/test-runs", body) == (
                422,
                {
                    "detail": {
                        "code": "invalid_request",
                        "errors": [{"loc": ["body"], "type": "value_error", "msg": message}],
                    }
                },
            )
        assert project.test_runs() == []
        assert studio.spent_microusd == 400_000
        assert studio.errors == []


def test_a_recorded_run_keeps_the_planned_path_and_the_texts_the_studio_stores() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plan = planned(
            client, base, application={"kind": "URL", "address": "  http://127.0.0.1:5173/ "}
        )
        path = plan["paths"][0]
        spaced = {**path, "heading": f"  {path['heading']}  "}
        sent = result(spaced, "chrome", "FAILED", detail="  TEXT_VISIBLE:\n Con 30   euro ")
        sent["seconds"] = 3
        sent["page_text"] = "p " * 1_000
        sent["steps"][0]["title"] = "t" * 400

        run = recorded_run(
            client,
            base,
            run_body(
                plan,
                [sent],
                application={"kind": "URL", "address": " http://127.0.0.1:5173/ "},
                browsers=[{"name": "chrome", "version": " 151.0 \t 1 "}],
                not_covered=[{"criterion": "AC-004", "reason": "  Non   serve "}],
            ),
        )

        (stored,) = run["results"]
        assert plan["application"] == {"kind": "URL", "address": "http://127.0.0.1:5173/"}
        assert run["application"] == plan["application"]
        assert run["browsers"] == [{"name": "chrome", "version": "151.0 1"}]
        assert run["not_covered"] == [{"criterion": "AC-004", "reason": "Non serve"}]
        assert stored["path"] == path
        assert (stored["seconds"], json.dumps(stored["seconds"])) == (3.0, "3.0")
        assert stored["steps"][1]["detail"] == "TEXT_VISIBLE: Con 30 euro"
        assert stored["steps"][0]["title"] == "t" * 299 + "…"
        assert len(stored["page_text"]) == 1500
        assert stored["page_text"].endswith("p…")
        assert run["criteria"][3] == {"code": "AC-004", "status": "NOT_COVERED", "paths": []}
        assert studio.errors == []


TEST_CASES = (
    *(
        ("POST", "/test-plans", {**plan_body(), **item[0]}, item[1], item[2])
        for item in PLAN_REFUSALS
    ),
    ("POST", "/test-plans", None, ["body"], "missing"),
    *(("POST", "/test-runs", {**RUN, **item[0]}, item[1], item[2]) for item in RUN_REFUSALS),
    (
        "POST",
        "/test-runs",
        {key: value for key, value in RUN.items() if key != "not_covered"},
        ["body", "not_covered"],
        "missing",
    ),
    ("POST", "/test-runs", None, ["body"], "missing"),
    *(
        ("POST", f"/test-runs/{UNKNOWN_ID}/reviews", item[0], item[1], item[2])
        for item in REVIEW_REFUSALS
    ),
    ("GET", "/test-plans/plan", None, ["path", "plan_id"], "uuid_parsing"),
    ("GET", "/test-runs/run", None, ["path", "run_id"], "uuid_parsing"),
    ("GET", "/test-runs/run/reviews", None, ["path", "run_id"], "uuid_parsing"),
)
ORDERED_PLAN_REFUSALS = (
    (
        plan_body(snapshot={**SNAPSHOT, "text": None, "hidden_text": 5, "elements": None}),
        [
            {"loc": ["body", "snapshot", "text"], "type": "string_type"},
            {"loc": ["body", "snapshot", "hidden_text"], "type": "string_type"},
            {"loc": ["body", "snapshot", "elements"], "type": "list_type"},
        ],
    ),
    (
        plan_body(
            earlier=[
                {
                    **EARLIER,
                    "snapshot": {
                        **SNAPSHOT,
                        "title": 5,
                        "hidden_text": None,
                        "elements": [ELEMENT] * 151,
                    },
                }
            ]
        ),
        [
            {"loc": ["body", "earlier", 0, "snapshot", "title"], "type": "string_type"},
            {"loc": ["body", "earlier", 0, "snapshot", "hidden_text"], "type": "string_type"},
            {"loc": ["body", "earlier", 0, "snapshot", "elements"], "type": "too_long"},
        ],
    ),
)


def test_invalid_test_requests_answer_422() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        for method, path, body, location, kind in TEST_CASES:
            assert client.call(method, base + path, body) == (422, invalid(location, kind)), (
                path,
                body,
            )
        for body, errors in ORDERED_PLAN_REFUSALS:
            assert client.call("POST", base + "/test-plans", body) == (
                422,
                {"detail": "invalid_request", "errors": errors},
            )
        assert (project.test_plans(), project.test_runs(), project.test_reviews()) == ([], [], [])
        assert project.plan_requests() == []
        assert studio.spent_microusd == 0
        assert studio.errors == []


def test_invalid_test_requests_answer_like_the_real_application(real_client: TestClient) -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        for method, path, body, _, _ in TEST_CASES:
            real = real_client.request(method, PREFIX + base + path, json=body)
            assert real.status_code == 422, (path, body, real.text)
            assert client.call(method, base + path, body) == (422, real.json()), (path, body)
        for body, _ in ORDERED_PLAN_REFUSALS:
            real = real_client.post(PREFIX + base + "/test-plans", json=body)
            assert real.status_code == 422, real.text
            assert client.call("POST", base + "/test-plans", body) == (422, real.json())
        assert studio.errors == []


def test_the_job_keys_are_the_keys_of_the_real_application() -> None:
    with FakeStudio(job_polls=5) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plan = planned(client, base)
        run = recorded_run(client, base, run_body(plan, [], browsers=[CHROME]))
        criteria = ["ac-002", "AC-004", "ac-002"]
        earlier = earlier_of(plan["paths"][1])
        bodies = [
            plan_body(criteria=criteria, earlier=[earlier]),
            plan_body(
                snapshot={**SNAPSHOT, "hidden_text": ""},
                criteria=criteria,
                earlier=[{**earlier, "snapshot": {**SNAPSHOT, "hidden_text": ""}}],
            ),
            plan_body(
                snapshot={**SNAPSHOT, "hidden_text": "Totale per persona"},
                criteria=criteria,
                earlier=[{**earlier, "snapshot": {**SNAPSHOT, "hidden_text": "Conto diviso"}}],
            ),
        ]
        review = {"locale": "en-US", "again": True}

        planning = [
            client.call("POST", base + "/test-plans", body, headers=PREFER)[1] for body in bodies
        ]
        reviewing = client.call(
            "POST", f"{base}/test-runs/{run['id']}/reviews", review, headers=PREFER
        )[1]

        for body, started in zip(bodies, planning, strict=True):
            assert studio._jobs[started["job_id"]].key == request_key(
                GenerationOperation.TEST_PLAN,
                {"project_id": project.id},
                acceptance_api.TestPlanRequest.model_validate(body),
            )
        assert planning[0]["job_id"] == planning[1]["job_id"] != planning[2]["job_id"]
        assert studio._jobs[reviewing["job_id"]].key == request_key(
            GenerationOperation.TEST_REVIEW,
            {"project_id": project.id, "run_id": run["id"]},
            acceptance_api.TestReviewRequest.model_validate(review),
        )
        assert {"TEST_PLAN", "TEST_REVIEW"} <= {item.value for item in GenerationOperation}
        assert studio.errors == []


def test_the_fields_of_a_plan_request_are_those_of_the_real_request() -> None:
    assert SNAPSHOT_FIELDS == ("url", "title", "text", "hidden_text", "elements")
    for fields, model in (
        (PLAN_FIELDS, acceptance_api.TestPlanRequest),
        (SNAPSHOT_FIELDS, acceptance_api.SnapshotRequest),
        (ELEMENT_FIELDS, acceptance_api.ElementRequest),
        (EARLIER_FIELDS, acceptance_api.EarlierRequest),
    ):
        assert fields == tuple(model.model_fields), model.__name__


def test_the_hidden_text_is_kept_in_the_request_and_changes_nothing_in_the_plan() -> None:
    hidden = "Totale per persona:   11,50 euro"
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plain = planned(client, base)
        blocked = earlier_of(plain["paths"][1])
        changes = [
            {"snapshot": {**SNAPSHOT, "hidden_text": hidden}},
            {"snapshot": {**SNAPSHOT, "hidden_text": "h" * 100_000}},
            {
                "criteria": ["ac-002"],
                "earlier": [{**blocked, "snapshot": {**SNAPSHOT, "hidden_text": hidden}}],
            },
            {"earlier": [{**blocked, "snapshot": None}]},
            {"earlier": [{key: value for key, value in blocked.items() if key != "snapshot"}]},
        ]

        plans = [planned(client, base, **item) for item in changes]

        requests = project.plan_requests()[::-1]
        assert requests == [
            acceptance_api.TestPlanRequest.model_validate(body).model_dump(mode="json")
            for body in (plan_body(), *(plan_body(**item) for item in changes))
        ]
        assert [item["snapshot"]["hidden_text"] for item in requests] == [
            "",
            hidden,
            "h" * 100_000,
            "",
            "",
            "",
        ]
        assert requests[3]["criteria"] == ["AC-002"]
        assert requests[3]["earlier"][0]["snapshot"] == {**SNAPSHOT, "hidden_text": hidden}
        assert [item["earlier"][0]["snapshot"] for item in requests[4:]] == [None, None]
        for plan in plans[:2]:
            assert {key: plan[key] for key in PLAN_KEYS[2:]} == {
                key: plain[key] for key in PLAN_KEYS[2:]
            }
        assert [(plan["replan_of"], plan["criteria"]) for plan in plans[2:]] == [
            (["TP-002"], ["AC-002"])
        ] * 3
        assert [plan["paths"][0]["code"] for plan in plans[2:]] == ["TP-005", "TP-006", "TP-007"]
        steps = [plan["paths"][0]["steps"] for plan in plans[2:]]
        assert steps == [steps[0]] * 3
        assert [plan["id"] for plan in project.test_plans()[::-1]] == [
            plain["id"],
            *(plan["id"] for plan in plans),
        ]
        assert studio.spent_microusd == 6 * COSTS["TEST_PLAN"]
        assert studio.errors == []


@pytest.mark.parametrize("language", ["it", "en"])
def test_a_review_of_a_run_follows_the_rules_of_the_fake(language: str) -> None:
    numbers = {
        "it": "2 criteri superati, 1 falliti, 1 bloccati, 0 non coperti, 0 non eseguiti",
        "en": "2 criteria passed, 1 failed, 1 blocked, 0 not covered, 0 not run",
    }
    with FakeStudio(language=language, twins=3, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plan = planned(client, base, locale=LOCALE[language])
        one, two, three, four = plan["paths"]
        results = [
            result(one, "chrome", "PASSED"),
            result(two, "chrome", "PASSED"),
            result(three, "chrome", "BLOCKED", done=1, detail="target not found: text: Con"),
            result(four, "chrome", "FAILED", detail="TEXT_VISIBLE: Il risultato"),
        ]
        run = recorded_run(client, base, run_body(plan, results, browsers=[CHROME]))

        status, answer = client.call(
            "POST", f"{base}/test-runs/{run['id']}/reviews", {"locale": LOCALE[language]}
        )

        review = answer["review"]
        assert (status, answer["status"], list(review)) == (201, "REVIEWED", TEST_REVIEW_KEYS)
        assert (review["run_id"], review["locale"], review["cost_microusd"]) == (
            run["id"],
            LOCALE[language],
            3 * COSTS["TEST_REVIEW"],
        )
        twins = project.current("twins")["snapshot"]["twin_versions"]
        critiques = review["critiques"]
        assert [(item["twin_id"], item["twin_name"]) for item in critiques] == [
            (twin["twin_id"], twin["profile"]["name"]) for twin in twins
        ]
        assert [item["verdict"] for item in critiques] == ["CONCERN", "FINE", "FINE"]
        about = {"criterion": "AC-003", "requirement": "REQ-003", "screen": "SCR-001"}
        assert [
            [(finding["severity"], finding["about"]) for finding in item["findings"]]
            for item in critiques
        ] == [[("MEDIUM", about)], [("LOW", about)], []]
        for item in critiques:
            assert FIRST_GOALS[language] in item["summary"]
            assert numbers[language] in item["summary"]
            for finding in item["findings"]:
                assert finding["text"] and finding["action"]
                assert "AC-003" in finding["text"]
        _, usage = client.call("GET", base + "/model-usage")
        assert [
            (item["task"], item["purpose"], item["cost_microusd"])
            for item in reversed(usage["items"])
        ] == [
            ("requirements", "TEST_PLAN", 200_000),
            *[("user-twin-evaluation", "TEST_REVIEW", 150_000)] * 3,
        ]
        reviewed = {
            **run,
            "critiques": critiques,
            "reviewed_at": review["reviewed_at"],
            "cost_microusd": 650_000,
        }
        assert client.call("GET", f"{base}/test-runs/{run['id']}") == (200, reviewed)
        assert client.call("GET", base + "/test-runs") == (200, {"items": [reviewed]})
        assert client.call("GET", f"{base}/test-runs/{run['id']}/reviews") == (
            200,
            {"items": [review]},
        )
        assert client.call("GET", base + "/acceptance-tests")[1]["latest_run"] == reviewed
        assert project.test_runs() == [reviewed]
        assert project.test_reviews() == [review]
        assert studio.spent_microusd == 650_000
        assert studio.errors == []


def test_a_review_of_a_run_that_passed_cites_its_first_criterion() -> None:
    with FakeStudio(language="en", twins=1, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        plan = planned(client, base, locale="en-US")
        results = [result(path, "chrome", "PASSED") for path in plan["paths"]]
        run = recorded_run(client, base, run_body(plan, results, browsers=[CHROME]))
        empty = recorded_run(client, base, run_body(plan, [], browsers=[CHROME]))
        project.rewrite_criterion("AC-001", "Checked with a manual count.")
        nothing = planned(client, base, criteria=["AC-001"])
        without = recorded_run(client, base, run_body(nothing, [], browsers=[CHROME]))

        reviews = [
            client.call("POST", f"{base}/test-runs/{item['id']}/reviews", {"locale": "en-US"})[1]
            for item in (run, empty, without)
        ]

        (passed,), (not_run,), (covered,) = (item["review"]["critiques"] for item in reviews)
        assert passed["verdict"] == "CONCERN"
        assert [finding["about"] for finding in passed["findings"]] == [
            {"criterion": "AC-001", "requirement": "REQ-001", "screen": "SCR-001"}
        ]
        assert "4 criteria passed, 0 failed" in passed["summary"]
        assert [finding["about"]["criterion"] for finding in not_run["findings"]] == ["AC-001"]
        assert [finding["about"]["criterion"] for finding in covered["findings"]] == ["AC-001"]
        assert (nothing["paths"], nothing["criteria"]) == ([], ["AC-001"])
        assert without["criteria"] == [{"code": "AC-001", "status": "NOT_COVERED", "paths": []}]
        assert studio.errors == []


def test_a_second_review_of_a_run_repeats_the_content_with_a_new_id() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plan = planned(client, base)
        run = recorded_run(client, base, run_body(plan, [], browsers=[CHROME]))
        path = f"{base}/test-runs/{run['id']}/reviews"

        _, first = client.call("POST", path, {"locale": "it-IT"})
        repeated = client.call("POST", path, {})
        status, second = client.call("POST", path, {"locale": "it-IT", "again": True})

        assert repeated == (409, refused("TEST_REVIEW_EXISTS"))
        older, newer = first["review"], second["review"]
        assert status == 201
        assert newer["id"] != older["id"]
        assert datetime.fromisoformat(newer["reviewed_at"]) > datetime.fromisoformat(
            older["reviewed_at"]
        )
        same = ("run_id", "locale", "critiques", "cost_microusd")
        assert {key: newer[key] for key in same} == {key: older[key] for key in same}
        assert client.call("GET", path) == (200, {"items": [newer, older]})
        _, current = client.call("GET", f"{base}/test-runs/{run['id']}")
        assert (current["reviewed_at"], current["cost_microusd"]) == (
            newer["reviewed_at"],
            200_000 + 300_000,
        )
        for body, location, kind in REVIEW_REFUSALS:
            assert client.call("POST", path, body) == (422, invalid(location, kind)), body
        _, french = client.call("POST", path, {"locale": "fr-FR", "again": "yes"})
        _, default = client.call("POST", path, {"again": 1})
        assert (french["review"]["locale"], default["review"]["locale"]) == ("fr-FR", "it-IT")
        assert len(project.test_reviews()) == 4
        assert studio.spent_microusd == 200_000 + 4 * 300_000
        assert studio.errors == []


def test_the_refusals_of_a_test_review_come_in_the_order_of_the_contract() -> None:
    body = {"locale": "it-IT"}
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        run = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        path = f"{base}/test-runs/{run['id']}/reviews"
        unknown = f"{base}/test-runs/{UNKNOWN_ID}/reviews"

        assert client.call("POST", unknown, body) == (404, refused("TEST_RUN_NOT_FOUND"))
        assert client.call("GET", unknown) == (404, refused("TEST_RUN_NOT_FOUND"))
        assert client.call("GET", f"{base}/test-runs/{UNKNOWN_ID}") == (
            404,
            refused("TEST_RUN_NOT_FOUND"),
        )
        assert client.call("POST", path, body)[0] == 201
        assert client.call("POST", path, body) == (409, refused("TEST_REVIEW_EXISTS"))
        _, team = client.call("GET", base + "/team-proposals/current")
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        edit = client.call(
            "PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited}
        )
        assert edit[0] == 201
        assert project.approved("design") and not project.approved("twins")
        assert client.call("POST", path, body) == (409, refused("TEST_REVIEW_EXISTS"))
        assert client.call("POST", path, {**body, "again": True}) == (
            409,
            refused("USER_MODELING_APPROVAL_REQUIRED"),
        )
        assert studio.spent_microusd == 200_000 + 300_000
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        run = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        path = f"{base}/test-runs/{run['id']}/reviews"

        assert client.call("POST", base + "/design/regenerations")[0] == 201
        assert not project.approved("design")
        assert client.call("POST", path, body) == (409, refused("DESIGN_APPROVAL_REQUIRED"))
        _, change = client.call(
            "POST", base + "/requirements/change-requests", {"request": "Aggiungi il bis"}
        )
        decided = client.call(
            "POST",
            f"{base}/requirements/revisions/{change['diff']['id']}/decision",
            {"decision": "APPROVE"},
        )
        assert decided[0] == 200
        assert not project.approved("requirements")
        assert client.call("POST", path, body) == (
            409,
            refused("REQUIREMENTS_APPROVAL_REQUIRED"),
        )
        assert project.test_reviews() == []
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        run = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        path = f"{base}/test-runs/{run['id']}/reviews"
        studio.hosted = False

        assert client.call("POST", path, body) == (503, refused("TEST_MODEL_NOT_CONFIGURED"))
        started = client.call("POST", path, body, headers=PREFER)
        job = poll(client, base, started[1]["job_id"])
        assert (job["status"], job["response"]) == (
            "FAILED",
            {"status_code": 503, "body": refused("TEST_MODEL_NOT_CONFIGURED")},
        )
        assert client.call("GET", base + "/acceptance-tests")[1]["plan_available"] is False
        assert project.test_reviews() == []
        assert studio.spent_microusd == 200_000
        assert studio.errors == []


def test_a_review_of_a_run_that_passes_the_ceiling_is_not_stored() -> None:
    exceeded = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
    with FakeStudio(budget_usd=0.4, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        run = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        path = f"{base}/test-runs/{run['id']}/reviews"

        assert client.call("POST", path, {"locale": "it-IT"}) == (402, exceeded)
        assert studio.spent_microusd == 200_000 + 150_000
        assert project.test_reviews() == []
        _, current = client.call("GET", f"{base}/test-runs/{run['id']}")
        assert (current["critiques"], current["reviewed_at"], current["cost_microusd"]) == (
            [],
            None,
            200_000,
        )
        _, usage = client.call("GET", base + "/model-usage")
        assert usage["totals"]["cost_microusd"] == studio.spent_microusd
        assert studio.errors == []


def test_a_review_of_a_run_with_prefer_runs_as_a_request_job() -> None:
    body = {"locale": "en-US", "again": False}
    with FakeStudio(language="en", job_polls=2) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        run = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        path = f"{base}/test-runs/{run['id']}/reviews"

        status, started = client.call("POST", path, body, headers=PREFER)

        assert (status, started["kind"], started["operation"], started["status"]) == (
            202,
            "REQUEST",
            "TEST_REVIEW",
            "RUNNING",
        )
        assert studio._jobs[started["job_id"]].key == (
            f"TEST_REVIEW:run_id={run['id']}:{digest_of(body)}"
        )
        assert client.call("POST", path, body, headers=PREFER)[1]["job_id"] == started["job_id"]
        again = client.call("POST", path, {**body, "again": True}, headers=PREFER)
        assert again[1]["job_id"] != started["job_id"]
        job_path = f"{base}/generation-jobs/{started['job_id']}"
        statuses = [client.call("GET", job_path)[1]["status"] for _ in range(3)]
        assert statuses == ["RUNNING", "RUNNING", "SUCCEEDED"]
        _, finished = client.call("GET", job_path)
        assert finished["response"] == {
            "status_code": 201,
            "body": {"status": "REVIEWED", "review": project.test_reviews()[0]},
        }
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        run = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        path = f"{base}/test-runs/{run['id']}/reviews"
        studio.fail_job("TEST_REVIEW", code="TIMEOUT")

        failed = poll(client, base, client.call("POST", path, body, headers=PREFER)[1]["job_id"])

        assert (failed["status"], failed["response"]) == (
            "FAILED",
            {
                "status_code": 503,
                "body": {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}},
            },
        )
        studio.lose_job("TEST_REVIEW")
        lost = client.call("POST", path, body, headers=PREFER)[1]
        assert client.call("GET", f"{base}/generation-jobs/{lost['job_id']}") == (
            404,
            refused("GENERATION_JOB_NOT_FOUND"),
        )
        assert project.test_reviews() == []
        assert studio.spent_microusd == 200_000
        assert studio.errors == []


@pytest.mark.parametrize("hosted", [True, False])
def test_the_overview_gives_the_reference_the_counts_and_the_latest_run(hosted: bool) -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        _, alignment = client.call("GET", base + "/alignment")
        status, before = client.call("GET", base + "/acceptance-tests")
        plan = planned(client, base)
        recorded_run(client, base, run_body(plan, [], browsers=[CHROME]))
        latest = recorded_run(client, base, run_body(plan, [], browsers=[FIREFOX]))
        studio.hosted = hosted

        _, after = client.call("GET", base + "/acceptance-tests")

        assert (status, list(before)) == (200, OVERVIEW_KEYS)
        assert before == {
            "project_id": project.id,
            "reference": alignment["reference"],
            "plan_available": True,
            "plans": 0,
            "runs": 0,
            "latest_run": None,
            "latest_run_stale": False,
            "latest_review": None,
        }
        assert after == {
            **before,
            "plan_available": hosted,
            "plans": 1,
            "runs": 2,
            "latest_run": latest,
        }
        earlier = studio.seed_project(owner=EMAIL, name="Fino ai requisiti", through="requirements")
        _, other = client.call("GET", f"/projects/{earlier.id}/acceptance-tests")
        assert other["reference"]["design"] is None
        assert other["reference"]["requirements"] is not None
        assert (other["plans"], other["runs"], other["latest_run"]) == (0, 0, None)
        assert studio.errors == []


def test_the_lists_give_the_twenty_newest_items() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        plans = [planned(client, base, criteria=[CRITERIA_CODES[index % 4]]) for index in range(21)]
        runs = [
            recorded_run(client, base, run_body(plans[0], [], browsers=[CHROME])) for _ in range(21)
        ]

        _, listed_plans = client.call("GET", base + "/test-plans")
        _, listed_runs = client.call("GET", base + "/test-runs")

        assert listed_plans["items"] == list(reversed(plans))[:20]
        assert listed_runs["items"] == list(reversed(runs))[:20]
        assert len(project.test_plans()) == len(project.test_runs()) == 21
        _, overview = client.call("GET", base + "/acceptance-tests")
        assert (overview["plans"], overview["runs"], overview["latest_run"]) == (21, 21, runs[-1])
        assert studio.errors == []


@pytest.mark.parametrize("language", ["it", "en"])
def test_the_tests_of_the_fake_pass_the_real_domain_rules(language: str) -> None:
    with FakeStudio(language=language, twins=2, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.rewrite_criterion("AC-004", "Il conto si controlla con una verifica manuale.")
        plan = planned(client, base, locale=LOCALE[language])
        replan = planned(client, base, criteria=["AC-002"], earlier=[earlier_of(plan["paths"][1])])
        paths = [plan["paths"][0], replan["paths"][0], plan["paths"][2]]
        results = [
            result(paths[0], "chrome", "PASSED"),
            result(paths[1], "firefox", "FAILED", detail="TITLE_CONTAINS: Calcolo"),
            result(paths[2], "chrome", "BLOCKED", done=1, detail="target not found: text: Con"),
        ]
        run = recorded_run(client, base, run_body(plan, results, replan_ids=[replan["id"]]))
        _, answer = client.call(
            "POST", f"{base}/test-runs/{run['id']}/reviews", {"locale": LOCALE[language]}
        )
        _, reviewed = client.call("GET", f"{base}/test-runs/{run['id']}")

        for item in (plan, replan):
            for path in item["paths"]:
                assert acceptance_domain.path_from_snapshot(path).to_snapshot() == path
            for entry in item["not_covered"]:
                assert acceptance_domain.not_covered_from_snapshot(entry).to_snapshot() == entry
            assert (
                acceptance_domain.application_from_snapshot(item["application"]).to_snapshot()
                == item["application"]
            )
        for entry in reviewed["results"]:
            parsed = acceptance_domain.path_result_from_snapshot(entry)
            assert parsed.to_snapshot() == entry
        outcomes = tuple(
            acceptance_domain.outcome_from_snapshot(item) for item in reviewed["criteria"]
        )
        assert tuple(item.to_snapshot() for item in outcomes) == tuple(reviewed["criteria"])
        assert acceptance_domain.run_summary(outcomes).to_snapshot() == reviewed["summary"]
        assert reviewed["summary"] == {
            "passed": 1,
            "failed": 1,
            "blocked": 1,
            "not_covered": 1,
            "not_run": 0,
        }
        for browser in reviewed["browsers"]:
            assert acceptance_domain.browser_from_snapshot(browser).to_snapshot() == browser
        assert reviewed["critiques"] == answer["review"]["critiques"]
        for critique in reviewed["critiques"]:
            assert acceptance_domain.critique_from_snapshot(critique).to_snapshot() == critique
        assert studio.errors == []


TASK_KEYS = [
    "code",
    "text",
    "about",
    "origin",
    "from_commit",
    "created_at",
    "status",
    "closed_at",
    "note",
]
CREATED_KEYS = ["status", "created", "tasks", "alignment"]
NO_ABOUT = {"requirements": [], "screens": [], "criteria": []}
OWNER_ORIGIN = {
    "kind": "OWNER",
    "commit": None,
    "test_run_id": None,
    "twin_id": None,
    "twin_name": None,
    "finding": None,
}
UNKNOWN_TWIN = "00000000-0000-4000-8000-000000000777"
OWNER_ITEM = {"text": "Scrivere il testo di aiuto.", "source": {"kind": "OWNER"}}
RUN_SOURCE = {
    "kind": "TEST_RUN",
    "test_run_id": UNKNOWN_ID,
    "twin_id": UNKNOWN_TWIN,
    "finding": 0,
}
CHANGE_SOURCE = {"kind": "CODE_CHANGE", "commit": "abc1234", "twin_id": UNKNOWN_TWIN, "finding": 0}
TASK_REQUESTS = (
    ("POST", "/code-tasks", None),
    ("POST", "/code-tasks", {}),
    ("POST", "/code-tasks", {"tasks": []}),
    ("POST", "/code-tasks", {"tasks": "x"}),
    ("POST", "/code-tasks", {"tasks": [1]}),
    ("POST", "/code-tasks", {"tasks": [OWNER_ITEM] * 11}),
    ("POST", "/code-tasks", {"tasks": [OWNER_ITEM], "extra": 1}),
    ("POST", "/code-tasks", {"tasks": [{"text": "x"}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": None, "source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "", "source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "t" * 301, "source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "  ", "source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "a\x01b", "source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": 5, "source": {"kind": "OWNER"}}]}),
    ("POST", "/code-tasks", {"tasks": [{**OWNER_ITEM, "about": {}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "x", "source": "OWNER"}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "x", "source": None}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "x", "source": {}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "x", "source": {"kind": "NOBODY"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "x", "source": {"kind": 3}}]}),
    ("POST", "/code-tasks", {"tasks": [{"text": "x", "source": {"kind": "OWNER", "x": 1}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {"kind": "TEST_RUN"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**RUN_SOURCE, "test_run_id": "x"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**RUN_SOURCE, "twin_id": 5}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**RUN_SOURCE, "finding": -1}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**RUN_SOURCE, "finding": 1.5}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**RUN_SOURCE, "finding": "a"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**RUN_SOURCE, "finding": None}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**RUN_SOURCE, "commit": "abc1234"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**CHANGE_SOURCE, "commit": "abc"}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {**CHANGE_SOURCE, "commit": "z" * 40}}]}),
    ("POST", "/code-tasks", {"tasks": [{"source": {"kind": "CODE_CHANGE", "commit": "abc1234"}}]}),
    ("GET", "/code-tasks?status=done", None),
    ("GET", "/code-tasks?status=OPEN", None),
    ("POST", "/code-tasks/TSK-001/status", None),
    ("POST", "/code-tasks/TSK-001/status", {}),
    ("POST", "/code-tasks/TSK-001/status", {"status": "done"}),
    ("POST", "/code-tasks/TSK-001/status", {"status": "CLOSED"}),
    ("POST", "/code-tasks/TSK-001/status", {"status": "DONE", "note": "n" * 301}),
    ("POST", "/code-tasks/TSK-001/status", {"status": "DONE", "note": "a\x01b"}),
    ("POST", "/code-tasks/TSK-001/status", {"status": "DONE", "note": 5}),
    ("POST", "/code-tasks/TSK-001/status", {"status": "DONE", "reason": "x"}),
)


def twins_of(project: FakeProject) -> list[dict[str, object]]:
    return project.current("twins")["snapshot"]["twin_versions"]


def reviewed(
    client: _Client, base: str, commit: str, message: str = "Add the split of the bill", **changes
) -> dict:
    record(client, base, commit, message, **changes)
    status, answer = client.call("POST", f"{base}/code-changes/{commit}/reviews", {})
    assert status == 201, answer
    return answer["run"]


def reviewed_test_run(client: _Client, base: str) -> dict:
    plan = planned(client, base)
    first = plan["paths"][0]
    failed = [result(first, "chrome", "FAILED", detail="TEXT_VISIBLE: Con 30 euro")]
    run = recorded_run(client, base, run_body(plan, failed, browsers=[CHROME]))
    status, answer = client.call("POST", f"{base}/test-runs/{run['id']}/reviews", {})
    assert status == 201, answer
    return client.call("GET", f"{base}/test-runs/{run['id']}")[1]


def change_source(commit: str, twin_id: str, finding: int = 0) -> dict:
    return {"kind": "CODE_CHANGE", "commit": commit, "twin_id": twin_id, "finding": finding}


def run_source(run_id: str, twin_id: str, finding: int = 0) -> dict:
    return {"kind": "TEST_RUN", "test_run_id": run_id, "twin_id": twin_id, "finding": finding}


def owner_item(text: str) -> dict:
    return {"text": text, "source": {"kind": "OWNER"}}


def new_tasks(client: _Client, base: str, *items: Mapping[str, object]) -> dict:
    status, answer = client.call("POST", base + "/code-tasks", {"tasks": list(items)})
    assert status == 201, answer
    return answer


def codes(answer: Mapping[str, object]) -> tuple[int, list[str]]:
    return answer["created"], [task["code"] for task in answer["tasks"]]


def approved_requirements_change(client: _Client, base: str, request: str) -> None:
    _, change = client.call("POST", base + "/requirements/change-requests", {"request": request})
    decided = client.call(
        "POST",
        f"{base}/requirements/revisions/{change['diff']['id']}/decision",
        {"decision": "APPROVE"},
    )
    assert decided[0] == 200
    assert client.call("POST", base + "/requirements/gate/submit")[0] == 200
    assert (
        client.call("POST", base + "/requirements/gate/decision", {"action": "APPROVE"})[0] == 200
    )


def test_tasks_are_listed_open_by_default_and_every_task_on_request() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        created = new_tasks(client, base, owner_item("Uno."), owner_item("Due."))
        client.call("POST", f"{base}/code-tasks/TSK-002/status", {"status": "DROPPED"})

        opened = client.call("GET", base + "/code-tasks")
        explicit = client.call("GET", base + "/code-tasks?status=open")
        every = client.call("GET", base + "/code-tasks?status=all")

        assert opened == explicit == (200, {"items": [created["tasks"][0]]})
        assert every == (200, {"items": project.tasks()})
        assert [task["status"] for task in every[1]["items"]] == ["OPEN", "DROPPED"]
        assert client.call("GET", base + "/code-tasks?status=done") == (
            422,
            invalid(["query", "status"], "literal_error"),
        )
        assert stranger(studio).call("GET", base + "/code-tasks") == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert studio.errors == []


def test_a_finding_of_a_commit_becomes_a_task_with_its_origin() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("finding")
        run = reviewed(client, base, commit)
        first, second = twins_of(project)

        status, answer = client.call(
            "POST",
            base + "/code-tasks",
            {
                "tasks": [
                    {"source": change_source(commit[:9].upper(), first["twin_id"], 0)},
                    {
                        "text": "  Ingrandire   le cifre. ",
                        "source": change_source(commit, first["twin_id"], 1),
                    },
                    {"text": None, "source": change_source(commit, second["twin_id"], 0)},
                ]
            },
        )

        finding = run["critiques"][0]["findings"][0]
        tasks = answer["tasks"]
        moment = tasks[0]["created_at"]
        assert (status, list(answer), answer["status"], answer["created"]) == (
            201,
            CREATED_KEYS,
            "CREATED",
            3,
        )
        assert [list(task) for task in tasks] == [TASK_KEYS] * 3
        assert tasks[0] == {
            "code": "TSK-001",
            "text": finding["action"],
            "about": {"requirements": ["REQ-003"], "screens": [], "criteria": []},
            "origin": {
                "kind": "CODE_CHANGE",
                "commit": commit,
                "test_run_id": None,
                "twin_id": first["twin_id"],
                "twin_name": first["profile"]["name"],
                "finding": finding["text"],
            },
            "from_commit": commit,
            "created_at": moment,
            "status": "OPEN",
            "closed_at": None,
            "note": None,
        }
        assert (tasks[1]["code"], tasks[1]["text"], tasks[1]["about"]) == (
            "TSK-002",
            "Ingrandire le cifre.",
            {"requirements": [], "screens": ["SCR-001"], "criteria": []},
        )
        assert tasks[2]["origin"]["twin_name"] == second["profile"]["name"]
        assert tasks[2]["about"] == {
            "requirements": ["REQ-003"],
            "screens": ["SCR-001"],
            "criteria": [],
        }
        assert {task["created_at"] for task in tasks} == {moment}
        assert answer["alignment"] == client.call("GET", base + "/alignment")[1]
        assert answer["alignment"]["tasks"] == tasks == project.tasks()
        assert studio.spent_microusd == 650_000
        assert studio.errors == []


def test_a_finding_of_a_test_run_becomes_a_task_about_its_criterion() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        run = reviewed_test_run(client, base)
        twin = twins_of(project)[0]

        answer = new_tasks(client, base, {"source": run_source(run["id"], twin["twin_id"], 0)})

        finding = run["critiques"][0]["findings"][0]
        assert finding["text"] == (
            "Criterion AC-001 does not assure me that the application does what I need."
        )
        assert answer["tasks"] == [
            {
                "code": "TSK-001",
                "text": "Fix the application where the path of criterion AC-001 stops.",
                "about": {
                    "requirements": [finding["about"]["requirement"]],
                    "screens": ["SCR-001"],
                    "criteria": ["AC-001"],
                },
                "origin": {
                    "kind": "TEST_RUN",
                    "commit": None,
                    "test_run_id": run["id"],
                    "twin_id": twin["twin_id"],
                    "twin_name": twin["profile"]["name"],
                    "finding": finding["text"],
                },
                "from_commit": None,
                "created_at": answer["tasks"][0]["created_at"],
                "status": "OPEN",
                "closed_at": None,
                "note": None,
            }
        ]
        assert studio.errors == []


def test_the_owner_writes_tasks_and_a_long_finding_is_cut_to_a_task() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("long")
        reviewed(client, base, commit)
        twin = twins_of(project)[0]["twin_id"]
        findings = project.change_runs[0]["critiques"][0]["findings"]
        findings[0]["action"] = "  Parola " * 60
        findings[1]["action"] = None

        owner, long, plain = new_tasks(
            client,
            base,
            owner_item("  Scrivere   il testo di aiuto. "),
            {"source": change_source(commit, twin, 0)},
            {"source": change_source(commit, twin, 1)},
        )["tasks"]

        assert {key: owner[key] for key in ("code", "text", "about", "origin", "from_commit")} == {
            "code": "TSK-001",
            "text": "Scrivere il testo di aiuto.",
            "about": NO_ABOUT,
            "origin": OWNER_ORIGIN,
            "from_commit": None,
        }
        assert long["text"] == " ".join(("Parola " * 60).split())[:299].rstrip() + "…"
        assert len(long["text"]) <= 300
        assert plain["text"] == findings[1]["text"]
        assert studio.errors == []


def test_a_source_that_is_already_an_open_task_answers_that_task() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("again")
        reviewed(client, base, commit)
        source = change_source(commit, twins_of(project)[0]["twin_id"], 0)

        once = new_tasks(client, base, {"source": source}, {"source": source})
        twice = new_tasks(
            client,
            base,
            {"text": "Un altro testo.", "source": source},
            owner_item("Uno."),
            owner_item("Uno."),
        )
        client.call("POST", f"{base}/code-tasks/TSK-001/status", {"status": "DONE"})
        after = new_tasks(client, base, {"source": source})

        assert codes(once) == (1, ["TSK-001", "TSK-001"])
        assert codes(twice) == (2, ["TSK-001", "TSK-002", "TSK-003"])
        assert twice["tasks"][0] == once["tasks"][0]
        assert codes(after) == (1, ["TSK-004"])
        assert [task["status"] for task in project.tasks()] == ["DONE", "OPEN", "OPEN", "OPEN"]
        assert studio.errors == []


def test_a_review_asked_again_with_other_findings_gives_new_tasks() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("bis")
        record(client, base, commit, "Aggiunge il bis", diff="+// REQ-005 aggiunge il bis\n")
        path = f"{base}/code-changes/{commit}/reviews"
        twin = twins_of(project)[0]["twin_id"]
        _, before = client.call("POST", path, {})
        first = new_tasks(
            client,
            base,
            {"source": change_source(commit, twin, 0)},
            {"source": change_source(commit, twin, 1)},
        )
        approved_requirements_change(client, base, "Aggiungi la richiesta del bis")

        _, after = client.call("POST", path, {"again": True})
        second = new_tasks(
            client,
            base,
            {"source": change_source(commit, twin, 0)},
            {"source": change_source(commit, twin, 1)},
        )
        repeated = new_tasks(client, base, {"source": change_source(commit, twin, 0)})

        older, newer = (answer["run"]["critiques"][0]["findings"] for answer in (before, after))
        assert ("REQ-001" in older[0]["text"], "REQ-005" in newer[0]["text"]) == (True, True)
        assert older[1]["text"] == newer[1]["text"]
        assert codes(first) == (2, ["TSK-001", "TSK-002"])
        assert codes(second) == (1, ["TSK-003", "TSK-002"])
        assert second["tasks"][0]["origin"]["finding"] == newer[0]["text"]
        assert second["tasks"][0]["about"]["requirements"] == ["REQ-005"]
        assert codes(repeated) == (0, ["TSK-003"])
        assert repeated["tasks"] == [second["tasks"][0]]
        assert [task["status"] for task in project.tasks()] == ["OPEN"] * 3
        assert studio.errors == []


def test_the_refusals_of_new_tasks_come_in_the_order_of_the_contract() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit, silent = commit_of("sources"), commit_of("silent")
        reviewed(client, base, commit)
        record(client, base, silent)
        for similar in ("abcdef1" + "0" * 33, "abcdef1" + "1" * 33):
            record(client, base, similar)
        run = reviewed_test_run(client, base)
        quiet = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        first, second = (twin["twin_id"] for twin in twins_of(project))
        owner = owner_item("Uno.")
        good_change = {"source": change_source(commit, first, 0)}
        good_run = {"source": run_source(run["id"], first, 0)}
        no_run = {"source": run_source(UNKNOWN_ID, first, 0)}
        no_change = {"source": change_source("0" * 40, first, 0)}
        ambiguous = {"source": change_source("abcdef1", first, 0)}
        cases = (
            ([owner, ambiguous, no_change, no_run], 404, refused("TEST_RUN_NOT_FOUND")),
            ([owner, ambiguous, no_change], 404, refused("CODE_CHANGE_NOT_FOUND")),
            ([ambiguous, good_change], 409, refused("CODE_CHANGE_AMBIGUOUS")),
            (
                [good_change, {"source": change_source(silent, first, 0)}],
                422,
                refused("TASK_SOURCE_INVALID", index=1),
            ),
            (
                [good_run, owner, {"source": run_source(quiet["id"], first, 0)}],
                422,
                refused("TASK_SOURCE_INVALID", index=2),
            ),
            (
                [good_change, {"source": change_source(commit, UNKNOWN_TWIN, 0)}],
                422,
                refused("TASK_SOURCE_INVALID", index=1),
            ),
            (
                [{"source": change_source(commit, second, 1)}],
                422,
                refused("TASK_SOURCE_INVALID", index=0),
            ),
            (
                [{"source": run_source(run["id"], first, 1)}],
                422,
                refused("TASK_SOURCE_INVALID", index=0),
            ),
        )

        for items, status, body in cases:
            assert client.call("POST", base + "/code-tasks", {"tasks": items}) == (
                status,
                body,
            ), items

        assert project.tasks() == []
        assert stranger(studio).call("POST", base + "/code-tasks", {"tasks": [owner]}) == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert studio.errors == []


def test_the_status_of_a_task_changes_with_its_note() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        new_tasks(client, base, owner_item("Uno."), owner_item("Due."))

        def change(code: str, body: object) -> tuple[int, object]:
            return client.call("POST", f"{base}/code-tasks/{code}/status", body)

        status, done = change("tsk-001", {"status": "DONE", "note": "  Fatto   bene. "})
        _, again = change("TSK-001", {"status": "DONE", "note": None})
        _, dropped = change("TSK-001", {"status": "DROPPED", "note": "Non serve."})
        _, reopened = change("TSK-001", {"status": "OPEN"})
        _, blank = change("TSK-002", {"status": "DROPPED", "note": "   "})

        task = done["task"]
        assert (status, list(done), done["status"]) == (
            200,
            ["status", "task", "alignment"],
            "UPDATED",
        )
        assert (task["status"], task["note"]) == ("DONE", "Fatto bene.")
        assert task["closed_at"] is not None
        assert [item["code"] for item in done["alignment"]["tasks"]] == ["TSK-002"]
        assert (again["task"]["closed_at"], again["task"]["note"]) == (task["closed_at"], None)
        assert datetime.fromisoformat(dropped["task"]["closed_at"]) > datetime.fromisoformat(
            task["closed_at"]
        )
        assert (dropped["task"]["status"], dropped["task"]["note"]) == ("DROPPED", "Non serve.")
        assert {key: reopened["task"][key] for key in ("status", "closed_at", "note")} == {
            "status": "OPEN",
            "closed_at": None,
            "note": None,
        }
        assert (blank["task"]["status"], blank["task"]["note"]) == ("DROPPED", None)
        for code in ("TSK-003", "TSK-0001", "TSK-000", "TASK-001", "TSK-1"):
            assert change(code, {"status": "DONE"}) == (404, refused("CODE_TASK_NOT_FOUND")), code
        assert stranger(studio).call(
            "POST", f"{base}/code-tasks/TSK-001/status", {"status": "DONE"}
        ) == (404, refused("PROJECT_NOT_FOUND"))
        assert change("TSK-001", {"status": "done"}) == (422, invalid(["body", "status"], "enum"))
        assert project.tasks()[0] == reopened["task"]
        assert studio.errors == []


def test_a_decision_turns_findings_of_the_twins_into_tasks() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("decision")
        run = reviewed(client, base, commit, "Fix the drift of the form")
        first, second = twins_of(project)
        path = f"{base}/code-changes/{commit}/decision"

        wrong = client.call(
            "POST",
            path,
            {
                "kind": "CODE_TASKS",
                "tasks": ["Uno."],
                "findings": [
                    {"twin_id": first["twin_id"], "finding": 0},
                    {"twin_id": second["twin_id"], "finding": 3},
                ],
            },
        )
        untouched = (project.tasks(), project.changes()[0]["decision"])
        status, decided = client.call(
            "POST",
            path,
            {
                "kind": "CODE_TASKS",
                "tasks": ["Uno."],
                "findings": [
                    {"twin_id": first["twin_id"], "finding": 1},
                    {"twin_id": second["twin_id"], "finding": 0},
                ],
            },
        )
        _, only = client.call(
            "POST",
            path,
            {
                "kind": "CODE_TASKS",
                "findings": [
                    {"twin_id": first["twin_id"], "finding": 1},
                    {"twin_id": first["twin_id"], "finding": 0},
                ],
            },
        )

        assert wrong == (422, refused("TASK_SOURCE_INVALID", index=1))
        assert untouched == ([], None)
        tasks = decided["alignment"]["tasks"]
        moment = decided["change"]["decision"]["decided_at"]
        assert status == 200
        assert tasks[0] == verdict_task(1, "Uno.", commit, moment) | {
            "about": {"requirements": ["REQ-003"], "screens": ["SCR-001"], "criteria": []}
        }
        assert tasks[1]["origin"]["finding"] == run["critiques"][0]["findings"][1]["text"]
        assert tasks[1]["text"] == run["critiques"][0]["findings"][1]["action"]
        assert tasks[2]["origin"]["twin_name"] == second["profile"]["name"]
        assert {task["created_at"] for task in tasks} == {moment}
        assert [task["code"] for task in only["alignment"]["tasks"]] == [
            "TSK-001",
            "TSK-002",
            "TSK-003",
            "TSK-004",
        ]
        assert (
            only["alignment"]["tasks"][3]["origin"]["finding"]
            == (run["critiques"][0]["findings"][0]["text"])
        )
        assert studio.errors == []


def test_an_aligned_decision_closes_the_tasks_of_the_tests_and_of_the_owner_made_before() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        run = reviewed_test_run(client, base)
        twin = twins_of(project)[0]["twin_id"]
        new_tasks(client, base, owner_item("Prima."), {"source": run_source(run["id"], twin, 0)})
        client.call("POST", f"{base}/code-tasks/TSK-001/status", {"status": "OPEN", "note": "Ora."})
        older, newer = commit_of("older"), commit_of("newer")
        record(client, base, older)
        new_tasks(client, base, owner_item("Dopo."))
        record(client, base, newer)

        def align(commit: str) -> dict:
            status, answer = client.call(
                "POST", f"{base}/code-changes/{commit}/decision", {"kind": "ALIGNED"}
            )
            assert status == 200, answer
            return answer

        first = align(older)
        closed = project.tasks()
        align(newer)

        moment = first["change"]["decision"]["decided_at"]
        assert [(task["code"], task["status"], task["closed_at"]) for task in closed] == [
            ("TSK-001", "DONE", moment),
            ("TSK-002", "DONE", moment),
            ("TSK-003", "OPEN", None),
        ]
        assert closed[0]["note"] is None
        assert [task["code"] for task in first["alignment"]["tasks"]] == ["TSK-003"]
        assert [task["status"] for task in project.tasks()] == ["DONE"] * 3
        assert studio.errors == []


def test_invalid_task_requests_answer_like_the_real_application(real_client: TestClient) -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        for method, path, body in TASK_REQUESTS:
            real = real_client.request(method, PREFIX + base + path, json=body)
            assert real.status_code == 422, (path, body, real.text)
            assert client.call(method, base + path, body) == (422, real.json()), (path, body)
        assert project.tasks() == []
        assert studio.errors == []


def findings_of(run: Mapping[str, object], position: int) -> list[str]:
    return [item["text"] for item in run["critiques"][position]["findings"]]


def test_a_review_turns_stale_when_a_newer_version_is_approved() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        aligned, pending, fresh = (commit_of(name) for name in ("aligned", "pending", "fresh"))
        reviewed(client, base, aligned)
        client.call("POST", f"{base}/code-changes/{aligned}/decision", {"kind": "ALIGNED"})
        reviewed(client, base, pending)
        record(client, base, fresh)
        _, before = client.call("GET", base + "/alignment")

        project.seed_version("design")
        _, after = client.call("GET", base + "/alignment")
        _, listed = client.call("GET", base + "/code-changes")
        _, one = client.call("GET", f"{base}/code-changes/{pending}")
        repeated = client.call("POST", base + "/code-changes", change_body(pending))
        _, again = client.call("POST", f"{base}/code-changes/{pending}/reviews", {"again": True})
        _, renewed = client.call("GET", base + "/alignment")
        project.seed_version("requirements")
        _, requirements = client.call("GET", base + "/alignment")
        client.call("POST", base + "/design/regenerations")
        _, unapproved = client.call("GET", base + "/alignment")

        reference = {
            "requirements_version_number": 1,
            "design_version_number": 2,
            "alternative_code": "DES-002",
        }
        assert (before["stale_reviews"], after["stale_reviews"]) == (0, 1)
        assert after["reference"]["design"]["version_number"] == 3
        assert {
            item["commit"]: None if item["review"] is None else item["review"]["stale"]
            for item in listed["items"]
        } == {fresh: None, pending: True, aligned: True}
        assert list(one["review"]) == [
            "run_id",
            "reviewed_at",
            "verdict",
            "summary",
            "reference",
            "stale",
        ]
        assert (one["review"]["reference"], one["review"]["stale"]) == (reference, True)
        assert repeated[0] == 200
        assert repeated[1]["change"]["review"]["stale"] is True
        assert again["run"]["reference"] == {**reference, "design_version_number": 3}
        assert renewed["stale_reviews"] == 0
        assert renewed["latest_change"]["commit"] == fresh
        assert requirements["stale_reviews"] == 1
        assert unapproved["reference"]["design"] is None
        assert unapproved["stale_reviews"] == 0
        assert studio.errors == []


def test_a_review_asked_again_remembers_the_findings_of_the_same_commit() -> None:
    with FakeStudio(twins=3, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        older, newer = commit_of("older"), commit_of("newer")
        first = reviewed(client, base, older)
        second = reviewed(client, base, newer)
        _, again = client.call("POST", f"{base}/code-changes/{newer}/reviews", {"again": True})

        contexts = project.earlier_findings()

        twins = [twin["twin_id"] for twin in twins_of(project)]
        assert [(item["kind"], item["run_id"], item["commit"]) for item in contexts] == [
            ("CODE_CHANGE", again["run"]["id"], newer),
            ("CODE_CHANGE", second["id"], newer),
            ("CODE_CHANGE", first["id"], older),
        ]
        assert contexts[2]["twins"] == [
            {"twin_id": twin, "earlier_source": None, "earlier_findings": []} for twin in twins
        ]
        assert contexts[1]["twins"] == [
            {
                "twin_id": twins[0],
                "earlier_source": "PREVIOUS_COMMIT",
                "earlier_findings": findings_of(first, 0),
            },
            {
                "twin_id": twins[1],
                "earlier_source": "PREVIOUS_COMMIT",
                "earlier_findings": findings_of(first, 1),
            },
            {"twin_id": twins[2], "earlier_source": None, "earlier_findings": []},
        ]
        assert contexts[0]["twins"][0] == {
            "twin_id": twins[0],
            "earlier_source": "THIS_COMMIT",
            "earlier_findings": findings_of(second, 0),
        }
        assert studio.errors == []


def test_the_overview_says_when_the_latest_run_is_stale_and_gives_the_latest_review() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        older = reviewed_test_run(client, base)
        latest = recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        _, fresh = client.call("GET", base + "/acceptance-tests")

        project.seed_version("design")
        _, stale = client.call("GET", base + "/acceptance-tests")

        assert fresh["latest_run"]["id"] == latest["id"]
        assert (fresh["latest_run_stale"], stale["latest_run_stale"]) == (False, True)
        assert (
            fresh["latest_review"]
            == stale["latest_review"]
            == {
                "run_id": older["id"],
                "finished_at": older["finished_at"],
                "reviewed_at": older["reviewed_at"],
                "critiques": older["critiques"],
            }
        )
        assert studio.errors == []


def test_a_review_of_a_run_remembers_the_findings_of_the_previous_reviewed_run() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        first = reviewed_test_run(client, base)
        recorded_run(client, base, run_body(planned(client, base), [], browsers=[CHROME]))
        second = reviewed_test_run(client, base)

        contexts = project.earlier_findings()

        twins = [twin["twin_id"] for twin in twins_of(project)]
        assert [(item["kind"], item["run_id"]) for item in contexts] == [
            ("TEST_RUN", second["id"]),
            ("TEST_RUN", first["id"]),
        ]
        assert contexts[0]["review_id"] == project.test_reviews()[0]["id"]
        assert contexts[0]["twins"] == [
            {"twin_id": twin, "earlier_findings": findings_of(first, position)}
            for position, twin in enumerate(twins)
        ]
        assert contexts[1]["twins"] == [{"twin_id": twin, "earlier_findings": []} for twin in twins]
        assert studio.errors == []


ENTRY_KEYS = [
    "twin_id",
    "twin_name",
    "profile_version_number",
    "development_version_number",
    "label",
    "observations",
    "retired",
]
UPDATE_KEYS = [
    "id",
    "twin_id",
    "twin_name",
    "created_at",
    "locale",
    "status",
    "base",
    "comment",
    "observations",
    "material",
    "decision",
    "cost_microusd",
]
LEARNED_TEXTS = {
    "it": (
        "Un rilievo sulla verifica dei criteri.",
        "Un rilievo sul commit {commit}.",
        "Dalle ultime critiche ho imparato 2 cose sul mio gruppo.",
    ),
    "en": (
        "A finding on the acceptance tests.",
        "A finding on the commit {commit}.",
        "From the latest critiques I learned 2 things about my group.",
    ),
}
NOTHING_NEW = "The latest critiques teach me nothing new."
TWIN = "00000000-0000-4000-8000-000000000555"
UPDATE = "00000000-0000-4000-8000-000000000556"
DECISION = f"/twin-updates/{UPDATE}/decision"
OBSERVATIONS = f"/user-twins/{TWIN}/observations"
RETIREMENT = f"/user-twins/{TWIN}/observations/OBS-001/retire"
LEARNING_REQUESTS = (
    ("POST", f"/user-twins/{TWIN}/updates", None),
    ("POST", f"/user-twins/{TWIN}/updates", {"locale": "x"}),
    ("POST", f"/user-twins/{TWIN}/updates", {"locale": "french"}),
    ("POST", f"/user-twins/{TWIN}/updates", {"locale": "it-IT", "again": True}),
    ("POST", "/user-twins/not-a-uuid/updates", {}),
    ("POST", DECISION, None),
    ("POST", DECISION, {}),
    ("POST", DECISION, {"decision": "approve", "kept": [{"index": 0}]}),
    ("POST", DECISION, {"decision": "APPROVE"}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": []}),
    ("POST", DECISION, {"decision": "REJECT", "kept": [{"index": 0}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": 0}, {"index": 0}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": -1}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": 1.5}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": "a"}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"statement": "x"}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": 0, "statement": ""}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": 0, "statement": " "}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": 0, "statement": "s" * 401}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": "x", "statement": ""}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": 0, "extra": 1}]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [1]}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": "all"}),
    ("POST", DECISION, {"decision": "APPROVE", "kept": [{"index": item} for item in range(7)]}),
    ("POST", DECISION, {"decision": "REJECT", "reason": "r" * 301}),
    ("POST", DECISION, {"decision": "REJECT", "reason": "a\x01"}),
    ("POST", DECISION, {"decision": "REJECT", "why": "x"}),
    ("POST", "/twin-updates/not-a-uuid/decision", {"decision": "REJECT"}),
    ("GET", "/twin-updates/not-a-uuid", None),
    ("POST", OBSERVATIONS, None),
    ("POST", OBSERVATIONS, {}),
    ("POST", OBSERVATIONS, {"statement": ""}),
    ("POST", OBSERVATIONS, {"statement": "  "}),
    ("POST", OBSERVATIONS, {"statement": "s" * 401}),
    ("POST", OBSERVATIONS, {"statement": 7}),
    ("POST", OBSERVATIONS, {"statement": "x", "about": {"requirement": "REQ-1"}}),
    ("POST", OBSERVATIONS, {"statement": "x", "about": {"screen": "scr-001"}}),
    ("POST", OBSERVATIONS, {"statement": "x", "about": "REQ-001"}),
    ("POST", OBSERVATIONS, {"statement": "x", "about": {"criterion": "AC-001"}}),
    ("POST", OBSERVATIONS, {"statement": "x", "source": "OWNER"}),
    ("POST", "/user-twins/not-a-uuid/observations", {"statement": "x"}),
    ("POST", RETIREMENT, None),
    ("POST", RETIREMENT, {"reason": "r" * 301}),
    ("POST", RETIREMENT, {"reason": 5}),
    ("POST", RETIREMENT, {"reason": "a\x01"}),
    ("POST", RETIREMENT, {"why": "x"}),
)


def update_path(base: str, twin_id: str) -> str:
    return f"{base}/user-twins/{twin_id}/updates"


def proposed(client: _Client, base: str, twin_id: str, locale: str = "it-IT") -> dict:
    status, answer = client.call("POST", update_path(base, twin_id), {"locale": locale})
    assert (status, answer["status"]) == (201, "PROPOSED"), answer
    return answer["update"]


def decided_update(client: _Client, base: str, update_id: str, body: object) -> dict:
    status, answer = client.call("POST", f"{base}/twin-updates/{update_id}/decision", body)
    assert status == 200, answer
    return answer


def learning_of(client: _Client, base: str) -> dict:
    status, answer = client.call("GET", base + "/twin-learning")
    assert status == 200, answer
    return answer


def test_the_learning_of_the_twins_follows_the_approved_twins() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        early = studio.seed_project(owner=EMAIL, name="Solo il team", through="team")
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        empty = learning_of(client, f"/projects/{early.id}")
        before = learning_of(client, base)
        reviewed(client, base, commit_of("material"))
        reviewed_test_run(client, base)
        after = learning_of(client, base)
        studio.hosted = False
        offline = learning_of(client, base)

        twins = twins_of(project)
        assert empty == {"project_id": early.id, "update_available": True, "twins": []}
        assert list(before) == ["project_id", "update_available", "twins"]
        assert before["twins"] == [
            {
                "twin_id": twin["twin_id"],
                "twin_name": twin["profile"]["name"],
                "profile_version_number": 1,
                "development_version_number": 0,
                "label": "1.0",
                "observations": [],
                "retired": [],
                "pending_update": None,
                "new_material": {"changes": 0, "tests": 0},
            }
            for twin in twins
        ]
        assert [twin["new_material"] for twin in after["twins"]] == [{"changes": 1, "tests": 1}] * 2
        assert offline["update_available"] is False
        assert project.twin_learning() == [
            {key: entry[key] for key in ENTRY_KEYS} for entry in before["twins"]
        ]
        assert stranger(studio).call("GET", base + "/twin-learning") == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert studio.errors == []


@pytest.mark.parametrize("language", ["it", "en"])
def test_a_proposal_learns_from_the_findings_of_the_new_material(language: str) -> None:
    tests_basis, commit_basis, comment = LEARNED_TEXTS[language]
    with FakeStudio(language=language, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        commit = commit_of("learn")
        change_run = reviewed(client, base, commit)
        test_run = reviewed_test_run(client, base)
        twin = twins_of(project)[0]
        spent = studio.spent_microusd

        status, answer = client.call(
            "POST", update_path(base, twin["twin_id"]), {"locale": LOCALE[language]}
        )

        update = answer["update"]
        name = twin["profile"]["name"]
        test_finding = test_run["critiques"][0]["findings"][0]
        change_finding = change_run["critiques"][0]["findings"][0]
        assert (status, answer["status"], list(update)) == (201, "PROPOSED", UPDATE_KEYS)
        assert update == {
            "id": update["id"],
            "twin_id": twin["twin_id"],
            "twin_name": name,
            "created_at": update["created_at"],
            "locale": LOCALE[language],
            "status": "PROPOSED",
            "base": {"profile_version_number": 1, "development_version_number": 0},
            "comment": comment,
            "observations": [
                {
                    "index": 0,
                    "statement": f"{name}: {test_finding['text']}",
                    "basis": tests_basis,
                    "about": {
                        "requirement": test_finding["about"]["requirement"],
                        "screen": "SCR-001",
                    },
                    "contradicts_profile": None,
                },
                {
                    "index": 1,
                    "statement": f"{name}: {change_finding['text']}",
                    "basis": commit_basis.format(commit=commit[:8]),
                    "about": {"requirement": "REQ-003", "screen": None},
                    "contradicts_profile": None,
                },
            ],
            "material": {"changes": 1, "tests": 1},
            "decision": None,
            "cost_microusd": 150_000,
        }
        assert studio.spent_microusd - spent == 150_000
        _, usage = client.call("GET", base + "/model-usage")
        assert {key: usage["items"][0][key] for key in ("task", "purpose", "cost_microusd")} == {
            "task": "user-twin-evaluation",
            "purpose": "TWIN_UPDATE",
            "cost_microusd": 150_000,
        }
        overview = learning_of(client, base)["twins"][0]
        assert overview["pending_update"] == update
        assert overview["new_material"] == {"changes": 0, "tests": 0}
        assert client.call("GET", f"{base}/twin-updates/{update['id']}") == (200, update)
        assert project.twin_updates() == [update]
        assert studio.errors == []


def test_a_proposal_without_findings_is_empty_and_needs_no_decision() -> None:
    with FakeStudio(language="en", twins=3, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        reviewed(client, base, commit_of("quiet"))
        third = twins_of(project)[2]["twin_id"]

        update = proposed(client, base, third, "en-US")

        assert {key: update[key] for key in ("status", "comment", "observations", "decision")} == {
            "status": "EMPTY",
            "comment": NOTHING_NEW,
            "observations": [],
            "decision": None,
        }
        assert update["material"] == {"changes": 1, "tests": 0}
        assert client.call(
            "POST", f"{base}/twin-updates/{update['id']}/decision", {"decision": "REJECT"}
        ) == (409, refused("TWIN_UPDATE_ALREADY_DECIDED"))
        assert learning_of(client, base)["twins"][2]["pending_update"] is None
        assert client.call("POST", update_path(base, third), {"locale": "en-US"}) == (
            409,
            refused("TWIN_UPDATE_NOTHING_NEW"),
        )
        assert studio.errors == []


def test_an_observation_already_learned_is_not_proposed_again() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        twin = twins_of(project)[0]["twin_id"]
        reviewed(client, base, commit_of("first"))
        first = proposed(client, base, twin, "en-US")
        decided_update(client, base, first["id"], {"decision": "APPROVE", "kept": [{"index": 0}]})
        reviewed(client, base, commit_of("second"))

        second = proposed(client, base, twin, "en-US")
        decided_update(client, base, second["id"], {"decision": "REJECT"})
        spaced = "  ".join(second["observations"][0]["statement"].upper().split())
        client.call("POST", f"{base}/user-twins/{twin}/observations", {"statement": spaced})
        reviewed(client, base, commit_of("third"))
        third = proposed(client, base, twin, "en-US")

        learned, screen = (item["statement"] for item in first["observations"])
        assert [item["statement"] for item in second["observations"]] == [screen]
        assert second["comment"] == "From the latest critiques I learned 1 things about my group."
        assert learned != screen
        assert (third["status"], third["comment"], third["observations"]) == (
            "EMPTY",
            NOTHING_NEW,
            [],
        )
        assert studio.errors == []


def test_the_refusals_of_a_proposal_come_in_the_order_of_the_contract() -> None:
    body = {"locale": "it-IT"}
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        early = studio.seed_project(owner=EMAIL, name="Solo i requisiti", through="requirements")
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        twin = twins_of(project)[0]["twin_id"]
        path = update_path(base, twin)
        other = update_path(f"/projects/{early.id}", twins_of(early)[0]["twin_id"])

        assert stranger(studio).call("POST", path, body) == (404, refused("PROJECT_NOT_FOUND"))
        assert client.call("POST", update_path(base, UNKNOWN_ID), body) == (
            404,
            refused("USER_TWIN_NOT_FOUND"),
        )
        assert client.call("POST", other, body) == (409, refused("DESIGN_APPROVAL_REQUIRED"))
        assert client.call("POST", path, body) == (409, refused("TWIN_UPDATE_NOTHING_NEW"))
        reviewed(client, base, commit_of("material"))
        pending = project.seed_update(0)
        assert client.call("POST", path, body) == (
            409,
            refused("TWIN_UPDATE_PENDING", update_id=pending["id"]),
        )
        _, team = client.call("GET", base + "/team-proposals/current")
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        client.call("PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited})
        assert client.call("POST", path, body) == (
            409,
            refused("USER_MODELING_APPROVAL_REQUIRED"),
        )
        assert studio.spent_microusd == 650_000
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.seed_change()
        _, change = client.call(
            "POST", base + "/requirements/change-requests", {"request": "Aggiungi il bis"}
        )
        client.call(
            "POST",
            f"{base}/requirements/revisions/{change['diff']['id']}/decision",
            {"decision": "APPROVE"},
        )
        assert client.call("POST", update_path(base, twins_of(project)[0]["twin_id"]), body) == (
            409,
            refused("REQUIREMENTS_APPROVAL_REQUIRED"),
        )
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.seed_change()
        path = update_path(base, twins_of(project)[0]["twin_id"])

        assert client.call("POST", path, body) == (
            503,
            refused("TWIN_UPDATE_MODEL_NOT_CONFIGURED"),
        )
        started = client.call("POST", path, body, headers=PREFER)
        job = poll(client, base, started[1]["job_id"])
        assert (job["status"], job["response"]) == (
            "FAILED",
            {"status_code": 503, "body": refused("TWIN_UPDATE_MODEL_NOT_CONFIGURED")},
        )
        assert (project.twin_updates(), studio.spent_microusd) == ([], 0)
        assert studio.errors == []


def test_a_proposal_with_prefer_runs_as_a_request_job() -> None:
    body = {"locale": "en-US"}
    with FakeStudio(language="en", twins=5, job_polls=2) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        project.seed_change()
        twins = [twin["twin_id"] for twin in twins_of(project)]

        status, started = client.call("POST", update_path(base, twins[0]), body, headers=PREFER)

        assert (status, started["kind"], started["operation"], started["status"]) == (
            202,
            "REQUEST",
            "TWIN_UPDATE",
            "RUNNING",
        )
        assert studio._jobs[started["job_id"]].key == (
            f"TWIN_UPDATE:twin_id={twins[0]}:{digest_of(body)}"
        )
        again = client.call("POST", update_path(base, twins[0]), body, headers=PREFER)
        assert again[1]["job_id"] == started["job_id"]
        for twin in twins[1:4]:
            assert client.call("POST", update_path(base, twin), body, headers=PREFER)[0] == 202
        assert client.call("POST", update_path(base, twins[4]), body, headers=PREFER) == (
            429,
            refused("TOO_MANY_GENERATIONS"),
        )
        job_path = f"{base}/generation-jobs/{started['job_id']}"
        statuses = [client.call("GET", job_path)[1]["status"] for _ in range(3)]
        assert statuses == ["RUNNING", "RUNNING", "SUCCEEDED"]
        _, finished = client.call("GET", job_path)
        assert finished["response"] == {
            "status_code": 201,
            "body": {"status": "PROPOSED", "update": project.twin_updates()[0]},
        }
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.seed_change()
        path = update_path(base, twins_of(project)[0]["twin_id"])
        studio.fail_job("TWIN_UPDATE", code="TIMEOUT")

        failed = poll(client, base, client.call("POST", path, body, headers=PREFER)[1]["job_id"])

        assert (failed["status"], failed["response"]) == (
            "FAILED",
            {
                "status_code": 503,
                "body": {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}},
            },
        )
        studio.lose_job("TWIN_UPDATE")
        lost = client.call("POST", path, body, headers=PREFER)[1]
        assert client.call("GET", f"{base}/generation-jobs/{lost['job_id']}") == (
            404,
            refused("GENERATION_JOB_NOT_FOUND"),
        )
        assert (project.twin_updates(), studio.spent_microusd) == ([], 0)
        assert studio.errors == []


def test_a_proposal_that_passes_the_ceiling_is_not_stored() -> None:
    exceeded = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}}
    with FakeStudio(budget_usd=0.1, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.seed_change()
        path = update_path(base, twins_of(project)[0]["twin_id"])

        assert client.call("POST", path, {"locale": "it-IT"}) == (402, exceeded)
        started = client.call("POST", path, {"locale": "it-IT"}, headers=PREFER)
        job = poll(client, base, started[1]["job_id"])

        assert (job["status"], job["response"]) == (
            "FAILED",
            {"status_code": 402, "body": exceeded},
        )
        assert (project.twin_updates(), studio.spent_microusd) == ([], 0)
        assert studio.errors == []


def test_an_approval_adds_the_kept_observations_with_their_edits() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        reviewed(client, base, commit_of("approve"))
        reviewed_test_run(client, base)
        twin = twins_of(project)[0]["twin_id"]
        update = proposed(client, base, twin)
        spent = studio.spent_microusd

        answer = decided_update(
            client,
            base,
            update["id"],
            {
                "decision": "APPROVE",
                "kept": [
                    {"index": 1, "statement": "  Chi paga   legge da lontano. "},
                    {"index": 0},
                ],
                "reason": "  Utile. ",
            },
        )

        decision = answer["update"]["decision"]
        moment = decision["decided_at"]
        entry = answer["twin"]
        first, second = update["observations"]
        assert (list(answer), answer["status"]) == (["status", "update", "twin"], "DECIDED")
        assert answer["update"] == {
            **update,
            "status": "APPROVED",
            "decision": {"decided_at": moment, "kept": [0, 1], "reason": "Utile."},
        }
        assert list(entry) == ENTRY_KEYS
        assert (entry["development_version_number"], entry["label"]) == (1, "1.1")
        assert entry["observations"] == [
            {
                "code": "OBS-001",
                "statement": first["statement"],
                "basis": first["basis"],
                "source": "TWIN_CRITIQUE",
                "about": first["about"],
                "contradicts_profile": None,
                "added_in_version": 1,
                "approved_at": moment,
                "update_id": update["id"],
            },
            {
                "code": "OBS-002",
                "statement": "Chi paga legge da lontano.",
                "basis": second["basis"],
                "source": "TWIN_CRITIQUE",
                "about": second["about"],
                "contradicts_profile": None,
                "added_in_version": 1,
                "approved_at": moment,
                "update_id": update["id"],
            },
        ]
        assert entry["retired"] == []
        assert project.twin_learning()[0] == entry
        assert learning_of(client, base)["twins"][0]["pending_update"] is None
        assert studio.spent_microusd == spent
        assert studio.errors == []


def test_a_rejection_learns_nothing_and_the_new_material_starts_again() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        reviewed(client, base, commit_of("reject"))
        twin = twins_of(project)[0]["twin_id"]
        update = proposed(client, base, twin)

        answer = decided_update(client, base, update["id"], {"decision": "REJECT", "kept": []})
        nothing = client.call("POST", update_path(base, twin), {"locale": "it-IT"})
        reviewed(client, base, commit_of("later"))
        later = proposed(client, base, twin)

        assert answer["update"]["status"] == "REJECTED"
        assert answer["update"]["decision"] == {
            "decided_at": answer["update"]["decision"]["decided_at"],
            "kept": [],
            "reason": None,
        }
        assert (answer["twin"]["label"], answer["twin"]["observations"]) == ("1.0", [])
        assert nothing == (409, refused("TWIN_UPDATE_NOTHING_NEW"))
        assert later["material"] == {"changes": 1, "tests": 0}
        assert [item["status"] for item in project.twin_updates()] == ["PROPOSED", "REJECTED"]
        assert studio.errors == []


def test_the_refusals_of_a_decision_on_an_update() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        twin = twins_of(project)[0]["twin_id"]
        project.seed_learning(
            0, [f"Osservazione numero {number}." for number in range(19)], source="OWNER"
        )
        project.seed_change()
        update = project.seed_update(0)
        path = f"{base}/twin-updates/{update['id']}/decision"
        unknown = f"{base}/twin-updates/{UNKNOWN_ID}"

        assert stranger(studio).call("POST", path, {"decision": "REJECT"}) == (
            404,
            refused("PROJECT_NOT_FOUND"),
        )
        assert client.call("POST", unknown + "/decision", {"decision": "REJECT"}) == (
            404,
            refused("TWIN_UPDATE_NOT_FOUND"),
        )
        assert client.call("GET", unknown) == (404, refused("TWIN_UPDATE_NOT_FOUND"))
        assert client.call(
            "POST", path, {"decision": "APPROVE", "kept": [{"index": 0}, {"index": 1}]}
        ) == (409, refused("TWIN_OBSERVATIONS_LIMIT"))
        assert client.call("POST", path, {"decision": "APPROVE", "kept": [{"index": 5}]}) == (
            422,
            {
                "detail": {
                    "code": "invalid_request",
                    "errors": [
                        {
                            "loc": ["body", "kept", 0, "index"],
                            "type": "value_error",
                            "msg": "the proposal has no observation at this index",
                        }
                    ],
                }
            },
        )
        project.development[twin] += 1
        assert client.call("POST", path, {"decision": "APPROVE", "kept": [{"index": 0}]}) == (
            409,
            refused("TWIN_UPDATE_CONTEXT_CHANGED"),
        )
        rejected = decided_update(client, base, update["id"], {"decision": "REJECT"})
        assert rejected["update"]["status"] == "REJECTED"
        assert client.call("POST", path, {"decision": "REJECT"}) == (
            409,
            refused("TWIN_UPDATE_ALREADY_DECIDED"),
        )
        assert studio.errors == []


def test_a_decision_after_the_twins_changed_answers_the_entry_of_the_update() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.seed_change()
        update = project.seed_update(0)
        _, team = client.call("GET", base + "/team-proposals/current")
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        client.call("PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited})

        answer = decided_update(
            client, base, update["id"], {"decision": "APPROVE", "kept": [{"index": 0}]}
        )

        entry = answer["twin"]
        assert (entry["twin_id"], entry["twin_name"], entry["label"]) == (
            update["twin_id"],
            update["twin_name"],
            "1.1",
        )
        assert [item["update_id"] for item in entry["observations"]] == [update["id"]]
        assert learning_of(client, base)["twins"] == []
        assert project.twin_learning() == []
        assert studio.errors == []


def test_the_owner_writes_and_retires_observations() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        first, second = (twin["twin_id"] for twin in twins_of(project))

        def learn(twin: str, body: object) -> tuple[int, object]:
            return client.call("POST", f"{base}/user-twins/{twin}/observations", body)

        def retire(twin: str, code: str, body: object) -> tuple[int, object]:
            return client.call("POST", f"{base}/user-twins/{twin}/observations/{code}/retire", body)

        status, learned = learn(
            first,
            {
                "statement": "  Chi paga usa spesso   il telefono di un amico. ",
                "about": {"requirement": "REQ-002", "screen": None},
            },
        )
        _, other = learn(second, {"statement": "Il titolare legge i conti a fine serata."})
        status_retired, retired = retire(first, "obs-001", {"reason": "  Non vale più. "})

        entry = learned["twin"]
        assert (status, list(learned), learned["status"]) == (201, ["status", "twin"], "LEARNED")
        assert (entry["development_version_number"], entry["label"]) == (1, "1.1")
        assert entry["observations"] == [
            {
                "code": "OBS-001",
                "statement": "Chi paga usa spesso il telefono di un amico.",
                "basis": None,
                "source": "OWNER",
                "about": {"requirement": "REQ-002", "screen": None},
                "contradicts_profile": None,
                "added_in_version": 1,
                "approved_at": entry["observations"][0]["approved_at"],
                "update_id": None,
            }
        ]
        assert other["twin"]["observations"][0]["code"] == "OBS-002"
        assert other["twin"]["observations"][0]["about"] == {"requirement": None, "screen": None}
        assert (status_retired, retired["status"]) == (200, "RETIRED")
        assert retired["twin"]["observations"] == []
        assert retired["twin"]["retired"] == [
            {
                "code": "OBS-001",
                "statement": "Chi paga usa spesso il telefono di un amico.",
                "retired_in_version": 2,
                "retired_at": retired["twin"]["retired"][0]["retired_at"],
                "reason": "Non vale più.",
            }
        ]
        assert retired["twin"]["label"] == "1.2"
        for twin, code in (
            (first, "OBS-001"),
            (first, "OBS-002"),
            (first, "OBS-999"),
            (first, "OBS-1"),
            (first, "TSK-001"),
        ):
            assert retire(twin, code, {}) == (404, refused("TWIN_OBSERVATION_NOT_FOUND")), code
        assert learn(UNKNOWN_ID, {"statement": "x"}) == (404, refused("USER_TWIN_NOT_FOUND"))
        assert retire(UNKNOWN_ID, "OBS-002", {}) == (404, refused("USER_TWIN_NOT_FOUND"))
        assert retire(second, "OBS-0002", {"reason": None})[1]["twin"]["retired"][0]["code"] == (
            "OBS-002"
        )
        assert stranger(studio).call(
            "POST", f"{base}/user-twins/{first}/observations", {"statement": "x"}
        ) == (404, refused("PROJECT_NOT_FOUND"))
        learn(first, {"statement": "Chi paga tiene il conto in mano."})
        project.seed_change()
        pending = project.seed_update(0)
        blocked = refused("TWIN_UPDATE_PENDING", update_id=pending["id"])
        assert learn(first, {"statement": "Nuova."}) == (409, blocked)
        assert retire(first, "OBS-003", {}) == (409, blocked)
        for number in range(20):
            assert learn(second, {"statement": f"Osservazione {number}."})[0] == 201
        assert learn(second, {"statement": "Una di troppo."}) == (
            409,
            refused("TWIN_OBSERVATIONS_LIMIT"),
        )
        _, team = client.call("GET", base + "/team-proposals/current")
        edited = [agent for agent in team["selected_agent_ids"] if agent != "FRONTEND_ENGINEER"]
        client.call("PATCH", base + "/team-proposals/current", {"selected_agent_ids": edited})
        assert learn(second, {"statement": "x"}) == (
            409,
            refused("USER_MODELING_APPROVAL_REQUIRED"),
        )
        assert retire(second, "OBS-004", {}) == (409, refused("USER_MODELING_APPROVAL_REQUIRED"))
        assert studio.errors == []


def test_invalid_learning_requests_answer_like_the_real_application(
    real_client: TestClient,
) -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="brief")
        base = f"/projects/{project.id}"
        for method, path, body in LEARNING_REQUESTS:
            real = real_client.request(method, PREFIX + base + path, json=body)
            assert real.status_code == 422, (path, body, real.text)
            assert client.call(method, base + path, body) == (422, real.json()), (path, body)
        assert project.twin_updates() == []
        assert studio.errors == []


def test_the_job_key_of_an_update_is_the_key_of_the_real_application() -> None:
    with FakeStudio(job_polls=5) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.seed_change()
        twin = twins_of(project)[0]["twin_id"]
        bodies = [{"locale": "en-US"}, {}]

        started = [
            client.call("POST", update_path(base, twin), body, headers=PREFER)[1] for body in bodies
        ]

        for body, job in zip(bodies, started, strict=True):
            assert studio._jobs[job["job_id"]].key == request_key(
                GenerationOperation.TWIN_UPDATE,
                {"project_id": project.id, "twin_id": twin},
                twin_learning_api.TwinUpdateRequest.model_validate(body),
            )
        assert started[0]["job_id"] != started[1]["job_id"]
        assert studio.errors == []


@pytest.mark.parametrize("language", ["it", "en"])
def test_the_tasks_and_the_learning_of_the_fake_pass_the_real_domain_rules(language: str) -> None:
    with FakeStudio(language=language, twins=3, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        project.seed_tasks()
        project.set_task_status("TSK-002", "DONE", "Fatto.")
        project.set_task_status("TSK-004", "DROPPED")
        first, _, third = (twin["twin_id"] for twin in twins_of(project))
        update = proposed(client, base, first, LOCALE[language])
        decided_update(
            client,
            base,
            update["id"],
            {"decision": "APPROVE", "kept": [{"index": 0, "statement": "Cambiata."}]},
        )
        client.call("POST", f"{base}/user-twins/{first}/observations", {"statement": "Scritta."})
        client.call("POST", f"{base}/user-twins/{first}/observations/OBS-001/retire", {})
        proposed(client, base, third, LOCALE[language])
        project.seed_update(1, [{"statement": "Diversa.", "contradicts_profile": "Il profilo."}])
        reviewed(client, base, commit_of("more"))
        rejected = proposed(client, base, first, LOCALE[language])
        decided_update(client, base, rejected["id"], {"decision": "REJECT", "reason": "No."})

        tasks = project.tasks()
        updates = project.twin_updates()
        entries = project.twin_learning()

        assert {task["origin"]["kind"] for task in tasks} == {"CODE_CHANGE", "TEST_RUN", "OWNER"}
        for task in tasks:
            assert changes_domain.code_task_from_snapshot(task).to_snapshot() == task
        assert {update["status"] for update in updates} == {
            "APPROVED",
            "REJECTED",
            "PROPOSED",
            "EMPTY",
        }
        for item in updates:
            assert learning_domain.twin_update_from_snapshot(item).to_snapshot() == item
        for entry in entries:
            assert learning_domain.twin_learning_from_snapshot(entry).to_snapshot() == entry
        assert entries[0]["label"] == "1.3"
        assert studio.errors == []


def domain_version(version: dict) -> DesignPackageVersion:
    return DesignPackageVersion(
        id=UUID(version["id"]),
        project_id=UUID(version["project_id"]),
        version_number=version["version_number"],
        package=DesignPackagePayload.model_validate(version["package"]).to_domain(),
        content_hash=version["content_hash"],
        created_by_user_id=UUID(version["created_by_user_id"]),
        created_at=datetime.fromisoformat(version["created_at"]),
        based_on_version_number=version["based_on_version_number"],
    )


def distance_answer(version: dict, mockups: dict) -> dict:
    report = design_distance_report(domain_version(version), mockups)
    return json.loads(
        json.dumps(DesignDistancePayload.model_validate(report).model_dump(mode="json"))
    )


def test_the_distance_route_measures_the_current_design_and_its_kept_mockups() -> None:
    with FakeStudio(language="en", job_polls=0, directions=True) as studio:
        client = signed(studio)
        other = stranger(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        base = f"/projects/{project.id}"
        missing = client.call("GET", base + "/design/distance")
        assert client.call("POST", base + "/design/proposals")[0] == 201
        current = project.current("design")
        early = fits(DesignDistancePayload, client.call("GET", base + "/design/distance"))
        mockups = {}
        for alternative in current["package"]["alternatives"]:
            _, job = client.call(
                "POST",
                base + "/design/mockups/jobs",
                {
                    "design_version_id": current["id"],
                    "design_content_hash": current["content_hash"],
                    "alternative_id": alternative["id"],
                },
            )
            _, finished = client.call("GET", f"{base}/design/mockups/jobs/{job['job_id']}")
            bound = finished["result"]["package"]["generated_mockup"]
            tokens = alternative["visual_language"]["tokens"]
            mockups[UUID(alternative["id"])] = bound_mockup_from_snapshot(
                bound, token_names=tokens
            ).mockup
        late = fits(DesignDistancePayload, client.call("GET", base + "/design/distance"))
        foreign = other.call("GET", base + "/design/distance")
        assert studio.errors == []

    assert missing == foreign == (404, refused("DESIGN_PACKAGE_NOT_FOUND"))
    assert early == distance_answer(current, {})
    assert late == distance_answer(current, mockups)
    assert early["pairs"][0]["verdict"] == "UNKNOWN"
    assert early["pairs"][0]["declared"]["axes_different"] == 5
    assert late["pairs"][0]["styles"]["available"] is True
    assert [item["direction"] for item in late["alternatives"]] == ["Reading sheet", "Till receipt"]


def test_the_distance_of_a_design_without_directions_keeps_the_applied_mockup() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        answer = fits(
            DesignDistancePayload, client.call("GET", f"/projects/{project.id}/design/distance")
        )
        current = project.current("design")
        assert studio.errors == []

    package = current["package"]
    chosen = next(
        item
        for item in package["alternatives"]
        if item["id"] == package["owner_selected_alternative_id"]
    )
    mockup = bound_mockup_from_snapshot(
        package["generated_mockup"], token_names=chosen["visual_language"]["tokens"]
    ).mockup
    assert answer == distance_answer(current, {UUID(chosen["id"]): mockup})
    assert answer["pairs"][0]["declared"]["axes_different"] is None
    assert answer["pairs"][0]["verdict"] == "UNKNOWN"
    assert [item["direction"] for item in answer["alternatives"]] == [None, None]


@pytest.mark.parametrize(
    ("directions", "purposes"),
    [
        (False, ["DESIGN_ALTERNATIVES_HOSTED"] * 2),
        (True, ["DESIGN_DIRECTIONS", "DESIGN_ALTERNATIVES_HOSTED"] * 2),
    ],
)
def test_a_directed_proposal_records_the_directions_before_the_alternatives(
    directions: bool, purposes: list[str]
) -> None:
    with FakeStudio(job_polls=0, directions=directions) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="requirements")
        base = f"/projects/{project.id}"
        assert client.call("POST", base + "/design/proposals")[0] == 201
        assert client.call("POST", base + "/design/regenerations")[0] == 201
        _, usage = client.call("GET", base + "/model-usage")
        assert studio.errors == []

    assert [item["purpose"] for item in reversed(usage["items"])] == purposes
    assert {item["task"] for item in usage["items"]} == {"design"}


@pytest.mark.parametrize("language", ["it", "en"])
def test_a_directed_fake_binds_the_choices_of_each_alternative_to_its_direction(
    language: str,
) -> None:
    packages = []
    for directions in (False, True):
        studio = FakeStudio(language=language, directions=directions)
        studio.add_account(EMAIL, PASSWORD)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        packages.append([version["package"] for version in project.designs])
    plain, directed = packages
    codes = [
        item["code"] for item in project.current("requirements")["specification"]["requirements"]
    ]
    languages = [item["visual_language"] for item in directed[-1]["alternatives"]]
    found = [visual_direction_from_snapshot(item["direction"]) for item in languages]

    assert all(
        "direction" not in item["visual_language"]
        for package in plain
        for item in package["alternatives"]
    )
    for snapshot, direction in zip(languages, found, strict=True):
        assert visual_language_from_snapshot(snapshot).to_snapshot() == snapshot
        for axis in DIRECTION_AXES:
            for dimension, allowed in AXIS_BINDINGS[axis][getattr(direction.axes, axis)].items():
                assert snapshot["choices"][dimension] in {item.value for item in allowed}
    assert direction_distance(found[0].axes, found[1].axes) == 5
    assert [item.candidates for item in found] == [5, 5]
    for package in directed:
        canonical_design(package, codes)
    with pytest.raises(ValueError, match="hosted"):
        FakeStudio(hosted=False, directions=True)
