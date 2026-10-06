from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from orchestwin.knowledge import state as shared_state
from orchestwin.knowledge import state_documents
from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    FEEDBACK_LEARNING,
    FEEDBACK_TESTS,
    KNOWLEDGE_INDEX,
    STATE_DOCUMENT,
    STATE_TEXT,
    schema_document,
)
from orchestwin.knowledge.schema import validate_document, validate_files
from orchestwin.knowledge.state import (
    MAX_FOLDER_TEST_RUNS,
    MAX_MESSAGE_LENGTH,
    ProjectStateSources,
)
from orchestwin.knowledge.state_documents import (
    acceptance_runs,
    change_reviews_document,
    current_reference,
    development_reference,
    learned_observations,
    learning_document,
    learning_entries,
    selected_alternative_code,
    stale_reviews,
    state_document,
    state_language,
    state_markdown,
)

from .knowledge_fixtures import (
    ALIGNED_COMMIT,
    CHANGE_RUN,
    CURRENT_REFERENCE,
    EARLIER_REFERENCE,
    PENDING_COMMIT,
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    RECEPTION_NAME,
    RECEPTION_TWIN,
    STALE_COMMIT,
    TEST_RUN,
    VOLUNTEER_NAME,
    VOLUNTEER_TWIN,
    change_run,
    development_sources,
    development_tasks,
    learned_entry,
    partial_sources,
    real_sources,
    sources,
    state_sources,
)
from .knowledge_fixtures import test_run as acceptance_run

