from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import replace
from functools import partial
from itertools import product
from types import MappingProxyType
from uuid import UUID

import pytest

from orchestwin.artifacts import visual_directions
from orchestwin.artifacts.design_packages import DesignExplorationPackage
from orchestwin.artifacts.design_realignment import _realigned_alternative, _realigned_language
from orchestwin.artifacts.visual_catalog import (
    NEUTRAL_VISUAL_CHOICES,
    VISUAL_DIMENSIONS,
    BorderWeight,
    ColorMode,
    SurfaceTone,
    offered_visual_values,
    resolve_visual_tokens,
)
from orchestwin.artifacts.visual_directions import (
    AXIS_BINDINGS,
    AXIS_DEFINITIONS,
    DIRECTION_AXES,
    DIRECTION_AXIS_VALUES,
    DIRECTION_CANDIDATES,
    HABITUAL_AXES,
    MAX_DIRECTION_CONCEPT_LENGTH,
    MAX_DIRECTION_NAME_LENGTH,
    MAX_DIRECTION_RULE_LENGTH,
    MAX_DIRECTION_RULES,
    MIN_DIRECTION_DISTANCE,
    MIN_DIRECTION_RULES,
    VISUAL_DIRECTIONS_CONTENT_HASH,
    VISUAL_DIRECTIONS_VERSION,
    DirectionAxes,
    DirectionColour,
    DirectionDensity,
    DirectionLayout,
    DirectionShape,
    DirectionType,
    VisualDirection,
    create_visual_direction,
    differing_axes,
    direction_distance,
    direction_exploration,
    direction_tokens,
    select_directions,
    visual_direction_from_snapshot,
    visual_directions_snapshot,
)
from orchestwin.artifacts.visual_exploration import visual_exploration
from orchestwin.artifacts.visual_fonts import bundled_font_tokens
from orchestwin.artifacts.visual_language import (
    _TOKEN_NAME,
    VisualLanguage,
    _plain_css_value,
    create_visual_language,
)
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

from . import design_fixtures

