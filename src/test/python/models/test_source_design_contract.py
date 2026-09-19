from copy import deepcopy

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_design_contract import validate_prototype_html

PROTOTYPE = {
    "screens": [
        {
            "id": "input",
            "code": "SCR-001",
            "elements": [
                {
                    "id": "number",
                    "code": "ELM-001",
                    "kind": "TEXT_INPUT",
                    "content": "Numero",
                    "field_name": "number",
                    "required": True,
                },
                {
                    "id": "operation",
                    "code": "ELM-002",
                    "kind": "SELECT",
                    "content": "Operazione",
                    "field_name": "operation",
                    "required": True,
                    "options": ["Addizione", "Sottrazione"],
                },
                {"id": "calculate", "code": "ELM-003", "kind": "BUTTON", "content": "Calcola"},
            ],
        },
        {
            "id": "result",
            "code": "SCR-002",
            "elements": [
                {"id": "back", "code": "ELM-004", "kind": "LINK", "content": "Torna"},
            ],
        },
    ],
    "transitions": [
        {"trigger_element_id": "calculate", "target_screen_id": "result"},
        {"trigger_element_id": "back", "target_screen_id": "input"},
    ],
}
HTML = """<section data-design-screen="SCR-001">
<label for="number">Numero</label><input id="number" name="number" required data-design-element="ELM-001">
<select name="operation" aria-label="Operazione" required data-design-element="ELM-002"><option disabled>—</option><option>Addizione</option><option>Sottrazione</option></select>
<button data-design-element="ELM-003" data-design-target="SCR-002">Calcola</button>
</section><section data-design-screen="SCR-002"><output>0</output><a data-design-element="ELM-004" data-design-target="SCR-001">Torna</a></section>"""


def test_accepts_selected_controls_and_screens_without_changing_content():
    prototype = deepcopy(PROTOTYPE)
    validate_prototype_html(HTML, prototype)
    assert prototype == PROTOTYPE


def test_wrapping_label_does_not_include_select_option_values():
    html = HTML.replace(
        '<select name="operation" aria-label="Operazione"',
        '<label>Operazione<select name="operation"',
    ).replace("</select>", "</select></label>")
    validate_prototype_html(html, PROTOTYPE)


@pytest.mark.parametrize(
    "before,after",
    [
        ("<select ", "<button "),
        ('name="number"', 'name="different"'),
        (" required", ""),
        ("<option>Sottrazione</option>", "<option>Divisione</option>"),
        ('data-design-screen="SCR-002"', 'data-design-screen="SCR-001"'),
        ('data-design-target="SCR-002"', 'data-design-target="SCR-001"'),
        (">Calcola</button>", ">Invia</button>"),
        ('data-design-element="ELM-004"', 'data-design-element="ELM-003"'),
    ],
)
def test_rejects_redesigned_or_missing_controls(before, after):
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        validate_prototype_html(HTML.replace(before, after), PROTOTYPE)


def test_rejects_control_moved_to_another_screen():
    moved = HTML.replace('</section><section data-design-screen="SCR-002">', "")
    moved = moved.replace("<button ", '</section><section data-design-screen="SCR-002"><button ')
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        validate_prototype_html(moved, PROTOTYPE)