SUBJECTS = {"requirements": None, "screens": None}
REFERENCE = {
    "requirements_version_number": None,
    "design_version_number": None,
    "alternative_code": None,
}
STATE_KEYS = {
    "schema_version": None,
    "kind": None,
    "project_id": None,
    "reference": {
        "requirements": {"version_id": None, "version_number": None, "content_hash": None},
        "design": {
            "version_id": None,
            "version_number": None,
            "content_hash": None,
            "alternative_code": None,
        },
    },
    "aligned": {
        "commit": None,
        "decided_at": None,
        "requirements_version_number": None,
        "design_version_number": None,
    },
    "changes": [
        {
            "commit": None,
            "parent": None,
            "committed_at": None,
            "author": None,
            "message": None,
            "files": [{"path": None, "kind": None, "added": None, "removed": None}],
            "recorded_at": None,
            "review": {
                "run_id": None,
                "reviewed_at": None,
                "verdict": None,
                "summary": None,
                "reference": REFERENCE,
                "stale": None,
            },
            "decision": {"kind": None, "decided_at": None, "note": None},
        }
    ],
    "tasks": [
        {
            "code": None,
            "text": None,
            "about": {"requirements": None, "screens": None, "criteria": None},
            "origin": {
                "kind": None,
                "commit": None,
                "test_run_id": None,
                "twin_id": None,
                "twin_name": None,
                "finding": None,
            },
            "from_commit": None,
            "created_at": None,
            "status": None,
            "closed_at": None,
            "note": None,
        }
    ],
}
LEARNED_KEYS = {
    "schema_version": None,
    "kind": None,
    "project_id": None,
    "twins": [
        {
            "twin_id": None,
            "twin_name": None,
            "profile_version_number": None,
            "development_version_number": None,
            "label": None,
            "observations": [
                {
                    "code": None,
                    "statement": None,
                    "basis": None,
                    "source": None,
                    "about": {"requirement": None, "screen": None},
                    "contradicts_profile": None,
                    "added_in_version": None,
                    "approved_at": None,
                    "update_id": None,
                }
            ],
            "retired": [
                {
                    "code": None,
                    "statement": None,
                    "retired_in_version": None,
                    "retired_at": None,
                    "reason": None,
                }
            ],
        }
    ],
}
CHANGES_KEYS = {
    "schema_version": None,
    "kind": None,
    "project_id": None,
    "runs": [
        {
            "id": None,
            "commit": None,
            "reviewed_at": None,
            "locale": None,
            "reference": {
                "requirements_version_number": None,
                "design_version_number": None,
                "alternative_code": None,
            },
            "critiques": [
                {
                    "twin_id": None,
                    "twin_name": None,
                    "verdict": None,
                    "summary": None,
                    "findings": [
                        {
                            "severity": None,
                            "text": None,
                            "about": {"requirement": None, "screen": None, "file": None},
                            "action": None,
                        }
                    ],
                }
            ],
            "alignment": {
                "status": None,
                "summary": None,
                "affected": SUBJECTS,
                "design_request": None,
                "requirements_request": None,
                "code_tasks": None,
            },
            "cost_microusd": None,
        }
    ],
}
TARGET = {"role": None, "name": None}
TESTS_KEYS = {
    "schema_version": None,
    "kind": None,
    "project_id": None,
    "runs": [
        {
            "id": None,
            "started_at": None,
            "finished_at": None,
            "recorded_at": None,
            "application": {"kind": None, "address": None},
            "browsers": [{"name": None, "version": None}],
            "reference": {
                "requirements_version_number": None,
                "design_version_number": None,
                "alternative_code": None,
            },
            "summary": {
                "passed": None,
                "failed": None,
                "blocked": None,
                "not_covered": None,
                "not_run": None,
            },
            "criteria": [{"code": None, "status": None, "paths": None}],
            "not_covered": [{"criterion": None, "reason": None}],
            "results": [
                {
                    "path": {
                        "code": None,
                        "heading": None,
                        "criteria": None,
                        "steps": [
                            {
                                "action": None,
                                "target": TARGET,
                                "value": None,
                                "expect": {"kind": None, "target": TARGET, "text": None},
                            }
                        ],
                    },
                    "browser": None,
                    "status": None,
                    "seconds": None,
                    "steps": [
                        {
                            "index": None,
                            "status": None,
                            "detail": None,
                            "url": None,
                            "title": None,
                            "screenshot": None,
                        }
                    ],
                    "page_text": None,
                }
            ],
            "critiques": [
                {
                    "twin_id": None,
                    "twin_name": None,
                    "verdict": None,
                    "summary": None,
                    "findings": [
                        {
                            "severity": None,
                            "text": None,
                            "about": {"criterion": None, "requirement": None, "screen": None},
                            "action": None,
                        }
                    ],
                }
            ],
            "reviewed_at": None,
            "cost_microusd": None,
        }
    ],
}
ITALIAN_TEXT = (
    "# Stato dello sviluppo: Lista ospiti workshop",
    "",
    "Questo documento dice a che punto è lo sviluppo del progetto fuori da OrchesTwin Studio: "
    "le versioni approvate che il codice deve realizzare, i commit registrati nello Studio, le "
    "critiche dei twin, le decisioni del proprietario e i compiti per il codice. I dati esatti "
    "sono in `state/state.json` e in `twins/feedback/changes.json`; il diff di un commit non "
    "viene mai copiato nella cartella.",
    "",
    "`ut push` invia allo Studio le modifiche fatte a mano in questa cartella: le differenze si "
    "approvano e nasce una versione nuova.",
    "",
    "## Riferimento",
    "",
    "- Requisiti: versione 2 (`requirements/requirements.md`).",
    "- Design: versione 4, alternativa DES-002 (`design/design.md`).",
    "",
    "## Punto allineato",
    "",
    "Commit `9d8e7f6`, deciso il 2026-09-28 10:00+00:00, con i requisiti alla versione 2 e il "
    "design alla versione 4.",
    "",
    "## Modifiche dopo il punto allineato",
    "",
    "Lo Studio ha registrato 2 modifiche; 1 è in attesa dopo il punto allineato.",
    "",
    "- `4f2a9c1` del 2026-09-28 11:00+00:00: Controllo del nome vuoto. Verdetto: il codice si "
    "allontana dai requisiti o dal design approvati (CODE_DRIFT). Decisione: sono stati "
    "registrati compiti per il codice (CODE_TASKS).",
    "",
    "## Compiti aperti",
    "",
    "- TSK-001: Mostrare il messaggio di errore accanto al campo del nome (requisiti REQ-003; "
    "schermate SCR-002; dalla decisione sul commit `4f2a9c1`).",
    "",
    "## Compiti chiusi",
    "",
    "Nessun compito è stato ancora chiuso.",
    "",
    "## Ultime critiche dei twin",
    "",
    "Commit `4f2a9c1`, rivisto il 2026-09-28 11:30+00:00. Verdetto: il codice si allontana dai "
    "requisiti o dal design approvati (CODE_DRIFT). Il controllo del nome vuoto non segue il "
    "requisito REQ-003.",
    "",
    "Compiti proposti per il codice: Mostrare il messaggio di errore accanto al campo del nome.",
    "",
    "### Addetti all'accoglienza: la modifica solleva un dubbio (CONCERN)",
    "",
    "Il messaggio per il nome vuoto compare solo dopo il salvataggio.",
    "",
    "- Importanza media (MEDIUM): Il campo del nome non spiega che cosa manca. Riguarda: "
    "REQ-003, SCR-002, src/app.js. Azione suggerita: Mostrare il messaggio accanto al campo del "
    "nome.",
    "- Importanza bassa (LOW): Il pulsante di conferma è piccolo sul tablet. Riguarda: SCR-002.",
    "",
    "### Organizzatori volontari: la modifica va bene (FINE)",
    "",
    "La lista si aggiorna subito e resta leggibile.",
    "",
    "- Importanza bassa (LOW): Il numero progressivo potrebbe essere più evidente. Riguarda: "
    "REQ-002, SCR-001. Azione suggerita: Rendere il numero in grassetto.",
    "",
    "## Verifica dei criteri",
    "",
    "L'ultima verifica dei criteri, conclusa il 2026-09-29 10:05+00:00, ha provato la cartella "
    "statica `dist` in Chrome 151.0.7922.76 e Firefox 156.0.1. Criteri: 1 superato, 1 fallito, "
    "0 bloccati, 1 non coperto, 0 non eseguiti. La revisione dei twin del 2026-09-29 10:20+00:00 "
    "lascia 2 critiche aperte. `twins/feedback/tests.json` contiene 1 verifica dei criteri con i "
    "passi, le prove e le critiche dei twin.",
    "",
    "## Cosa hanno imparato i twin",
    "",
    "Osservazioni apprese dai twin durante lo sviluppo: Addetti all'accoglienza, versione 1.0, "
    "nessuna osservazione; Organizzatori volontari, versione 1.0, nessuna osservazione. "
    "`twins/feedback/learned.json` le contiene con la loro origine; `ut twins update` ne propone "
    "di nuove.",
    "",
)
ENGLISH_TEXT = (
    "# Development state: Lista ospiti workshop",
    "",
    "This document says where the development of the project stands outside OrchesTwin Studio: "
    "the approved versions the code is expected to implement, the commits recorded in the "
    "Studio, the critiques of the user twins, the decisions of the owner and the tasks for the "
    "code. The exact records are in `state/state.json` and `twins/feedback/changes.json`; the "
    "diff of a commit is never copied into the folder.",
    "",
    "`ut push` sends the hand-made changes of this folder to the Studio: you approve the "
    "differences and a new version is born.",
    "",
    "## Reference",
    "",
    "- Requirements: version 2 (`requirements/requirements.md`).",
    "- Design: version 4, alternative DES-002 (`design/design.md`).",
    "",
    "## Aligned point",
    "",
    "Commit `9d8e7f6`, decided on 2026-09-28 10:00+00:00, with requirements version 2 and design "
    "version 4.",
    "",
    "## Changes after the aligned point",
    "",
    "The Studio has recorded 2 changes; 1 is waiting after the aligned point.",
    "",
    "- `4f2a9c1` of 2026-09-28 11:00+00:00: Controllo del nome vuoto. Verdict: the code departs "
    "from the approved requirements or design (CODE_DRIFT). Decision: tasks for the code were "
    "recorded (CODE_TASKS).",
    "",
    "## Open tasks",
    "",
    "- TSK-001: Mostrare il messaggio di errore accanto al campo del nome (requirements REQ-003; "
    "screens SCR-002; from the decision on commit `4f2a9c1`).",
    "",
    "## Closed tasks",
    "",
    "No task has been closed yet.",
    "",
    "## Latest critiques of the twins",
    "",
    "Commit `4f2a9c1`, reviewed on 2026-09-28 11:30+00:00. Verdict: the code departs from the "
    "approved requirements or design (CODE_DRIFT). Il controllo del nome vuoto non segue il "
    "requisito REQ-003.",
    "",
    "Tasks proposed for the code: Mostrare il messaggio di errore accanto al campo del nome.",
    "",
    "### Addetti all'accoglienza: the change raises a concern (CONCERN)",
    "",
    "Il messaggio per il nome vuoto compare solo dopo il salvataggio.",
    "",
    "- Importance medium (MEDIUM): Il campo del nome non spiega che cosa manca. About: REQ-003, "
    "SCR-002, src/app.js. Suggested action: Mostrare il messaggio accanto al campo del nome.",
    "- Importance low (LOW): Il pulsante di conferma è piccolo sul tablet. About: SCR-002.",
    "",
    "### Organizzatori volontari: the change is fine (FINE)",
    "",
    "La lista si aggiorna subito e resta leggibile.",
    "",
    "- Importance low (LOW): Il numero progressivo potrebbe essere più evidente. About: REQ-002, "
    "SCR-001. Suggested action: Rendere il numero in grassetto.",
    "",
    "## Acceptance tests",
    "",
    "The latest run of the acceptance tests, finished on 2026-09-29 10:05+00:00, checked the "
    "static folder `dist` in Chrome 151.0.7922.76 and Firefox 156.0.1. Criteria: 1 passed, "
    "1 failed, 0 blocked, 1 not covered, 0 not run. The review of the twins on "
    "2026-09-29 10:20+00:00 leaves 2 open critiques. `twins/feedback/tests.json` holds 1 run of "
    "the acceptance tests with the steps, the evidence and the critiques of the twins.",
    "",
    "## What the twins learned",
    "",
    "Observations learned by the twins during the development: Addetti all'accoglienza, version "
    "1.0, no observation; Organizzatori volontari, version 1.0, no observation. "
    "`twins/feedback/learned.json` holds them with where each comes from; `ut twins update` "
    "proposes new ones.",
    "",
)
DEVELOPMENT_ITALIAN = (
    "## Modifiche dopo il punto allineato",
    "",
    "Lo Studio ha registrato 3 modifiche; 2 sono in attesa dopo il punto allineato.",
    "",
    "- `4f2a9c1` del 2026-09-28 11:00+00:00: Controllo del nome vuoto. Verdetto: il codice si "
    "allontana dai requisiti o dal design approvati (CODE_DRIFT). Decisione: sono stati "
    "registrati compiti per il codice (CODE_TASKS).",
    "- `7c3e1a9` del 2026-09-28 10:20+00:00: Filtro della lista per tavolo. Verdetto: il design "
    "va aggiornato con una nuova versione (DESIGN_OUTDATED). Decisione: è stata chiesta una "
    "nuova versione del design (DESIGN_CHANGE). Da riesaminare: rivisto con i requisiti alla "
    "versione 2 e il design alla versione 3, alternativa DES-002.",
    "",
    "1 revisione è stata fatta con versioni precedenti dei requisiti o del design: "
    "`ut verify --recheck` fa riesaminare quel commit ai twin.",
    "",
    "## Compiti aperti",
    "",
    "- TSK-001: Mostrare il messaggio di errore accanto al campo del nome (requisiti REQ-003; "
    "schermate SCR-002; dalla decisione sul commit `4f2a9c1`).",
    "- TSK-002: Ingrandire il pulsante di conferma sul tablet (requisiti nessuno; schermate "
    "SCR-002; da un rilievo del twin Addetti all'accoglienza sul commit `4f2a9c1`).",
    "- TSK-003: Mostrare un messaggio accanto al campo del nome (requisiti REQ-003; schermate "
    "SCR-002; criteri AC-002; da un rilievo del twin Addetti all'accoglienza sulla verifica dei "
    "criteri).",
    "- TSK-004: Aggiungere il logo del workshop in alto (requisiti nessuno; schermate SCR-001; "
    "scritto dal proprietario).",
    "",
    "## Compiti chiusi",
    "",
    "Fatti:",
    "",
    "- TSK-005: Scrivere il titolo della pagina in italiano (scritto dal proprietario; fatto il "
    "2026-09-29 12:00+00:00).",
    "",
    "Abbandonati:",
    "",
    "- TSK-006: Provare la lista sul tablet (da un rilievo del twin Addetti all'accoglienza sulla "
    "verifica dei criteri; abbandonato il 2026-09-29 12:30+00:00; nota: La prova sul tablet la "
    "fa una persona).",
    "",
    "## Ultime critiche dei twin",
)
DEVELOPMENT_ENGLISH = (
    "## Changes after the aligned point",
    "",
    "The Studio has recorded 3 changes; 2 are waiting after the aligned point.",
    "",
    "- `4f2a9c1` of 2026-09-28 11:00+00:00: Controllo del nome vuoto. Verdict: the code departs "
    "from the approved requirements or design (CODE_DRIFT). Decision: tasks for the code were "
    "recorded (CODE_TASKS).",
    "- `7c3e1a9` of 2026-09-28 10:20+00:00: Filtro della lista per tavolo. Verdict: the design "
    "should get a new version (DESIGN_OUTDATED). Decision: a new design version was requested "
    "(DESIGN_CHANGE). To re-review: reviewed against requirements version 2 and design version "
    "3, alternative DES-002.",
    "",
    "1 review was made against earlier versions of the requirements or of the design: "
    "`ut verify --recheck` has the twins review that commit again.",
    "",
    "## Open tasks",
    "",
    "- TSK-001: Mostrare il messaggio di errore accanto al campo del nome (requirements REQ-003; "
    "screens SCR-002; from the decision on commit `4f2a9c1`).",
    "- TSK-002: Ingrandire il pulsante di conferma sul tablet (requirements none; screens "
    "SCR-002; from a finding of the twin Addetti all'accoglienza on commit `4f2a9c1`).",
    "- TSK-003: Mostrare un messaggio accanto al campo del nome (requirements REQ-003; screens "
    "SCR-002; criteria AC-002; from a finding of the twin Addetti all'accoglienza on the "
    "acceptance tests).",
    "- TSK-004: Aggiungere il logo del workshop in alto (requirements none; screens SCR-001; "
    "written by the owner).",
    "",
    "## Closed tasks",
    "",
    "Done:",
    "",
    "- TSK-005: Scrivere il titolo della pagina in italiano (written by the owner; done on "
    "2026-09-29 12:00+00:00).",
    "",
    "Dropped:",
    "",
    "- TSK-006: Provare la lista sul tablet (from a finding of the twin Addetti all'accoglienza "
    "on the acceptance tests; dropped on 2026-09-29 12:30+00:00; note: La prova sul tablet la fa "
    "una persona).",
    "",
    "## Latest critiques of the twins",
)
LEARNED_PARAGRAPH = {
    "it": (
        "## Cosa hanno imparato i twin\n\nOsservazioni apprese dai twin durante lo sviluppo: "
        "Addetti all'accoglienza, versione 1.3, 2 osservazioni; Organizzatori volontari, versione "
        "1.0, nessuna osservazione. `twins/feedback/learned.json` le contiene con la loro origine; "
        "`ut twins update` ne propone di nuove.\n"
    ),
    "en": (
        "## What the twins learned\n\nObservations learned by the twins during the development: "
        "Addetti all'accoglienza, version 1.3, 2 observations; Organizzatori volontari, version "
        "1.0, no observation. `twins/feedback/learned.json` holds them with where each comes "
        "from; `ut twins update` proposes new ones.\n"
    ),
}
INDEX_DEVELOPMENT = (
    "## Development state",
    "",
    "The Studio has recorded 3 changes (commits) of the code. The aligned point is commit "
    "`9d8e7f6`, decided on 2026-09-28 10:00+00:00. 2 changes are waiting after the aligned "
    "point. 1 review was made against earlier versions of the requirements or of the design: "
    "`ut verify --recheck` has the twins review that commit again. 4 tasks are open for the "
    "code. "
    "`state/state.md` explains the state in the language of the project; `state/state.json` and "
    "`twins/feedback/changes.json` hold the exact records.",
    "",
    "The open tasks and where each comes from:",
    "",
    "- TSK-001: Mostrare il messaggio di errore accanto al campo del nome (from the decision on "
    "commit `4f2a9c1`).",
    "- TSK-002: Ingrandire il pulsante di conferma sul tablet (from a finding of the twin "
    "Addetti all'accoglienza on commit `4f2a9c1`).",
    "- TSK-003: Mostrare un messaggio accanto al campo del nome (from a finding of the twin "
    "Addetti all'accoglienza on the acceptance tests).",
    "- TSK-004: Aggiungere il logo del workshop in alto (written by the owner).",
    "",
    "## Latest critiques on the code",
)
INDEX_LEARNING = (
    "## What the twins learned",
    "",
    "- Addetti all'accoglienza, version 1.3:",
    "  - OBS-001: Gli addetti lavorano in piedi e tengono il tablet con una mano sola.",
    "  - OBS-003: Gli addetti leggono la lista da due metri, mentre accolgono gli ospiti.",
    "- Organizzatori volontari, version 1.0: it has learned nothing yet.",
    "",
    "`twins/feedback/learned.json` holds what the twins learned during the development, with "
    "where every observation comes from; `ut twins update` proposes new ones from their latest "
    "critiques.",
    "",
    "## Schema",
)
INDEX_SECTION = (
    "## Acceptance tests",
    "",
    "The latest run of the acceptance tests, finished on 2026-09-29 10:05+00:00, checked the "
    "static folder `dist` in Chrome 151.0.7922.76 and Firefox 156.0.1. Criteria: 1 passed, "
    "1 failed, 0 blocked, 1 not covered, 0 not run.",
    "",
    "Criteria that failed or were blocked:",
    "",
    "- AC-002 failed: Rifiutare un nome vuoto con un messaggio accanto al campo (path TP-002).",
    "",
    "The review of the twins on 2026-09-29 10:20+00:00 leaves 2 open critiques. "
    "`twins/feedback/tests.json` holds 1 run of the acceptance tests with the steps, the "
    "evidence and the critiques of the twins. `ut test` runs the tests again.",
    "",
)
PUSH_LINE = {
    "en": (
        "`ut push` sends the hand-made changes of this folder to the Studio: you approve the "
        "differences and a new version is born."
    ),
    "it": (
        "`ut push` invia allo Studio le modifiche fatte a mano in questa cartella: le "
        "differenze si approvano e nasce una versione nuova."
    ),
}
NO_RUN = {
    "en": (
        "No run of the acceptance tests is recorded yet: `ut test` runs them on the application "
        "and records the result in the Studio."
    ),
    "it": (
        "Nessuna verifica dei criteri è stata ancora registrata: `ut test` la esegue "
        "sull'applicazione e ne registra il risultato nello Studio."
    ),
}