STORED_DIRECTIONS_HASH = "b298850d85a2b7465658dca275b3a626e8968897c655418962d3050b76ba27d0"
CONCEPT = (
    "A page set like a printed register, with a masthead and ruled groups. It suits careful "
    "readers who compare entries on a wide screen."
)
RULES = (
    "The title of every screen stands alone below the masthead, at the display size.",
    "Thin rules separate the groups of content; no group is enclosed in a box.",
    "The main action is a solid button in the primary colour, the only coloured element.",
)
EDITORIAL_AXES = DirectionAxes(
    layout=DirectionLayout.EDITORIAL,
    shape=DirectionShape.SQUARE_RULES,
    type=DirectionType.DISPLAY,
    colour=DirectionColour.INK,
    density=DirectionDensity.SPACIOUS,
)
AXIS_IDS = {
    "layout": ("PANELS", "BANDS", "EDITORIAL", "STAGE", "WORKBENCH", "MOSAIC"),
    "shape": ("ROUNDED_OUTLINE", "SQUARE_RULES", "HEAVY_FRAME", "SOFT_FILL", "PILL"),
    "type": ("EVEN", "DISPLAY", "CAPS_LABELS", "READING"),
    "colour": ("ACCENT_ONLY", "FIELDS", "INK", "TINTED"),
    "density": ("COMPACT", "COMFORTABLE", "SPACIOUS"),
}
DEFINITIONS = {
    "layout": {
        "PANELS": (
            "a header bar, a title row and the content grouped in bordered panels arranged in "
            "a grid"
        ),
        "BANDS": (
            "a stack of full-width horizontal bands, each with its own background and one "
            "purpose, without cards"
        ),
        "EDITORIAL": (
            "a printed page: a masthead, one wide column and one narrow side column, groups "
            "separated by rules and white space, without cards"
        ),
        "STAGE": (
            "one centred column with a single task or object at a time, large and calm, "
            "everything else small around it"
        ),
        "WORKBENCH": (
            "a tool surface that uses the whole width: a slim toolbar, dense rows or tables from "
            "edge to edge, filters or details in a side column"
        ),
        "MOSAIC": (
            "a grid of tiles of clearly different sizes, where the size of a tile says how much "
            "it matters"
        ),
    },
    "shape": {
        "ROUNDED_OUTLINE": "rounded corners and thin outlines around panels and controls",
        "SQUARE_RULES": (
            "square corners, with thin rules above or below the groups instead of boxes around them"
        ),
        "HEAVY_FRAME": "thick frames in the text colour and hard offset shadows without blur",
        "SOFT_FILL": "filled surfaces without borders, told apart by their tone and by space",
        "PILL": "pill-shaped controls, very large radii and surfaces that float on a soft shadow",
    },
    "type": {
        "EVEN": "a restrained scale: titles a little larger than the text, hierarchy from weight",
        "DISPLAY": (
            "a very large and heavy title on every screen, four times the text size, with "
            "everything else small"
        ),
        "CAPS_LABELS": (
            "small upper-case labels with wide tracking above their values, numbers in a "
            "monospace face aligned in columns"
        ),
        "READING": "a larger text size, a generous line height and a narrow measure, as in a book",
    },
    "colour": {
        "ACCENT_ONLY": (
            "neutral surfaces, with the primary colour only on the main action and on the "
            "current state"
        ),
        "FIELDS": (
            "large flat fields of the primary colour: whole bands, tiles or headers are filled "
            "with it"
        ),
        "INK": (
            "almost monochrome: text colour on the background, with the primary colour only as "
            "a small mark"
        ),
        "TINTED": (
            "tinted surfaces everywhere: groups sit on soft tints of the primary colour, with "
            "few borders"
        ),
    },
    "density": {
        "COMPACT": "tight spacing and small controls, many rows visible at once",
        "COMFORTABLE": "balanced spacing and controls of a standard height",
        "SPACIOUS": "generous spacing, large controls, few things on a screen",
    },
}
BINDINGS = {
    "layout": {
        "PANELS": {"header": ("COMPACT_BAR", "MINIMAL")},
        "BANDS": {"header": ("HERO_BAND",)},
        "EDITORIAL": {"header": ("MINIMAL", "CENTERED_TITLE")},
        "STAGE": {"header": ("CENTERED_TITLE", "MINIMAL")},
        "WORKBENCH": {"header": ("COMPACT_BAR",)},
        "MOSAIC": {"header": ("MINIMAL", "COMPACT_BAR")},
    },
    "shape": {
        "ROUNDED_OUTLINE": {
            "corners": ("SOFT", "ROUND"),
            "borders": ("HAIRLINE",),
            "elevation": ("FLAT", "SUBTLE"),
        },
        "SQUARE_RULES": {"corners": ("SHARP",), "borders": ("HAIRLINE",), "elevation": ("FLAT",)},
        "HEAVY_FRAME": {
            "corners": ("SHARP", "SOFT"),
            "borders": ("BOLD",),
            "elevation": ("FLAT",),
        },
        "SOFT_FILL": {
            "corners": ("SOFT", "ROUND"),
            "borders": ("NONE", "HAIRLINE"),
            "elevation": ("FLAT",),
        },
        "PILL": {
            "corners": ("PILL",),
            "borders": ("NONE", "HAIRLINE"),
            "elevation": ("SUBTLE", "RAISED"),
        },
    },
    "type": {
        "EVEN": {"type_scale": ("COMPACT", "REGULAR"), "heading_weight": ("REGULAR", "SEMIBOLD")},
        "DISPLAY": {
            "type_scale": ("DISPLAY",),
            "heading_weight": ("SEMIBOLD", "BLACK"),
            "heading_case": ("SENTENCE", "UPPERCASE"),
        },
        "CAPS_LABELS": {
            "type_scale": ("COMPACT", "REGULAR"),
            "heading_case": ("UPPERCASE", "SMALL_CAPS"),
        },
        "READING": {
            "type_scale": ("REGULAR", "DISPLAY"),
            "heading_case": ("SENTENCE",),
            "heading_weight": ("REGULAR", "SEMIBOLD"),
        },
    },
    "colour": {
        "ACCENT_ONLY": {
            "emphasis": ("RESTRAINED", "BALANCED"),
            "background": ("PLAIN", "GRADIENT"),
        },
        "FIELDS": {"emphasis": ("BOLD",), "background": ("PLAIN",)},
        "INK": {"emphasis": ("RESTRAINED",), "background": ("PLAIN",)},
        "TINTED": {
            "emphasis": ("BALANCED", "BOLD"),
            "background": ("TINTED", "GRADIENT"),
            "surface_tone": ("TINTED", "WARM", "COOL"),
        },
    },
    "density": {
        "COMPACT": {"density": ("COMPACT",)},
        "COMFORTABLE": {"density": ("COMFORTABLE",)},
        "SPACIOUS": {"density": ("SPACIOUS",)},
    },
}
TEXT = "TEXT"
TOKENS = {
    "layout": {
        "PANELS": {"--vl-content-width": "1200px"},
        "BANDS": {"--vl-content-width": "1120px"},
        "EDITORIAL": {"--vl-content-width": "1080px"},
        "STAGE": {"--vl-content-width": "640px"},
        "WORKBENCH": {"--vl-content-width": "1600px"},
        "MOSAIC": {"--vl-content-width": "1280px"},
    },
    "shape": {
        "ROUNDED_OUTLINE": {},
        "SQUARE_RULES": {
            "--vl-radius-control": "0px",
            "--vl-radius-panel": "0px",
            "--vl-border-width": "1px",
            "--vl-shadow": "none",
        },
        "HEAVY_FRAME": {"--vl-border-width": "3px", "--vl-shadow": f"6px 6px 0 {TEXT}"},
        "SOFT_FILL": {"--vl-shadow": "none"},
        "PILL": {"--vl-radius-panel": "28px"},
    },
    "type": {
        "EVEN": {"--vl-line-height-heading": "1.2"},
        "DISPLAY": {
            "--vl-size-display": "72px",
            "--vl-size-display-narrow": "40px",
            "--vl-size-title": "22px",
            "--vl-line-height-heading": "1.02",
        },
        "CAPS_LABELS": {
            "--vl-size-label": "12px",
            "--vl-label-tracking": "0.1em",
            "--vl-line-height-heading": "1.15",
        },
        "READING": {
            "--vl-size-body": "18px",
            "--vl-line-height": "1.7",
            "--vl-measure": "66ch",
            "--vl-line-height-heading": "1.25",
        },
    },
    "colour": {"ACCENT_ONLY": {}, "FIELDS": {}, "INK": {}, "TINTED": {}},
    "density": {
        "COMPACT": {"--vl-section-gap": "24px"},
        "COMFORTABLE": {"--vl-section-gap": "48px"},
        "SPACIOUS": {"--vl-section-gap": "88px"},
    },
}
EVERY_AXES = tuple(
    DirectionAxes(layout=layout, shape=shape, type=kind, colour=colour, density=density)
    for layout, shape, kind, colour, density in product(*DIRECTION_AXIS_VALUES.values())
)


