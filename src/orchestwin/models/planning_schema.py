"""Constrain planning references to evidence keys and typed artifact codes."""


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
        known["DES"] = ["DES-001", "DES-002"]
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
            elif name in {"twin", "twins"}:
                target.update(type="string", enum=list(context["twins"]))
            elif name == "sources":
                target.update(type="string", enum=list(context["evidence"]))
    if task == "design":
        schema["properties"]["recommendation"].update(reference("DES"))

        schema["properties"]["alternatives"] = _fixed_array(
            definitions, "AlternativeDraft", [{"code": {"const": code}} for code in known["DES"]]
        )
        # Coverage is a governance obligation, not something the model can omit.
        pairs = [
            (alternative, key, twin)
            for alternative in known["DES"]
            for key, twin in context["twins"].items()
        ]
        schema["properties"]["critiques"] = _fixed_array(
            definitions,
            "CritiqueDraft",
            [
                {
                    "code": {"const": f"CRQ-{index:03d}"},
                    "alternative": {"const": alternative},
                    "twin": {"const": key},
                    "observation_keys": {"items": {"enum": list(twin["observations"])}},
                }
                for index, (alternative, key, twin) in enumerate(pairs, 1)
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
