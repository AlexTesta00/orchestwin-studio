from __future__ import annotations

from datetime import datetime
from functools import cache

from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, folder_archive
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.state import ProjectStateSources
from src.test.python.knowledge.knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    RECEPTION_TWIN,
    VOLUNTEER_TWIN,
    partial_sources,
    real_documents,
)

DEFAULT_PROJECT_NAME = "Calcolo mancia"
ARCHIVE_PROJECT_ID = str(REAL_PROJECT_ID)
COMPLETE_STAGE = "design"
TEST_RUN_ID = "00000000-0000-4000-8000-00000000e001"
TEST_ADDRESS = "http://127.0.0.1:41234/"
TEST_TITLE = "Lista ospiti"
TASK_COMMIT = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
LEARNING_UPDATE_ID = "00000000-0000-4000-8000-00000000f001"


@cache
def _published() -> tuple[tuple[int, int, str | None], tuple[tuple[str, str, int], ...]]:
    documents = real_documents()
    design = documents["design"]
    package = design["package"]
    chosen = next(
        (
            str(item["code"])
            for item in package["alternatives"]
            if item["id"] == package["owner_selected_alternative_id"]
        ),
        None,
    )
    twins = tuple(
        (str(twin["twin_id"]), str(twin["profile"]["name"]), int(twin["version_number"]))
        for twin in documents["twins"]["snapshot"]["twin_versions"]
    )
    versions = (
        int(documents["requirements"]["version_number"]),
        int(design["version_number"]),
        chosen,
    )
    return versions, twins


def folder_frame(through: str) -> dict[str, object]:
    if through not in STAGES:
        raise ValueError(f"through must be one of {', '.join(STAGES)}")
    (requirements, design, alternative), twins = _published()
    present = STAGES[: STAGES.index(through) + 1]
    return {
        "reference": {
            "requirements_version_number": requirements,
            "design_version_number": design,
            "alternative_code": alternative,
        }
        if "design" in present
        else None,
        "twins": tuple(
            {"twin_id": twin_id, "twin_name": name, "profile_version_number": version}
            for twin_id, name, version in twins
        )
        if "twins" in present
        else (),
    }


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


def _origin(
    kind: str,
    *,
    commit: str | None = None,
    test_run_id: str | None = None,
    finding: str | None = None,
) -> dict[str, object]:
    twin = finding is not None
    return {
        "kind": kind,
        "commit": commit,
        "test_run_id": test_run_id,
        "twin_id": RECEPTION_TWIN if twin else None,
        "twin_name": "Addetti all'accoglienza" if twin else None,
        "finding": finding,
    }


def _task(
    number: int,
    text: str,
    origin: dict[str, object],
    *,
    criteria: tuple[str, ...] = (),
    status: str = "OPEN",
    closed_at: str | None = None,
    note: str | None = None,
) -> dict[str, object]:
    owner = origin["kind"] == "OWNER"
    return {
        "code": f"TSK-{number:03d}",
        "text": text,
        "about": {
            "requirements": [] if owner else ["REQ-003"],
            "screens": [] if owner else ["SCR-002"],
            "criteria": list(criteria),
        },
        "origin": origin,
        "from_commit": origin["commit"],
        "created_at": f"2026-09-29T{number + 5:02d}:00:00+00:00",
        "status": status,
        "closed_at": closed_at,
        "note": note,
    }


def origin_tasks() -> tuple[dict[str, object], ...]:
    return (
        _task(
            1,
            "Mostrare il messaggio di errore accanto al campo del nome.",
            _origin("CODE_CHANGE", commit=TASK_COMMIT),
        ),
        _task(
            2,
            "Mostrare il messaggio accanto al campo del nome.",
            _origin(
                "CODE_CHANGE",
                commit=TASK_COMMIT,
                finding="Il campo del nome non spiega che cosa manca.",
            ),
            status="DONE",
            closed_at="2026-09-29T09:30:00+00:00",
            note="Fatto nel commit successivo.",
        ),
        _task(
            3,
            "Mostrare un avviso accanto al campo del nome.",
            _origin(
                "TEST_RUN",
                test_run_id=TEST_RUN_ID,
                finding="Con il nome vuoto non compare nessun messaggio.",
            ),
            criteria=("AC-002",),
        ),
        _task(
            4,
            "Aggiungere l'esportazione della lista in un foglio di calcolo.",
            _origin("OWNER"),
            status="DROPPED",
            closed_at="2026-09-29T09:45:00+00:00",
            note="Non serve per il primo evento.",
        ),
    )


def legacy_task() -> dict[str, object]:
    return {
        "code": "TSK-005",
        "text": "Coprire il requisito REQ-003 con un test automatico.",
        "about": {"requirements": ["REQ-003"], "screens": []},
        "from_commit": TASK_COMMIT,
        "created_at": "2026-09-28T11:40:00+00:00",
        "status": "OPEN",
    }


def learned_entries() -> tuple[dict[str, object], ...]:
    return (
        {
            "twin_id": RECEPTION_TWIN,
            "twin_name": "Addetti all'accoglienza",
            "profile_version_number": 1,
            "development_version_number": 3,
            "label": "1.3",
            "observations": [
                {
                    "code": "OBS-001",
                    "statement": "Chi accoglie gli ospiti controlla la lista su un tablet, in "
                    "piedi e di fretta.",
                    "basis": "Due rilievi sui commit del modulo e uno sulla verifica dei criteri.",
                    "source": "TWIN_CRITIQUE",
                    "about": {"requirement": "REQ-003", "screen": "SCR-002"},
                    "contradicts_profile": None,
                    "added_in_version": 1,
                    "approved_at": "2026-09-29T11:00:00+00:00",
                    "update_id": LEARNING_UPDATE_ID,
                },
                {
                    "code": "OBS-003",
                    "statement": "All'ingresso serve sapere subito se un nome è già in lista.",
                    "basis": None,
                    "source": "OWNER",
                    "about": {"requirement": None, "screen": None},
                    "contradicts_profile": None,
                    "added_in_version": 2,
                    "approved_at": "2026-09-29T11:30:00+00:00",
                    "update_id": None,
                },
            ],
            "retired": [
                {
                    "code": "OBS-002",
                    "statement": "Gli ospiti arrivano tutti insieme all'inizio dell'evento.",
                    "retired_in_version": 3,
                    "retired_at": "2026-09-29T12:00:00+00:00",
                    "reason": "Non vale per gli eventi della sera.",
                }
            ],
        },
        {
            "twin_id": VOLUNTEER_TWIN,
            "twin_name": "Organizzatori volontari",
            "profile_version_number": 1,
            "development_version_number": 0,
            "label": "1.0",
            "observations": [],
            "retired": [],
        },
    )
