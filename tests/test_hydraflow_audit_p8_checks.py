"""Tests for P8 (superpowers / skills) check functions."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p8_superpowers  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _settings(
    root: Path,
    *,
    hooks: dict[str, list] | None = None,
    filename: str = "settings.json",
) -> None:
    payload: dict = {}
    if hooks is not None:
        payload["hooks"] = hooks
    _write(root / ".claude" / filename, json.dumps(payload))


# --- .claude / settings --------------------------------------------------


def test_claude_dir_present_passes(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    assert _run("P8.1", _ctx(tmp_path)).status is Status.PASS


def test_claude_dir_absent_fails(tmp_path: Path) -> None:
    assert _run("P8.1", _ctx(tmp_path)).status is Status.FAIL


def test_settings_json_passes(tmp_path: Path) -> None:
    _settings(tmp_path)
    assert _run("P8.2", _ctx(tmp_path)).status is Status.PASS


def test_settings_local_json_also_counts(tmp_path: Path) -> None:
    _settings(tmp_path, filename="settings.local.json")
    assert _run("P8.2", _ctx(tmp_path)).status is Status.PASS


def test_settings_absent_fails(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    assert _run("P8.2", _ctx(tmp_path)).status is Status.FAIL


def test_settings_malformed_json_fails(tmp_path: Path) -> None:
    _write(tmp_path / ".claude" / "settings.json", "{ not json")
    assert _run("P8.2", _ctx(tmp_path)).status is Status.FAIL


# --- Hook kinds ----------------------------------------------------------


def test_pre_tool_use_hook_detected(tmp_path: Path) -> None:
    _settings(tmp_path, hooks={"PreToolUse": [{"matcher": "Bash"}]})
    assert _run("P8.3", _ctx(tmp_path)).status is Status.PASS


def test_no_pre_tool_use_hook_fails(tmp_path: Path) -> None:
    _settings(tmp_path, hooks={"Stop": [{"matcher": "*"}]})
    assert _run("P8.3", _ctx(tmp_path)).status is Status.FAIL


def test_three_hook_kinds_all_present(tmp_path: Path) -> None:
    _settings(
        tmp_path,
        hooks={
            "PreToolUse": [{"m": "a"}],
            "PostToolUse": [{"m": "b"}],
            "Stop": [{"m": "c"}],
        },
    )
    assert _run("P8.5", _ctx(tmp_path)).status is Status.PASS


def test_three_hook_kinds_missing_one_fails(tmp_path: Path) -> None:
    _settings(
        tmp_path,
        hooks={"PreToolUse": [{"m": "a"}], "PostToolUse": [{"m": "b"}]},
    )
    result = _run("P8.5", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "Stop" in result.message


# --- CLAUDE.md core skills ----------------------------------------------


_ALL_SIX_SKILLS = """
# Project

Use: brainstorming, test-driven-development, systematic-debugging,
writing-plans, verification-before-completion, and requesting-code-review.
"""


def test_all_six_skills_named_passes(tmp_path: Path) -> None:
    _write(tmp_path / "CLAUDE.md", _ALL_SIX_SKILLS)
    assert _run("P8.4", _ctx(tmp_path)).status is Status.PASS


def test_missing_core_skill_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "CLAUDE.md",
        "Use brainstorming and writing-plans.\n",
    )
    result = _run("P8.4", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "test-driven-development" in result.message


# --- Trace collector -----------------------------------------------------


def test_trace_collector_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "trace_collector.py",
        "# writes subprocess traces\ndef write_trace(run_dir): ...\n",
    )
    assert _run("P8.6", _ctx(tmp_path)).status is Status.PASS


def test_trace_collector_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P8.6", _ctx(tmp_path)).status is Status.FAIL


# --- Review after every PR ------------------------------------------------


def test_claude_md_requires_review_every_pr_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "CLAUDE.md",
        "Run a code review after every PR you create, not only substantial features.\n",
    )
    assert _run("P8.7", _ctx(tmp_path)).status is Status.PASS


def test_claude_md_requires_review_every_pr_case_insensitive(tmp_path: Path) -> None:
    _write(tmp_path / "CLAUDE.md", "CODE REVIEW AFTER EVERY PR is mandatory.\n")
    assert _run("P8.7", _ctx(tmp_path)).status is Status.PASS


def test_claude_md_review_rule_paraphrase_passes(tmp_path: Path) -> None:
    """#11153 review: the check must tolerate rewording (sibling P10.1
    convention) — cadence marker + review co-occurring in one sentence, in
    either order, not one literal phrase."""
    _write(
        tmp_path / "CLAUDE.md",
        "After every PR you create, run a fresh-eyes code review before "
        "enabling auto-merge.\n",
    )
    assert _run("P8.7", _ctx(tmp_path)).status is Status.PASS


def test_claude_md_review_rule_cross_sentence_mention_fails(tmp_path: Path) -> None:
    """'review' in one sentence and 'every PR' in another must not pass —
    the co-occurrence window stops at sentence bounds."""
    _write(
        tmp_path / "CLAUDE.md",
        "We value code review. CI runs on every PR automatically.\n",
    )
    assert _run("P8.7", _ctx(tmp_path)).status is Status.FAIL


def test_claude_md_review_substring_words_do_not_pass(tmp_path: Path) -> None:
    """#11166 (re-audit find): 'preview' contains the substring 'review' —
    an unanchored regex passed CLAUDE.md text that says nothing about
    running a code review. The interview case guards the same anchor from
    the cadence-first alternation side."""
    _write(
        tmp_path / "CLAUDE.md",
        "Preview environments are generated for every PR automatically.\n",
    )
    assert _run("P8.7", _ctx(tmp_path)).status is Status.FAIL

    _write(
        tmp_path / "CLAUDE.md",
        "Interview every PR author before merge for context.\n",
    )
    assert _run("P8.7", _ctx(tmp_path)).status is Status.FAIL


def test_claude_md_only_substantial_features_review_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "CLAUDE.md",
        "For substantial features, plan for 2-3 fresh-eyes review iterations "
        "before merge.\n",
    )
    result = _run("P8.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "every PR" in result.message


def test_claude_md_missing_fails_p8_7(tmp_path: Path) -> None:
    result = _run("P8.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "CLAUDE.md missing" in result.message