def state_folder(state: ProjectStateSources | None = None) -> KnowledgeFolder:
    return build_knowledge_folder(
        real_sources(state=state_sources() if state is None else state),
        version_number=1,
        created_at=PUBLISHED_AT,
    )


def development_folder() -> KnowledgeFolder:
    return state_folder(development_sources())


def with_review(change: dict[str, object], **review: object) -> dict[str, object]:
    return {**change, "review": {**change["review"], **review}}


def assert_keys(value: object, tree: object, path: str) -> None:
    if isinstance(tree, dict):
        if value is None:
            return
        assert isinstance(value, dict), path
        assert set(value) == set(tree), path
        for key, inner in tree.items():
            assert_keys(value[key], inner, f"{path}.{key}")
    elif isinstance(tree, list):
        assert isinstance(value, list), path
        for index, item in enumerate(value):
            assert_keys(item, tree[0], f"{path}[{index}]")


def published_schema(folder: KnowledgeFolder, name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads(folder.files[schema_document(name)]))


def test_the_four_documents_have_exactly_the_keys_of_the_contract() -> None:
    folder = development_folder()
    state = json.loads(folder.files[STATE_DOCUMENT])
    changes = json.loads(folder.files[FEEDBACK_CHANGES])
    tests = json.loads(folder.files[FEEDBACK_TESTS])
    learned = json.loads(folder.files[FEEDBACK_LEARNING])

    assert_keys(state, STATE_KEYS, "state")
    assert_keys(changes, CHANGES_KEYS, "changes")
    assert_keys(tests, TESTS_KEYS, "tests")
    assert_keys(learned, LEARNED_KEYS, "learned")
    assert state["aligned"] is not None
    assert [change["commit"] for change in state["changes"]] == [
        PENDING_COMMIT,
        STALE_COMMIT,
        ALIGNED_COMMIT,
    ]
    assert [change["review"] is None for change in state["changes"]] == [False, False, True]
    assert [change["review"]["reference"] for change in state["changes"][:2]] == [
        CURRENT_REFERENCE,
        EARLIER_REFERENCE,
    ]
    assert all(change["decision"] is not None for change in state["changes"])
    assert all(value is not None for value in state["reference"].values())
    assert {task["origin"]["kind"] for task in state["tasks"]} == {
        "CODE_CHANGE",
        "TEST_RUN",
        "OWNER",
    }
    assert {task["status"] for task in state["tasks"]} == {"OPEN", "DONE", "DROPPED"}
    assert changes["runs"][0]["critiques"][0]["findings"]
    run = tests["runs"][0]
    assert [result["browser"] for result in run["results"]] == ["chrome", "firefox"]
    assert run["results"][0]["path"]["steps"][2]["expect"]["kind"] == "TEXT_VISIBLE"
    assert run["critiques"][0]["findings"][0]["about"]["criterion"] == "AC-002"
    assert [len(twin["observations"]) for twin in learned["twins"]] == [2, 0]
    assert [len(twin["retired"]) for twin in learned["twins"]] == [1, 0]


