"""One-shot canary trace — see docs/superpowers/specs/2026-04-20-prompt-audit-design.md.

Monkey-patches ``base_runner.stream_claude_process`` to capture every ``prompt=``
argument with call-site traceback, drives the triage runner against a synthetic
canary issue, and writes the captured prompts to
``tests/fixtures/prompts/canary-trace.jsonl``.

Scope is deliberately tiny — one runner, one canary issue, at least one captured
prompt. The goal is to prove the tracing mechanism works and seed the coverage
assertion; the eval gate (sub-project 2) extends the canary to a real target repo.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PromptInterceptor:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, *, prompt: str, cmd: list[str] | None = None) -> None:
        call_site = "".join(traceback.format_stack(limit=12))
        self.entries.append(
            {
                "prompt": prompt,
                "cmd": list(cmd) if cmd is not None else [],
                "call_site": call_site,
            }
        )

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for entry in self.entries:
                f.write(json.dumps(entry) + "\n")


def install(interceptor: PromptInterceptor) -> None:
    """Replace ``base_runner.stream_claude_process`` with a recording stub.

    The stub captures the prompt, then returns a canned transcript that keeps
    the triage runner's downstream parser happy (valid JSON matching the schema).
    """
    import base_runner  # noqa: PLC0415

    _CANNED_TRIAGE_JSON = (
        '{"ready": true, "reasons": [], "issue_type": "feature", '
        '"clarity_score": 9, "needs_discovery": false, "enrichment": ""}'
    )

    async def recording_stub(*, cmd: list[str], prompt: str, **_kwargs: Any) -> str:
        interceptor.record(prompt=prompt, cmd=cmd)
        return _CANNED_TRIAGE_JSON

    base_runner.stream_claude_process = recording_stub  # type: ignore[assignment]


# NOTE: an end-to-end driver (instantiate BaseRunner+StateTracker+EventBus, run
# TriageRunner.evaluate on a synthetic issue) was deliberately omitted from this
# sub-project. `StateTracker` and the runner graph have enough wiring that
# standing them up safely in <5 minutes wasn't feasible, and Task 25 of the plan
# (see docs/superpowers/plans/2026-04-20-prompt-audit.md) used a simpler fallback
# path — directly invoking ``render_target`` on a registry entry and feeding the
# result through this interceptor's ``record()`` to produce the canary trace
# artifact at tests/fixtures/prompts/canary-trace.jsonl.
#
# Sub-project 2 (eval gate) is the right home for a full end-to-end canary: it
# will need a real canary repo and a wired-up factory anyway. At that point,
# revisit this file and add an end-to-end driver that uses ``install()`` to
# patch ``stream_claude_process`` before driving ``TriageRunner.evaluate(...)``
# — just make sure to match the real ``BaseRunner.__init__`` signature
# (``config``, ``event_bus``, ``runner`` + kwargs ``hindsight``, ``credentials``,
# ``wiki_store``) rather than the aspirational shape that was here before.
