"""Executed-behaviour tests for the staging RC dry-run shard SHA pin (#11518).

The shard job of ``.github/workflows/staging-rc-dryrun.yml`` used to check out
``ref: ${{ needs.resolve.outputs.sha }}`` — a job output, which CodeQL flags as
``actions/cache-poisoning/poisonable-step`` (alert #108) because it cannot see
that the SHA is a ``git rev-parse HEAD`` of the protected ``staging`` branch.

The fix checks out the literal protected branch and *asserts in-job* that the
checked-out HEAD is the SHA the ``resolve`` job named. That assertion is the
safety property of the whole workflow — it is what preserves "one SHA per
report" — so it lives in ``scripts/staging_rc_dryrun_pin.py`` where a test can
actually **run** it, rather than as inline YAML bash that only a shape test can
look at. Every test here executes the real code path: real ``$GITHUB_OUTPUT``
files, real exit codes, real ``git rev-parse``, real JSON round-trip through the
reporter that consumes it.
"""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.staging_rc_dryrun_pin import (
    SKIP_REASON,
    main,
    resolve_head_sha,
    skip_marker_payload,
    verify_pin,
)
from scripts.staging_rc_dryrun_report import collect_failures
from scripts.staging_rc_dryrun_report import main as report_main

_SHA_A = "a" * 40
_SHA_B = "b" * 40

REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_SCRIPT = REPO_ROOT / "scripts" / "staging_rc_dryrun_pin.py"


