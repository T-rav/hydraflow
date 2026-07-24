"""Regression for #10403: erosion scatter must only count TOP-LEVEL symbols.

The scatter sensor flagged ``append`` as "scattered across 4 modules" — but that
was just four classes each with a ``def append(self, ...)`` METHOD (common
interface, not concept scatter). The ``_DEF_RE``/``_CLASS_RE`` regexes matched
indented method/nested-class defs (a documented v1 simplification), turning
common method names into false-positive findings that then churned to HITL.

Fix: require column-0 (module-level) def/class/constant. A concept is a
module-level function/class/constant independently reinvented across modules;
a method named ``append`` is not. Genuine module-level scatter (e.g. a
duplicated ``_GIT_TIMEOUT_S`` constant) still flags.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from erosion.scatter import added_symbols_for_range


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def test_indented_method_and_nested_class_are_not_extracted(tmp_path: Path) -> None:
    """#10403: `def append` method + nested class must NOT count (they were the FP)."""
    _init_repo(tmp_path)
    (tmp_path / "ledger.py").write_text("class Base:\n    pass\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)

    (tmp_path / "ledger.py").write_text(
        "class Base:\n"
        "    def append(self, record):\n"
        "        return record\n"
        "    class Inner:\n"
        "        pass\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add method"], cwd=tmp_path, check=True
    )

    added = added_symbols_for_range(tmp_path, "HEAD~1..HEAD")

    assert added is not None
    # Neither the `append` method nor the nested `Inner` class is concept scatter.
    assert added.get("ledger.py", []) == []


def test_toplevel_def_class_constant_are_still_extracted(tmp_path: Path) -> None:
    """Real signal preserved: module-level function/class/constant still flag."""
    _init_repo(tmp_path)
    (tmp_path / "m.py").write_text("X = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)

    (tmp_path / "m.py").write_text(
        "X = 1\n\n\n"
        "def parse_config():\n    pass\n\n\n"
        "class TrendStore:\n    pass\n\n\n"
        "_GIT_TIMEOUT_S = 30\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=tmp_path, check=True)

    added = added_symbols_for_range(tmp_path, "HEAD~1..HEAD")

    assert added is not None
    assert set(added["m.py"]) == {"parse_config", "TrendStore", "_GIT_TIMEOUT_S"}
