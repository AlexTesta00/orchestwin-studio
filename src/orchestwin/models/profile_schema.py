"""Project-bound profile grammar; inference chooses content, never approval or provenance."""

import json
from copy import deepcopy


def constrain_profile_schema(schema, context, task):
    if task not in {"personas", "user-twins"}:
        return
    if task == "user-twins":
        _constrain_twin_drafts(schema, context)
        return
    definitions = schema["$defs"]
    provenance_definitions = {}
    value_definitions = {}
    inferred = deepcopy(definitions["ProfileObservation"])
    inferred["properties"].update(
        epistemic_status={"const": "MODEL_INFERRED"},
        human_validation={"const": "REQUIRED"},
        rationale={"type": "string", "minLength": 1, "maxLength": 240},
    )
    inferred["required"] = list(inferred["properties"])
    definitions["InferredProfileObservation"] = inferred
    for branch in definitions["ObservationValue"]["anyOf"]:
        kind = branch["properties"]["kind"]["const"]
        name = "ProfileValue" + kind
        definitions[name] = deepcopy(branch)
        value_definitions[kind] = {"$ref": "#/$defs/" + name}

    def observation(key, kinds, provenance):
        provenance_key = json.dumps(provenance, sort_keys=True)
        if provenance_key not in provenance_definitions:
            name = "ProfileProvenance" + str(len(provenance_definitions))
            definitions[name] = {"const": provenance}
            provenance_definitions[provenance_key] = {"$ref": "#/$defs/" + name}
        return {
            "allOf": [
                {"$ref": "#/$defs/InferredProfileObservation"},
                {
                    "properties": {
                        "observation_key": {"const": key},
                        "provenance": provenance_definitions[provenance_key],
                        "value": {"anyOf": [value_definitions[kind] for kind in sorted(kinds)]},
                    }
                },
            ]
        }

    def fixed_array(items):
        return {
            "type": "array",
            "prefixItems": items,
            "minItems": len(items),
            "maxItems": len(items),
            "items": False,
        }

    proposals = []
    if task == "personas":
        for candidate in context["candidates"]:
            proposal = deepcopy(definitions["ProposedPersonaProfile"])
            profile = deepcopy(definitions["PersonaProfile"])
            provenance = candidate["role_observation"]["provenance"]
            profile["properties"].update(
                {
                    "source": {"const": "SYSTEM_PROPOSED"},
                    "kind": {"const": "PROTO_PERSONA"},
                    "confirmation_status": {"const": "PENDING_CONFIRMATION"},
                    "rejection_reason": {"const": None},
                    "observations": fixed_array(
                        [
                            {"const": candidate["role_observation"]},
                            observation("persona.summary", {"TEXT"}, provenance),
                            observation(
                                "persona.goals", {"ITEMS", "UNKNOWN", "ABSTAINED"}, provenance
                            ),
                            observation(
                                "persona.context_of_use",
                                {"TEXT", "UNKNOWN", "ABSTAINED"},
                                provenance,
                            ),
                        ]
                    ),
                }
            )
            proposal["properties"].update(
                {
                    "candidate_ordinal": {"const": candidate["ordinal"]},
                    "candidate_content_hash": {"const": candidate["candidate_content_hash"]},
                    "profile": profile,
                }
            )
            proposals.append(proposal)
    schema["properties"]["proposals"] = fixed_array(proposals)
    # Bound profiles replace generic profile definitions. Retain only reachable
    # definitions so metadata repetition does not consume the model context.
    needed = set()

    def visit(value):
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/$defs/"):
                name = reference.removeprefix("#/$defs/")
                if name not in needed:
                    needed.add(name)
                    visit(definitions[name])
            for key, item in value.items():
                if key != "$defs":
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(schema)
    schema["$defs"] = {name: definitions[name] for name in sorted(needed)}


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