def axes(layout: str, shape: str, kind: str, colour: str, density: str) -> DirectionAxes:
    return DirectionAxes(layout=layout, shape=shape, type=kind, colour=colour, density=density)


def direction(**changes: object) -> VisualDirection:
    arguments: dict[str, object] = {
        "name": "Printed register",
        "concept": CONCEPT,
        "rules": RULES,
        "axes": EDITORIAL_AXES,
        "typicality": 12,
        "candidates": DIRECTION_CANDIDATES,
        **changes,
    }
    return create_visual_direction(**arguments)


def directed_language(
    language: VisualLanguage, value: VisualDirection | None = None
) -> VisualLanguage:
    return create_visual_language(
        choices=language.choices,
        product_name=language.product_name,
        rationale=language.rationale,
        twin_fit=language.twin_fit,
        direction=direction() if value is None else value,
    )


def directed_package(
    package: DesignExplorationPackage, value: VisualDirection | None = None
) -> DesignExplorationPackage:
    return replace(
        package,
        alternatives=tuple(
            item
            if item.visual_language is None
            else replace(item, visual_language=directed_language(item.visual_language, value))
            for item in package.alternatives
        ),
    )


def expected_tokens(chosen: DirectionAxes, text: str) -> dict[str, str]:
    expected: dict[str, str] = {}
    for axis in DIRECTION_AXES:
        for name, value in TOKENS[axis][getattr(chosen, axis).value].items():
            expected[name] = value.replace(TEXT, text)
    return expected


def admits_valid_choices(bound: dict[str, tuple[str, ...]], mode: ColorMode) -> bool:
    names = tuple(bound)
    for values in product(*(bound[name] for name in names)):
        with suppress(ValueError):
            replace(
                NEUTRAL_VISUAL_CHOICES, color_mode=mode, **dict(zip(names, values, strict=True))
            )
            return True
    return False


def test_the_vocabulary_has_the_axes_values_and_limits_of_the_contract() -> None:
    assert VISUAL_DIRECTIONS_VERSION == 1
    assert DIRECTION_AXES == ("layout", "shape", "type", "colour", "density")
    assert tuple(DIRECTION_AXIS_VALUES) == DIRECTION_AXES
    assert tuple(DIRECTION_AXIS_VALUES.values()) == (
        DirectionLayout,
        DirectionShape,
        DirectionType,
        DirectionColour,
        DirectionDensity,
    )
    assert {
        axis: tuple(item.value for item in values) for axis, values in DIRECTION_AXIS_VALUES.items()
    } == AXIS_IDS
    assert all(
        item.name == item.value for values in DIRECTION_AXIS_VALUES.values() for item in values
    )
    assert (MIN_DIRECTION_DISTANCE, DIRECTION_CANDIDATES) == (4, 5)
    assert (MAX_DIRECTION_NAME_LENGTH, MAX_DIRECTION_CONCEPT_LENGTH) == (60, 400)
    assert (MIN_DIRECTION_RULES, MAX_DIRECTION_RULES, MAX_DIRECTION_RULE_LENGTH) == (3, 5, 240)
    assert HABITUAL_AXES.to_snapshot() == {
        "layout": "PANELS",
        "shape": "ROUNDED_OUTLINE",
        "type": "EVEN",
        "colour": "ACCENT_ONLY",
        "density": "COMFORTABLE",
    }
    with pytest.raises(TypeError):
        DIRECTION_AXIS_VALUES["layout"] = DirectionShape


