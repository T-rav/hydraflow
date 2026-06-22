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


def _run_launcher(workspace: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the launcher with a given HYDRAFLOW_FACTORY_WORKSPACE + cwd.

    Only used for cases where the in-place guard must FIRE — those exit before
    any clone / `make run`, so this never launches a server.
    """
    bash = shutil.which("bash")
    assert bash is not None
    env = {**os.environ, "HYDRAFLOW_FACTORY_WORKSPACE": workspace}
    return subprocess.run(
        [bash, str(SCRIPT)],
        check=False,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_guard_blocks_absolute_dev_root() -> None:
    # Pointing the workspace at the dev checkout (absolute) must abort before
    # the destructive `git reset --hard`.
    result = _run_launcher(str(REPO_ROOT), cwd=REPO_ROOT)
    assert result.returncode != 0
    assert "dev checkout" in result.stderr


def test_guard_blocks_relative_dot_alias() -> None:
    # The data-loss bug the adversarial review caught: a RELATIVE workspace
    # ('.') resolving to the dev checkout must still be refused — the guard
    # canonicalizes before comparing.
    result = _run_launcher(".", cwd=REPO_ROOT)
    assert result.returncode != 0
    assert "dev checkout" in result.stderr


def test_guard_canonicalizes_before_comparing() -> None:
    # The script must resolve the workspace path before the guard, not compare
    # a raw (possibly relative) string.
    text = SCRIPT.read_text()
    assert "pwd -P" in text, "workspace path must be canonicalized before the guard"


def test_makefile_wires_the_factory_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "\nfactory:" in makefile, "Makefile is missing the `factory` target"
    assert "run-factory-isolated.sh" in makefile
    assert ".PHONY: help run dev factory" in makefile, (
        "`factory` must be declared .PHONY"
    )
