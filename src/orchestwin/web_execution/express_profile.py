"""Structurally validated Node.js Express profile for JavaScript and TypeScript."""

from __future__ import annotations

from dataclasses import dataclass

from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import WebDetectionSnapshot
from orchestwin.web_execution.lockfiles import WebDependencyLockReport
from orchestwin.web_execution.profile_contracts import (
    WebProfileContract,
    WebProfileIssue,
    WebProfileIssueCode,
    WebProfileRunnerSet,
    WebProfileValidation,
    common_profile_issues,
    create_profile_contract,
    create_profile_validation,
    dependency_issues,
    json_object,
    require_any_path,
    require_paths,
    script_issues,
)
from orchestwin.web_execution.runtime_evidence import WebHealthCheckSpec
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebTargetSelection,
    WebValidationScope,
    web_scope_for,
)

_FORBIDDEN_DEPENDENCIES = frozenset(
    {
        "@nestjs/core",
        "fastify",
        "koa",
        "nuxt",
        "react",
        "vite",
        "vue",
    }
)
_JAVASCRIPT_ENTRYPOINTS = (
    "app.js",
    "index.js",
    "server.js",
    "src/app.js",
    "src/index.js",
    "src/server.js",
)
_TYPESCRIPT_ENTRYPOINTS = (
    "app.ts",
    "index.ts",
    "server.ts",
    "src/app.ts",
    "src/index.ts",
    "src/server.ts",
)


@dataclass(frozen=True, slots=True)
class WebNodeExpressExecutionProfile:
    """Profile for one API-only Express service with a local health endpoint."""

    @property
    def scope(self) -> WebValidationScope:
        return web_scope_for(ExecutionTarget.WEB_NODE_EXPRESS)

    def validate(
        self,
        snapshot: WebDetectionSnapshot,
        *,
        selection: WebTargetSelection,
        lock_report: WebDependencyLockReport,
    ) -> WebProfileValidation:
        issues: list[WebProfileIssue] = common_profile_issues(
            snapshot,
            selection=selection,
            lock_report=lock_report,
            expected_target=ExecutionTarget.WEB_NODE_EXPRESS,
        )
        issues.extend(require_paths(snapshot, "package.json", "package-lock.json"))
        manifest, manifest_issue = json_object(snapshot, "package.json")
        if manifest_issue is not None:
            issues.append(manifest_issue)
        if manifest is not None:
            issues.extend(
                dependency_issues(
                    manifest=manifest,
                    path="package.json",
                    required=frozenset({"express"}),
                    forbidden=_FORBIDDEN_DEPENDENCIES,
                )
            )
            required_scripts = {"start", "test"}
            if selection.language_configuration.backend is WebImplementationLanguage.TYPESCRIPT:
                required_scripts.add("build")
            issues.extend(
                script_issues(
                    manifest=manifest,
                    path="package.json",
                    required=frozenset(required_scripts),
                )
            )
        language = selection.language_configuration.backend
        if language is WebImplementationLanguage.TYPESCRIPT:
            issues.extend(require_paths(snapshot, "tsconfig.json"))
            issues.extend(require_any_path(snapshot, candidates=_TYPESCRIPT_ENTRYPOINTS))
        elif language is WebImplementationLanguage.JAVASCRIPT:
            issues.extend(require_any_path(snapshot, candidates=_JAVASCRIPT_ENTRYPOINTS))
        else:
            issues.append(
                WebProfileIssue(
                    code=WebProfileIssueCode.LANGUAGE_MISMATCH,
                    path=None,
                    message="Express profile requires a JavaScript or TypeScript backend.",
                )
            )
        return create_profile_validation(
            snapshot=snapshot,
            selection=selection,
            lock_report=lock_report,
            scope=self.scope,
            issues=issues,
        )

    def create_contract(
        self,
        snapshot: WebDetectionSnapshot,
        *,
        selection: WebTargetSelection,
        lock_report: WebDependencyLockReport,
        source_revision_content_hash: str,
        source_tree_hash: str,
        runners: WebProfileRunnerSet,
        declared_routes: tuple[WebBrowserRouteSpec, ...] = (),
    ) -> WebProfileContract:
        if declared_routes:
            raise ValueError("API-only Express profile does not accept browser routes")
        validation = self.validate(
            snapshot,
            selection=selection,
            lock_report=lock_report,
        )
        return create_profile_contract(
            validation=validation,
            snapshot=snapshot,
            lock_report=lock_report,
            source_revision_content_hash=source_revision_content_hash,
            source_tree_hash=source_tree_hash,
            runners=runners,
            health_checks=(
                WebHealthCheckSpec(
                    check_id="express.health",
                    host="127.0.0.1",
                    port=3000,
                    path="/health",
                    expected_status_codes=(200, 204),
                    request_timeout_seconds=2,
                    maximum_attempts=20,
                    interval_milliseconds=250,
                ),
            ),
            browser_base_url=None,
            declared_routes=(),
        )