@pytest.mark.parametrize("state", [state_sources(), development_sources(), ProjectStateSources()])
def test_the_four_documents_validate_against_their_published_schemas(
    state: ProjectStateSources,
) -> None:
    folder = state_folder(state)

    for path, name in (
        (STATE_DOCUMENT, "state"),
        (FEEDBACK_CHANGES, "changes"),
        (FEEDBACK_TESTS, "tests"),
        (FEEDBACK_LEARNING, "learning"),
    ):
        payload = json.loads(folder.files[path])
        errors = [error.message for error in published_schema(folder, name).iter_errors(payload)]
        assert errors == [], path
        validate_document(name, payload)
    validate_files(folder.files)


def test_the_state_document_copies_the_sources_and_reads_the_reference_from_the_stages() -> None:
    package = real_sources(state=state_sources())

    document = state_document(package)

    assert document["schema_version"] == 3
    assert document["kind"] == "orchestwin.project-state"
    assert document["project_id"] == str(REAL_PROJECT_ID)
    assert document["reference"] == {
        "requirements": {
            "version_id": str(package.requirements.id),
            "version_number": 2,
            "content_hash": package.requirements.content_hash,
        },
        "design": {
            "version_id": str(package.design.id),
            "version_number": 4,
            "content_hash": package.design.content_hash,
            "alternative_code": "DES-002",
        },
    }
    assert document["aligned"] == dict(state_sources().aligned)
    assert document["changes"] == [
        with_review(dict(state_sources().changes[0]), reference=None, stale=False),
        dict(state_sources().changes[1]),
    ]
    assert document["tasks"] == [older_task()]


def older_task() -> dict[str, object]:
    task = dict(state_sources().tasks[0])
    return {
        "code": task["code"],
        "text": task["text"],
        "about": {**task["about"], "criteria": []},
        "origin": {
            "kind": "CODE_CHANGE",
            "commit": PENDING_COMMIT,
            "test_run_id": None,
            "twin_id": None,
            "twin_name": None,
            "finding": None,
        },
        "from_commit": PENDING_COMMIT,
        "created_at": task["created_at"],
        "status": "OPEN",
        "closed_at": None,
        "note": None,
    }


def test_the_state_document_copies_the_tasks_and_the_references_of_the_new_sources() -> None:
    document = state_document(real_sources(state=development_sources()))
    pending, stale, aligned = development_sources().changes

    assert document["changes"] == [
        with_review(dict(pending), stale=False),
        with_review(dict(stale), stale=True),
        dict(aligned),
    ]
    assert document["tasks"] == [older_task(), *development_tasks()[1:]]
    assert [list(task) for task in document["tasks"]] == [
        [
            "code",
            "text",
            "about",
            "origin",
            "from_commit",
            "created_at",
            "status",
            "closed_at",
            "note",
        ]
    ] * 6
    assert list(document["changes"][0]["review"]) == [
        "run_id",
        "reviewed_at",
        "verdict",
        "summary",
        "reference",
        "stale",
    ]


@pytest.mark.parametrize(
    ("change", "written"),
    [
        ({}, {"criteria": [], "closed_at": None, "note": None}),
        ({"origin": None}, {"criteria": [], "closed_at": None, "note": None}),
        (
            {"about": {"requirements": [], "screens": [], "criteria": None}},
            {"criteria": [], "closed_at": None, "note": None},
        ),
        (
            {"status": "DONE", "closed_at": "2026-09-29T09:00:00+00:00", "note": "Fatto."},
            {"criteria": [], "closed_at": "2026-09-29T09:00:00+00:00", "note": "Fatto."},
        ),
    ],
)
def test_a_task_written_by_older_code_gets_the_whole_shape(
    change: dict[str, object], written: dict[str, object]
) -> None:
    task = {**state_sources().tasks[0], **change}
    state = ProjectStateSources(tasks=(task,))

    stored = state_document(real_sources(state=state))["tasks"][0]

    assert stored["origin"] == older_task()["origin"]
    assert stored["about"]["criteria"] == written["criteria"]
    assert (stored["closed_at"], stored["note"]) == (written["closed_at"], written["note"])
    validate_files(state_folder(state).files)


def test_a_task_keeps_its_origin_and_writes_identifiers_as_text() -> None:
    task = {
        **development_tasks()[2],
        "origin": {**development_tasks()[2]["origin"], "test_run_id": UUID(TEST_RUN)},
        "created_at": datetime(2026, 9, 29, 10, 30, tzinfo=UTC),
        "number": 3,
    }

    stored = state_document(real_sources(state=ProjectStateSources(tasks=(task,))))["tasks"][0]

    assert stored == development_tasks()[2]
    assert stored["origin"]["test_run_id"] == TEST_RUN


def test_the_change_reviews_document_holds_the_runs_as_given() -> None:
    document = change_reviews_document(real_sources(state=state_sources()))

    assert document == {
        "schema_version": 3,
        "kind": "orchestwin.change-reviews",
        "project_id": str(REAL_PROJECT_ID),
        "runs": [change_run()],
    }


def test_an_empty_state_writes_empty_documents() -> None:
    package = real_sources()

    assert state_document(package)["aligned"] is None
    assert state_document(package)["changes"] == []
    assert state_document(package)["tasks"] == []
    assert change_reviews_document(package)["runs"] == []
    assert state_documents.test_reviews_document(package) == {
        "schema_version": 3,
        "kind": "orchestwin.test-reviews",
        "project_id": str(REAL_PROJECT_ID),
        "runs": [],
    }


def test_the_test_reviews_document_holds_the_runs_as_given() -> None:
    document = state_documents.test_reviews_document(real_sources(state=state_sources()))

    assert document == {
        "schema_version": 3,
        "kind": "orchestwin.test-reviews",
        "project_id": str(REAL_PROJECT_ID),
        "runs": [acceptance_run()],
    }
    assert FEEDBACK_TESTS == "twins/feedback/tests.json"
    assert FEEDBACK_TESTS is shared_state.FEEDBACK_TESTS


def test_the_test_runs_keep_only_the_keys_of_the_contract_written_as_text() -> None:
    run = {
        **acceptance_run(),
        "id": UUID(TEST_RUN),
        "plan_id": "00000000-0000-4000-8000-00000000e201",
        "finished_at": datetime(2026, 9, 29, 10, 5, tzinfo=UTC),
        "results": [
            {**result, "screenshots": ["01.png"]} for result in acceptance_run()["results"]
        ],
    }
    folder = state_folder(state=ProjectStateSources(tests=(run,)))

    stored = json.loads(folder.files[FEEDBACK_TESTS])["runs"][0]

    assert stored == acceptance_run()
    assert "plan_id" not in folder.files[FEEDBACK_TESTS]
    validate_files(folder.files)


