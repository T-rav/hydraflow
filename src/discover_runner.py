"""Discover runner — planner-invoked discovery research helper (ADR-0107)."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, ClassVar

from agent_cli import build_agent_command
from base_runner import BaseRunner
from discover_expander import expand_research_brief, format_queries_for_prompt
from exception_classify import reraise_on_credit_or_bug
from human_steering import fenced_steering_guidance
from models import DiscoverResult
from plugin_skill_registry import (
    discover_plugin_skills,
    format_plugin_skills_for_prompt,
    skills_for_phase,
)
from runner_constants import MEMORY_SUGGESTION_PROMPT
from skill_registry import BUILTIN_SKILLS

if TYPE_CHECKING:
    from dedup_store import DedupStore
    from models import Task
    from ports import PRPort

logger = logging.getLogger("hydraflow.discover")

# Markers for extracting structured output from transcript
_DISCOVER_START = "DISCOVER_START"
_DISCOVER_END = "DISCOVER_END"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

# Evaluator skill + escalation label constants (§4.10)
_SKILL_NAME = "discover-completeness"
_ESCALATION_LABEL_STUCK = "discover-stuck"
_ESCALATION_LABEL_HITL = "hitl-escalation"


def _mockworld_sentinel_active(runner: DiscoverRunner) -> bool:
    """True when the ADR-0063 MockWorld sentinel is attached to *runner*.

    Under the sentinel the runner must NEVER dispatch a subprocess: in the
    air-gapped docker sandbox a real ``claude -p`` spawn blocks for the full
    ``agent_timeout``, wedging the discover phase loop mid-tick (frozen
    heartbeat) and starving every scenario that routes an issue through
    discover (#9796 — s51 failed every rc/* promotion this way).
    """
    fake_llm = getattr(runner, "_mockworld_fake_llm", None)
    return fake_llm is not None and bool(getattr(fake_llm, "_is_fake_adapter", False))


def _consume_mockworld_discover_script(
    runner: DiscoverRunner, issue_number: int
) -> tuple[bool, str, list[str]] | None:
    """Consume one scripted DiscoverRunner coherence outcome, if present.

    Returns ``(passed, summary, findings)`` matching the
    ``parse_discover_completeness_result`` shape, or ``None`` when no
    MockWorld scripting is active for *issue_number*. When the scripted
    outcome carries ``queries_required``, those queries are stashed in a
    per-task buffer that ``_dispatch_expander`` drains for the next call
    so the expander returns the scripted queries instead of dispatching
    a real subagent.
    """
    fake_llm = getattr(runner, "_mockworld_fake_llm", None)
    if fake_llm is None or not getattr(fake_llm, "_is_fake_adapter", False):
        return None
    if not hasattr(fake_llm, "pop_discover_script"):
        return None
    scripted = fake_llm.pop_discover_script(issue_number)
    if scripted is None:
        return None
    # Stash queries for the next _dispatch_expander call. The runner owns
    # the buffer (not FakeLLM) because the expander dispatch is keyed by
    # the (issue, attempt) pair in the bounded retry loop and the buffer
    # is short-lived — one entry per scripted failure.
    if scripted.queries_required:
        buf = getattr(runner, "_mockworld_pending_queries", None)
        if buf is None:
            buf = {}
            runner._mockworld_pending_queries = buf  # type: ignore[attr-defined]
        buf.setdefault(issue_number, []).extend(scripted.queries_required)
    summary = scripted.summary or (
        "All five rubric criteria pass"
        if scripted.coherent
        else "scripted coherence rejection"
    )
    return scripted.coherent, summary, list(scripted.findings)


def _take_mockworld_pending_queries(
    runner: DiscoverRunner, issue_number: int
) -> list[str] | None:
    """Pop the scripted expander queries for *issue_number*, if any.

    Returns ``None`` when the runner is not in MockWorld mode. Returns an
    empty list when the scenario scripted a coherence failure WITHOUT
    queries (expander surfaced nothing — same as the real expander
    returning [] from a low-confidence subagent).
    """
    fake_llm = getattr(runner, "_mockworld_fake_llm", None)
    if fake_llm is None or not getattr(fake_llm, "_is_fake_adapter", False):
        return None
    buf = getattr(runner, "_mockworld_pending_queries", None)
    if not buf:
        return []
    return buf.pop(issue_number, [])


class DiscoverRunner(BaseRunner):
    """Launches an agent to research a vague/broad/escalated issue before planning.

    ADR-0107 made this a general planner-invoked helper — issues land here
    for being low-clarity, escalated, or cycled back, not for being
    "product" work specifically. The brief it produces must satisfy the
    ``discover-completeness`` rubric (§4.10): named *Intent*, *Affected
    area*, *Acceptance criteria*, *Open questions*, and *Known unknowns*
    sections, grounded in the codebase via Glob/Grep/Read. For issues that
    are genuinely user-facing product features, it additionally researches
    the external competitive/user landscape (WebSearch); internal
    engineering/tooling issues skip that optional research.
    """

    _log = logger
    _phase_name: ClassVar[str] = "discover"

    def bind_escalation_deps(
        self, prs: PRPort, dedup: DedupStore | None = None
    ) -> None:
        """Wire issue-filing + dedup deps used by evaluator escalation.

        Bound by the service factory (``service_registry.build_services``)
        right after construction (ADR-0107 — this engine is invoked as a
        planner helper, not a standalone phase). Without binding, escalation
        logs a warning and returns — evaluator dispatch and bounded retry
        still run.
        """
        self._prs = prs
        self._dedup = dedup

    async def discover(
        self, task: Task, _worker_id: int = 0, *, guidance: str = ""
    ) -> DiscoverResult:
        """Run product discovery with post-output evaluation (§4.10).

        When ``config.max_discover_attempts > 0`` the runner evaluates
        each produced brief via the ``discover-completeness`` skill; on
        RETRY it re-runs discovery up to the budget, then escalates via
        ``hitl-escalation`` / ``discover-stuck`` and returns the last
        (best-available) brief so the phase can still post a comment.

        ADR-0063 W3a — discover-expander. On the FIRST coherence-failure
        within the bounded retry loop the runner dispatches the
        ``discover-expander`` subagent (capped by
        ``config.max_discover_expansions``, default 1) to propose new
        research queries; those queries are injected into the next
        attempt's prompt before re-running discovery. One expansion per
        issue by default — further coherence failures fall through to
        normal retry + escalation.

        ``guidance`` (ADR-0099 #4, human-on-the-loop continuous steering)
        is live operator guidance for this issue, sourced by
        :class:`DiscoverPhase` from ``StateTracker.get_human_steering``.
        It is folded, fenced, into BOTH prompt-construction sites: the
        main discovery-brief prompt (:meth:`_build_prompt`) and the
        ``discover-completeness`` evaluator prompt (:meth:`_evaluate_brief`).
        Empty string when the feature is off or no guidance was posted —
        reference signal only, never blocking.
        """
        result = DiscoverResult(issue_number=task.id)
        if self._config.dry_run:
            logger.info("[dry-run] Would run discovery for issue #%d", task.id)
            result.research_brief = "Dry-run: discovery skipped"
            return result

        max_attempts = max(1, self._config.max_discover_attempts or 1)
        evaluator_enabled = self._config.max_discover_attempts > 0
        max_expansions = max(0, int(self._config.max_discover_expansions or 0))
        expansions_used = 0
        expanded_queries: list[str] = []
        last_summary = ""
        last_findings: list[str] = []
        for attempt in range(1, max_attempts + 1):
            result = await self._run_discovery_once(
                task, attempt, expanded_queries=expanded_queries, guidance=guidance
            )
            if not evaluator_enabled:
                return result
            passed, summary, findings = await self._evaluate_brief(
                task, result.research_brief, guidance=guidance
            )
            last_summary, last_findings = summary, findings
            if passed:
                return result
            logger.warning(
                "Discover brief rejected for #%d attempt %d/%d: %s",
                task.id,
                attempt,
                max_attempts,
                summary,
            )
            # ADR-0063 W3a — on the first coherence failure, dispatch
            # the discover-expander before the next attempt. Bounded by
            # ``max_discover_expansions`` (default 1). When the
            # expander returns no queries we still proceed to the next
            # attempt (no harm), but we do not consume another expansion
            # slot — there was nothing to inject.
            should_expand = expansions_used < max_expansions and attempt < max_attempts
            if should_expand:
                new_queries = await self._dispatch_expander(
                    task=task,
                    original_brief=result.research_brief,
                    coherence_failure_reason=summary,
                    failure_findings=findings,
                )
                if new_queries:
                    expansions_used += 1
                    # Accumulate: queries from successive expansions all
                    # feed forward so the next attempt sees the union.
                    expanded_queries = expanded_queries + new_queries
                    logger.info(
                        "discover-expander injected %d new queries for #%d "
                        "(expansion %d/%d)",
                        len(new_queries),
                        task.id,
                        expansions_used,
                        max_expansions,
                    )
        await self._escalate_stuck(task, last_summary, last_findings, max_attempts)
        return result

    async def _dispatch_expander(
        self,
        *,
        task: Task,
        original_brief: str,
        coherence_failure_reason: str,
        failure_findings: list[str],
    ) -> list[str]:
        """Dispatch the discover-expander subagent (ADR-0063 W3a).

        Thin wrapper that supplies the runner's CLI command, working
        directory, and ``_execute`` callable to the pure expander helper.
        Returns the parsed expansion queries (possibly empty).

        MockWorld bypass: when the scenario scripted the prior coherence
        failure with ``queries_required`` via
        :meth:`FakeLLM.script_discover`, the queries surface here via a
        per-task buffer the bypass-aware ``_evaluate_brief`` populated
        before raising the coherence flag. This skips the expander
        subprocess entirely for sandbox scenarios.
        """
        scripted_queries = _take_mockworld_pending_queries(self, task.id)
        if scripted_queries is not None:
            return scripted_queries

        try:
            return await expand_research_brief(
                task=task,
                original_brief=original_brief,
                coherence_failure_reason=coherence_failure_reason,
                failure_findings=failure_findings,
                executor=self._execute,
                cmd=self._build_command(),
                cwd=self._config.repo_root,
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("discover-expander wrapper failed for #%d: %s", task.id, exc)
            return []

    async def _run_discovery_once(
        self,
        task: Task,
        attempt: int,
        *,
        expanded_queries: list[str] | None = None,
        guidance: str = "",
    ) -> DiscoverResult:
        """Run a single discovery pass — produces one :class:`DiscoverResult`.

        Factored from the original single-shot ``discover`` body so the
        outer loop can invoke it once per attempt. ``expanded_queries``
        (ADR-0063 W3a) carries research queries the discover-expander
        subagent produced after a prior coherence failure; when present
        they are appended to the prompt so the next brief explicitly
        addresses each one. ``guidance`` (ADR-0099 #4) is live operator
        steering, folded fenced into the prompt by :meth:`_build_prompt`.
        """
        result = DiscoverResult(issue_number=task.id)
        transcript = ""

        # MockWorld bypass (ADR-0063 sentinel): never spawn a subprocess in
        # the sandbox. Without this, the air-gapped ``claude -p`` spawn blocks
        # for the full agent_timeout and wedges the discover loop (#9796).
        # ``_evaluate_brief`` still consumes any scripted coherence verdict,
        # so failure-path scenarios keep working against this stub brief.
        if _mockworld_sentinel_active(self):
            result.research_brief = (
                f"MockWorld discovery brief for issue #{task.id} (attempt "
                f"{attempt}). Deterministic sandbox stub — no subprocess was "
                f"dispatched."
            )
            result.opportunities = ["MockWorld sandbox stub"]
            return result

        try:
            cmd = self._build_command()
            prompt = self._build_prompt(task, guidance=guidance)

            # Inject memory context (prior learnings, ADRs, retrospectives)
            memory_section = await self._inject_memory(
                query_context=f"product discovery for {task.title} {(task.body or '')[:200]}",
            )
            if memory_section:
                prompt += (
                    f"\n\n## Existing System Knowledge\n\n"
                    f"Prior learnings, architecture decisions, and retrospectives "
                    f"relevant to this discovery. Use this to ground your research "
                    f"in what the team already knows."
                    f"{memory_section}"
                )

            # ADR-0063 W3a — inject any expanded research queries from a
            # prior discover-expander dispatch so this attempt's brief
            # answers them explicitly.
            expansion_section = format_queries_for_prompt(expanded_queries or [])
            if expansion_section:
                prompt = f"{prompt}\n\n{expansion_section}"

            def _check_complete(accumulated: str) -> bool:
                if _DISCOVER_END in accumulated:
                    logger.info(
                        "Discovery markers found for issue #%d — terminating",
                        task.id,
                    )
                    return True
                return False

            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": f"discover:attempt-{attempt}"},
                on_output=_check_complete,
                issue_labels=task.tags,
            )

            parsed = self._extract_result(transcript, task.id)
            if parsed:
                result = parsed
            else:
                # Fallback: use raw transcript as research brief
                result.research_brief = self._extract_raw_brief(transcript)
                if not result.research_brief:
                    result.research_brief = (
                        "Discovery agent ran but produced no structured output. "
                        "Raw transcript available in logs."
                    )

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.research_brief = f"Discovery failed: {exc!r}"
            logger.exception(
                "Discovery failed for issue #%d: %s",
                task.id,
                exc,
                extra={"issue": task.id},
            )

        try:
            self._save_transcript(
                f"discover-issue-attempt{attempt}", task.id, transcript
            )
        except OSError:
            logger.warning(
                "Failed to save discovery transcript for issue #%d",
                task.id,
                exc_info=True,
            )

        return result

    async def _evaluate_brief(
        self, task: Task, brief: str, *, guidance: str = ""
    ) -> tuple[bool, str, list[str]]:
        """Dispatch ``discover-completeness`` against *brief*.

        A missing skill (registry disabled) fails open so this extension
        never blocks discovery on its own absence.

        ``guidance`` (ADR-0099 #4) is live operator steering, folded
        fenced into the evaluator prompt via
        :func:`build_discover_completeness_prompt` — the second of
        discover's two prompt-construction sites (the first being
        :meth:`_build_prompt`).

        MockWorld bypass: when the instance carries a ``_mockworld_fake_llm``
        sentinel attribute and the scenario has scripted a coherence verdict
        via :meth:`FakeLLM.script_discover`, the scripted outcome is returned
        in lieu of dispatching the read-only subprocess. This lets sandbox
        scenarios drive the ADR-0063 W3a recovery branch without producing
        a synthetic ``DISCOVER_COMPLETENESS_RESULT`` transcript.
        """
        scripted = _consume_mockworld_discover_script(self, task.id)
        if scripted is not None:
            return scripted

        # MockWorld fail-open (companion to the ``_run_discovery_once``
        # bypass): a scenario that seeded no ``discover`` script must not
        # fall through to a real evaluator subprocess — that spawn wedges
        # the air-gapped sandbox exactly like the main discovery pass
        # (#9796). Scripted verdicts were already consumed above.
        if _mockworld_sentinel_active(self):
            return True, "MockWorld sandbox: no scripted verdict — fail open", []

        skill = next((s for s in BUILTIN_SKILLS if s.name == _SKILL_NAME), None)
        if skill is None:
            return True, f"{_SKILL_NAME} not registered — fail open", []
        prompt = skill.prompt_builder(
            issue_number=task.id,
            issue_title=task.title,
            issue_body=task.body or "",
            brief=brief or "",
            guidance=guidance,
        )
        try:
            transcript = await self._execute(
                self._build_command(),
                prompt,
                self._config.repo_root,
                {"issue": task.id, "source": "discover:evaluator"},
                issue_labels=task.tags,
                # #9998: telemetry keys on the skill name so prompt-efficiency
                # ordering matches the corpus's expected_catcher names; the
                # event source stays "discover:evaluator" for scenario scripts.
                telemetry_source=skill.name,
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "discover-completeness dispatch failed for #%d: %s", task.id, exc
            )
            return True, f"evaluator dispatch failed: {exc!r}", []
        return skill.result_parser(transcript)

    async def _escalate_stuck(
        self, task: Task, summary: str, findings: list[str], attempts: int
    ) -> None:
        """File hitl-escalation / discover-stuck with dedup.

        Dedup key ``discover_runner:{task.id}`` in the shared
        ``hitl_escalations`` set. Closing the escalation issue clears
        the key (per §3.2) so the runner can retry on the next cycle.
        """
        prs: PRPort | None = getattr(self, "_prs", None)
        dedup: DedupStore | None = getattr(self, "_dedup", None)
        key = f"discover_runner:{task.id}"
        if dedup is not None and key in dedup.get():
            logger.info("discover-stuck for #%d already filed (dedup)", task.id)
            return
        if prs is None:
            logger.warning(
                "discover-stuck for #%d but PRManager not bound; logging only. "
                "attempts=%d summary=%s",
                task.id,
                attempts,
                summary,
            )
            return
        body_lines = [
            f"Discover-completeness evaluator rejected {attempts} bounded "
            f"retries for issue #{task.id}.",
            "",
            f"**Last summary:** {summary}",
        ]
        if findings:
            body_lines.append("")
            body_lines.append("**Last findings:**")
            for finding in findings[:10]:
                body_lines.append(f"- {finding}")
        body_lines += [
            "",
            "Action: a human must review the issue body, clarify the "
            "ambiguity that blocked the brief, and either retry Discover "
            "manually or accept the current brief. Closing this issue "
            "clears the dedup key so the runner can retry.",
        ]
        issue_number = await prs.create_issue(
            title=f"[discover-stuck] #{task.id} — {task.title}",
            body="\n".join(body_lines),
            labels=[_ESCALATION_LABEL_HITL, _ESCALATION_LABEL_STUCK],
        )
        if issue_number and dedup is not None:
            dedup.add(key)
            logger.info(
                "Filed discover-stuck escalation #%d for task #%d",
                issue_number,
                task.id,
            )

    def _build_command(self, _worktree_path=None) -> list[str]:  # type: ignore[override]
        """Construct the CLI invocation for discovery research.

        Uses the planner model (opus) for deep thinking — discovery
        needs thorough reasoning, not fast classification.
        """
        return build_agent_command(
            tool=self._config.planner_tool,
            model=self._config.planner_model,
            disallowed_tools="Write,Edit,NotebookEdit",
            effort="max",
        )

    def _build_prompt(self, task: Task, *, guidance: str = "") -> str:
        """Build the discovery research prompt (ADR-0107 general-purpose helper).

        The produced ``research_brief`` must satisfy the
        ``discover-completeness`` rubric (§4.10,
        :func:`discover_completeness.build_discover_completeness_prompt`) —
        named *Intent* / *Affected area* / *Acceptance criteria* /
        *Open questions* / *Known unknowns* sections. Product-specific
        research (competitors, user needs, opportunities) is framed as
        optional, gated on the issue actually being a user-facing feature,
        since ADR-0107 routes ordinary engineering/tooling issues through
        this same helper.

        ``guidance`` (ADR-0099 #4) is live operator steering for this
        issue; folded in fenced via :func:`fenced_steering_guidance`,
        which returns ``""`` when there is no guidance so behavior is
        unchanged when the feature is off.
        """
        prompt = f"""You are conducting discovery research to ground the plan that
follows. The planner routed this issue here because it is low-clarity,
broad, escalated, or has cycled back from a later stage — your job is to
reduce that ambiguity before implementation planning starts.

## Issue #{task.id}: {task.title}

{task.body or "(No description provided)"}

## Your Mission

Your job is NOT to plan implementation. Your job is to produce a
discovery brief the planner can act on directly. Issues land here as
often for being internal engineering/tooling work (a lint rule, a config
knob, a parser fix) as for being user-facing product features — decide
which this is from the issue body before you start researching, and
do not force a "product" framing onto an engineering issue.

## Required Brief Structure

Your ``research_brief`` MUST contain the following five sections, each
under its own markdown heading, in this order, using this exact wording
(an automated rubric parses these headings — do not rename, merge, or
skip any of them, even when a section ends up thin):

### Intent

Restate what is actually being asked and why, in your own words — not a
copy of the issue body. Narrow the scope, name the specific behavior
change requested, and surface anything the issue leaves implicit.

### Affected area

Use Glob/Grep/Read to explore the CODEBASE and name the concrete
touchpoints: files, modules, functions/classes, config fields, or ADRs
this issue would touch. Prefer file paths and symbol names you actually
verified over guesses — if the issue names a file, confirm it (or
correct it if the real touchpoint differs).

### Acceptance criteria

A bulleted list (3+ items). Every bullet MUST name an observable,
testable outcome — a metric, a CLI exit code, a parsed field, a UI
state, a benchmark threshold. Vague aspirations ("it's better", "users
are happier") are not acceptable.

### Open questions

A bulleted list. If the issue text hedges at all ("maybe", "could be",
"not sure", "it depends", "we might", "possibly", "unclear", "tbd",
"optional", "deferred"), you MUST surface at least one concrete open
question grounded in that hedge — do not silently resolve the ambiguity
yourself.

### Known unknowns

What you could not determine from the codebase and issue alone: blocking
dependencies, unresolved design choices, missing config, prerequisite
work that has not landed yet.

Each section needs real content — at least 50 characters of prose, or 3+
bullets. At least one section must add information that is NOT already
stated in the issue body (a file path you found, a related ADR, a
numeric threshold, a constraint) — a brief that only paraphrases the
issue fails review.

## Optional: Product & Market Research

Only when this issue is genuinely a user-facing product feature (not an
internal engineering/tooling change), extend your research with:

- **Competitive landscape** — if you have WebSearch, research existing
  solutions: what they do well, where they fall short, how they position
  and monetize. Cite sources.
- **User needs** — the jobs-to-be-done, friction points, and personas
  affected.
- **Opportunities** — genuinely divergent directions worth a human
  choosing between, each specific, differentiated, and feasible. Only
  list an opportunity if it is a real alternative — do not pad the list
  to hit a count. The planner treats 2+ opportunities as a signal to ask
  a human to pick a direction, so a route with one clear feasible path
  forward should return zero or one opportunities, not manufactured
  choices.

Skip this section entirely (return empty arrays for ``competitors`` /
``user_needs`` / ``opportunities``) for internal engineering/tooling
issues — do not force competitor or persona research onto a lint rule or
config change.

## Required Output

{_DISCOVER_START}

```json
{{
  "issue_number": {task.id},
  "research_brief": "Markdown containing the five required sections: ## Intent / ## Affected area / ## Acceptance criteria / ## Open questions / ## Known unknowns",
  "competitors": ["Competitor — what they do, their core strength, and their key weakness (product-facing issues only)"],
  "user_needs": ["Need — evidence, affected persona, severity (product-facing issues only)"],
  "opportunities": ["Opportunity — why viable, differentiation angle, feasibility assessment (product-facing issues only)"]
}}
```

{_DISCOVER_END}

## Research Quality Standards

- Use Glob/Grep/Read to ground the Affected area section in the real
  codebase — do not guess file paths or symbol names.
- If you have WebSearch/WebFetch and this is a product-facing issue, use
  them; otherwise state "NOTE: Web search unavailable — analysis based on
  general knowledge. Verify before making decisions." and continue
  without it.
- Quality over quantity — 3 deep insights beat 10 shallow bullet points.
- Challenge your own assumptions — what could you be wrong about?

{MEMORY_SUGGESTION_PROMPT}
"""
        plugin_skills_section = format_plugin_skills_for_prompt(
            skills_for_phase(
                "discover",
                discover_plugin_skills(self._config.required_plugins),
                self._config.phase_skills,
            )
        )
        if plugin_skills_section:
            prompt = f"{prompt}\n\n{plugin_skills_section}"
        prompt += fenced_steering_guidance(guidance)
        return prompt

    def _extract_result(
        self, transcript: str, issue_number: int
    ) -> DiscoverResult | None:
        """Extract structured DiscoverResult from agent transcript."""
        # Find content between markers
        start_idx = transcript.find(_DISCOVER_START)
        end_idx = transcript.find(_DISCOVER_END)
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return None

        section = transcript[start_idx:end_idx]

        # Extract JSON block
        match = _JSON_BLOCK_RE.search(section)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
            return DiscoverResult(
                issue_number=issue_number,
                research_brief=data.get("research_brief", ""),
                competitors=data.get("competitors", []),
                user_needs=data.get("user_needs", []),
                opportunities=data.get("opportunities", []),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(
                "Failed to parse discovery JSON for issue #%d",
                issue_number,
                exc_info=True,
            )
            return None

    def _extract_raw_brief(self, transcript: str) -> str:
        """Extract a usable brief from raw transcript when JSON parsing fails."""
        start_idx = transcript.find(_DISCOVER_START)
        end_idx = transcript.find(_DISCOVER_END)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            raw = transcript[start_idx + len(_DISCOVER_START) : end_idx].strip()
            # Remove JSON blocks, keep any plain text
            raw = _JSON_BLOCK_RE.sub("", raw).strip()
            if raw:
                return raw
        return ""
