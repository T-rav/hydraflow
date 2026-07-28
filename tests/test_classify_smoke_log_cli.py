"""Wire-up tests for the ``scripts/classify_smoke_log.py`` CLI seam (#10776).

The post-merge-smoke workflow consumes the classifier through this CLI (the
recursion guard forbids the factory from editing ``.github/workflows/``, so
the workflow shells out to this script rather than embedding the logic). These
tests pin the contract that seam exposes: JSON on stdout + GitHub Actions
``name=value`` output pairs on ``--out``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_PATH = _REPO_ROOT / "scripts" / "classify_smoke_log.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("classify_smoke_log", _CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NODESOURCE_403_LOG = (
    "#8 12.34 NodeSource fetch attempt 1 failed (CDN 403/5xx); retrying in 5s\n"
    "#8 25.44 W: Failed to fetch https://deb.nodesource.com/node_20.x 403 Forbidden\n"
)

GENUINE_TEST_FAILURE_LOG = (
    "FAILED tests/test_orchestrator.py::test_loop_starts - AssertionError\n"
    "make: *** [Makefile:88: post-merge-smoke] Error 1\n"
)


class TestClassifySmokeLogCli:
    def test_infra_flake_first_run_emits_retry(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli = _load_cli()
        log = tmp_path / "smoke.log"
        log.write_text(NODESOURCE_403_LOG, encoding="utf-8")

        rc = cli.main(["--log", str(log), "--prior-attempts", "0"])

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] == "retry"
        assert payload["signature_id"] == "nodesource-cdn-403"

    def test_infra_flake_recurrence_emits_targeted_and_writes_github_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli = _load_cli()
        log = tmp_path / "smoke.log"
        log.write_text(NODESOURCE_403_LOG, encoding="utf-8")
        out = tmp_path / "gh_output"

        rc = cli.main(
            [
                "--log",
                str(log),
                "--prior-attempts",
                "1",
                "--ref-name",
                "staging",
                "--sha",
                "abc123",
                "--run-url",
                "https://ci/run/1",
                "--out",
                str(out),
            ]
        )

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] == "file_targeted"
        assert "NodeSource" in payload["issue_title"]

        # GitHub Actions output file carries the branchable action + a heredoc
        # for the multi-line issue body.
        written = out.read_text(encoding="utf-8")
        assert "action=file_targeted" in written
        assert "issue_body<<" in written  # multi-line heredoc form
        assert "abc123" in written

    def test_real_red_emits_file_generic(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli = _load_cli()
        log = tmp_path / "smoke.log"
        log.write_text(GENUINE_TEST_FAILURE_LOG, encoding="utf-8")

        rc = cli.main(["--log", str(log), "--prior-attempts", "0"])

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] == "file_generic"
        assert payload["signature_id"] is None  # JSON stdout keeps None

    def test_prior_attempts_defaults_from_env(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cli = _load_cli()
        log = tmp_path / "smoke.log"
        log.write_text(NODESOURCE_403_LOG, encoding="utf-8")
        monkeypatch.setenv("SMOKE_PRIOR_ATTEMPTS", "1")

        rc = cli.main(["--log", str(log)])

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        # With one prior attempt already recorded, the retry budget is spent.
        assert payload["action"] == "file_targeted"
