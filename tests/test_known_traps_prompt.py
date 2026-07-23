"""Known CI Traps prompt steering from harness-insights (#9858).

The insights store recorded recurring CI failure classes but nothing
injected them into the next agent's instructions — the fleet kept re-hitting
documented walls (live case: factory PR #9922 added a `# noqa` and tripped
the suppression ratchet, a class the store already knew).
"""

from __future__ import annotations

import json
from pathlib import Path

from harness_insights import format_known_traps_for_prompt, top_failure_categories


def _write_failures(path: Path, rows: list[dict]) -> Path:
    f = path / "harness_failures.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return f


def test_recurring_categories_ranked_with_samples(tmp_path: Path) -> None:
    f = _write_failures(
        tmp_path,
        [
            {"category": "quality_gate", "detail": "ratchet: new noqa"},
            {"category": "quality_gate", "detail": "ratchet again"},
            {"category": "quality_gate", "detail": "third"},
            {"category": "ci_failure", "detail": "arch drift"},
            {"category": "ci_failure", "detail": "arch drift 2"},
            {"category": "one_off", "detail": "noise"},
        ],
    )

    top = top_failure_categories(f)

    assert top[0][0] == "quality_gate" and top[0][1] == 3
    assert top[0][2] == "ratchet: new noqa"  # first sample wins
    assert top[1][0] == "ci_failure" and top[1][1] == 2


def test_malformed_lines_and_missing_file_are_safe(tmp_path: Path) -> None:
    f = tmp_path / "harness_failures.jsonl"
    f.write_text('not json\n{"category": "x"}\n{"nope": 1}\n')

    assert top_failure_categories(f) == [("x", 1, "")]
    assert top_failure_categories(tmp_path / "absent.jsonl") == []


def test_formatter_renders_only_recurring_classes(tmp_path: Path) -> None:
    section = format_known_traps_for_prompt(
        [("quality_gate", 3, "ratchet: new noqa"), ("one_off", 1, "noise")]
    )

    assert "Known CI Traps" in section
    assert "quality_gate" in section and "seen 3x" in section
    assert "one_off" not in section  # count<2 is noise, not a trap
    assert "noqa" in section  # the standing ratchet warning rides along


def test_formatter_empty_for_healthy_repo() -> None:
    assert format_known_traps_for_prompt([]) == ""
    assert format_known_traps_for_prompt([("x", 1, "")]) == ""
