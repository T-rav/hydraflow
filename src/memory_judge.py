"""LLM judge that scores tribal-memory candidates against the durability bar.

Runs a small Claude (or whatever ``background_tool`` is configured) prompt
that returns a JSON verdict. Below threshold → reject. At/above threshold
→ accept. Malformed responses are conservatively treated as rejects so
noise can't slip through on parser errors.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.memory_judge")

JUDGE_PROMPT = """\
You are reviewing a candidate memory for a long-lived engineering knowledge base.

Only ADR-quality, durable, hard-won facts belong here — the things a senior
engineer would tell a new hire on day one. Examples of what BELONGS:
  - "The main branch is protected; pushes will fail." (architectural invariant)
  - "Always rebuild Vite assets before pushing UI; cache poisoning broke prod twice."
  - "Patch optional-dependency imports at the *importing* module, not the source."
What does NOT belong:
  - Anything tied to a single issue/PR ("renamed X in #5741")
  - Implementation details that will change next refactor
  - Trivial observations or restatements of existing CLAUDE.md content
  - Anything that would not still be true a year from now

Score the candidate from 0.0 (pure noise) to 1.0 (must-keep tribal knowledge).
Respond with ONLY a single JSON object on one line:
{{"score": <float>, "verdict": "accept"|"reject", "reason": "<one sentence>"}}

Candidate:
  principle: {principle}
  rationale: {rationale}
  failure_mode: {failure_mode}
  scope: {scope}
"""


@dataclass(frozen=True)
class JudgeVerdict:
    accepted: bool
    score: float
    reason: str


class MemoryJudge:
    """LLM-backed quality gate for tribal memory candidates."""

    def __init__(
        self,
        config: HydraFlowConfig,
        runner: SubprocessRunner,
        *,
        threshold: float = 0.7,
        gh_token: str = "",
    ) -> None:
        self._config = config
        self._runner = runner
        self._threshold = threshold
        self._gh_token = gh_token

    async def evaluate(
        self,
        *,
        principle: str,
        rationale: str,
        failure_mode: str,
        scope: str,
    ) -> JudgeVerdict:
        from agent_cli import build_lightweight_command  # noqa: PLC0415
        from subprocess_util import make_clean_env  # noqa: PLC0415

        prompt = JUDGE_PROMPT.format(
            principle=principle,
            rationale=rationale,
            failure_mode=failure_mode,
            scope=scope,
        )

        tool = self._config.background_tool
        if tool == "inherit":
            tool = "claude"
        model = self._config.memory_judge_model

        cmd, cmd_input = build_lightweight_command(
            tool=tool, model=model, prompt=prompt
        )
        env = make_clean_env(self._gh_token)

        try:
            result = await self._runner.run_simple(
                cmd,
                env=env,
                input=cmd_input,
                timeout=self._config.agent_timeout,
            )
        except (TimeoutError, OSError, FileNotFoundError, NotImplementedError) as exc:
            logger.warning(
                "Memory judge runner failed, rejecting conservatively: %s", exc
            )
            return JudgeVerdict(
                accepted=False, score=0.0, reason=f"judge runner error: {exc}"
            )

        if result.returncode != 0:
            logger.warning(
                "Memory judge returned non-zero (rc=%d): %s",
                result.returncode,
                result.stderr[:200],
            )
            return JudgeVerdict(accepted=False, score=0.0, reason="judge non-zero exit")

        return self._parse_verdict(result.stdout)

    def _parse_verdict(self, raw: str) -> JudgeVerdict:
        if not raw.strip():
            return JudgeVerdict(
                accepted=False, score=0.0, reason="empty judge response"
            )
        try:
            # Take the last non-empty line in case the tool prints prelude.
            line = raw.strip().splitlines()[-1]
            data = json.loads(line)
            score = float(data["score"])
            reason = str(data.get("reason", ""))
        except (json.JSONDecodeError, KeyError, ValueError, IndexError):
            return JudgeVerdict(
                accepted=False, score=0.0, reason="malformed judge response"
            )

        accepted = score >= self._threshold
        return JudgeVerdict(accepted=accepted, score=score, reason=reason)
