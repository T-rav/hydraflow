"""Regression guard for #10499 — `_added_paths_for_range` always returns `{}`.

Escape ledger row `bug-issue:055267e7b2b7900d615b0ff8553ef511dc3e8652` was
filed with low-confidence ``fixes-chain`` attribution because the
``regression-pin`` detection source (``escape.detect.detect_escapes``) is
permanently unreachable: ``_added_paths_for_range`` marks each commit's
``--name-only`` block with a sentinel line ``_SHA_MARKER + sha``, then scans
for it with ``str.splitlines()``. ``\\x1e`` (Record Separator) — the
sentinel's boundary character — is itself one of the characters
``str.splitlines()`` treats as a line break, so the marker line is shredded
into three pieces (``''``, ``'ESCSHA'``, the sha) before the scan ever sees
it. No line ever starts with the intact marker, so the per-commit added-paths
map is always empty and a commit that adds a ``tests/regressions/`` file is
never classified as a ``regression-pin`` escape — it falls through to the
low-confidence ``bug-issue`` fallback instead.

Fix: a marker built from a non-line-boundary control character
(``\\x01``, SOH), and explicit ``str.split("\\n")`` instead of
``str.splitlines()`` — `git log` output uses bare ``\\n`` line endings, and
``splitlines()``'s wider boundary set is exactly what caused this bug, so it
is the wrong tool for parsing marker-delimited git output in general.

``audit.detect._changed_paths_for_range`` (#10370) is the same defect class:
it built its marker from ``\\x1eAUDITSHA\\x1e`` and scanned with
``str.splitlines()`` too, so ``MergedChange.changed_paths`` was always ``()``
in production — silently disabling ``audit.stratify.classify_blast_radius``'s
path-based elevation (gauntlet / migration / security / structural all
require a non-empty ``changed_paths`` match) for every sampled-audit merge.
``audit.detect`` and ``escape.detect`` are known scatter siblings (see
``tests/regressions/test_issue_10402.py``), so this was fixed alongside the
``escape.detect`` fix rather than left for a follow-up.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from audit.detect import _changed_paths_for_range, merged_changes_for_range
from escape.detect import _added_paths_for_range, commits_for_range, detect_escapes


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=_git_env())


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _add_file(repo: Path, rel: str, content: str, message: str) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _head(repo)


class TestAddedPathsForRange:
    def test_maps_single_commit_to_its_added_file(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        sha = _add_file(
            repo,
            "tests/regressions/test_a.py",
            "def test_a(): pass\n",
            "fix: pin regression a",
        )

        added = _added_paths_for_range(repo, f"{base_sha}..{sha}")

        assert added == {sha: ["tests/regressions/test_a.py"]}

    def test_attributes_paths_per_commit_across_many_commits(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        sha1 = _add_file(
            repo, "tests/regressions/test_a.py", "x = 1\n", "fix: pin a"
        )
        sha2 = _add_file(repo, "src/mod.py", "def f(): return 1\n", "feat: mod")
        sha3 = _add_file(
            repo, "tests/regressions/test_b.py", "x = 2\n", "fix: pin b"
        )

        added = _added_paths_for_range(repo, f"{base_sha}..{sha3}")

        assert added == {
            sha1: ["tests/regressions/test_a.py"],
            sha2: ["src/mod.py"],
            sha3: ["tests/regressions/test_b.py"],
        }

    def test_empty_for_commit_that_adds_no_files(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        seed = _add_file(repo, "src/mod.py", "x = 1\n", "feat: seed")
        (repo / "src" / "mod.py").write_text("x = 2\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fix: tweak, no new files")
        modify_sha = _head(repo)

        added = _added_paths_for_range(repo, f"{seed}..{modify_sha}")

        # `git log --diff-filter=A` omits the marker line entirely for a
        # commit with no matching diff entries, so the commit never becomes
        # a key at all — assert the full empty mapping, not just a `.get()`
        # fallback that would pass even if `modify_sha` mapped to garbage.
        assert added == {}
        assert modify_sha not in added

    def test_maps_non_ascii_added_path_unescaped(self, tmp_path: Path) -> None:
        # core.quotepath defaults to true, which octal-escapes non-ASCII path
        # bytes and wraps the whole path in literal quotes (e.g.
        # `"tests/regressions/test_\303\251.py"`), defeating a startswith()
        # match against the raw path. `_added_paths_for_range` must disable
        # it so this round-trips as real UTF-8, not a quoted escape (#10499).
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        sha = _add_file(
            repo,
            "tests/regressions/test_café.py",
            "def test_cafe(): pass\n",
            "fix: pin regression with non-ascii filename",
        )

        added = _added_paths_for_range(repo, f"{base_sha}..{sha}")

        assert added == {sha: ["tests/regressions/test_café.py"]}


class TestRegressionPinDetectionEndToEnd:
    def test_commits_for_range_detects_regression_pin(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        _add_file(repo, "src/mod.py", "def risky(): return 1\n", "feat: risky change")
        bad_sha = _head(repo)
        head_sha = _add_file(
            repo,
            "tests/regressions/test_mod.py",
            "def test_mod(): pass\n",
            f"fix: pin regression from {bad_sha}",
        )

        commits = commits_for_range(repo, f"{base_sha}..{head_sha}")
        assert commits is not None
        candidates = detect_escapes(commits)

        pin_candidates = [c for c in candidates if c.detection_source == "regression-pin"]
        assert len(pin_candidates) == 1
        assert pin_candidates[0].detection_ref == head_sha
        # medium confidence, not low -- this must NOT reach the low-confidence
        # HITL surface (escape.metrics.low_confidence), which is the whole
        # point of restoring the regression-pin detection source (#10499).
        assert pin_candidates[0].attribution_confidence == "medium"

    def test_detects_regression_pin_at_a_non_ascii_path(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        _add_file(repo, "src/mod.py", "def risky(): return 1\n", "feat: risky change")
        bad_sha = _head(repo)
        head_sha = _add_file(
            repo,
            "tests/regressions/test_café.py",
            "def test_cafe(): pass\n",
            f"fix: pin regression from {bad_sha}",
        )

        commits = commits_for_range(repo, f"{base_sha}..{head_sha}")
        assert commits is not None
        candidates = detect_escapes(commits)

        pin_candidates = [c for c in candidates if c.detection_source == "regression-pin"]
        assert len(pin_candidates) == 1
        assert pin_candidates[0].detection_ref == head_sha


class TestAuditDetectSameDefectClass:
    """``audit.detect`` shared the ``\\x1eMARKER\\x1e`` + ``splitlines()`` bug —
    fixed alongside ``escape.detect`` since both are scatter siblings."""

    def test_changed_paths_for_range_maps_single_commit(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        sha = _add_file(repo, "src/mod.py", "def f(): return 1\n", "feat: add mod (#7)")

        changed = _changed_paths_for_range(repo, f"{base_sha}..{sha}")

        assert changed == {sha: ["src/mod.py"]}

    def test_maps_non_ascii_changed_path_unescaped(self, tmp_path: Path) -> None:
        # Same core.quotepath defect class as escape.detect (#10499): without
        # disabling it, a non-ASCII path comes back quoted/octal-escaped.
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        sha = _add_file(
            repo, "src/café.py", "def f(): return 1\n", "feat: add café (#7)"
        )

        changed = _changed_paths_for_range(repo, f"{base_sha}..{sha}")

        assert changed == {sha: ["src/café.py"]}

    def test_merged_changes_for_range_populates_changed_paths(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        sha = _add_file(
            repo, "src/gauntlet.py", "def g(): return 1\n", "feat: touch gauntlet (#9)"
        )

        changes = merged_changes_for_range(repo, f"{base_sha}..{sha}")

        assert changes is not None
        assert len(changes) == 1
        assert changes[0].changed_paths == ("src/gauntlet.py",)
