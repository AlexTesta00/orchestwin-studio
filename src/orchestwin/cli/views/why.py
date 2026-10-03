from __future__ import annotations

import json

from orchestwin.cli.views.workflow_inputs import show_limits


def show(console, answer, *, details=False):
    target = answer["target"]
    console.say("why.target", title=target["title"])
    labels = [
        target["code"],
        console.text("why.status." + target["display_status"]),
        console.text("why.version", version=target["reference"]["version_number"]),
    ]
    if target.get("rationale"):
        labels.append(console.text("why.origin." + target["rationale"]["origin"]))
    console.write(" · ".join(labels))
    summary = answer["summary"]
    console.say(
        "why.completeness",
        twin=console.text("why.boolean." + str(summary["complete_to_twin"]).lower()),
        evidence=console.text("why.boolean." + str(summary["complete_to_evidence"]).lower()),
        branches=console.text("why.boolean." + str(summary["all_paths_complete"]).lower()),
    )
    for key in ("upstream", "downstream", "human_validation"):
        console.say("why." + key, count=len(answer[key]))
        nodes = answer[key] if details else answer[key][:3]
        for node in nodes:
            console.write(f"  {node['title']} ({node['code']})")
            if details:
                console.write(console.text("why.status." + node["display_status"]))
                reference = node["reference"]
                console.write(
                    f"    version={reference['version_number']} content_hash={reference['content_hash']}"
                )
                rationale = node.get("rationale")
                if rationale:
                    console.say("why.origin." + rationale["origin"])
                    console.write(rationale["text"])
                console.write(
                    json.dumps(node.get("declared_context", {}), ensure_ascii=True, sort_keys=True)
                )
                for item in node.get("citations", []):
                    console.write(json.dumps(item, ensure_ascii=True, sort_keys=True))
        if not details and len(answer[key]) > len(nodes):
            console.say("why.more", count=len(answer[key]) - len(nodes))
    perspectives = answer.get("declared_context", {}).get("perspectives", [])
    if perspectives:
        console.say("why.context")
        for item in perspectives:
            console.write(str(item.get("title", item.get("name", item.get("perspective", item)))))
    gaps = answer.get("gaps", [])
    for limit in answer.get("limits", []):
        if limit in {"LEGACY_DOSSIER", "LEGACY_FEEDBACK_CONTEXT_MISSING"}:
            console.say("why.limit." + limit)
    show_limits(console, answer.get("limits", []))
    stop_reasons = set(summary["stop_reasons"])
    for key, selected in (
        ("why.interrupted", [gap for gap in gaps if gap["code"] in stop_reasons]),
        ("why.limits", [gap for gap in gaps if gap["code"] not in stop_reasons]),
    ):
        if not selected:
            continue
        console.say(key, count=len(selected))
        shown = selected if details else {gap["code"]: gap for gap in selected}.values()
        for gap in shown:
            console.write(console.text("why.gap." + gap["code"]))
            if details:
                console.write(json.dumps(gap, ensure_ascii=True, sort_keys=True))
    if details:
        console.write(
            json.dumps(
                {
                    "target": target,
                    "summary": answer["summary"],
                    "links": answer["links"],
                    "limits": answer.get("limits", []),
                },
                ensure_ascii=True,
                indent=2,
            )
        )
