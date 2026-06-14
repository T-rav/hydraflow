"""The `make factory` isolated-workspace launcher must stay wired and valid.

Running the factory from a dedicated clone (instead of the dev checkout) is how
we keep the developer's working tree clean — the factory mutates its repo_root as
it runs. This guards the launcher script + Makefile wiring so the escape hatch
can't silently rot.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run-factory-isolated.sh"


def test_launcher_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file(), "scripts/run-factory-isolated.sh is missing"
    assert os.access(SCRIPT, os.X_OK), (
        "scripts/run-factory-isolated.sh must be executable (chmod +x)"
    )


def test_launcher_script_passes_bash_syntax_check() -> None:
    bash = shutil.which("bash")
    if bash is None:
        return  # no bash on this runner — skip rather than false-fail
    result = subprocess.run(
        [bash, "-n", str(SCRIPT)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"


def test_launcher_refuses_to_run_in_place() -> None:
    # The in-place guard (workspace == current checkout) is what stops the
    # script from dirtying the dev checkout it was meant to protect.
    text = SCRIPT.read_text()
    assert "is the current checkout" in text


def test_makefile_wires_the_factory_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "\nfactory:" in makefile, "Makefile is missing the `factory` target"
    assert "run-factory-isolated.sh" in makefile
    assert ".PHONY: help run dev factory" in makefile, (
        "`factory` must be declared .PHONY"
    )
