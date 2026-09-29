"""Constrain planning references to evidence keys and typed artifact codes."""

from orchestwin.artifacts.visual_exploration import exploration_bindings

CRITIQUE_LISTS = (
    "strengths",
    "concerns",
    "unmet_needs",
    "on_accessibility",
    "trust_concerns",
    "questions",
    "suggested_changes",
)
UNBOUNDED_CRITIQUE_TWINS = 2
SHORT_CRITIQUE_TWINS = 4
DESIGN_ALTERNATIVE_CODES = ("DES-001", "DES-002")
HOSTED_DESIGN_PURPOSE = "DESIGN_ALTERNATIVES_HOSTED"
HOSTED_CRITIQUE_DEFINITION = "HostedCritiqueDraft"


def critique_list_limit(twin_count):
    if twin_count <= UNBOUNDED_CRITIQUE_TWINS:
        return None
    return 2 if twin_count <= SHORT_CRITIQUE_TWINS else 1


def critique_pairs(twin_keys):
    pairs = [(alternative, key) for alternative in DESIGN_ALTERNATIVE_CODES for key in twin_keys]
    return [
        (f"CRQ-{index:03d}", alternative, key) for index, (alternative, key) in enumerate(pairs, 1)
    ]


def constrain_planning_schema(schema, context, task):
    if task not in {"requirements", "design", "architecture"}:
        return
    definitions = schema.get("$defs", {})
    known = {}
    if task != "requirements":
        view = context["requirements"]
        known = {
            prefix: [item["code"] for item in view[group]]
            for prefix, group in (("REQ", "requirements"), ("USR", "stories"), ("AC", "criteria"))
        }

    if task == "design":
        known["DES"] = list(DESIGN_ALTERNATIVE_CODES)
    if task == "architecture" and "structure" in context:
        known["CMP"] = [x["code"] for x in context["structure"]["components"]]
        known["ENV"] = [x["code"] for x in context["structure"]["environments"]]

    def reference(prefix):
        return (
            {"type": "string", "enum": known[prefix]}
            if prefix in known
            else {"type": "string", "pattern": f"^{prefix}-[0-9]{{3,}}$"}
        )

    prefixes = {
        "requirements": "REQ",
        "requirement_ids": "REQ",
        "stories": "USR",
        "criteria": "AC",
        "acceptance_criterion_ids": "AC",
        "alternative": "DES",
        "alternatives": "DES",
        "recommendation": "DES",
        "source_component_id": "CMP",
        "target_component_id": "CMP",
        "owning_component_id": "CMP",
        "component_ids": "CMP",
        "architecture_component_ids": "CMP",
        "environment_ids": "ENV",
        "required_test_case_ids": "TST",
    }
    for definition in definitions.values():
        for name, field in definition.get("properties", {}).items():
            target = field.get("items", field)
            if name in prefixes:
                target.update(reference(prefixes[name]))
            elif name in {"twin", "twins", "as_twin"}:
                target.update(type="string", enum=list(context["twins"]))
            elif name == "sources":
                target.update(type="string", enum=list(context["evidence"]))
    if task == "design":
        if context.get("purpose") not in (None, HOSTED_DESIGN_PURPOSE):
            return
        schema["properties"]["recommendation"].update(reference("DES"))

        if "TwinFitDraft" in definitions:
            definitions["VisualLanguageDraft"]["properties"]["twin_fit"] = _fixed_array(
                definitions, "TwinFitDraft", [{"twin": {"const": key}} for key in context["twins"]]
            )
        exploration = context.get("visual_exploration") or {}
        schema["properties"]["alternatives"] = _fixed_array(
            definitions,
            "AlternativeDraft",
            [
                {"code": {"const": code}, **exploration_bindings(exploration, code)}
                for code in known["DES"]
            ],
        )
        hosted = context.get("purpose") == HOSTED_DESIGN_PURPOSE
        critique = HOSTED_CRITIQUE_DEFINITION if hosted else "CritiqueDraft"
        limit = None if hosted else critique_list_limit(len(context["twins"]))
        if limit is not None and critique in definitions:
            for name in CRITIQUE_LISTS:
                definitions[critique]["properties"][name]["maxItems"] = limit
        # Coverage is a governance obligation, not something the model can omit.
        pairs = critique_pairs(list(context["twins"]))
        schema["properties"]["critiques"] = _fixed_array(
            definitions,
            critique,
            [
                {
                    "code": {"const": code},
                    "alternative": {"const": alternative},
                    "as_twin": {"const": key},
                    "observation_keys": {
                        "items": {"enum": list(context["twins"][key]["observations"])}
                    },
                }
                for code, alternative, key in pairs
            ],
        )

    if task == "architecture":
        if "test_cases" not in schema["properties"]:
            return
        if "CMP" in known:
            if len(known["CMP"]) == 1:
                schema["properties"]["connections"]["maxItems"] = 0
            else:
                definitions["ConnectionDraft"]["anyOf"] = [
                    {
                        "properties": {
                            "source_component_id": {"const": code},
                            "target_component_id": {"enum": [x for x in known["CMP"] if x != code]},
                        }
                    }
                    for code in known["CMP"]
                ]
        obligations = [
            {
                "acceptance_criterion_ids": {"const": [item["code"]]},
                "requirement_ids": {"const": item["requirement_ids"]},
            }
            for item in context["requirements"]["criteria"]
        ]
        covered = {code for item in obligations for code in item["requirement_ids"]["const"]}
        # Preserve approved links. An uncovered requirement gets its own planning
        # slot; the model still chooses its criterion linkage and all test content.
        obligations.extend(
            {"requirement_ids": {"const": [code]}} for code in known["REQ"] if code not in covered
        )
        codes = [f"TST-{index:03d}" for index in range(1, len(obligations) + 1)]
        schema["properties"]["test_cases"] = _fixed_array(
            definitions,
            "TestCaseDraft",
            [
                {"code": {"const": code}, **binding}
                for code, binding in zip(codes, obligations, strict=True)
            ],
        )
        definitions["QualityGateDraft"]["properties"]["required_test_case_ids"]["items"].update(
            enum=codes
        )


def _fixed_array(definitions, definition, bindings):
    return {
        "type": "array",
        "minItems": len(bindings),
        "maxItems": len(bindings),
        "prefixItems": [
            {"allOf": [{"$ref": f"#/$defs/{definition}"}, {"properties": binding}]}
            for binding in bindings
        ],
        "items": False,
    }
