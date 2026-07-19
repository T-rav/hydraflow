"""prompt_refiner context assembly, holdout invariant, patch parsing."""

from pathlib import Path

import pytest

from prompt_refiner import (
    PatchParseError,
    assemble_refine_context,
    parse_patch_response,
)
from tests.trust.adversarial.corpus_runner import CASES_DIR, discover_cases, is_holdout


def test_context_contains_builder_source_and_case_material(tmp_path: Path) -> None:
    case = tmp_path / "some-case"
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir()
    (case / "README.md").write_text("# some-case\nKeyword: kw-1\n")
    (case / "expected_transcript.txt").write_text("EXPECTED-MARKER\n")
    ctx = assemble_refine_context(
        Path.cwd(), case, "diff-sanity", failure_transcript="FAILED-MARKER"
    )
    assert "build_diff_sanity_prompt" in ctx  # builder source embedded
    assert "kw-1" in ctx and "EXPECTED-MARKER" in ctx and "FAILED-MARKER" in ctx


def test_context_refuses_holdout_case(tmp_path: Path) -> None:
    case = tmp_path / "trap"
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir()
    (case / "HOLDOUT").write_text("")
    with pytest.raises(ValueError, match="holdout"):
        assemble_refine_context(Path.cwd(), case, "diff-sanity", failure_transcript="")


def test_no_holdout_content_reachable_via_context() -> None:
    """The structural invariant: for every real non-holdout case, the assembled
    context never contains any holdout case's id or README keyword."""
    holdouts = [c for c in discover_cases(CASES_DIR) if is_holdout(c)]
    assert holdouts, "seed holdout cases missing"
    normal = list(discover_cases(CASES_DIR, include_holdout=False))[:3]
    for case in normal:
        ctx = assemble_refine_context(
            Path.cwd(), case, "diff-sanity", failure_transcript="x"
        )
        for trap in holdouts:
            assert trap.name not in ctx


def test_parse_patch_response_extracts_diff_fence() -> None:
    text = "reasoning...\n```diff\n--- a/src/diff_sanity.py\n+++ b/src/diff_sanity.py\n@@ -1 +1 @@\n-a\n+b\n```\ndone"
    assert parse_patch_response(text).startswith("--- a/src/diff_sanity.py")


def test_parse_patch_response_rejects_missing_fence() -> None:
    with pytest.raises(PatchParseError):
        parse_patch_response("no diff here")


def test_tripwire_rejects_foreign_file() -> None:
    from prompt_refiner import check_tripwires

    patch = "--- a/src/pr_manager.py\n+++ b/src/pr_manager.py\n@@ -1 +1 @@\n-a\n+b\n"
    reasons = check_tripwires(patch, "diff-sanity", Path.cwd())
    assert any("only" in r and "diff_sanity" in r for r in reasons)


def test_tripwire_rejects_corpus_edit() -> None:
    from prompt_refiner import check_tripwires

    patch = (
        "--- a/tests/trust/adversarial/cases/x/README.md\n"
        "+++ b/tests/trust/adversarial/cases/x/README.md\n@@ -1 +1 @@\n-a\n+b\n"
    )
    reasons = check_tripwires(patch, "diff-sanity", Path.cwd())
    assert any("tests/trust" in r for r in reasons)


def test_tripwire_accepts_builder_only_patch() -> None:
    from prompt_refiner import SKILL_BUILDER_MODULES, check_tripwires

    mod = SKILL_BUILDER_MODULES["diff-sanity"]
    patch = f"--- a/{mod}\n+++ b/{mod}\n@@ -1 +1 @@\n-a\n+b\n"
    assert check_tripwires(patch, "diff-sanity", Path.cwd()) == []


def test_tripwire_rejects_bundled_deletion_of_corpus_file() -> None:
    """A legit builder hunk bundled with a `+++ /dev/null` deletion section
    must still be caught — the deleted path is invisible to a +++-b/-only
    scanner, but the corpus-edit ban must still fire (#9724)."""
    from prompt_refiner import check_tripwires

    patch = (
        "--- a/src/diff_sanity.py\n+++ b/src/diff_sanity.py\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/tests/trust/adversarial/cases/x/README.md "
        "b/tests/trust/adversarial/cases/x/README.md\n"
        "deleted file mode 100644\nindex abc123..0000000\n"
        "--- a/tests/trust/adversarial/cases/x/README.md\n+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-content\n"
    )
    reasons = check_tripwires(patch, "diff-sanity", Path.cwd())
    assert any("tests/trust" in r for r in reasons)


def test_tripwire_rejects_pure_rename_of_corpus_file() -> None:
    """A pure rename section carries no ---/+++ lines at all — only
    `rename from`/`rename to` — and must still be caught (#9724)."""
    from prompt_refiner import SKILL_BUILDER_MODULES, check_tripwires

    mod = SKILL_BUILDER_MODULES["diff-sanity"]
    patch = (
        f"--- a/{mod}\n+++ b/{mod}\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/tests/trust/adversarial/cases/x/README.md "
        "b/tests/trust/adversarial/cases/decoy/README.md\n"
        "similarity index 100%\n"
        "rename from tests/trust/adversarial/cases/x/README.md\n"
        "rename to tests/trust/adversarial/cases/decoy/README.md\n"
    )
    reasons = check_tripwires(patch, "diff-sanity", Path.cwd())
    assert any("tests/trust" in r for r in reasons)


def test_tripwire_rejects_bundled_foreign_file_creation() -> None:
    """A `+++ b/<path>` creation section IS caught by the old regex — this
    pins that a bundled new-file section against a foreign path still trips
    the only-touch-the-allowed-module rule (#9724)."""
    from prompt_refiner import SKILL_BUILDER_MODULES, check_tripwires

    mod = SKILL_BUILDER_MODULES["diff-sanity"]
    patch = (
        f"--- a/{mod}\n+++ b/{mod}\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/src/evil.py b/src/evil.py\n"
        "new file mode 100644\nindex 0000000..abc123\n"
        "--- /dev/null\n+++ b/src/evil.py\n@@ -0,0 +1 @@\n+evil\n"
    )
    reasons = check_tripwires(patch, "diff-sanity", Path.cwd())
    assert any("only" in r and mod in r for r in reasons)


def test_tripwire_rejects_bundled_empty_file_creation_no_hunk() -> None:
    """A brand-new EMPTY file carries no ---/+++ lines at all — git omits the
    hunk entirely for a zero-byte file, leaving only the `diff --git` header.
    This is the truly-invisible creation shape (unlike a `+++ b/`-bearing
    creation, which the old regex already caught) (#9724)."""
    from prompt_refiner import SKILL_BUILDER_MODULES, check_tripwires

    mod = SKILL_BUILDER_MODULES["diff-sanity"]
    patch = (
        f"--- a/{mod}\n+++ b/{mod}\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/tests/trust/empty_new_file.txt b/tests/trust/empty_new_file.txt\n"
        "new file mode 100644\nindex 0000000..e69de29\n"
    )
    reasons = check_tripwires(patch, "diff-sanity", Path.cwd())
    assert any("tests/trust" in r for r in reasons)