def test_the_folder_keeps_at_most_the_newest_test_runs() -> None:
    runs = tuple(
        {**acceptance_run(), "id": f"00000000-0000-4000-8000-{number:012d}"}
        for number in range(MAX_FOLDER_TEST_RUNS + 3)
    )
    package = real_sources(state=ProjectStateSources(tests=runs))

    folder = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)
    stored = json.loads(folder.files[FEEDBACK_TESTS])["runs"]

    assert acceptance_runs(package) == runs[:MAX_FOLDER_TEST_RUNS]
    assert [run["id"] for run in stored] == [run["id"] for run in runs[:MAX_FOLDER_TEST_RUNS]]
    assert folder.manifest["feedback"]["test_runs"] == MAX_FOLDER_TEST_RUNS
    validate_files(folder.files)


@pytest.mark.parametrize(
    ("through", "requirements", "design"),
    [("brief", False, False), ("twins", False, False), ("requirements", True, False)],
)
def test_the_reference_holds_only_the_approved_stages(
    through: str, requirements: bool, design: bool
) -> None:
    reference = development_reference(partial_sources(through))

    assert (reference["requirements"] is not None) is requirements
    assert (reference["design"] is not None) is design


def test_the_alternative_code_is_the_one_the_owner_selected() -> None:
    package = real_sources().payload("design")

    assert selected_alternative_code(package) == "DES-002"
    assert selected_alternative_code({**package, "owner_selected_alternative_id": None}) is None
    assert selected_alternative_code({**package, "owner_selected_alternative_id": "x"}) is None


def test_a_change_without_its_review_takes_the_latest_run_of_its_commit() -> None:
    newer = change_run()
    older = {
        **change_run(),
        "id": "00000000-0000-4000-8000-00000000d000",
        "reviewed_at": "2026-09-28T11:10:00+00:00",
        "alignment": {**change_run()["alignment"], "status": "ALIGNED", "summary": "Allineato."},
    }
    change = {key: value for key, value in state_sources().changes[0].items() if key != "review"}
    state = ProjectStateSources(changes=(change,), runs=(newer, older))

    document = state_document(real_sources(state=state))

    assert document["changes"][0]["review"] == {
        "run_id": CHANGE_RUN,
        "reviewed_at": "2026-09-28T11:30:00+00:00",
        "verdict": "CODE_DRIFT",
        "summary": "Il controllo del nome vuoto non segue il requisito REQ-003.",
        "reference": CURRENT_REFERENCE,
        "stale": False,
    }
    unreviewed = ProjectStateSources(changes=(change,), runs=())
    assert state_document(real_sources(state=unreviewed))["changes"][0]["review"] is None


def test_a_change_without_its_review_is_stale_when_its_latest_run_is() -> None:
    earlier = {**change_run(), "reference": dict(EARLIER_REFERENCE)}
    change = {key: value for key, value in state_sources().changes[0].items() if key != "review"}
    state = ProjectStateSources(changes=(change,), runs=(earlier,))

    review = state_document(real_sources(state=state))["changes"][0]["review"]

    assert (review["reference"], review["stale"]) == (EARLIER_REFERENCE, True)
    assert stale_reviews(real_sources(state=state)) == 1


def test_the_diff_and_other_keys_never_reach_the_folder() -> None:
    change = {
        **state_sources().changes[0],
        "diff": "diff --git a/src/app.js b/src/app.js",
        "id": "00000000-0000-4000-8000-00000000c001",
        "message": "x" * (MAX_MESSAGE_LENGTH + 50),
        "committed_at": datetime(2026, 9, 28, 11, 0, tzinfo=UTC),
    }
    run = {**change_run(), "generation_ids": ["one"], "id": UUID(CHANGE_RUN)}
    state = ProjectStateSources(changes=(change,), runs=(run,))
    folder = state_folder(state=state)

    recorded = json.loads(folder.files[STATE_DOCUMENT])["changes"][0]
    stored = json.loads(folder.files[FEEDBACK_CHANGES])["runs"][0]

    assert "diff" not in recorded and "id" not in recorded
    assert "diff --git" not in "".join(folder.files.values())
    assert recorded["message"] == "x" * MAX_MESSAGE_LENGTH
    assert recorded["committed_at"] == "2026-09-28T11:00:00+00:00"
    assert "generation_ids" not in stored
    assert stored["id"] == CHANGE_RUN
    validate_files(folder.files)


def test_the_manifest_summarises_the_development_state() -> None:
    manifest = state_folder().manifest

    assert manifest["state"] == {
        "document": STATE_DOCUMENT,
        "text": STATE_TEXT,
        "changes": 2,
        "pending_changes": 1,
        "stale_reviews": 0,
        "aligned_commit": ALIGNED_COMMIT,
        "open_tasks": 1,
    }
    assert manifest["feedback"]["changes"] == FEEDBACK_CHANGES
    assert manifest["feedback"]["change_reviews"] == 1
    assert manifest["feedback"]["tests"] == FEEDBACK_TESTS
    assert manifest["feedback"]["test_runs"] == 1
    assert manifest["feedback"]["learned"] == FEEDBACK_LEARNING
    assert manifest["feedback"]["learned_observations"] == 0


def test_the_manifest_counts_the_stale_reviews_and_the_learned_observations() -> None:
    manifest = development_folder().manifest

    assert manifest["state"] == {
        "document": STATE_DOCUMENT,
        "text": STATE_TEXT,
        "changes": 3,
        "pending_changes": 2,
        "stale_reviews": 1,
        "aligned_commit": ALIGNED_COMMIT,
        "open_tasks": 4,
    }
    assert list(manifest["state"])[3:5] == ["pending_changes", "stale_reviews"]
    assert manifest["feedback"]["learned"] == FEEDBACK_LEARNING
    assert manifest["feedback"]["learned_observations"] == 2
    assert list(manifest["feedback"])[-2:] == ["learned", "learned_observations"]


def test_a_folder_without_test_runs_still_announces_the_empty_document() -> None:
    folder = state_folder(state=replace(state_sources(), tests=()))

    assert json.loads(folder.files[FEEDBACK_TESTS])["runs"] == []
    assert folder.manifest["feedback"]["tests"] == FEEDBACK_TESTS
    assert folder.manifest["feedback"]["test_runs"] == 0
    assert (
        f"## Verifica dei criteri\n\n{NO_RUN['it']}\n\n## Cosa hanno imparato i twin\n"
        in folder.files[STATE_TEXT]
    )
    assert f"## Acceptance tests\n\n{NO_RUN['en']}\n" in folder.files[KNOWLEDGE_INDEX]
    assert "Verifica dei criteri" not in folder.files[KNOWLEDGE_INDEX]
    validate_files(folder.files)


def test_without_an_aligned_point_every_change_is_pending() -> None:
    state = replace(state_sources(), aligned=None)
    manifest = state_folder(state=state).manifest

    assert manifest["state"]["pending_changes"] == 2
    assert manifest["state"]["aligned_commit"] is None


def test_the_state_text_is_written_in_italian_for_an_italian_project() -> None:
    folder = state_folder()

    assert folder.manifest["project"]["language"] == "it"
    assert folder.files[STATE_TEXT] == "\n".join(ITALIAN_TEXT)


@pytest.mark.parametrize("language", ["en", None, "fr", "EN-us"])
def test_the_state_text_is_written_in_english_otherwise(language: str | None) -> None:
    text = state_markdown(real_sources(state=state_sources()), language=language)

    assert text == "\n".join(ENGLISH_TEXT)


@pytest.mark.parametrize(
    ("language", "heading"), [("it", "## Riferimento"), ("en", "## Reference")]
)
def test_the_state_text_says_after_its_intro_how_hand_made_changes_reach_the_studio(
    language: str, heading: str
) -> None:
    for text in (
        state_markdown(real_sources(state=development_sources()), language=language),
        state_markdown(partial_sources("brief"), language=language),
    ):
        lines = text.splitlines()

        assert lines[3:7] == ["", PUSH_LINE[language], "", heading]
        assert lines.count(PUSH_LINE[language]) == 1
    assert PUSH_LINE["en"] not in state_markdown(partial_sources("brief"), language="it")
    assert PUSH_LINE["it"] not in state_markdown(partial_sources("brief"), language="en")


