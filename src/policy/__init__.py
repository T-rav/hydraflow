"""The decision seam: normalized ``Fact`` in, typed ``StandardDecision`` out (#11749).

HydraFlow independently re-derived the same shape five times —
``standard -> evidence -> classification -> gate -> exception/baseline ->
remediation`` — in ADR enforcement (``REAL``/``WEAK``/``MISSING``), the
disturbance ratchets, the erosion ratchets, rails drift, and AutoTighten.
Each carried its own decision logic *and* its own exception format:
``adr_conformance.live_grandfathered``, ``disturbance.baseline.diff`` and
``adr_conformance_remediation.classify_remediation`` are three answers to one
question. This package normalizes the **decision** so a sixth actuator
inherits the vocabulary instead of inventing a sixth exception format.

Three modules, and the split between them is the load-bearing part:

* :mod:`policy.models` — the vocabulary. ``Fact`` (one observation, no
  judgement), ``StandardDecision`` (one judgement per ``(standard, subject)``),
  the ``DecisionEngine`` protocol, and the minimal ``Charter`` that selects
  which standards a run decides. Pure data; no I/O.
* :mod:`policy.facts` — the collectors. Everything that reads the repo lives
  here: ADR scanning, baseline JSON, the exemption allow-list, a loop's
  in-flight conformance result. Collectors emit ``Fact`` records and nothing
  else.
* :mod:`policy.python_engine` — ``PythonDecisionEngine``, the reference
  implementation of the protocol and the parity target for the OPA pilot
  (#11750).

**The engine never touches the world.** Per epic #11752: the decision engine
never runs pytest, inspects git, launches agents, touches worktrees, repairs
code, schedules, routes models, manages PRs, or owns lifecycle state. It takes
normalized facts in and returns a typed decision out. If a decision needs a
file read to be made, the read belongs in a collector, not in the engine — and
because the engine only ever sees ``Fact`` records, a decision is reproducible
offline from ``.hydraflow/{repo_slug}/metrics/facts.jsonl`` on a clean
checkout, with no external service up (#11687).

:mod:`policy.store` is the JSONL round-trip for that ledger.
"""

from __future__ import annotations

from adr_conformance_remediation import RemediationAction
from policy.facts import (
    COLLECTED_STANDARDS,
    STANDARD_ADR_CONFORMANCE,
    STANDARD_ADR_ENFORCEMENT,
    adr_subject,
    collect_adr_enforcement_facts,
    conformance_facts,
)
from policy.models import (
    Charter,
    CharterArticles,
    DecisionEngine,
    DecisionStatus,
    Fact,
    FactValue,
    StandardDecision,
)
from policy.python_engine import (
    DecisionEngineError,
    MissingFactError,
    PythonDecisionEngine,
    UnsupportedStandardError,
)
from policy.store import append_facts, facts_path, read_facts

#: One import surface for a consumer of the seam. ``RemediationAction`` is
#: re-exported because ``StandardDecision.remediation`` is typed with it — an
#: actuator cannot interpret a decision without it, and reaching back into
#: ``adr_conformance_remediation`` for one enum would tie the consumer to the
#: standard the vocabulary is meant to outlive. Same object either way; there
#: is one class, not two identities.
__all__ = [
    "COLLECTED_STANDARDS",
    "STANDARD_ADR_CONFORMANCE",
    "STANDARD_ADR_ENFORCEMENT",
    "Charter",
    "CharterArticles",
    "DecisionEngine",
    "DecisionEngineError",
    "DecisionStatus",
    "Fact",
    "FactValue",
    "MissingFactError",
    "PythonDecisionEngine",
    "RemediationAction",
    "StandardDecision",
    "UnsupportedStandardError",
    "adr_subject",
    "append_facts",
    "collect_adr_enforcement_facts",
    "conformance_facts",
    "facts_path",
    "read_facts",
]
