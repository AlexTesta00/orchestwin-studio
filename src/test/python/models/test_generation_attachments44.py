from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.models.structured_generation import (
    ATTACHMENT_MEDIA_TYPES,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    GenerationAttachment,
    ModelRuntimeIdentity,
    create_structured_generation_request,
    create_structured_json_schema,
    structured_generation_request_hash,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-screenshot-001"
JPEG = b"\xff\xd8\xff\xe0" + b"synthetic-screenshot-002"
HASH_BEFORE_ATTACHMENTS = "44c8261f1edec86d3f42732700895d29b66046afc7e6e9f88ea32a2b77a0a686"
SNAPSHOT_HASH_BEFORE_ATTACHMENTS = (
    "9f51660f5d283353552c6aa853a0c0ac763929bed39e6865ac59c27d47569d56"
)
IDENTITY = ModelRuntimeIdentity(
    provider_id="claude-code",
    runtime_id="claude-code-cli",
    base_model_repository="anthropic/claude-opus-5-5",
    base_model_revision="claude-opus-5-5",
    tokenizer_revision="claude-opus-5-5",
    configuration_sha256="c" * 64,
)
SCHEMA = create_structured_json_schema(
    schema_id="proposal-user-twin-evaluation-v1",
    version_number=1,
    schema_payload={
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    },
)


def screenshot(number=1, content=PNG, media_type="image/png"):
    extension = "png" if media_type == "image/png" else "jpg"
    return GenerationAttachment(f"screenshot-{number:03d}.{extension}", media_type, content)


def request(**changes):
    values = {
        "request_id": UUID("00000000-0000-4000-8000-000000440001"),
        "task_id": "proposal-user-twin-evaluation-v1",
        "expected_identity": IDENTITY,
        "output_schema": SCHEMA,
        "system_instruction": "Read every named screenshot with the Read tool before answering.",
        "input_payload": {"context": {"design": {"screens": [{"code": "SCR-001"}]}}},
        "allowed_evidence_refs": (),
        "prompt_version_ref": "s44-design-critique-v1",
        "temperature": 1.0,
        "max_output_tokens": 3072,
        "timeout_seconds": 900,
    }
    return create_structured_generation_request(**{**values, **changes})


def test_an_attachment_names_its_digest_and_its_size_without_showing_its_bytes():
    attachment = screenshot()
    digest = hashlib.sha256(PNG).hexdigest()
    assert (attachment.sha256, attachment.byte_size) == (digest, len(PNG))
    assert attachment.reference() == {
        "name": "screenshot-001.png",
        "media_type": "image/png",
        "sha256": digest,
        "byte_size": len(PNG),
    }
    assert "synthetic-screenshot" not in repr(attachment)
    assert sorted(ATTACHMENT_MEDIA_TYPES) == ["image/jpeg", "image/png"]
    assert (MAX_ATTACHMENTS, MAX_ATTACHMENT_BYTES) == (4, 5 * 1024 * 1024)


@pytest.mark.parametrize("name", ["screenshot-001.png", "page_2.jpg", "0", "s" * 64])
def test_a_short_lower_case_file_name_is_accepted(name):
    assert GenerationAttachment(name, "image/jpeg", JPEG).name == name


@pytest.mark.parametrize(
    "name",
    [
        "Screenshot-001.png",
        "screenshot 001.png",
        "",
        ".screenshot.png",
        "-screenshot.png",
        "shots/screenshot-001.png",
        "..\\screenshot-001.png",
        "screenshot-001.png\n",
        "s" * 65,
        None,
    ],
)
def test_a_name_with_capitals_spaces_folders_or_too_many_characters_is_refused(name):
    with pytest.raises(ValueError, match="name is invalid"):
        GenerationAttachment(name, "image/png", PNG)


@pytest.mark.parametrize("media_type", ["image/gif", "IMAGE/PNG", "image/webp", "", None])
def test_a_media_type_other_than_png_or_jpeg_is_refused(media_type):
    with pytest.raises(ValueError, match="media type is not supported"):
        GenerationAttachment("screenshot-001.png", media_type, PNG)


def test_the_content_holds_between_one_byte_and_five_megabytes():
    largest = bytes(MAX_ATTACHMENT_BYTES)
    accepted = GenerationAttachment("screenshot-001.png", "image/png", largest)
    assert accepted.byte_size == 5_242_880
    for content in (b"", largest + b"\x00"):
        with pytest.raises(ValueError, match="invalid size"):
            GenerationAttachment("screenshot-001.png", "image/png", content)
    with pytest.raises(ValueError, match="must be bytes"):
        GenerationAttachment("screenshot-001.png", "image/png", bytearray(PNG))


def test_a_request_with_two_attachments_keeps_their_references_and_no_bytes():
    first, second = screenshot(), screenshot(2, JPEG, "image/jpeg")
    attached = request(attachments=(first, second))
    snapshot = attached.to_snapshot()
    assert attached.attachments == (first, second)
    assert snapshot["attachments"] == [first.reference(), second.reference()]
    assert "synthetic-screenshot" not in json.dumps(snapshot)
    assert snapshot["content_hash"] == attached.content_hash
    assert attached.content_hash != HASH_BEFORE_ATTACHMENTS


def test_a_request_without_attachments_keeps_the_hash_and_the_snapshot_of_before():
    plain = request()
    assert plain.attachments == ()
    assert plain.content_hash == HASH_BEFORE_ATTACHMENTS
    assert request(attachments=()).content_hash == HASH_BEFORE_ATTACHMENTS
    assert request(attachments=[]).content_hash == HASH_BEFORE_ATTACHMENTS
    snapshot = plain.to_snapshot()
    assert "attachments" not in snapshot
    assert snapshot_content_hash(snapshot) == SNAPSHOT_HASH_BEFORE_ATTACHMENTS
    recomputed = structured_generation_request_hash(
        request_id=plain.request_id,
        task_id=plain.task_id,
        expected_identity=plain.expected_identity,
        output_schema=plain.output_schema,
        system_instruction=plain.system_instruction,
        input_payload_json=plain.input_payload_json,
        allowed_evidence_refs=plain.allowed_evidence_refs,
        prompt_version_ref=plain.prompt_version_ref,
        temperature=plain.temperature,
        max_output_tokens=plain.max_output_tokens,
        timeout_seconds=plain.timeout_seconds,
        schema_version=plain.schema_version,
    )
    assert recomputed == HASH_BEFORE_ATTACHMENTS


def test_more_than_four_attachments_or_a_repeated_name_are_refused():
    five = tuple(screenshot(number) for number in range(1, 6))
    assert len(request(attachments=five[:4]).attachments) == 4
    with pytest.raises(ValueError, match="at most 4 attachments"):
        request(attachments=five)
    repeated = (screenshot(), GenerationAttachment("screenshot-001.png", "image/jpeg", JPEG))
    with pytest.raises(ValueError, match="names must be unique"):
        request(attachments=repeated)


def test_the_hash_follows_the_content_and_the_order_of_the_attachments():
    first, second = screenshot(), screenshot(2, JPEG, "image/jpeg")
    one = request(attachments=(first,))
    changed = screenshot(content=PNG + b"!")
    assert request(attachments=(changed,)).content_hash != one.content_hash
    assert one.content_hash != HASH_BEFORE_ATTACHMENTS
    forward = request(attachments=(first, second)).content_hash
    assert forward != request(attachments=(second, first)).content_hash
    for attachments in ((changed,), ()):
        with pytest.raises(ValueError, match="content hash is inconsistent"):
            replace(one, attachments=attachments)


def test_a_request_holds_only_a_tuple_of_attachments():
    one = request(attachments=(screenshot(),))
    with pytest.raises(ValueError, match="tuple of attachments"):
        replace(one, attachments=[screenshot()])
    with pytest.raises(ValueError, match="tuple of attachments"):
        request(attachments=({"name": "screenshot-001.png"},))
