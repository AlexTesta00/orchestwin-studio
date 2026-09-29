from __future__ import annotations

from copy import deepcopy

TRICKY = 'Nome "vero" <b>x</b> & 50% #1; [a] (b) {c} | ; : perché `sì` \\ fine'
TWIN_ONE = {
    "twin_id": "00000000-0000-4000-8000-0000000000a1",
    "version_number": 1,
    "content_hash": "a" * 64,
    "name": "Addetti all'accoglienza",
}
TWIN_TWO = {
    "twin_id": "00000000-0000-4000-8000-0000000000a2",
    "version_number": 1,
    "content_hash": "b" * 64,
    "name": "Organizzatori volontari",
}
REQ_ONE = "00000000-0000-4000-8000-000000000101"
REQ_TWO = "00000000-0000-4000-8000-000000000102"
REQ_THREE = "00000000-0000-4000-8000-000000000103"
STORY_ONE = "00000000-0000-4000-8000-000000000201"
STORY_TWO = "00000000-0000-4000-8000-000000000202"
CRITERION_ONE = "00000000-0000-4000-8000-000000000301"
SCENARIO_ONE = "00000000-0000-4000-8000-000000000401"
RISK_ONE = "00000000-0000-4000-8000-000000000501"
DONE_ONE = "00000000-0000-4000-8000-000000000601"
ALTERNATIVE_ONE = "00000000-0000-4000-8000-000000000701"
ALTERNATIVE_TWO = "00000000-0000-4000-8000-000000000702"
SCREEN_ONE = "00000000-0000-4000-8000-000000000801"
SCREEN_TWO = "00000000-0000-4000-8000-000000000802"
ELEMENT_ONE = "00000000-0000-4000-8000-000000000901"
ELEMENT_TWO = "00000000-0000-4000-8000-000000000902"
ELEMENT_THREE = "00000000-0000-4000-8000-000000000903"


def specification() -> dict[str, object]:
    return deepcopy(
        {
            "schema_version": 1,
            "user_twin_references": [TWIN_ONE, TWIN_TWO],
            "requirements": [
                {
                    "id": REQ_ONE,
                    "code": "REQ-001",
                    "title": "Aggiunta ospite",
                    "statement": "Inserire il nome di un ospite e aggiungerlo alla lista",
                    "kind": "FUNCTIONAL",
                    "priority": "MUST",
                    "user_twin_references": [TWIN_ONE],
                },
                {
                    "id": REQ_TWO,
                    "code": "REQ-002",
                    "title": TRICKY,
                    "statement": TRICKY,
                    "kind": "NON_FUNCTIONAL",
                    "priority": "SHOULD",
                    "user_twin_references": [],
                },
                {
                    "id": REQ_THREE,
                    "code": "REQ-003",
                    "title": "Nessun backend",
                    "statement": "Applicazione web statica senza backend",
                    "kind": "CONSTRAINT",
                    "priority": "MUST",
                    "user_twin_references": [],
                },
            ],
            "user_stories": [
                {
                    "id": STORY_ONE,
                    "code": "USR-001",
                    "goal": "Aggiungere ospiti per nome",
                    "benefit": "Gestire la lista durante l'evento",
                    "user_twin_reference": TWIN_ONE,
                    "requirement_ids": [REQ_ONE],
                },
                {
                    "id": STORY_TWO,
                    "code": "USR-002",
                    "goal": TRICKY,
                    "benefit": "Vedere la lista aggiornata",
                    "user_twin_reference": TWIN_TWO,
                    "requirement_ids": [REQ_ONE, REQ_TWO],
                },
            ],
            "acceptance_criteria": [
                {
                    "id": CRITERION_ONE,
                    "code": "AC-001",
                    "statement": "L'applicazione aggiunge un ospite e rifiuta i nomi vuoti",
                    "verification_method": "DEMONSTRATION",
                    "requirement_ids": [REQ_ONE],
                    "user_story_ids": [STORY_ONE],
                }
            ],
            "scenarios": [
                {
                    "id": SCENARIO_ONE,
                    "code": "SCN-001",
                    "title": "Aggiunta di tre ospiti",
                    "actor": TWIN_ONE,
                    "requirement_ids": [REQ_ONE],
                    "acceptance_criterion_ids": [CRITERION_ONE],
                }
            ],
            "risks": [
                {
                    "id": RISK_ONE,
                    "code": "RSK-001",
                    "summary": "Nomi duplicati",
                    "impact": "CRITICAL",
                    "likelihood": "POSSIBLE",
                    "requirement_ids": [REQ_ONE],
                }
            ],
            "definition_of_done": [
                {
                    "id": DONE_ONE,
                    "code": "DOD-001",
                    "statement": "Un volontario aggiunge tre ospiti e li vede in lista",
                    "verification_method": "DEMONSTRATION",
                    "requirement_ids": [REQ_ONE, REQ_TWO],
                }
            ],
        }
    )


