"""Isolation contract for implicit ``ConfigFactory`` filesystem roots."""

from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import helpers
from tests.helpers import ConfigFactory

_FORKED_PROBE_PATH_ENV = "CONFIG_FACTORY_FORKED_PROBE_PATH"


def test_implicit_roots_are_unique_and_self_contained() -> None:
    first = ConfigFactory.create()
    second = ConfigFactory.create()

    assert first.repo_root != second.repo_root
    assert first.repo_root.name.startswith(
        f"{helpers._CONFIG_FACTORY_TEMP_ROOT_PREFIX}{os.getpid()}-"
    )
    assert second.repo_root.name.startswith(
        f"{helpers._CONFIG_FACTORY_TEMP_ROOT_PREFIX}{os.getpid()}-"
    )
    assert first.workspace_base == first.repo_root / "test-worktrees"
    assert second.workspace_base == second.repo_root / "test-worktrees"
    assert first.cost_inferences_path.is_relative_to(first.repo_root)
    assert second.cost_inferences_path.is_relative_to(second.repo_root)
    assert first.repo_root != Path("/tmp/hydraflow-test-repo").resolve()
    assert second.repo_root != Path("/tmp/hydraflow-test-repo").resolve()


def test_explicit_root_preserves_existing_workspace_semantics(tmp_path: Path) -> None:
    explicit_root = tmp_path / "repo"
    before = set(helpers._CONFIG_FACTORY_TEMP_ROOTS.get(os.getpid(), set()))

    config = ConfigFactory.create(repo_root=explicit_root)

    assert config.repo_root == explicit_root.resolve()
    assert config.workspace_base == (explicit_root.parent / "test-worktrees").resolve()
    assert set(helpers._CONFIG_FACTORY_TEMP_ROOTS.get(os.getpid(), set())) == before


def test_cleanup_removes_only_current_process_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_pid = os.getpid()
    owned = tmp_path / "owned"
    foreign = tmp_path / "foreign"
    owned.mkdir()
    foreign.mkdir()
    registry = {owner_pid: {owned}, owner_pid + 1: {foreign}}
    monkeypatch.setattr(helpers, "_CONFIG_FACTORY_TEMP_ROOTS", registry)

    helpers._cleanup_owned_config_factory_temp_roots()

    assert not owned.exists()
    assert foreign.is_dir()
    assert registry == {owner_pid + 1: {foreign}}


def test_model_copy_keeps_implicit_root_alive() -> None:
    original = ConfigFactory.create()
    copied = original.model_copy()
    root = copied.repo_root

    del original
    gc.collect()

    assert root.is_dir()
    assert copied.workspace_base == root / "test-worktrees"


def test_implicit_roots_are_isolated_and_cleaned_across_xdist_processes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = """
import json
import os
from tests.helpers import ConfigFactory

config = ConfigFactory.create()
print(json.dumps({
    "exists": config.repo_root.is_dir(),
    "pid": os.getpid(),
    "repo_root": str(config.repo_root),
    "worker": os.environ["PYTEST_XDIST_WORKER"],
}))
"""
    payloads: list[dict[str, object]] = []
    for worker in ("gw0", "gw1"):
        env = os.environ.copy()
        env["PYTEST_XDIST_WORKER"] = worker
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (
                str(repo_root / "src"),
                str(repo_root),
                env.get("PYTHONPATH", ""),
            )
            if part
        )
        completed = subprocess.run(  # noqa: S603 - fixed local interpreter/script
            [sys.executable, "-c", script],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payloads.append(json.loads(completed.stdout.strip().splitlines()[-1]))

    roots = [Path(str(payload["repo_root"])) for payload in payloads]
    assert [payload["worker"] for payload in payloads] == ["gw0", "gw1"]
    assert all(payload["exists"] is True for payload in payloads)
    assert roots[0] != roots[1]
    assert all(not root.exists() for root in roots)


def test_forked_cleanup_probe() -> None:
    """Create a root inside the real pytest-forked child for the parent probe."""

    config = ConfigFactory.create()
    marker_path = os.environ.get(_FORKED_PROBE_PATH_ENV)
    if marker_path is not None:
        Path(marker_path).write_text(str(config.repo_root), encoding="utf-8")

    assert config.repo_root.is_dir()


def test_pytest_forked_child_cleans_implicit_root(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    marker_path = tmp_path / "forked-root.txt"
    env = os.environ.copy()
    env[_FORKED_PROBE_PATH_ENV] = str(marker_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(repo_root / "src"),
            str(repo_root),
            env.get("PYTHONPATH", ""),
        )
        if part
    )

    subprocess.run(  # noqa: S603 - fixed local interpreter/test node
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--forked",
            f"{__file__}::test_forked_cleanup_probe",
        ],
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    forked_root = Path(marker_path.read_text(encoding="utf-8"))
    assert not forked_root.exists()
