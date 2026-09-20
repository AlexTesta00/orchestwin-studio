"""Normalize DOM identities/syntax without replacing letters inside natural language."""

import hashlib
import json
import re
from html.parser import HTMLParser

VOID = frozenset({"input", "img", "meta", "link", "br", "hr"})
REFERENCES = frozenset({"id", "for", "form", "aria-labelledby"})


class NormalizedHTML(HTMLParser):
    def __init__(self, raw, mapping):
        super().__init__(convert_charrefs=True)
        self.mapping, self.events = mapping, []
        self.feed(raw)
        self.close()

    def handle_starttag(self, tag, attrs):
        normalized = []
        for key, value in attrs:
            if key in REFERENCES and value is not None:
                value = " ".join(self.mapping.get(token, token) for token in value.split())
            normalized.append((key, value))
        self.events.append(("start", tag, sorted(normalized)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag not in VOID:
            self.events.append(("end", tag))

    def handle_data(self, data):
        if data.strip():
            self.events.append(("text", data.strip()))

    def handle_comment(self, data):
        self.events.append(("comment", data))

    def handle_decl(self, decl):
        self.events.append(("declaration", decl.lower()))


def semantic_key(row):
    user = json.loads(row["messages"][1]["content"])
    payload = user["input"]
    content = payload.get("verified_artifact_content")
    raw = content["items"][0]["data"] if content else None
    task = payload["artifact_bundle"]["scenario"]["task"]
    ids = list(
        dict.fromkeys(
            re.findall(r'\bid=["\']([^"\']+)', raw or "")
            + re.findall(r"#([A-Za-z][A-Za-z0-9_-]*)", task)
        )
    )
    mapping = {token: f"ELEMENT_{index}" for index, token in enumerate(ids)}
    task = re.sub(r"#([A-Za-z][A-Za-z0-9_-]*)", lambda m: "#" + mapping.get(m[1], m[1]), task)
    task = re.sub(
        r"form=([\"'])([^\"']+)\1", lambda m: "form='" + mapping.get(m[2], m[2]) + "'", task
    )
    value = dict(
        instruction=row["messages"][0]["content"],
        task=task,
        profile=payload["user_twin"]["profile"],
        html=NormalizedHTML(raw, mapping).events if raw is not None else None,
        schema=user["output_schema"],
        contract=user.get("response_contract"),
    )
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
