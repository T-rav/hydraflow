"""The tracked compile flow (ADR-0111): extract, verify, synthesize, validate.

Separate from the legacy one-shot ``compile_topic`` because the flow is
checkpointed and resumable — each node reads and writes ``FlowState``, and the
provenance rules (shipped-claim union, supersession resolution) exist only
because a run can stop between nodes and be resumed against a wiki that moved.
``_dedup_known_ids``, ``_resolve_supersession_ids`` and
``_union_shipped_claim_provenance`` are pure helpers of the validate/verify
nodes and travel with them; ``_SYNTHESIS_ID_RE`` and ``_flow_aborted`` are read
nowhere else.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flows import Edge, Flow, FlowState, KillSwitch, Node, NodeHook
from repo_wiki import (
    DEFAULT_TOPICS,
    WikiEntry,
    _load_tracked_active_entries,
    _mark_tracked_entry_superseded,
    _write_tracked_synthesis_entry,
    synthesis_matches_active_bodies,
)

from ._prompts import _COMPILE_TOPIC_PROMPT

if TYPE_CHECKING:
    pass


logger = logging.getLogger("hydraflow.wiki_compiler")


_SYNTHESIS_ID_RE = re.compile(r"^(\d+)-")


def _flow_aborted(state: FlowState) -> bool:
    """Edge guard: route to the terminal when a node has signalled abort.

    Nodes set ``state['_stop']`` on any fail-closed early-exit (too few
    inputs, model failure, empty / anchor-less / byte-identical output) so
    the graph routes straight to ``done`` without running ``validate`` — the
    only node that writes.
    """
    return bool(state.get("_stop"))


class WikiCompilerFlowMixin:
    """The tracked compile flow (ADR-0111): extract, verify, synthesize, validate."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``WikiCompiler.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    if TYPE_CHECKING:

        async def _call_model(
            self, prompt: str, context: str
        ) -> str | None: ...  # provided by _model_io

        @staticmethod
        def _filter_anchored_entries(
            entries: list[WikiEntry], *, repo: str, topic: str, context: str
        ) -> list[WikiEntry]: ...  # provided by _compiler

        @staticmethod
        def _parse_entries(raw: str) -> list[WikiEntry]: ...  # provided by _compiler

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

        raw = await self._call_model(prompt, "flow_synthesize")
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
            WikiCompilerFlowMixin._dedup_known_ids(entry.supersedes_ids, known_ids)
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
