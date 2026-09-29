from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    KNOWLEDGE_INDEX,
    STATE_DOCUMENT,
    STATE_TEXT,
    schema_document,
)
from orchestwin.knowledge.schema import validate_document, validate_files
from orchestwin.knowledge.state import MAX_MESSAGE_LENGTH, ProjectStateSources
from orchestwin.knowledge.state_documents import (
    change_reviews_document,
    development_reference,
    selected_alternative_code,
    state_document,
    state_language,
    state_markdown,
)

from .knowledge_fixtures import (
    ALIGNED_COMMIT,
    CHANGE_RUN,
    PENDING_COMMIT,
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    change_run,
    partial_sources,
    real_sources,
    state_sources,
)

SUBJECTS = {"requirements": None, "screens": None}
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
            "review": {"run_id": None, "reviewed_at": None, "verdict": None, "summary": None},
            "decision": {"kind": None, "decided_at": None, "note": None},
        }
    ],
    "tasks": [
        {
            "code": None,
            "text": None,
            "about": SUBJECTS,
            "from_commit": None,
            "created_at": None,
            "status": None,
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
ITALIAN_TEXT = (
    "# Stato dello sviluppo: Lista ospiti workshop",
    "",
    "Questo documento dice a che punto è lo sviluppo del progetto fuori da OrchesTwin Studio: "
    "le versioni approvate che il codice deve realizzare, i commit registrati nello Studio, le "
    "critiche dei twin, le decisioni del proprietario e i compiti per il codice. I dati esatti "
    "sono in `state/state.json` e in `twins/feedback/changes.json`; il diff di un commit non "
    "viene mai copiato nella cartella.",
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
    "schermate SCR-002; dal commit `4f2a9c1`).",
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
    "screens SCR-002; from commit `4f2a9c1`).",
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
)


def state_folder(state: ProjectStateSources | None = None) -> KnowledgeFolder:
    return build_knowledge_folder(
        real_sources(state=state_sources() if state is None else state),
        version_number=1,
        created_at=PUBLISHED_AT,
    )


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


def test_the_two_documents_have_exactly_the_keys_of_the_contract() -> None:
    folder = state_folder()
    state = json.loads(folder.files[STATE_DOCUMENT])
    changes = json.loads(folder.files[FEEDBACK_CHANGES])

    assert_keys(state, STATE_KEYS, "state")
    assert_keys(changes, CHANGES_KEYS, "changes")
    assert state["aligned"] is not None
    assert [change["review"] is None for change in state["changes"]] == [False, True]
    assert all(change["decision"] is not None for change in state["changes"])
    assert all(value is not None for value in state["reference"].values())
    assert changes["runs"][0]["critiques"][0]["findings"]


def test_the_two_documents_validate_against_their_published_schemas() -> None:
    folder = state_folder()

    for path, name in ((STATE_DOCUMENT, "state"), (FEEDBACK_CHANGES, "changes")):
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
    assert document["changes"] == [dict(change) for change in state_sources().changes]
    assert document["tasks"] == [dict(task) for task in state_sources().tasks]


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
    }
    unreviewed = ProjectStateSources(changes=(change,), runs=())
    assert state_document(real_sources(state=unreviewed))["changes"][0]["review"] is None


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
        "aligned_commit": ALIGNED_COMMIT,
        "open_tasks": 1,
    }
    assert manifest["feedback"]["changes"] == FEEDBACK_CHANGES
    assert manifest["feedback"]["change_reviews"] == 1


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