@pytest.mark.parametrize(("language", "words"), [("it", "it"), ("it-IT", "it"), ("IT", "it")])
def test_every_italian_language_code_gives_italian(language: str, words: str) -> None:
    assert state_language(language) == words
    assert state_language(None) == "en"


def test_an_empty_state_says_that_nothing_happened_yet() -> None:
    italian = state_markdown(partial_sources("brief"), language="it")
    english = state_markdown(partial_sources("brief"), language="en")

    for line in (
        "- Requisiti: non ancora approvati.",
        "- Design: non ancora approvato.",
        "Nessun commit è stato ancora dichiarato allineato.",
        "Lo Studio non ha ancora registrato nessuna modifica (commit) del codice.",
        "Non c'è nessun compito aperto per il codice.",
        "Nessun commit è stato ancora rivisto.",
    ):
        assert line in italian.splitlines()
    for line in (
        "- Requirements: not approved yet.",
        "- Design: not approved yet.",
        "No commit has been decided aligned yet.",
        "The Studio has recorded no change (commit) of the code yet.",
        "There is no open task for the code.",
        "No commit has been reviewed yet.",
    ):
        assert line in english.splitlines()


def test_a_change_after_the_aligned_point_without_review_or_decision_says_so() -> None:
    change = {
        **state_sources().changes[0],
        "commit": "a" * 40,
        "message": "  Nuova schermata  \nDettagli",
        "review": None,
        "decision": None,
    }
    state = replace(state_sources(), changes=(change, *state_sources().changes))

    text = state_markdown(real_sources(state=state), language="en")

    assert "The Studio has recorded 3 changes; 2 are waiting after the aligned point." in text
    assert (
        "- `aaaaaaa` of 2026-09-28 11:00+00:00: Nuova schermata. Verdict: not reviewed yet. "
        "Decision: no decision yet."
    ) in text


def test_changes_that_are_all_aligned_leave_nothing_waiting() -> None:
    state = replace(
        state_sources(),
        aligned={**state_sources().aligned, "commit": PENDING_COMMIT},
    )

    text = state_markdown(real_sources(state=state), language="it")

    assert "Lo Studio ha registrato 2 modifiche; nessuna è in attesa dopo il punto allineato." in (
        text
    )
    assert "- `4f2a9c1`" not in text


def test_a_partial_folder_keeps_the_critiques_in_the_state_text_only() -> None:
    folder = build_knowledge_folder(
        partial_sources("requirements", state=state_sources()),
        version_number=1,
        created_at=PUBLISHED_AT,
    )

    assert "twins/feedback/feedback.md" not in folder.files
    assert (
        "### Addetti all'accoglienza: la modifica solleva un dubbio (CONCERN)"
        in (folder.files[STATE_TEXT])
    )
    assert "- Design: non ancora approvato." in folder.files[STATE_TEXT]
    validate_files(folder.files)


def test_the_index_summarises_the_development_and_the_latest_critiques() -> None:
    index = state_folder().files[KNOWLEDGE_INDEX]

    assert (
        "The Studio has recorded 2 changes (commits) of the code. The aligned point is commit "
        "`9d8e7f6`, decided on 2026-09-28 10:00+00:00. 1 change is waiting after the aligned "
        "point. 1 task is open for the code. `state/state.md` explains the state in the language "
        "of the project; `state/state.json` and `twins/feedback/changes.json` hold the exact "
        "records."
    ) in index
    assert (
        "## Latest critiques on the code\n\n"
        "Commit `4f2a9c1`, reviewed on 2026-09-28 11:30+00:00: the code departs from the "
        "approved requirements or design (CODE_DRIFT).\n\n"
        "- Addetti all'accoglienza: the change raises a concern (CONCERN). Il messaggio per il "
        "nome vuoto compare solo dopo il salvataggio.\n"
        "- Organizzatori volontari: the change is fine (FINE). La lista si aggiorna subito e "
        "resta leggibile.\n"
    ) in index
    assert "`twins/feedback/changes.json` holds 1 review run of the twins" in index


def test_the_state_changes_the_content_hash_of_the_folder() -> None:
    plain = build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT)

    assert state_folder().content_hash != plain.content_hash


def test_the_index_summarises_the_latest_test_run_in_english_for_every_project() -> None:
    folder = state_folder()
    index = folder.files[KNOWLEDGE_INDEX]
    english = state_documents.test_lines(sources(state=state_sources()))

    assert folder.manifest["project"]["language"] == "it"
    assert "\n".join(INDEX_SECTION) in index
    assert index.index("## Latest critiques on the code") < index.index("## Acceptance tests")
    assert index.index("## Acceptance tests") < index.index("## Schema")
    assert "Verifica dei criteri" not in index
    assert english == list(INDEX_SECTION)


def test_without_test_runs_the_index_says_how_to_run_them() -> None:
    expected = ["## Acceptance tests", "", NO_RUN["en"], ""]

    assert state_documents.test_lines(sources()) == expected
    assert state_documents.test_lines(partial_sources("brief")) == expected


def stopped_run() -> dict[str, object]:
    run = acceptance_run()
    blocked = {
        **run["results"][1],
        "path": {
            **run["results"][1]["path"],
            "code": "TP-003",
            "heading": "Filtrare la lista per tavolo.",
            "criteria": ["AC-004"],
        },
        "status": "BLOCKED",
    }
    return {
        **run,
        "summary": {"passed": 1, "failed": 1, "blocked": 2, "not_covered": 1, "not_run": 0},
        "criteria": [
            *run["criteria"],
            {"code": "AC-004", "status": "BLOCKED", "paths": ["TP-003", "TP-002"]},
            {"code": "AC-005", "status": "BLOCKED", "paths": []},
        ],
        "results": [*run["results"], blocked, {**blocked, "browser": "chrome"}],
    }


def test_the_index_lists_every_failed_or_blocked_criterion_with_its_first_path() -> None:
    state = ProjectStateSources(tests=(stopped_run(),))

    english = state_documents.test_lines(sources(state=state))
    italian = state_markdown(real_sources(state=state), language="it")

    assert english[6:10] == [
        "- AC-002 failed: Rifiutare un nome vuoto con un messaggio accanto al campo (path TP-002).",
        "- AC-004 blocked: Filtrare la lista per tavolo (path TP-003).",
        "- AC-005 blocked.",
        "",
    ]
    assert state_documents.test_lines(real_sources(state=state)) == english
    assert english[2].endswith("Criteria: 1 passed, 1 failed, 2 blocked, 1 not covered, 0 not run.")
    assert "Criteri: 1 superato, 1 fallito, 2 bloccati, 1 non coperto, 0 non eseguiti." in italian


def test_the_index_says_when_nothing_failed_and_the_twins_did_not_review_yet() -> None:
    run = {
        **acceptance_run(),
        "summary": {"passed": 2, "failed": 0, "blocked": 0, "not_covered": 1, "not_run": 0},
        "criteria": [
            {"code": "AC-001", "status": "PASSED", "paths": ["TP-001"]},
            {"code": "AC-002", "status": "PASSED", "paths": ["TP-002"]},
        ],
        "critiques": [],
        "reviewed_at": None,
    }
    state = ProjectStateSources(tests=(run,))

    english = state_documents.test_lines(sources(state=state))
    text = state_markdown(real_sources(state=state), language="it")

    assert english[4:7] == [
        "No criterion failed or was blocked.",
        "",
        "The twins have not reviewed this run yet. `twins/feedback/tests.json` holds 1 run of the "
        "acceptance tests with the steps, the evidence and the critiques of the twins. `ut test` "
        "runs the tests again.",
    ]
    assert state_documents.test_lines(real_sources(state=state)) == english
    assert "Criteri: 2 superati, 0 falliti, 0 bloccati, 1 non coperto, 0 non eseguiti." in text
    assert "I twin non hanno ancora criticato questa verifica." in text


