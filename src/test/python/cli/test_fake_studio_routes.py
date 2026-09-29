from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

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
from orchestwin.api.design_mockups import MockupCapabilities
from orchestwin.api.design_review_pins import ReviewDocumentPayload, ReviewPinsPayload
from orchestwin.api.generation_jobs import GenerationJob, GenerationJobKind, GenerationOperation
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
from orchestwin.artifacts.bound_mockups import bound_mockup_from_snapshot
from orchestwin.artifacts.design_evaluation import synthetic_finding_from_snapshot
from orchestwin.artifacts.generated_mockup_review import review_generated_mockup
from orchestwin.artifacts.visual_catalog import MODES, VisualChoices
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.application import IdentityUnitOfWork, LocalIdentityApplicationService
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.models.design import DesignProposalIssueCode

from .support.fake_studio import PREFIX, ROUTES, FakeStudio, route_table

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
    }

    assert needed <= set(route_table())
    assert needed <= real_routes


class _Client:
    def __init__(self, studio: FakeStudio) -> None:
        self.base = studio.address + PREFIX
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token: str | None = None

    def call(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        content: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, object]:
        data = content if content is not None else None
        if content is None and body is not None:
            data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": content_type} if data is not None else {}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, _parsed(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, _parsed(error.read())


def _parsed(content: bytes) -> object:
    return json.loads(content.decode("utf-8")) if content else None


def fits(model: type[BaseModel], reply: tuple[int, object], status: int = 200) -> dict:
    code, payload = reply
    assert code == status, payload
    assert isinstance(payload, dict)
    assert set(payload) == set(model.model_fields), model.__name__
    model.model_validate(payload)
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
        blocked = fits(
            TeamProposalGenerationResponse, client.call("POST", base + "/team-proposals"), 409
        )
        assert blocked["status"] == "BLOCKED_BY_CONSTRAINTS"
        assert blocked["issues"]
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
