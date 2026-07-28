"""Regression guard for #10750 — a wiki lesson must not be superseded by an
unrelated topic (content-integrity of the supersession graph).

A sampled adversarial re-audit of PR #10732 (wiki maintenance) upheld a real
content-integrity escape: the testing-topic entry "Header.jsx status dot:
encode state via aria-label/title..." (an accessibility-testing lesson) was
flipped ``status: superseded`` with ``superseded_by`` pointing at "PRManager
changes must mirror in FakeGitHub" — a completely unrelated synthesis entry
that also listed the aria-label entry in its ``supersedes``. This is NOT the
cartesian mapping bug (#10566, which now honors the LLM's per-entry
``supersedes_ids``); it is the synthesis LLM itself declaring a topically-wrong
``supersedes`` id. Following the ``superseded_by`` pointer landed on unrelated
PRManager/FakeGitHub content, so the still-true accessibility lesson became
effectively unreachable (the "N-to-1 wiki merges silently drop predecessor
lessons" class, gotchas #1157).

Structural bidirectional consistency did NOT catch it — the corrupt state was
internally consistent (both edges present). The defect is semantic: a topical
mismatch. This guard pins that specific mismatch, keyed on H1 titles so it
survives the wiki's constant renumbering: the Header.jsx aria-label lesson must
never be superseded by (nor listed in the ``supersedes`` of) the
PRManager/FakeGitHub mirroring lesson.
"""

from __future__ import annotations

from pathlib import Path

from wiki_supersession_repair import load_topic_entries

_TESTING_TOPIC = (
    Path(__file__).resolve().parents[2]
    / "repo_wiki"
    / "T-rav"
    / "hydraflow"
    / "testing"
)


def _is_aria_label_lesson(title: str) -> bool:
    t = title.lower()
    return "status dot" in t and "aria-label" in t


def _is_prmanager_mirror_lesson(title: str) -> bool:
    t = title.lower()
    return "prmanager" in t and "fakegithub" in t


def test_header_aria_label_lesson_not_superseded_by_prmanager_topic() -> None:
    entries = load_topic_entries(_TESTING_TOPIC)
    assert entries, f"no tracked wiki entries found under {_TESTING_TOPIC}"

    by_id = {e.id: e for e in entries if e.id}
    aria = [e for e in entries if _is_aria_label_lesson(e.title)]
    assert aria, "the Header.jsx aria-label accessibility lesson is missing"

    for entry in aria:
        # 1) Its superseded_by (if any) must not point at the PRManager topic.
        if entry.superseded_by:
            successor = by_id.get(entry.superseded_by)
            assert successor is not None, (
                f"entry {entry.id!r} superseded_by {entry.superseded_by!r} which "
                "does not resolve to a tracked entry"
            )
            assert not _is_prmanager_mirror_lesson(successor.title), (
                f"aria-label lesson {entry.id!r} is superseded by unrelated "
                f"PRManager/FakeGitHub entry {successor.id!r} — the #10750 escape"
            )

        # 2) No PRManager-topic entry may claim to supersede the aria-label lesson.
        claimers = [
            e
            for e in entries
            if entry.id in e.supersedes and _is_prmanager_mirror_lesson(e.title)
        ]
        assert not claimers, (
            f"PRManager/FakeGitHub entr{'y' if len(claimers) == 1 else 'ies'} "
            f"{[e.id for e in claimers]} wrongly list aria-label lesson "
            f"{entry.id!r} in supersedes — the #10750 escape"
        )