def test_the_sentences_name_an_address_and_use_the_singular_forms() -> None:
    run = {
        **acceptance_run(),
        "application": {"kind": "URL", "address": "https://ospiti.example.org/lista"},
        "browsers": [{"name": "firefox", "version": "156.0.1"}],
        "summary": {"passed": 1, "failed": 1, "blocked": 1, "not_covered": 1, "not_run": 1},
        "critiques": [acceptance_run()["critiques"][1], acceptance_run()["critiques"][0]],
    }
    run["critiques"][1] = {**run["critiques"][1], "findings": run["critiques"][1]["findings"][:1]}
    older = {**acceptance_run(), "id": "00000000-0000-4000-8000-00000000e100"}
    state = ProjectStateSources(tests=(run, older))

    english = state_markdown(real_sources(state=state), language="en")
    italian = state_markdown(real_sources(state=state), language="it")

    assert (
        "The latest run of the acceptance tests, finished on 2026-09-29 10:05+00:00, checked the "
        "address `https://ospiti.example.org/lista` in Firefox 156.0.1. Criteria: 1 passed, "
        "1 failed, 1 blocked, 1 not covered, 1 not run. The review of the twins on "
        "2026-09-29 10:20+00:00 leaves 1 open critique. `twins/feedback/tests.json` holds 2 runs "
        "of the acceptance tests with the steps, the evidence and the critiques of the twins."
    ) in english
    assert (
        "L'ultima verifica dei criteri, conclusa il 2026-09-29 10:05+00:00, ha provato "
        "l'indirizzo `https://ospiti.example.org/lista` in Firefox 156.0.1. Criteri: 1 superato, "
        "1 fallito, 1 bloccato, 1 non coperto, 1 non eseguito. La revisione dei twin del "
        "2026-09-29 10:20+00:00 lascia 1 critica aperta. `twins/feedback/tests.json` contiene "
        "2 verifiche dei criteri con i passi, le prove e le critiche dei twin."
    ) in italian


def test_a_review_without_findings_leaves_no_open_critique() -> None:
    run = {
        **acceptance_run(),
        "critiques": [{**critique, "findings": []} for critique in acceptance_run()["critiques"]],
    }
    state = ProjectStateSources(tests=(run,))

    english = state_markdown(real_sources(state=state), language="en")
    italian = state_markdown(real_sources(state=state), language="it")

    assert "The review of the twins on 2026-09-29 10:20+00:00 leaves no open critique." in english
    assert "La revisione dei twin del 2026-09-29 10:20+00:00 non lascia critiche aperte." in (
        italian
    )


def reviewed_state(*references: dict[str, object] | None) -> ProjectStateSources:
    pending = development_sources().changes[0]
    changes = tuple(
        with_review(
            dict(pending), reference=reference, run_id=f"00000000-0000-4000-8000-0000000d{i:04d}"
        )
        | {"commit": f"{i + 1:x}" * 40}
        for i, reference in enumerate(references)
    )
    return ProjectStateSources(changes=changes)


def test_the_current_reference_is_made_of_the_published_versions() -> None:
    assert current_reference(real_sources()) == CURRENT_REFERENCE
    assert current_reference(partial_sources("requirements")) is None
    assert current_reference(partial_sources("twins")) is None
    assert current_reference(partial_sources("brief")) is None


@pytest.mark.parametrize(
    ("changed", "stale"),
    [
        ({}, False),
        ({"requirements_version_number": 1}, True),
        ({"design_version_number": 3}, True),
        ({"design_version_number": 5}, True),
        ({"alternative_code": "DES-001"}, True),
        ({"alternative_code": None}, True),
    ],
)
def test_a_review_is_stale_when_any_version_it_was_made_against_changed(
    changed: dict[str, object], stale: bool
) -> None:
    state = reviewed_state({**CURRENT_REFERENCE, **changed})

    review = state_document(real_sources(state=state))["changes"][0]["review"]

    assert review["stale"] is stale
    assert stale_reviews(real_sources(state=state)) == int(stale)


def test_a_review_without_a_reference_is_never_stale() -> None:
    state = reviewed_state(None)
    document = state_document(real_sources(state=state))

    assert document["changes"][0]["review"]["reference"] is None
    assert document["changes"][0]["review"]["stale"] is False
    assert state_document(real_sources(state=state_sources()))["changes"][0]["review"]["stale"] is (
        False
    )


def test_the_folder_decides_the_stale_flag_whatever_the_sources_say() -> None:
    pending, stale, aligned = development_sources().changes
    state = replace(
        development_sources(),
        changes=(
            with_review(dict(pending), stale=True),
            with_review(dict(stale), stale=False),
            aligned,
        ),
    )

    changes = state_document(real_sources(state=state))["changes"]

    assert [change["review"]["stale"] for change in changes[:2]] == [False, True]


@pytest.mark.parametrize("through", ["brief", "team", "twins", "requirements"])
def test_without_an_approved_design_no_review_is_stale(through: str) -> None:
    package = partial_sources(through, state=development_sources())
    folder = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)

    changes = json.loads(folder.files[STATE_DOCUMENT])["changes"]

    assert [change["review"]["stale"] for change in changes[:2]] == [False, False]
    assert folder.manifest["state"]["stale_reviews"] == 0
    assert "Da riesaminare" not in folder.files[STATE_TEXT]
    assert "--recheck" not in folder.files[KNOWLEDGE_INDEX]
    validate_files(folder.files)


def test_only_the_changes_after_the_aligned_point_count_as_stale_reviews() -> None:
    pending, stale, aligned = development_sources().changes
    aligned_review = {
        "run_id": "00000000-0000-4000-8000-00000000d004",
        "reviewed_at": "2026-09-28T09:50:00+00:00",
        "verdict": "ALIGNED",
        "summary": "La prima versione segue il design.",
        "reference": dict(EARLIER_REFERENCE),
    }
    state = replace(
        development_sources(), changes=(pending, stale, {**aligned, "review": aligned_review})
    )
    without_point = replace(state, aligned=None)

    changes = state_document(real_sources(state=state))["changes"]

    assert [change["review"]["stale"] for change in changes] == [False, True, True]
    assert stale_reviews(real_sources(state=state)) == 1
    assert stale_reviews(real_sources(state=without_point)) == 2
    assert state_folder(without_point).manifest["state"]["stale_reviews"] == 2


def test_several_stale_reviews_are_counted_in_both_texts() -> None:
    state = reviewed_state(EARLIER_REFERENCE, CURRENT_REFERENCE, {**EARLIER_REFERENCE})
    folder = state_folder(state)

    english = state_markdown(real_sources(state=state), language="en")

    assert folder.manifest["state"]["stale_reviews"] == 2
    assert (
        "2 revisioni sono state fatte con versioni precedenti dei requisiti o del design: "
        "`ut verify --recheck` fa riesaminare quei commit ai twin."
    ) in folder.files[STATE_TEXT]
    assert folder.files[STATE_TEXT].count("Da riesaminare: rivisto con i requisiti") == 2
    sentence = (
        "2 reviews were made against earlier versions of the requirements or of the design: "
        "`ut verify --recheck` has the twins review those commits again."
    )
    assert sentence in english
    assert (
        f"3 changes are waiting after the aligned point. {sentence} No task"
        in (folder.files[KNOWLEDGE_INDEX])
    )


def test_a_stale_review_without_a_selected_alternative_says_so() -> None:
    state = reviewed_state({**EARLIER_REFERENCE, "alternative_code": None})

    english = state_markdown(real_sources(state=state), language="en")
    italian = state_markdown(real_sources(state=state), language="it")

    assert "design version 3, alternative not selected." in english
    assert "design alla versione 3, alternativa non scelta." in italian


@pytest.mark.parametrize("language", ["it", "en"])
def test_the_state_text_lists_the_tasks_by_origin_and_marks_the_stale_reviews(
    language: str,
) -> None:
    text = state_markdown(real_sources(state=development_sources()), language=language)
    expected = DEVELOPMENT_ITALIAN if language == "it" else DEVELOPMENT_ENGLISH

    assert "\n".join(expected) in text
    assert text.endswith(LEARNED_PARAGRAPH[language])


def test_a_closed_task_without_its_closing_time_or_note_says_only_its_origin() -> None:
    task = {**state_sources().tasks[0], "status": "DONE"}
    state = replace(state_sources(), tasks=(task,))

    italian = state_markdown(real_sources(state=state), language="it")
    english = state_markdown(real_sources(state=state), language="en")

    assert (
        "## Compiti aperti\n\nNon c'è nessun compito aperto per il codice.\n\n## Compiti chiusi\n\n"
        "Fatti:\n\n- TSK-001: Mostrare il messaggio di errore accanto al campo del nome (dalla "
        "decisione sul commit `4f2a9c1`).\n\n## Ultime critiche dei twin"
    ) in italian
    assert (
        "Done:\n\n- TSK-001: Mostrare il messaggio di errore accanto al campo del nome (from the "
        "decision on commit `4f2a9c1`).\n\n## Latest critiques of the twins"
    ) in english
    assert "Dropped:" not in english


