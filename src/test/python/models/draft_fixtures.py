"""Translate domain-valid test data to the semantic model wire contracts."""

from orchestwin.models.proposal_generation import wire_value
from orchestwin.models.requirements_drafts import requirements_context


def proposal_draft(stage, value, request):
    raw = wire_value(value)
    codes = {}

    def collect(item):
        if isinstance(item, dict):
            if "id" in item and "code" in item:
                codes[item["id"]] = item["code"]
            for child in item.values():
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)

    collect(raw)
    if stage != "requirements":
        collect(wire_value(request.requirements.version.specification))
    twins = (
        request.user_modeling.user_twin_references
        if stage != "architecture"
        else request.requirements.version.specification.user_twin_references
    )
    twin_codes = {str(twin.twin_id): f"T{i}" for i, twin in enumerate(twins, 1)}

    def convert(item):
        if isinstance(item, str):
            return codes.get(item, item)
        if isinstance(item, list):
            return [convert(child) for child in item]
        if isinstance(item, dict):
            if "twin_id" in item:
                return twin_codes[item["twin_id"]]
            return {key: convert(child) for key, child in item.items() if key != "id"}
        return item

    result = convert(raw)
    if stage == "requirements":
        _, sources, _ = requirements_context(request)

        def source_key(source):
            return next(key for key, ref in sources.items() if wire_value(ref) == source)

        result = {
            key: result[key]
            for key in (
                "requirements",
                "user_stories",
                "acceptance_criteria",
                "scenarios",
                "risks",
                "definition_of_done",
            )
        }
        for group, items in result.items():
            for original, item in zip(raw[group], items, strict=True):
                for old, new in {
                    "requirement_ids": "requirements",
                    "user_story_ids": "stories",
                    "acceptance_criterion_ids": "criteria",
                    "user_twin_references": "twins",
                    "user_twin_reference": "twin",
                    "actor": "twin",
                }.items():
                    if old in item:
                        item[new] = item.pop(old)
                if "sources" in item:
                    item["sources"] = [source_key(source) for source in original["sources"]]
                item.pop("review_status", None)
        return result
    if stage == "design":
        result = {
            key: result[key] for key in ("alternatives", "critiques", "concerns", "open_questions")
        }
        result["recommendation"] = codes[raw["recommended_alternative_id"]]
        for item in [
            *result["alternatives"],
            *result["concerns"],
            *(w for a in result["alternatives"] for w in a["workflows"]),
        ]:
            for old, new in {
                "requirement_ids": "requirements",
                "user_story_ids": "stories",
                "acceptance_criterion_ids": "criteria",
                "user_twin_references": "twins",
                "design_alternative_ids": "alternatives",
            }.items():
                if old in item:
                    item[new] = item.pop(old)
        for item in result["critiques"]:
            item["alternative"] = item.pop("design_alternative_id")
            item["twin"] = item.pop("user_twin_reference")
            twin = request.user_modeling.user_twins[int(item["twin"][1:]) - 1]
            item["observation_keys"] = [twin.observations[0].observation_key]
            item["confidence"] = item["confidence"]["value"]
            for key in ("provenance", "epistemic_status", "human_validation", "kind"):
                item.pop(key)
        return result
    architecture, plan = result["architecture"], result["test_plan"]
    for key in (
        "code",
        "selected_design_alternative_id",
        "prototype_id",
        "requirement_ids",
        "acceptance_criterion_ids",
    ):
        architecture.pop(key)
    architecture.update(
        {key: plan[key] for key in ("environments", "test_cases", "quality_gates", "fixtures")}
    )
    architecture["test_strategy"] = plan["strategy"]
    for item in architecture["test_cases"]:
        item.pop("design_alternative_ids")
    return architecture
