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


def result_prototype():
    prototype = deepcopy(PROTOTYPE)
    prototype["screens"][1]["elements"].insert(
        0, {"id": "output", "code": "ELM-005", "kind": "TEXT", "content": "Dynamic result"}
    )
    return prototype


@pytest.mark.parametrize(
    "tag,value", [("output", ""), ("p", "12"), ("span", "Saved"), ("pre", "[]")]
)
def test_accepts_dynamic_result_without_requiring_placeholder_text(tag, value):
    html = HTML.replace(
        "<output>0</output>", f'<{tag} data-design-element="ELM-005">{value}</{tag}>'
    )
    validate_prototype_html(html, result_prototype())


@pytest.mark.parametrize(
    "markup",
    [
        '<ul><li data-design-element="ELM-005">12</li></ul>',
        '<dl><dt data-design-element="ELM-005">Result</dt><dd>12</dd></dl>',
        '<dl><dt>Result</dt><dd data-design-element="ELM-005">12</dd></dl>',
        '<table><tr><td data-design-element="ELM-005">12</td></tr></table>',
        '<table><tr><th data-design-element="ELM-005">Result</th></tr></table>',
        '<table><caption data-design-element="ELM-005">Result</caption></table>',
        '<figure><figcaption data-design-element="ELM-005">12</figcaption></figure>',
    ],
)
def test_accepts_semantic_text_containers_in_the_selected_screen(markup):
    validate_prototype_html(HTML.replace("<output>0</output>", markup), result_prototype())


@pytest.mark.parametrize(
    "result_markup",
    [
        "<output>0</output>",
        '<output data-design-element="ELM-005">0</output><p data-design-element="ELM-005">0</p>',
        '<a data-design-element="ELM-005">0</a>',
        '<script data-design-element="ELM-005">0</script>',
    ],
)
def test_rejects_missing_duplicate_or_nontext_result_marker(result_markup):
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        validate_prototype_html(
            HTML.replace("<output>0</output>", result_markup), result_prototype()
        )


def test_rejects_result_marker_in_wrong_screen():
    html = HTML.replace("<output>0</output>", "").replace(
        "</section>", '<output data-design-element="ELM-005">0</output></section>', 1
    )
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        validate_prototype_html(html, result_prototype())


def test_rejects_result_after_back_when_mockup_places_it_before():
    html = HTML.replace("<output>0</output>", "").replace(
        "</a>", '</a><output data-design-element="ELM-005">0</output>'
    )
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        validate_prototype_html(html, result_prototype())


@pytest.mark.parametrize(
    "extra", ['<p id="number">Other</p>', '<a id="back">Back</a><a id="back">Again</a>']
)
def test_rejects_duplicate_html_ids_even_on_extra_controls(extra):
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        validate_prototype_html(HTML + extra, PROTOTYPE)


def test_accepts_unique_html_ids_on_extra_controls():
    validate_prototype_html(
        HTML + '<p id="error">Invalid input</p><span id="hint">Help</span>', PROTOTYPE
    )
