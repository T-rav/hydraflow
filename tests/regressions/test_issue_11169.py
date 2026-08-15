"""Regression guard for #11169 — console-conformance check #6 was whole-history.

``scripts/check_console_conformance.py`` check #6 (ledger immutability) ran
``git log --diff-filter=M -- agents/console/decisions/*/`` with no revision
range and a pathspec ending in a trailing slash (directories only, never a
blob). Two compounding defects: the check never actually fired (dead code),
and once the pathspec is repaired, an unbounded ``git log`` walks *all*
history reachable from HEAD — so any commit anywhere in the past that
modified a decision record makes every subsequent build fail forever, with
no path to green short of a history rewrite (not permitted on protected
branches).

The fix scopes the scan to ``merge_base(HEAD, base)..HEAD`` — only the PR's
own commits — and exempts records the PR itself creates from in-PR
corrections. #11170 (rename/delete blindness on the same two lines) was
folded into this issue by operator ruling: check #6 now also treats
deletion and rename of a merged record as a violation.

These fixtures shell to real ``git`` in temp repos (not mocked) — the
pathspec, rename-detection (``-M``), and merge-base semantics being
exercised are exactly the parts a mock would paper over.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from scripts.check_console_conformance import _PR_BASE_ENV, collect_errors


@pytest.fixture(autouse=True)
def _isolated_pr_base_env():
    """check #6's base resolution reads HYDRAFLOW_AUDIT_PR_BASE from the real
    environment — isolate it so host/CI state can't leak into these fixtures
    and so tests that set it don't leak into tests that don't."""
    saved = os.environ.pop(_PR_BASE_ENV, None)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(_PR_BASE_ENV, None)
        else:
            os.environ[_PR_BASE_ENV] = saved


RECORD = """# ARCH-0001: test

**Date:** 2026-07-31 · **Seats:** operator · **Verdict:** ACCEPT
**Dissent:** none
**Enforcement:** decision-of-record
**Evidence:** none
"""

PERSONA = """---
name: sample
authority: proposal-only
feeds: verdicts
---
body
"""


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_git_env(),
    )


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _scaffold(root: Path) -> None:
    agents = root / "agents"
    for sub in (
        "console/decisions/arch",
        "console/decisions/design",
        "console/decisions/general",
    ):
        (agents / sub).mkdir(parents=True)
    (agents / "sample.md").write_text(PERSONA)
    (agents / "console" / "design.md").write_text(
        "# Design Console\n\n**Chair:** product-manager · seats\n"
    )
    (agents / "console" / "arch.md").write_text(
        "# Architecture Console\n\n**Chair:** senior-principal · seats\n"
    )
    (agents / "console" / "README.md").write_text(
        "| **General** | vp-eng | calibration | here |\n"
    )
    (agents / "console" / "decisions" / "arch" / "0001-test.md").write_text(RECORD)


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _head(repo)


def _init_base_repo(tmp_path: Path) -> Path:
    """A repo on branch 'main' with one committed, conformant record."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _scaffold(repo)
    _commit_all(repo, "feat: initial ledger")
    return repo


def _record(repo: Path, chamber: str, name: str) -> Path:
    return repo / "agents" / "console" / "decisions" / chamber / name


