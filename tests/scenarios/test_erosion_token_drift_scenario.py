"""MockWorld scenario for ErosionMetricsLoop's token-drift filing actuator (#11442).

End-to-end over FakeGitHub + a real (tiny) git repo on disk + a real
``DedupStore`` + real ``inferences.jsonl`` telemetry under the loop's own
config, one layer up from ``tests/test_erosion_metrics_loop_token_drift.py``:
proves the third whole-repo candidate kind rides the REGULAR
``_file_findings`` path into the real ``FakeGitHub.create_issue`` port and
dedups per (source, ISO week) across ticks.

* eight steady baseline weeks pinned via ``token_drift.pin_baseline`` + one
  trailing complete week where ``implementer``'s share breaches the band →
  tick 1 files exactly one ``hydraflow-find`` issue, titled with the
  engine-computed before/after shares and sigma;
* new commit, same week, same telemetry → tick 2 files nothing;
* late-arriving rows push ``planner`` over the band in the same week → tick 3
  files a second, separate issue — the dedup key is per source, not per week.

Sandbox e2e is N/A for this slice: no docker, UI, or subprocess surface —
the only external edge is ``PRPort.create_issue``, which this scenario
drives through the real fake.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dedup_store import DedupStore
from erosion.token_drift_filing import token_drift_fingerprint
from tests.scenarios.fakes.mock_world import MockWorld
from tests.test_erosion_metrics_loop_token_drift import (
    seed_second_drifting_source,
    seed_token_drift,
)

pytestmark = pytest.mark.scenario_loops


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "drift_repo"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _commit_file(repo: Path, name: str) -> None:
    (repo / "src" / name).write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")


def _make_state(initial_sha: str) -> Any:
    from unittest.mock import MagicMock

    state = MagicMock()
    cursor = {"sha": initial_sha}
    state.get_erosion_last_processed_sha.side_effect = lambda: cursor["sha"]
    state.set_erosion_last_processed_sha.side_effect = lambda sha: cursor.update(
        sha=sha
    )
    return state


def _build_loop(
    tmp_path: Path, repo: Path, github: Any, state: Any, dedup: DedupStore
) -> Any:
    from erosion_metrics_loop import ErosionMetricsLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)
    return ErosionMetricsLoop(
        config=bg.config,
        pr_manager=github,
        state=state,
        dedup=dedup,
        deps=bg.loop_deps,
    )


class TestErosionTokenDriftScenario:
    async def test_files_once_per_source_per_week_through_fake_github(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)
        github = world.github
        repo = _init_repo(tmp_path)
        base_sha = _head(repo)
        _commit_file(repo, "a.py")
        dedup = DedupStore(
            "erosion_metrics_filed_findings",
            tmp_path / "dedup" / "erosion_metrics_filed.json",
        )
        loop = _build_loop(tmp_path, repo, github, _make_state(base_sha), dedup)
        now = datetime.now(UTC)
        window_key = seed_token_drift(loop._config, now=now)
        implementer_key = token_drift_fingerprint("implementer", window_key)
        planner_key = token_drift_fingerprint("planner", window_key)

        # Tick 1: implementer's share breaches the band → exactly one issue.
        first = await loop._do_work()
        assert first["status"] == "ok"
        assert first["filed"] == 1
        assert first["token_drift"] == {
            "window_key": window_key,
            "drifting": ["implementer"],
        }
        assert len(github._issues) == 1
        issue = next(iter(github._issues.values()))
        assert issue.title == (
            f"Token drift: `implementer` share 41.0% → 60.0% (10.7σ) "
            f"in week {window_key}"
        )
        assert {"hydraflow-find", "erosion-metrics"} <= set(issue.labels)
        assert "| observed | 60.0% |" in issue.body
        assert f"| ISO week | {window_key} |" in issue.body
        assert dedup.get() == {implementer_key}

        # Tick 2: new commit, same week, same telemetry → nothing new.
        _commit_file(repo, "b.py")
        second = await loop._do_work()
        assert second["filed"] == 0
        assert len(github._issues) == 1

        # Tick 3: late-arriving rows push planner over the band too → the
        # second source files its own issue; implementer stays deduped.
        seed_second_drifting_source(loop._config, now=now)
        _commit_file(repo, "c.py")
        third = await loop._do_work()
        assert third["filed"] == 1
        assert third["token_drift"]["drifting"] == ["implementer", "planner"]
        assert len(github._issues) == 2
        titles = sorted(i.title for i in github._issues.values())
        assert sum("`planner` share" in t for t in titles) == 1
        assert sum("`implementer` share" in t for t in titles) == 1
        assert dedup.get() == {implementer_key, planner_key}
