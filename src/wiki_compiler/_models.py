"""The typed verdicts the compiler's LLM calls return.

Every one of these is a parse target: a model call answers in JSON and the
matching model is what the answer becomes. They live together, away from the
methods that build the prompts, because ``src/`` imports them by name
(``repo_wiki_ingest``, ``plan_phase_wiki_ingest``, ``review_phase._wiki_ingest``,
``adr_draft_opener``) while nothing outside this package builds a prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


logger = logging.getLogger("hydraflow.wiki_compiler")


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
