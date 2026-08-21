"""Regression for #11580: the wheel installs a working ``hydraflow`` console script.

``uv pip install git+https://github.com/T-rav/hydraflow@<ref>`` produced a wheel
holding the ``src/`` sub-packages and none of the ~340 flat modules
(``server.py``, ``config.py``, ...), so ``[project.scripts] hydraflow =
"server:main"`` failed at import in every clean venv.

This builds the real wheel with the venv's own setuptools (no network, no
``uv build`` isolation) from a scratch copy of the project, then:

* asserts every flat module and ``assets/model_pricing.json`` are in the wheel
  (and the UI source tree / templates / ``src/__init__.py`` are not);
* resolves every ``console_scripts`` entry point and runs
  ``hydraflow --version`` / ``--help`` **from the unpacked wheel only**:
  ``python -S`` so the dev venv's editable ``.pth`` (which puts ``src/`` back
  on ``sys.path`` and would mask the bug) is never processed; third-party
  dependencies come from the venv's site-packages through ``PYTHONPATH``.

One module-scoped build (a few seconds) is shared by the tests below. The
static counterpart (no build) is ``tests/architecture/test_wheel_console_script.py``.
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

# The UI tree (node_modules, vite sources) is ~8 MB and never part of the
# wheel; the egg-info / bytecode are build residue from the editable install.
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
def unpacked_wheel(
    built_wheel: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    site = tmp_path_factory.mktemp("site")
    with zipfile.ZipFile(built_wheel) as zf:
        zf.extractall(site)
    return site


def _wheel_names(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as zf:
        return set(zf.namelist())


def _console_scripts(site: Path) -> dict[str, str]:
    dist_info = next(site.glob("hydraflow-*.dist-info"))
    parser = configparser.ConfigParser()
    parser.read(dist_info / "entry_points.txt")
    return dict(parser["console_scripts"])


def _run_from_wheel(site: Path, code: str, *args: str, home: Path) -> subprocess.CompletedProcess[str]:
    """Run ``code`` with ONLY the unpacked wheel + the venv's third-party deps.

    ``-S`` skips site initialisation, so the editable ``.pth`` that maps
    ``hydraflow`` onto the checkout's ``src/`` never runs; the wheel directory
    is first on ``PYTHONPATH`` and the cwd is an empty directory.
    """
    scratch = home / "cwd"
    scratch.mkdir(exist_ok=True)
    pythonpath = os.pathsep.join([str(site), sysconfig.get_paths()["purelib"]])
    return subprocess.run(
        [sys.executable, "-S", "-c", code, *args],
        cwd=scratch,
        env=_clean_env(home, pythonpath),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_wheel_ships_flat_modules_and_runtime_assets(built_wheel: Path) -> None:
    names = _wheel_names(built_wheel)
    expected_flat = {f"{p.stem}.py" for p in SRC.glob("*.py")} - {"__init__.py"}
    missing = sorted(expected_flat - names)
    assert missing == [], f"flat src/ modules absent from the wheel: {missing}"
    assert "server.py" in names
    assert "config.py" in names
    assert "assets/model_pricing.json" in names, "model_pricing.py reads this file"
    assert "hydraflow_gateway/__main__.py" in names
    # src/__init__.py only exists to make the checkout's ``src.`` alias
    # importable from the repo root; a top-level ``__init__`` module is wrong.
    assert "__init__.py" not in names
    leaked = sorted(n for n in names if n.startswith(("ui/", "templates/", "tests/")))
    assert leaked == [], f"excluded trees leaked into the wheel: {leaked[:5]}"


def test_console_script_entry_points_resolve_from_the_wheel(
    unpacked_wheel: Path, tmp_path: Path
) -> None:
    scripts = _console_scripts(unpacked_wheel)
    assert scripts.get("hydraflow") == "server:main"
    probe = textwrap.dedent(
        """
        import importlib, sys
        for target in sys.argv[1:]:
            module, _, attr = target.partition(":")
            mod = importlib.import_module(module)
            assert callable(getattr(mod, attr)), target
            print(f"{target} -> {mod.__file__}")
        """
    )
    result = _run_from_wheel(unpacked_wheel, probe, *scripts.values(), home=tmp_path)
    assert result.returncode == 0, (
        f"console script target failed to import from the wheel:\n{result.stderr[-4000:]}"
    )
    for line in result.stdout.strip().splitlines():
        target, _, origin = line.partition(" -> ")
        assert origin.startswith(str(unpacked_wheel)), (
            f"{target} resolved outside the wheel ({origin}) — the probe leaked "
            "the checkout's src/ onto sys.path, so it proves nothing"
        )


def test_hydraflow_version_and_help_run_without_booting_the_server(
    unpacked_wheel: Path, tmp_path: Path
) -> None:
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))[
        "project"
    ]["version"]
    result = _run_from_wheel(
        unpacked_wheel, "import server; server.main(['--version'])", home=tmp_path
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == f"hydraflow {version}"

    result = _run_from_wheel(
        unpacked_wheel, "import server; server.main(['--help'])", home=tmp_path
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.startswith("usage: hydraflow")
