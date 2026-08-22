"""Regression for #11589: repo-root resources resolve from an installed wheel.

#11580 made the wheel importable. It did not make it *runnable*: eight modules
located ``prompts/``, ``templates/``, ``static/`` and friends with
``Path(__file__).resolve().parent.parent``, which names ``<repo>`` from
``<repo>/src/mod.py`` and ``lib/python3.11/`` from ``site-packages/mod.py``. So
``preflight.runner`` read prompts from a directory that does not exist in any
wheel install — and, for the same reason, from inside the agent image until
``prompts/`` was copied in by hand.

The trees now live under ``src/hydraflow_resources/`` and ship as package data,
resolved through ``package_resources``. Unit tests cannot see this class: they
import from the checkout, where the wrong expression happened to be right. So
this builds the real wheel and resolves the resources **from the unpacked wheel
only** — ``python -S`` (the dev venv's editable ``.pth`` would put ``src/`` back
on ``sys.path`` and mask everything) with the cwd outside the repository.

The static counterpart is ``tests/architecture/test_wheel_console_script.py``;
the console-script counterpart is ``tests/regressions/test_issue_11580.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

_COPY_IGNORE = shutil.ignore_patterns(
    "ui", "*.egg-info", "__pycache__", "node_modules", "*.pyc"
)


def _clean_env(home: Path, pythonpath: str | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HYDRAFLOW_SENTRY_DISABLED": "1",
    }
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    return env


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the wheel from a scratch copy of pyproject + setup.py + src/."""
    proj = tmp_path_factory.mktemp("proj")
    for name in ("pyproject.toml", "setup.py"):
        shutil.copy(REPO_ROOT / name, proj / name)
    shutil.copytree(SRC, proj / "src", ignore=_COPY_IGNORE)
    out = tmp_path_factory.mktemp("dist")
    code = (
        "import sys; from setuptools import build_meta; "
        "print(build_meta.build_wheel(sys.argv[1]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(out)],
        cwd=proj,
        env=_clean_env(tmp_path_factory.mktemp("home")),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, f"wheel build failed:\n{result.stderr[-4000:]}"
    wheel = out / result.stdout.strip().splitlines()[-1]
    assert wheel.is_file(), f"build reported {wheel} but it does not exist"
    return wheel


@pytest.fixture(scope="module")
def unpacked_wheel(built_wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    site = tmp_path_factory.mktemp("site")
    with zipfile.ZipFile(built_wheel) as zf:
        zf.extractall(site)
    return site


def _run_from_wheel(site: Path, code: str, *, home: Path) -> subprocess.CompletedProcess[str]:
    """Run *code* against the unpacked wheel + the venv's third-party deps only."""
    scratch = home / "cwd"
    scratch.mkdir(exist_ok=True)
    pythonpath = os.pathsep.join([str(site), sysconfig.get_paths()["purelib"]])
    return subprocess.run(
        [sys.executable, "-S", "-c", textwrap.dedent(code)],
        cwd=scratch,
        env=_clean_env(home, pythonpath),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_wheel_ships_the_runtime_resource_trees(built_wheel: Path) -> None:
    """Every declared resource file is in the wheel, under its package."""
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    on_disk = {
        f"hydraflow_resources/{p.relative_to(SRC / 'hydraflow_resources').as_posix()}"
        for p in (SRC / "hydraflow_resources").rglob("*")
        if p.is_file()
    }
    missing = sorted(on_disk - names)
    assert missing == [], (
        f"resource files declared as package data but absent from the wheel: "
        f"{missing}"
    )


def test_auto_agent_prompt_renders_from_the_installed_wheel(
    unpacked_wheel: Path, tmp_path: Path
) -> None:
    """``preflight.runner`` finds its prompts with no checkout in sight (#11589)."""
    result = _run_from_wheel(
        unpacked_wheel,
        """
        from preflight.runner import render_prompt
        text = render_prompt(
            sub_label="triage-stuck",
            persona="engineer",
            issue_number=11589,
            repo_slug="T-rav/hydraflow",
            worktree_path="/tmp/wt",
            issue_body="body",
            issue_comments_block="",
            escalation_context_block="",
            wiki_excerpts_block="",
            sentry_events_block="",
            recent_commits_block="",
            prior_attempts_block="",
        )
        print("RENDERED", len(text), "11589" in text)
        """,
        home=tmp_path,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert result.stdout.split()[-1] == "True", result.stdout


def test_dashboard_template_resolves_from_the_installed_wheel(
    unpacked_wheel: Path, tmp_path: Path
) -> None:
    """The dashboard's fallback HTML + JS are found beside the installed modules."""
    result = _run_from_wheel(
        unpacked_wheel,
        """
        import dashboard
        html = (dashboard._TEMPLATE_DIR / "index.html").read_text()
        js = (dashboard._STATIC_DIR / "dashboard.js").read_text()
        print("OK", bool(html.strip()) and bool(js.strip()))
        """,
        home=tmp_path,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert result.stdout.strip() == "OK True", result.stdout


def test_resource_lookup_from_the_wheel_never_points_at_site_packages_root(
    unpacked_wheel: Path, tmp_path: Path
) -> None:
    """The resolved directory is inside the wheel, not the old walk-up target."""
    result = _run_from_wheel(
        unpacked_wheel,
        """
        from package_resources import resource_dir
        print(resource_dir("prompts"))
        """,
        home=tmp_path,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert result.stdout.strip() == str(
        unpacked_wheel / "hydraflow_resources" / "prompts"
    )


def test_checkout_only_resources_fail_loudly_from_the_wheel(
    unpacked_wheel: Path, tmp_path: Path
) -> None:
    """``scripts/`` is not in the wheel, and asking for it says so by name."""
    result = _run_from_wheel(
        unpacked_wheel,
        """
        from package_resources import ResourceNotFoundError, checkout_path
        try:
            checkout_path("scripts", "audit_prompts.py")
        except ResourceNotFoundError as exc:
            print("RAISED", "scripts/audit_prompts.py" in str(exc))
        """,
        home=tmp_path,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert result.stdout.strip() == "RAISED True", result.stdout
