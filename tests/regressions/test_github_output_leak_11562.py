"""Regression pin: the runner's ``$GITHUB_OUTPUT`` never reaches tests (#11562).

Three CLI scripts default ``--github-output``/``--out`` to
``os.environ.get("GITHUB_OUTPUT")``. GitHub Actions always sets that variable,
so a test calling ``main()`` in-process WITHOUT the flag inherited the runner's
real step-output file: the verdict landed in the file instead of stdout
(``test_missing_output_path_does_not_crash`` was the only red check on PR
#11560 for three attempts, green on every laptop) and the test payloads were
appended to the job's real outputs.

The fix scrubs ``GITHUB_OUTPUT`` in ``tests/conftest.py::setup_test_environment``
for the whole session. This pin reproduces the runner's shape — a FRESH pytest
process whose environment carries ``GITHUB_OUTPUT`` pointing at a probe file —
runs the real CLI test modules inside it, and asserts they pass AND the probe
stays empty. It cannot be an in-process test: the session scrub has already
removed the variable by the time any test body runs.

Cost: the nested session collects ~20 small CLI tests and its CALL phase is
~2s locally — far inside the 60s duration ratchet in ``tests/conftest.py``.
CI runs ``tests/regressions`` in the serial pytest leg (``ci.yml``), outside
the ``-n auto`` bulk, so runner contention does not stack on top of it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every test module that calls a GITHUB_OUTPUT-defaulting CLI ``main()``
# in-process (the #11562 site roster).
_CLI_TEST_TARGETS = (
    "tests/test_classify_smoke_log_cli.py",
    "tests/test_staging_rc_dryrun_pin.py::TestGithubOutput",
    "tests/test_staging_rc_dryrun_report.py",
)


def test_runner_github_output_never_reaches_in_process_cli_mains(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "github_output"
    probe.touch()
    # Drop the outer session's pytest bookkeeping (xdist worker ids, current
    # test) so the nested run is a plain single-process session.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["GITHUB_OUTPUT"] = str(probe)

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *_CLI_TEST_TARGETS],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    tail = proc.stdout[-4000:] + proc.stderr[-2000:]
    assert proc.returncode == 0, tail
    passed = re.search(r"(\d+) passed", proc.stdout)
    assert passed is not None and int(passed.group(1)) >= 5, tail
    assert probe.read_text(encoding="utf-8") == "", (
        "an in-process CLI main() wrote into the runner's $GITHUB_OUTPUT:\n"
        + probe.read_text(encoding="utf-8")
    )
