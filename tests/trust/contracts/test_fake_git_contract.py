"""Contract tests: FakeGit output must match recorded git-CLI cassettes.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2. Replay-side gate: drive `FakeGit` with cassette inputs and assert the
output matches (after the `sha:short` normalizer collapses commit hashes).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_git import FakeGit
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "git"

# Repo root, so a cassette's repo-relative ``fixture_repo`` resolves to a real
# directory on disk. ``__file__`` is ``tests/trust/contracts/<this>.py`` → three
# ``parents`` hops land on the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _count_insertions(data: bytes) -> int:
    """Lines git would count as insertions when adding *data* to a new file.

    Mirrors git's diff line accounting: every newline-terminated line counts,
    plus a trailing line with no final newline. An empty file adds nothing.
    """
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _root_commit_summary(*, fixture_dir: Path, short_sha: str, message: str) -> str:
    """Reproduce real ``git commit`` stdout for the initial commit of *fixture_dir*.

    A refresh tick records ``commit.yaml`` by running ``git add -A`` + ``git
    commit`` against the fixture sandbox, so the fake's confirmation output must
    match git's full root-commit summary, not a single ``[main <sha>]`` line:
    the ``(root-commit)`` header, the ``N files changed, M insertions(+)``
    shortstat, and one ``create mode <mode> <path>`` line per added file in
    byte-sorted path order.

    Built from a live scan of *fixture_dir* (``.git`` excluded, dotfiles like
    ``.gitkeep`` included) rather than a hardcoded string, so the fake stays in
    lockstep with the fixture: adding or editing a fixture file can't silently
    desync the committed cassette from what the fake reproduces.
    """
    entries: list[tuple[str, int, int]] = []  # (relpath, mode, insertions)
    for path in fixture_dir.rglob("*"):
        rel_parts = path.relative_to(fixture_dir).parts
        if not path.is_file() or ".git" in rel_parts:
            continue
        rel = path.relative_to(fixture_dir).as_posix()
        # git tracks only the executable bit: 100755 when set, else 100644.
        mode = 100755 if path.stat().st_mode & 0o111 else 100644
        entries.append((rel, mode, _count_insertions(path.read_bytes())))
    entries.sort(key=lambda e: e[0])  # byte order == git's tree order (flat dir)

    files = len(entries)
    insertions = sum(ins for _, _, ins in entries)
    file_word = "file" if files == 1 else "files"
    ins_word = "insertion" if insertions == 1 else "insertions"
    summary = f" {files} {file_word} changed, {insertions} {ins_word}(+)"
    # git appends ", 0 deletions(-)" on a root commit only when insertions == 0
    # (see git's print_stat_summary); with any insertions the clause is omitted.
    if insertions == 0:
        summary += ", 0 deletions(-)"

    lines = [f"[main (root-commit) {short_sha}] {message}", summary]
    lines.extend(f" create mode {mode} {rel}" for rel, mode, _ in entries)
    return "\n".join(lines) + "\n"


async def _invoke_fake_git(cassette: Cassette) -> FakeOutput:  # noqa: PLR0911
    """Dispatch the cassette input through FakeGit's matching method."""
    fake = FakeGit()
    method = cassette.input.command
    args = cassette.input.args

    # Every method operates on a path in the fake's in-memory worktree map.
    cwd = Path("/sandbox")

    if method == "worktree_add":
        await fake.worktree_add(cwd, branch=str(args[0]), new_branch=True)
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "commit":
        sha = await fake.commit(cwd, message=str(args[0]))
        # Emit git's full root-commit summary so the cassette shape matches real
        # `git commit` output after the `sha:short` normalizer collapses the hex
        # hash. The summary is scanned from the cassette's declared fixture repo
        # so file/insertion counts stay in lockstep with the fixture contents.
        summary = _root_commit_summary(
            fixture_dir=_REPO_ROOT / cassette.fixture_repo,
            short_sha=sha[:7],
            message=str(args[0]),
        )
        return FakeOutput(exit_code=0, stdout=summary, stderr="")

    if method == "push":
        await fake.push(cwd, remote=str(args[0]), branch=str(args[1]))
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "rev_parse":
        # Seed a commit so rev_parse returns something non-zero.
        await fake.commit(cwd, message="seed")
        sha = await fake.rev_parse(cwd, "HEAD")
        return FakeOutput(exit_code=0, stdout=f"{sha}\n", stderr="")

    if method == "worktree_prune":
        await fake.worktree_prune()
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "worktree_remove":
        # Seed the worktree so there is something to remove, mirroring the
        # add→remove lifecycle the real adapter drives.
        await fake.worktree_add(cwd, branch=str(args[0]), new_branch=True)
        await fake.worktree_remove(cwd, force=True)
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "status":
        # `git status --porcelain` on a clean tree emits no output; FakeGit
        # mirrors that by returning an empty string.
        out = await fake.status(cwd)
        return FakeOutput(exit_code=0, stdout=out, stderr="")

    if method == "config_unset":
        # Seed the key so there is something to unset, mirroring real usage
        # where a corrupted config entry is cleared.
        fake.script_set_corrupted_config(cwd, key=str(args[0]), value="stale")
        await fake.config_unset(cwd, key=str(args[0]))
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "config_get":
        # Seed the value so config_get has something to return.
        fake.script_set_corrupted_config(cwd, key=str(args[0]), value="false")
        result = await fake.config_get(cwd, str(args[0]))
        if result is None:
            return FakeOutput(exit_code=1, stdout="", stderr="")
        return FakeOutput(exit_code=0, stdout=f"{result}\n", stderr="")

    msg = f"FakeGit has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_git_matches_cassette(cassette_path: Path) -> None:
    """Replay a git cassette; assert FakeGit's output matches under normalizers."""
    await replay_cassette(cassette_path, _invoke_fake_git)


def test_cassette_directory_not_empty() -> None:
    """A trust gate with zero cassettes is a silent pass — guard against that."""
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
