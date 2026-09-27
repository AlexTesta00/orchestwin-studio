from __future__ import annotations

from itertools import product
from uuid import UUID, uuid4

import pytest

from orchestwin.artifacts.visual_catalog import (
    ARCHETYPES,
    FONTS,
    NEUTRAL_VISUAL_CHOICES,
    VISUAL_DIMENSIONS,
    FontFamily,
    HueFamily,
    VisualChoices,
    hue_families_are_distinct,
    require_distinct_visual_choices,
)
from orchestwin.artifacts.visual_exploration import (
    EXPLORED_ALTERNATIVES,
    EXPLORED_DIMENSIONS,
    HEADING_GROUP_SIZE,
    HUE_GROUP_SIZE,
    NON_LIGHT_MODES,
    PAIR_GROUP_SIZE,
    exploration_bindings,
    require_explored_choices,
    visual_exploration,
)

PROJECTS = tuple(UUID(int=index + 1, version=4) for index in range(300))


def test_exploration_is_deterministic_and_changes_with_the_project():
    project = uuid4()
    assert visual_exploration(project) == visual_exploration(project)
    distinct = {repr(visual_exploration(item)) for item in PROJECTS}
    assert len(distinct) == len(PROJECTS)


def test_every_alternative_receives_disjoint_groups_of_catalog_values():
    for project in PROJECTS:
        exploration = visual_exploration(project)
        assert tuple(exploration) == EXPLORED_ALTERNATIVES
        first, second = (exploration[code] for code in EXPLORED_ALTERNATIVES)
        for name in EXPLORED_DIMENSIONS:
            members = set(VISUAL_DIMENSIONS[name].__members__)
            assert set(first[name]) <= members and set(second[name]) <= members
            assert not set(first[name]) & set(second[name])
            expected = {"hue_family": HUE_GROUP_SIZE, "heading_family": HEADING_GROUP_SIZE}.get(
                name, PAIR_GROUP_SIZE
            )
            assert len(first[name]) == len(second[name]) == expected
        assert all(
            hue_families_are_distinct(HueFamily(one), HueFamily(other))
            for one, other in product(first["hue_family"], second["hue_family"])
        )
        readable = {family.value for family, spec in FONTS.items() if spec.body_safe}
        assert set(first["body_family"]) | set(second["body_family"]) <= readable
        assert "color_mode" not in first
        if "color_mode" in second:
            assert second["color_mode"] == tuple(item.value for item in NON_LIGHT_MODES)


def test_the_catalog_is_covered_across_projects_and_some_projects_leave_the_light_mode():
    seen = {name: set() for name in EXPLORED_DIMENSIONS}
    non_light = 0
    for project in PROJECTS:
        exploration = visual_exploration(project)
        non_light += "color_mode" in exploration[EXPLORED_ALTERNATIVES[1]]
        for dimensions in exploration.values():
            for name in EXPLORED_DIMENSIONS:
                seen[name].update(dimensions[name])
    for name in EXPLORED_DIMENSIONS:
        expected = set(VISUAL_DIMENSIONS[name].__members__)
        if name == "body_family":
            expected = {family.value for family, spec in FONTS.items() if spec.body_safe}
        assert seen[name] == expected
    assert len(PROJECTS) // 5 < non_light < len(PROJECTS) // 2


def _choices(code, exploration, archetype):
    values = NEUTRAL_VISUAL_CHOICES.to_snapshot()
    for name, allowed in exploration[code].items():
        if name == "heading_family":
            values[name] = next(item for item in allowed if item != FontFamily.SCRIPT.value)
        elif name == "color_mode":
            values[name] = "DARK"
        else:
            values[name] = allowed[0]
    values["archetype"] = archetype.value
    values["navigation"] = ARCHETYPES[archetype].navigation[0].value
    return VisualChoices.from_snapshot(values)


def test_every_exploration_admits_two_valid_and_distinct_alternatives():
    archetypes = tuple(ARCHETYPES)
    for project in PROJECTS:
        exploration = visual_exploration(project)
        pair = [
            _choices(code, exploration, archetypes[index])
            for index, code in enumerate(EXPLORED_ALTERNATIVES)
        ]
        require_distinct_visual_choices(pair)
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


def test_bindings_constrain_only_the_explored_dimensions_of_the_alternative():
    exploration = visual_exploration(PROJECTS[1])
    code = EXPLORED_ALTERNATIVES[0]
    binding = exploration_bindings(exploration, code)
    properties = binding["visual"]["properties"]
    assert set(properties) == set(exploration[code])
    assert properties["hue_family"] == {"enum": list(exploration[code]["hue_family"])}
    assert exploration_bindings(exploration, "DES-009") == {}
    assert exploration_bindings({}, code) == {}


def test_script_headings_are_bound_to_their_tones_case_and_modes():
    found = 0
    for project in PROJECTS:
        exploration = visual_exploration(project)
        for code in EXPLORED_ALTERNATIVES:
            visual = exploration_bindings(exploration, code)["visual"]
            headings = exploration[code]["heading_family"]
            if "SCRIPT" not in headings:
                assert "anyOf" not in visual
                continue
            found += 1
            plain, script = visual["anyOf"]
            assert plain["properties"]["heading_family"]["enum"] == [
                item for item in headings if item != "SCRIPT"
            ]
            rule = script["properties"]
            assert rule["heading_family"] == {"const": "SCRIPT"}
            assert rule["heading_case"] == {"const": "SENTENCE"}
            assert set(rule["tone"]["enum"]) == {
                "PLAYFUL",
                "ARTISANAL",
                "LUXURIOUS",
                "WARM",
                "RUSTIC",
            }
            allowed = exploration[code].get("color_mode", ("LIGHT", "DARK"))
            assert rule["color_mode"]["enum"] == [
                mode for mode in ("LIGHT", "DARK") if mode in allowed
            ]
            assert rule["color_mode"]["enum"]
    assert found > 0
