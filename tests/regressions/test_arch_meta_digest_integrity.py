"""``docs/arch/.meta.json`` must agree with the artifacts it claims to digest.

Regression guard for a corruption that lands green. ``.meta.json`` is a content
digest over ``docs/arch/generated/*``, and a three-way *text* merge of a digest
file is meaningless by construction: git resolves the one differing ``content_sha``
line toward whichever side it prefers, while the artifact itself stays as this
branch wrote it. Both staging merges on #11749 did exactly that, cleanly and with
no conflict, recording ``origin/staging``'s ``modules.md`` digest over this
branch's ``modules.md`` — the file carrying the new ``src.policy`` node, i.e. the
very change the record is supposed to attest to.

Nothing went red either time. ``make arch-check`` re-derives the artifacts and
compares *those*; it never reads ``.meta.json``, so a false provenance record
passes every gate and merges silently. The failure is deterministic, not a
one-off: any branch that changes a digested artifact and merges staging
re-acquires a wrong digest on every merge.

The invariant is re-derived from ``arch.runner``'s own helpers rather than
re-implemented here. A guard that reimplements the hashing it checks is checking
its own copy, so ``_sha256``, ``_META_NAME`` and ``_DRIFT_EXEMPT`` are imported
from the module that writes the file; if the digest contract changes, this test
follows it instead of silently disagreeing.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from arch.runner import _DRIFT_EXEMPT, _META_NAME, _sha256

REPO = Path(__file__).resolve().parents[2]
ARCH_DIR = REPO / "docs" / "arch"
GENERATED_DIR = ARCH_DIR / "generated"
META_PATH = ARCH_DIR / _META_NAME


def _meta(path: Path = META_PATH) -> dict:
    """Load ``.meta.json``, failing LOUDLY on every degenerate input.

    A guard that skips when its input goes missing is the exact class this
    file exists to catch, so absent / empty / unparseable / artifact-less are
    all hard failures with a diagnostic, never a silent pass and never a bare
    traceback. The ``artifacts`` check matters most: an empty map would make
    the per-artifact comparison below iterate nothing and go green over a file
    that attests to nothing at all.
    """
    assert path.is_file(), (
        f"{path} is missing. The digest guard has no input, which is a failure "
        "and not a reason to skip — run `make arch-regen`."
    )
    raw = path.read_text(encoding="utf-8").strip()
    assert raw, f"{path} is empty. Run `make arch-regen`."
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"{path} is not valid JSON ({exc}). Run `make arch-regen`."
        raise AssertionError(msg) from exc
    assert isinstance(data, dict), (
        f"{path} is not a JSON object. Run `make arch-regen`."
    )
    assert data.get("artifacts"), (
        f"{path} records no artifacts. An empty map would make the per-artifact "
        "check iterate nothing and pass over a file attesting to nothing."
    )
    assert data.get("content_sha"), f"{path} records no rollup content_sha."
    return data


def test_every_recorded_artifact_digest_matches_the_file_on_disk() -> None:
    """The per-artifact half: this is what the merge corrupted."""
    recorded = _meta()["artifacts"]

    mismatched = {
        name: {"recorded": entry["content_sha"], "actual": actual}
        for name, entry in sorted(recorded.items())
        if (actual := _sha256((GENERATED_DIR / name).read_text(encoding="utf-8")))
        != entry["content_sha"]
    }

    assert not mismatched, (
        "docs/arch/.meta.json records a content_sha that does not match the "
        f"artifact on disk: {json.dumps(mismatched, indent=2)}\n\n"
        "This is almost always a merge that text-merged the digest file. Do NOT "
        "hand-edit the sha — run `make arch-regen` and commit the result. "
        "`make arch-check` cannot catch this: it re-derives the artifacts and "
        "never reads .meta.json."
    )


def test_the_rollup_digest_matches_the_per_artifact_digests() -> None:
    """The rollup half, computed the way ``arch.runner.emit`` computes it."""
    meta = _meta()
    per_artifact = {n: e["content_sha"] for n, e in meta["artifacts"].items()}

    expected = _sha256("".join(per_artifact[n] for n in sorted(per_artifact)))

    assert meta["content_sha"] == expected, (
        f"top-level content_sha {meta['content_sha']} does not equal the digest "
        f"of its own artifact digests ({expected}). Run `make arch-regen`."
    )


def _tracked_generated_artifacts() -> set[str]:
    """Git-TRACKED ``.md`` artifacts, minus the drift-exempt ones.

    Tracked, not globbed: ``loop-fitness.md`` is written into the same
    directory at runtime and is gitignored, so a glob would demand a digest for
    a file that ``emit`` never hashes. ``_DRIFT_EXEMPT`` is imported rather than
    restated — those two derive from a moving ``git log`` window and are
    excluded on purpose, to keep ``.meta.json`` branch-stable.
    """
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "docs/arch/generated/*.md"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    names = {Path(line).name for line in out.stdout.split() if line.strip()}
    return names - _DRIFT_EXEMPT


def test_recorded_artifacts_are_exactly_the_digested_set() -> None:
    """Anti-vacuity, both directions.

    An empty or shrunken ``artifacts`` map would make the comparison above pass
    over nothing, which is how a digest guard stops seeing its subject. Pinned
    against a derivation rather than a count, so adding an artifact without a
    digest reddens and dropping one from the map reddens too.
    """
    recorded = set(_meta()["artifacts"])
    expected = _tracked_generated_artifacts()

    assert recorded == expected, (
        f"missing from .meta.json: {sorted(expected - recorded)}; "
        f"recorded but not a tracked generated artifact: "
        f"{sorted(recorded - expected)}. Run `make arch-regen`."
    )
    assert recorded, "no artifacts recorded — the guard would pass over nothing"


# ---------------------------------------------------------------------------
# The gate's own failure mode
# ---------------------------------------------------------------------------


def test_a_missing_meta_file_fails_rather_than_skipping(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="is missing"):
        _meta(tmp_path / "absent.json")


def test_an_empty_meta_file_fails_rather_than_skipping(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("")

    with pytest.raises(AssertionError, match="is empty"):
        _meta(path)


def test_an_unparseable_meta_file_fails_rather_than_skipping(tmp_path: Path) -> None:
    path = tmp_path / "torn.json"
    path.write_text('{"artifacts": {')

    with pytest.raises(AssertionError, match="not valid JSON"):
        _meta(path)


def test_a_meta_file_recording_no_artifacts_fails(tmp_path: Path) -> None:
    """The vacuity case: an empty map would let the per-artifact check pass."""
    path = tmp_path / "hollow.json"
    path.write_text(json.dumps({"content_sha": "x" * 64, "artifacts": {}}))

    with pytest.raises(AssertionError, match="records no artifacts"):
        _meta(path)
