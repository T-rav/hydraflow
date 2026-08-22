"""Observed prompt coverage — the denominator measured, not inferred.

``prompt_fitness`` answers "is every prompt builder registered?" by walking the
AST of ``src/`` and matching function names against a convention. That gate is
real, but its denominator is *inferred*: a builder named ``make_prompt`` or
``assemble_instructions`` is a prompt by every meaning of the word and invisible
to it, and a Markdown template under ``prompts/`` is not a Python function at
all. Both were verified to slip through (#10857, #10858).

This module measures the same thing from the other end. Every assembled prompt
passes through :func:`prompt_gate.gate_prompt` on its way to a backend — that is
the CH-6 choke point, and it is the one place where "this text is about to be
sent to a model" is a fact rather than a naming guess. Recording a *shape* there
gives an observed denominator: anything the factory actually sent, however it
was named and whatever language it was written in.

**Records carry no prompt content.** The gate's audit stream holds "counts and
pattern NAMES only"; this holds the same discipline for the same reason —
regulated-class prompts flow through here. A shape is a hash over the prompt's
structural anchors with every value-bearing token removed before hashing, so a
record cannot reconstruct, and cannot leak, what was in the prompt.

The reconciliation this feeds is deliberately *coarse*: it asks whether anything
in ``PROMPT_REGISTRY`` resembles an observed shape at all. A shape that resembles
nothing registered is a prompt the factory sends and the eval suite has never
scored. That question survives fuzzy fingerprints; "which builder exactly?" does
not, and claiming that precision would be false.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from json import dumps
from pathlib import Path

from file_util import append_jsonl
from package_resources import checkout_path

logger = logging.getLogger("hydraflow.prompt_observatory")

# Counts writes that failed. Observation is best-effort by design, but a
# best-effort measurement that fails silently reports a clean bill of health it
# did not earn — see reconcile(). A dict rather than a bare int so incrementing
# needs no ``global``, which ruff rejects and the disturbance ratchet would not
# let us suppress.
_COUNTERS: dict[str, int] = {"write_failures": 0}

# Anchors are the structural skeleton a builder emits regardless of its inputs:
# Markdown headings, bolded field labels, and the XML-ish section tags ADR-0087
# asks for. Interpolated values change between runs; anchors do not.
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_BOLD_LABEL = re.compile(r"\*\*([^*\n]{2,60}?)\*\*\s*:?", re.MULTILINE)
_SECTION_TAG = re.compile(r"<(/?)([a-z][a-z0-9_]{1,40})(?:\s[^>]*)?>", re.IGNORECASE)

# Value-bearing tokens are stripped BEFORE hashing, so an anchor that embeds an
# issue number, a path or a branch name still collapses to the same shape — and
# so that no record can carry a fragment of real content.
_VALUES = (
    re.compile(r"\d+"),
    re.compile(r"[a-z]+://\S+", re.IGNORECASE),
    re.compile(r"[\w./-]+\.(?:py|md|json|ya?ml|txt|ts|tsx|js)\b", re.IGNORECASE),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"[\"'][^\"'\n]{0,80}[\"']"),
)

_MIN_ANCHORS = 3

# Markdown headings alone are too thin a skeleton: measured over the 70
# registered fixtures, 11 carry fewer than three and 5 carry none at all, so
# those five hashed identically and the shape could not tell them apart. The
# builder's own literal instruction lines are the remaining stable signal —
# they come from the f-string, so they repeat across runs while the payload
# does not.
_INSTRUCTION_MIN_CHARS = 24
_INSTRUCTION_MAX_CHARS = 200
_FENCE = re.compile(r"^\s*```")


def _normalize(text: str) -> str:
    for pattern in _VALUES:
        text = pattern.sub(" ", text)
    return " ".join(text.lower().split())


def _instruction_lines(prompt: str) -> set[str]:
    """Normalized prose lines that plausibly come from the builder's literal.

    Payload lines are excluded structurally where possible (fenced blocks, diff
    lines) and by shape otherwise: very short lines carry no signal, very long
    ones are usually wrapped payload.
    """
    out: set[str] = set()
    in_code = False
    for raw in prompt.splitlines():
        if _FENCE.match(raw):
            in_code = not in_code
            continue
        if in_code or raw[:1] in {"+", "-", ">"}:
            continue
        # A "**Label**: value" line mixes the builder's literal with the value
        # it interpolated, so keeping the whole line makes the shape move with
        # the payload — which is the one thing a shape must not do. The label
        # is already captured as its own anchor, so drop the line.
        if _BOLD_LABEL.search(raw):
            continue
        norm = _normalize(raw)
        if _INSTRUCTION_MIN_CHARS <= len(norm) <= _INSTRUCTION_MAX_CHARS:
            out.add(f"i:{norm}")
    return out


def anchors(prompt: str) -> frozenset[str]:
    """Structural anchors of *prompt*, normalized and value-stripped.

    Deliberately not the whole text: two runs of one builder differ in payload
    and agree in skeleton, so the skeleton is what identifies the shape.
    """
    found: set[str] = set()
    for match in _HEADING.finditer(prompt):
        if norm := _normalize(match.group(1)):
            found.add(f"h:{norm}")
    for match in _BOLD_LABEL.finditer(prompt):
        if norm := _normalize(match.group(1)):
            found.add(f"b:{norm}")
    for match in _SECTION_TAG.finditer(prompt):
        found.add(f"t:{match.group(2).lower()}")
    found |= _instruction_lines(prompt)
    return frozenset(found)


def token_hashes(prompt: str) -> frozenset[str]:
    """Anchors as short digests — what a persisted record is allowed to hold.

    Matching works identically over hashes, and a hash cannot be read back into
    the instruction text it came from. Anchors themselves stay in-process only,
    because ``_instruction_lines`` cannot perfectly separate a builder's literal
    from wrapped payload, and the gate's rule for anything written to disk is
    counts and names, never content.
    """
    return frozenset(
        hashlib.sha256(a.encode()).hexdigest()[:10] for a in anchors(prompt)
    )


def shape_id(prompt: str) -> str:
    """Stable, content-free identifier for a prompt's structure."""
    items = sorted(anchors(prompt))
    digest = hashlib.sha256("\n".join(items).encode()).hexdigest()[:16]
    return f"s{len(items):03d}-{digest}"


