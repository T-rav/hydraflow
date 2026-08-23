"""`.meta.json` must not vary with the branch's commit graph.

`docs/arch/.meta.json` used to digest EVERY generated artifact, including the
two `_DRIFT_EXEMPT` ones (`changelog.md`, `traceability_matrix.md`) that derive
from a moving `git log` window rather than from source. Two branches with
byte-identical architecture therefore produced different `.meta.json` bytes, so
it conflicted on essentially every rebase and staging advance -- and the
`merge=arch-meta` driver named in `.gitattributes` only exists where
`make ensure-hooks` has run, never in a fresh clone, a CI checkout, or GitHub's
server-side merge.
"""

from __future__ import annotations

import json

from arch import runner
from arch._models import CommitInfo
from arch.generators.changelog import render_changelog


def _meta_for(tmp_path, monkeypatch, changelog_body: str) -> dict:
    """Emit into a tmpdir with `changelog.md` forced to `changelog_body`."""
    real = runner._compute_artifacts

    def fake(repo_root):
        arts = dict(real(repo_root))
        arts["changelog.md"] = changelog_body
        return arts

    monkeypatch.setattr(runner, "_compute_artifacts", fake)
    out = tmp_path / "generated"
    runner.emit(repo_root=runner.Path(__file__).resolve().parents[2], out_dir=out)
    return json.loads((out.parent / ".meta.json").read_text())


def test_meta_digest_ignores_a_changed_changelog(tmp_path, monkeypatch):
    """The whole point: a different git-log window must not move the digest."""
    a = _meta_for(tmp_path / "a", monkeypatch, "# changelog\n\n- `aaaaaaa` one\n")
    b = _meta_for(tmp_path / "b", monkeypatch, "# changelog\n\n- `bbbbbbb` two\n")
    assert a["content_sha"] == b["content_sha"]
    assert a == b


def test_drift_exempt_artifacts_are_absent_from_the_digest():
    """They are still emitted -- they are just not hashed."""
    assert runner._DRIFT_EXEMPT, "guard is meaningless if the set is empty"
    meta = json.loads(
        (runner.Path(__file__).resolve().parents[2] / "docs/arch/.meta.json").read_text()
    )
    for name in runner._DRIFT_EXEMPT:
        assert name not in meta["artifacts"], (
            f"{name} derives from git history, so hashing it makes .meta.json "
            "branch-dependent and it conflicts on every rebase"
        )


def test_deterministic_artifacts_are_still_digested():
    """Excluding the exempt pair must not hollow the digest out entirely."""
    meta = json.loads(
        (runner.Path(__file__).resolve().parents[2] / "docs/arch/.meta.json").read_text()
    )
    digested = set(meta["artifacts"])
    expected = {n for n in runner._ARTIFACT_FILES if n not in runner._DRIFT_EXEMPT}
    assert digested == expected
    assert "loops.md" in digested and "ports.md" in digested


def test_changelog_does_not_double_a_pr_ref_the_subject_already_carries():
    """412 entries in the published artifact read `(#11656) (#11656)`."""
    out = render_changelog(
        [
            CommitInfo(
                sha="abc1234def",
                subject="fix(gateway): P4 — multi-account pools (#11656)",
                iso_date="2026-08-22",
                pr_number=11656,
            )
        ]
    )
    assert "(#11656) (#11656)" not in out
    assert "(#11656)" in out


def test_changelog_still_appends_a_ref_the_subject_lacks():
    """Negative control -- the de-dup must not suppress a genuinely new ref."""
    out = render_changelog(
        [
            CommitInfo(
                sha="abc1234def",
                subject="fix(gateway): P4 — multi-account pools",
                iso_date="2026-08-22",
                pr_number=11656,
            )
        ]
    )
    assert "(#11656)" in out
