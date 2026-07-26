"""LLM-driven wiki compilation — synthesize, cross-reference, deduplicate.

This is the "librarian" from Karpathy's LLM Knowledge Base pattern.
Instead of mechanically dumping entries, the compiler uses an LLM to:

1. **Synthesize** — merge redundant entries into consolidated insights
2. **Cross-reference** — add backlinks between related entries across topics
3. **Deduplicate** — identify and merge entries covering the same concept
4. **Resolve contradictions** — flag or resolve conflicting entries

Called periodically by RepoWikiLoop and optionally after large ingests.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from dedup_store import DedupStore
from flows import Edge, Flow, FlowState, KillSwitch, Node, NodeHook
from knowledge_metrics import metrics as _metrics
from prompt_gate_alerts import (
    alert_prompt_gate_block,
    clear_prompt_gate_block,
    is_prompt_gate_blocked,
)
from repo_wiki import (
    DEFAULT_TOPICS,
    WikiEntry,
    _load_tracked_active_entries,
    _mark_tracked_entry_superseded,
    _write_tracked_synthesis_entry,
    synthesis_matches_active_bodies,
)
from wiki_anchor_gate import config_field_vocabulary, has_repo_anchor

_SYNTHESIS_ID_RE = re.compile(r"^(\d+)-")


# ---------------------------------------------------------------------------
# Contradiction-check models
# ---------------------------------------------------------------------------


class ContradictedEntry(BaseModel):
    id: str = Field(description="ULID of the sibling entry that is contradicted")
    reason: str = Field(description="One-sentence explanation")


class ContradictionCheck(BaseModel):
    contradicts: list[ContradictedEntry] = Field(default_factory=list)


class GeneralizationCheck(BaseModel):
    same_principle: bool = False
    generalized_title: str = ""
    generalized_body: str = ""
    confidence: Literal["high", "medium", "low"] = "low"


class CorroborationDecision(BaseModel):
    """Outcome of ``WikiCompiler.dedup_or_corroborate``.

    When ``should_corroborate`` is True, the caller should bump
    ``canonical_path``'s ``corroborations`` counter instead of writing
    the new entry as a sibling. ``canonical_path`` is carried directly
    because ``WikiEntry.id`` is a ULID while filenames use a separate
    per-topic sequential prefix — there's no reliable id → path map.
    """

    should_corroborate: bool = False
    canonical_title: str = ""
    canonical_id: str = ""
    canonical_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


class ADRDraftDecision(BaseModel):
    two_plus_issues: bool = False
    in_tribal: bool = False
    architectural: bool = False
    load_bearing: bool = False
    draft_ok: bool = False
    reason: str = ""


if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from events import EventBus
    from execution import SubprocessRunner
    from repo_wiki import RepoWikiStore
    from tribal_wiki import TribalWikiStore

logger = logging.getLogger("hydraflow.wiki_compiler")

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_COMPILE_TOPIC_PROMPT = """\
You are a technical knowledge librarian maintaining a per-repository wiki.

Below are all current entries in the **{topic}** topic for repository **{repo}**.
Your job is to compile them into a clean, deduplicated set of entries.

## Current entries

{entries_text}

## Voice and structure (read this first — it overrides every other rule)

Each entry's `content` field MUST be **scannable** documentation, not a wall
of prose. Agents and humans read the title to decide whether to read the
entry, then read the entry to apply a rule — both audiences need structure.

**Required shape for every entry — no exceptions, ALL THREE PARTS REQUIRED:**

1. **Rule** (1 sentence): the rule itself, no narrative ramp-up.
2. **Example** (inline code, file path, or 2-3 bullet points): how the
   rule looks in use. Skip ONLY when the rule is purely conceptual.
3. **Why line** (literal markdown `**Why:**` prefix, then 1 sentence):
   the failure mode or constraint the rule prevents. The literal text
   `**Why:**` MUST appear at the start of the closing line — agents
   grep for this marker to extract the rationale. An entry without a
   `**Why:**` line is malformed.

Example of the required format:

> Use `is None` and `is not None` for optional objects.
>
> Example: `if callback is None: return`. Avoid `==` comparison for
> sentinels; custom `__eq__` can hide subtle bugs.
>
> **Why:** Identity checks are O(1) and immune to overridden `__eq__`;
> equality checks against `None` accidentally match falsy values.

**Hard length budget per entry — enforced, not aspirational:**

- `title`: ≤ 80 characters, specific enough that a reader can decide
  relevance from the title alone. Avoid generic labels like "Notes",
  "Findings", "Background", "Concurrency and I/O safety", or any
  multi-rule umbrella title.
- `content`: ≤ 150 words. If the source material exceeds this, **emit
  multiple entries.** A single entry covering "concurrency and I/O
  safety" with 5 distinct rules MUST become 5 separate entries.

**Anti-patterns to avoid:**

- Long single-paragraph dumps with no structure.
- Umbrella entries that consolidate unrelated rules under one title
  (e.g., a "Concurrency and I/O safety" entry covering locks, atomic
  writes, async patterns, and trace context all at once). Each rule
  gets its own entry.