def resemblance(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard overlap of two anchor sets, 0.0 when either is empty."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True)
class Observation:
    """One prompt shape seen at the gate."""

    shape: str
    source: str
    tool: str
    tokens: frozenset[str] = field(default_factory=frozenset)
    count: int = 1


def observation_record(
    prompt: str,
    *,
    source: str,
    tool: str,
    issue_number: int | None = None,
) -> dict[str, object]:
    """The JSONL row for one gated prompt. Content-free by construction.

    Only digests are written — never the anchors themselves. Matching works the
    same over hashes, and a digest cannot be read back into the text it came
    from, which matters because ``_instruction_lines`` cannot perfectly
    separate a builder's literal from wrapped payload. A prompt whose skeleton
    is too thin to identify (fewer than three anchors) records its shape and
    count without the token list.

    ``issue_number`` is recorded only when the gate caller knows it (#11027). It
    is the one field that lets an observed shape — which ``reconcile`` bridges to
    a registered prompt builder — be joined to that issue's *outcomes* (verdict
    pass rate, retries, escapes, cost), the prompt-of-record linkage the #10855
    rubric-vs-outcome pairing needs. Absent when unknown; never invented.
    """
    hashes = token_hashes(prompt)
    record: dict[str, object] = {
        "shape": shape_id(prompt),
        "source": source,
        "tool": tool,
        "anchor_count": len(hashes),
        "prompt_chars": len(prompt),
    }
    if issue_number is not None:
        record["issue_number"] = issue_number
    if len(hashes) >= _MIN_ANCHORS:
        record["tokens"] = sorted(hashes)
    return record


def observe(
    prompt: str, *, config, source: str, tool: str, issue_number: int | None = None
) -> None:
    """Append one shape record. Best-effort: NEVER raises, never blocks a send.

    This sits on the hot path of every model call, so it is deliberately
    subordinate to the gate's real job. A failure here — unwritable path, full
    disk, a regex pathology on a strange prompt — must not stop a prompt the
    gate already allowed. Kill switch: ``prompt_observatory_enabled``.
    """
    try:
        if not getattr(config, "prompt_observatory_enabled", False):
            return
        record = observation_record(
            prompt, source=source, tool=tool, issue_number=issue_number
        )
        record["timestamp"] = datetime.now(UTC).isoformat()
        record["repo"] = getattr(config, "repo", "")
        append_jsonl(config.prompt_observatory_path, dumps(record))
    except Exception:
        # Swallowed so a measurement failure never stops a send — but COUNTED
        # and logged at warning, because a silently-dead observer makes
        # "no unrecognized shapes" indistinguishable from "not looking", which
        # is the exact failure mode this whole subsystem exists to catch one
        # level up. reconcile() refuses to report all-clear while this is > 0.
        _COUNTERS["write_failures"] += 1
        logger.warning(
            "prompt observatory write failed (%d since start); observed prompt "
            "coverage is now incomplete",
            _COUNTERS["write_failures"],
            exc_info=True,
        )


def write_failures() -> int:
    """Observation writes that failed in this process since start."""
    return _COUNTERS["write_failures"]


def reset_write_failures() -> None:
    """Test seam: clear the in-process failure counter."""
    _COUNTERS["write_failures"] = 0


def load_observations(path) -> dict[str, Observation]:
    """Read the ledger, collapsing repeats into one Observation per shape."""
    out: dict[str, Observation] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn trailing write is not a reason to lose the rest
        shape = str(row.get("shape", ""))
        if not shape:
            continue
        prior = out.get(shape)
        out[shape] = Observation(
            shape=shape,
            source=str(row.get("source", "")),
            tool=str(row.get("tool", "")),
            tokens=frozenset(row.get("tokens") or ()),
            count=(prior.count + 1) if prior else 1,
        )
    return out


# A registered fixture and a production render of the same builder differ only
# in payload, so their anchor sets overlap almost entirely: measured across the
# 70 fixtures, variants of one builder score 0.97-0.98, while the 16
# unregistered auto-agent templates score 0.005 against the whole registry and
# the two registered ones score 1.000. The threshold sits in that gap. It is
# deliberately low — the question is "does anything registered resemble this at
# all", and a false *match* merely fails to raise an alarm, while a false
# mismatch would cry wolf on every run.
RESEMBLANCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class UnrecognizedShape:
    """An observed prompt that resembles nothing in PROMPT_REGISTRY."""

    shape: str
    source: str
    tool: str
    count: int
    best_match: str
    best_score: float


def registry_token_sets() -> dict[str, frozenset[str]]:
    """Registered prompt name -> token digests of its rendered fixture."""
    # scripts/ is a development artefact the wheel does not ship; ask the
    # checkout, which names what is missing instead of pointing into
    # site-packages (#11589).
    audit_path = checkout_path("scripts", "audit_prompts.py")
    spec = importlib.util.spec_from_file_location("_audit_prompts_obs", audit_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return {}
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_audit_prompts_obs", module)
    spec.loader.exec_module(module)

    out: dict[str, frozenset[str]] = {}
    for target in module.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        try:
            out[target.name] = token_hashes(module.render_target(target))
        except Exception:  # pragma: no cover - reported by the fitness gate
            continue
    return out


def unrecognized_shapes(
    observations: dict[str, Observation],
    registry: dict[str, frozenset[str]] | None = None,
    *,
    threshold: float = RESEMBLANCE_THRESHOLD,
) -> list[UnrecognizedShape]:
    """Observed shapes that no registered prompt resembles.

    Each one is a prompt the factory actually sent and the eval suite has never
    scored — the gap the AST-based ratchet cannot see, because it is blind to
    builders that dodge the naming convention and to prompts that are not
    Python at all.

    Shapes recorded without tokens (too thin to identify) are skipped rather
    than reported: they cannot be matched either way, and reporting them would
    be noise rather than a finding.
    """
    known = registry_token_sets() if registry is None else registry
    findings: list[UnrecognizedShape] = []
    for obs in observations.values():
        if not obs.tokens:
            continue
        best_name, best_score = "", 0.0
        for name, tokens in known.items():
            score = resemblance(obs.tokens, tokens)
            if score > best_score:
                best_name, best_score = name, score
        if best_score < threshold:
            findings.append(
                UnrecognizedShape(
                    shape=obs.shape,
                    source=obs.source,
                    tool=obs.tool,
                    count=obs.count,
                    best_match=best_name or "(nothing)",
                    best_score=round(best_score, 3),
                )
            )
    return sorted(findings, key=lambda f: (-f.count, f.shape))


# Shapes seen at the gate that are known not to be registrable prompts, each
# with the reason. This is the pass/fail authority — NOT the threshold.
#
# A tunable threshold as the verdict is a knob, and a knob gets turned until
# the alarm stops; the same objection this repo already applies to
# GRANDFATHERED, EXCLUDED_BUILDERS and PLACEHOLDER_LEAK_EXEMPT. Resemblance
# still RANKS findings and annotates them, but "is this acceptable?" is
# answered by a written decision, not a number someone can move.
ACKNOWLEDGED_SHAPES: dict[str, str] = {}
ACKNOWLEDGED_SHAPES_MAX = 8


@dataclass(frozen=True)
class Reconciliation:
    """Observed-vs-registered result, carrying its own trustworthiness.

    ``findings`` alone is not readable as a verdict: an empty list means
    "nothing unrecognized" only when ``trustworthy`` is true. When the ledger
    is empty, or writes have been failing, an empty list means "we did not
    look", and conflating the two is how a dead measurement passes for a
    healthy one.
    """

    findings: list[UnrecognizedShape]
    observed_shapes: int
    write_failures: int
    ledger_present: bool

    @property
    def trustworthy(self) -> bool:
        return (
            self.ledger_present and self.observed_shapes > 0 and not self.write_failures
        )

    @property
    def summary(self) -> str:
        if not self.trustworthy:
            why = (
                "no ledger"
                if not self.ledger_present
                else "no observations recorded"
                if not self.observed_shapes
                else f"{self.write_failures} failed write(s)"
            )
            return f"UNTRUSTWORTHY ({why}) — absence of findings proves nothing"
        if self.findings:
            return f"{len(self.findings)} unrecognized prompt shape(s) in production"
        return f"all {self.observed_shapes} observed shape(s) recognized"


def reconcile(
    path,
    registry: dict[str, frozenset[str]] | None = None,
    *,
    threshold: float = RESEMBLANCE_THRESHOLD,
) -> Reconciliation:
    """Compare what the factory sent against what the eval suite scores."""
    observations = load_observations(path)
    findings = [
        f
        for f in unrecognized_shapes(observations, registry, threshold=threshold)
        if f.shape not in ACKNOWLEDGED_SHAPES
    ]
    return Reconciliation(
        findings=findings,
        observed_shapes=len(observations),
        write_failures=write_failures(),
        ledger_present=Path(path).exists(),
    )
