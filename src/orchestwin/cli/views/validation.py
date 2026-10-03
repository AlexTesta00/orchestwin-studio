from __future__ import annotations

import json


def show(console, answer, *, details=False):
    if answer["kind"] == "orchestwin.scenario-walkthrough":
        console.say("validation.walkthrough", title=answer["scenario"]["title"])
        console.say("validation.task", value=answer.get("task") or "-")
        for step in answer["steps"]:
            console.write(f"  {step['number']}. {step['text']}")
            for gap in step.get("gaps", []):
                console.say("validation.gap." + gap["code"])
        console.say("validation.anchor_candidates", count=len(answer.get("anchor_candidates", [])))
        console.say("validation.synthetic_limit")
    else:
        console.say("validation.candidates", count=answer["candidate_count"])
        selected = answer["candidates"] if details else []
        for item in selected:
            console.write(f"  {item['title']} ({item['code']})")
        if len(selected) < answer["candidate_count"]:
            console.say("validation.more", count=answer["candidate_count"] - len(selected))
        console.say("validation.hypotheses", count=answer["summary"]["hypotheses"])
        for item in answer["hypotheses"]:
            if item.get("current", True) or details:
                console.write(f"  {item['code']}: {item.get('question') or item.get('task')}")
                console.say("validation.state." + item["state"])
                if not item.get("current", True):
                    console.say("validation.previous")
        console.say("validation.outcomes", count=len(answer["outcomes"]))
        for item in answer["outcomes"]:
            console.write(f"  {item['code']} · {item['session_ref']}")
            console.say("validation.session." + item["session_kind"])
            console.say(
                "validation.retired"
                if item["effective_status"] == "RETIRED"
                else "validation.state." + item["outcome"]
            )
            if item.get("coverage") == "PARTIAL":
                console.say("validation.partial")
            for gap in item.get("gaps", []):
                console.say("validation.gap." + gap["code"])
        console.say("validation.no_promotion")
    for omitted in answer.get("omitted_sections", []):
        console.say(
            "validation.omitted", value=json.dumps(omitted, ensure_ascii=True, sort_keys=True)
        )
    if details:
        console.write(json.dumps(answer, ensure_ascii=True, indent=2))