- Retrospective voice ("This entry captures the lesson that…", "We
  learned in PR #N that…"). Write in rule voice ("Use X. Avoid Y.").
- Restating the title in the first sentence.
- Inline JSON or code fences spanning more than 5 lines (link to the
  source instead).

## Repo-specificity requirement (load-bearing — entries are gated on this)

Every entry MUST be grounded in **{repo}** — reference at least one
concrete repo anchor: a `src/*.py` module or file path, a registered
loop/worker/Port/runner/store name (e.g. `RepoWikiLoop`, `WorkspacePort`),
a config field (e.g. `rc_cadence_hours`), an ADR number (e.g. `ADR-0042`),
or a fake/double name (e.g. `FakeGitHub`).

**DROP any entry that reads as generic programming best-practice** — a rule
that would apply verbatim to any Python project and names nothing from this
repo. Examples to DROP, not emit: "Use `is None` for optional sentinels",
"Create a specialized method rather than overloading", "Use portable shell
commands in Alpine containers", "Delete code blocks bottom-to-top." A
downstream deterministic gate rejects anchor-less entries and logs them, so
emitting them wastes the slot — fold their durable, repo-specific corollary
(if any) into an anchored entry instead.

## Compilation rules (apply only after the structure rules above)

1. **Merge true duplicates ONLY**: Two entries are duplicates if they
   state the same rule about the same target. Two entries that touch
   adjacent topics (e.g., "use atomic writes" and "use file locks")
   are NOT duplicates — keep both as separate entries. When in doubt,
   keep separate.
2. **Split umbrella entries**: If an existing entry packs multiple
   distinct rules under one title, split it into one entry per rule
   even though the input was a single entry. Splitting is preferred
   over merging.
3. **Cross-reference**: If an entry relates to entries in other topics
   ({other_topics}), add a brief note like "See also: [topic] — [entry
   title]" inside the content.
4. **Resolve contradictions**: If entries contradict each other, keep
   the more recent one and note the resolution.
5. **Remove stale content**: If an entry's insight has been superseded
   by a newer one, drop it.
6. **Preserve source attribution**: Keep source_issue and source_type
   from the original entries when an output entry maps 1:1 to a single
   input. For split or genuinely-merged entries, use source_type
   "compiled" and source_issue null.
7. **Declare correspondence**: Every output entry MUST set
   "supersedes_ids" to the input entry id(s) — see the `(id: ...)`
   annotation next to each entry's title above — that it directly
   replaces. A 1:1 rewrite lists that one id. A merge lists every id
   it merges. A split of one umbrella input into several outputs
   lists that same input id on each split output. Do NOT list an id
   from an input this output doesn't actually draw from, and do NOT
   invent ids not shown above — readers follow this pointer from the
   old entry to its replacement, so a wrong id misdirects them to an
   unrelated topic.

## Expected entry-count behavior

- For a topic with N coherent input entries, expect roughly N output
  entries (give or take a couple from true-duplicate merges).
- A 50% reduction in entry count almost always means under-splitting.
  If your output has ≤ half the input count, double-check that you
  haven't created umbrella entries.

## Output format

Return a JSON array of compiled entries. Each entry must be a JSON object with these fields:
- "title": string (≤ 80 chars, descriptive — see length budget above)
- "content": string (rule + example + Why; ≤ 150 words)
- "source_type": string (plan, implement, review, hitl, or "compiled")
- "source_issue": number or null
- "stale": false
- "supersedes_ids": array of strings — the input entry ids (from the
  "(id: ...)" annotations above) this output entry replaces. See rule 7.

Return ONLY the JSON array, no other text.
"""

_CONTRADICTION_PROMPT = """\
You are a technical knowledge librarian. A new wiki entry has been written to the
**{topic}** topic of repository **{repo}**. Identify which existing sibling entries
(if any) it contradicts — meaning the new entry's advice is incompatible with an
existing entry's advice, not merely different in emphasis.

## New entry

title: {new_title}
content:
{new_content}

## Existing sibling entries (current only)

{siblings_text}

## Instructions

Return a JSON object with one key, "contradicts", mapping to an array of
{{"id": <sibling_id>, "reason": <one-sentence>}} objects.

Only include a sibling if the new entry **directly contradicts** it — e.g.,
"use X" vs "never use X", or "Python 3.11 minimum" vs "Python 3.10 minimum".
Do NOT include siblings that are merely related or complementary.

Return ONLY the JSON object, no other text.

Example valid outputs:
  {{"contradicts": []}}
  {{"contradicts": [{{"id":"01HQ...","reason":"new entry says X, this one said not-X"}}]}}
"""

_GENERALIZATION_PROMPT = """\
You are a technical knowledge librarian comparing two wiki entries from
different repositories, both on topic **{topic}**. Decide whether they
encode the **same underlying principle** (not merely the same keywords).

## Entry A (repo: {repo_a})

title: {title_a}
content:
{content_a}

## Entry B (repo: {repo_b})

title: {title_b}
content:
{content_b}

## Instructions

Return a JSON object with these keys:
- same_principle: bool — true only if both entries advise the same rule in
  a way that would generalize across any Python project
- generalized_title: str — if same_principle is true, a short neutral title
- generalized_body: str — if same_principle is true, merged content that drops
  repo-specific details
- confidence: "high" | "medium" | "low" — how sure you are

Return ONLY the JSON object, no other text.

Example outputs:
  {{"same_principle": false, "generalized_title": "", "generalized_body": "", "confidence": "low"}}
  {{"same_principle": true, "generalized_title": "Pytest async mode", "generalized_body": "Configure pytest-asyncio with mode=auto.", "confidence": "high"}}
"""

_SYNTHESIZE_INGEST_PROMPT = """\
You are a technical knowledge librarian. A {source_type} phase just completed for \
issue #{issue_number} in repository {repo}.

## Raw phase output

{raw_text}

## Instructions

Extract 1-5 durable knowledge entries from this output. Focus on:
- Architecture decisions or patterns discovered
- Gotchas, pitfalls, or edge cases encountered
- Testing strategies or conventions learned
- Dependency quirks or version constraints found
- Reusable patterns or anti-patterns identified

Skip ephemeral details (specific variable names, one-off debugging steps).
Each entry should be a standalone insight useful for future work on this repo.

## Voice and structure (load-bearing — do not skip)

Each entry's `content` field MUST be **scannable** documentation, not a wall
of prose. Agents and humans read the title to decide whether to read the
entry, then read the entry to apply a rule — both audiences need structure.

Required shape for each entry:

