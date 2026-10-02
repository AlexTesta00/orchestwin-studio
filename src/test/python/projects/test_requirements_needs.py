from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.projects.requirements import create_requirement, create_user_story
from orchestwin.projects.requirements_needs import create_user_need
from orchestwin.projects.requirements_quality import create_usage_scenario
from orchestwin.projects.requirements_specifications import RequirementsSpecification
from src.test.python.projects.test_requirements_specifications import (
    brief_source,
    build_specification,
)

NEED_ID = UUID(int=901)
SECOND_NEED_ID = UUID(int=902)


def enriched_specification(
    specification: RequirementsSpecification | None = None,
) -> RequirementsSpecification:
    base = build_specification() if specification is None else specification
    needs = tuple(
        create_user_need(
            need_id=UUID(int=901 + index),
            code=f"NED-{index + 1:03}",
            title=f"Understand available choices for {scenario.actor.name}",
            statement="Know which choice fulfils the request before confirming it.",
            scenario_ids=(scenario.id,),
            sources=(base.requirements[0].sources[0],),
        )
        for index, scenario in enumerate(base.scenarios)
    )
    return replace(
        base,
        schema_version=2,
        needs=needs,
        scenarios=tuple(
            replace(
                scenario,
                context="At the reception desk while serving an arriving guest.",
                goal="Identify and reserve a suitable available room.",
                criticalities=("Room availability can change before confirmation.",),
                sources=(base.requirements[0].sources[0],),
            )
            for scenario in base.scenarios
        ),
        requirements=tuple(
            replace(requirement, need_ids=tuple(need.id for need in needs))
            for requirement in base.requirements
        ),
        user_stories=tuple(
            replace(
                story,
                need_ids=tuple(
                    need.id
                    for need in needs
                    if any(
                        scenario.id in need.scenario_ids
                        and scenario.actor == story.user_twin_reference
                        for scenario in base.scenarios
                    )
                ),
            )
            for story in base.user_stories
        ),
    )


