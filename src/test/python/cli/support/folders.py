from __future__ import annotations

from datetime import datetime

from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, folder_archive
from orchestwin.knowledge.state import ProjectStateSources
from src.test.python.knowledge.knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    RECEPTION_TWIN,
    VOLUNTEER_TWIN,
    partial_sources,
)

DEFAULT_PROJECT_NAME = "Calcolo mancia"
ARCHIVE_PROJECT_ID = str(REAL_PROJECT_ID)
COMPLETE_STAGE = "design"
TEST_RUN_ID = "00000000-0000-4000-8000-00000000e001"
TEST_ADDRESS = "http://127.0.0.1:41234/"
TEST_TITLE = "Lista ospiti"


def stage_folder(
    *,
    through: str,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    created_at: datetime = PUBLISHED_AT,
    state: ProjectStateSources | None = None,
) -> KnowledgeFolder:
    sources = partial_sources(
        through, project_name=project_name, state=state or ProjectStateSources()
    )
    return build_knowledge_folder(sources, version_number=version_number, created_at=created_at)


def valid_folder(
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    created_at: datetime = PUBLISHED_AT,
) -> KnowledgeFolder:
    return stage_folder(
        through=COMPLETE_STAGE,
        project_name=project_name,
        version_number=version_number,
        created_at=created_at,
    )


def valid_archive(*, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1) -> bytes:
    folder = valid_folder(project_name=project_name, version_number=version_number)
    return folder_archive(folder).content


def valid_files(
    *, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1
) -> dict[str, str]:
    return dict(valid_folder(project_name=project_name, version_number=version_number).files)


def partial_archive(
    *, through: str, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1
) -> bytes:
    folder = stage_folder(through=through, project_name=project_name, version_number=version_number)
    return folder_archive(folder).content


def state_archive(
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    state: ProjectStateSources,
) -> bytes:
    folder = stage_folder(
        through=COMPLETE_STAGE,
        project_name=project_name,
        version_number=version_number,
        state=state,
    )
    return folder_archive(folder).content


def _step(
    action: str,
    *,
    target: tuple[str, str] | None = None,
    value: str | None = None,
    expect: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "action": action,
        "target": None if target is None else {"role": target[0], "name": target[1]},
        "value": value,
        "expect": expect,
    }


def _done(
    code: str, browser: str, index: int, status: str = "DONE", detail: str | None = None
) -> dict[str, object]:
    return {
        "index": index,
        "status": status,
        "detail": detail,
        "url": TEST_ADDRESS,
        "title": TEST_TITLE,
        "screenshot": f"{code}/{browser}/{index:02d}.png",
    }


def _result(
    path: dict[str, object], browser: str, status: str, seconds: float, page_text: str
) -> dict[str, object]:
    code = str(path["code"])
    failed = status == "FAILED"
    steps = [
        _done(
            code,
            browser,
            index,
            "FAILED" if failed and index == len(path["steps"]) else "DONE",
            "ELEMENT_VISIBLE: alert: Il nome è obbligatorio"
            if failed and index == len(path["steps"])
            else None,
        )
        for index in range(1, len(path["steps"]) + 1)
    ]
    return {
        "path": path,
        "browser": browser,
        "status": status,
        "seconds": seconds,
        "steps": steps,
        "page_text": page_text,
    }


def acceptance_run_document() -> dict[str, object]:
    add_guest = {
        "code": "TP-001",
        "heading": "Aggiungere un ospite e vederlo nella lista",
        "criteria": ["AC-001"],
        "steps": [
            _step("OPEN", value="/"),
            _step("TYPE", target=("textbox", "Nome ospite"), value="Marco Rossi"),
            _step(
                "CLICK",
                target=("button", "Conferma"),
                expect={"kind": "TEXT_VISIBLE", "target": None, "text": "Marco Rossi"},
            ),
        ],
    }
    empty_name = {
        "code": "TP-002",
        "heading": "Un nome vuoto non entra nella lista",
        "criteria": ["AC-002"],
        "steps": [
            _step("OPEN", value="/"),
            _step(
                "CLICK",
                target=("button", "Conferma"),
                expect={
                    "kind": "ELEMENT_VISIBLE",
                    "target": {"role": "alert", "name": "Il nome è obbligatorio"},
                    "text": None,
                },
            ),
        ],
    }
    return {
        "id": TEST_RUN_ID,
        "started_at": "2026-09-29T10:00:00+00:00",
        "finished_at": "2026-09-29T10:01:12+00:00",
        "recorded_at": "2026-09-29T10:01:13+00:00",
        "application": {"kind": "STATIC", "address": "dist"},
        "browsers": [
            {"name": "chrome", "version": "151.0.7922.76"},
            {"name": "firefox", "version": "156.0.1"},
        ],
        "reference": {
            "requirements_version_number": 2,
            "design_version_number": 4,
            "alternative_code": "DES-002",
        },
        "summary": {"passed": 1, "failed": 1, "blocked": 0, "not_covered": 1, "not_run": 0},
        "criteria": [
            {"code": "AC-001", "status": "PASSED", "paths": ["TP-001"]},
            {"code": "AC-002", "status": "FAILED", "paths": ["TP-002"]},
            {"code": "AC-003", "status": "NOT_COVERED", "paths": []},
        ],
        "not_covered": [{"criterion": "AC-003", "reason": "Richiede una verifica manuale"}],
        "results": [
            _result(add_guest, "chrome", "PASSED", 3.4, "Lista ospiti Marco Rossi"),
            _result(add_guest, "firefox", "PASSED", 4.1, "Lista ospiti Marco Rossi"),
            _result(empty_name, "chrome", "FAILED", 2.2, "Lista ospiti Nessun ospite"),
            _result(empty_name, "firefox", "FAILED", 2.6, "Lista ospiti Nessun ospite"),
        ],
        "critiques": [
            {
                "twin_id": RECEPTION_TWIN,
                "twin_name": "Addetti all'accoglienza",
                "verdict": "CONCERN",
                "summary": "Un nome vuoto non mostra nessun avviso: all'ingresso perderei tempo.",
                "findings": [
                    {
                        "severity": "MEDIUM",
                        "text": "Con il nome vuoto non compare nessun messaggio.",
                        "about": {
                            "criterion": "AC-002",
                            "requirement": "REQ-003",
                            "screen": "SCR-002",
                        },
                        "action": "Mostrare un avviso accanto al campo del nome.",
                    }
                ],
            },
            {
                "twin_id": VOLUNTEER_TWIN,
                "twin_name": "Organizzatori volontari",
                "verdict": "FINE",
                "summary": "La lista si aggiorna subito dopo l'aggiunta di un ospite.",
                "findings": [],
            },
        ],
        "reviewed_at": "2026-09-29T10:05:00+00:00",
        "cost_microusd": 500000,
    }