def test_the_axis_definitions_are_the_texts_of_the_contract() -> None:
    assert tuple(AXIS_DEFINITIONS) == DIRECTION_AXES
    assert {
        axis: {value.value: text for value, text in texts.items()}
        for axis, texts in AXIS_DEFINITIONS.items()
    } == DEFINITIONS
    for axis, texts in AXIS_DEFINITIONS.items():
        assert tuple(texts) == tuple(DIRECTION_AXIS_VALUES[axis])
    with pytest.raises(TypeError):
        AXIS_DEFINITIONS["layout"][DirectionLayout.PANELS] = "a page"


def test_axes_coerce_their_ids_and_reject_unknown_values() -> None:
    coerced = axes("EDITORIAL", "SQUARE_RULES", "DISPLAY", "INK", "SPACIOUS")
    snapshot = coerced.to_snapshot()

    assert coerced == EDITORIAL_AXES
    assert all(
        type(getattr(coerced, axis)) is DIRECTION_AXIS_VALUES[axis] for axis in DIRECTION_AXES
    )
    assert list(snapshot) == list(DIRECTION_AXES)
    assert all(type(value) is str for value in snapshot.values())
    assert DirectionAxes.from_snapshot(snapshot) == coerced
    assert DirectionAxes.from_snapshot(dict(reversed(snapshot.items()))) == coerced
    for value in ("NEON", "panels", 1, None, DirectionShape.PILL):
        with pytest.raises(ValueError, match="unknown visual direction value for layout"):
            replace(coerced, layout=value)
    for payload in (
        {key: value for key, value in snapshot.items() if key != "density"},
        {**snapshot, "motion": "CALM"},
        list(snapshot.values()),
    ):
        with pytest.raises(ValueError, match="axes require exactly"):
            DirectionAxes.from_snapshot(payload)
    with pytest.raises(ValueError, match="axes must be strings"):
        DirectionAxes.from_snapshot({**snapshot, "type": 1})
    with pytest.raises(ValueError, match="unknown visual direction value for colour"):
        DirectionAxes.from_snapshot({**snapshot, "colour": "NEON"})


def test_a_direction_snapshot_round_trips_with_the_wire_shape_of_the_contract() -> None:
    value = direction(name="  Printed   register ", rules=(f"  {RULES[0]} ", *RULES[1:]))
    snapshot = value.to_snapshot()
    stored = json.loads(json.dumps(snapshot))
    reordered = {
        **dict(reversed(stored.items())),
        "axes": dict(reversed(stored["axes"].items())),
    }

    assert list(snapshot) == [
        "name",
        "concept",
        "rules",
        "axes",
        "typicality",
        "candidates",
        "vocabulary_version",
    ]
    assert snapshot == {
        "name": "Printed register",
        "concept": CONCEPT,
        "rules": list(RULES),
        "axes": {
            "layout": "EDITORIAL",
            "shape": "SQUARE_RULES",
            "type": "DISPLAY",
            "colour": "INK",
            "density": "SPACIOUS",
        },
        "typicality": 12,
        "candidates": 5,
        "vocabulary_version": 1,
    }
    assert visual_direction_from_snapshot(snapshot) == value
    assert visual_direction_from_snapshot(stored) == value
    assert visual_direction_from_snapshot(reordered) == value
    assert value.content_hash == snapshot_content_hash(snapshot)
    assert value.content_hash != direction(typicality=13).content_hash


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: {**value, "extra": 1}, "snapshot requires exactly"),
        (
            lambda value: {key: item for key, item in value.items() if key != "typicality"},
            "snapshot requires exactly",
        ),
        (lambda value: {**value, "rules": tuple(value["rules"])}, "rules must be a list"),
        (lambda value: {**value, "rules": value["rules"][:2]}, "needs 3 to 5 rules"),
        (lambda value: {**value, "rules": [*value["rules"], 7]}, "rule must be a string"),
        (lambda value: {**value, "name": f" {value['name']}"}, "name must be normalized"),
        (lambda value: {**value, "concept": ""}, "concept must not be empty"),
        (lambda value: {**value, "typicality": 12.0}, "typicality must be an integer"),
        (lambda value: {**value, "typicality": "12"}, "typicality must be an integer"),
        (lambda value: {**value, "candidates": True}, "candidates must be an integer"),
        (lambda value: {**value, "vocabulary_version": 0}, "vocabulary version must be positive"),
        (lambda value: {**value, "axes": {**value["axes"], "layout": "panels"}}, "for layout"),
        (lambda value: {**value, "axes": {**value["axes"], "x": "X"}}, "axes require exactly"),
        (lambda value: [*value], "snapshot must be a mapping"),
    ],
)
def test_a_direction_snapshot_that_is_not_canonical_is_rejected(change, message) -> None:
    stored = json.loads(json.dumps(direction().to_snapshot()))

    with pytest.raises(ValueError, match=message):
        visual_direction_from_snapshot(change(stored))


