"""Unit tests for the runtime-cache tracking guard.

Covers the pure classifiers (mode a: git-tracked cache files; mode b: untracked
un-ignored loop artifacts under a generated-artifact dir) and the CLI exit codes.
The script is loaded via ``importlib`` exactly like
``tests/test_check_conflict_markers.py`` so no cross-module ``_``-prefixed import
is needed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "scripts" / "check_runtime_cache_tracked.py"
_spec = importlib.util.spec_from_file_location("check_runtime_cache_tracked", _SCRIPT)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["check_runtime_cache_tracked"] = guard
_spec.loader.exec_module(guard)


class TestClassifyTrackedPaths:
    def test_flags_log_jsonl_cache(self) -> None:
        assert guard.classify_tracked_paths(["docs/foo/log.jsonl"]) == [
            "docs/foo/log.jsonl"
        ]

    def test_flags_index_json_cache(self) -> None:
        assert guard.classify_tracked_paths(["docs/bar/index.json"]) == [
            "docs/bar/index.json"
        ]

    def test_flags_dedup_caches(self) -> None:
        offenders = guard.classify_tracked_paths(
            ["a/ingest_dedup.json", "b/foo_dedup.json"]
        )
        assert offenders == ["a/ingest_dedup.json", "b/foo_dedup.json"]

    def test_flags_generic_cache_basenames(self) -> None:
        offenders = guard.classify_tracked_paths(["svc/state_cache.json"])
        assert offenders == ["svc/state_cache.json"]

    def test_flags_path_under_cache_dir_segment(self) -> None:
        assert guard.classify_tracked_paths(["svc/cache/blob.json"]) == [
            "svc/cache/blob.json"
        ]

    def test_numbered_repo_wiki_log_is_not_a_cache(self) -> None:
        offenders = guard.classify_tracked_paths(
            ["repo_wiki/T-rav/hydraflow/log/7644.jsonl"]
        )
        assert offenders == []

    def test_test_fixtures_are_excluded(self) -> None:
        paths = ["tests/fixtures/prompts/canary-trace.jsonl", "tests/foo/index.json"]
        assert guard.classify_tracked_paths(paths) == []

    def test_ordinary_source_files_are_not_caches(self) -> None:
        paths = ["src/foo.py", "README.md", "src/ui/package.json"]
        assert guard.classify_tracked_paths(paths) == []

    def test_allowlisted_path_is_exempt(self, monkeypatch) -> None:
        monkeypatch.setattr(guard, "ALLOWLIST", frozenset({"docs/keep/index.json"}))
        assert guard.classify_tracked_paths(["docs/keep/index.json"]) == []

    def test_empty_input_returns_empty(self) -> None:
        assert guard.classify_tracked_paths([]) == []


class TestClassifyUntrackedArtifacts:
    def test_flags_untracked_artifact_under_generated_dir(self) -> None:
        offenders = guard.classify_untracked_artifacts(
            ["docs/arch/generated/loop-fitness.md"]
        )
        assert offenders == ["docs/arch/generated/loop-fitness.md"]

    def test_ignores_untracked_files_outside_generated_dirs(self) -> None:
        offenders = guard.classify_untracked_artifacts(
            ["scratch/notes.md", "tmp/x.json"]
        )
        assert offenders == []

    def test_empty_input_returns_empty(self) -> None:
        assert guard.classify_untracked_artifacts([]) == []


class TestMain:
    def test_explicit_cache_path_returns_1_with_remediation(
        self, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr(guard, "_repo_root", lambda: Path("/repo"))
        rc = guard.main(["docs/foo/index.json"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "git rm --cached" in captured.err

    def test_explicit_clean_path_returns_0(self, capsys, monkeypatch) -> None:
        monkeypatch.setattr(guard, "_repo_root", lambda: Path("/repo"))
        rc = guard.main(["src/foo.py"])
        assert rc == 0
        assert capsys.readouterr().err == ""

    def test_tracked_mode_over_live_repo_is_clean(self) -> None:
        assert guard.main(["--tracked"]) == 0

    def test_untracked_mode_returns_1_when_artifact_present(
        self, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr(guard, "_repo_root", lambda: Path("/repo"))
        monkeypatch.setattr(
            guard,
            "_untracked_unignored_files",
            lambda _root: ["docs/arch/generated/loop-fitness.md"],
        )
        rc = guard.main(["--untracked"])
        captured = capsys.readouterr()
        assert rc == 1
        assert ".gitignore" in captured.err