def workflow(code: str, title: str, steps: list[str], requirements: list[str]) -> dict:
    return {
        "id": f"00000000-0000-4000-8000-0000000010{code[-2:]}",
        "code": code,
        "title": title,
        "steps": steps,
        "requirement_ids": requirements,
        "user_story_ids": [STORY_ONE],
    }


def package() -> dict[str, object]:
    return deepcopy(
        {
            "schema_version": 1,
            "owner_selected_alternative_id": ALTERNATIVE_ONE,
            "recommended_alternative_id": ALTERNATIVE_TWO,
            "alternatives": [
                {
                    "id": ALTERNATIVE_ONE,
                    "code": "DES-001",
                    "title": "Lista ospiti a passi guidati",
                    "workflows": [
                        workflow(
                            "FLOW-001",
                            "Aggiunta di un ospite",
                            ["Inserire il nome", TRICKY, "Vedere la lista aggiornata"],
                            [REQ_ONE, REQ_TWO],
                        )
                    ],
                },
                {
                    "id": ALTERNATIVE_TWO,
                    "code": "DES-002",
                    "title": "Lista ospiti a scheda unica",
                    "workflows": [
                        workflow("FLOW-001", "Aggiunta rapida", ["Inserire il nome"], [REQ_ONE])
                    ],
                },
            ],
            "prototype": {
                "code": "PRT-001",
                "design_alternative_id": ALTERNATIVE_ONE,
                "entry_screen_id": SCREEN_ONE,
                "screens": [
                    {
                        "id": SCREEN_ONE,
                        "code": "SCR-001",
                        "title": "Aggiungi ospite",
                        "state": "DEFAULT",
                        "requirement_ids": [REQ_ONE],
                        "elements": [
                            {
                                "id": ELEMENT_ONE,
                                "code": "ELM-001",
                                "content": "Aggiungi",
                                "requirement_ids": [REQ_ONE],
                            }
                        ],
                    },
                    {
                        "id": SCREEN_TWO,
                        "code": "SCR-002",
                        "title": TRICKY,
                        "state": "SUCCESS",
                        "requirement_ids": [],
                        "elements": [
                            {
                                "id": ELEMENT_TWO,
                                "code": "ELM-002",
                                "content": TRICKY,
                                "requirement_ids": [REQ_TWO],
                            },
                            {
                                "id": ELEMENT_THREE,
                                "code": "ELM-003",
                                "content": "Lista",
                                "requirement_ids": [],
                            },
                        ],
                    },
                ],
                "transitions": [
                    {
                        "code": "TRN-001",
                        "source_screen_id": SCREEN_ONE,
                        "target_screen_id": SCREEN_TWO,
                        "trigger_element_id": ELEMENT_ONE,
                        "outcome": "aggiungi",
                    },
                    {
                        "code": "TRN-002",
                        "source_screen_id": SCREEN_TWO,
                        "target_screen_id": SCREEN_ONE,
                        "trigger_element_id": ELEMENT_TWO,
                        "outcome": "Torna all'inserimento",
                    },
                ],
            },
        }
    )