def test_need_factory_normalizes_and_canonicalizes_without_duplicating_actors():
    source = brief_source()
    need = create_user_need(
        need_id=NEED_ID,
        code="NED-001",
        title=" Know  availability ",
        statement=" Choose a room  with confidence. ",
        scenario_ids=(UUID(int=2), UUID(int=1)),
        sources=(source,),
    )
    assert need.title == "Know availability"
    assert need.statement == "Choose a room with confidence."
    assert need.scenario_ids == (UUID(int=1), UUID(int=2))
    assert set(need.to_snapshot()) == {
        "id",
        "code",
        "title",
        "statement",
        "scenario_ids",
        "sources",
    }
    assert len(need.content_hash) == 64
    assert '"scenario_ids"' in need.canonical_json()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("code", "REQ-001", "NED"),
        ("title", " ", "empty"),
        ("title", "x" * 201, "maximum"),
        ("statement", "x" * 2001, "maximum"),
        ("scenario_ids", (), "empty"),
        ("scenario_ids", (UUID(int=1), UUID(int=1)), "unique"),
        ("sources", (), "empty"),
        ("sources", (brief_source(), brief_source()), "unique"),
    ),
)
def test_need_factory_rejects_invalid_values(field, value, message):
    values = {
        "need_id": NEED_ID,
        "code": "NED-001",
        "title": "Know availability",
        "statement": "Choose a suitable room.",
        "scenario_ids": (UUID(int=1),),
        "sources": (brief_source(),),
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        create_user_need(**values)


def test_need_direct_constructor_requires_normalized_canonical_values():
    need = enriched_specification().needs[0]
    with pytest.raises(ValueError, match="normalized"):
        replace(need, title=" title ")
    with pytest.raises(ValueError, match="canonical"):
        replace(need, scenario_ids=(UUID(int=2), UUID(int=1)))


@pytest.mark.parametrize("collection", ("requirements", "user_stories"))
def test_requirement_and_story_factories_canonicalize_need_ids(collection):
    artifact = getattr(build_specification(), collection)[0]
    values = {name: getattr(artifact, name) for name in artifact.__dataclass_fields__}
    identity_key = "requirement_id" if collection == "requirements" else "story_id"
    factory = create_requirement if collection == "requirements" else create_user_story
    values[identity_key] = values.pop("id")
    values["need_ids"] = (SECOND_NEED_ID, NEED_ID)
    value = factory(**values)
    assert value.need_ids == (NEED_ID, SECOND_NEED_ID)
    assert value.to_snapshot()["need_ids"] == [str(NEED_ID), str(SECOND_NEED_ID)]
    with pytest.raises(ValueError, match="canonical"):
        replace(value, need_ids=(SECOND_NEED_ID, NEED_ID))
    values["need_ids"] = (NEED_ID, NEED_ID)
    with pytest.raises(ValueError, match="unique"):
        factory(**values)


def test_legacy_artifacts_omit_new_fields_and_enriched_scenario_emits_all_four():
    legacy = build_specification()
    assert "needs" not in legacy.to_snapshot()
    for artifact in (*legacy.requirements, *legacy.user_stories):
        assert "need_ids" not in artifact.to_snapshot()
    scenario = legacy.scenarios[0]
    assert not {"context", "goal", "criticalities", "sources"}.intersection(scenario.to_snapshot())
    partial = replace(scenario, context="At the reception desk.")
    assert partial.to_snapshot()["goal"] is None
    assert partial.to_snapshot()["criticalities"] == []
    assert partial.to_snapshot()["sources"] == []


def test_scenario_factory_preserves_narrative_criticalities_order_and_normalizes_text():
    scenario = build_specification().scenarios[0]
    values = {name: getattr(scenario, name) for name in scenario.__dataclass_fields__}
    values["scenario_id"] = values.pop("id")
    values.update(
        context=" At the  reception desk. ",
        goal=" Find a suitable  room. ",
        criticalities=(" Second problem. ", " First problem. "),
        sources=(brief_source(),),
    )
    enriched = create_usage_scenario(**values)
    assert enriched.context == "At the reception desk."
    assert enriched.goal == "Find a suitable room."
    assert enriched.criticalities == ("Second problem.", "First problem.")
    values["criticalities"] = ("Same problem.", " Same problem. ")
    with pytest.raises(ValueError, match="unique"):
        create_usage_scenario(**values)


@pytest.mark.parametrize("field", ("context", "goal"))
def test_scenario_enriched_text_caps(field):
    scenario = build_specification().scenarios[0]
    with pytest.raises(ValueError, match="maximum"):
        replace(scenario, **{field: "x" * 2001})


@pytest.mark.parametrize("field", ("needs", "requirements", "user_stories", "scenarios"))
def test_schema_one_rejects_each_new_data_group(field):
    legacy = build_specification()
    enriched = enriched_specification(legacy)
    with pytest.raises(ValueError, match="schema 1"):
        replace(legacy, **{field: getattr(enriched, field)})


@pytest.mark.parametrize("schema_version", (0, 3, True, 1.5, 1.0))
def test_unsupported_schema_version_is_rejected(schema_version):
    with pytest.raises(ValueError, match="schema version"):
        replace(build_specification(), schema_version=schema_version)


def test_schema_two_roundtrip_shape_and_existing_identity():
    legacy = build_specification()
    enriched = enriched_specification(legacy)
    assert enriched.schema_version == 2
    assert enriched.to_snapshot()["needs"][0] == enriched.needs[0].to_snapshot()
    for name in (
        "requirements",
        "user_stories",
        "scenarios",
        "acceptance_criteria",
        "risks",
        "definition_of_done",
    ):
        assert [(item.id, item.code) for item in getattr(enriched, name)] == [
            (item.id, item.code) for item in getattr(legacy, name)
        ]


def test_schema_two_requires_needs():
    with pytest.raises(ValueError, match="needs must not be empty"):
        replace(enriched_specification(), needs=())


@pytest.mark.parametrize(("field", "value"), (("context", None), ("goal", None), ("sources", ())))
def test_schema_two_requires_scenario_context_goal_and_sources(field, value):
    specification = enriched_specification()
    with pytest.raises(ValueError, match="context, goal, and sources"):
        replace(specification, scenarios=(replace(specification.scenarios[0], **{field: value}),))


def test_schema_two_allows_empty_criticalities():
    specification = enriched_specification()
    assert replace(
        specification, scenarios=(replace(specification.scenarios[0], criticalities=()),)
    )


def test_schema_two_rejects_unknown_scenario_and_uncovered_scenario():
    specification = enriched_specification()
    with pytest.raises(ValueError, match="unknown references"):
        replace(
            specification, needs=(replace(specification.needs[0], scenario_ids=(UUID(int=999),)),)
        )
    with pytest.raises(ValueError, match="every scenario"):
        replace(
            specification,
            scenarios=(
                *specification.scenarios,
                replace(specification.scenarios[0], id=UUID(int=903), code="SCN-002"),
            ),
        )


@pytest.mark.parametrize("collection", ("requirements", "user_stories"))
def test_schema_two_rejects_empty_and_unknown_need_links(collection):
    specification = enriched_specification()
    artifacts = getattr(specification, collection)
    for links, message in (((), "require need IDs"), ((UUID(int=999),), "unknown references")):
        with pytest.raises(ValueError, match=message):
            replace(
                specification,
                **{collection: (replace(artifacts[0], need_ids=links), *artifacts[1:])},
            )


def test_schema_two_rejects_unused_need():
    specification = enriched_specification()
    with pytest.raises(ValueError, match="every need"):
        replace(
            specification,
            needs=(
                *specification.needs,
                replace(specification.needs[0], id=SECOND_NEED_ID, code="NED-002"),
            ),
        )


def test_story_and_linked_requirement_must_share_a_need():
    specification = enriched_specification()
    second = replace(specification.needs[0], id=SECOND_NEED_ID, code="NED-002")
    with pytest.raises(ValueError, match="share a need"):
        replace(
            specification,
            needs=(*specification.needs, second),
            requirements=(
                replace(specification.requirements[0], need_ids=(SECOND_NEED_ID,)),
                specification.requirements[1],
            ),
        )


def test_story_needs_must_include_its_actor_and_requirement_twins_must_be_need_actors():
    specification = enriched_specification()
    other = replace(specification.user_twin_references[0], twin_id=UUID(int=904))
    twins = (other, *specification.user_twin_references)
    with pytest.raises(ValueError, match="scenario of its User Twin"):
        replace(
            specification,
            user_twin_references=twins,
            user_stories=(replace(specification.user_stories[0], user_twin_reference=other),),
        )
    with pytest.raises(ValueError, match="actors of its needs"):
        replace(
            specification,
            user_twin_references=twins,
            requirements=(
                replace(specification.requirements[0], user_twin_references=(other,)),
                specification.requirements[1],
            ),
        )