@pytest.fixture(autouse=True)
def _no_ambient_github_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the *runner's* ``$GITHUB_OUTPUT`` out of the code under test.

    ``main`` defaults ``--github-output`` to the env var, and Actions always
    sets it. Without this, an in-process ``main`` call that omits the flag
    appends to the runner's real output file on CI while printing to stdout
    locally — so the suite passes on a laptop and fails in CI. Tests that need
    the variable set pass ``env=`` to a subprocess explicitly.
    """
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)


def _read_outputs(path: Path) -> dict[str, str]:
    """Parse a ``$GITHUB_OUTPUT`` file the way the Actions runner does."""
    outputs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            outputs[key] = value
    return outputs


def _run(tmp_path: Path, *args: str) -> tuple[int, dict[str, str]]:
    """Invoke ``main`` with a real ``$GITHUB_OUTPUT`` file; return (rc, outputs)."""
    out = tmp_path / "github_output.txt"
    out.touch()
    rc = main([*args, "--github-output", str(out)])
    return rc, _read_outputs(out)


class TestVerifyPin:
    """The pure comparison, isolated from IO."""

    def test_identical_shas_match(self) -> None:
        assert verify_pin(_SHA_A, _SHA_A).matched is True

    def test_different_shas_do_not_match(self) -> None:
        assert verify_pin(_SHA_A, _SHA_B).matched is False

    def test_surrounding_whitespace_is_ignored(self) -> None:
        assert verify_pin(f"  {_SHA_A}\n", f"{_SHA_A}  ").matched is True

    def test_case_differences_are_ignored(self) -> None:
        assert verify_pin(_SHA_A.upper(), _SHA_A).matched is True

    def test_abbreviated_sha_is_not_a_match(self) -> None:
        # A prefix match would let a *different* commit satisfy the pin.
        assert verify_pin(_SHA_A[:12], _SHA_A).matched is False

    def test_blank_expected_never_matches_blank_actual(self) -> None:
        # Two empty strings are "equal"; treating that as a match would let a
        # broken resolve job wave the shard straight through.
        assert verify_pin("", "").matched is False

    def test_verdict_carries_both_shas(self) -> None:
        verdict = verify_pin(_SHA_A, _SHA_B)
        assert (verdict.expected, verdict.actual) == (_SHA_A, _SHA_B)


class TestGithubOutput:
    """``matched`` is what every downstream ``if:`` reads — it must be written."""

    def test_match_writes_matched_true(self, tmp_path: Path) -> None:
        _, outputs = _run(tmp_path, "--expected-sha", _SHA_A, "--actual-sha", _SHA_A)
        assert outputs["matched"] == "true"

    def test_mismatch_writes_matched_false(self, tmp_path: Path) -> None:
        _, outputs = _run(tmp_path, "--expected-sha", _SHA_A, "--actual-sha", _SHA_B)
        assert outputs["matched"] == "false"

    def test_output_is_appended_not_truncated(self, tmp_path: Path) -> None:
        out = tmp_path / "github_output.txt"
        out.write_text("preexisting=1\n", encoding="utf-8")
        main(
            [
                "--expected-sha",
                _SHA_A,
                "--actual-sha",
                _SHA_A,
                "--github-output",
                str(out),
            ]
        )
        assert _read_outputs(out) == {"preexisting": "1", "matched": "true"}

    def test_missing_output_path_does_not_crash(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # With no `--github-output` and no $GITHUB_OUTPUT (stripped by the
        # autouse fixture — a hand-run of the script off-runner), the verdict
        # falls back to stdout instead of crashing on a None path.
        assert main(["--expected-sha", _SHA_A, "--actual-sha", _SHA_A]) == 0
        assert "matched=true" in capsys.readouterr().out


class TestExitCodes:
    """A shard that skips must stay green; a broken pin must go red."""

    def test_match_exits_zero(self, tmp_path: Path) -> None:
        rc, _ = _run(tmp_path, "--expected-sha", _SHA_A, "--actual-sha", _SHA_A)
        assert rc == 0

    def test_mismatch_exits_zero(self, tmp_path: Path) -> None:
        # Staging advancing mid-run is a benign race: the next 6-hourly tick
        # re-runs the shard. Going red here would be pure alert noise.
        rc, _ = _run(tmp_path, "--expected-sha", _SHA_A, "--actual-sha", _SHA_B)
        assert rc == 0

    def test_empty_expected_sha_exits_nonzero(self, tmp_path: Path) -> None:
        rc, outputs = _run(tmp_path, "--expected-sha", "", "--actual-sha", _SHA_A)
        assert rc != 0
        assert outputs["matched"] == "false"

    def test_unresolvable_head_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No `--actual-sha` and nothing for `git rev-parse HEAD` to resolve:
        # a broken checkout, not the staging-advanced race.
        bare = tmp_path / "not-a-repo"
        bare.mkdir()
        monkeypatch.chdir(bare)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        rc, outputs = _run(tmp_path, "--expected-sha", _SHA_A)
        assert rc != 0
        assert outputs["matched"] == "false"


class TestNotice:
    def test_mismatch_emits_a_single_line_github_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(tmp_path, "--expected-sha", _SHA_A, "--actual-sha", _SHA_B)
        notices = [
            line
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("::notice")
        ]
        assert len(notices) == 1
        assert _SHA_A[:12] in notices[0] and _SHA_B[:12] in notices[0]

    def test_match_emits_no_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(tmp_path, "--expected-sha", _SHA_A, "--actual-sha", _SHA_A)
        assert "::notice" not in capsys.readouterr().out


class TestSkipMarker:
    """The skip marker stands in for the shard summary the run never wrote."""

    def test_mismatch_writes_the_marker(self, tmp_path: Path) -> None:
        marker = tmp_path / "summary.json"
        _run(
            tmp_path,
            "--expected-sha",
            _SHA_A,
            "--actual-sha",
            _SHA_B,
            "--shard",
            "3/6",
            "--skip-summary-json",
            str(marker),
        )
        payload = json.loads(marker.read_text())
        assert payload["shard"] == "3/6"
        assert payload["skipped"]["reason"] == SKIP_REASON
        assert payload["skipped"]["expected_sha"] == _SHA_A
        assert payload["skipped"]["actual_sha"] == _SHA_B

    def test_match_does_not_write_the_marker(self, tmp_path: Path) -> None:
        # On the happy path the real run writes this file; clobbering it with a
        # skip marker would erase the shard's actual results.
        marker = tmp_path / "summary.json"
        _run(
            tmp_path,
            "--expected-sha",
            _SHA_A,
            "--actual-sha",
            _SHA_A,
            "--skip-summary-json",
            str(marker),
        )
        assert not marker.exists()

    def test_marker_parent_directory_is_created(self, tmp_path: Path) -> None:
        marker = tmp_path / "nested" / "dir" / "summary.json"
        _run(
            tmp_path,
            "--expected-sha",
            _SHA_A,
            "--actual-sha",
            _SHA_B,
            "--skip-summary-json",
            str(marker),
        )
        assert marker.exists()


class TestSkipMarkerReporterContract:
    """The marker is consumed by ``staging_rc_dryrun_report`` — prove it parses.

    A field-name or shape drift between the pin step and the reporter would
    otherwise be invisible until a live dry-run raced staging.
    """

    def test_collect_failures_reads_the_marker_as_no_failures(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "summary.json"
        _run(
            tmp_path,
            "--expected-sha",
            _SHA_A,
            "--actual-sha",
            _SHA_B,
            "--shard",
            "1/6",
            "--skip-summary-json",
            str(marker),
        )
        assert collect_failures([marker]) == []

    def test_reporter_end_to_end_reports_no_failures_for_a_skipped_shard(
        self, tmp_path: Path
    ) -> None:
        results = tmp_path / "dryrun-summaries" / "shard-1"
        results.mkdir(parents=True)
        _run(
            tmp_path,
            "--expected-sha",
            _SHA_A,
            "--actual-sha",
            _SHA_B,
            "--shard",
            "1/6",
            "--skip-summary-json",
            str(results / "summary.json"),
        )
        report_out = tmp_path / "report_output.txt"
        report_out.touch()
        rc = report_main(
            [
                "--results-dir",
                str(tmp_path / "dryrun-summaries"),
                "--sha",
                _SHA_A,
                "--github-output",
                str(report_out),
            ]
        )
        assert rc == 0
        # No `hydraflow-find` issue may be filed off a shard that never ran.
        assert _read_outputs(report_out)["has_failures"] == "false"

    def test_marker_matches_the_real_summary_payload_keys(self) -> None:
        from scripts.sandbox_scenario import _summary_payload

        real = _summary_payload([("s01_happy", 0, 1.0)], shard="1/6")
        marker = skip_marker_payload("1/6", _SHA_A, _SHA_B)
        assert set(real).issubset(set(marker))

    def test_a_marker_never_names_a_failing_scenario(self) -> None:
        marker = skip_marker_payload("1/6", _SHA_A, _SHA_B)
        assert marker["failed"] == []
        assert marker["scenarios"] == []


class TestResolveHeadSha:
    """The default ``--actual-sha`` comes from a real ``git rev-parse HEAD``."""

    def _make_repo(self, tmp_path: Path) -> str:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
        (tmp_path / "f.txt").write_text("hi\n")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init", "--no-verify"],
            cwd=tmp_path,
            check=True,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_resolves_head_of_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        head = self._make_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert resolve_head_sha() == head

    def test_missing_git_binary_resolves_to_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No `git` on PATH raises OSError rather than returning non-zero; an
        # uncaught one would crash the pin step *before* it writes `matched`,
        # leaving the gate output unset instead of an explicit refusal.
        empty_path = tmp_path / "empty-bin"
        empty_path.mkdir()
        monkeypatch.setenv("PATH", str(empty_path))
        assert resolve_head_sha() == ""

    def test_missing_git_binary_still_writes_a_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty_path = tmp_path / "empty-bin"
        empty_path.mkdir()
        monkeypatch.setenv("PATH", str(empty_path))
        rc, outputs = _run(tmp_path, "--expected-sha", _SHA_A)
        assert rc != 0
        assert outputs["matched"] == "false"

    def test_defaulted_actual_sha_matches_real_head(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        head = self._make_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "github_output.txt"
        out.touch()
        rc = main(["--expected-sha", head, "--github-output", str(out)])
        assert rc == 0
        assert _read_outputs(out)["matched"] == "true"

    def test_defaulted_actual_sha_detects_an_advanced_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._make_repo(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "github_output.txt"
        out.touch()
        rc = main(["--expected-sha", _SHA_A, "--github-output", str(out)])
        assert rc == 0
        assert _read_outputs(out)["matched"] == "false"

    def test_outside_a_git_repo_resolves_to_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bare = tmp_path / "not-a-repo"
        bare.mkdir()
        monkeypatch.chdir(bare)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        assert resolve_head_sha() == ""


class TestCommandLineEntrypoint:
    """The workflow calls ``python3 scripts/staging_rc_dryrun_pin.py`` directly.

    It runs *before* ``setup-python``, from the repo root, with no ``PYTHONPATH``
    — so the module must be runnable as a bare file path with stdlib only.
    """

    def test_module_main_guard_propagates_the_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Executes the `if __name__ == "__main__"` guard itself: a script whose
        # guard swallowed the return value would report success to the runner
        # even when the pin could not be verified.
        out = tmp_path / "github_output.txt"
        out.touch()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                str(PIN_SCRIPT),
                "--expected-sha",
                "",
                "--actual-sha",
                _SHA_A,
                "--github-output",
                str(out),
            ],
        )
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(PIN_SCRIPT), run_name="__main__")
        assert excinfo.value.code != 0
        assert _read_outputs(out)["matched"] == "false"

    def test_runs_as_a_bare_script_and_writes_matched_true(
        self, tmp_path: Path
    ) -> None:
        out = tmp_path / "github_output.txt"
        out.touch()
        proc = subprocess.run(
            [
                sys.executable,
                str(PIN_SCRIPT),
                "--expected-sha",
                _SHA_A,
                "--actual-sha",
                _SHA_A,
                "--github-output",
                str(out),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        assert proc.returncode == 0, proc.stderr
        assert _read_outputs(out)["matched"] == "true"

    def test_reads_github_output_from_the_environment(self, tmp_path: Path) -> None:
        out = tmp_path / "github_output.txt"
        out.touch()
        proc = subprocess.run(
            [
                sys.executable,
                str(PIN_SCRIPT),
                "--expected-sha",
                _SHA_A,
                "--actual-sha",
                _SHA_B,
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "GITHUB_OUTPUT": str(out),
            },
        )
        assert proc.returncode == 0, proc.stderr
        assert _read_outputs(out)["matched"] == "false"
