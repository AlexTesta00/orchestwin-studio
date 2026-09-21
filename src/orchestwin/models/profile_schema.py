"""Project-bound profile grammar; inference chooses content, never approval or provenance."""

from copy import deepcopy

from orchestwin.models.profile_drafts import (
    PERSONA_ITEM_LIMIT,
    PERSONA_ITEM_TEXT_LIMIT,
    PERSONA_REASON_LIMIT,
    PERSONA_TEXT_LIMIT,
)


def constrain_profile_schema(schema, context, task):
    if task == "personas":
        _constrain_persona_drafts(schema, context)
    elif task == "user-twins":
        _constrain_twin_drafts(schema, context)


def _constrain_persona_drafts(schema, context):
    definitions = schema["$defs"]
    for branch in definitions["ObservationValue"]["anyOf"]:
        bounded = deepcopy(branch)
        properties = bounded["properties"]
        kind = properties["kind"]["const"]
        if kind == "TEXT":
            properties["text"]["maxLength"] = PERSONA_TEXT_LIMIT
        elif kind == "ITEMS":
            properties["items"]["maxItems"] = PERSONA_ITEM_LIMIT
            properties["items"]["items"]["maxLength"] = PERSONA_ITEM_TEXT_LIMIT
        elif kind == "ABSTAINED":
            properties["reason"]["maxLength"] = PERSONA_REASON_LIMIT
        definitions["ProfileValue" + kind] = bounded
    fields = (
        ("persona.summary", ("TEXT",)),
        ("persona.goals", ("ITEMS", "UNKNOWN", "ABSTAINED")),
        ("persona.context_of_use", ("TEXT", "UNKNOWN", "ABSTAINED")),
    )
    observations = [
        {
            "allOf": [
                {"$ref": "#/$defs/PersonaObservationDraft"},
                {
                    "properties": {
                        "observation_key": {"const": key},
                        "value": {
                            "anyOf": [{"$ref": "#/$defs/ProfileValue" + kind} for kind in kinds]
                        },
                    }
                },
            ]
        }
        for key, kinds in fields
    ]
    definitions["PersonaProfileDraft"]["properties"]["observations"] = {
        "type": "array",
        "prefixItems": observations,
        "items": False,
        "minItems": len(observations),
        "maxItems": len(observations),
    }
    proposals = [
        {
            "allOf": [
                {"$ref": "#/$defs/PersonaProfileDraft"},
                {"properties": {"candidate_ordinal": {"const": candidate["ordinal"]}}},
            ]
        }
        for candidate in context["candidates"]
    ]
    schema["properties"]["proposals"] = {
        "type": "array",
        "prefixItems": proposals,
        "items": False,
        "minItems": len(proposals),
        "maxItems": len(proposals),
    }


def _constrain_twin_drafts(schema, context):
    from orchestwin.twins.user_twins import UserTwinField

    definitions = schema["$defs"]
    for branch in definitions["ObservationValue"]["anyOf"]:
        definitions["ProfileValue" + branch["properties"]["kind"]["const"]] = branch
    text_fields = {"role", "context_of_use", "technical_literacy", "risk_sensitivity"}
    observations = []
    for field in UserTwinField:
        if field is UserTwinField.AGE_RANGE:
            continue
        kinds = ["TEXT" if field.value in text_fields else "ITEMS"]
        if field is not UserTwinField.ROLE:
            kinds += ["UNKNOWN", "ABSTAINED"]
        observations.append(
            {
                "allOf": [
                    {"$ref": "#/$defs/TwinObservationDraft"},
                    {
                        "properties": {
                            "observation_key": {"const": field.observation_key},
                            "value": {
                                "anyOf": [{"$ref": "#/$defs/ProfileValue" + kind} for kind in kinds]
                            },
                        }
                    },
                ]
            }
        )
    definitions["TwinProfileDraft"]["properties"]["observations"] = {
        "type": "array",
        "prefixItems": observations,
        "items": False,
        "minItems": len(observations),
        "maxItems": len(observations),
    }
    proposals = [
        {
            "allOf": [
                {"$ref": "#/$defs/TwinProfileDraft"},
                {"properties": {"persona_id": {"const": reference["persona_id"]}}},
            ]
        }
        for reference in context["persona_references"]
    ]
    schema["properties"]["proposals"] = {
        "type": "array",
        "prefixItems": proposals,
        "items": False,
        "minItems": len(proposals),
        "maxItems": len(proposals),
    }
