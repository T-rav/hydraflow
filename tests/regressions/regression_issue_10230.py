"""Regression #10230: FakeGit commit template must match real multi-file root-commit output.

``ContractRefreshLoop`` re-records ``tests/trust/contracts/cassettes/git/commit.yaml``
every tick by running real ``git commit`` against the ``git_sandbox`` fixture,
which is seeded with *three* tracked files (``.gitkeep``, ``README.md``,
``file.txt``) — not the single ``hello.txt`` the recorder docstring once
assumed. Real git therefore emits the full root-commit summary::

    [main (root-commit) <sha>] initial
     3 files changed, 5 insertions(+)
     create mode 100644 .gitkeep
     create mode 100644 README.md
     create mode 100644 file.txt

The replay-side helper (``_invoke_fake_git``'s ``"commit"`` branch) previously
emitted only the single-line ``[main <sha>] initial`` template, so every fresh
recording produced a cassette the fake could never match — blocking *every*
``contract-refresh/*`` PR the loop opens (observed in closed PR #10184), since
one drifted adapter is bundled with all the others into one branch.

This pins the end-to-end contract: drive the *production* recorder against a
pristine copy of the committed fixture, then replay the freshly recorded
cassette through the fake. It was RED before the fake's commit branch was
taught to reproduce git's multi-file root-commit summary.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "trust"
    / "contracts"
    / "fixtures"
    / "git_sandbox"
)


@pytest.mark.skipif(shutil.which("git") is None, reason="git binary not on PATH")
async def test_fresh_recording_replays_through_fake(tmp_path: Path) -> None:
    """A cassette freshly recorded from real git must replay green through FakeGit."""
    from contract_recording import record_git
    from tests.trust.contracts._replay import replay_cassette
    from tests.trust.contracts.test_fake_git_contract import _invoke_fake_git

    # Copy the committed fixture so the recorder's in-place ``git init`` does
    # not dirty the tracked fixture directory.
    sandbox = tmp_path / "git_sandbox"
    shutil.copytree(_FIXTURE, sandbox)
    out_dir = tmp_path / "cassettes"

    paths = record_git(sandbox, out_dir)
    assert paths, "recorder returned no cassettes (git present but recording failed)"
    commit_cassette = next(p for p in paths if p.name == "commit.yaml")

    # Pre-fix this raised AssertionError: the fake emitted a single-line
    # ``[main <sha>] initial`` while the real recording is the multi-file
    # root-commit summary.
    await replay_cassette(commit_cassette, _invoke_fake_git)