def test_the_snapshot_reader_compares_the_rebuilt_direction_with_the_payload(monkeypatch) -> None:
    stored = direction().to_snapshot()
    original = VisualDirection.to_snapshot
    monkeypatch.setattr(
        VisualDirection, "to_snapshot", lambda self: {**original(self), "typicality": 99}
    )

    with pytest.raises(ValueError, match="visual direction snapshot is not canonical"):
        visual_direction_from_snapshot(stored)


def test_texts_are_normalized_and_kept_within_their_limits() -> None:
    longest = direction(
        name="n" * MAX_DIRECTION_NAME_LENGTH,
        concept="c" * MAX_DIRECTION_CONCEPT_LENGTH,
        rules=tuple(f"{index}" * MAX_DIRECTION_RULE_LENGTH for index in range(MAX_DIRECTION_RULES)),
    )
    spaced = direction(concept=f"\n {CONCEPT.replace('. ', '.   ')} ")

    assert (len(longest.name), len(longest.concept)) == (60, 400)
    assert {len(rule) for rule in longest.rules} == {240}
    assert len(longest.rules) == MAX_DIRECTION_RULES
    assert spaced.concept == CONCEPT
    assert direction().vocabulary_version == VISUAL_DIRECTIONS_VERSION
    for changes, message in (
        ({"name": "n" * (MAX_DIRECTION_NAME_LENGTH + 1)}, "name exceeds maximum length"),
        ({"name": "   "}, "name must not be empty"),
        ({"concept": "c" * (MAX_DIRECTION_CONCEPT_LENGTH + 1)}, "concept exceeds maximum length"),
        ({"rules": (*RULES[:2], "r" * (MAX_DIRECTION_RULE_LENGTH + 1))}, "rule exceeds maximum"),
        ({"rules": RULES[:2]}, "needs 3 to 5 rules"),
        ({"rules": (*RULES, *RULES)}, "needs 3 to 5 rules"),
        ({"rules": (*RULES[:2], " ")}, "rule must not be empty"),
        ({"rules": RULES[0]}, "sequence of texts"),
    ):
        with pytest.raises(ValueError, match=message):
            direction(**changes)


def test_the_constructor_accepts_only_the_stored_form() -> None:
    value = direction()

    assert replace(value) == value
    for changes, message in (
        ({"name": " Printed register"}, "name must be normalized"),
        ({"concept": 7}, "concept must be a string"),
        ({"rules": list(RULES)}, "rules must be a tuple"),
        ({"rules": (*RULES[:2], f"{RULES[2]} ")}, "rule must be normalized"),
        ({"axes": EDITORIAL_AXES.to_snapshot()}, "axes must be DirectionAxes"),
    ):
        with pytest.raises(ValueError, match=message):
            replace(value, **changes)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("typicality", -1),
        ("typicality", 101),
        ("typicality", True),
        ("typicality", 12.0),
        ("candidates", 1),
        ("candidates", 21),
        ("candidates", False),
        ("vocabulary_version", 0),
        ("vocabulary_version", True),
    ],
)
def test_integers_stay_in_their_range_and_booleans_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field.replace("_", " ")):
        replace(direction(), **{field: value})


def test_integers_accept_the_bounds_of_their_range() -> None:
    value = direction()

    assert replace(value, typicality=0, candidates=2).typicality == 0
    assert replace(value, typicality=100, candidates=20).candidates == 20
    assert replace(value, vocabulary_version=2).vocabulary_version == 2


def test_the_distance_counts_the_axes_that_differ_in_axis_order() -> None:
    two = replace(HABITUAL_AXES, colour=DirectionColour.INK, layout=DirectionLayout.STAGE)

    assert differing_axes(HABITUAL_AXES, HABITUAL_AXES) == ()
    assert direction_distance(HABITUAL_AXES, HABITUAL_AXES) == 0
    assert differing_axes(HABITUAL_AXES, two) == ("layout", "colour")
    assert direction_distance(two, HABITUAL_AXES) == 2
    assert differing_axes(EDITORIAL_AXES, HABITUAL_AXES) == DIRECTION_AXES
    assert direction_distance(HABITUAL_AXES, EDITORIAL_AXES) == 5


