"""Unit tests for the shadow shape classifier (issue #9354).

Covers the three-way classification (MUTATING / VOLATILE / DETERMINISTIC)
and the ``is_value_comparable`` predicate.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# ShapeClass enum and is_value_comparable
# ---------------------------------------------------------------------------


def test_shape_class_is_str_enum() -> None:
    from contracts.shadow_classifier import ShapeClass

    assert str(ShapeClass.MUTATING) == "MUTATING"
    assert str(ShapeClass.VOLATILE) == "VOLATILE"
    assert str(ShapeClass.DETERMINISTIC) == "DETERMINISTIC"


def test_is_value_comparable_deterministic_only() -> None:
    from contracts.shadow_classifier import ShapeClass, is_value_comparable

    assert is_value_comparable(ShapeClass.DETERMINISTIC) is True
    assert is_value_comparable(ShapeClass.VOLATILE) is False
    assert is_value_comparable(ShapeClass.MUTATING) is False


# ---------------------------------------------------------------------------
# SHAPE_VERDICT_KEY constant
# ---------------------------------------------------------------------------


def test_shape_verdict_key_matches_dispatcher_key() -> None:
    """SHAPE_VERDICT_KEY must equal the key shape_dispatchers embeds in drift
    dicts so the compare-time suppression in LiveCorpusReplayLoop can find it."""
    from contracts.shadow_classifier import SHAPE_VERDICT_KEY

    assert SHAPE_VERDICT_KEY == "shape_validation_failed"


# ---------------------------------------------------------------------------
# classify — MUTATING shapes (dropped at record time)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "create", "--title", "x"],
        ["pr", "create", "--title", "x"],
        ["issue", "comment", "1", "--body", "hi"],
        ["pr", "comment", "1", "--body", "hi"],
        ["issue", "close", "1"],
        ["pr", "merge", "1"],
        ["issue", "edit", "1", "--title", "y"],
        ["issue", "delete", "1"],
        ["pr", "close", "1"],
        ["issue", "reopen", "1"],
    ],
)
def test_gh_mutating_verbs_classify_as_mutating(args: list[str]) -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("github", "gh", args)
    assert result is ShapeClass.MUTATING, f"expected MUTATING for {args}, got {result}"


@pytest.mark.parametrize(
    "args",
    [
        ["push"],
        ["push", "origin", "main"],
        ["clone", "https://github.com/x/y"],
        ["worktree", "add", "../worktree", "branch"],
        ["worktree", "remove", "../worktree"],
        ["add", "src/file.py"],
        ["commit", "-m", "msg"],
        ["merge", "feature"],
        ["rebase", "main"],
        ["reset", "--hard", "HEAD~1"],
        ["restore", "src/file.py"],
        ["fetch", "origin"],
        ["tag", "v1.0"],
    ],
)
def test_git_mutating_commands_classify_as_mutating(args: list[str]) -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("git", "git", args)
    assert result is ShapeClass.MUTATING, f"expected MUTATING for {args}, got {result}"


def test_gh_api_with_post_method_classifies_as_mutating() -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("github", "gh", ["api", "--method", "POST", "repos/x/y/issues"])
    assert result is ShapeClass.MUTATING


def test_gh_api_with_patch_method_classifies_as_mutating() -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify(
        "github", "gh", ["api", "--method", "PATCH", "repos/x/y/issues/1"]
    )
    assert result is ShapeClass.MUTATING


def test_gh_api_with_x_flag_post_classifies_as_mutating() -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("github", "gh", ["api", "-X", "POST", "repos/x/y/issues"])
    assert result is ShapeClass.MUTATING


# ---------------------------------------------------------------------------
# classify — VOLATILE shapes (kept for shape-only validation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "list"],
        ["issue", "list", "--state", "open"],
        ["pr", "list"],
        ["pr", "list", "--state", "open"],
        ["search", "issues", "--repo", "x/y"],
        ["search", "prs", "--repo", "x/y"],
    ],
)
def test_gh_list_and_search_classify_as_volatile(args: list[str]) -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("github", "gh", args)
    assert result is ShapeClass.VOLATILE, f"expected VOLATILE for {args}, got {result}"


@pytest.mark.parametrize(
    "api_args",
    [
        ["api", "search/issues", "--jq", ".items"],
        ["api", "repos/x/y/pulls"],
        ["api", "repos/x/y/issues"],
    ],
)
def test_gh_api_search_and_list_paths_classify_as_volatile(api_args: list[str]) -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("github", "gh", api_args)
    assert result is ShapeClass.VOLATILE, (
        f"expected VOLATILE for {api_args}, got {result}"
    )


@pytest.mark.parametrize(
    "args",
    [
        ["status", "--porcelain"],
        ["log", "--oneline", "-5"],
        ["diff", "HEAD~1", "HEAD"],
        ["ls-remote", "origin"],
        ["show", "HEAD"],
    ],
)
def test_git_query_commands_classify_as_volatile(args: list[str]) -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("git", "git", args)
    assert result is ShapeClass.VOLATILE, f"expected VOLATILE for {args}, got {result}"


# ---------------------------------------------------------------------------
# classify — DETERMINISTIC shapes (full value comparison)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["pr", "view", "42", "--json", "state,number"],
        ["pr", "view", "1"],
        ["issue", "view", "99", "--json", "number,state"],
        ["issue", "view", "1"],
        ["pr", "checks", "42"],
    ],
)
def test_gh_view_and_checks_classify_as_deterministic(args: list[str]) -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("github", "gh", args)
    assert result is ShapeClass.DETERMINISTIC, (
        f"expected DETERMINISTIC for {args}, got {result}"
    )


# ---------------------------------------------------------------------------
# classify — conservative fallback for unknown adapters/commands
# ---------------------------------------------------------------------------


def test_docker_adapter_falls_back_to_volatile() -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("docker", "docker", ["run", "--rm", "alpine"])
    assert result is ShapeClass.VOLATILE


def test_claude_adapter_falls_back_to_volatile() -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("claude", "claude", ["-p", "hello"])
    assert result is ShapeClass.VOLATILE


def test_gh_empty_args_falls_back_to_volatile() -> None:
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("github", "gh", [])
    assert result is ShapeClass.VOLATILE


def test_git_worktree_list_classifies_as_volatile() -> None:
    """git worktree list is a query, not a mutation."""
    from contracts.shadow_classifier import ShapeClass, classify

    result = classify("git", "git", ["worktree", "list"])
    assert result is ShapeClass.VOLATILE
