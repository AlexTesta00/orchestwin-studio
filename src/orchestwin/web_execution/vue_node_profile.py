"""Composable Vue frontend and Express backend Web execution profile."""

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
    paths_with_suffix,
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

_FRONTEND_FORBIDDEN = frozenset({"@angular/core", "express", "next", "nuxt", "react"})
_BACKEND_FORBIDDEN = frozenset({"@nestjs/core", "fastify", "koa", "react", "vite", "vue"})
_FRONTEND_JAVASCRIPT_ENTRIES = (
    "frontend/src/main.js",
    "frontend/src/main.jsx",
    "frontend/src/main.mjs",
)
_FRONTEND_TYPESCRIPT_ENTRIES = (
    "frontend/src/main.ts",
    "frontend/src/main.tsx",
)
_BACKEND_JAVASCRIPT_ENTRIES = (
    "backend/app.js",
    "backend/index.js",
    "backend/server.js",
    "backend/src/app.js",
    "backend/src/index.js",
    "backend/src/server.js",
)
_BACKEND_TYPESCRIPT_ENTRIES = (
    "backend/app.ts",
    "backend/index.ts",
    "backend/server.ts",
    "backend/src/app.ts",
    "backend/src/index.ts",
    "backend/src/server.ts",
)


@dataclass(frozen=True, slots=True)
class WebVueNodeExecutionProfile:
    """Profile that composes two locked npm roots without merging their plans."""

    @property
    def scope(self) -> WebValidationScope:
        return web_scope_for(ExecutionTarget.WEB_VUE_NODE)

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
            expected_target=ExecutionTarget.WEB_VUE_NODE,
        )
        issues.extend(
            require_paths(
                snapshot,
                "backend/package-lock.json",
                "backend/package.json",
                "frontend/package-lock.json",
                "frontend/package.json",
            )
        )
        if not paths_with_suffix(snapshot, root="frontend", suffix=".vue"):
            issues.append(
                WebProfileIssue(
                    code=WebProfileIssueCode.REQUIRED_PATH_MISSING,
                    path=None,
                    message="Composed Web profile requires a frontend .vue component.",
                )
            )
        frontend, frontend_issue = json_object(snapshot, "frontend/package.json")
        backend, backend_issue = json_object(snapshot, "backend/package.json")
        if frontend_issue is not None:
            issues.append(frontend_issue)
        if backend_issue is not None:
            issues.append(backend_issue)
        if frontend is not None:
            issues.extend(
                dependency_issues(
                    manifest=frontend,
                    path="frontend/package.json",
                    required=frozenset({"vite", "vue"}),
                    forbidden=_FRONTEND_FORBIDDEN,
                )
            )
            issues.extend(
                script_issues(
                    manifest=frontend,
                    path="frontend/package.json",
                    required=frozenset({"build", "preview", "test"}),
                )
            )
        if backend is not None:
            issues.extend(
                dependency_issues(
                    manifest=backend,
                    path="backend/package.json",
                    required=frozenset({"express"}),
                    forbidden=_BACKEND_FORBIDDEN,
                )
            )
            required_backend_scripts = {"start", "test"}
            if selection.language_configuration.backend is WebImplementationLanguage.TYPESCRIPT:
                required_backend_scripts.add("build")
            issues.extend(
                script_issues(
                    manifest=backend,
                    path="backend/package.json",
                    required=frozenset(required_backend_scripts),
                )
            )
        language = selection.language_configuration.frontend
        if language is not selection.language_configuration.backend:
            issues.append(
                WebProfileIssue(
                    code=WebProfileIssueCode.LANGUAGE_MISMATCH,
                    path=None,
                    message="Composed Web profile supports only matching JS/JS or TS/TS.",
                )
            )
        elif language is WebImplementationLanguage.TYPESCRIPT:
            issues.extend(
                require_paths(
                    snapshot,
                    "backend/tsconfig.json",
                    "frontend/tsconfig.json",
                )
            )
            issues.extend(
                require_any_path(
                    snapshot,
                    candidates=_FRONTEND_TYPESCRIPT_ENTRIES,
                    message="Vue frontend TypeScript entrypoint is missing.",
                )
            )
            issues.extend(
                require_any_path(
                    snapshot,
                    candidates=_BACKEND_TYPESCRIPT_ENTRIES,
                    message="Express backend TypeScript entrypoint is missing.",
                )
            )
        elif language is WebImplementationLanguage.JAVASCRIPT:
            issues.extend(
                require_any_path(
                    snapshot,
                    candidates=_FRONTEND_JAVASCRIPT_ENTRIES,
                    message="Vue frontend JavaScript entrypoint is missing.",
                )
            )
            issues.extend(
                require_any_path(
                    snapshot,
                    candidates=_BACKEND_JAVASCRIPT_ENTRIES,
                    message="Express backend JavaScript entrypoint is missing.",
                )
            )
        else:
            issues.append(
                WebProfileIssue(
                    code=WebProfileIssueCode.LANGUAGE_MISMATCH,
                    path=None,
                    message="Composed Web profile requires matching JavaScript-family roots.",
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
                    check_id="vue-node.backend",
                    host="127.0.0.1",
                    port=3000,
                    path="/health",
                    expected_status_codes=(200, 204),
                    request_timeout_seconds=2,
                    maximum_attempts=20,
                    interval_milliseconds=250,
                ),
                WebHealthCheckSpec(
                    check_id="vue-node.frontend",
                    host="127.0.0.1",
                    port=4173,
                    path="/",
                    expected_status_codes=(200,),
                    request_timeout_seconds=2,
                    maximum_attempts=20,
                    interval_milliseconds=250,
                ),
            ),
            browser_base_url="http://127.0.0.1:4173",
            declared_routes=declared_routes,
        )
