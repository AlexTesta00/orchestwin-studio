from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts.design_discussion import (
    MAX_CONFLICT_TOPIC_LENGTH,
    MAX_DISCUSSION_ROUNDS,
    MAX_OWNER_ANSWER_LENGTH,
    MAX_QUESTION_LENGTH,
    MAX_REACTION_REASON_LENGTH,
    MAX_STATEMENT_LENGTH,
    DesignDiscussion,
    DiscussionProposalTarget,
    DiscussionStance,
    DiscussionStatus,
    DiscussionSynthesis,
    ReactionVerdict,
    SynthesisConflict,
    SynthesisProposal,
    TwinReaction,
    TwinStatement,
    create_discussion_round,
    design_discussion_from_snapshot,
    discussion_round_from_snapshot,
    normalize_owner_note,
    proposal_code,
    validate_locale,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
PROJECT = UUID("00000000-0000-4000-8000-000000000001")
OWNER = UUID("00000000-0000-4000-8000-000000000002")
VERSION = UUID("00000000-0000-4000-8000-000000000003")
ALTERNATIVE = UUID("00000000-0000-4000-8000-000000000004")
DISCUSSION = UUID("00000000-0000-4000-8000-000000000005")
ADA = UUID("00000000-0000-4000-8000-000000000a01")
BRUNO = UUID("00000000-0000-4000-8000-000000000b02")
CARLA = UUID("00000000-0000-4000-8000-000000000c03")


def statement(twin_id=ADA, name="Ada", generation=11, **changes):
    values = {
        "twin_id": twin_id,
        "twin_version": 1,
        "twin_name": name,
        "stance": DiscussionStance.CONCERN,
        "statement": "La ricerca funziona, ma il modulo di prenotazione è troppo lungo.",
        "replies_to": (),
        "proposals": ("Accorciare il modulo di prenotazione.",),
        "grounded_on": ("user_twin.goals", "user_twin.frustrations"),
        "confidence": 0.7,
        "model_generation_id": UUID(int=generation),
    }
    values.update(changes)
    return TwinStatement(**values)


def conflict(*positions, topic="Densità della dashboard"):
    return SynthesisConflict(
        topic=topic,
        positions=positions or ((ADA, "È troppo densa."), (BRUNO, "Va bene così.")),
    )


def proposal(ordinal=1, text="Accorciare il modulo.", supported_by=(ADA,)):
    return SynthesisProposal(
        code=proposal_code(ordinal),
        text=text,
        target=DiscussionProposalTarget.DESIGN,
        supported_by=supported_by,
    )


def synthesis(generation=13, **changes):
    values = {
        "agreements": ("Il flusso di prenotazione è chiaro.",),
        "conflicts": (conflict(),),
        "proposals": (proposal(),),
        "questions_for_owner": ("Serve una modalità per utenti esperti?",),
        "model_generation_id": UUID(int=generation),
    }
    values.update(changes)
    return DiscussionSynthesis(**values)


def discussion_round(ordinal=1, *, replies=(), note=None, minutes=None, **changes):
    base = 100 * ordinal
    values = {
        "ordinal": ordinal,
        "owner_note": note,
        "statements": (
            statement(generation=base + 1, replies_to=replies),
            statement(BRUNO, "Bruno", generation=base + 2, stance=DiscussionStance.SUPPORT),
        ),
        "synthesis": synthesis(generation=base + 3),
        "created_at": NOW + timedelta(minutes=ordinal if minutes is None else minutes),
    }
    values.update(changes)
    return create_discussion_round(**values)


def reaction(
    twin_id=BRUNO, verdict=ReactionVerdict.PARTLY, reason="Capisco, ma al banco serve rapidità."
):
    return TwinReaction(twin_id=twin_id, verdict=verdict, reason=reason)


def reacting_round(ordinal=2):
    base = 100 * ordinal
    return discussion_round(
        ordinal,
        statements=(
            statement(
                generation=base + 1,
                statement="Ora accetto il riepilogo, ma il modulo resta lungo per me.",
                replies_to=(BRUNO,),
                reactions=(reaction(),),
            ),
            statement(
                BRUNO,
                "Bruno",
                generation=base + 2,
                statement="Concordo con Ada: anche di notte il modulo mi rallenta.",
                replies_to=(ADA,),
                reactions=(reaction(ADA, ReactionVerdict.AGREE, "Anche io perdo tempo."),),
            ),
        ),
    )


def discussion(**changes):
    values = {
        "id": DISCUSSION,
        "project_id": PROJECT,
        "owner_user_id": OWNER,
        "design_version_id": VERSION,
        "design_version_number": 2,
        "design_content_hash": "a" * 64,
        "alternative_id": ALTERNATIVE,
        "alternative_code": "DES-002",
        "locale": "it-IT",
        "status": DiscussionStatus.OPEN,
        "rounds": (discussion_round(),),
        "created_at": NOW,
        "decided_at": None,
    }
    values.update(changes)
    return DesignDiscussion(**values)


def test_snapshot_has_the_exact_shape_read_by_the_frontend_and_round_trips():
    item = discussion(rounds=(discussion_round(), discussion_round(2, replies=(BRUNO,))))
    snapshot = item.to_snapshot()
    assert set(snapshot) == {
        "id",
        "project_id",
        "owner_user_id",
        "design_version_id",
        "design_version_number",
        "design_content_hash",
        "alternative_id",
        "alternative_code",
        "status",
        "created_at",
        "decided_at",
        "max_rounds",
        "rounds",
    }
    assert snapshot["max_rounds"] == MAX_DISCUSSION_ROUNDS == 4
    assert snapshot["decided_at"] is None
    assert snapshot["status"] == "OPEN"
    first = snapshot["rounds"][0]
    assert set(first) == {
        "ordinal",
        "owner_note",
        "created_at",
        "content_hash",
        "statements",
        "synthesis",
    }
    assert set(first["statements"][0]) == {
        "twin_id",
        "twin_version",
        "twin_name",
        "stance",
        "statement",
        "replies_to",
        "proposals",
        "grounded_on",
        "confidence",
        "model_generation_id",
    }
    assert first["synthesis"] == {
        "agreements": ["Il flusso di prenotazione è chiaro."],
        "conflicts": [
            {
                "topic": "Densità della dashboard",
                "positions": [
                    {"twin_id": str(ADA), "position": "È troppo densa."},
                    {"twin_id": str(BRUNO), "position": "Va bene così."},
                ],
            }
        ],
        "proposals": [
            {
                "code": "PRP-001",
                "text": "Accorciare il modulo.",
                "target": "DESIGN",
                "supported_by": [str(ADA)],
            }
        ],
        "questions_for_owner": ["Serve una modalità per utenti esperti?"],
        "model_generation_id": str(UUID(int=103)),
    }
    assert snapshot["rounds"][1]["statements"][0]["replies_to"] == [str(BRUNO)]
    assert design_discussion_from_snapshot(snapshot, locale="it-IT") == item
    assert discussion_round_from_snapshot(first) == item.rounds[0]
    assert item.participants == (ADA, BRUNO)


def test_round_hash_and_canonical_snapshots_detect_tampering():
    round_ = discussion_round()
    snapshot = round_.to_snapshot()
    edited = {**snapshot, "statements": [dict(item) for item in snapshot["statements"]]}
    edited["statements"][0]["statement"] = "Tutto perfetto."
    with pytest.raises(ValueError, match="hash is inconsistent"):
        discussion_round_from_snapshot(edited)
    with pytest.raises(ValueError, match="hash is inconsistent"):
        discussion_round_from_snapshot({**snapshot, "content_hash": "f" * 64})
    with pytest.raises(ValueError, match="hash is inconsistent"):
        replace(round_, owner_note="Una nota diversa.")
    with pytest.raises(ValueError, match="not canonical"):
        design_discussion_from_snapshot(
            {**discussion().to_snapshot(), "max_rounds": 5}, locale="it"
        )


def test_owner_notes_are_normalized_and_bounded():
    assert normalize_owner_note(None) is None
    assert normalize_owner_note("  Più   veloce\nper favore ") == "Più veloce per favore"
    assert discussion_round(note="  Più   veloce ").owner_note == "Più veloce"
    for note in ("   ", "x" * 1001):
        with pytest.raises(ValueError):
            normalize_owner_note(note)


def test_statements_are_grounded_normalized_and_bounded():
    assert statement().content_hash == statement().content_hash
    assert statement().content_hash != statement(confidence=0.71).content_hash
    for changes in (
        {"grounded_on": ()},
        {"grounded_on": ("user_twin.made_up",)},
        {"grounded_on": ("user_twin.goals", "user_twin.goals")},
        {
            "grounded_on": (
                "user_twin.goals",
                "user_twin.role",
                "user_twin.frustrations",
                "user_twin.pain_points",
                "user_twin.expertise",
            )
        },
        {"confidence": 1},
        {"confidence": 1.2},
        {"proposals": ("Uno.", "Due.", "Tre.", "Quattro.")},
        {"proposals": ("Uno.", "Uno.")},
        {"proposals": (" Uno.",)},
        {"statement": "x" * (MAX_STATEMENT_LENGTH + 1)},
        {"statement": "Due  spazi."},
        {"twin_name": " Ada"},
        {"replies_to": (ADA,)},
        {"replies_to": (BRUNO, BRUNO)},
        {"stance": "SUPPORT"},
        {"twin_version": 0},
    ):
        with pytest.raises(ValueError):
            statement(**changes)


def test_synthesis_names_distinct_twins_and_numbers_its_proposals():
    assert synthesis(conflicts=(), proposals=(), agreements=(), questions_for_owner=())
    for build in (
        lambda: conflict((ADA, "Solo io.")),
        lambda: conflict((ADA, "Sì."), (ADA, "No.")),
        lambda: conflict((ADA, "Sì."), (BRUNO, " No.")),
        lambda: conflict(topic="x" * (MAX_CONFLICT_TOPIC_LENGTH + 1)),
        lambda: proposal(supported_by=()),
        lambda: proposal(supported_by=(ADA, ADA)),
        lambda: SynthesisProposal(
            code="REQ-001",
            text="Accorciare il modulo.",
            target=DiscussionProposalTarget.DESIGN,
            supported_by=(ADA,),
        ),
    ):
        with pytest.raises(ValueError):
            build()
    for changes in (
        {"conflicts": tuple(conflict(topic=f"Tema {index}") for index in range(5))},
        {"proposals": (proposal(2),)},
        {"proposals": (proposal(1), proposal(2, text="Accorciare il modulo."))},
        {"proposals": tuple(proposal(index, text=f"Proposta {index}.") for index in range(1, 7))},
        {"agreements": tuple(f"Accordo {index}." for index in range(6))},
        {"agreements": ("Uguale.", "Uguale.")},
        {"questions_for_owner": tuple(f"Domanda {index}?" for index in range(5))},
        {"questions_for_owner": ("x" * (MAX_QUESTION_LENGTH + 1),)},
    ):
        with pytest.raises(ValueError):
            synthesis(**changes)


def test_rounds_hold_one_statement_per_twin_and_replies_only_after_the_first():
    assert discussion_round(2, replies=(BRUNO,)).statements[0].replies_to == (BRUNO,)
    with pytest.raises(ValueError, match="first round"):
        discussion_round(replies=(BRUNO,))
    with pytest.raises(ValueError, match="participants"):
        discussion_round(2, replies=(CARLA,))
    with pytest.raises(ValueError, match="one statement per twin"):
        discussion_round(statements=(statement(generation=1), statement(generation=2)))
    with pytest.raises(ValueError, match="one statement per twin"):
        discussion_round(statements=())
    with pytest.raises(ValueError, match="synthesis names only"):
        discussion_round(
            synthesis=synthesis(generation=103, proposals=(proposal(supported_by=(CARLA,)),))
        )
    with pytest.raises(ValueError, match="distinct generations"):
        discussion_round(synthesis=synthesis(generation=101))
    for ordinal in (0, MAX_DISCUSSION_ROUNDS + 1):
        with pytest.raises(ValueError, match="round ordinal"):
            discussion_round(ordinal)
    with pytest.raises(ValueError, match="timezone-aware"):
        discussion_round(created_at=datetime(2026, 9, 27, 10, 0))


def test_discussions_keep_their_rounds_ordered_among_the_same_twins():
    four = tuple(discussion_round(ordinal) for ordinal in range(1, 5))
    assert len(discussion(rounds=four).rounds) == 4
    for changes, message in (
        ({"rounds": ()}, "rounds"),
        ({"rounds": (discussion_round(2),)}, "numbered"),
        ({"rounds": (*four, discussion_round(4))}, "rounds"),
        ({"rounds": (discussion_round(minutes=-1),)}, "in time"),
        (
            {
                "rounds": (
                    discussion_round(),
                    discussion_round(
                        2,
                        statements=(statement(generation=201), statement(CARLA, "Carla", 202)),
                        synthesis=synthesis(generation=203, conflicts=(), proposals=()),
                    ),
                )
            },
            "same twins",
        ),
        ({"decided_at": NOW + timedelta(hours=1)}, "decision time"),
        ({"status": DiscussionStatus.APPROVED}, "decision time"),
        (
            {"status": DiscussionStatus.CLOSED, "decided_at": NOW + timedelta(seconds=30)},
            "after its last round",
        ),
        ({"locale": "it IT"}, "language tag"),
        ({"alternative_code": "ALT-001"}, "DES"),
        ({"design_content_hash": "A" * 64}, "SHA-256"),
        ({"created_at": datetime(2026, 9, 27, 10, 0)}, "timezone-aware"),
        ({"status": "OPEN"}, "DiscussionStatus"),
    ):
        with pytest.raises(ValueError, match=message):
            discussion(**changes)


def test_rounds_are_appended_while_open_and_a_decision_is_final():
    opened = discussion()
    extended = opened.with_round(discussion_round(2, replies=(BRUNO,)))
    assert [item.ordinal for item in extended.rounds] == [1, 2]
    decided_at = NOW + timedelta(hours=1)
    approved = extended.decided(DiscussionStatus.APPROVED, decided_at)
    assert approved.status is DiscussionStatus.APPROVED
    assert approved.to_snapshot()["decided_at"] == decided_at.isoformat()
    assert design_discussion_from_snapshot(approved.to_snapshot(), locale="it-IT") == approved
    closed = opened.decided(DiscussionStatus.CLOSED, decided_at)
    assert closed.status is DiscussionStatus.CLOSED
    with pytest.raises(ValueError, match="already been decided"):
        approved.decided(DiscussionStatus.CLOSED, decided_at)
    with pytest.raises(ValueError, match="open discussion"):
        closed.with_round(discussion_round(2))
    with pytest.raises(ValueError, match="approves or closes"):
        opened.decided(DiscussionStatus.OPEN, decided_at)
    with pytest.raises(ValueError, match="numbered"):
        opened.with_round(discussion_round(3))


@pytest.mark.parametrize("locale", ["it", "it-IT", "en-US", "pt-BR", "zh-Hant-TW"])
def test_language_tags_are_accepted(locale):
    validate_locale(locale)


@pytest.mark.parametrize("locale", ["", "i", "it_IT", "it IT", "italiano-molto-lungo-XX", None])
def test_malformed_language_tags_are_rejected(locale):
    with pytest.raises(ValueError):
        validate_locale(locale)


def test_reactions_are_serialized_only_when_present_and_round_trip():
    later = reacting_round()
    snapshot = later.to_snapshot()
    ada, bruno = snapshot["statements"]
    assert ada["reactions"] == [
        {
            "twin_id": str(BRUNO),
            "verdict": "PARTLY",
            "reason": "Capisco, ma al banco serve rapidità.",
        }
    ]
    assert ada["replies_to"] == [str(BRUNO)]
    assert bruno["reactions"] == [
        {"twin_id": str(ADA), "verdict": "AGREE", "reason": "Anche io perdo tempo."}
    ]
    assert later.statements[0].reacted_twins == (BRUNO,)
    assert discussion_round_from_snapshot(snapshot) == later
    item = discussion(rounds=(discussion_round(), later))
    assert design_discussion_from_snapshot(item.to_snapshot(), locale="it-IT") == item
    opening = discussion_round().to_snapshot()
    assert all("reactions" not in statement for statement in opening["statements"])
    padded = [{**statement, "reactions": []} for statement in opening["statements"]]
    with pytest.raises(ValueError, match="not canonical"):
        discussion_round_from_snapshot({**opening, "statements": padded})


def test_rounds_stored_before_reactions_reload_with_the_same_hash():
    stored = {
        "ordinal": 2,
        "owner_note": "Rispondetevi.",
        "created_at": "2026-09-27T10:02:00+00:00",
        "statements": [
            {
                "twin_id": str(ADA),
                "twin_version": 1,
                "twin_name": "Ada",
                "stance": "CONCERN",
                "statement": "Il modulo resta lungo.",
                "replies_to": [str(BRUNO)],
                "proposals": ["Accorciare il modulo."],
                "grounded_on": ["user_twin.goals"],
                "confidence": 0.7,
                "model_generation_id": str(UUID(int=201)),
            },
            {
                "twin_id": str(BRUNO),
                "twin_version": 1,
                "twin_name": "Bruno",
                "stance": "SUPPORT",
                "statement": "Per me va bene così.",
                "replies_to": [],
                "proposals": [],
                "grounded_on": ["user_twin.goals"],
                "confidence": 0.6,
                "model_generation_id": str(UUID(int=202)),
            },
        ],
        "synthesis": {
            "agreements": [],
            "conflicts": [],
            "proposals": [],
            "questions_for_owner": [],
            "model_generation_id": str(UUID(int=203)),
        },
    }
    stored["content_hash"] = snapshot_content_hash(stored)
    reloaded = discussion_round_from_snapshot(stored)
    assert reloaded.content_hash == stored["content_hash"]
    assert reloaded.to_snapshot() == stored
    assert [item.reactions for item in reloaded.statements] == [(), ()]
    assert reloaded.statements[0].replies_to == (BRUNO,)
    assert reloaded.owner_note == "Rispondetevi."
    assert [item.owner_answer for item in reloaded.statements] == [None, None]
    assert all("answer_to_owner" not in item for item in reloaded.to_snapshot()["statements"])


def test_reactions_name_other_participants_once_and_match_the_replies():
    for changes, message in (
        ({"replies_to": (BRUNO,), "reactions": (reaction(ADA),)}, "react to itself"),
        ({"replies_to": (BRUNO,), "reactions": (reaction(), reaction())}, "distinct twins"),
        ({"replies_to": (), "reactions": (reaction(),)}, "replies to the twins it reacts to"),
        (
            {"replies_to": (BRUNO, CARLA), "reactions": (reaction(),)},
            "replies to the twins it reacts to",
        ),
        ({"replies_to": (BRUNO,), "reactions": ("PARTLY",)}, "TwinReaction"),
        ({"replies_to": (BRUNO,), "reactions": [reaction()]}, "TwinReaction"),
    ):
        with pytest.raises(ValueError, match=message):
            statement(**changes)
    for build, message in (
        (lambda: reaction(verdict="AGREE"), "ReactionVerdict"),
        (lambda: reaction(reason=" Capisco."), "normalized"),
        (lambda: reaction(reason="x" * (MAX_REACTION_REASON_LENGTH + 1)), "exceeds"),
        (lambda: reaction(twin_id="b02"), "UUID"),
    ):
        with pytest.raises(ValueError, match=message):
            build()
    with pytest.raises(ValueError, match="first round"):
        discussion_round(
            statements=(
                statement(generation=101, replies_to=(BRUNO,), reactions=(reaction(),)),
                statement(BRUNO, "Bruno", generation=102),
            )
        )
    with pytest.raises(ValueError, match="participants"):
        discussion_round(
            2,
            statements=(
                statement(generation=201, replies_to=(CARLA,), reactions=(reaction(CARLA),)),
                statement(BRUNO, "Bruno", generation=202),
            ),
        )


def test_answers_to_the_owner_are_serialized_only_when_present():
    plain = statement()
    before = plain.to_snapshot()
    assert "answer_to_owner" not in before
    assert plain.content_hash == snapshot_content_hash(before)
    assert replace(plain, owner_answer=None).content_hash == plain.content_hash
    answered = statement(owner_answer="Sì, il riepilogo mi basta.")
    assert answered.to_snapshot() == {**before, "answer_to_owner": "Sì, il riepilogo mi basta."}
    assert answered.content_hash != plain.content_hash
    noted = discussion_round(
        note="Il riepilogo vi basta?",
        statements=(
            statement(generation=101, owner_answer="Sì, il riepilogo mi basta."),
            statement(BRUNO, "Bruno", generation=102),
        ),
    )
    snapshot = noted.to_snapshot()
    assert snapshot["statements"][0]["answer_to_owner"] == "Sì, il riepilogo mi basta."
    assert "answer_to_owner" not in snapshot["statements"][1]
    assert discussion_round_from_snapshot(snapshot) == noted
    unanswered = discussion_round(note="Il riepilogo vi basta?")
    assert discussion_round_from_snapshot(unanswered.to_snapshot()) == unanswered
    with pytest.raises(ValueError, match="an answer to the owner requires the owner's note"):
        discussion_round(
            statements=(
                statement(generation=101, owner_answer="Sì."),
                statement(BRUNO, "Bruno", generation=102),
            )
        )
    for answer, message in (
        (" Sì.", "normalized"),
        ("", "must not be empty"),
        ("x" * (MAX_OWNER_ANSWER_LENGTH + 1), "exceeds"),
        (7, "normalized"),
    ):
        with pytest.raises(ValueError, match=message):
            statement(owner_answer=answer)