def tie_key(project_id: UUID, pair: tuple[VisualDirection, VisualDirection]) -> str:
    first, second = pair
    seed = f"orchestwin-visual-directions-v1:{project_id}:{first.name}:{second.name}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def selection_candidates() -> tuple[VisualDirection, ...]:
    return (
        direction(name="Quiet panels", axes=HABITUAL_AXES, typicality=60),
        direction(name="Printed register", axes=EDITORIAL_AXES, typicality=40),
        direction(
            name="Ruled ledger",
            axes=axes("EDITORIAL", "SQUARE_RULES", "DISPLAY", "INK", "COMFORTABLE"),
            typicality=0,
        ),
        direction(
            name="Soft bands",
            axes=axes("BANDS", "PILL", "READING", "TINTED", "COMFORTABLE"),
            typicality=0,
        ),
    )


def test_selection_prefers_the_largest_distance_then_the_lowest_typicality() -> None:
    quiet, printed, ruled, soft = selection_candidates()

    assert [direction_distance(printed.axes, item.axes) for item in (quiet, soft)] == [5, 5]
    assert [direction_distance(ruled.axes, item.axes) for item in (quiet, soft)] == [4, 4]
    assert select_directions((quiet, printed, ruled, soft), project_id=UUID(int=1)) == (
        printed,
        soft,
    )
    assert select_directions((soft, ruled, printed, quiet), project_id=UUID(int=1)) == (
        soft,
        printed,
    )


def test_selection_breaks_a_tie_with_the_seeded_hash_of_the_project_and_the_names() -> None:
    trio = (
        direction(name="Quiet panels", axes=HABITUAL_AXES, typicality=10),
        direction(name="Printed register", axes=EDITORIAL_AXES, typicality=10),
        direction(
            name="Soft bands",
            axes=axes("BANDS", "PILL", "READING", "TINTED", "COMPACT"),
            typicality=10,
        ),
    )
    pairs = ((trio[0], trio[1]), (trio[0], trio[2]), (trio[1], trio[2]))
    results = set()

    assert {direction_distance(first.axes, second.axes) for first, second in pairs} == {5}
    for index in range(1, 41):
        project_id = UUID(int=index)
        expected = min(pairs, key=partial(tie_key, project_id))
        selected = select_directions(trio, project_id=project_id)
        assert selected == expected
        assert select_directions(list(trio), project_id=project_id) == selected
        results.add(selected)
    assert len(results) > 1


def test_selection_respects_the_avoided_directions_while_an_eligible_pair_remains() -> None:
    quiet, printed, ruled, soft = selection_candidates()
    candidates = (quiet, printed, ruled, soft)

    assert select_directions(candidates, project_id=UUID(int=1), avoided=(soft.axes,)) == (
        quiet,
        printed,
    )
    assert select_directions(candidates, project_id=UUID(int=1), avoided=iter([printed.axes])) == (
        ruled,
        soft,
    )
    assert select_directions(candidates, project_id=UUID(int=1), avoided=(ruled.axes,)) == (
        printed,
        soft,
    )
    assert select_directions(
        candidates, project_id=UUID(int=1), avoided=(replace(HABITUAL_AXES, type="READING"),)
    ) == (printed, soft)


def test_selection_ignores_the_avoided_directions_when_no_eligible_pair_remains() -> None:
    quiet, printed, ruled, soft = selection_candidates()
    candidates = (quiet, printed, ruled, soft)

    for avoided in ((quiet.axes, printed.axes, ruled.axes), (quiet.axes, soft.axes)):
        assert select_directions(candidates, project_id=UUID(int=1), avoided=avoided) == (
            printed,
            soft,
        )


def test_selection_without_an_eligible_pair_is_refused() -> None:
    quiet = direction(name="Quiet panels", axes=HABITUAL_AXES)
    bands = direction(name="Quiet bands", axes=replace(HABITUAL_AXES, layout="BANDS"))
    soft = direction(name="Soft panels", axes=replace(HABITUAL_AXES, shape="PILL", type="READING"))

    assert direction_distance(bands.axes, soft.axes) == MIN_DIRECTION_DISTANCE - 1
    for candidates in ((quiet, bands, soft), (quiet,), ()):
        with pytest.raises(ValueError, match=r"^the candidate directions are too close"):
            select_directions(candidates, project_id=UUID(int=1))
    with pytest.raises(ValueError, match="too close to each other"):
        select_directions((quiet, bands, soft), project_id=UUID(int=1), avoided=(quiet.axes,))


