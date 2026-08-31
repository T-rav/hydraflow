"""Evidence gathering for the retrospective (§1).

`gather` is a pure read over artefacts the pipeline already writes: the
`SubprocessTrace` JSONs under `<data_root>/traces/` and the phase transcripts
under `<log_dir>/`. It must never raise — a retro tick is best-effort, and a
repo predating trace collection simply yields an empty bundle.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retro_evidence import TRANSCRIPT_GLOBS, gather  # noqa: E402
from tests.helpers import ConfigFactory

SRC = Path(__file__).parent.parent / "src"


def _config(tmp_path: Path):
    # log_dir is a read-only property derived from data_root.
    config = ConfigFactory.create()
    config.data_root = tmp_path / "data"
    config.log_dir.mkdir(parents=True, exist_ok=True)
    return config


def _write_trace(config, issue: int, phase: str, run: int, idx: int, **over) -> Path:
    payload = {
        "issue_number": issue,
        "phase": phase,
        "source": "implementer",
        "run_id": run,
        "subprocess_idx": idx,
        "backend": "claude",
        "started_at": "2026-08-31T00:00:00+00:00",
        "ended_at": "2026-08-31T00:01:00+00:00",
        "success": True,
        "crashed": False,
        "error": None,
        "tokens": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_hit_rate": 0.0,
        },
        "tools": {"tool_counts": {}, "tool_errors": {}, "total_invocations": 0},
        "tool_calls": [],
        "skill_results": [],
        "turn_count": 1,
        "inference_count": 1,
    }
    payload.update(over)
    d = config.data_root / "traces" / str(issue) / phase / f"run-{run}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"subprocess-{idx}.json"
    path.write_text(json.dumps(payload))
    return path


class TestGatherIsTotal:
    def test_missing_everything_yields_an_empty_bundle(self, tmp_path: Path):
        bundle = gather(_config(tmp_path), 42)

        assert bundle.issue_number == 42
        assert bundle.traces == []
        assert bundle.transcripts == {}

    def test_malformed_trace_json_is_skipped_not_raised(self, tmp_path: Path):
        config = _config(tmp_path)
        _write_trace(config, 42, "implement", 1, 0)
        bad = config.data_root / "traces" / "42" / "implement" / "run-1"
        (bad / "subprocess-9.json").write_text("{not json")

        bundle = gather(config, 42)

        assert len(bundle.traces) == 1


class TestGatherCollectsTraces:
    def test_traces_span_phases_and_runs(self, tmp_path: Path):
        config = _config(tmp_path)
        _write_trace(config, 42, "implement", 1, 0)
        _write_trace(config, 42, "implement", 2, 0)
        _write_trace(config, 42, "review", 1, 0)

        bundle = gather(config, 42)

        assert {(t.phase, t.run_id) for t in bundle.traces} == {
            ("implement", 1),
            ("implement", 2),
            ("review", 1),
        }

    def test_another_issues_traces_are_not_collected(self, tmp_path: Path):
        config = _config(tmp_path)
        _write_trace(config, 42, "implement", 1, 0)
        _write_trace(config, 99, "implement", 1, 0)

        bundle = gather(config, 42)

        assert [t.issue_number for t in bundle.traces] == [42]


class TestGatherCollectsTranscripts:
    def test_static_phase_prefixes_are_read(self, tmp_path: Path):
        config = _config(tmp_path)
        for prefix in ("issue", "plan-issue", "triage-issue", "hitl-issue"):
            (config.log_dir / f"{prefix}-42.txt").write_text(f"body of {prefix}")

        bundle = gather(config, 42)

        assert set(bundle.transcripts) >= {
            "issue-42",
            "plan-issue-42",
            "triage-issue-42",
            "hitl-issue-42",
        }
        assert bundle.transcripts["plan-issue-42"] == "body of plan-issue"

    def test_dynamic_attempt_numbered_prefixes_are_read(self, tmp_path: Path):
        config = _config(tmp_path)
        (config.log_dir / "discover-issue-attempt2-42.txt").write_text("d")
        (config.log_dir / "shape-issue-turn1-attempt3-42.txt").write_text("s")

        bundle = gather(config, 42)

        assert "discover-issue-attempt2-42" in bundle.transcripts
        assert "shape-issue-turn1-attempt3-42" in bundle.transcripts

    def test_pr_keyed_review_transcripts_are_not_mistaken_for_the_issue(
        self, tmp_path: Path
    ):
        """`review-pr-42.txt` is keyed by PR number, not issue number."""
        config = _config(tmp_path)
        (config.log_dir / "review-pr-42.txt").write_text("different entity")
        (config.log_dir / "review-fix-42.txt").write_text("different entity")

        bundle = gather(config, 42)

        assert bundle.transcripts == {}


class TestPrefixCoverageIsDerivedNotSpelled:
    """A new runner adding an issue-keyed transcript must not go unread.

    Derived from the `_save_transcript` call sites rather than restated, so a
    prefix added elsewhere in src/ reds this test instead of silently falling
    outside the retro's view.
    """

    # Two spellings reach _save_transcript: a literal first argument, and a
    # `transcript_prefix=` keyword threaded through the reviewer. Deriving from
    # only the first would leave the keyword form unseen — and would make the
    # PR-keyed exclusion below dead code that silently passes.
    _PREFIX_PATTERNS = (
        re.compile(r"_save_transcript\(\s*f?\"([^\"]+)\""),
        re.compile(r"transcript_prefix\s*=\s*f?\"([^\"]+)\""),
    )

    @classmethod
    def _all_prefixes(cls) -> set[str]:
        found: set[str] = set()
        for path in SRC.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in cls._PREFIX_PATTERNS:
                for raw in pattern.findall(text):
                    found.add(re.sub(r"\{[^}]+\}", "*", raw))
        return found

    @classmethod
    def _pr_keyed(cls) -> set[str]:
        # reviewer/_fixes.py keys these by result.pr_number, a different entity
        # from the issue the retro gathers evidence for.
        return {p for p in cls._all_prefixes() if p.startswith("review-")}

    @classmethod
    def _issue_keyed_prefixes(cls) -> set[str]:
        return cls._all_prefixes() - cls._pr_keyed()

    def test_every_issue_keyed_prefix_has_a_gather_glob(self):
        globs = {g.replace("-{n}.txt", "") for g in TRANSCRIPT_GLOBS}

        uncovered = {p for p in self._issue_keyed_prefixes() if p not in globs}

        assert not uncovered, f"transcript prefixes the retro cannot see: {uncovered}"

    def test_the_derivation_actually_finds_call_sites(self):
        """Guard the guard: an empty derivation would make it vacuously pass."""
        assert "issue" in self._issue_keyed_prefixes()

    def test_the_pr_keyed_exclusion_is_live_not_dead(self):
        """An exclusion that never matches anything is a comment, not a filter."""
        assert self._pr_keyed() == {"review-pr", "review-fix"}
