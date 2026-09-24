"""Read-only projection of durable Web capabilities into the public catalog.

These descriptors identify the typed execution APIs and their exact scope. They
are not adapters for Sprint 07's generic brownfield detection or command planning.
"""

from dataclasses import dataclass, fields

from sqlalchemy import text

from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.execution_profiles import (
    ExecutionProfileMetadata,
    ExecutionProfileNetworkPolicy,
    ExecutionTarget,
)
from orchestwin.web_execution.profile_loader import LoadedWebProfileCatalog
from orchestwin.web_execution.targets import WebValidationScope
from orchestwin.web_execution.validation_evidence import WebProfileValidationEvidenceCatalog
from orchestwin.web_execution.validation_evidence_persistence import (
    SqlAlchemyWebValidationEvidenceRepository,
)


@dataclass(frozen=True, slots=True)
class GovernedCatalogProfile(ExecutionProfileMetadata):
    """A compatible public descriptor whose hash also binds its narrower scope."""

    validation_scope: WebValidationScope
    runner_image_digests: tuple[str, ...]

    def __post_init__(self):
        ExecutionProfileMetadata.__post_init__(self)
        scope = self.validation_scope
        if (
            self.profile_id != scope.target.value
            or self.version != scope.profile_version
            or self.supported_targets != (scope.target,)
            or self.capability_status != scope.capability_status
            or self.validation_evidence_refs != scope.validation_evidence_refs
        ):
            raise ValueError("EXECUTION_CATALOG_SCOPE_MISMATCH")

    def _content_snapshot(self):
        return {
            **ExecutionProfileMetadata._content_snapshot(self),
            "governed_execution": {
                "family": "WEB",
                "profile_id": self.validation_scope.profile_id,
                "profile_version": self.validation_scope.profile_version,
                "validation_scope": self.validation_scope.to_snapshot(),
                "runner_image_digests": list(self.runner_image_digests),
                "prepare_endpoint": "/projects/{project_id}/web-executions/prepare",
                "start_endpoint": "/projects/{project_id}/web-executions",
                "source_validation_required": True,
                "gate_7_required": True,
                "runtime_availability": "NOT_CHECKED",
                "legacy_brownfield_capability_status": "DESIGN_ONLY_LEVEL_C",
            },
        }


def project_execution_catalog(registry, *, web, web_resources):
    """Project evaluated scopes only; never promote the broad built-in detectors."""
    scopes = {profile.scope.target: profile.scope for profile in web.registry.profiles}
    result = []
    for profile in registry.profiles:
        base = profile.metadata
        target = base.supported_targets[0]
        if target not in scopes:
            result.append(base)
            continue
        scope = scopes[target]
        decision = web.promotion_for(scope.profile_id, scope.profile_version)
        digests = ()
        if decision.is_eligible:
            digests = (
                decision.execution_runner_image_digest,
                decision.browser_runner_image_digest,
            )
        values = {
            field.name: getattr(base, field.name) for field in fields(ExecutionProfileMetadata)
        }
        values.update(
            version=scope.profile_version,
            capability_status=scope.capability_status,
            validation_evidence_refs=scope.validation_evidence_refs,
            file_indicators=scope.required_roots,
            required_runners=tuple(
                sorted(
                    ("web.php" if target is ExecutionTarget.WEB_PHP else "web.node",)
                    + (("web.browser",) if scope.requires_browser_evidence else ())
                )
            ),
            resource_defaults=web_resources,
            network_policy=ExecutionProfileNetworkPolicy(
                setup=CommandNetworkMode.DISABLED
                if target is ExecutionTarget.WEB_STATIC
                else CommandNetworkMode.CONTROLLED,
                static_checks=CommandNetworkMode.DISABLED,
                build=CommandNetworkMode.DISABLED,
                test=CommandNetworkMode.DISABLED,
                run=CommandNetworkMode.DISABLED,
            ),
            license_notes=(
                "Governed typed execution scope only; source validation and exact Gate 7 approval "
                "are required. Runtime availability is checked separately. Broad legacy "
                "brownfield detection is not promoted by this catalog projection."
            ),
        )
        result.append(
            GovernedCatalogProfile(
                **values,
                validation_scope=scope,
                runner_image_digests=tuple(sorted({digest for digest in digests if digest})),
            )
        )
    return tuple(result)


class SqlAlchemyExecutionCatalogLoader:
    """Read the verified web history in one consistent read-only SQL transaction."""

    def __init__(self, session_factory, *, registry, web_resources):
        self.sessions, self.registry, self.web_resources = session_factory, registry, web_resources

    async def load(self):
        async with self.sessions() as session, session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            web = LoadedWebProfileCatalog(
                WebProfileValidationEvidenceCatalog(
                    await SqlAlchemyWebValidationEvidenceRepository(session).history()
                )
            )
        return project_execution_catalog(self.registry, web=web, web_resources=self.web_resources)
