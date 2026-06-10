"""Production adapters wiring TermProposerLoop to real subprocess infrastructure.

`ClaudeCLIClient` implements the `LLMClient` Protocol by shelling out to a
configured agent CLI tool (`claude`/`codex`/`gemini`) via the project's
`SubprocessRunner`. Mirrors the lightweight-call pattern from
`wiki_compiler.WikiCompiler._call_model`.

`OpenAutoPRBotPRPort` implements the `BotPRPort` Protocol by writing draft
files to disk and delegating to `auto_pr.open_automated_pr_async` for the
worktree → commit → push → `gh pr create` flow.

Wired into `service_registry.build_services` (replaces the chunk-2
placeholder clients that raised NotImplementedError on first tick).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_cli import AgentTool

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.term_proposer_runtime")


class ClaudeCLIClient:
    """Subprocess-CLI adapter for the LLMClient Protocol.

    Invokes `claude -p` (or another agent tool) one-shot via SubprocessRunner;
    parses JSON out of stdout. Tolerant of markdown fences around the JSON
    payload (model output sometimes wraps in ```json ... ```).
    """

    def __init__(
        self,
        runner: SubprocessRunner,
        *,
        tool: AgentTool = "claude",
        model: str = "claude-sonnet-4-6",
        timeout: int = 180,
    ) -> None:
        self._runner = runner
        self._tool: AgentTool = tool
        self._model = model
        self._timeout = timeout

    async def complete_structured(
        self, *, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Send prompt to the CLI tool and return the parsed JSON object.

        `schema` is unused by the CLI path (the prompt itself instructs the
        model on output shape); kept in the signature to satisfy the Protocol.
        """
        del schema
        from agent_cli import build_lightweight_command  # noqa: PLC0415
        from runner_utils import raise_if_credit_exhausted  # noqa: PLC0415

        cmd, cmd_input = build_lightweight_command(
            tool=self._tool,
            model=self._model,
            prompt=prompt,
            isolate_user_settings=True,
        )
        result = await self._runner.run_simple(
            cmd, input=cmd_input, timeout=self._timeout
        )
        # run_simple surfaces credit-out as rc!=0 text (it never raises), so
        # scan and convert to CreditExhaustedError — otherwise the billing
        # signal is misclassified as a generic CLI failure and burns budget.
        raise_if_credit_exhausted(result.stdout, result.stderr, self._tool)
        if result.returncode != 0:
            raise RuntimeError(
                f"{self._tool} CLI failed (rc={result.returncode}): "
                f"{result.stderr[:200]}"
            )
        return self._extract_json(result.stdout)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Pull a JSON object out of CLI stdout (tolerant of markdown fences)."""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"no JSON object in CLI output: {text[:200]}")
        return json.loads(match.group(0))


# Generated arch artifacts that derive from docs/wiki/terms/ (ADR-0053).
# When a proposer adds/edits a term file, these two views go stale and the
# pre-push `make arch-check` drift guard rejects the push — so they MUST be
# regenerated and staged into the same bot-PR commit. See ADR-0053 / ADR-0058.
_TERMS_REL_DIR = "docs/wiki/terms"
_UL_GLOSSARY_REL = "docs/arch/generated/ubiquitous-language.md"
_UL_CONTEXT_MAP_REL = "docs/arch/generated/ubiquitous-language-context-map.md"


def regenerate_ubiquitous_language_artifacts(repo_root: Path) -> list[Path]:
    """Re-render the term-derived arch artifacts from on-disk term files.

    Term-proposer / edge-proposer bot-PRs mutate ``docs/wiki/terms/`` but the
    generated ubiquitous-language views in ``docs/arch/generated/`` derive from
    those term files. Committing the term change without refreshing the views
    leaves ``make arch-check`` (run by the pre-push hook) detecting drift, which
    rejects the push and the proposer PR never lands. Regenerating here — after
    the new term files are written under ``repo_root`` — keeps the views in sync
    so the same commit passes the drift guard.

    Returns the absolute paths of the regenerated artifacts (for staging). When
    no terms directory exists, returns an empty list (nothing to regenerate).
    """
    from ubiquitous_language import (  # noqa: PLC0415
        TermStore,
        render_context_map,
        render_glossary,
    )

    terms_dir = repo_root / _TERMS_REL_DIR
    if not terms_dir.is_dir():
        return []

    try:
        terms = TermStore(terms_dir).list()
    except (ValueError, OSError) as exc:
        # A malformed term file shouldn't crash the PR-open. Degrade to the
        # prior behavior (no regen) — the pre-push arch-check still guards
        # correctness; we just don't pre-stage the refreshed views.
        logger.warning(
            "ubiquitous-language regen skipped — could not load terms: %s", exc
        )
        return []
    regenerated: list[Path] = []
    for rel_path, body in (
        (_UL_GLOSSARY_REL, render_glossary(terms)),
        (_UL_CONTEXT_MAP_REL, render_context_map(terms)),
    ):
        abs_path = repo_root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(body, encoding="utf-8")
        regenerated.append(abs_path)
    return regenerated


class OpenAutoPRBotPRPort:
    """BotPRPort adapter wrapping auto_pr.open_automated_pr_async.

    Writes each draft term file under repo_root, then delegates the full
    worktree-copy → commit → push → `gh pr create` flow to the existing
    helper. Sets `auto_merge=False` — DependabotMergeLoop handles auto-merge
    once the PR carries `hydraflow-ul-proposed`.
    """

    def __init__(
        self, *, repo_root: Path, gh_token: str = "", base: str = "main"
    ) -> None:
        self._repo_root = repo_root
        self._gh_token = gh_token
        # Target branch for the bot PR. Callers pass ``config.base_branch()`` so
        # UL PRs follow the two-tier branch model (ADR-0042): ``staging`` when
        # staging is enabled, ``main`` otherwise. Defaults to ``main`` for the
        # pre-staging single-tier case.
        self._base = base

    async def open_bot_pr(
        self,
        *,
        branch: str,
        title: str,
        body: str,
        labels: list[str],
        files: dict[str, str],
    ) -> int:
        """Write files to disk and open a PR. Returns the PR number."""
        from auto_pr import open_automated_pr_async  # noqa: PLC0415

        written_paths: list[Path] = []
        wrote_term_file = False
        for rel_path, content in files.items():
            abs_path = self._repo_root / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            written_paths.append(abs_path)
            if Path(rel_path).is_relative_to(_TERMS_REL_DIR):
                wrote_term_file = True

        # Term changes make the generated ubiquitous-language views stale; the
        # pre-push arch-check drift guard rejects the push unless the refreshed
        # views ride along in the SAME commit. Regenerate + stage them here.
        if wrote_term_file:
            written_paths.extend(
                regenerate_ubiquitous_language_artifacts(self._repo_root)
            )

        result = await open_automated_pr_async(
            repo_root=self._repo_root,
            branch=branch,
            files=written_paths,
            pr_title=title,
            pr_body=body,
            base=self._base,
            auto_merge=False,
            gh_token=self._gh_token,
            raise_on_failure=False,
            labels=labels,
        )

        if result.status != "opened" or result.pr_url is None:
            raise RuntimeError(
                f"open_automated_pr_async returned status={result.status!r} "
                f"error={result.error!r}"
            )
        return self._extract_pr_number(result.pr_url)

    @staticmethod
    def _extract_pr_number(pr_url: str) -> int:
        """Parse a github.com PR URL like '.../pull/4242' to its int number."""
        match = re.search(r"/pull/(\d+)", pr_url)
        if not match:
            raise RuntimeError(f"could not parse PR number from {pr_url!r}")
        return int(match.group(1))
