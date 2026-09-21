"""Optional counterfactual decision supervision for the synthetic calibration experiment.

Half of each family's training groups keep full completion loss. The other half
supervise the first divergent output tokens between counterfactual siblings
and the next token, which disambiguates partially shared BPE prefixes.
The training operator must also disable accumulation-wide token normalization
so each example contributes its own mean loss before gradient accumulation.
No input, output token, validation row or test row is rewritten.
"""

from collections import defaultdict
from copy import deepcopy

STATES = frozenset({"MISSING", "PRESENT", "INSUFFICIENT"})


def configure_decision_loss(trainer):
    """Use the Trainer's documented mean-per-example path, with one row per batch."""
    if (
        trainer.args.per_device_train_batch_size != 1
        or trainer.args.world_size != 1
        or trainer.compute_loss_func is not None
    ):
        raise ValueError("decision loss requires one example, one process and default model loss")
    before = trainer.model_accepts_loss_kwargs
    # Without this flag the Trainer sends the token count of the entire
    # accumulation group to the model, so short decisions remain underweighted.
    trainer.model_accepts_loss_kwargs = False
    return {
        "policy": "PER_EXAMPLE_MEAN_THEN_GRADIENT_ACCUMULATION_V1",
        "model_accepts_loss_kwargs_before": before,
        "model_accepts_loss_kwargs_after": trainer.model_accepts_loss_kwargs,
        "per_device_train_batch_size": 1,
        "world_size": 1,
        "gradient_accumulation_steps": trainer.args.gradient_accumulation_steps,
        "custom_loss_used": False,
    }


def balance_decision_supervision(rows: list[dict], encoded: list[dict]):
    if not rows or len(rows) != len(encoded) or any(row.get("split") != "train" for row in rows):
        raise ValueError("decision supervision requires aligned training rows only")
    siblings = defaultdict(dict)
    families = defaultdict(set)
    completions, starts = [], []
    for index, (row, tokens) in enumerate(zip(rows, encoded, strict=True)):
        key = (row["group_id"], row["locale"])
        state = row["judgement"]
        if state not in STATES or state in siblings[key]:
            raise ValueError("duplicate or unknown counterfactual state")
        siblings[key][state] = index
        families[row["family"]].add(row["group_id"])
        mask, ids = tokens["completion_mask"], tokens["input_ids"]
        if len(mask) != len(ids) or 1 not in mask:
            raise ValueError("complete supervised output required")
        start = mask.index(1)
        if mask != [0] * start + [1] * (len(ids) - start):
            raise ValueError("initial supervision must cover the whole completion only")
        starts.append(start)
        completions.append(ids[start:])
    if any(set(group) != STATES for group in siblings.values()):
        raise ValueError("all three counterfactual siblings are required")
    selected = {group for groups in families.values() for group in sorted(groups)[::2]}
    output = deepcopy(encoded)
    observations = []
    for index, row in enumerate(rows):
        focused = row["group_id"] in selected
        decisions = set()
        if focused:
            own = completions[index]
            for other in siblings[(row["group_id"], row["locale"])].values():
                if other == index:
                    continue
                different = next(
                    (
                        i
                        for i, (a, b) in enumerate(zip(own, completions[other], strict=False))
                        if a != b
                    ),
                    None,
                )
                if different is None:
                    raise ValueError("counterfactual outputs require an explicit divergent token")
                # A BPE fork can be '\":[{' versus '\":['; the latter has not
                # yet specified whether findings is empty. Include its next token.
                decisions.update(
                    starts[index] + position
                    for position in range(different, min(different + 2, len(own)))
                )
            output[index]["completion_mask"] = [
                int(i in decisions) for i in range(len(encoded[index]["input_ids"]))
            ]
        observations.append(
            {
                "group_id": row["group_id"],
                "family": row["family"],
                "locale": row["locale"],
                "judgement": row["judgement"],
                "mode": "DECISION_TOKENS" if focused else "FULL_COMPLETION",
                "decision_token_positions": sorted(decisions),
                "supervised_tokens": sum(output[index]["completion_mask"]),
            }
        )
    return output, {
        "policy": "COUNTERFACTUAL_DECISION_BALANCED_V2_BPE_BRANCH",
        "batch_size_required": 1,
        "selection": "Alternating sorted opaque training group IDs within each family; all languages and states stay together.",
        "input_or_target_tokens_changed": False,
        "validation_or_test_supervision_changed": False,
        "branch_supervision": "First divergent token and its following token, covering partially shared BPE prefixes.",
        "full_completion_rows": sum(o["mode"] == "FULL_COMPLETION" for o in observations),
        "decision_rows": sum(o["mode"] == "DECISION_TOKENS" for o in observations),
        "supervised_tokens": sum(o["supervised_tokens"] for o in observations),
        "rows": observations,
    }
