from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from orchestwin.knowledge.documents import counted
from orchestwin.knowledge.layout import (
    FEEDBACK_CHANGES,
    KNOWLEDGE_SCHEMA_VERSION,
    STATE_DOCUMENT,
    STATE_TEXT,
    stage_text,
)
from orchestwin.knowledge.sources import KnowledgeSources
from orchestwin.knowledge.state import (
    CHANGE_REVIEWS_KIND,
    MAX_MESSAGE_LENGTH,
    MIN_COMMIT_LENGTH,
    STATE_KIND,
)

SHORT_MESSAGE_LENGTH: Final = 200
_SUBJECTS_SHAPE: Final = {"requirements": [None], "screens": [None]}
_CHANGE_SHAPE: Final = {
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
_ALIGNED_SHAPE: Final = {
    "commit": None,
    "decided_at": None,
    "requirements_version_number": None,
    "design_version_number": None,
}
_TASK_SHAPE: Final = {
    "code": None,
    "text": None,
    "about": _SUBJECTS_SHAPE,
    "from_commit": None,
    "created_at": None,
    "status": None,
}
_RUN_SHAPE: Final = {
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
        "affected": _SUBJECTS_SHAPE,
        "design_request": None,
        "requirements_request": None,
        "code_tasks": [None],
    },
    "cost_microusd": None,
}
_TEXTS: Final[dict[str, dict[str, Any]]] = {
    "en": {
        "title": "# Development state: {project}",
        "intro": (
            "This document says where the development of the project stands outside OrchesTwin "
            "Studio: the approved versions the code is expected to implement, the commits "
            "recorded in the Studio, the critiques of the user twins, the decisions of the owner "
            "and the tasks for the code. The exact records are in `{document}` and `{changes}`; "
            "the diff of a commit is never copied into the folder."
        ),
        "reference": "## Reference",
        "requirements": "- Requirements: version {number} (`{path}`).",
        "requirements_missing": "- Requirements: not approved yet.",
        "design": "- Design: version {number}, alternative {alternative} (`{path}`).",
        "design_missing": "- Design: not approved yet.",
        "no_alternative": "not selected",
        "aligned": "## Aligned point",
        "aligned_point": "Commit `{commit}`, decided on {when}{versions}.",
        "aligned_versions": ", with requirements version {requirements} and design version {design}",
        "no_aligned": "No commit has been decided aligned yet.",
        "pending": "## Changes after the aligned point",
        "recorded": "The Studio has recorded {changes}; {pending} after the aligned point.",
        "no_changes": "The Studio has recorded no change (commit) of the code yet.",
        "change_words": ("change", "changes"),
        "pending_words": ("none is waiting", "1 is waiting", "{count} are waiting"),
        "change": "- `{commit}` of {when}: {message}. Verdict: {verdict}. Decision: {decision}.",
        "no_review": "not reviewed yet",
        "no_decision": "no decision yet",
        "tasks": "## Open tasks",
        "task": (
            "- {code}: {text} (requirements {requirements}; screens {screens}; "
            "from commit `{commit}`)."
        ),
        "no_codes": "none",
        "no_tasks": "There is no open task for the code.",
        "critiques": "## Latest critiques of the twins",
        "run": "Commit `{commit}`, reviewed on {when}. Verdict: {verdict}. {summary}",
        "design_request": "Design change request: {text}",
        "requirements_request": "Requirements change request: {text}",
        "code_tasks": "Tasks proposed for the code: {tasks}.",
        "twin": "### {name}: {verdict}",
        "finding": "- Importance {severity}: {text}",
        "finding_about": " About: {subjects}.",
        "finding_action": " Suggested action: {action}",
        "no_findings": "No finding.",
        "no_runs": "No commit has been reviewed yet.",
    },
    "it": {
        "title": "# Stato dello sviluppo: {project}",
        "intro": (
            "Questo documento dice a che punto è lo sviluppo del progetto fuori da OrchesTwin "
            "Studio: le versioni approvate che il codice deve realizzare, i commit registrati "
            "nello Studio, le critiche dei twin, le decisioni del proprietario e i compiti per il "
            "codice. I dati esatti sono in `{document}` e in `{changes}`; il diff di un commit "
            "non viene mai copiato nella cartella."
        ),
        "reference": "## Riferimento",
        "requirements": "- Requisiti: versione {number} (`{path}`).",
        "requirements_missing": "- Requisiti: non ancora approvati.",
        "design": "- Design: versione {number}, alternativa {alternative} (`{path}`).",
        "design_missing": "- Design: non ancora approvato.",
        "no_alternative": "non scelta",
        "aligned": "## Punto allineato",
        "aligned_point": "Commit `{commit}`, deciso il {when}{versions}.",
        "aligned_versions": (
            ", con i requisiti alla versione {requirements} e il design alla versione {design}"
        ),
        "no_aligned": "Nessun commit è stato ancora dichiarato allineato.",
        "pending": "## Modifiche dopo il punto allineato",
        "recorded": "Lo Studio ha registrato {changes}; {pending} dopo il punto allineato.",
        "no_changes": "Lo Studio non ha ancora registrato nessuna modifica (commit) del codice.",
        "change_words": ("modifica", "modifiche"),
        "pending_words": ("nessuna è in attesa", "1 è in attesa", "{count} sono in attesa"),
        "change": (
            "- `{commit}` del {when}: {message}. Verdetto: {verdict}. Decisione: {decision}."
        ),
        "no_review": "non ancora rivisto",
        "no_decision": "nessuna decisione",
        "tasks": "## Compiti aperti",
        "task": (
            "- {code}: {text} (requisiti {requirements}; schermate {screens}; "
            "dal commit `{commit}`)."
        ),
        "no_codes": "nessuno",
        "no_tasks": "Non c'è nessun compito aperto per il codice.",
        "critiques": "## Ultime critiche dei twin",
        "run": "Commit `{commit}`, rivisto il {when}. Verdetto: {verdict}. {summary}",
        "design_request": "Richiesta di modifica del design: {text}",
        "requirements_request": "Richiesta di modifica dei requisiti: {text}",
        "code_tasks": "Compiti proposti per il codice: {tasks}.",
        "twin": "### {name}: {verdict}",
        "finding": "- Importanza {severity}: {text}",
        "finding_about": " Riguarda: {subjects}.",
        "finding_action": " Azione suggerita: {action}",
        "no_findings": "Nessun rilievo.",
        "no_runs": "Nessun commit è stato ancora rivisto.",
    },
}
_VERDICT_WORDS: Final = {
    "en": {
        "ALIGNED": "the code is aligned with the approved requirements and design",
        "CODE_DRIFT": "the code departs from the approved requirements or design",
        "DESIGN_OUTDATED": "the design should get a new version",
        "REQUIREMENTS_OUTDATED": "the requirements should get a new version",
    },
    "it": {
        "ALIGNED": "il codice è allineato ai requisiti e al design approvati",
        "CODE_DRIFT": "il codice si allontana dai requisiti o dal design approvati",
        "DESIGN_OUTDATED": "il design va aggiornato con una nuova versione",
        "REQUIREMENTS_OUTDATED": "i requisiti vanno aggiornati con una nuova versione",
    },
}
_DECISION_WORDS: Final = {
    "en": {
        "ALIGNED": "this commit is the aligned point",
        "DESIGN_CHANGE": "a new design version was requested",
        "REQUIREMENTS_CHANGE": "a change of the requirements was requested",
        "CODE_TASKS": "tasks for the code were recorded",
        "DISMISSED": "nothing to do",
    },
    "it": {
        "ALIGNED": "questo commit è il punto allineato",
        "DESIGN_CHANGE": "è stata chiesta una nuova versione del design",
        "REQUIREMENTS_CHANGE": "è stata chiesta una modifica dei requisiti",
        "CODE_TASKS": "sono stati registrati compiti per il codice",
        "DISMISSED": "niente da fare",
    },
}
_CRITIQUE_WORDS: Final = {
    "en": {
        "FINE": "the change is fine",
        "CONCERN": "the change raises a concern",
        "DRIFT": "the change departs from what was approved",
    },
    "it": {
        "FINE": "la modifica va bene",
        "CONCERN": "la modifica solleva un dubbio",
        "DRIFT": "la modifica si allontana da quanto approvato",
    },
}
_SEVERITY_WORDS: Final = {
    "en": {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"},
    "it": {"LOW": "bassa", "MEDIUM": "media", "HIGH": "alta"},
}


def _plain(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _shaped(value: object, shape: object) -> object:
    if isinstance(shape, dict) and isinstance(value, Mapping):
        return {key: _shaped(value.get(key), inner) for key, inner in shape.items()}
    if isinstance(shape, list) and isinstance(value, list | tuple):
        return [_shaped(item, shape[0]) for item in value]
    return _plain(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _latest_review(change: Mapping[str, object], runs: Sequence[object]) -> object:
    if "review" in change:
        return change["review"]
    for run in map(_mapping, runs):
        if run.get("commit") == change.get("commit"):
            alignment = _mapping(run.get("alignment"))
            return {
                "run_id": run.get("id"),
                "reviewed_at": run.get("reviewed_at"),
                "verdict": alignment.get("status"),
                "summary": alignment.get("summary"),
            }
    return None


def _change(change: object, runs: Sequence[object]) -> object:
    source = _mapping(change)
    shaped = _shaped({**source, "review": _latest_review(source, runs)}, _CHANGE_SHAPE)
    message = shaped.get("message")
    if isinstance(message, str):
        shaped["message"] = message[:MAX_MESSAGE_LENGTH]
    return shaped


def _version_reference(version) -> dict[str, object]:
    return {
        "version_id": str(version.id),
        "version_number": version.version_number,
        "content_hash": version.content_hash,
    }


def selected_alternative_code(package: Mapping[str, object]) -> str | None:
    selected = package.get("owner_selected_alternative_id")
    if selected is None:
        return None
    return next(
        (
            str(item["code"])
            for item in package.get("alternatives") or ()
            if isinstance(item, Mapping) and item.get("id") == selected
        ),
        None,
    )


def development_reference(sources: KnowledgeSources) -> dict[str, object]:
    present = sources.present_stages
    design = None
    if "design" in present:
        design = {
            **_version_reference(sources.design),
            "alternative_code": selected_alternative_code(sources.payload("design")),
        }
    return {
        "requirements": (
            _version_reference(sources.requirements) if "requirements" in present else None
        ),
        "design": design,
    }


def state_document(sources: KnowledgeSources) -> dict[str, object]:
    state = sources.state
    return {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "kind": STATE_KIND,
        "project_id": str(sources.project_id),
        "reference": development_reference(sources),
        "aligned": _shaped(state.aligned, _ALIGNED_SHAPE),
        "changes": [_change(change, state.runs) for change in state.changes],
        "tasks": [_shaped(task, _TASK_SHAPE) for task in state.tasks],
    }


def change_reviews_document(sources: KnowledgeSources) -> dict[str, object]:
    return {
        "schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "kind": CHANGE_REVIEWS_KIND,
        "project_id": str(sources.project_id),
        "runs": [_shaped(run, _RUN_SHAPE) for run in sources.state.runs],
    }


def state_language(language: str | None) -> str:
    return "it" if language is not None and language.lower().startswith("it") else "en"


def _inline(value: object) -> str:
    return " ".join(str(value).split())


def _bare(value: object) -> str:
    return _inline(value).rstrip(".")


def _sentence(value: object) -> str:
    text = _inline(value)
    return text if not text or text.endswith((".", "!", "?", "…")) else f"{text}."


def _short(commit: object) -> str:
    return str(commit)[:MIN_COMMIT_LENGTH]


def _when(value: object) -> str:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return _inline(value)
    return moment.isoformat(sep=" ", timespec="minutes")


def _headline(message: object) -> str:
    lines = str(message or "").strip().splitlines()
    first = _inline(lines[0]) if lines else ""
    if len(first) > SHORT_MESSAGE_LENGTH:
        return first[: SHORT_MESSAGE_LENGTH - 1].rstrip() + "…"
    return first.rstrip(".")


def _worded(words: Mapping[str, str], code: object) -> str:
    text = words.get(str(code))
    return str(code) if text is None else f"{text} ({code})"


def _codes(values: object, empty: str) -> str:
    items = [str(item) for item in values] if isinstance(values, list) else []
    return ", ".join(items) if items else empty


def _pending(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    aligned = _mapping(document["aligned"]).get("commit")
    pending = []
    for change in map(_mapping, document["changes"]):
        if aligned is not None and str(change.get("commit")) == str(aligned):
            break
        pending.append(change)
    return pending


def _open_tasks(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [task for task in map(_mapping, document["tasks"]) if task.get("status") == "OPEN"]


def _reference_lines(document: Mapping[str, Any], texts: Mapping[str, Any]) -> list[str]:
    reference = _mapping(document["reference"])
    requirements = reference.get("requirements")
    design = reference.get("design")
    lines = [texts["reference"], ""]
    if isinstance(requirements, Mapping):
        lines.append(
            texts["requirements"].format(
                number=requirements["version_number"], path=stage_text("requirements")
            )
        )
    else:
        lines.append(texts["requirements_missing"])
    if isinstance(design, Mapping):
        lines.append(
            texts["design"].format(
                number=design["version_number"],
                alternative=design["alternative_code"] or texts["no_alternative"],
                path=stage_text("design"),
            )
        )
    else:
        lines.append(texts["design_missing"])
    return [*lines, ""]


def _aligned_lines(document: Mapping[str, Any], texts: Mapping[str, Any]) -> list[str]:
    aligned = document["aligned"]
    if not isinstance(aligned, Mapping):
        return [texts["aligned"], "", texts["no_aligned"], ""]
    requirements = aligned["requirements_version_number"]
    design = aligned["design_version_number"]
    versions = (
        texts["aligned_versions"].format(requirements=requirements, design=design)
        if requirements is not None and design is not None
        else ""
    )
    point = texts["aligned_point"].format(
        commit=_short(aligned["commit"]), when=_when(aligned["decided_at"]), versions=versions
    )
    return [texts["aligned"], "", point, ""]


def _pending_lines(
    document: Mapping[str, Any], texts: Mapping[str, Any], language: str
) -> list[str]:
    lines = [texts["pending"], ""]
    changes = document["changes"]
    if not changes:
        return [*lines, texts["no_changes"], ""]
    pending = _pending(document)
    none, one, many = texts["pending_words"]
    waiting = none if not pending else one if len(pending) == 1 else many
    lines.extend(
        [
            texts["recorded"].format(
                changes=counted(len(changes), *texts["change_words"]),
                pending=waiting.format(count=len(pending)),
            ),
            "",
        ]
    )
    for change in pending:
        review = _mapping(change.get("review"))
        decision = _mapping(change.get("decision"))
        lines.append(
            texts["change"].format(
                commit=_short(change.get("commit")),
                when=_when(change.get("committed_at")),
                message=_headline(change.get("message")),
                verdict=(
                    _worded(_VERDICT_WORDS[language], review.get("verdict"))
                    if review
                    else texts["no_review"]
                ),
                decision=(
                    _worded(_DECISION_WORDS[language], decision.get("kind"))
                    if decision
                    else texts["no_decision"]
                ),
            )
        )
    if pending:
        lines.append("")
    return lines


def _task_lines(document: Mapping[str, Any], texts: Mapping[str, Any]) -> list[str]:
    lines = [texts["tasks"], ""]
    tasks = _open_tasks(document)
    for task in tasks:
        about = _mapping(task.get("about"))
        lines.append(
            texts["task"].format(
                code=task.get("code"),
                text=_bare(task.get("text")),
                requirements=_codes(about.get("requirements"), texts["no_codes"]),
                screens=_codes(about.get("screens"), texts["no_codes"]),
                commit=_short(task.get("from_commit")),
            )
        )
    if not tasks:
        lines.append(texts["no_tasks"])
    return [*lines, ""]


def _finding_line(finding: Mapping[str, Any], texts: Mapping[str, Any], language: str) -> str:
    about = _mapping(finding.get("about"))
    subjects = [
        str(about[key]) for key in ("requirement", "screen", "file") if about.get(key) is not None
    ]
    line = texts["finding"].format(
        severity=_worded(_SEVERITY_WORDS[language], finding.get("severity")),
        text=_sentence(finding.get("text")),
    )
    if subjects:
        line += texts["finding_about"].format(subjects=", ".join(subjects))
    if finding.get("action"):
        line += texts["finding_action"].format(action=_sentence(finding["action"]))
    return line


def _run_lines(run: Mapping[str, Any], texts: Mapping[str, Any], language: str) -> list[str]:
    alignment = _mapping(run.get("alignment"))
    heading = texts["run"].format(
        commit=_short(run.get("commit")),
        when=_when(run.get("reviewed_at")),
        verdict=_worded(_VERDICT_WORDS[language], alignment.get("status")),
        summary=_sentence(alignment.get("summary") or ""),
    )
    lines = [heading.rstrip(), ""]
    for key in ("design_request", "requirements_request"):
        if alignment.get(key):
            lines.extend([texts[key].format(text=_sentence(alignment[key])), ""])
    tasks = alignment.get("code_tasks")
    if isinstance(tasks, list) and tasks:
        lines.extend([texts["code_tasks"].format(tasks="; ".join(map(_bare, tasks))), ""])
    for critique in map(_mapping, run.get("critiques") or ()):
        findings = [_mapping(item) for item in critique.get("findings") or ()]
        lines.extend(
            [
                texts["twin"].format(
                    name=_inline(critique.get("twin_name")),
                    verdict=_worded(_CRITIQUE_WORDS[language], critique.get("verdict")),
                ),
                "",
                _sentence(critique.get("summary") or ""),
                "",
                *(_finding_line(finding, texts, language) for finding in findings),
            ]
        )
        if not findings:
            lines.append(texts["no_findings"])
        lines.append("")
    return lines


def state_markdown(sources: KnowledgeSources, *, language: str | None) -> str:
    words = state_language(language)
    texts = _TEXTS[words]
    document = state_document(sources)
    runs = change_reviews_document(sources)["runs"]
    lines = [
        texts["title"].format(project=_inline(sources.project_name)),
        "",
        texts["intro"].format(document=STATE_DOCUMENT, changes=FEEDBACK_CHANGES),
        "",
        *_reference_lines(document, texts),
        *_aligned_lines(document, texts),
        *_pending_lines(document, texts, words),
        *_task_lines(document, texts),
        texts["critiques"],
        "",
    ]
    if runs:
        lines.extend(_run_lines(_mapping(runs[0]), texts, words))
    else:
        lines.extend([texts["no_runs"], ""])
    return "\n".join(lines)


def development_lines(sources: KnowledgeSources) -> list[str]:
    document = state_document(sources)
    runs = change_reviews_document(sources)["runs"]
    aligned = document["aligned"]
    pending = len(_pending(document))
    tasks = len(_open_tasks(document))
    recorded = (
        f"The Studio has recorded {counted(len(document['changes']), 'change', 'changes')} "
        "(commits) of the code."
        if document["changes"]
        else "The Studio has recorded no change (commit) of the code yet."
    )
    point = (
        f"The aligned point is commit `{_short(aligned['commit'])}`, decided on "
        f"{_when(aligned['decided_at'])}."
        if isinstance(aligned, Mapping)
        else "No commit has been decided aligned yet."
    )
    waiting = (
        f"{counted(pending, 'change is', 'changes are')} waiting after the aligned point."
        if pending
        else "No change is waiting after the aligned point."
    )
    open_tasks = (
        f"{counted(tasks, 'task is', 'tasks are')} open for the code."
        if tasks
        else "No task is open for the code."
    )
    lines = [
        "## Development state",
        "",
        f"{recorded} {point} {waiting} {open_tasks} `{STATE_TEXT}` explains the state in the "
        f"language of the project; `{STATE_DOCUMENT}` and `{FEEDBACK_CHANGES}` hold the exact "
        "records.",
        "",
        "## Latest critiques on the code",
        "",
    ]
    critiques = list(map(_mapping, _mapping(runs[0]).get("critiques") or ())) if runs else []
    if not critiques:
        return [*lines, "None yet.", ""]
    run = _mapping(runs[0])
    alignment = _mapping(run.get("alignment"))
    lines.extend(
        [
            f"Commit `{_short(run.get('commit'))}`, reviewed on {_when(run.get('reviewed_at'))}: "
            f"{_worded(_VERDICT_WORDS['en'], alignment.get('status'))}.",
            "",
        ]
    )
    for critique in critiques:
        lines.append(
            f"- {_inline(critique.get('twin_name'))}: "
            f"{_worded(_CRITIQUE_WORDS['en'], critique.get('verdict'))}. "
            f"{_sentence(critique.get('summary') or '')}".rstrip()
        )
    return [*lines, ""]


def change_critique_lines(sources: KnowledgeSources) -> list[str]:
    lines = ["## Critiques on the code changes", ""]
    runs = change_reviews_document(sources)["runs"]
    for run in map(_mapping, runs):
        reference = _mapping(run.get("reference"))
        alignment = _mapping(run.get("alignment"))
        parts = [
            f"Commit `{_short(run.get('commit'))}`, reviewed on {_when(run.get('reviewed_at'))} "
            f"against requirements version {reference.get('requirements_version_number')} and "
            f"design version {reference.get('design_version_number')}, alternative "
            f"{reference.get('alternative_code') or 'not selected'}: "
            f"{_worded(_VERDICT_WORDS['en'], alignment.get('status'))}.",
            _sentence(alignment.get("summary") or ""),
        ]
        for critique in map(_mapping, run.get("critiques") or ()):
            findings = len(critique.get("findings") or ())
            parts.append(
                f"{_inline(critique.get('twin_name'))}: "
                f"{_worded(_CRITIQUE_WORDS['en'], critique.get('verdict'))}, "
                f"{counted(findings, 'finding', 'findings')}. "
                f"{_sentence(critique.get('summary') or '')}".rstrip()
            )
        if alignment.get("design_request"):
            parts.append(f"Design change request: {_sentence(alignment['design_request'])}")
        if alignment.get("requirements_request"):
            parts.append(
                f"Requirements change request: {_sentence(alignment['requirements_request'])}"
            )
        tasks = alignment.get("code_tasks")
        if isinstance(tasks, list) and tasks:
            parts.append(f"Tasks proposed for the code: {'; '.join(map(_bare, tasks))}.")
        lines.extend([" ".join(part for part in parts if part), ""])
    if not runs:
        lines.extend(["No code change has been reviewed yet.", ""])
    return lines


__all__ = [
    "SHORT_MESSAGE_LENGTH",
    "change_critique_lines",
    "change_reviews_document",
    "development_lines",
    "development_reference",
    "selected_alternative_code",
    "state_document",
    "state_language",
    "state_markdown",
]
