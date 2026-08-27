"""Structurally validated framework-free PHP and Composer Web profile."""

from __future__ import annotations

from collections.abc import Mapping
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
    json_object,
    require_paths,
)
from orchestwin.web_execution.runtime_evidence import WebHealthCheckSpec
from orchestwin.web_execution.targets import (
    WebTargetSelection,
    WebValidationScope,
    web_scope_for,
)

_REQUIRED_PACKAGES = frozenset({"php", "phpunit/phpunit"})
_FORBIDDEN_PACKAGES = frozenset(
    {
        "laravel/framework",
        "symfony/framework-bundle",
    }
)


@dataclass(frozen=True, slots=True)
class WebPhpExecutionProfile:
    """Profile for framework-free PHP applications served from public/."""

    @property
    def scope(self) -> WebValidationScope:
        return web_scope_for(ExecutionTarget.WEB_PHP)

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
            expected_target=ExecutionTarget.WEB_PHP,
        )
        issues.extend(
            require_paths(
                snapshot,
                "composer.json",
                "composer.lock",
                "public/index.php",
            )
        )
        manifest, manifest_issue = json_object(snapshot, "composer.json")
        if manifest_issue is not None:
            issues.append(manifest_issue)
        if manifest is not None:
            issues.extend(_composer_package_issues(manifest))
        wordpress_paths = tuple(
            path
            for path in snapshot.included_paths
            if path == "wp-config.php" or path.startswith("wp-content/")
        )
        issues.extend(
            WebProfileIssue(
                code=WebProfileIssueCode.UNSUPPORTED_PROJECT,
                path=path,
                message="WordPress is outside the framework-free PHP validation scope.",
            )
            for path in wordpress_paths
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
                    check_id="php.root",
                    host="127.0.0.1",
                    port=8080,
                    path="/",
                    expected_status_codes=(200,),
                    request_timeout_seconds=2,
                    maximum_attempts=20,
                    interval_milliseconds=250,
                ),
            ),
            browser_base_url="http://127.0.0.1:8080",
            declared_routes=declared_routes,
        )


def _composer_package_issues(
    manifest: Mapping[str, object],
) -> tuple[WebProfileIssue, ...]:
    names: set[str] = set()
    for field in ("require", "require-dev"):
        values = manifest.get(field)
        if isinstance(values, dict):
            names.update(key.casefold() for key in values if isinstance(key, str))
    issues = [
        WebProfileIssue(
            code=WebProfileIssueCode.REQUIRED_DEPENDENCY_MISSING,
            path="composer.json",
            message=f"Required Composer package {name} is missing from the manifest.",
        )
        for name in sorted(_REQUIRED_PACKAGES - names)
    ]
    issues.extend(
        WebProfileIssue(
            code=WebProfileIssueCode.FORBIDDEN_DEPENDENCY,
            path="composer.json",
            message=f"Composer package {name} is outside the framework-free PHP profile.",
        )
        for name in sorted(_FORBIDDEN_PACKAGES & names)
    )
    return tuple(issues)
