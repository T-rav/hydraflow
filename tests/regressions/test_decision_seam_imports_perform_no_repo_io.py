"""Regression: importing the decision seam reads no repo file (epic #11752).

`tests/architecture/test_policy_engine_is_pure.py` pins, per source, exactly
which symbols may be imported — and states its own limit plainly: *"it does
not constrain the transitive import graph"*. That limit is not theoretical.
The pure seam grew a dependency on `charter_model`, and the cheap way to
satisfy the pin was to add the name to an allow-list, which would have let a
pure module import something nothing held pure — moving the hole down a level
instead of closing it.

The pin is a check on SPELLING. This is the check on BEHAVIOUR: import the
seam under `sys.addaudithook` and assert nothing opens a file inside the
repository while it happens. A future dependency that reads `charter.yaml`,
a standards directory or a ledger at import time fails here no matter how its
import is spelled, and no matter which allow-list was widened to admit it.

Scoped to DATA files inside the repo: Python's own import machinery opens
site-packages, stdlib, `.py` sources and `.pyc` caches, and failing on those
would make this a test of CPython rather than of HydraFlow. What must never
happen is the seam opening `charter.yaml`, a standards directory, a ledger or
a config file while it is being imported.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = """
import sys
from pathlib import Path

REPO = Path({repo!r}).resolve()
violations = []


def _hook(event, args):
    if event != "open":
        return
    path = args[0]
    if not isinstance(path, str):
        return
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return
    if not resolved.is_relative_to(REPO):
        return
    if ".venv" in resolved.parts or "site-packages" in resolved.parts:
        return
    # Python's own import machinery reads .py sources and writes/reads .pyc
    # caches; flagging those would make this a test of CPython. What must
    # never happen is the seam opening DATA at import: charter.yaml, a
    # standards directory, a ledger, a config file.
    if resolved.suffix in {{".py", ".pyc"}} or "__pycache__" in resolved.parts:
        return
    # Editable-install metadata, read by the import system itself. Same class
    # as site-packages: it describes how the package is installed, not what
    # HydraFlow decided to read.
    if any(part.endswith(".egg-info") for part in resolved.parts):
        return
    violations.append(str(resolved.relative_to(REPO)))


sys.path.insert(0, str(REPO / "src"))
sys.addaudithook(_hook)

import policy.models  # noqa: F401
import policy.python_engine  # noqa: F401

# Proof the hook is live: this read MUST be seen, or a silent hook would make
# the whole test vacuous.
canary = REPO / "pyproject.toml"
with canary.open("rb"):
    pass
if "pyproject.toml" not in violations:
    print("HOOK-DEAD")
    raise SystemExit(2)
violations.remove("pyproject.toml")

print("VIOLATIONS:" + ",".join(sorted(set(violations))))
"""


def test_importing_the_decision_seam_opens_no_repo_file() -> None:
    probe = _PROBE.format(repo=str(REPO_ROOT))
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
        check=False,
    )
    assert "HOOK-DEAD" not in result.stdout, (
        "the audit hook never observed its own canary read, so this test "
        "would pass against any import graph:\n" + result.stdout + result.stderr
    )
    assert result.returncode == 0, (
        f"probe failed (rc={result.returncode}):\n{result.stdout}\n{result.stderr}"
    )

    line = next(
        (ln for ln in result.stdout.splitlines() if ln.startswith("VIOLATIONS:")), None
    )
    assert line is not None, (
        f"probe produced no verdict:\n{result.stdout}{result.stderr}"
    )
    opened = [p for p in line[len("VIOLATIONS:") :].split(",") if p]
    assert not opened, (
        "importing the decision seam opened repo files — the transitive import "
        "graph now reaches the world, which the per-source import pin cannot "
        "see:\n  " + "\n  ".join(opened)
    )
