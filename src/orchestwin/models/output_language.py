from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

MIN_JUDGED_WORDS: Final = 6
MIN_OTHER_MARKERS: Final = 2
OTHER_MARKER_RATIO: Final = 2
MIN_DOMINANT_MARKERS: Final = 5
DOMINANT_MARKER_RATIO: Final = 2
LANGUAGE_NAMES: Final = {"it": "Italian", "en": "English"}
ITALIAN_MARKERS: Final = frozenset(
    [
        "il",
        "lo",
        "la",
        "i",
        "gli",
        "le",
        "un",
        "una",
        "di",
        "del",
        "della",
        "dei",
        "delle",
        "che",
        "per",
        "con",
        "non",
        "ma",
        "e",
        "è",
        "sono",
        "ha",
        "nel",
        "nella",
        "sul",
        "sulla",
        "come",
        "più",
        "anche",
        "se",
        "mi",
        "ci",
        "si",
        "al",
        "alla",
        "ai",
        "alle",
        "da",
        "dal",
        "dalla",
        "questo",
        "questa",
    ]
)
ENGLISH_MARKERS: Final = frozenset(
    [
        "the",
        "and",
        "which",
        "with",
        "that",
        "this",
        "is",
        "are",
        "for",
        "not",
        "but",
        "has",
        "have",
        "from",
        "would",
        "should",
        "my",
        "our",
        "their",
        "of",
        "to",
        "it",
        "be",
        "can",
        "will",
        "more",
        "than",
        "when",
        "while",
    ]
)
JUDGED_LANGUAGES: Final = {
    "it": (ITALIAN_MARKERS, ENGLISH_MARKERS),
    "en": (ENGLISH_MARKERS, ITALIAN_MARKERS),
}
_LOCALE_SEPARATOR: Final = re.compile(r"[-_]")
_LETTERS: Final = re.compile(r"[^\W\d_]+")


def written_in_another_language(text: str, locale: str) -> bool:
    language = _LOCALE_SEPARATOR.split(locale, maxsplit=1)[0].casefold()
    if language not in JUDGED_LANGUAGES:
        return False
    words = _LETTERS.findall(text.casefold())
    if len(words) < MIN_JUDGED_WORDS:
        return False
    own_markers, other_markers = JUDGED_LANGUAGES[language]
    own = sum(word in own_markers for word in words)
    other = sum(word in other_markers for word in words)
    return other >= MIN_OTHER_MARKERS and other > OTHER_MARKER_RATIO * own


def word_count(text: str) -> int:
    return len(_LETTERS.findall(text))


def dominant_language(texts: Iterable[str]) -> str | None:
    italian = english = 0
    for text in texts:
        words = _LETTERS.findall(text.casefold())
        italian += sum(word in ITALIAN_MARKERS for word in words)
        english += sum(word in ENGLISH_MARKERS for word in words)
    if italian >= MIN_DOMINANT_MARKERS and italian > DOMINANT_MARKER_RATIO * english:
        return "it"
    if english >= MIN_DOMINANT_MARKERS and english > DOMINANT_MARKER_RATIO * italian:
        return "en"
    return None


__all__ = [
    "DOMINANT_MARKER_RATIO",
    "ENGLISH_MARKERS",
    "ITALIAN_MARKERS",
    "JUDGED_LANGUAGES",
    "LANGUAGE_NAMES",
    "MIN_DOMINANT_MARKERS",
    "MIN_JUDGED_WORDS",
    "MIN_OTHER_MARKERS",
    "OTHER_MARKER_RATIO",
    "dominant_language",
    "word_count",
    "written_in_another_language",
]
