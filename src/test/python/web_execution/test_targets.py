"""Tests for capability-honest Web target validation scopes."""

from __future__ import annotations

import pytest

from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
    create_sprint08_web_validation_scopes,
    web_scope_for,
)


def test_sprint08_defines_exactly_five_design_only_web_scopes() -> None:
    scopes = create_sprint08_web_validation_scopes()

    assert set(scopes) == {
        ExecutionTarget.WEB_STATIC,
        ExecutionTarget.WEB_VUE,
        ExecutionTarget.WEB_NODE_EXPRESS,
        ExecutionTarget.WEB_PHP,
        ExecutionTarget.WEB_VUE_NODE,
    }
    assert all(
        scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for scope in scopes.values()
    )
    assert all(scope.validation_evidence_refs == () for scope in scopes.values())
    assert len({scope.content_hash for scope in scopes.values()}) == 5


def test_vue_and_express_treat_javascript_and_typescript_as_first_class() -> None:
    scopes = create_sprint08_web_validation_scopes()

    assert {
        configuration.frontend
        for configuration in scopes[ExecutionTarget.WEB_VUE].language_configurations
    } == {
        WebImplementationLanguage.JAVASCRIPT,
        WebImplementationLanguage.TYPESCRIPT,
    }
    assert {
        configuration.backend
        for configuration in scopes[ExecutionTarget.WEB_NODE_EXPRESS].language_configurations
    } == {
        WebImplementationLanguage.JAVASCRIPT,
        WebImplementationLanguage.TYPESCRIPT,
    }


def test_composed_scope_only_admits_matching_language_pairs() -> None:
    scope = web_scope_for(ExecutionTarget.WEB_VUE_NODE)

    assert scope.layout is WebProjectLayout.FRONTEND_BACKEND
    assert {
        (configuration.frontend, configuration.backend)
        for configuration in scope.language_configurations
    } == {
        (
            WebImplementationLanguage.JAVASCRIPT,
            WebImplementationLanguage.JAVASCRIPT,
        ),
        (
            WebImplementationLanguage.TYPESCRIPT,
            WebImplementationLanguage.TYPESCRIPT,
        ),
    }

    mixed = WebTargetSelection(
        target=ExecutionTarget.WEB_VUE_NODE,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.TYPESCRIPT,
            backend=WebImplementationLanguage.JAVASCRIPT,
        ),
        layout=WebProjectLayout.FRONTEND_BACKEND,
    )
    with pytest.raises(ValueError, match="outside the validation scope"):
        mixed.validate_against(scope)


def test_api_only_express_is_the_only_scope_without_browser_evidence() -> None:
    scopes = create_sprint08_web_validation_scopes()

    without_browser = {
        target for target, scope in scopes.items() if not scope.requires_browser_evidence
    }
    assert without_browser == {ExecutionTarget.WEB_NODE_EXPRESS}
