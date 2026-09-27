from __future__ import annotations

from orchestwin.models.output_language import (
    DOMINANT_MARKER_RATIO,
    ENGLISH_MARKERS,
    ITALIAN_MARKERS,
    JUDGED_LANGUAGES,
    LANGUAGE_NAMES,
    MIN_DOMINANT_MARKERS,
    MIN_JUDGED_WORDS,
    MIN_OTHER_MARKERS,
    OTHER_MARKER_RATIO,
    dominant_language,
    word_count,
    written_in_another_language,
)

LIVE_REASONS = (
    "Addetti all'accoglienza prioritizes quick verification and duplicate detection, aligning "
    "with my tablet use and need for simple flows.",
    "Addetti all'accoglienza prioritizes table visibility but misses accessibility and feedback "
    "details.",
    "Responsabile di sala prioritizes accuracy and sharing, which aligns with my need for "
    "reliable calculations but conflicts with my focus on speed and simplicity.",
    "Coordinatrice dei prestiti prioritizes data integrity and editing capabilities, which "
    "conflict with my focus on quick registration.",
    "Segreteria didattica emphasizes accuracy and verification, which aligns with my goal of "
    "avoiding errors but conflicts with my need for speed.",
)
ITALIAN_TEXTS = (
    "Il pulsante 'Save and close' non spiega cosa succede ai dati",
    "Il pulsante 'Save and close' e il link 'Terms of the service' non spiegano cosa succede "
    "ai dati.",
    "Il filtro 'Show all' e il pulsante 'Search for bookings' sono chiari per me.",
    "Concordo con Responsabile di sala sulla verifica dei conti, ma a me serve soprattutto la "
    "velocità al banco.",
    "Il flusso guidato mi aiuta, però il modulo è troppo lungo quando ho la coda allo sportello.",
    "Nella schermata Settings il link Help non si vede e il toggle Dark mode è nascosto.",
    "Sì: se il riepilogo resta leggibile anche di notte, per me il flusso va bene.",
)


def test_the_markers_and_thresholds_are_fixed():
    assert (len(ITALIAN_MARKERS), len(ENGLISH_MARKERS)) == (42, 29)
    assert not ITALIAN_MARKERS & ENGLISH_MARKERS
    assert {"è", "più", "dalla", "questa"} <= ITALIAN_MARKERS
    assert {"the", "which", "would", "while"} <= ENGLISH_MARKERS
    assert JUDGED_LANGUAGES == {
        "it": (ITALIAN_MARKERS, ENGLISH_MARKERS),
        "en": (ENGLISH_MARKERS, ITALIAN_MARKERS),
    }
    assert (MIN_JUDGED_WORDS, MIN_OTHER_MARKERS, OTHER_MARKER_RATIO) == (6, 2, 2)


def test_the_english_reasons_of_the_live_run_are_not_in_the_language_of_an_italian_project():
    for reason in LIVE_REASONS:
        for locale in ("it-IT", "it_IT", "IT", "it"):
            assert written_in_another_language(reason, locale)
        for locale in ("en", "en-US", "EN_gb"):
            assert not written_in_another_language(reason, locale)


def test_italian_texts_that_quote_english_labels_stay_in_the_language_of_the_project():
    for text in ITALIAN_TEXTS:
        assert not written_in_another_language(text, "it-IT")


def test_short_texts_and_other_languages_are_never_judged():
    assert not written_in_another_language("Fine for the night shift", "it-IT")
    assert written_in_another_language("Fine for the night shift too", "it-IT")
    assert not written_in_another_language("Il modulo è per me", "en-US")
    for locale in ("fr-FR", "de", "es_ES", "pt-BR", ""):
        for text in (*LIVE_REASONS, *ITALIAN_TEXTS):
            assert not written_in_another_language(text, locale)


def test_words_are_case_folded_runs_of_letters_and_the_other_language_must_dominate():
    assert written_in_another_language("THE FLOW WORKS AND THE FORM IS LONG", "it-IT")
    assert written_in_another_language("IL MODULO È CHIARO MA LA RICERCA È LENTA", "en-US")
    assert written_in_another_language("the_and_which1with2that3this", "it-IT")
    assert not written_in_another_language("Il modulo and the form fields", "it-IT")
    assert written_in_another_language("Il modulo and the form with fields", "it-IT")
    assert not written_in_another_language("Prenotazioni veloci for turni notturni lunghi", "it")


def test_the_dominant_language_thresholds_and_names_are_fixed():
    assert (MIN_DOMINANT_MARKERS, DOMINANT_MARKER_RATIO) == (5, 2)
    assert LANGUAGE_NAMES == {"it": "Italian", "en": "English"}
    assert set(LANGUAGE_NAMES) == set(JUDGED_LANGUAGES)


def test_the_dominant_language_of_italian_and_english_texts():
    assert dominant_language(ITALIAN_TEXTS) == "it"
    assert dominant_language(LIVE_REASONS) == "en"
    assert dominant_language(iter(ITALIAN_TEXTS)) == "it"
    assert dominant_language(["THE FORM AND THE LIST ARE CLEAR FOR THE DESK"]) == "en"


def test_mixed_texts_have_no_dominant_language():
    assert dominant_language([*ITALIAN_TEXTS, *LIVE_REASONS]) is None
    assert dominant_language(["il la di che per", "the and"]) == "it"
    assert dominant_language(["il la di che per", "the and with"]) is None
    assert dominant_language(["the and with that this", "il e"]) == "en"
    assert dominant_language(["the and with that this", "il e la"]) is None


def test_too_little_text_has_no_dominant_language():
    assert dominant_language([]) is None
    assert dominant_language([""]) is None
    assert dominant_language(["Il modulo è chiaro"]) is None
    assert dominant_language(["il", "la", "di", "che"]) is None
    assert dominant_language(["il", "la", "di", "che", "per"]) == "it"
    assert dominant_language(["the form and the list"]) is None


def test_words_are_the_runs_of_letters():
    assert word_count("") == 0
    assert word_count("REQ-001") == 1
    assert word_count("T1") == 1
    assert word_count("create a reservation accurately") == 4
    assert word_count("the_and_which1with2that3this") == 6
    assert word_count("Il modulo è più chiaro, però lento.") == 7
