"""Structurally validated Vue 3 and Vite profile for JavaScript and TypeScript."""

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

_FORBIDDEN_DEPENDENCIES = frozenset(
    {
        "@angular/core",
        "express",
        "next",
        "nuxt",
        "react",
    }
)


@dataclass(frozen=True, slots=True)
class WebVueExecutionProfile:
    """Profile for a single-root Vue 3 application built and previewed by Vite."""

    @property
    def scope(self) -> WebValidationScope:
        return web_scope_for(ExecutionTarget.WEB_VUE)

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
            expected_target=ExecutionTarget.WEB_VUE,
        )
        issues.extend(require_paths(snapshot, "package.json", "package-lock.json"))
        if not paths_with_suffix(snapshot, root=".", suffix=".vue"):
            issues.append(
                WebProfileIssue(
                    code=WebProfileIssueCode.REQUIRED_PATH_MISSING,
                    path=None,
                    message="Vue profile requires at least one .vue component.",
                )
            )
        manifest, manifest_issue = json_object(snapshot, "package.json")
        if manifest_issue is not None:
            issues.append(manifest_issue)
        if manifest is not None:
            issues.extend(
                dependency_issues(
                    manifest=manifest,
                    path="package.json",
                    required=frozenset({"vite", "vue"}),
                    forbidden=_FORBIDDEN_DEPENDENCIES,
                )
            )
            issues.extend(
                script_issues(
                    manifest=manifest,
                    path="package.json",
                    required=frozenset({"build", "preview", "test"}),
                )
            )
        language = selection.language_configuration.frontend
        if language is WebImplementationLanguage.TYPESCRIPT:
            issues.extend(require_paths(snapshot, "tsconfig.json"))
            issues.extend(
                require_any_path(
                    snapshot,
                    candidates=("src/main.ts", "src/main.tsx"),
                )
            )
        elif language is WebImplementationLanguage.JAVASCRIPT:
            issues.extend(
                require_any_path(
                    snapshot,
                    candidates=("src/main.js", "src/main.jsx", "src/main.mjs"),
                )
            )
        else:
            issues.append(
                WebProfileIssue(
                    code=WebProfileIssueCode.LANGUAGE_MISMATCH,
                    path=None,
                    message="Vue profile requires a JavaScript or TypeScript frontend.",
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
                    check_id="vue.root",
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
