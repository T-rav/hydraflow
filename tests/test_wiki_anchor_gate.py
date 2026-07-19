"""Tests for the repo-specificity anchor gate (#9954).

The wiki issue-synthesis pipeline was minting generic coding truisms as
durable repo-knowledge entries. ``has_repo_anchor`` is the deterministic
heuristic that decides whether an entry earns its place: it must reference
something specific to *this* repo (a ``.py`` module, an ADR number, a
HydraFlow class name, or a known config field).

The platitude / real-gotcha fixtures below are verbatim examples from the
issue and from the live wiki so the gate is pinned against real content,
not synthetic strings.
"""

from __future__ import annotations

from wiki_anchor_gate import (
    config_field_vocabulary,
    has_repo_anchor,
)

# Verbatim platitudes named in issue #9954 — these MUST be rejected.
_PLATITUDES = [
    (
        "Use is None and is not None for optional sentinels",
        "Use `is None` and `is not None` for optional objects. Example: "
        "`if callback is None: return`. Avoid `==` comparison for sentinels; "
        "custom `__eq__` can hide subtle bugs. **Why:** identity checks are "
        "immune to overridden `__eq__`.",
    ),
    (
        "Create a specialized method rather than overloading",
        "Prefer a dedicated method over a flag argument that switches "
        "behavior. Example: split `save(force=True)` into `save()` and "
        "`force_save()`. **Why:** boolean flags obscure call sites.",
    ),
    (
        "Use portable shell commands in Alpine containers — Python is absent",
        "In Alpine-based Docker containers, avoid Python and non-standard "
        "utilities. Use portable POSIX commands for memory/CPU operations. "
        "Example: `dd if=/dev/zero bs=1M count=32 of=/dev/null`. **Why:** "
        "Alpine's minimal tooling excludes many GNU utilities.",
    ),
    (
        "Delete code blocks bottom-to-top to avoid line-number shifts",
        "When removing multiple ranges, edit from the last line upward. "
        "**Why:** deleting from the top renumbers everything below it.",
    ),
]

# Real repo-specific gotchas — these MUST land.
_ANCHORED = [
    (
        "Error-tolerance tests must cover CreditExhaustedError re-raise",
        "When testing that a loop tolerates port failures, include a case "
        "asserting `CreditExhaustedError` is not swallowed. See "
        "`test_review_phase_core.py:1919`. **Why:** `reraise_on_credit_or_bug` "
        "is load-bearing.",
    ),
    (
        "StagingPromotionLoop cuts RC PRs on a cadence",
        "The StagingPromotionLoop opens rc/ promotion PRs every "
        "`rc_cadence_hours`. **Why:** main only advances via RC promotion.",
    ),
    (
        "RepoWikiLoop maintenance PRs coalesce",
        "Subsequent ticks append to the same branch when "
        "`repo_wiki_maintenance_pr_coalesce` is true. **Why:** avoids "
        "duplicate maintenance PRs.",
    ),
    (
        "Two-tier branch promotion",
        "PRs target staging per ADR-0042; main advances via rc/ PRs. "
        "**Why:** staging gates promotion.",
    ),
    (
        "Fail-closed Port ownership",
        "A Port should raise rather than swallow so the FakeGitHub double "
        "surfaces the failure. **Why:** silent swallow hides real errors.",
    ),
]


class TestStructuralAnchors:
    def test_py_path_is_anchor(self) -> None:
        assert has_repo_anchor("See src/repo_wiki.py for the mint logic.")

    def test_bare_py_filename_is_anchor(self) -> None:
        assert has_repo_anchor("wiki_compiler.py owns the synthesis prompt.")

    def test_adr_number_is_anchor(self) -> None:
        assert has_repo_anchor("PRs target staging per ADR-0042.")
        assert has_repo_anchor("see adr 53 for the glossary")

    def test_loop_classname_is_anchor(self) -> None:
        assert has_repo_anchor("RepoWikiLoop keeps the wiki fresh.")

    def test_port_classname_is_anchor(self) -> None:
        assert has_repo_anchor("Route reads through WorkspacePort.")

    def test_fake_classname_is_anchor(self) -> None:
        assert has_repo_anchor("FakeGitHub records the command.")

    def test_ecase_dot_prose_is_not_a_py_path(self) -> None:
        # "e.g." and ordinary dotted prose must not be read as a .py path.
        assert not has_repo_anchor("Prefer small functions, e.g. one job each.")

    def test_bare_capitalized_word_is_not_a_classname(self) -> None:
        assert not has_repo_anchor("Store the value. Manage the queue.")


class TestConfigFieldAnchors:
    def test_known_config_field_is_anchor(self) -> None:
        vocab = frozenset({"rc_cadence_hours", "max_repo_wiki_chars"})
        assert has_repo_anchor(
            "Cut RC PRs every rc_cadence_hours.", config_fields=vocab
        )

    def test_unknown_snake_case_is_not_anchor(self) -> None:
        vocab = frozenset({"rc_cadence_hours"})
        assert not has_repo_anchor(
            "Set source_type when you ingest.", config_fields=vocab
        )

    def test_no_vocab_means_structural_only(self) -> None:
        # Without a vocabulary, a bare config-field mention is not enough.
        assert not has_repo_anchor("tune rc_cadence_hours as needed")


class TestRealCorpus:
    def test_all_named_platitudes_rejected(self) -> None:
        vocab = config_field_vocabulary()
        for title, body in _PLATITUDES:
            assert not has_repo_anchor(f"{title}\n{body}", config_fields=vocab), (
                f"platitude wrongly anchored: {title!r}"
            )

    def test_all_real_gotchas_kept(self) -> None:
        vocab = config_field_vocabulary()
        for title, body in _ANCHORED:
            assert has_repo_anchor(f"{title}\n{body}", config_fields=vocab), (
                f"real gotcha wrongly rejected: {title!r}"
            )

    def test_empty_text_is_not_anchored(self) -> None:
        assert not has_repo_anchor("")


class TestConfigFieldVocabulary:
    def test_includes_distinctive_fields(self) -> None:
        vocab = config_field_vocabulary()
        assert "rc_cadence_hours" in vocab
        assert "max_repo_wiki_chars" in vocab

    def test_excludes_single_token_fields(self) -> None:
        # Single-word fields ("model", "repo") appear in ordinary prose and
        # would false-positive the gate.
        vocab = config_field_vocabulary()
        assert "model" not in vocab
        assert "repo" not in vocab