- Open with a one-sentence rule statement (no narrative ramp-up).
- Follow with a short example (inline code, file path, or 2-3 bullet
  points) showing the rule in use. If the rule is purely conceptual,
  skip the example.
- Close with a `**Why:**` line in one sentence, naming the failure mode
  or constraint the rule prevents.

Hard length budget per entry:

- `title`: ≤ 80 characters, specific enough that a reader can decide
  relevance from the title alone (avoid generic labels like "Notes",
  "Findings", "Background", or "{source_type} from #{issue_number}").
- `content`: ≤ 150 words. If the source material exceeds this, **emit
  multiple entries** rather than producing a single long blob.

Anti-patterns to avoid:

- Long single-paragraph dumps with no structure.
- Retrospective voice ("This entry captures the lesson that…", "We
  learned in PR #N that…"). Write in rule voice ("Use X. Avoid Y.").
- Restating the title in the first sentence.
- Inline JSON or code fences spanning more than 5 lines (link to the
  source instead).

## Repo-specificity requirement (load-bearing — entries are gated on this)

Every entry MUST be grounded in **{repo}** — reference at least one
concrete repo anchor: a `src/*.py` module or file path, a registered
loop/worker/Port/runner/store name (e.g. `RepoWikiLoop`), a config field
(e.g. `rc_cadence_hours`), an ADR number (e.g. `ADR-0042`), or a fake name
(e.g. `FakeGitHub`). **Skip any insight that reads as generic programming
best-practice** — a rule that would apply verbatim to any Python project
and names nothing from this repo. A downstream deterministic gate rejects
anchor-less entries, so emitting them wastes the slot.

## Output format

Return a JSON array of entries. Each entry must be:
- "title": string (≤ 80 chars, descriptive — see length budget above)
- "content": string (rule + example + Why; ≤ 150 words)
- "source_type": "{source_type}"
- "source_issue": {issue_number}

Return ONLY the JSON array, no other text.
"""


_ADR_DRAFT_JUDGE_PROMPT = """\
You are a technical knowledge librarian evaluating whether a pattern rises to
ADR-worthy architectural status. Review the proposed ADR draft below and
answer two questions strictly:

1. **architectural**: does it change a system-level invariant (loop topology,
   state machine, persistence layout, promotion flow, module boundary)?
   Operational tips, style conventions, and per-phase workflows are NOT
   architectural.
2. **load_bearing**: if this decision were reversed tomorrow, would multiple
   components need to change?

## Proposed ADR

title: {title}
context: {context}
decision: {decision}
consequences: {consequences}

Return ONLY a JSON object:
  {{"architectural": <bool>, "load_bearing": <bool>, "reason": "<1 sentence>"}}
"""


# ---------------------------------------------------------------------------
# ADR draft suggestion parser
# ---------------------------------------------------------------------------

_ADR_DRAFT_HEADER_RE = re.compile(r"^ADR_DRAFT_SUGGESTION:\s*$", re.MULTILINE)


def parse_adr_draft_suggestion(transcript: str) -> dict | None:
    """Parse an ADR_DRAFT_SUGGESTION block from a transcript.

    Returns a dict with keys: title, context, decision, consequences,
    evidence_issues (list[int]), evidence_wiki_entries (list[str]).
    Returns None when no block is found or parsing fails.
    """
    header = _ADR_DRAFT_HEADER_RE.search(transcript)
    if header is None:
        return None

    tail = transcript[header.end() :]
    fields: dict[str, Any] = {
        "title": "",
        "context": "",
        "decision": "",
        "consequences": "",
        "evidence_issues": [],
        "evidence_wiki_entries": [],
    }
    current_key: str | None = None
    in_evidence = False
    for line in tail.split("\n"):
        if not line.strip():
            if current_key in {"title"}:
                current_key = None
            continue
        stripped = line.rstrip()
        # Field heading like "title: Foo"
        m = re.match(
            r"^(title|context|decision|consequences|evidence):\s*(.*)$", stripped
        )
        if m:
            key = m.group(1)
            rest = m.group(2).strip()
            if key == "evidence":
                in_evidence = True
                current_key = None
                continue
            in_evidence = False
            current_key = key
            fields[key] = rest
            continue

        if in_evidence:
            sm = re.match(r"^\s*-\s*issue:\s*(\d+)\s*$", stripped)
            if sm:
                fields["evidence_issues"].append(int(sm.group(1)))
                continue
            sm = re.match(r"^\s*-\s*wiki_entry:\s*([0-9A-Z]{26})\s*$", stripped)
            if sm:
                fields["evidence_wiki_entries"].append(sm.group(1))
                continue
            # End of evidence list (non-bullet line that isn't indented)
            if not line.startswith((" ", "\t")):
                in_evidence = False

        if current_key and line.startswith("  "):
            fields[current_key] = (fields[current_key] + " " + stripped.strip()).strip()

    if not fields["title"]:
        return None
    return fields


# ---------------------------------------------------------------------------
# Compile flow (P1 of #10682, ADR-0111)
# ---------------------------------------------------------------------------


def _flow_aborted(state: FlowState) -> bool:
    """Edge guard: route to the terminal when a node has signalled abort.

    Nodes set ``state['_stop']`` on any fail-closed early-exit (too few
    inputs, model failure, empty / anchor-less / byte-identical output) so
    the graph routes straight to ``done`` without running ``validate`` — the
    only node that writes.
    """
    return bool(state.get("_stop"))


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class WikiCompiler:
    """LLM-powered wiki compilation and synthesis."""

    @staticmethod
    def _parse_contradiction_output(raw: str) -> ContradictionCheck:
        """Parse contradiction-check LLM output. Never raises."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return ContradictionCheck()

        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return ContradictionCheck()

        if not isinstance(obj, dict) or "contradicts" not in obj:
            return ContradictionCheck()

        try:
            return ContradictionCheck.model_validate(obj)
        except Exception:  # noqa: BLE001
            return ContradictionCheck()

    @staticmethod
    def _parse_generalization_output(raw: str) -> GeneralizationCheck:
        """Parse generalization-check LLM output. Never raises."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return GeneralizationCheck()
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return GeneralizationCheck()
        if not isinstance(obj, dict):
            return GeneralizationCheck()
        try:
            return GeneralizationCheck.model_validate(obj)
        except Exception:  # noqa: BLE001
            return GeneralizationCheck()

    def __init__(
        self,
        config: HydraFlowConfig,
        runner: SubprocessRunner,
        credentials: Credentials | None = None,
        event_bus: EventBus | None = None,
        gate_block_dedup: DedupStore | None = None,
    ) -> None:
        self._config = config
        self._runner = runner
        if credentials is None:
            from config import Credentials as _Creds  # noqa: PLC0415

            credentials = _Creds()
        self._credentials = credentials
        # Prompt-gate block escalation (#9734 finding 3): without a bus the
        # ERROR log still fires; the SYSTEM_ALERT is simply skipped.
        self._bus = event_bus
        self._gate_block_dedup = gate_block_dedup or DedupStore(
            "prompt_gate_blocked",
            config.data_root / "dedup" / "prompt_gate_blocked.json",
        )

    async def compile_topic(
        self,
        store: RepoWikiStore,
        repo: str,
        topic: str,
        other_topics: list[str] | None = None,
    ) -> int:
        """Compile all entries in a single topic using the LLM.

        Reads current entries, asks the LLM to synthesize/deduplicate,
        then writes the compiled entries back.  Returns the number of
        entries after compilation (0 on failure).
        """

        repo_dir = store._repo_dir(repo)
        topic_path = repo_dir / f"{topic}.md"
        entries = store._load_topic_entries(topic_path)

        if len(entries) < 2:
            return len(entries)  # nothing to compile

        entries_text = "\n\n".join(
            f"### {e.title} (id: {e.id})\n{e.content}\n"
            f"Source: #{e.source_issue or 'N/A'} ({e.source_type})\n"
            f"Created: {e.created_at}"
            for e in entries
        )

        if other_topics is None:
            other_topics = [t for t in DEFAULT_TOPICS if t != topic]

        prompt = _COMPILE_TOPIC_PROMPT.format(
            topic=topic,
            repo=repo,
            entries_text=entries_text,
            other_topics=", ".join(other_topics),
        )

        raw = await self._call_model(prompt)
        if raw is None:
            return len(entries)

        compiled = self._parse_entries(raw)
        if not compiled:
            logger.warning(
                "Wiki compile for %s/%s produced no valid entries — keeping originals",
                repo,
                topic,
            )
            return len(entries)

        # Repo-specificity gate (#9954): drop anchor-less platitudes so
        # synthesis never overwrites the topic page with generic best
        # practice. Empty result → keep the originals untouched.
        compiled = self._filter_anchored_entries(
            compiled, repo=repo, topic=topic, context="compile"
        )
        if not compiled:
            logger.info(
                "Wiki compile for %s/%s: all synthesized entries lacked a "
                "repo anchor — keeping originals",
                repo,
                topic,
            )
            return len(entries)

        store._write_topic_page(topic_path, topic, compiled)
        store._rebuild_index(repo)
        store._append_log(
            repo,
            "compile",
            {
                "topic": topic,
                "before": len(entries),
                "after": len(compiled),
            },
        )

        logger.info(
            "Wiki compile %s/%s: %d entries → %d",
            repo,
            topic,
            len(entries),
            len(compiled),
        )
        return len(compiled)

    async def compile_topic_tracked(
        self,
        tracked_root: Path,
        repo: str,
        topic: str,
        *,
        other_topics: list[str] | None = None,
    ) -> int:
        """Tracked-layout counterpart of ``compile_topic``.

        Reads ``status: active`` per-entry files in
        ``{tracked_root}/{repo}/{topic}/*.md``, asks the LLM to
        synthesize / deduplicate, then:

        - Writes each compiled entry as a new per-entry file with
          ``source_phase: synthesis`` under a ``synthesis-<timestamp>``
          suffix so the filename doesn't collide with issue-tagged
          entries.
        - Flips every input entry's ``status`` to ``superseded`` with a
          ``superseded_by`` pointer to the synthesis entry that actually
          replaces it, per the LLM's own ``supersedes_ids`` declaration
          (see ``_resolve_supersession_ids``) — not a blanket pointer to
          every synthesis entry regardless of topical match (#10566).

        Returns the number of compiled entries written (0 if the LLM
        call failed or the topic had fewer than 2 active entries).

        The stale-flag path already writes to the tracked layout (Phase
        7), so combining this method with ``_maybe_open_maintenance_pr``
        lets ``RepoWikiLoop`` emit complete maintenance PRs without
        needing a separate synthesis sub-loop.

        Since P1 of #10682 (ADR-0111) the multi-step compile runs as an
        explicit ``src.flows.Flow`` — ``extract -> verify -> synthesize ->
        validate`` — built by :meth:`_build_compile_flow`. Behavior and the
        return contract are unchanged; the steps are just no longer inlined.
        """
        flow = self._build_compile_flow()
        state: FlowState = {
            "tracked_root": tracked_root,
            "repo": repo,
            "topic": topic,
            "other_topics": other_topics,
            "result": 0,
        }
        result = await flow.run(state)
        return int(result.state["result"])

    def _build_compile_flow(
        self,
        *,
        checkpoint: NodeHook | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> Flow:
        """Build the tracked-compile DAG (P1 of #10682, ADR-0111).

        The straight-line compile is re-expressed as an explicit flow:
        ``extract -> verify -> synthesize -> validate`` with a terminal
        ``done`` sink. Every fail-closed abort (too few inputs, model
        failure, empty / anchor-less / byte-identical output) routes straight
        to ``done``, so ``validate`` — the only node that writes — runs
        exclusively on a genuine, anchored, non-no-op synthesis. The LLM call
        lives inside ``synthesize`` alone (the actuator boundary); routing
        between nodes is deterministic.

        ``checkpoint`` / ``kill_switch`` stay injected per ADR-0111 so the
        primitive's persistence + halt seams are wired-through and testable.
        The production entry runs without a checkpoint: a single-shot compile
        needs no resume, and writing one would be a new on-disk side effect
        this parity-gated, no-flag refactor must not introduce. Per-node
        ``on_node`` event wiring is deferred to a later phase per ADR-0111.
        """
        return Flow(
            nodes=[
                Node("extract", self._flow_extract, kind="gate"),
                Node("verify", self._flow_verify),
                Node("synthesize", self._flow_synthesize, kind="gate"),
                Node("validate", self._flow_validate),
                Node("done", self._flow_done),
            ],
            edges=[
                # First-match-wins: an aborted node skips straight to the sink.
                Edge("extract", "done", when=_flow_aborted),
                Edge("extract", "verify"),
                Edge("verify", "synthesize"),
                Edge("synthesize", "done", when=_flow_aborted),
                Edge("synthesize", "validate"),
                Edge("validate", "done"),
            ],
            entry="extract",
            checkpoint=checkpoint,
            kill_switch=kill_switch,
        )

    async def _flow_extract(self, state: FlowState) -> FlowState:
        """Load the topic's active tracked entries (#10682 extract node).

        Fewer than two active entries means there is nothing to compile:
        abort to the terminal so no model call is ever spent.
        """

        topic_dir = state["tracked_root"] / state["repo"] / state["topic"]
        active_entries = _load_tracked_active_entries(topic_dir)
        state["topic_dir"] = topic_dir
        state["active_entries"] = active_entries
        if len(active_entries) < 2:
            state["_stop"] = True
        return state

    async def _flow_verify(self, state: FlowState) -> FlowState:
        """Pin shipped-claim provenance from the inputs (#10682 verify node).

        Unions ``fixed_in_pr`` / ``code_refs`` across the active sources up
        front (#10590) so the value is captured from the inputs before the
        LLM can drop it; ``validate`` applies it to the synthesized entries.
        Pure over ``active_entries`` — no side effects, no I/O — so computing
        it here rather than on the write path is behavior-preserving.
        """
        union_pr, union_refs = self._union_shipped_claim_provenance(
            state["active_entries"]
        )
        state["union_pr"] = union_pr
        state["union_refs"] = union_refs
        return state

    async def _flow_synthesize(self, state: FlowState) -> FlowState:
        """Run the LLM compile and gate its output (#10682 synthesize node).

        The single actuator: build the prompt, call the model, parse, then
        apply the repo-anchor gate (#9954) and the byte-identity no-op guard
        (#10573). Any failure or empty / anchor-less / no-op result aborts to
        the terminal, keeping the originals untouched.
        """

        active_entries = state["active_entries"]
        repo = state["repo"]
        topic = state["topic"]
        other_topics = state["other_topics"]

        entries_text = "\n\n".join(
            f"### {e['title']} (id: {e['id']})\n{e['body']}\n"
            f"Source: #{e['source_issue'] or 'N/A'} ({e['source_phase']})\n"
            f"Created: {e['created_at']}"
            for e in active_entries
        )

        if other_topics is None:
            other_topics = [t for t in DEFAULT_TOPICS if t != topic]

        prompt = _COMPILE_TOPIC_PROMPT.format(
            topic=topic,
            repo=repo,
            entries_text=entries_text,
            other_topics=", ".join(other_topics),
        )

        raw = await self._call_model(prompt)
        if raw is None:
            state["_stop"] = True
            return state

        compiled = self._parse_entries(raw)
        if not compiled:
            logger.warning(
                "Wiki compile_tracked for %s/%s produced no valid entries — "
                "keeping originals",
                repo,
                topic,
            )
            state["_stop"] = True
            return state

        # Repo-specificity gate (#9954): drop anchor-less platitudes before
        # they are written as synthesis entries. Keeping originals when the
        # gate empties the batch is the fail-safe — never supersede the
        # inputs with nothing.
        compiled = self._filter_anchored_entries(
            compiled, repo=repo, topic=topic, context="compile_tracked"
        )
        if not compiled:
            logger.info(
                "Wiki compile_tracked for %s/%s: all synthesized entries "
                "lacked a repo anchor — keeping originals",
                repo,
                topic,
            )
            state["_stop"] = True
            return state

        # Byte-identity no-op guard (#10573): if the synthesized bodies are
        # byte-identical to the current active set, writing them would only
        # mint new ids and supersede the originals with exact copies —
        # unbounded id growth and a permanently churning maintenance PR.
        # Skip re-emission when nothing actually changed; a genuine edit
        # (added / removed / edited entry) still flows through below.
        if synthesis_matches_active_bodies(active_entries, compiled):
            logger.info(
                "Wiki compile_tracked %s/%s: synthesized output byte-identical "
                "to active set — skipping re-emission (no new ids)",
                repo,
                topic,
            )
            state["_stop"] = True
            return state

        state["compiled"] = compiled
        return state

    async def _flow_validate(self, state: FlowState) -> FlowState:
        """Apply provenance, then persist the synthesis (#10682 validate node).

        Carries the pinned shipped-claim provenance onto every output
        (#10590), resolves per-entry supersession (#10566), writes each
        synthesis entry, and flips every input to ``superseded``. The only
        node that mutates the tracked layout, and it runs only after
        ``synthesize`` produced a genuine, anchored, non-no-op result.
        """

        active_entries = state["active_entries"]
        compiled = state["compiled"]
        repo = state["repo"]
        topic = state["topic"]
        topic_dir = state["topic_dir"]
        union_pr = state["union_pr"]
        union_refs = state["union_refs"]

        # Shipped-claim provenance union (#10590): the LLM is not guaranteed
        # to echo the source entries' fixed_in_pr / code_refs, so carry the
        # pinned union (captured in ``verify``) deterministically onto every
        # synthesized entry. Promotion merges / splits entries, so the
        # source→synthesis mapping is not 1:1; unioning the whole superseded
        # set onto each output over-approximates but never DROPS a shipped
        # claim — under-reporting is the bug, and extra valid code_refs only
        # make the downstream verifier corroborate more readily.
        if union_pr is not None or union_refs:
            for entry in compiled:
                entry.fixed_in_pr = union_pr
                entry.code_refs = union_refs

        per_entry_supersedes = self._resolve_supersession_ids(active_entries, compiled)
        synthesis_paths: list[Path] = []
        for entry, supersedes in zip(compiled, per_entry_supersedes, strict=True):
            path = _write_tracked_synthesis_entry(
                topic_dir,
                entry=entry,
                topic=topic,
                supersedes=supersedes,
            )
            synthesis_paths.append(path)

        if synthesis_paths:
            m = _SYNTHESIS_ID_RE.match(synthesis_paths[0].name)
            primary_id = m.group(1) if m else "unknown"

            superseded_by: dict[str, str] = {}
            for path, supersedes in zip(
                synthesis_paths, per_entry_supersedes, strict=True
            ):
                sm = _SYNTHESIS_ID_RE.match(path.name)
                new_id = sm.group(1) if sm else "unknown"
                for old_id in supersedes:
                    superseded_by.setdefault(old_id, new_id)

            for entry in active_entries:
                new_id = (
                    superseded_by.get(entry["id"]) if entry["id"] else None
                ) or primary_id
                _mark_tracked_entry_superseded(
                    Path(entry["path"]), superseded_by=new_id
                )

        logger.info(
            "Wiki compile_tracked %s/%s: %d active → %d synthesis",
            repo,
            topic,
            len(active_entries),
            len(compiled),
        )
        state["result"] = len(compiled)
        return state

    @staticmethod
    async def _flow_done(state: FlowState) -> FlowState:
        """Terminal sink for the compile flow (#10682).

        A no-op join point so every path — the four-node happy walk and each
        fail-closed abort — ends at one observable terminal carrying the
        final ``result`` count.
        """
        return state

    async def detect_contradictions(
        self,
        *,
        new_entry: WikiEntry,
        siblings: list[WikiEntry],
        repo: str,
    ) -> ContradictionCheck:
        """Ask the LLM which siblings (if any) the new entry contradicts.

        ``siblings`` must already be filtered to ``current`` entries on the
        same topic. Returns an empty ContradictionCheck on LLM failure or if
        siblings is empty — never raises.
        """
        if not siblings:
            return ContradictionCheck()

        siblings_text = "\n\n".join(
            f"id: {s.id}\ntitle: {s.title}\ncontent:\n{s.content}" for s in siblings
        )
        prompt = _CONTRADICTION_PROMPT.format(
            topic=new_entry.topic or "unknown",
            repo=repo,
            new_title=new_entry.title,
            new_content=new_entry.content,
            siblings_text=siblings_text,
        )

        raw = await self._call_model(prompt)
        if raw is None:
            return ContradictionCheck()
        return self._parse_contradiction_output(raw)

    async def generalize_pair(
        self,
        *,
        entry_a: WikiEntry,
        entry_b: WikiEntry,
        topic: str,
    ) -> GeneralizationCheck:
        """Ask the LLM whether two entries encode the same principle.

        Returns an empty GeneralizationCheck on LLM failure — never raises.
        Caller decides whether to act on ``same_principle`` given
        ``confidence``.
        """
        prompt = _GENERALIZATION_PROMPT.format(
            topic=topic,
            repo_a=entry_a.source_repo or "unknown",
            title_a=entry_a.title,
            content_a=entry_a.content,
            repo_b=entry_b.source_repo or "unknown",
            title_b=entry_b.title,
            content_b=entry_b.content,
        )
        raw = await self._call_model(prompt)
        if raw is None:
            return GeneralizationCheck()
        return self._parse_generalization_output(raw)

    async def dedup_or_corroborate(
        self,
        *,
        repo_slug: str,
        entry: WikiEntry,
        existing_entries: list[tuple[WikiEntry, Path]],
        topic: str,
        min_confidence: Literal["medium", "high"] = "medium",
    ) -> CorroborationDecision:
        """Use ``generalize_pair`` to decide whether ``entry`` is a
        re-discovery of an existing active entry.

        ``existing_entries`` carries ``(WikiEntry, Path)`` tuples so the
        path travels with the entry — the caller then bumps the
        canonical's ``corroborations`` counter without re-walking the
        topic directory. Stops at the first confident match: we don't
        need to rank matches, just detect one.

        Returns an empty decision (``should_corroborate=False``) when
        there are no existing entries, or no match hits the confidence
        floor.
        """
        del repo_slug  # carried for symmetry with other compiler methods
        if not existing_entries:
            return CorroborationDecision()
        acceptable = {"high"} if min_confidence == "high" else {"high", "medium"}
        for existing, existing_path in existing_entries:
            check = await self.generalize_pair(
                entry_a=entry, entry_b=existing, topic=topic
            )
            if check.same_principle and check.confidence in acceptable:
                return CorroborationDecision(
                    should_corroborate=True,
                    canonical_title=existing.title,
                    canonical_id=existing.id,
                    canonical_path=existing_path,
                )
        return CorroborationDecision()

    async def judge_adr_draft(
        self,
        *,
        suggestion: dict,
        tribal: TribalWikiStore,
    ) -> ADRDraftDecision:
        """Evaluate the 4 gates for an ADR_DRAFT_SUGGESTION."""
        _metrics.increment("adr_drafts_judged")
        decision = ADRDraftDecision()

        # Gate 1 — evidence list has ≥2 distinct issues
        issues = suggestion.get("evidence_issues", [])
        decision.two_plus_issues = len(set(issues)) >= 2
        if not decision.two_plus_issues:
            decision.reason = "needs ≥2 distinct issues as evidence"
            return decision

        # Gate 2 — at least one cited wiki entry lives in tribal
        wiki_ids = suggestion.get("evidence_wiki_entries", [])
        if not wiki_ids:
            decision.reason = "no tribal wiki entry cited"
            return decision

        tribal_ids: set[str] = set()
        tribal_repo_dir = tribal.repo_dir()
        for topic_name in DEFAULT_TOPICS:
            topic_path = tribal_repo_dir / f"{topic_name}.md"
            if topic_path.exists():
                for entry in tribal.load_topic_entries(topic_path):
                    tribal_ids.add(entry.id)
        decision.in_tribal = any(wid in tribal_ids for wid in wiki_ids)
        if not decision.in_tribal:
            decision.reason = "referenced wiki entry not present in tribal store"
            return decision

        # Gates 3 + 4 (LLM)
        prompt = _ADR_DRAFT_JUDGE_PROMPT.format(
            title=suggestion.get("title", ""),
            context=suggestion.get("context", ""),
            decision=suggestion.get("decision", ""),
            consequences=suggestion.get("consequences", ""),
        )
        raw = await self._call_model(prompt)
        if raw is None:
            decision.reason = "llm unavailable"
            return decision
        parsed = self._parse_adr_judge_output(raw)
        decision.architectural = bool(parsed.get("architectural", False))
        decision.load_bearing = bool(parsed.get("load_bearing", False))
        decision.reason = str(parsed.get("reason", ""))

        decision.draft_ok = (
            decision.two_plus_issues
            and decision.in_tribal
            and decision.architectural
            and decision.load_bearing
        )
        return decision

    @staticmethod
    def _parse_adr_judge_output(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return {}
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return obj if isinstance(obj, dict) else {}

    async def synthesize_ingest(
        self,
        repo: str,
        issue_number: int,
        source_type: str,
        raw_text: str,
    ) -> list[WikiEntry]:
        """Use the LLM to extract knowledge entries from raw phase output.

        Instead of mechanical section parsing, the LLM identifies durable
        insights and produces structured entries.  Returns an empty list
        on failure.
        """
        if not raw_text or len(raw_text) < 100:
            return []

        # Cap input to avoid token limits
        truncated = raw_text[:20_000]

        prompt = _SYNTHESIZE_INGEST_PROMPT.format(
            source_type=source_type,
            issue_number=issue_number,
            repo=repo,
            raw_text=truncated,
        )

        raw = await self._call_model(prompt)
        if raw is None:
            return []

        entries = self._parse_entries(raw)
        logger.info(
            "Wiki synthesize %s #%d (%s): %d entries extracted",
            repo,
            issue_number,
            source_type,
            len(entries),
        )
        return entries

    async def _call_model(self, prompt: str) -> str | None:
        """Call the configured CLI backend for wiki compilation.

        Routes through ``run_lightweight_agent`` so the spawn is
        cost-visible (PromptTelemetry, source="wiki_compilation") and
        pauses on credit exhaustion. ``CreditExhaustedError`` propagates;
        all other errors are logged and swallowed (returns None).
        """
        from runner_utils import run_lightweight_agent  # noqa: PLC0415

        try:
            result = await run_lightweight_agent(
                runner=self._runner,
                config=self._config,
                tool=self._config.wiki_compilation_tool,
                model=self._config.wiki_compilation_model,
                provider=self._config.wiki_compilation_provider,
                prompt=prompt,
                source="wiki_compilation",
                timeout=self._config.wiki_compilation_timeout,
                gh_token=self._credentials.gh_token,
            )
            if result.returncode != 0:
                if is_prompt_gate_blocked(result.stderr):
                    # A gate block is a persistent policy misconfiguration,
                    # not a transient failure: every tick re-blocks, so a
                    # soft warn would be a PERMANENT silent no-op (#9734
                    # review finding 3). Escalate: ERROR + one SYSTEM_ALERT.
                    await alert_prompt_gate_block(
                        dedup=self._gate_block_dedup,
                        event_bus=self._bus,
                        source="wiki_compilation",
                        repo=self._config.repo or "",
                        detail=result.stderr[:200],
                    )
                    return None
                logger.warning(
                    "Wiki compilation model failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:200],
                )
                return None
            clear_prompt_gate_block(self._gate_block_dedup, "wiki_compilation")
            return result.stdout if result.stdout else None
        except TimeoutError:
            logger.warning("Wiki compilation model timed out")
            return None
        except (OSError, FileNotFoundError, NotImplementedError) as exc:
            logger.warning("Wiki compilation model unavailable: %s", exc)
            return None

    @staticmethod
    def _dedup_known_ids(ids: list[str], known_ids: set[str]) -> list[str]:
        """De-dup ``ids`` (order preserved) and drop any not in ``known_ids``.

        Guards ``_resolve_supersession_ids`` against two LLM failure
        modes: a hallucinated id not present in the input list, and a
        repeated id within a single entry's own ``supersedes_ids``.
        """
        seen: set[str] = set()
        out: list[str] = []
        for old_id in ids:
            if old_id in known_ids and old_id not in seen:
                seen.add(old_id)
                out.append(old_id)
        return out

    @staticmethod
    def _resolve_supersession_ids(
        active_entries: list[dict[str, Any]],
        compiled: list[WikiEntry],
    ) -> list[list[str]]:
        """Map each ``compiled`` entry to the old entry ids it supersedes.

        Returns a list aligned index-for-index with ``compiled``. Honors
        the LLM's own ``supersedes_ids`` declaration per entry (deduped,
        filtered to ids that actually exist in ``active_entries``)
        instead of blanket-linking every synthesis entry to every input
        entry — that cartesian mapping broke topical continuity in the
        wiki's supersedes/superseded_by graph (#10566): five unrelated
        old entries all pointed at one new entry, and every new entry
        claimed to supersede all five.

        An old id nobody explicitly claims (the LLM omitted the tag for
        it, or a compilation rule dropped it as stale with no direct
        successor) is folded onto the first compiled entry, so every
        input still ends up superseded by *something* rather than left
        dangling. Multiple entries legitimately claiming the same old id
        (an umbrella entry split across several outputs) is not an
        error — each keeps that id in its own ``supersedes`` list; only
        the ``superseded_by`` pointer on the old entry itself picks one
        canonical winner (first-claim, by output order).
        """
        known_ids = {e["id"] for e in active_entries if e["id"]}
        per_entry = [
            WikiCompiler._dedup_known_ids(entry.supersedes_ids, known_ids)
            for entry in compiled
        ]
        claimed = {old_id for ids in per_entry for old_id in ids}
        orphans = [
            e["id"] for e in active_entries if e["id"] and e["id"] not in claimed
        ]
        if orphans and per_entry:
            per_entry[0] = per_entry[0] + [o for o in orphans if o not in per_entry[0]]
        return per_entry

    @staticmethod
    def _union_shipped_claim_provenance(
        active_entries: list[dict[str, Any]],
    ) -> tuple[str | None, tuple[str, ...]]:
        """Union the shipped-claim provenance across the superseded sources
        (issue #10590).

        Returns ``(fixed_in_pr, code_refs)`` where ``fixed_in_pr`` is an
        order-preserving, de-duplicated, comma-joined string of every
        distinct non-empty source PR (or ``None`` when none carry one), and
        ``code_refs`` is the order-preserving, de-duplicated tuple of every
        source ``code_ref``. Deterministic — no LLM involved — so a
        synthesized entry can never silently drop a source's shipped claim
        during promotion.

        A source ``fixed_in_pr`` may itself be a comma-joined *compound* of
        several PRs — any prior synthesis round emits one, since this method
        joins the union with commas. An N-to-1 merge that folds such a
        compound source in alongside a sibling sharing one of its PRs must
        still land each distinct PR exactly once. So the union splits on
        commas and de-dups at individual-PR granularity, symmetric with
        ``code_refs`` below; whole-string dedup instead re-emitted a shared
        PR twice and never treated the compound's embedded PRs as
        first-class, distinct references (#10655).
        """
        prs: list[str] = []
        seen_pr: set[str] = set()
        refs: list[str] = []
        seen_ref: set[str] = set()
        for entry in active_entries:
            raw_pr = entry.get("fixed_in_pr")
            for token in raw_pr.split(",") if isinstance(raw_pr, str) else ():
                pr = token.strip()
                if pr and pr not in seen_pr:
                    seen_pr.add(pr)
                    prs.append(pr)
            for ref in entry.get("code_refs") or ():
                cleaned = ref.strip() if isinstance(ref, str) else ""
                if cleaned and cleaned not in seen_ref:
                    seen_ref.add(cleaned)
                    refs.append(cleaned)
        fixed_in_pr = ",".join(prs) if prs else None
        return fixed_in_pr, tuple(refs)

    @staticmethod
    def _filter_anchored_entries(
        entries: list[WikiEntry],
        *,
        repo: str,
        topic: str,
        context: str,
    ) -> list[WikiEntry]:
        """Drop entries lacking a repo-specific anchor (#9954).

        A synthesized entry earns its place only if its title/content
        references something specific to this repo — a ``.py`` module, an
        ADR number, a loop/Port/runner class name, or a known config
        field. Generic best-practice platitudes ("Use ``is None`` for
        optional sentinels") dilute the wiki context injected into agent
        prompts (``max_repo_wiki_chars`` truncates) and are rejected here.
        Each drop is logged and counted so the gate stays observable and
        cannot silently regress.
        """
        vocab = config_field_vocabulary()
        kept: list[WikiEntry] = []
        dropped = 0
        for entry in entries:
            text = f"{entry.title}\n{entry.content}"
            if has_repo_anchor(text, config_fields=vocab):
                kept.append(entry)
                continue
            dropped += 1
            logger.info(
                "Wiki %s gate dropped anchor-less entry for %s/%s: %r",
                context,
                repo,
                topic,
                entry.title,
            )
        if dropped:
            _metrics.increment("wiki_entries_rejected_no_anchor", dropped)
        return kept

    @staticmethod
    def _parse_entries(raw: str) -> list[WikiEntry]:
        """Parse LLM output into WikiEntry objects.

        Tolerant of markdown fences and extra text around the JSON array.
        """
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            # Remove first and last lines (fences)
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        # Find the JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("Wiki compiler output has no JSON array")
            return []

        try:
            items = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Wiki compiler output is not valid JSON")
            return []

        entries: list[WikiEntry] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                raw_supersedes_ids = item.get("supersedes_ids")
                supersedes_ids = (
                    [str(x) for x in raw_supersedes_ids if isinstance(x, str | int)]
                    if isinstance(raw_supersedes_ids, list)
                    else []
                )
                entries.append(
                    WikiEntry(
                        title=item.get("title", "Untitled"),
                        content=item.get("content", ""),
                        source_type=item.get("source_type", "compiled"),
                        source_issue=item.get("source_issue"),
                        stale=item.get("stale", False),
                        supersedes_ids=supersedes_ids,
                    )
                )
            except Exception:  # noqa: BLE001
                logger.warning("Skipping invalid entry from compiler output")

        return entries
