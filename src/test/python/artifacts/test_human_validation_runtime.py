from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import UUID

import pytest

from orchestwin.artifacts import human_validation_runtime as runtime_module
from orchestwin.artifacts.human_validation_runtime import SqlAlchemyHumanValidationService
from orchestwin.validation import ValidationError
from src.test.python.artifacts.test_human_validation import (
    NOW,
    OWNER,
    PROJECT,
    TEXT,
    hypothesis,
    outcome_request,
    request,
)
from src.test.python.artifacts.test_validation_projection import document
from src.test.python.projects.test_research_evidence import source


class Session:
    def __init__(self):
        self.active = False

    async def __aenter__(self):
        self.active = True
        return self

    async def __aexit__(self, *_):
        self.active = False

    def begin(self):
        return self


def service(monkeypatch, *, owned=True):
    state = {
        "session": Session(),
        "sessions": 0,
        "locked": False,
        "hypotheses": [],
        "outcomes": [],
        "source": source(TEXT, empirical=True),
        "current_source": None,
        "text": TEXT,
        "document": document(),
    }
    state["document"]["project_id"] = str(PROJECT)

    def sessions():
        state["sessions"] += 1
        return state["session"]

    class Repository:
        def __init__(self, session, *, owner_user_id):
            assert session is state["session"] and owner_user_id == OWNER

        async def owned(self, project_id, *, lock=False):
            assert project_id == PROJECT
            state["locked"] = state["locked"] or lock
            return owned

        async def hypothesis(self, *, project_id, hypothesis_id):
            return next(
                (item for item in reversed(state["hypotheses"]) if item.id == hypothesis_id), None
            )

        async def next_code(self, *, project_id, outcome=False):
            return "HVO-001" if outcome else "HYP-001"

        async def append_hypothesis(self, record):
            assert state["locked"]
            state["hypotheses"].append(record)

        async def append_outcome(self, record):
            assert state["locked"]
            state["outcomes"].append(record)

    class Sources:
        def __init__(self, session, *, owner_user_id):
            assert session is state["session"] and owner_user_id == OWNER

        async def get(self, project_id, source_id, version=None):
            return (
                state["source"]
                if version is not None
                else state["current_source"] or state["source"]
            )

        async def text(self, *_):
            return state["text"]

    class Why:
        async def in_session(self, session, *, owner_user_id, project_id, validation_context=False):
            assert session is state["session"] and state["locked"]
            assert owner_user_id == OWNER and project_id == PROJECT
            assert validation_context
            return deepcopy(state["document"])

    monkeypatch.setattr(runtime_module, "SqlAlchemyHumanValidationRepository", Repository)
    monkeypatch.setattr(runtime_module, "SqlAlchemyResearchEvidenceRepository", Sources)
    return SqlAlchemyHumanValidationService(
        sessions, why_query_service=Why(), clock=lambda: NOW
    ), state


def test_hypothesis_write_and_revision_share_project_lock_and_single_session(monkeypatch):
    runtime, state = service(monkeypatch)
    initial = asyncio.run(
        runtime.save_hypothesis(owner_user_id=OWNER, project_id=PROJECT, request=request())
    )
    assert state["sessions"] == 1 and initial["status"] == "HYPOTHESIS_SAVED"
    payload = {
        **request(),
        "based_on_version_number": 1,
        "based_on_content_hash": initial["hypothesis"]["content_hash"],
    }
    revised = asyncio.run(
        runtime.save_hypothesis(
            owner_user_id=OWNER,
            project_id=PROJECT,
            request=payload,
            hypothesis_id=UUID(initial["hypothesis"]["id"]),
        )
    )
    assert revised["hypothesis"]["version_number"] == 2
    assert state["sessions"] == 2 and len(state["hypotheses"]) == 2
    with pytest.raises(ValidationError, match="HYPOTHESIS_VERSION_CONFLICT"):
        asyncio.run(
            runtime.save_hypothesis(
                owner_user_id=OWNER,
                project_id=PROJECT,
                request=payload,
                hypothesis_id=UUID(initial["hypothesis"]["id"]),
            )
        )
    assert len(state["hypotheses"]) == 2


def test_outcome_rechecks_exact_hypothesis_source_and_context_under_one_lock(monkeypatch):
    runtime, state = service(monkeypatch)
    chosen = hypothesis()
    state["hypotheses"].append(chosen)
    result = asyncio.run(
        runtime.record_outcome(
            owner_user_id=OWNER,
            project_id=PROJECT,
            request=outcome_request(chosen, state["source"]),
        )
    )
    assert result["status"] == "VALIDATION_OUTCOME_RECORDED"
    assert state["sessions"] == 1 and len(state["outcomes"]) == 1
    state["document"]["nodes"][1]["current"] = False
    with pytest.raises(ValidationError, match="VALIDATION_CONTEXT_CHANGED"):
        asyncio.run(
            runtime.record_outcome(
                owner_user_id=OWNER,
                project_id=PROJECT,
                request=outcome_request(chosen, state["source"]),
            )
        )
    assert len(state["outcomes"]) == 1


def test_non_owner_is_rejected_before_loading_references_or_persisting(monkeypatch):
    runtime, state = service(monkeypatch, owned=False)
    with pytest.raises(ValidationError, match="PROJECT_NOT_FOUND"):
        asyncio.run(
            runtime.save_hypothesis(owner_user_id=OWNER, project_id=PROJECT, request=request())
        )
    assert state["hypotheses"] == [] and state["outcomes"] == []


def test_old_hypothesis_version_is_not_reassigned_to_current(monkeypatch):
    runtime, state = service(monkeypatch)
    chosen = hypothesis()
    state["hypotheses"].append(chosen)
    stale = {**outcome_request(chosen, state["source"]), "hypothesis_content_hash": "a" * 64}
    with pytest.raises(ValidationError, match="HYPOTHESIS_VERSION_CONFLICT"):
        asyncio.run(runtime.record_outcome(owner_user_id=OWNER, project_id=PROJECT, request=stale))
    assert state["outcomes"] == []
