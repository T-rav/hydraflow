"""Regression for issue #9566 — bare-word over-matching in SUBCATEGORY_KEYWORDS.

``src/harness_insights.py`` ``SUBCATEGORY_KEYWORDS`` (line 56) uses broad bare
single-word keywords — ``type``, ``format``, ``style``, ``test``, ``coverage``,
``convention``, ``exception`` — and :func:`extract_subcategories` matches them as
plain *substrings* (``kw.lower() in lower``), not on word boundaries. This is the
same class of bug fixed in ``review_insights.CATEGORY_KEYWORDS`` (#9545 / #9426),
where the fix replaced bare substring matching with whole-word / deficiency-phrase
keywords.

Even though the subcategory extractor runs over agent failure-detail logs
(inherently negative, so praise over-matching is less acute), the bare substrings
still *mis-bucket* failures into the wrong subcategory:

  - ``format`` is a substring of "in**format**ion" / "trans**format**ion"
    → unrelated text mis-bucketed as ``lint_error``
  - ``test`` is a substring of "la**test**" / "grea**test**"
    → unrelated text mis-bucketed as ``test_failure``
  - ``type`` is a substring of "proto**type**" / "**type**script"
    → unrelated text mis-bucketed as ``type_error``

These tests assert that neutral / unrelated failure detail text does NOT match the
wrong subcategory, plus a ratchet guard mirroring #9545 that fails CI if a bare
broad single-word keyword is (re)introduced into ``SUBCATEGORY_KEYWORDS``.

RED against current code: every case below mis-buckets, and the ratchet guard
finds several bare keywords outside the deficiency allowlist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from harness_insights import (  # noqa: E402
    SUBCATEGORY_KEYWORDS,
    extract_subcategories,
)

# Failure-detail strings that are unrelated to the named subcategory but, under
# bare-substring matching, falsely match it. (detail, subcategory-that-must-NOT-match)
_FALSE_MATCH_CASES: list[tuple[str, str]] = [
    # "information" contains the substring "format"
    ("The agent received outdated information from the API and stalled.", "lint_error"),
    # "transformation" contains the substring "format"
    (
        "The transformation step produced an empty payload and was retried.",
        "lint_error",
    ),
    # "latest" contains the substring "test"
    (
        "Implementer fetched the latest commit before retrying the build.",
        "test_failure",
    ),
    # "prototype" contains the substring "type"
    ("A new prototype handler was wired into the dispatcher.", "type_error"),
    # "typescript" contains the substring "type"
    ("The typescript bundle failed to upload to the artifact store.", "type_error"),
]


@pytest.mark.parametrize(("detail", "wrong_subcategory"), _FALSE_MATCH_CASES)
def test_unrelated_detail_does_not_mis_bucket(
    detail: str, wrong_subcategory: str
) -> None:
    """Neutral/unrelated failure text must not match a wrong subcategory (#9566)."""
    matched = extract_subcategories(detail)
    assert wrong_subcategory not in matched, (
        f"{detail!r} was mis-bucketed as {wrong_subcategory!r} via bare-substring "
        f"matching; got {matched}"
    )


# Single words that are inherently deficiency-signalling are allowed to stay bare.
# Mirrors the allowlist convention from #9545 (review_insights ratchet guard).
_SINGLE_WORD_ALLOWLIST: frozenset[str] = frozenset(
    {
        "ruff",
        "pyright",
        "mypy",
        "pytest",
        "untested",
        "timeout",
        "syntax",
        "conflict",
        "screenshot",
    }
)


def test_subcategory_keywords_ratchet_guard() -> None:
    """Every SUBCATEGORY_KEYWORDS entry is a phrase or an allowlisted word (#9566).

    A keyword is acceptable if it contains a space, ``/`` or ``-`` (i.e. it is a
    phrase, which cannot accidentally appear inside a larger identifier), or if it
    is in the small documented deficiency allowlist. Bare broad single words such
    as ``type``/``format``/``style``/``test``/``coverage``/``convention``/
    ``exception`` are the over-matching offenders and must be removed or qualified.
    """
    offenders: list[tuple[str, str]] = []
    for subcategory, keywords in SUBCATEGORY_KEYWORDS.items():
        for kw in keywords:
            is_phrase = any(c in kw for c in (" ", "/", "-"))
            if not is_phrase and kw.lower() not in _SINGLE_WORD_ALLOWLIST:
                offenders.append((subcategory, kw))

    assert not offenders, (
        "Bare broad single-word keywords found in SUBCATEGORY_KEYWORDS — these "
        "match as substrings inside larger words and mis-bucket failures. Qualify "
        "them as phrases or add to the deficiency allowlist (#9566): "
        f"{offenders}"
    )
