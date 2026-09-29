from __future__ import annotations

from itertools import product
from uuid import UUID, uuid4

import pytest

from orchestwin.artifacts.visual_catalog import (
    ARCHETYPES,
    DISTINCT_VISUAL_DIMENSIONS,
    FONTS,
    NEUTRAL_VISUAL_CHOICES,
    RETIRED_VISUAL_VALUES,
    FontFamily,
    HueFamily,
    VisualChoices,
    hue_families_are_distinct,
    offered_visual_values,
    require_distinct_visual_choices,
    visual_differences,
)
from orchestwin.artifacts.visual_exploration import (
    BACKGROUND_GROUP_SIZE,
    EXPLORED_ALTERNATIVES,
    EXPLORED_DIMENSIONS,
    HEADING_GROUP_SIZE,
    HUE_GROUP_SIZE,
    NON_LIGHT_MODES,
    PAIR_GROUP_SIZE,
    VISUAL_EXPLORATION_VERSION,
    exploration_bindings,
    require_explored_choices,
    visual_exploration,
)

PROJECTS = tuple(UUID(int=index + 1, version=4) for index in range(500))
GROUP_SIZES = {
    "hue_family": HUE_GROUP_SIZE,
    "heading_family": HEADING_GROUP_SIZE,
    "background": BACKGROUND_GROUP_SIZE,
}


def offered(name: str) -> set[str]:
    values = {item.value for item in offered_visual_values(name)}
    if name == "body_family":
        return {value for value in values if FONTS[FontFamily(value)].body_safe}
    return values


def test_exploration_is_deterministic_versioned_and_changes_with_the_project():
    project = uuid4()
    assert VISUAL_EXPLORATION_VERSION == 2
    assert visual_exploration(project) == visual_exploration(project)
    distinct = {repr(visual_exploration(item)) for item in PROJECTS}
    assert len(distinct) == len(PROJECTS)


def test_every_alternative_receives_disjoint_groups_of_offered_values():
    for project in PROJECTS:
        exploration = visual_exploration(project)
        assert tuple(exploration) == EXPLORED_ALTERNATIVES
        first, second = (exploration[code] for code in EXPLORED_ALTERNATIVES)
        for name in EXPLORED_DIMENSIONS:
            assert set(first[name]) <= offered(name) and set(second[name]) <= offered(name)
            assert not set(first[name]) & set(second[name])
            expected = GROUP_SIZES.get(name, PAIR_GROUP_SIZE)
            assert len(first[name]) == len(second[name]) == expected
        assert all(
            hue_families_are_distinct(HueFamily(one), HueFamily(other))
            for one, other in product(first["hue_family"], second["hue_family"])
        )
        assert "color_mode" not in first
        if "color_mode" in second:
            assert second["color_mode"] == tuple(item.value for item in NON_LIGHT_MODES)


def test_no_exploration_offers_a_value_that_is_no_longer_offered():
    retired = {
        name: {item.value for item in RETIRED_VISUAL_VALUES[name]} for name in EXPLORED_DIMENSIONS
    }
    assert retired["background"] == {"DOTS", "GRID", "STRIPES"}
    assert retired["heading_family"] == {"SCRIPT", "MONOSPACE"}
    for project in PROJECTS:
        for dimensions in visual_exploration(project).values():
            for name in EXPLORED_DIMENSIONS:
                assert not set(dimensions[name]) & retired[name]


def test_the_offered_catalog_is_covered_across_projects_and_some_projects_leave_the_light_mode():
    seen = {name: set() for name in EXPLORED_DIMENSIONS}
    backgrounds = set()
    non_light = 0
    for project in PROJECTS:
        exploration = visual_exploration(project)
        non_light += "color_mode" in exploration[EXPLORED_ALTERNATIVES[1]]
        backgrounds.add(tuple(exploration[code]["background"] for code in EXPLORED_ALTERNATIVES))
        for dimensions in exploration.values():
            for name in EXPLORED_DIMENSIONS:
                seen[name].update(dimensions[name])
    for name in EXPLORED_DIMENSIONS:
        assert seen[name] == offered(name)
    assert len(backgrounds) == 6
    assert len(PROJECTS) // 5 < non_light < len(PROJECTS) // 2


def _choices(code, exploration, archetype):
    values = NEUTRAL_VISUAL_CHOICES.to_snapshot()
    for name, allowed in exploration[code].items():
        values[name] = "DARK" if name == "color_mode" else allowed[0]
    values["archetype"] = archetype.value
    values["navigation"] = ARCHETYPES[archetype].navigation[0].value
    return VisualChoices.from_snapshot(values)


