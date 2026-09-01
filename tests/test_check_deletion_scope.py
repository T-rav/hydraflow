"""Unit tests for the deletion-scope gate (#11902).

The incident: `git reset --soft` onto a NEWER ref, then `git add -A`, recorded
16 files two already-merged PRs had ADDED as deletions. Every gate passed —
ruff, arch-check, the pre-commit hooks, `make audit` at PASS 94 / FAIL 0 —
because every one of them asks "is what is here correct?", and a deleted file
is not around to be incorrect.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_deletion_scope import declared_paths, out_of_scope


class TestInScope:
    def test_a_sibling_in_the_same_directory_is_scope(self) -> None:
        assert out_of_scope(["src/policy/old.py"], ["src/policy/new.py"]) == []

    def test_a_module_retired_into_its_own_package_is_scope(self) -> None:
        """The batch 5-8 decomposition shape, run every few weeks here."""
        assert (
            out_of_scope(
                ["src/wiki_compiler.py"],
                ["src/wiki_compiler/__init__.py", "src/wiki_compiler/_flow.py"],
            )
            == []
        )

    def test_a_deletion_in_an_untouched_subtree_is_not_scope(self) -> None:
        """The measured incident: a PR working in scripts/ and src/policy/
        deleted src/retro_*.py, a subtree it never otherwise mentions."""
        assert out_of_scope(
            ["src/retro_evidence.py", "src/retro_findings.py"],
            ["scripts/hydraflow_audit/rules.py", "src/policy/facts.py"],
        ) == ["src/retro_evidence.py", "src/retro_findings.py"]

    def test_a_near_miss_package_name_is_not_scope(self) -> None:
        """`src/foo.py` is not excused by `src/foobar/` — prefix, not subtree."""
        assert out_of_scope(["src/foo.py"], ["src/foobar/thing.py"]) == ["src/foo.py"]

    def test_a_root_level_deletion_needs_a_root_level_sibling(self) -> None:
        assert out_of_scope(["CHANGELOG.md"], ["src/a.py"]) == ["CHANGELOG.md"]
        assert out_of_scope(["CHANGELOG.md"], ["README.md"]) == []


class TestDeclaration:
    def test_a_trailer_names_one_path(self) -> None:
        assert declared_paths("Removes: src/retro_evidence.py") == [
            "src/retro_evidence.py"
        ]

    def test_a_trailer_takes_several_separators(self) -> None:
        body = "feat: x\n\nRemoves: a.py, b.py\nRemoves: c.py\n"
        assert declared_paths(body) == ["a.py", "b.py", "c.py"]

    def test_no_trailer_declares_nothing(self) -> None:
        assert declared_paths("chore: delete some files\n\nThey were stale.") == []

    def test_prose_mentioning_removal_is_not_a_declaration(self) -> None:
        """Naming is the mechanism: the incident deleted 16 files its author
        never intended to touch, and nobody types sixteen unintended paths."""
        assert declared_paths("This PR removes the retro pipeline entirely.") == []


class TestTheGateWouldHaveCaughtTheIncident:
    #: 16 files from two already-merged PRs, against a branch working elsewhere.
    _DELETED = [
        "src/retro_evidence.py",
        "src/retro_findings.py",
        "src/retro_signals.py",
        "tests/test_retro_evidence.py",
    ]
    _TOUCHED = ["scripts/hydraflow_audit/rules.py", "src/policy/facts.py"]

    def test_undeclared_deletions_are_all_reported(self) -> None:
        assert out_of_scope(self._DELETED, self._TOUCHED) == self._DELETED

    def test_declaring_one_path_does_not_excuse_the_others(self) -> None:
        """A single hand-wave must not clear sixteen accidental deletions."""
        offenders = out_of_scope(self._DELETED, self._TOUCHED)
        declared = declared_paths("Removes: src/retro_evidence.py")
        undeclared = [p for p in offenders if p not in declared]
        assert undeclared == self._DELETED[1:]

    def test_declaring_every_path_clears_it(self) -> None:
        offenders = out_of_scope(self._DELETED, self._TOUCHED)
        declared = declared_paths("Removes: " + ", ".join(self._DELETED))
        assert [p for p in offenders if p not in declared] == []


def test_no_deletions_is_never_an_offence() -> None:
    assert out_of_scope([], ["src/a.py"]) == []


class TestItFailsClosed:
    """The first version of this gate shipped broken in exactly one way.

    ``_git`` ran with ``check=False`` and returned stdout. On the shallow CI
    checkout ``git diff origin/staging...HEAD`` exited non-zero, stdout was
    empty, and an empty deletion list reads exactly like "deletes nothing" — so
    it printed ``[deletion-scope OK] no files deleted`` on a branch that deleted
    a file, and went green. A gate for silent deletions that fails silently is
    worse than none: it occupies the slot a working one would have.
    """

    def test_a_missing_base_is_an_error_not_an_empty_diff(self, tmp_path) -> None:
        import subprocess

        import check_deletion_scope as gate

        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        rc = gate.main(["--base", "origin/definitely-not-a-branch", "--head", "HEAD"])
        assert rc == 1, (
            "an unresolvable base must FAIL; returning 0 is the shipped bug — "
            "no comparison was made, and 'nothing found' was reported as 'nothing there'"
        )

    def test_git_failure_raises_rather_than_returning_empty(self) -> None:
        import check_deletion_scope as gate
        import pytest as _pytest

        with _pytest.raises(gate.BaseUnresolvable):
            gate._git("rev-parse", "--verify", "definitely-not-a-ref^{commit}")
