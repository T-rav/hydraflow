"""Prompt outcome pairing (#10855) — make the rubric ungameable before a floor.

The 8-criterion ADR-0087 rubric (``prompt_fitness``) measures the **form** of a
prompt — XML tags present, request leads, edge cases named — not whether the
prompt produces better work. A score *floor* on a form metric, enforced against a
factory that optimises consistently and at scale, is **Goodhart with the factory
holding the pen**: the cheapest way to clear the floor is to add markup, and the
dashboard would show rising prompt quality while results degraded. This module
supplies the two guards that make a form score admissible as a quality claim,
per ADR-0116 §6.

**1. The rule.** A score improvement accompanied by an outcome regression is a
failure, not a win (:func:`pairing_verdict`). A prompt is only ever compared
against **its own prior baseline** — never a cross-prompt league table (the
never-compare-teams rule) — and only within a single model version (comparisons
across a model-version boundary must reset, the #10369 convention).

**2. Gaming-failure-mode detection.** The cheapest way to raise a form score is
to add tags and edge-case boilerplate without changing what the prompt asks.
:func:`detect_markup_only_gain` flags a score-improving change whose **instruction
content** — the imperative and the constraints, with structural markup stripped —
is byte-identical: a score that rose while the prompt's actual request did not.

**Honest limitation (ADR-0130).** Attribution is confounded, and worse: the
rubric keys a prompt *builder by name*, while every outcome series (verdict pass
rate, retry/loop-back count, escape attribution, cost) is keyed by
``issue_number``, and **no record links a builder to the outcomes of the work it
produced**. So the outcome JOIN this module models is *issue-scoped*, not
builder-scoped, and ``prompt_fitness.outcome_paired`` must stay ``False`` until a
prompt-of-record field exists. The **rule** and the **gaming detector** need no
such join — they compare a prompt against its own two versions/baselines — and
are live today. Where sample volume is too low for a signal, the verdict is
``INSUFFICIENT_DATA`` with the minimum detectable effect reported, never a chart
of noise (#10838).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: A quality delta smaller than this (fractional) is treated as noise, not a
#: regression — keeps a 0.001 wobble from making a real score gain inadmissible.
DEFAULT_MATERIALITY: float = 0.02


class PairingVerdict(StrEnum):
    """Admissibility of a prompt-score change once paired with its outcome."""

    ADMISSIBLE = "admissible"
    #: Score improved while a quality outcome regressed — the failure the rule
    #: exists to catch. A claim citing only the score is inadmissible.
    SCORE_UP_OUTCOME_DOWN = "score_up_outcome_down"
    #: Not enough resolved outcomes on either side to judge — report the MDE,
    #: never a verdict from noise.
    INSUFFICIENT_DATA = "insufficient_data"
    #: A score change compared across a model-version boundary — the series must
    #: reset at the boundary (#10369), so the two sides are not comparable.
    MODEL_VERSION_BOUNDARY = "model_version_boundary"


@dataclass(frozen=True)
class OutcomeSnapshot:
    """The paired outcome series for one prompt baseline, over ``n_samples``.

    All four are already collected elsewhere (this is a join, not new capture),
    but keyed by issue — see the module's honest-limitation note. Directionality
    is normalized to "higher pass rate is better; lower retries / escapes / cost
    is better".
    """

    pass_rate: float  # verdict pass rate in [0, 1] — higher is better
    retry_rate: float  # mean retries / loop-backs per task — lower is better
    escape_rate: float  # escape-attributed merges per task — lower is better
    cost_per_success: float  # USD per successful outcome — lower is better (efficiency)
    n_samples: int
    model_version: str = ""


def _worse(before: float, after: float, *, materiality: float) -> bool:
    """True when ``after`` is materially larger than ``before`` (lower-is-better)."""
    return after - before > materiality


def quality_regressed(
    before: OutcomeSnapshot,
    after: OutcomeSnapshot,
    *,
    materiality: float = DEFAULT_MATERIALITY,
) -> bool:
    """True when any *quality* dimension regressed materially.

    Quality is pass rate (higher better), retry rate and escape rate (lower
    better). ``cost_per_success`` is efficiency, not quality, so it is reported
    alongside but does not on its own make a score gain inadmissible.
    """
    pass_rate_down = before.pass_rate - after.pass_rate > materiality
    return (
        pass_rate_down
        or _worse(before.retry_rate, after.retry_rate, materiality=materiality)
        or _worse(before.escape_rate, after.escape_rate, materiality=materiality)
    )


def pairing_verdict(
    *,
    score_before: float,
    score_after: float,
    outcome_before: OutcomeSnapshot,
    outcome_after: OutcomeSnapshot,
    min_samples: int = 5,
    materiality: float = DEFAULT_MATERIALITY,
) -> PairingVerdict:
    """Apply the rule: a score gain paired with a quality regression is a failure.

    Compares a prompt against its own prior baseline within a single model
    version. Returns ``INSUFFICIENT_DATA`` when either side has too few resolved
    outcomes, ``MODEL_VERSION_BOUNDARY`` when the two sides straddle a model
    upgrade, ``SCORE_UP_OUTCOME_DOWN`` when the score improved but quality
    regressed, and ``ADMISSIBLE`` otherwise.
    """
    if (
        outcome_before.model_version
        and outcome_after.model_version
        and outcome_before.model_version != outcome_after.model_version
    ):
        return PairingVerdict.MODEL_VERSION_BOUNDARY
    if outcome_before.n_samples < min_samples or outcome_after.n_samples < min_samples:
        return PairingVerdict.INSUFFICIENT_DATA
    score_improved = score_after - score_before > materiality
    if score_improved and quality_regressed(
        outcome_before, outcome_after, materiality=materiality
    ):
        return PairingVerdict.SCORE_UP_OUTCOME_DOWN
    return PairingVerdict.ADMISSIBLE


def minimum_detectable_effect(n_samples: int) -> float:
    """A coarse MDE for a rate in [0, 1] at n samples (~1/sqrt(n), capped at 1).

    Reported alongside an ``INSUFFICIENT_DATA`` verdict so a low-volume prompt
    says "the smallest change I could have detected" instead of charting noise.
    """
    if n_samples <= 0:
        return 1.0
    return min(1.0, 1.0 / (n_samples**0.5))


# --- Gaming-failure-mode detection -----------------------------------------

_XML_TAG_RE = re.compile(r"</?[A-Za-z][\w:-]*(?:\s[^>]*)?>")
_MARKDOWN_STRUCTURE_RE = re.compile(r"[*_`#>|~\-]+")
_WHITESPACE_RE = re.compile(r"\s+")


def instruction_content(text: str) -> str:
    """The prompt's *instruction content* — its request, markup removed.

    Strips XML/HTML tags and Markdown structural characters, lowercases, and
    collapses whitespace, so two prompts that ask for the exact same thing with
    different scaffolding normalize to the same string. This is deliberately
    aggressive: it is used only to answer "did the actual request change, or just
    the markup?", so removing formatting that the rubric rewards is the point.
    """
    without_tags = _XML_TAG_RE.sub(" ", text)
    without_structure = _MARKDOWN_STRUCTURE_RE.sub(" ", without_tags)
    return _WHITESPACE_RE.sub(" ", without_structure).strip().lower()


@dataclass(frozen=True)
class GamingSignal:
    """The verdict of the markup-only-gain detector for one prompt change."""

    score_improved: bool
    instruction_changed: bool

    @property
    def is_markup_only_gain(self) -> bool:
        """A score-improving change that left the actual request untouched."""
        return self.score_improved and not self.instruction_changed


def detect_markup_only_gain(
    *,
    before_text: str,
    after_text: str,
    score_before: float,
    score_after: float,
    materiality: float = DEFAULT_MATERIALITY,
) -> GamingSignal:
    """Flag a score-improving prompt edit whose instruction content is unchanged.

    The signature of gaming the form rubric: the score rose but the imperative
    and constraints are byte-identical after markup is stripped — tags and
    edge-case boilerplate were added without changing what the prompt asks. Such
    a change should be surfaced, not celebrated.
    """
    score_improved = score_after - score_before > materiality
    instruction_changed = instruction_content(before_text) != instruction_content(
        after_text
    )
    return GamingSignal(
        score_improved=score_improved, instruction_changed=instruction_changed
    )
