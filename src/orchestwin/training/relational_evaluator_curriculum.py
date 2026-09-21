"""Synthetic relational HTML curriculum, with grouped unseen tasks and structures.

The oracle covers this deliberately closed fixture grammar. It is not a browser
accessible-name implementation or evidence of actual user performance.
"""

from __future__ import annotations

import random
from html import escape
from xml.etree import ElementTree

from orchestwin.evaluation.artifact_content import artifact_content_instruction
from orchestwin.evaluation.field_scope_prompt import field_scope_instruction
from orchestwin.evaluation.model_evaluator import _system_instruction
from orchestwin.training.grounded_evaluator_curriculum import FAMILIES, SCHEMA, example

CURRICULUM_ID = "grounded-evaluator-relational-calibration-v2"
INSTRUCTION = artifact_content_instruction(field_scope_instruction(_system_instruction(), SCHEMA))


def oracle(raw: str | None, family: str, target: str) -> str:
    if family not in FAMILIES:
        raise ValueError("unknown calibration family")
    if raw is None:
        return "INSUFFICIENT"
    root = ElementTree.fromstring(raw)
    matches = [e for e in root.iter() if e.get("id") == target]
    if len(matches) != 1:
        return "INSUFFICIENT"
    element = matches[0]

    def text(element):
        return "".join(element.itertext()).strip()

    if family == "button_name":
        references = element.get("aria-labelledby", "").split()
        named = [e for e in root.iter() if e.get("id") in references]
        present = bool(
            any(text(e) for e in named) or element.get("aria-label", "").strip() or text(element)
        )
    elif family == "input_label":
        present = any(e.tag == "label" and e.get("for") == target and text(e) for e in root.iter())
    elif family == "image_text":
        present = bool(element.get("alt", "").strip())
    elif family == "document_language":
        present = element is root and root.tag == "html" and bool(root.get("lang", "").strip())
    else:
        present = bool(text(element))
    return "PRESENT" if present else "MISSING"


def render(family, target, task, locale, state, variant):
    """Hold styles 6 and 7 out with their task phrases, across all families."""
    style = variant % 8
    present = state == "PRESENT"
    label_id = target + "-label"
    text = escape(task)
    blank = ("", " ", "\t", "\n ")[variant % 4]
    value = text if present else blank
    nested = f"<span><strong>{value}</strong></span>"
    document_id = target if family == "document_language" else "document"
    if family == "button_name":
        if style in {0, 4}:
            snippet = f'<button id="{target}" aria-label="{value}"></button>'
        elif style in {1, 5}:
            snippet = f'<button id="{target}">{nested}</button>'
        else:
            # Missing cases include both broken references and references to empty text.
            referenced = label_id if present or style == 3 else target + "-absent"
            labels = f'<span id="{label_id}">{nested}</span>'
            ids = referenced if style != 7 else f"{target}-absent {referenced}"
            button = f'<button id="{target}" aria-labelledby="{ids}"></button>'
            snippet = labels + button if style < 6 else button + f"<aside>{labels}</aside>"
    elif family == "input_label":
        associated = target if present or style in {0, 3} else target + "-other"
        label_text = nested if present or associated == target else f"<span>{text}</span>"
        label = f'<label for="{associated}">{label_text}</label>'
        control = f'<input id="{target}" />'
        snippet = label + control if style < 6 else control + f"<section>{label}</section>"
    elif family == "image_text":
        snippet = f'<figure><img id="{target}" src="diagram.png" alt="{value}" /></figure>'
    elif family == "document_language":
        snippet = f'<section lang="{locale}"><p>{text}</p></section>'
    else:
        tag = "h1" if family == "heading" else "p"
        role = ' role="alert"' if family == "error_guidance" else ""
        snippet = f'<{tag} id="{target}"{role}>{nested}</{tag}>'
    distractors = (
        f'<button id="other-button">{text}</button><label for="other-field">{text}</label>'
        '<input id="other-field" /><img src="other.png" alt="Other" />'
        '<p role="alert">Try again</p><h1>Other heading</h1>'
    )
    language = locale if family != "document_language" or present else blank
    raw = f'<html id="{document_id}" lang="{language}"><body><main>{snippet}{distractors}</main></body></html>'
    if state == "INSUFFICIENT":
        if (variant // 8) % 2:
            return raw, None
        raw = f'<section id="unrelated-fragment">{distractors}</section>'
    return raw, raw


def build_curriculum(*, seed: int = 20260915, variants: int = 32) -> list[dict]:
    if not 16 <= variants <= 256 or variants % 8:
        raise ValueError("relational calibration needs a multiple of eight variants, at least 16")
    rows = []
    for family in FAMILIES:
        for variant in range(variants):
            split = "test" if variant % 8 == 7 else "validation" if variant % 8 == 6 else "train"
            for locale in ("en", "it"):
                for state in ("INSUFFICIENT", "MISSING", "PRESENT"):
                    row = example(
                        seed=seed,
                        family=family,
                        variant=variant,
                        locale=locale,
                        state=state,
                        curriculum_id=CURRICULUM_ID,
                        render=render,
                        classify=oracle,
                        instruction=INSTRUCTION,
                    )
                    row.update(split=split, structure_family=variant % 8)
                    rows.append(row)
    random.Random(seed).shuffle(rows)
    return rows
