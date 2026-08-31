"""Pairwise judgements over entries that already exist: contradict, generalize, dedup, ADR-draft.

The compile side writes a topic; this side is asked a yes/no about a PAIR (or
about one transcript) and answers with a typed verdict. Each judgement owns its
own never-raising output parser, because a malformed model answer must degrade
to the neutral verdict rather than break the caller's sweep.
``parse_adr_draft_suggestion`` and ``_ADR_DRAFT_HEADER_RE`` read the OTHER end
of the same ADR-draft exchange — the transcript marker a runner emits — and are
kept beside the judge that scores it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from knowledge_metrics import metrics as _metrics
from repo_wiki import (
    DEFAULT_TOPICS,
    WikiEntry,
)

from ._models import (
    ADRDraftDecision,
    ContradictionCheck,
    CorroborationDecision,
    GeneralizationCheck,
)
from ._prompts import (
    _ADR_DRAFT_JUDGE_PROMPT,
    _CONTRADICTION_PROMPT,
    _GENERALIZATION_PROMPT,
)

if TYPE_CHECKING:
    from tribal_wiki import TribalWikiStore


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


class WikiCompilerJudgeMixin:
    """Pairwise judgements over entries that already exist: contradict, generalize, dedup, ADR-draft."""

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

        raw = await self._call_model(prompt, "detect_contradictions")
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
        raw = await self._call_model(prompt, "generalize_pair")
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
        raw = await self._call_model(prompt, "judge_adr_draft")
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
