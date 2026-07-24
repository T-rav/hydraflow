"""Staging RC dry-run sensor reporter — #10352 (G2).

Covers the pure aggregation + issue-body formatting that turns per-shard run
summaries into a hydraflow-find issue naming the broken RC-gate scenario(s).
Docker/CI wiring is not exercised here — only the logic that decides *what* the
sensor reports.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.sandbox_scenario import _summary_payload
from scripts.staging_rc_dryrun_report import (
    collect_failures,
    format_find_issue,
    main,
)


class TestSummaryPayload:
    def test_records_failures_and_passes(self) -> None:
        payload = _summary_payload(
            [("s01_happy", 0, 12.3), ("s75_stall", 1, 8.9)], shard="2/6"
        )
        assert payload["shard"] == "2/6"
        assert payload["failed"] == ["s75_stall"]
        names = [s["name"] for s in payload["scenarios"]]
        assert names == ["s01_happy", "s75_stall"]

    def test_infra_failures_count_as_failed(self) -> None:
        # rc==2 is an infra failure (build/healthcheck); still a failure.
        payload = _summary_payload([("s10_boom", 2, 1.0)], shard=None)
        assert payload["failed"] == ["s10_boom"]

    def test_all_green_has_no_failures(self) -> None:
        payload = _summary_payload([("s01", 0, 1.0), ("s02", 0, 2.0)], shard="1/6")
        assert payload["failed"] == []


class TestCollectFailures:
    def _write(self, tmp_path: Path, name: str, payload: dict) -> Path:
        p = tmp_path / name
        p.write_text(json.dumps(payload))
        return p

    def test_unions_across_shards_sorted_unique(self, tmp_path: Path) -> None:
        self._write(
            tmp_path,
            "summary-1.json",
            _summary_payload([("s81", 1, 1.0), ("s01", 0, 1.0)], "1/2"),
        )
        self._write(
            tmp_path,
            "summary-2.json",
            _summary_payload([("s75", 1, 1.0), ("s81", 1, 1.0)], "2/2"),
        )
        assert collect_failures(sorted(tmp_path.glob("summary*.json"))) == [
            "s75",
            "s81",
        ]

    def test_empty_when_all_pass(self, tmp_path: Path) -> None:
        self._write(
            tmp_path, "summary-1.json", _summary_payload([("s01", 0, 1.0)], "1/1")
        )
        assert collect_failures(sorted(tmp_path.glob("summary*.json"))) == []

    def test_skips_malformed_and_missing(self, tmp_path: Path) -> None:
        (tmp_path / "summary-bad.json").write_text("{not json")
        self._write(
            tmp_path, "summary-ok.json", _summary_payload([("s99", 1, 1.0)], "1/2")
        )
        paths = [
            tmp_path / "summary-bad.json",
            tmp_path / "summary-ok.json",
            tmp_path / "summary-missing.json",  # never written
        ]
        assert collect_failures(paths) == ["s99"]

    def test_ignores_non_dict_payloads(self, tmp_path: Path) -> None:
        (tmp_path / "summary-list.json").write_text("[1, 2, 3]")
        assert collect_failures([tmp_path / "summary-list.json"]) == []


class TestFormatFindIssue:
    def test_title_names_count_and_short_sha(self) -> None:
        title, _ = format_find_issue(["s75", "s81"], "abcdef1234567890", "https://run")
        assert "2 RC-gate scenario(s)" in title
        assert "abcdef123456" in title  # 12-char short sha

    def test_body_lists_scenarios_full_sha_and_run_url(self) -> None:
        _, body = format_find_issue(
            ["s75_worker_stall", "s81_label_drift"],
            "deadbeefcafe0001",
            "https://github.com/run/42",
        )
        assert "`s75_worker_stall`" in body
        assert "`s81_label_drift`" in body
        assert "deadbeefcafe0001" in body
        assert "https://github.com/run/42" in body
        assert "advisory on" in body  # explains why staging didn't block

    def test_handles_missing_sha_and_url(self) -> None:
        title, body = format_find_issue(["s01"], "", "")
        assert "unknown" in title
        assert "unknown" in body
        assert "(local run)" in body


class TestMain:
    def _shard_summary(self, tmp_path: Path, shard_dir: str, payload: dict) -> None:
        d = tmp_path / shard_dir
        d.mkdir(parents=True)
        (d / "summary.json").write_text(json.dumps(payload))

    def test_writes_has_failures_true_and_body_on_break(self, tmp_path: Path) -> None:
        self._shard_summary(
            tmp_path,
            "shard-1",
            _summary_payload([("s81", 1, 1.0)], "1/6"),
        )
        out = tmp_path / "gh_output"
        rc = main(
            [
                "--results-dir",
                str(tmp_path),
                "--sha",
                "cafebabe0000",
                "--run-url",
                "https://run",
                "--github-output",
                str(out),
            ]
        )
        assert rc == 0
        text = out.read_text()
        assert "has_failures=true" in text
        assert "title=" in text  # single-line title
        assert "body<<" in text  # multiline body via heredoc delimiter
        assert "s81" in text

    def test_writes_has_failures_false_when_green(self, tmp_path: Path) -> None:
        self._shard_summary(
            tmp_path, "shard-1", _summary_payload([("s01", 0, 1.0)], "1/6")
        )
        out = tmp_path / "gh_output"
        rc = main(["--results-dir", str(tmp_path), "--github-output", str(out)])
        assert rc == 0
        text = out.read_text()
        assert "has_failures=false" in text
        assert "title" not in text

    def test_no_summaries_is_green(self, tmp_path: Path) -> None:
        out = tmp_path / "gh_output"
        rc = main(["--results-dir", str(tmp_path), "--github-output", str(out)])
        assert rc == 0
        assert "has_failures=false" in out.read_text()