def test_selection_is_deterministic() -> None:
    candidates = selection_candidates()
    project_id = UUID("6f1c3a52-0a7e-4b8e-9d3c-2b1f0e9a8c7d")

    first = select_directions(candidates, project_id=project_id, avoided=(candidates[3].axes,))
    second = select_directions(
        list(candidates), project_id=project_id, avoided=[candidates[3].axes]
    )

    assert first == second == (candidates[0], candidates[1])


def test_exploration_replaces_and_adds_the_dimensions_bound_by_the_direction() -> None:
    base = visual_exploration(design_fixtures.PROJECT_ID)
    chosen = direction(axes=axes("BANDS", "PILL", "READING", "TINTED", "SPACIOUS"))
    unchanged = {
        code: {name: tuple(values) for name, values in dimensions.items()}
        for code, dimensions in base.items()
    }
    expected = {
        **unchanged["DES-001"],
        "header": ("HERO_BAND",),
        "corners": ("PILL",),
        "borders": ("NONE", "HAIRLINE"),
        "elevation": ("SUBTLE", "RAISED"),
        "type_scale": ("REGULAR", "DISPLAY"),
        "heading_case": ("SENTENCE",),
        "heading_weight": ("REGULAR", "SEMIBOLD"),
        "emphasis": ("BALANCED", "BOLD"),
        "background": ("TINTED", "GRADIENT"),
        "surface_tone": ("TINTED", "WARM", "COOL"),
        "density": ("SPACIOUS",),
    }

    explored = direction_exploration(base, {"DES-001": chosen})

    assert tuple(explored) == tuple(base)
    assert explored["DES-001"] == expected
    assert list(explored["DES-001"]) == list(expected)
    assert explored["DES-002"] == unchanged["DES-002"]
    assert all(
        type(item) is str
        for dimensions in explored.values()
        for values in dimensions.values()
        for item in values
    )
    assert direction_exploration(base, {}) == unchanged
    assert direction_exploration(base, {"DES-009": chosen}) == unchanged
    assert base == visual_exploration(design_fixtures.PROJECT_ID)


@pytest.mark.parametrize("axis", DIRECTION_AXES)
def test_every_axis_value_binds_the_catalog_dimensions_of_the_contract(axis: str) -> None:
    for value in DIRECTION_AXIS_VALUES[axis]:
        chosen = direction(axes=replace(HABITUAL_AXES, **{axis: value}))
        bound = direction_exploration({"DES-001": {}}, {"DES-001": chosen})["DES-001"]
        expected = BINDINGS[axis][value.value]

        assert {name: bound[name] for name in expected} == expected
        assert {
            name: tuple(item.value for item in ids)
            for name, ids in AXIS_BINDINGS[axis][value].items()
        } == expected
        assert list(AXIS_BINDINGS[axis][value]) == list(expected)


def test_every_bound_value_is_an_offered_value_of_its_catalog_dimension() -> None:
    assert tuple(AXIS_BINDINGS) == DIRECTION_AXES
    for axis, values in AXIS_BINDINGS.items():
        assert tuple(values) == tuple(DIRECTION_AXIS_VALUES[axis])
        for bound in values.values():
            for dimension, ids in bound.items():
                assert dimension in VISUAL_DIMENSIONS
                assert ids
                assert len(set(ids)) == len(ids)
                assert all(type(item) is VISUAL_DIMENSIONS[dimension] for item in ids)
                assert set(ids) <= set(offered_visual_values(dimension))
    assert all(
        set(bound["borders"]) - {BorderWeight.NONE} for bound in AXIS_BINDINGS["shape"].values()
    )


def test_every_combination_of_the_axes_admits_valid_choices_in_every_colour_mode() -> None:
    assert len(EVERY_AXES) == 6 * 5 * 4 * 4 * 3
    assert admits_valid_choices({"borders": ("NONE",)}, ColorMode.LIGHT)
    assert not admits_valid_choices({"borders": ("NONE",)}, ColorMode.HIGH_CONTRAST_DARK)
    for chosen in EVERY_AXES:
        bound = direction_exploration({"DES-001": {}}, {"DES-001": direction(axes=chosen)})
        for mode in ColorMode:
            assert admits_valid_choices(bound["DES-001"], mode), (chosen, mode)


def test_direction_tokens_follow_the_table_and_every_value_is_plain_css() -> None:
    catalog = resolve_visual_tokens(NEUTRAL_VISUAL_CHOICES)
    text = catalog["--vl-color-text"]

    for chosen in EVERY_AXES:
        tokens = direction_tokens(direction(axes=chosen), catalog)
        assert tokens == expected_tokens(chosen, text)
        assert all(_TOKEN_NAME.fullmatch(name) for name in tokens)
        assert all(_plain_css_value(value) for value in tokens.values())


