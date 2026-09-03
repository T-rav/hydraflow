"""#12117: the duplicate-infra guard must say when it could not look.

`hf.check-existing-infra-before-new-file.sh` scans `git ls-files` for siblings
sharing a new file's name tokens. Outside a git repo that returns nothing,
`CANDIDATES` is empty, and the hook allowed — reporting a clean bill of health
for a check it never performed.

Measured before the fix:

    CLAUDE_PROJECT_DIR = a real repo   -> exit 2 (refuses)
    CLAUDE_PROJECT_DIR = not a repo    -> exit 0 (allows, SILENTLY)

That is how the issue was reported as "staging red": a tree extracted with
`git archive` carries no `.git`, so every BLOCK case failed and every ALLOW
case passed.

Fail-open stays — an unwritable /tmp must never wedge an unattended run — but
this one path is now audible, because it is the only one where the guard's
entire subject was unreadable rather than merely empty.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_HOOK = _REPO / ".claude" / "hooks" / "hf.check-existing-infra-before-new-file.sh"


def _run(project_dir: Path, target: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"file_path": str(project_dir / target)}})
    return subprocess.run(
        ["bash", str(_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(project_dir),
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "HF_HOOK_MARKER_DIR": tempfile.mkdtemp(),
        },
    )


def test_outside_a_repo_the_guard_says_it_could_not_scan() -> None:
    """The silent-allow that made the guard look healthy while inert."""
    done = _run(Path(tempfile.mkdtemp()), "tests/test_event_reducer_coverage.py")

    assert done.returncode == 0, "must still allow — wedging a run is worse"
    assert "not a git repository" in done.stderr, (
        "the guard allowed without saying it could not look, so 'nothing "
        "matched' and 'I could not scan' remain the same answer (#12117)"
    )


def test_inside_a_repo_it_still_refuses_a_duplicate() -> None:
    """The decoy: without it, the assertion above passes against a hook that
    allows everything everywhere and merely prints a warning."""
    done = _run(_REPO, "tests/test_event_reducer_coverage_v2.py")

    assert done.returncode == 2, (
        f"the guard stopped refusing a duplicate inside a real repo "
        f"(rc={done.returncode}, stderr={done.stderr[:200]!r})"
    )
    assert "not a git repository" not in done.stderr
