"""Git-identity hermeticity guard (feedback_ci_no_global_git_config, PR #8354).

CI runners have no global git config. A test that runs a real `git commit`
without explicit `-c user.*` overrides therefore fails there with
`Author identity unknown`, while passing on any laptop whose `~/.gitconfig`
happens to supply one — the env-dependent red PR #8354 shipped.

`tests/conftest.py::setup_test_environment` removes that whole class by
seeding `GIT_AUTHOR_*` / `GIT_COMMITTER_*` for the session, so no test depends
on ambient identity. That fixture is the artifact this memory was promoted on,
and nothing verified it: the promotion named a mechanism no test could see was
still wired — the same gap #12105 closed for `config_disable` seam
declarations, where deleting an override reddened nothing.

Pinned live rather than textually, because the failure this prevents is a
runtime one: on a runner, this test IS the canary that the seeding is in force.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_IDENTITY_KEYS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)


def test_the_session_fixture_seeds_a_git_identity() -> None:
    """Live: the four keys are present for every test in the session."""
    missing = [k for k in _IDENTITY_KEYS if not os.environ.get(k)]

    assert not missing, (
        f"tests/conftest.py::setup_test_environment no longer seeds {missing}. "
        "Any test running a real `git commit` without explicit -c overrides "
        "will now pass locally and fail on CI with 'Author identity unknown'."
    )


def _commit_under_ci_shape(
    work: Path, *, identity: bool
) -> subprocess.CompletedProcess[str]:
    """Run a real `git commit` in a runner-shaped environment.

    A plain empty-HOME probe is NOT enough: git falls back to deriving
    `you@hostname` and the commit succeeds, which made my first version of the
    decoy below pass and proved nothing. `user.useConfigOnly=true` is what
    refuses that fallback, and only the three together reproduce the
    `Author identity unknown` a GitHub Actions runner gives.
    """
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_KEYS}
    home = work.parent / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = str(home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    if identity:
        env.update(dict.fromkeys(_IDENTITY_KEYS[:1], "HydraFlow Test"))
        env["GIT_AUTHOR_EMAIL"] = "test@hydraflow.local"
        env["GIT_COMMITTER_NAME"] = "HydraFlow Test"
        env["GIT_COMMITTER_EMAIL"] = "test@hydraflow.local"
    subprocess.run(["git", "init", "-q", str(work)], check=True, capture_output=True)
    (work / "f.txt").write_text("x\n")
    subprocess.run(
        ["git", "add", "-A"], cwd=work, check=True, capture_output=True, env=env
    )
    return subprocess.run(
        ["git", "-c", "user.useConfigOnly=true", "commit", "-m", "probe"],
        cwd=work,
        capture_output=True,
        text=True,
        env=env,
        check=False,  # the failing case IS the decoy's subject
    )


def test_the_seeded_identity_is_what_lets_a_commit_succeed(tmp_path: Path) -> None:
    """The consequence, not the variable.

    Asserting the four keys exist would still pass if git ignored them. This
    runs the real operation in the runner's shape and requires the seeded
    identity to carry it.
    """
    done = _commit_under_ci_shape(tmp_path / "with", identity=True)

    assert done.returncode == 0, (
        f"git refused the seeded identity: {done.stderr.strip()[:200]}"
    )


def test_without_that_identity_the_same_commit_fails(tmp_path: Path) -> None:
    """The decoy — and it earned its place.

    My first version omitted `user.useConfigOnly`, so git derived
    `you@hostname`, the commit succeeded, and the positive test above was
    attributing to the fixture something the host was doing anyway.
    """
    done = _commit_under_ci_shape(tmp_path / "without", identity=False)

    assert done.returncode != 0, (
        "a commit with no identity anywhere SUCCEEDED, so the test above "
        "cannot be attributing anything to the conftest seeding"
    )
    assert "identity unknown" in done.stderr.lower()
