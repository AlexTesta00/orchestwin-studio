from __future__ import annotations

import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import usage
from orchestwin.cli.client import api_failure, payload
from orchestwin.cli.errors import ApiFailure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.http import Reply

LATEST: Final = "latest"
APPLIED: Final = "applied"
APPROVE: Final = "APPROVE"
DECLARATIVE_TIMEOUT: Final = 900.0
NO_MODEL: Final = "REAL_MODEL_RUNTIME_NOT_CONFIGURED"
NO_MOCKUP_MODEL: Final = "REAL_MOCKUP_MODEL_NOT_CONFIGURED"


@dataclass(frozen=True, slots=True)
class Capabilities:
    generated_mockups: bool
    iterations: bool
    static_check: bool
    model: str | None


@dataclass(frozen=True, slots=True)
class ModelRuntime:
    model: bool
    budget: bool
    billing: str = usage.API_BILLING


NO_CAPABILITIES: Final = Capabilities(
    generated_mockups=False, iterations=False, static_check=False, model=None
)


def model_runtime(client: StudioClient) -> ModelRuntime:
    reply = client.request("GET", usage.BUDGET_PATH)
    if reply.status == 404:
        return ModelRuntime(model=True, budget=False)
    if reply.status >= 400:
        failure = api_failure(reply)
        if reply.status == 503 and failure.code in usage.NO_BUDGET_CODES:
            return ModelRuntime(model=failure.code != NO_MODEL, budget=False)
        raise failure
    document = payload(reply)
    total = document.get("total_microusd") if isinstance(document, dict) else None
    return ModelRuntime(
        model=True,
        budget=isinstance(total, int) and not isinstance(total, bool),
        billing=usage.billing(document),
    )


def design_path(project_id: str) -> str:
    return f"/projects/{project_id}/design"


def proposals_path(project_id: str) -> str:
    return f"{design_path(project_id)}/proposals"


def regenerations_path(project_id: str) -> str:
    return f"{design_path(project_id)}/regenerations"


def evaluations_path(project_id: str) -> str:
    return f"{design_path(project_id)}/evaluations"


def mockup_jobs_path(project_id: str) -> str:
    return f"{design_path(project_id)}/mockups/jobs"


def mockup_job_path(project_id: str, job_id: str) -> str:
    return f"{mockup_jobs_path(project_id)}/{job_id}"


def iteration_jobs_path(project_id: str) -> str:
    return f"{design_path(project_id)}/iterations/jobs"


def iteration_job_path(project_id: str, job_id: str) -> str:
    return f"{iteration_jobs_path(project_id)}/{job_id}"


def request_job_path(project_id: str, job_id: str) -> str:
    return f"/projects/{project_id}/generation-jobs/{job_id}"


def readiness(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = client.get(f"{design_path(project_id)}/readiness")
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def current(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    document = client.get(f"{design_path(project_id)}/current", optional=True)
    if document is None:
        return None
    if not isinstance(document, dict) or not isinstance(document.get("package"), dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def history(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(design_path(project_id)))


def capabilities(client: StudioClient, project_id: str) -> Capabilities:
    reply = client.request("GET", f"{design_path(project_id)}/mockups/capabilities")
    if reply.status >= 400:
        return NO_CAPABILITIES
    document = payload(reply)
    if not isinstance(document, dict):
        return NO_CAPABILITIES
    model = document.get("model")
    return Capabilities(
        generated_mockups=document.get("generated_mockups") is True,
        iterations=document.get("iterations") is True,
        static_check=document.get("static_check") is True,
        model=model if isinstance(model, str) and model else None,
    )


def mockup_document(
    client: StudioClient,
    project_id: str,
    alternative_id: str,
    *,
    source: str = LATEST,
) -> Mapping[str, object] | None:
    query = urllib.parse.urlencode({"alternative_id": alternative_id, "source": source})
    document = client.get(f"{design_path(project_id)}/mockups/document?{query}", optional=True)
    if document is None:
        return None
    if not isinstance(document, dict) or not isinstance(document.get("html"), str):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def latest_mockup(
    client: StudioClient, project_id: str, alternative_id: str
) -> Mapping[str, object] | None:
    query = urllib.parse.urlencode({"alternative_id": alternative_id})
    reply = client.request("GET", f"{design_path(project_id)}/mockups?{query}")
    if reply.status >= 400 or not reply.content.strip():
        return None
    document = reply.json()
    if not isinstance(document, dict) or not isinstance(document.get("package"), dict):
        return None
    return document


def version_body(version: Mapping[str, object], **extra: object) -> dict[str, object]:
    return {
        "design_version_id": version.get("id"),
        "design_content_hash": version.get("content_hash"),
        **extra,
    }


def start_mockup(
    client: StudioClient,
    project_id: str,
    version: Mapping[str, object],
    alternative_id: str,
) -> Reply:
    return client.request(
        "POST",
        mockup_jobs_path(project_id),
        body=version_body(version, alternative_id=alternative_id),
    )


def declarative_mockup(
    client: StudioClient,
    project_id: str,
    version: Mapping[str, object],
    alternative_id: str,
) -> Mapping[str, object]:
    reply = client.request(
        "POST",
        f"{design_path(project_id)}/mockups",
        body=version_body(version, alternative_id=alternative_id),
        timeout=DECLARATIVE_TIMEOUT,
    )
    document = payload(reply)
    if not isinstance(document, dict) or not isinstance(document.get("package"), dict):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return document


def iteration_body(
    version: Mapping[str, object], request: str, rules: Sequence[str]
) -> dict[str, object]:
    return version_body(version, request=request, assertions=list(rules))


def evaluation_body(version: Mapping[str, object], locale: str) -> dict[str, object]:
    return version_body(version, locale=locale)


def propose_revision(
    client: StudioClient, project_id: str, package: Mapping[str, object]
) -> Mapping[str, object]:
    document = client.post(f"{design_path(project_id)}/revisions", {"package": package})
    diff = document.get("diff") if isinstance(document, dict) else None
    if not isinstance(diff, dict) or not isinstance(diff.get("id"), str):
        raise ApiFailure("API_FAILURE", http_status=201)
    return document


def decide_revision(
    client: StudioClient,
    project_id: str,
    diff_id: str,
    decision: str = APPROVE,
) -> Mapping[str, object]:
    document = client.post(
        f"{design_path(project_id)}/revisions/{diff_id}/decision", {"decision": decision}
    )
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def revisions(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(f"{design_path(project_id)}/revisions"))


def submit_gate(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = client.post(f"{design_path(project_id)}/gate/submit")
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def decide_gate(
    client: StudioClient, project_id: str, action: str = APPROVE
) -> Mapping[str, object]:
    document = client.post(f"{design_path(project_id)}/gate/decision", {"action": action})
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def evaluations(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    return _items(client.get(evaluations_path(project_id), optional=True))


def comparison(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    reply = client.request("GET", f"{evaluations_path(project_id)}/comparison")
    if reply.status >= 400:
        return None
    document = payload(reply)
    return document if isinstance(document, dict) else None


def iterations(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    document = client.get(f"{design_path(project_id)}/iterations", optional=True)
    return _items(document.get("items") if isinstance(document, dict) else None)


def project_jobs(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    document = client.get(f"/projects/{project_id}/generation-jobs")
    return _items(document.get("items") if isinstance(document, dict) else None)


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
