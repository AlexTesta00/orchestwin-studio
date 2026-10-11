from __future__ import annotations

from typing import Any, Final

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
        "push": (
            "`ut push` sends the hand-made changes of this folder to the Studio: you approve the "
            "differences and a new version is born."
        ),
        "align_design": (
            "`ut align --from-design` brings the code up to the current design when the design "
            "changed after the code was written."
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
        "stale": (
            " To re-review: reviewed against requirements version {requirements} and design "
            "version {design}, alternative {alternative}."
        ),
        "stale_count": (
            "1 review was made against earlier versions of the requirements or of the design: "
            "`ut verify --recheck` has the twins review that commit again.",
            "{count} reviews were made against earlier versions of the requirements or of the "
            "design: `ut verify --recheck` has the twins review those commits again.",
        ),
        "tasks": "## Open tasks",
        "task": "- {code}: {text} ({details}).",
        "about_requirements": "requirements {codes}",
        "about_screens": "screens {codes}",
        "about_criteria": "criteria {codes}",
        "origins": {
            "verdict": "from the decision on commit `{commit}`",
            "change_finding": "from a finding of the twin {twin} on commit `{commit}`",
            "test_finding": "from a finding of the twin {twin} on the acceptance tests",
            "owner": "written by the owner",
        },
        "no_codes": "none",
        "no_tasks": "There is no open task for the code.",
        "closed": "## Closed tasks",
        "done": "Done:",
        "dropped": "Dropped:",
        "done_on": "done on {when}",
        "dropped_on": "dropped on {when}",
        "note": "note: {note}",
        "no_closed": "No task has been closed yet.",
        "learning": "## What the twins learned",
        "learned": "Observations learned by the twins during the development: {twins}.",
        "learned_twin": "{name}, version {label}, {count}",
        "observation_words": ("observation", "observations"),
        "no_observation": "no observation",
        "learned_document": (
            "`{document}` holds them with where each comes from; `ut twins update` proposes new "
            "ones."
        ),
        "no_twin_learned": "No twin has learned anything yet during the development.",
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
        "push": (
            "`ut push` invia allo Studio le modifiche fatte a mano in questa cartella: le "
            "differenze si approvano e nasce una versione nuova."
        ),
        "align_design": (
            "`ut align --from-design` porta il codice al design attuale quando il design è "
            "cambiato dopo che il codice è stato scritto."
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
        "stale": (
            " Da riesaminare: rivisto con i requisiti alla versione {requirements} e il design "
            "alla versione {design}, alternativa {alternative}."
        ),
        "stale_count": (
            "1 revisione è stata fatta con versioni precedenti dei requisiti o del design: "
            "`ut verify --recheck` fa riesaminare quel commit ai twin.",
            "{count} revisioni sono state fatte con versioni precedenti dei requisiti o del "
            "design: `ut verify --recheck` fa riesaminare quei commit ai twin.",
        ),
        "tasks": "## Compiti aperti",
        "task": "- {code}: {text} ({details}).",
        "about_requirements": "requisiti {codes}",
        "about_screens": "schermate {codes}",
        "about_criteria": "criteri {codes}",
        "origins": {
            "verdict": "dalla decisione sul commit `{commit}`",
            "change_finding": "da un rilievo del twin {twin} sul commit `{commit}`",
            "test_finding": "da un rilievo del twin {twin} sulla verifica dei criteri",
            "owner": "scritto dal proprietario",
        },
        "no_codes": "nessuno",
        "no_tasks": "Non c'è nessun compito aperto per il codice.",
        "closed": "## Compiti chiusi",
        "done": "Fatti:",
        "dropped": "Abbandonati:",
        "done_on": "fatto il {when}",
        "dropped_on": "abbandonato il {when}",
        "note": "nota: {note}",
        "no_closed": "Nessun compito è stato ancora chiuso.",
        "learning": "## Cosa hanno imparato i twin",
        "learned": "Osservazioni apprese dai twin durante lo sviluppo: {twins}.",
        "learned_twin": "{name}, versione {label}, {count}",
        "observation_words": ("osservazione", "osservazioni"),
        "no_observation": "nessuna osservazione",
        "learned_document": (
            "`{document}` le contiene con la loro origine; `ut twins update` ne propone di nuove."
        ),
        "no_twin_learned": "Nessun twin ha ancora appreso qualcosa durante lo sviluppo.",
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
_BROWSER_LABELS: Final = {"chrome": "Chrome", "firefox": "Firefox"}
_TEST_TEXTS: Final[dict[str, dict[str, Any]]] = {
    "en": {
        "heading": "## Acceptance tests",
        "critiques_heading": "## Critiques on the acceptance tests",
        "none": (
            "No run of the acceptance tests is recorded yet: `ut test` runs them on the "
            "application and records the result in the Studio."
        ),
        "latest": (
            "The latest run of the acceptance tests, finished on {when}, checked {application} in "
            "{browsers}."
        ),
        "run": (
            "The run of {when} checked {application} in {browsers}, against requirements version "
            "{requirements} and design version {design}, alternative {alternative}."
        ),
        "static": "the static folder `{address}`",
        "url": "the address `{address}`",
        "and": "and",
        "numbers": "Criteria: {numbers}.",
        "statuses": {
            "passed": ("passed", "passed"),
            "failed": ("failed", "failed"),
            "blocked": ("blocked", "blocked"),
            "not_covered": ("not covered", "not covered"),
            "not_run": ("not run", "not run"),
        },
        "stopped": "Criteria that failed or were blocked:",
        "stopped_statuses": {"FAILED": "failed", "BLOCKED": "blocked"},
        "stopped_line": "- {code} {status}{heading}{path}.",
        "stopped_path": " (path {path})",
        "none_stopped": "No criterion failed or was blocked.",
        "review": "The review of the twins on {when} leaves {critiques}.",
        "open_words": ("open critique", "open critiques"),
        "review_clear": "The review of the twins on {when} leaves no open critique.",
        "unreviewed": "The twins have not reviewed this run yet.",
        "document": (
            "`{document}` holds {runs} with the steps, the evidence and the critiques of the twins."
        ),
        "run_words": ("run of the acceptance tests", "runs of the acceptance tests"),
        "again": "`ut test` runs the tests again.",
        "reviewed": "The twins reviewed it on {when}.",
        "twin": "{name}: {verdict}.",
        "findings": "Findings: {findings}",
        "finding": "importance {severity}{about}: {text}",
        "finding_about": " about {codes}",
        "no_findings": "No finding.",
        "no_alternative": "not selected",
    },
    "it": {
        "heading": "## Verifica dei criteri",
        "none": (
            "Nessuna verifica dei criteri è stata ancora registrata: `ut test` la esegue "
            "sull'applicazione e ne registra il risultato nello Studio."
        ),
        "latest": (
            "L'ultima verifica dei criteri, conclusa il {when}, ha provato {application} in "
            "{browsers}."
        ),
        "static": "la cartella statica `{address}`",
        "url": "l'indirizzo `{address}`",
        "and": "e",
        "numbers": "Criteri: {numbers}.",
        "statuses": {
            "passed": ("superato", "superati"),
            "failed": ("fallito", "falliti"),
            "blocked": ("bloccato", "bloccati"),
            "not_covered": ("non coperto", "non coperti"),
            "not_run": ("non eseguito", "non eseguiti"),
        },
        "review": "La revisione dei twin del {when} lascia {critiques}.",
        "open_words": ("critica aperta", "critiche aperte"),
        "review_clear": "La revisione dei twin del {when} non lascia critiche aperte.",
        "unreviewed": "I twin non hanno ancora criticato questa verifica.",
        "document": "`{document}` contiene {runs} con i passi, le prove e le critiche dei twin.",
        "run_words": ("verifica dei criteri", "verifiche dei criteri"),
    },
}
_TEST_VERDICT_WORDS: Final = {
    "FINE": "the results are fine",
    "CONCERN": "the results raise a concern",
    "DRIFT": "the application departs from what was approved",
}
_LEARNING_TEXTS: Final[dict[str, Any]] = {
    "heading": "## What the twins learned",
    "feedback_heading": "## Learned during development",
    "twin": "{name}, version {label}",
    "nothing": "it has learned nothing yet",
    "none_active": "no active learned observation",
    "index_document": (
        "`{document}` holds what the twins learned during the development, with where every "
        "observation comes from; `ut twins update` proposes new ones from their latest critiques."
    ),
    "active_words": ("active learned observation", "active learned observations"),
    "has": "{twin}, has {count}.",
    "has_nothing": "{twin}, has learned nothing yet.",
    "has_none_active": "{twin}, has no active learned observation.",
    "from_critiques": "from its own critiques, approved by the owner on {when}",
    "from_owner": "written by the owner on {when}",
    "observation": "{code} ({origin}): {statement}",
    "basis": "Basis: {basis}",
    "contradicts": "Warning, it contradicts the profile: {text}",
    "retired_words": ("Retired observation", "Retired observations"),
    "retired": "{words}: {codes}.",
    "no_twin": "No twin has learned anything yet during the development.",
}
