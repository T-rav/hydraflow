"""In-memory fake of ``src/wiki_compiler.py:WikiCompiler`` for scenario tests.

Records every ``compile_topic_tracked`` invocation and returns a
configurable number of compiled entries. Never invokes an LLM.

Scenario tests exercising the ``RepoWikiLoop``'s tracked-topic compile
(the inline on-merge compile of PR #8400 was removed by #9836) assert on
``.compile_calls`` to verify the right topics were picked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class CompileCall:
    """One invocation of ``compile_topic_tracked``."""

    tracked_root: Path
    repo: str
    topic: str


@dataclass
class FakeWikiCompiler:
    """Drop-in replacement for WikiCompiler in scenario tests.

    Implements the methods PostMergeHandler and RepoWikiLoop actually
    call (the rest raise AttributeError on access so missed wiring is
    loud).
    """

    # ClassVar so dataclass doesn't promote it to an init field.
    _is_fake_adapter: ClassVar[bool] = True

    compile_calls: list[CompileCall] = field(default_factory=list)
    compiled_entries_per_call: int = 1
    #: What the anchor gate "said" about the last compile (#11888). Defaults
    #: to "nothing rejected", so an ordinary scenario can never trip the
    #: barren gate by accident; a scenario testing that gate sets these.
    rejected_digests: list[str] = field(default_factory=list)
    accepted_entries_per_call: int | None = None

    async def compile_topic_tracked(
        self,
        tracked_root: Path,
        repo: str,
        topic: str,
    ) -> int:
        self.compile_calls.append(
            CompileCall(tracked_root=tracked_root, repo=repo, topic=topic)
        )
        return self.compiled_entries_per_call

    async def compile_topic(self, *args, **kwargs) -> int:
        """Legacy topic-page compile — return 0 to indicate no change."""
        return 0

    @property
    def last_anchor_gate_verdict(self) -> tuple[list[str], int]:
        """Anchor-gate verdict of the last compile (#11888).

        Configurable rather than fixed: a scenario that wants the barren path
        must be able to say "this compile rejected X and wrote nothing", which
        is the whole shape under test. The DEFAULT is "rejected nothing", so
        every scenario that does not care cannot trip the gate by accident.
        """
        accepted = self.accepted_entries_per_call
        if accepted is None:
            accepted = self.compiled_entries_per_call
        return list(self.rejected_digests), accepted

    async def detect_contradictions(self, *args, **kwargs):
        """Ingest-time contradiction detector — never flags anything in fakes."""

        class _Empty:
            contradicts: list = []

        return _Empty()

    async def dedup_or_corroborate(self, **kwargs):
        """Corroboration decision stub.

        Default is 'no match' so scenarios exercise the normal write
        path. Tests that need corroboration to fire should assign
        ``fake.dedup_decision = CorroborationDecision(...)`` before
        running the tick.
        """
        from wiki_compiler import CorroborationDecision  # noqa: PLC0415

        return getattr(self, "dedup_decision", CorroborationDecision())