def test_every_exploration_admits_two_valid_and_distinct_alternatives():
    archetypes = tuple(ARCHETYPES)
    explored = set(EXPLORED_DIMENSIONS) - {"hue_family"}
    for project in PROJECTS:
        exploration = visual_exploration(project)
        pair = [
            _choices(code, exploration, archetypes[index])
            for index, code in enumerate(EXPLORED_ALTERNATIVES)
        ]
        require_distinct_visual_choices(pair)
        assert explored <= set(visual_differences(*pair))
        assert len(explored) >= DISTINCT_VISUAL_DIMENSIONS
        for code, choices in zip(EXPLORED_ALTERNATIVES, pair, strict=True):
            require_explored_choices(code, choices, exploration)


def test_choices_outside_the_exploration_are_rejected_with_the_dimension_name():
    project = PROJECTS[0]
    exploration = visual_exploration(project)
    code = EXPLORED_ALTERNATIVES[0]
    inside = _choices(code, exploration, next(iter(ARCHETYPES)))
    outside = next(
        item.value for item in HueFamily if item.value not in exploration[code]["hue_family"]
    )
    values = {**inside.to_snapshot(), "hue_family": outside}
    with pytest.raises(ValueError, match=f"{code} must choose hue_family"):
        require_explored_choices(code, VisualChoices.from_snapshot(values), exploration)
    require_explored_choices("DES-003", VisualChoices.from_snapshot(values), exploration)


@pytest.mark.parametrize(
    ("name", "value"),
    [("background", "DOTS"), ("background", "GRID"), ("background", "STRIPES")],
)
def test_a_new_design_cannot_bind_a_value_that_is_no_longer_offered(name, value):
    for project in PROJECTS[:50]:
        exploration = visual_exploration(project)
        for index, code in enumerate(EXPLORED_ALTERNATIVES):
            inside = _choices(code, exploration, tuple(ARCHETYPES)[index])
            retired = VisualChoices.from_snapshot({**inside.to_snapshot(), name: value})
            with pytest.raises(ValueError, match=f"{code} must choose {name}"):
                require_explored_choices(code, retired, exploration)


def test_retired_headings_are_never_bound_to_a_new_design():
    for project in PROJECTS[:50]:
        exploration = visual_exploration(project)
        for index, code in enumerate(EXPLORED_ALTERNATIVES):
            inside = _choices(code, exploration, tuple(ARCHETYPES)[index])
            for heading, tone in (("MONOSPACE", "TECHNICAL"), ("SCRIPT", "ARTISANAL")):
                retired = VisualChoices.from_snapshot(
                    {**inside.to_snapshot(), "heading_family": heading, "tone": tone}
                )
                with pytest.raises(ValueError, match=f"{code} must choose heading_family"):
                    require_explored_choices(code, retired, exploration)


def test_bindings_constrain_only_the_explored_dimensions_of_the_alternative():
    exploration = visual_exploration(PROJECTS[1])
    code = EXPLORED_ALTERNATIVES[0]
    binding = exploration_bindings(exploration, code)
    properties = binding["visual"]["properties"]
    assert set(properties) == set(exploration[code])
    assert properties["hue_family"] == {"enum": list(exploration[code]["hue_family"])}
    assert properties["background"] == {"enum": list(exploration[code]["background"])}
    assert exploration_bindings(exploration, "DES-009") == {}
    assert exploration_bindings({}, code) == {}


def test_new_explorations_never_need_the_script_binding():
    for project in PROJECTS:
        exploration = visual_exploration(project)
        for code in EXPLORED_ALTERNATIVES:
            assert "anyOf" not in exploration_bindings(exploration, code)["visual"]


def test_script_headings_of_an_earlier_exploration_stay_bound_to_their_tones_case_and_modes():
    exploration = {
        "DES-001": {"heading_family": ("SCRIPT", "SLAB_SERIF", "NARROW_SANS")},
        "DES-002": {
            "heading_family": ("SCRIPT", "HUMANIST_SANS", "SYSTEM_UI"),
            "color_mode": tuple(item.value for item in NON_LIGHT_MODES),
        },
    }
    for code in EXPLORED_ALTERNATIVES:
        visual = exploration_bindings(exploration, code)["visual"]
        headings = exploration[code]["heading_family"]
        plain, script = visual["anyOf"]
        assert plain["properties"]["heading_family"]["enum"] == [
            item for item in headings if item != "SCRIPT"
        ]
        rule = script["properties"]
        assert rule["heading_family"] == {"const": "SCRIPT"}
        assert rule["heading_case"] == {"const": "SENTENCE"}
        assert set(rule["tone"]["enum"]) == {"PLAYFUL", "ARTISANAL", "LUXURIOUS", "WARM", "RUSTIC"}
        allowed = exploration[code].get("color_mode", ("LIGHT", "DARK"))
        assert rule["color_mode"]["enum"] == [mode for mode in ("LIGHT", "DARK") if mode in allowed]
