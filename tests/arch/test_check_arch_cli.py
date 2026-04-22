from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_arch.py"


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_rules_prints_skipped_and_exits_zero(tmp_path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIPPED" in (r.stdout + r.stderr)


def test_with_violations_exits_one_and_prints_human_report(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "low.py").write_text("import high\n")
    (tmp_path / "src" / "high.py").write_text("x = 1\n")
    (tmp_path / ".hydraflow").mkdir()
    (tmp_path / ".hydraflow" / "arch_rules.py").write_text(
        "from hydraflow.arch import LayerMap, Allowlist, python_ast_extractor\n"
        "EXTRACTOR = python_ast_extractor\n"
        "LAYERS = LayerMap({'src/low.py': 1, 'src/high.py': 2})\n"
        "ALLOWLIST = Allowlist({})\n"
        "FITNESS = []\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "src/low.py" in r.stdout
    assert "layer" in r.stdout