def test_the_index_lists_the_open_tasks_by_origin_and_the_stale_reviews() -> None:
    index = development_folder().files[KNOWLEDGE_INDEX]

    assert "\n".join(INDEX_DEVELOPMENT) in index
    assert "\n".join(INDEX_LEARNING) in index
    assert index.index("## Acceptance tests") < index.index("## What the twins learned")
    assert "TSK-005" not in index and "TSK-006" not in index


def test_the_index_of_a_state_without_open_tasks_lists_none() -> None:
    state = replace(state_sources(), tasks=())
    index = state_folder(state).files[KNOWLEDGE_INDEX]

    assert "No task is open for the code." in index
    assert "The open tasks and where each comes from:" not in index
    assert "--recheck" not in index


def test_the_learning_document_has_one_entry_for_every_published_twin_in_its_order() -> None:
    package = real_sources(state=development_sources())

    document = learning_document(package)

    assert document == {
        "schema_version": 3,
        "kind": "orchestwin.twin-learning",
        "project_id": str(REAL_PROJECT_ID),
        "twins": [
            learned_entry(),
            {
                "twin_id": VOLUNTEER_TWIN,
                "twin_name": VOLUNTEER_NAME,
                "profile_version_number": 1,
                "development_version_number": 0,
                "label": "1.0",
                "observations": [],
                "retired": [],
            },
        ],
    }
    assert [twin["twin_id"] for twin in document["twins"]] == [
        twin["twin_id"] for twin in development_folder().manifest["twins"]
    ]
    assert learned_observations(package) == 2
    assert json.loads(development_folder().files[FEEDBACK_LEARNING]) == document


def test_the_identity_of_a_twin_and_its_label_come_from_the_published_stage() -> None:
    wrong = {
        **learned_entry(),
        "twin_name": "Nome sbagliato",
        "profile_version_number": 7,
        "label": "9.9",
        "pending_update": None,
        "new_material": {"changes": 1, "tests": 0},
    }
    state = replace(development_sources(), learning=(wrong,))

    entry = learning_entries(real_sources(state=state))[0]

    assert entry == learned_entry()
    assert (entry["twin_name"], entry["profile_version_number"], entry["label"]) == (
        RECEPTION_NAME,
        1,
        "1.3",
    )


def test_an_entry_of_a_twin_outside_the_published_stage_is_ignored() -> None:
    stranger = {**learned_entry(), "twin_id": "00000000-0000-4000-8000-00000000abcd"}
    state = replace(development_sources(), learning=(stranger,))
    folder = state_folder(state)

    entries = learning_entries(real_sources(state=state))

    assert [entry["twin_id"] for entry in entries] == [RECEPTION_TWIN, VOLUNTEER_TWIN]
    assert [entry["label"] for entry in entries] == ["1.0", "1.0"]
    assert folder.manifest["feedback"]["learned_observations"] == 0
    assert "00000000-0000-4000-8000-00000000abcd" not in folder.files[FEEDBACK_LEARNING]


def test_without_learning_every_twin_starts_at_development_version_zero() -> None:
    entries = learning_entries(real_sources())

    assert [(entry["twin_name"], entry["label"]) for entry in entries] == [
        (RECEPTION_NAME, "1.0"),
        (VOLUNTEER_NAME, "1.0"),
    ]
    assert all(entry["observations"] == entry["retired"] == [] for entry in entries)
    assert learned_observations(real_sources()) == 0


def test_an_entry_without_its_version_or_its_lists_reads_as_empty() -> None:
    bare = {"twin_id": RECEPTION_TWIN}
    state = ProjectStateSources(learning=(bare,))

    entry = learning_entries(real_sources(state=state))[0]

    assert (entry["development_version_number"], entry["label"]) == (0, "1.0")
    assert entry["observations"] == entry["retired"] == []


def test_the_learned_observations_keep_only_the_keys_of_the_contract_written_as_text() -> None:
    source = learned_entry()
    observation = {
        **source["observations"][0],
        "update_id": UUID(source["observations"][0]["update_id"]),
        "approved_at": datetime(2026, 9, 29, 11, 0, tzinfo=UTC),
        "number": 1,
    }
    retired = {**source["retired"][0], "retired_at": datetime(2026, 9, 29, 15, 0, tzinfo=UTC)}
    entry = {
        **source,
        "twin_id": UUID(RECEPTION_TWIN),
        "observations": [observation, source["observations"][1]],
        "retired": [retired],
    }
    folder = state_folder(replace(development_sources(), learning=(entry,)))

    stored = json.loads(folder.files[FEEDBACK_LEARNING])["twins"][0]

    assert stored == learned_entry()
    assert '"number"' not in folder.files[FEEDBACK_LEARNING]
    validate_files(folder.files)


@pytest.mark.parametrize("through", ["brief", "team"])
def test_a_folder_without_the_twins_stage_says_nothing_about_learning(through: str) -> None:
    package = partial_sources(through, state=development_sources())
    folder = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)

    assert FEEDBACK_LEARNING not in folder.files
    assert "learned" not in folder.manifest["feedback"]
    assert "learned_observations" not in folder.manifest["feedback"]
    assert schema_document("learning") in folder.files
    assert "## What the twins learned" not in folder.files[KNOWLEDGE_INDEX]
    assert "## Cosa hanno imparato i twin" not in folder.files[STATE_TEXT]
    assert state_documents.learning_lines(package) == []
    assert learning_entries(package) == []


@pytest.mark.parametrize("through", ["twins", "requirements"])
def test_a_folder_with_the_twins_stage_carries_what_they_learned(through: str) -> None:
    package = partial_sources(through, state=development_sources())
    folder = build_knowledge_folder(package, version_number=1, created_at=PUBLISHED_AT)

    assert json.loads(folder.files[FEEDBACK_LEARNING]) == learning_document(package)
    assert folder.manifest["feedback"]["learned"] == FEEDBACK_LEARNING
    assert folder.manifest["feedback"]["learned_observations"] == 2
    assert "\n".join(INDEX_LEARNING) in folder.files[KNOWLEDGE_INDEX]
    assert folder.files[STATE_TEXT].endswith(LEARNED_PARAGRAPH["it"])
    validate_files(folder.files)


def test_a_twin_whose_observations_were_all_retired_has_no_active_one() -> None:
    entry = {**learned_entry(), "observations": []}
    state = replace(development_sources(), learning=(entry,))

    lines = state_documents.learning_lines(real_sources(state=state))

    assert lines[2] == "- Addetti all'accoglienza, version 1.3: no active learned observation."
    assert (
        "Addetti all'accoglienza, versione 1.3, nessuna osservazione; Organizzatori volontari"
        in state_folder(state).files[STATE_TEXT]
    )


def test_a_twins_stage_without_twins_says_that_no_twin_learned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state_documents, "learning_entries", lambda package: [])

    italian = state_markdown(real_sources(), language="it")
    english = state_markdown(real_sources(), language="en")

    assert italian.endswith(
        "## Cosa hanno imparato i twin\n\nNessun twin ha ancora appreso qualcosa durante lo "
        "sviluppo.\n"
    )
    assert english.endswith(
        "## What the twins learned\n\nNo twin has learned anything yet during the development.\n"
    )
    assert state_documents.learning_lines(real_sources()) == [
        "## What the twins learned",
        "",
        INDEX_LEARNING[-3],
        "",
    ]


def test_an_observation_count_of_one_is_singular_in_both_languages() -> None:
    entry = {**learned_entry(), "observations": learned_entry()["observations"][:1]}
    state = replace(development_sources(), learning=(entry,))

    italian = state_markdown(real_sources(state=state), language="it")
    english = state_markdown(real_sources(state=state), language="en")

    assert "Addetti all'accoglienza, versione 1.3, 1 osservazione;" in italian
    assert "Addetti all'accoglienza, version 1.3, 1 observation;" in english
