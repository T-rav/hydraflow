"""setuptools shim: enumerate the flat ``src/*.py`` modules for the wheel (#11580).

Everything static lives in ``pyproject.toml``. This file exists for one thing
``pyproject.toml`` cannot express: HydraFlow keeps ~340 top-level modules
directly under ``src/`` (the ``PYTHONPATH=src`` flat-module convention, see
CLAUDE.md), and ``[tool.setuptools.packages.find]`` discovers *packages* only.
``py-modules`` must be a literal list — listing the modules by hand would put
every new-module PR in merge-conflict range — so they are globbed here at build
time. The ``__main__`` guard keeps the module importable for the architecture
guard (``tests/architecture/test_wheel_console_script.py``) without running
``setup()``; setuptools' build backend executes this file as ``__main__``.
"""

from __future__ import annotations

from pathlib import Path

from setuptools import setup

SRC = Path(__file__).resolve().parent / "src"


def flat_modules(src: Path = SRC) -> list[str]:
    """Top-level importable modules under ``src/`` (``src/foo.py`` -> ``foo``).

    ``src/__init__.py`` is excluded: it is the checkout's package marker (it
    makes the ``src.`` alias importable from the repo root), not a module the
    wheel should ship as a top-level ``__init__``.
    """
    return sorted(
        path.stem
        for path in src.glob("*.py")
        if path.stem != "__init__" and path.stem.isidentifier()
    )


if __name__ == "__main__":
    setup(py_modules=flat_modules())