class TestPathspecAndScopingCore:
    def test_amendment_before_merge_base_does_not_latch(self, tmp_path: Path) -> None:
        """The exact bug: a historical amendment must not poison every future
        branch that never touches the ledger."""
        repo = _init_base_repo(tmp_path)
        # Amend the record directly on main (simulating a past, already-merged
        # amendment reachable from any future branch point).
        _record(repo, "arch", "0001-test.md").write_text(
            RECORD.replace("ACCEPT", "AMEND")
        )
        _commit_all(repo, "fix: correct verdict wording")

        # A brand-new branch off the now-amended main, touching nothing in
        # the ledger, must pass — the amendment is entirely before this
        # branch's own merge-base range.
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "README.md").write_text("unrelated change\n")
        _commit_all(repo, "chore: unrelated")

        errors = collect_errors(repo, check_git=True)
        assert not [e for e in errors if "immutability" in e]

    def test_inpr_typo_fix_on_record_created_same_pr_passes(
        self, tmp_path: Path
    ) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        _record(repo, "arch", "0002-test.md").write_text(RECORD)
        _commit_all(repo, "feat: draft record 0002")
        _record(repo, "arch", "0002-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(repo, "fix: typo in 0002 verdict")

        errors = collect_errors(repo, check_git=True)
        assert not [e for e in errors if "immutability" in e]

    def test_merged_record_rewritten_on_branch_is_flagged(self, tmp_path: Path) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        _record(repo, "arch", "0001-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(repo, "fix: quietly flip the verdict")

        errors = collect_errors(repo, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches
        assert "0001-test.md" in matches[0]
        assert "modified" in matches[0]

    def test_new_record_only_branch_passes_clean(self, tmp_path: Path) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        _record(repo, "arch", "0002-test.md").write_text(RECORD)
        _commit_all(repo, "feat: add record 0002")

        errors = collect_errors(repo, check_git=True)
        assert not [e for e in errors if "immutability" in e]

    def test_non_ledger_branch_passes_clean(self, tmp_path: Path) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "README.md").write_text("hello\n")
        _commit_all(repo, "chore: unrelated readme")

        errors = collect_errors(repo, check_git=True)
        assert not [e for e in errors if "immutability" in e]

    def test_multi_violation_across_commits_end_to_end(self, tmp_path: Path) -> None:
        repo = _init_base_repo(tmp_path)
        _record(repo, "arch", "0002-test.md").write_text(RECORD)
        _commit_all(repo, "feat: add record 0002")

        _git(repo, "checkout", "-q", "-b", "feature")
        _record(repo, "arch", "0001-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(repo, "fix: amend 0001")
        _record(repo, "arch", "0002-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(repo, "fix: amend 0002")

        errors = collect_errors(repo, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches
        assert "0001-test.md" in matches[0]
        assert "0002-test.md" in matches[0]


class TestRenameAndDelete:
    """#11170 folded in: D and R on a merged record are violations too."""

    def test_merged_record_deleted_is_flagged(self, tmp_path: Path) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        _record(repo, "arch", "0001-test.md").unlink()
        _commit_all(repo, "chore: remove record")

        errors = collect_errors(repo, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches
        assert "0001-test.md" in matches[0]
        assert "deleted" in matches[0]

    def test_merged_record_renamed_within_chamber_is_flagged(
        self, tmp_path: Path
    ) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        old = _record(repo, "arch", "0001-test.md")
        new = _record(repo, "arch", "0001-renamed.md")
        _git(repo, "mv", str(old.relative_to(repo)), str(new.relative_to(repo)))
        _commit_all(repo, "chore: rename record")

        errors = collect_errors(repo, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches
        assert "renamed" in matches[0]
        assert "0001-test.md" in matches[0]
        assert "0001-renamed.md" in matches[0]

    def test_merged_record_moved_out_of_ledger_is_flagged(self, tmp_path: Path) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        old = _record(repo, "arch", "0001-test.md")
        new = repo / "0001-test.md"
        _git(repo, "mv", str(old.relative_to(repo)), str(new.relative_to(repo)))
        _commit_all(repo, "chore: move record out of ledger")

        errors = collect_errors(repo, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches, "moving a merged record out of the ledger must still be caught"

    def test_rename_plus_content_change_is_flagged_as_rename(
        self, tmp_path: Path
    ) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        old = _record(repo, "arch", "0001-test.md")
        new = _record(repo, "arch", "0001-moved.md")
        _git(repo, "mv", str(old.relative_to(repo)), str(new.relative_to(repo)))
        new.write_text(RECORD.replace("ACCEPT", "REJECT"))
        _commit_all(repo, "chore: rename and edit in one commit")

        errors = collect_errors(repo, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches
        assert "renamed" in matches[0]

    def test_new_record_deleted_within_same_pr_is_not_flagged(
        self, tmp_path: Path
    ) -> None:
        # A record drafted and then discarded within the same PR never
        # existed at the merge-base — nothing to violate.
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        rec = _record(repo, "arch", "0002-draft.md")
        rec.write_text(RECORD)
        _commit_all(repo, "feat: draft record 0002")
        rec.unlink()
        _commit_all(repo, "chore: discard draft 0002")

        errors = collect_errors(repo, check_git=True)
        assert not [e for e in errors if "immutability" in e]


class TestBaseResolution:
    def test_falls_back_to_local_main_when_no_origin_remote(
        self, tmp_path: Path
    ) -> None:
        repo = _init_base_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        _record(repo, "arch", "0001-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(repo, "fix: amend 0001")

        errors = collect_errors(repo, check_git=True)
        assert [e for e in errors if "immutability" in e], (
            "with no origin remote, the local 'main' branch candidate must "
            "still resolve a merge-base"
        )

    def test_all_candidates_unresolvable_skips_without_crashing(
        self, tmp_path: Path, capsys
    ) -> None:
        repo = tmp_path / "lonely"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "orphan")
        _scaffold(repo)
        _commit_all(repo, "feat: initial ledger")
        _record(repo, "arch", "0001-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(repo, "fix: amend 0001 (no base branch exists at all)")

        errors = collect_errors(repo, check_git=True)
        assert not [e for e in errors if "immutability" in e], (
            "an unresolvable base must degrade to skipping check #6, never "
            "to a false pass claim masking a crash, and never to a whole-"
            "history walk"
        )
        assert "skipped" in capsys.readouterr().err

    def test_env_var_takes_precedence_over_fallback_chain(self, tmp_path: Path) -> None:
        # Real remote-tracking refs: clone from an upstream repo so
        # origin/main and origin/staging both exist as genuine
        # refs/remotes/origin/* refs (#11169 review: "no test exercises the
        # origin/<base> remote-tracking candidate").
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        _git(upstream, "init", "-q", "-b", "main")
        _scaffold(upstream)
        _commit_all(upstream, "feat: initial ledger")
        _git(upstream, "checkout", "-q", "-b", "staging")
        # staging is ahead of main by a commit that itself amends the record
        # — if resolution ever fell back to the wrong candidate, this
        # amendment would incorrectly land inside the "PR range" and either
        # falsely flag (if treated as introduced by the PR) or the base
        # picked would be wrong. We assert the env-specified base wins.
        _record(upstream, "arch", "0001-test.md").write_text(
            RECORD.replace("ACCEPT", "AMEND-ON-STAGING")
        )
        _commit_all(upstream, "fix: staging-only amendment")
        _git(upstream, "checkout", "-q", "main")

        clone = tmp_path / "clone"
        _git(tmp_path, "clone", "-q", str(upstream), str(clone))
        _git(clone, "checkout", "-q", "-b", "feature", "origin/staging")
        (clone / "README.md").write_text("unrelated\n")
        _commit_all(clone, "chore: unrelated change on top of staging")

        os.environ[_PR_BASE_ENV] = "staging"
        errors = collect_errors(clone, check_git=True)

        # The PR branch itself never touches the ledger after branching from
        # origin/staging (which already contains the amendment) — scoping to
        # origin/staging's merge-base means the staging-only amendment is
        # NOT in this PR's own range, so it must not be flagged.
        assert not [e for e in errors if "immutability" in e]

    def test_precedence_prefers_origin_staging_over_origin_main(
        self, tmp_path: Path
    ) -> None:
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        _git(upstream, "init", "-q", "-b", "main")
        _scaffold(upstream)
        _commit_all(upstream, "feat: initial ledger")
        _git(upstream, "checkout", "-q", "-b", "staging")
        _record(upstream, "arch", "0002-test.md").write_text(RECORD)
        _commit_all(upstream, "feat: staging-only record 0002")
        _git(upstream, "checkout", "-q", "main")

        clone = tmp_path / "clone"
        _git(tmp_path, "clone", "-q", str(upstream), str(clone))
        # PR branch forks from origin/staging (the real base) but no env var
        # is set — the fallback chain must prefer origin/staging over
        # origin/main so the merge-base is staging's tip, not main's.
        _git(clone, "checkout", "-q", "-b", "feature", "origin/staging")
        _record(clone, "arch", "0002-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(clone, "fix: amend the record staging just added")

        os.environ.pop(_PR_BASE_ENV, None)
        errors = collect_errors(clone, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches, (
            "if origin/main (which predates record 0002) were picked instead "
            "of origin/staging, 0002 would look PR-created and this "
            "amendment would be wrongly exempted"
        )
        assert "0002-test.md" in matches[0]


class TestMergeCommitInclusion:
    def test_modification_landing_via_merged_side_branch_is_flagged(
        self, tmp_path: Path
    ) -> None:
        repo = _init_base_repo(tmp_path)
        base_sha = _head(repo)

        _git(repo, "checkout", "-q", "-b", "side")
        _record(repo, "arch", "0001-test.md").write_text(
            RECORD.replace("ACCEPT", "REJECT")
        )
        _commit_all(repo, "fix: amend 0001 on a side branch")

        _git(repo, "checkout", "-q", "-b", "feature", base_sha)
        (repo / "README.md").write_text("unrelated dev-branch work\n")
        _commit_all(repo, "chore: unrelated work on feature")
        _git(repo, "merge", "-q", "--no-edit", "side")

        errors = collect_errors(repo, check_git=True)
        matches = [e for e in errors if "immutability" in e]
        assert matches, (
            "a modification delivered via a merge commit inside the PR's "
            "own range must not be silently excluded"
        )
        assert "0001-test.md" in matches[0]


class TestLiveTreeUnaffected:
    def test_repo_ledger_still_passes_check_git_false(self) -> None:
        from scripts.check_console_conformance import collect_errors as _collect

        repo_root = Path(__file__).resolve().parent.parent.parent
        assert _collect(repo_root, check_git=False) == []
