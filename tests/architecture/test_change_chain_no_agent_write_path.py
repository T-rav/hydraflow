"""No agent-facing prompt may name the chain directory (ADR-0149).

The chain's security property is that the implementer *inherits* its files
as history rather than authoring them: the harness materialises and commits
them into the worktree before the agent starts, so the agent has no write
path to what the gate later reads. ADR-0149 justifies the chain by "the
agent cannot rewrite the CH-1 record"; this guard holds the stronger form.

A prompt that tells an agent to write, update or regenerate anything under
``docs/changes/`` hands the write path back, and would do so silently — the
digest check would then be comparing a file the agent authored against a
record it also influenced. This is the guard that notices.

The corpus test is not padding. A static sweep that silently matches
nothing passes forever; this repo has shipped that defect before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every tree whose contents reach an agent as instructions.
PROMPT_ROOTS = (
    Path("src/hydraflow_resources/prompts"),
    Path(".claude/commands"),
    Path(".claude/skills"),
    Path("agents"),
)

PROMPT_SUFFIXES = frozenset({".md", ".txt", ".j2", ".jinja", ".jinja2"})

# The needle: any reference to the chain tree from inside a prompt.
CHAIN_DIR_NEEDLE = "docs/changes"


def _prompt_files() -> list[Path]:
    """Every prompt-shaped file under every prompt root."""
    return sorted(
        path
        for root in PROMPT_ROOTS
        if (REPO_ROOT / root).is_dir()
        for path in (REPO_ROOT / root).rglob("*")
        if path.is_file() and path.suffix in PROMPT_SUFFIXES
    )


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


#: Roots that must exist and must contribute files. Asserted individually,
#: not as "at least one survives": `src/hydraflow_resources/prompts` holds
#: roughly half the corpus, and a check satisfied by any one surviving root
#: would let that half stop being swept while staying green — the exact
#: silent-hollowing failure this module says it exists to prevent.
REQUIRED_ROOTS = (
    Path("src/hydraflow_resources/prompts"),
    Path(".claude/commands"),
    Path("agents"),
)


@pytest.mark.parametrize("root", REQUIRED_ROOTS, ids=str)
def test_each_required_prompt_root_still_contributes_files(root: Path):
    swept = [p for p in _prompt_files() if str(root) in str(p.relative_to(REPO_ROOT))]

    assert swept, (
        f"{root} contributed no files to the sweep — it moved or was renamed, "
        "and its prompts are now unswept while this guard stays green"
    )


def test_the_prompt_corpus_is_not_empty():
    """A sweep with an empty corpus is green for the wrong reason."""
    assert _prompt_files(), "no prompt files found — the sweep has no subject"


def test_the_needle_matches_a_known_positive():
    """The predicate must be able to fire, or its silence proves nothing."""
    synthetic = "Write the plan to docs/changes/issue-1/plan.md when done."

    assert CHAIN_DIR_NEEDLE in synthetic


@pytest.mark.parametrize("path", _prompt_files(), ids=_relative)
def test_no_prompt_names_the_chain_directory(path: Path):
    body = path.read_text(encoding="utf-8", errors="replace")

    assert CHAIN_DIR_NEEDLE not in body, (
        f"{_relative(path)} names {CHAIN_DIR_NEEDLE!r}. The artifact chain is "
        "written by the harness (change_chain_writer), never by an agent — a "
        "prompt that points an agent at it hands back the write path ADR-0149 "
        "removed."
    )
