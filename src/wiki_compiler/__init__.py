"""Back-compat re-exports for the ``wiki_compiler`` package.

``src/wiki_compiler.py`` held an 849-LOC, 26-method ``WikiCompiler`` alongside
five verdict models, five prompt templates and a transcript parser. Split for
mass discipline (Refs #11547, batch 8), the shape ``agent/``, ``workspace/``,
``pr_unsticker/`` and ``epic/`` already use. Existing imports keep working::

    from wiki_compiler import WikiCompiler              # still works
    from wiki_compiler import CorroborationDecision     # still works
    from wiki_compiler import parse_adr_draft_suggestion  # still works

Layout:
  * ``_compiler.py`` — construction, the legacy one-shot ``compile_topic``,
    the ingest synthesis call, and the two readers every compile path shares
    (``_parse_entries`` / ``_filter_anchored_entries``): what the class IS.
  * ``_flow.py``     — the tracked compile flow (ADR-0111). Separate from the
    one-shot compile because it is checkpointed: the provenance rules
    (shipped-claim union, supersession resolution) exist only because a run
    can stop between nodes and resume against a wiki that moved.
  * ``_judge.py``    — pairwise judgements over entries that already exist.
    The compile side WRITES a topic; this side is asked a yes/no about a pair
    and answers with a typed verdict, each with its own never-raising parser.
  * ``_model_io.py`` — ``_call_model``: the one seam this package spawns an
    agent through, so the circuit breaker and the prompt-gate escalation have
    exactly one home.
  * ``_models.py``   — the typed verdicts those calls return.
  * ``_prompts.py``  — the five templates. ``_COMPILE_TOPIC_PROMPT`` has two
    callers (``_compiler`` and ``_flow``); owned by either, the other would
    have to import it back and close a cycle.

Each slice is a mixin ``WikiCompiler`` inherits, so there is exactly ONE class
identity and every ``patch.object(WikiCompiler, ...)`` target still resolves.

**Patch targets follow their call site.** A module-level name a test reaches
through is bound in the module that CALLS it, so ``patch("wiki_compiler.X")``
would replace an attribute HERE and leave the real binding untouched — a patch
that silently no-ops, and one that passes. ``is_prompt_gate_blocked``,
``alert_prompt_gate_block`` and ``clear_prompt_gate_block`` are bound in
``wiki_compiler._model_io``; ``logger`` is bound in every slice (all the same
``logging.getLogger("hydraflow.wiki_compiler")`` object, so mutating IT is
fine — naming the wrong module is not). Patch those, not this module.

Only the class ``src/`` imports, the four verdict models ``src/`` imports by
name, and the one transcript parser ``base_runner`` imports are re-exported.
Class re-exports are identity-safe (``isinstance`` and ``patch.object`` both
still work through them); ``parse_adr_draft_suggestion`` is a pure function of
a string that nothing patches, and anything that wants to must patch
``base_runner.parse_adr_draft_suggestion`` — the call site's own binding, never
this one. The prompts and ``_ADR_DRAFT_HEADER_RE`` are deliberately NOT
re-exported: a second name for a module-level constant is the one that rebinds
without effect, so a stale target must raise rather than no-op.
"""

from __future__ import annotations

from ._compiler import WikiCompiler
from ._judge import parse_adr_draft_suggestion
from ._models import (
    ADRDraftDecision,
    ContradictedEntry,
    ContradictionCheck,
    CorroborationDecision,
    GeneralizationCheck,
)

__all__ = [
    "ADRDraftDecision",
    "ContradictedEntry",
    "ContradictionCheck",
    "CorroborationDecision",
    "GeneralizationCheck",
    "WikiCompiler",
    "parse_adr_draft_suggestion",
]
