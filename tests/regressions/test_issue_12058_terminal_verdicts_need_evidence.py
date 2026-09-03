"""#12058: a terminal verdict must carry its evidence, not just its label.

`docs/wiki/memory-feedback/README.md` and the repo wiki's verdict rules both
say it — "Promoted entries must cite a real artifact in `promoted_in`. Wontfix
entries must carry `wontfix_reason`" — and only the CONVERSE was in code
(#12069 refused `promoted_in` set on a non-promoted row).

So a row could be stamped terminal with no evidence at all. That is the same
false green as a passing test that asserts nothing, and it is the shape that
let three already-enforced rows sit at `pending` while `MemoryBacklogLoop`
re-filed them every tick until the backlog blew its per-tick filing cap —
which is what #12058 was.
"""

from __future__ import annotations

import pathlib

import pytest

from memory_backlog_mirror import load_mirror_entry

_MIRROR = pathlib.Path("docs/wiki/memory-feedback")


def _write(tmp_path: pathlib.Path, **front: object) -> pathlib.Path:
    fields = {
        "source": "feedback_x.md",
        "name": "X",
        "description": "d",
        "status": "pending",
        "issue": "null",
        "promoted_in": "null",
        "wontfix_reason": "null",
        "created": "'2026-01-01'",
        **front,
    }
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    p = tmp_path / "feedback-x.md"
    p.write_text(f"---\n{body}\n---\n\nrule text\n")
    return p


def test_promoted_without_an_artifact_is_refused(tmp_path) -> None:
    path = _write(tmp_path, status="promoted")

    with pytest.raises(ValueError, match="promoted"):
        load_mirror_entry(path)


def test_wontfix_without_a_reason_is_refused(tmp_path) -> None:
    path = _write(tmp_path, status="wontfix")

    with pytest.raises(ValueError, match="wontfix"):
        load_mirror_entry(path)


def test_a_terminal_row_with_its_evidence_loads(tmp_path) -> None:
    """The decoy: the guards must accept a properly-evidenced verdict.

    Without this, both assertions above pass against a loader that rejects
    every terminal row outright.
    """
    ok_promoted = load_mirror_entry(
        _write(tmp_path, status="promoted", promoted_in="docs/adr/0104-x.md")
    )
    assert ok_promoted.status == "promoted"

    ok_wontfix = load_mirror_entry(
        _write(tmp_path, status="wontfix", wontfix_reason="no code surface")
    )
    assert ok_wontfix.status == "wontfix"


def test_every_row_on_disk_carries_its_evidence() -> None:
    """The live corpus, not a fixture — this is what #12058 was about."""
    missing: list[str] = []
    for f in sorted(_MIRROR.glob("*.md")):
        if f.stem == "README":
            continue
        entry = load_mirror_entry(f)
        if entry.status == "promoted" and not entry.promoted_in:
            missing.append(f"{f.stem}: promoted with no promoted_in")
        if entry.status == "wontfix" and not entry.wontfix_reason:
            missing.append(f"{f.stem}: wontfix with no wontfix_reason")

    assert not missing, "\n".join(missing)


def test_the_backlog_no_longer_re_files_a_settled_rule() -> None:
    """Only genuinely-buildable rules stay `pending`, and re-filing them is right.

    16 rows were pending; 14 were settled (2 already enforced, 12 with no code
    surface) and were re-filed every tick regardless. The two that remain have
    a named blocker rather than no surface at all, so their re-filing is the
    loop working, not thrashing.
    """
    from memory_backlog_mirror import pending_entries

    pending = {e.slug for e in pending_entries(_MIRROR)}

    assert pending == {
        "feedback-ci-no-global-git-config",
        "feedback-cleanup-prs-need-full-suite",
    }, (
        "a row moved into or out of `pending` without a verdict — if it is "
        "genuinely buildable say so here, otherwise it needs promoted_in or "
        "wontfix_reason (#12058)"
    )
