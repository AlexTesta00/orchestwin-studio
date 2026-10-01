from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import cache

from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder, folder_archive
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.state import ProjectStateSources
from src.test.python.knowledge.knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    RECEPTION_TWIN,
    VOLUNTEER_TWIN,
    real_documents,
    sources_of,
)

DEFAULT_PROJECT_NAME = "Calcolo mancia"
ARCHIVE_PROJECT_ID = str(REAL_PROJECT_ID)
COMPLETE_STAGE = "design"
TEST_RUN_ID = "00000000-0000-4000-8000-00000000e001"
TEST_ADDRESS = "http://127.0.0.1:41234/"
TEST_TITLE = "Lista ospiti"
TASK_COMMIT = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
LEARNING_UPDATE_ID = "00000000-0000-4000-8000-00000000f001"


def _fixture_documents(language: str) -> dict[str, dict[str, object]]:
    documents = real_documents()
    if language == "it":
        return documents
    brief = documents["brief"]["brief"]["fields"]
    brief["description"] = (
        "The team needs a web product to manage the guest list and check reservations at the reception desk."
    )
    brief["problem"] = (
        "The information is spread across files and the team cannot find the current guest list when people arrive."
    )
    brief["goals"] = [
        "Keep the information available to the team.",
        "Check the guest list and record arrivals.",
    ]
    brief["target_users"] = ["Reception staff and volunteer organizers."]
    brief["budget"] = "No budget is available."
    brief["definition_of_done"] = ["A volunteer adds three guests and sees them on the list."]
    brief["domain"] = "Community events"
    brief["functional_requirements"] = [
        "Enter a guest's name and add it to the list.",
        "Show the list with a sequence number and the guest's name.",
        "Reject empty names with a visible message.",
    ]
    brief["non_functional_requirements"] = [
        "The product must be easy to use on a tablet.",
        "The user does not need to register.",
    ]
    brief["risks"] = ["The same guest name may be entered more than once."]
    brief["stakeholders"] = ["The workshop coordinator."]
    brief["technical_constraints"] = ["A static web application with no backend."]
    brief["temporal_constraints"] = "The product must be ready before the next workshop."
    specification = documents["requirements"]["specification"]
    for item in specification["requirements"]:
        item["statement"] = (
            f"The system must support {item['code']} for the user and keep the information available to the team."
        )
    for item in specification["user_stories"]:
        item["goal"] = f"complete {item['code']} with the current information for the team"
    for item in specification["acceptance_criteria"]:
        item["statement"] = (
            f"When the user follows {item['code']}, the system shows the current information and confirms the action."
        )
    hashes: dict[str, str] = {}

    def refresh(value):
        if isinstance(value, dict):
            return {key: refresh(item) for key, item in value.items()}
        if isinstance(value, list):
            return [refresh(item) for item in value]
        return hashes.get(value, value) if isinstance(value, str) else value

    def rehash(version, key):
        previous = version["content_hash"]
        current = hashlib.sha256(
            json.dumps(
                version[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        version["content_hash"] = current
        hashes[previous] = current

    for stage, key in (
        ("brief", "brief"),
        ("team", "proposal"),
        ("twins", "snapshot"),
        ("requirements", "specification"),
        ("design", "package"),
    ):
        version = refresh(documents[stage])
        if stage == "twins":
            for persona in version[key]["persona_versions"]:
                rehash(persona, "profile")
            version = refresh(version)
            for twin in version[key]["twin_versions"]:
                rehash(twin, "profile")
            version = refresh(version)
        rehash(version, key)
        documents[stage] = version
    return documents


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
    language: str = "it",
) -> KnowledgeFolder:
    present = STAGES[: STAGES.index(through) + 1]
    versions = {
        stage: version
        for stage, version in stage_versions(_fixture_documents(language)).items()
        if stage in present
    }
    sources = sources_of(
        versions,
        project_id=REAL_PROJECT_ID,
        project_name=project_name,
        state=state or ProjectStateSources(),
    )
    return build_knowledge_folder(sources, version_number=version_number, created_at=created_at)


def valid_folder(
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    created_at: datetime = PUBLISHED_AT,
    language: str = "it",
) -> KnowledgeFolder:
    return stage_folder(
        through=COMPLETE_STAGE,
        project_name=project_name,
        version_number=version_number,
        created_at=created_at,
        language=language,
    )


def valid_archive(
    *, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1, language: str = "it"
) -> bytes:
    folder = valid_folder(
        project_name=project_name, version_number=version_number, language=language
    )
    return folder_archive(folder).content


def valid_files(
    *, project_name: str = DEFAULT_PROJECT_NAME, version_number: int = 1, language: str = "it"
) -> dict[str, str]:
    return dict(
        valid_folder(
            project_name=project_name, version_number=version_number, language=language
        ).files
    )


def partial_archive(
    *,
    through: str,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    language: str = "it",
) -> bytes:
    folder = stage_folder(
        through=through,
        project_name=project_name,
        version_number=version_number,
        language=language,
    )
    return folder_archive(folder).content


def state_archive(
    *,
    project_name: str = DEFAULT_PROJECT_NAME,
    version_number: int = 1,
    state: ProjectStateSources,
    language: str = "it",
) -> bytes:
    folder = stage_folder(
        through=COMPLETE_STAGE,
        project_name=project_name,
        version_number=version_number,
        state=state,
        language=language,
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