def test_the_heavy_frame_shadow_takes_the_text_colour_of_every_mode() -> None:
    heavy = direction(axes=replace(HABITUAL_AXES, shape=DirectionShape.HEAVY_FRAME))
    colours = set()

    for mode, tone in product(ColorMode, SurfaceTone):
        catalog = resolve_visual_tokens(
            replace(NEUTRAL_VISUAL_CHOICES, color_mode=mode, surface_tone=tone)
        )
        tokens = direction_tokens(heavy, catalog)
        assert tokens["--vl-shadow"] == f"6px 6px 0 {catalog['--vl-color-text']}"
        assert tokens["--vl-border-width"] == "3px"
        assert _plain_css_value(tokens["--vl-shadow"])
        colours.add(catalog["--vl-color-text"])
    assert len(colours) > 1
    assert direction_tokens(direction(axes=HABITUAL_AXES), {}) == expected_tokens(
        HABITUAL_AXES, TEXT
    )
    with pytest.raises(ValueError, match="text colour"):
        direction_tokens(heavy, {})


def test_a_language_with_a_direction_merges_the_direction_tokens_over_the_catalog() -> None:
    for chosen in EVERY_AXES[::7]:
        value = direction(axes=chosen)
        catalog = resolve_visual_tokens(NEUTRAL_VISUAL_CHOICES)
        language = create_visual_language(
            choices=NEUTRAL_VISUAL_CHOICES,
            product_name="Catalog",
            rationale="Every direction value",
            direction=value,
        )
        assert language.direction == value
        assert language.token_values == {
            **catalog,
            **direction_tokens(value, catalog),
            **bundled_font_tokens(NEUTRAL_VISUAL_CHOICES, catalog),
        }


def test_the_vocabulary_snapshot_and_its_hash_are_stable() -> None:
    snapshot = visual_directions_snapshot()

    assert set(snapshot) == {
        "version",
        "axes",
        "definitions",
        "bindings",
        "tokens",
        "minimum_distance",
        "candidates",
    }
    assert snapshot["version"] == VISUAL_DIRECTIONS_VERSION
    assert snapshot["axes"] == {axis: list(ids) for axis, ids in AXIS_IDS.items()}
    assert snapshot["definitions"] == DEFINITIONS
    assert snapshot["bindings"] == {
        axis: {
            value: {name: list(ids) for name, ids in bound.items()}
            for value, bound in values.items()
        }
        for axis, values in BINDINGS.items()
    }
    assert snapshot["tokens"] == {
        axis: {
            value: {
                name: item.replace(TEXT, "var(--vl-color-text)") for name, item in bound.items()
            }
            for value, bound in values.items()
        }
        for axis, values in TOKENS.items()
    }
    assert (snapshot["minimum_distance"], snapshot["candidates"]) == (4, 5)
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert visual_directions_snapshot() == snapshot
    digest = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
    assert digest == VISUAL_DIRECTIONS_CONTENT_HASH
    assert VISUAL_DIRECTIONS_CONTENT_HASH == STORED_DIRECTIONS_HASH


def test_the_vocabulary_hash_changes_when_a_definition_changes(monkeypatch) -> None:
    changed = MappingProxyType(
        {
            **AXIS_DEFINITIONS,
            "density": MappingProxyType(
                {**AXIS_DEFINITIONS["density"], DirectionDensity.COMPACT: "tight spacing"}
            ),
        }
    )
    monkeypatch.setattr(visual_directions, "AXIS_DEFINITIONS", changed)

    snapshot = visual_directions.visual_directions_snapshot()

    assert snapshot["definitions"]["density"]["COMPACT"] == "tight spacing"
    assert snapshot_content_hash(snapshot) != VISUAL_DIRECTIONS_CONTENT_HASH


def test_a_direction_survives_the_realignment_of_the_twins() -> None:
    language = directed_language(design_fixtures.visual_language())
    renamed = replace(design_fixtures.twin_reference(), version_number=3, name="Front Desk Twin")
    current = {renamed.twin_id: renamed}
    alternative = replace(design_fixtures.design_alternative(index=2), visual_language=language)

    realigned = _realigned_language(language, current)
    moved = _realigned_alternative(alternative, current)

    assert realigned is not None
    assert realigned.direction == language.direction
    assert realigned.to_snapshot()["direction"] == language.to_snapshot()["direction"]
    assert realigned.token_values == language.token_values
    assert [item.name for item in realigned.twin_fit] == ["Front Desk Twin"]
    assert moved.visual_language == realigned
    assert moved.user_twin_references == (renamed,)
