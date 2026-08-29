"""``OpaDecisionEngine`` — the Rego half of pilot #11750. **EXPERIMENTAL.**

This module exists to answer one question with numbers instead of opinion:
does moving a standard's decision into Open Policy Agent buy anything over the
bespoke Python that decides it today? It implements the same
:class:`policy.models.DecisionEngine` protocol as
:class:`policy.python_engine.PythonDecisionEngine`, over the same
:class:`policy.models.Fact` records, and is parity-tested against it in
``tests/architecture/test_policy_opa_parity.py``.

**Read the verdict before building on this.** The measurement record and the
adopt / not-adopt ruling live in ``docs/proposals/opa-pilot-findings.md``.
Nothing in the running factory reads this engine; it is wired into
``make opa-test`` and the parity test and nowhere else.

**Scope.** ``adr_enforcement`` only. Facts for any other standard raise
``UnsupportedStandardError`` — the same refusal ``PythonDecisionEngine`` makes,
for the same reason: an engine that cannot judge an article must say so rather
than return silence that reads as compliance.

**No network, ever.** The engine shells out to a locally pinned ``opa eval``
binary; there is no OPA server, no bundle fetch, and no ``http.send`` in the
policy (``tests/architecture/test_policy_opa_parity.py`` pins that). #11687's
rule is that no conformance claim may depend on an external service being up,
and a decision layer that could reach the network at decision time would break
it. ``opa eval`` is handed the policy file and the input document on stdin and
runs to completion offline.

**Absent binary degrades, never crashes.** Importing this module runs nothing.
:meth:`OpaDecisionEngine.availability` reports why the engine cannot run
(``binary-not-found`` / ``policy-not-found``), :meth:`decide` raises
:class:`OpaUnavailableError` carrying that reason, and callers fall back to the
Python engine — the ``docs/wiki/dependencies.md`` graceful-degradation
contract.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess  # nosec B404 - pinned local `opa eval`, argv list, never a shell
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from adr_conformance_remediation import RemediationAction
from policy.facts import STANDARD_ADR_ENFORCEMENT
from policy.models import Charter, DecisionStatus, StandardDecision
from policy.python_engine import (
    DecisionEngineError,
    MissingFactError,
    UnsupportedStandardError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from policy.models import Fact

logger = logging.getLogger("hydraflow.policy.opa")

#: Repo-relative home of the pinned binary that ``make opa-install`` writes.
OPA_BIN_REL = Path(".opa") / "opa"

#: Repo-relative home of the policy this engine evaluates.
POLICY_REL = Path("policy") / "adr_enforcement.rego"

#: Environment override, so CI can point at a binary installed elsewhere.
OPA_BIN_ENV = "HYDRAFLOW_OPA_BIN"

#: The Rego document the engine asks for. One query, one round trip.
DECISIONS_QUERY = "data.hydraflow.adr_enforcement.decisions"

#: ``missing_facts`` is asked for in the same evaluation so a fail-closed
#: refusal carries the collector's own diagnosis instead of an empty result.
MISSING_QUERY = "data.hydraflow.adr_enforcement.missing_facts"

#: Wall-clock ceiling for one ``opa eval``. Generous: the whole ADR corpus
#: evaluates in tens of milliseconds, so anything near this is a hung process,
#: not a slow one.
EVAL_TIMEOUT_S = 60.0

_REPO_ROOT = Path(__file__).resolve().parents[2]


class OpaUnavailableError(DecisionEngineError):
    """The OPA engine cannot run here — binary or policy missing."""


class OpaEvaluationError(DecisionEngineError):
    """``opa eval`` ran and failed, or returned something unparseable."""


@dataclass(frozen=True)
class OpaAvailability:
    """Whether this engine can decide, and — when it cannot — why not.

    The *reason* is the observable the ``dependencies.md`` contract asks for:
    an absent optional dependency must say what is absent, not fail silently
    and not crash. Callers record it; ``decide`` raises with it.
    """

    available: bool
    reason: str
    binary: Path | None = None
    version: str = ""


def _resolve_binary(repo_root: Path) -> Path | None:
    """Find the pinned ``opa``: env override, then ``.opa/opa``, then ``PATH``."""
    override = os.environ.get(OPA_BIN_ENV, "").strip()
    if override:
        candidate = Path(override)
        return (
            candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None
        )
    vendored = repo_root / OPA_BIN_REL
    if vendored.is_file() and os.access(vendored, os.X_OK):
        return vendored
    found = shutil.which("opa")
    return Path(found) if found else None


class OpaDecisionEngine:
    """Evaluate ``adr_enforcement`` through a locally pinned ``opa eval``.

    **EXPERIMENTAL** — see the module docstring and
    ``docs/proposals/opa-pilot-findings.md``.
    """

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        binary: Path | None = None,
        policy: Path | None = None,
    ) -> None:
        self._repo_root = repo_root or _REPO_ROOT
        self._binary = (
            binary if binary is not None else _resolve_binary(self._repo_root)
        )
        self._policy = policy if policy is not None else self._repo_root / POLICY_REL
        self._last_eval_seconds: float = 0.0
        self._availability: OpaAvailability | None = None

    # -- availability --------------------------------------------------------

    def availability(self) -> OpaAvailability:
        """Can this engine decide here? If not, say what is missing.

        Never raises and never crashes on a broken install: a binary that is
        present but will not report a version is reported unavailable, not
        propagated.

        Answered once per instance and cached. The probe is itself a process
        spawn (~9 ms), so re-running it inside every ``decide`` would put more
        wall time into asking whether OPA exists than into asking it anything.
        Construct a new engine to re-probe.
        """
        if self._availability is None:
            self._availability = self._probe()
        return self._availability

    def _probe(self) -> OpaAvailability:
        if self._binary is None:
            return OpaAvailability(
                available=False,
                reason=(
                    f"binary-not-found: no `opa` at ${OPA_BIN_ENV}, "
                    f"{OPA_BIN_REL}, or on PATH — run `make opa-install`"
                ),
            )
        if not self._policy.is_file():
            return OpaAvailability(
                available=False,
                reason=f"policy-not-found: {self._policy} is missing",
                binary=self._binary,
            )
        try:
            proc = subprocess.run(  # nosec B603 - argv list, pinned binary, no shell
                [str(self._binary), "version"],
                capture_output=True,
                text=True,
                timeout=EVAL_TIMEOUT_S,
                check=False,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return OpaAvailability(
                available=False,
                reason=f"binary-not-runnable: {self._binary} ({exc})",
                binary=self._binary,
            )
        if proc.returncode != 0:
            return OpaAvailability(
                available=False,
                reason=f"binary-not-runnable: {self._binary} exited {proc.returncode}",
                binary=self._binary,
            )
        version = next(
            (
                line.split(":", 1)[1].strip()
                for line in proc.stdout.splitlines()
                if line.startswith("Version:")
            ),
            "",
        )
        return OpaAvailability(
            available=True, reason="ok", binary=self._binary, version=version
        )

    @property
    def last_eval_seconds(self) -> float:
        """Wall time of the most recent ``opa eval`` — measurement 3's number."""
        return self._last_eval_seconds

    # -- the protocol --------------------------------------------------------

    def decide(
        self, facts: Sequence[Fact], charter: Charter | None = None
    ) -> list[StandardDecision]:
        """Judge every ``adr_enforcement`` subject the charter places in force.

        Sorted by ``(standard, subject)`` like the Python engine, so two runs
        over the same ledger produce identical output regardless of fact order.
        """
        state = self.availability()
        if not state.available:
            logger.warning("OPA decision engine unavailable: %s", state.reason)
            raise OpaUnavailableError(state.reason)

        active = charter if charter is not None else Charter()
        grouped: dict[str, dict[str, object]] = {}
        for fact in facts:
            if not active.governs(fact.standard):
                continue
            if fact.standard != STANDARD_ADR_ENFORCEMENT:
                raise UnsupportedStandardError(
                    f"the OPA pilot decides {STANDARD_ADR_ENFORCEMENT!r} only; "
                    f"got {fact.standard!r} (subject {fact.subject!r}). An engine "
                    "that cannot judge an article must refuse, not return silence "
                    "that reads as compliance."
                )
            grouped.setdefault(fact.subject, {})[fact.key] = fact.value

        if not grouped:
            return []

        document = self._evaluate(self._input_document(active, grouped))
        by_subject = {fact.subject: fact for fact in facts}
        return [
            self._as_decision(
                document[subject], [f for f in facts if f.subject == subject]
            )
            for subject in sorted(by_subject)
            if subject in document
        ]

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _input_document(
        charter: Charter, subjects: dict[str, dict[str, object]]
    ) -> dict[str, object]:
        return {
            "charter": {
                "standards": list(charter.articles.standards),
                "assurance": charter.articles.assurance,
            },
            "subjects": subjects,
        }

    def _evaluate(self, document: dict[str, object]) -> dict[str, dict[str, object]]:
        """One ``opa eval``; refuse loudly on a fail-closed or malformed result."""
        raw = self._eval_query(document, f"[{DECISIONS_QUERY}, {MISSING_QUERY}]")
        if len(raw) != 2:
            raise OpaEvaluationError(
                f"expected [decisions, missing_facts], got {raw!r}"
            )
        decisions, missing = raw
        if not isinstance(missing, list):
            raise OpaEvaluationError(
                f"expected a list of missing facts, got {missing!r}"
            )
        if missing:
            raise MissingFactError(
                "; ".join(str(m) for m in missing)
                + ". The engine reads no files, so a fact it was not given is a "
                "collector bug — fix the collector rather than defaulting the "
                "value in the policy."
            )
        if not isinstance(decisions, dict):
            raise OpaEvaluationError(
                f"expected an object of decisions, got {decisions!r}"
            )
        return decisions

    def _eval_query(self, document: dict[str, object], query: str) -> list[object]:
        assert self._binary is not None  # nosec B101 - guarded by availability()
        argv = [
            str(self._binary),
            "eval",
            "--format=json",
            f"--data={self._policy}",
            "--stdin-input",
            query,
        ]
        started = time.perf_counter()
        try:
            proc = subprocess.run(  # nosec B603 - argv list, pinned binary, no shell
                argv,
                input=json.dumps(document),
                capture_output=True,
                text=True,
                timeout=EVAL_TIMEOUT_S,
                check=False,
                cwd=self._repo_root,
            )
        except subprocess.TimeoutExpired as exc:
            raise OpaEvaluationError(
                f"`opa eval` timed out after {EVAL_TIMEOUT_S}s"
            ) from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise OpaEvaluationError(f"`opa eval` could not run: {exc}") from exc
        finally:
            self._last_eval_seconds = time.perf_counter() - started
        if proc.returncode != 0:
            raise OpaEvaluationError(
                f"`opa eval` exited {proc.returncode}: {proc.stderr.strip()[:500]}"
            )
        try:
            payload = json.loads(proc.stdout)
            expressions = payload["result"][0]["expressions"]
            value = expressions[0]["value"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise OpaEvaluationError(
                f"`opa eval` returned an unreadable document: {proc.stdout[:500]!r}"
            ) from exc
        if not isinstance(value, list):
            raise OpaEvaluationError(f"expected a two-element array, got {value!r}")
        return value

    @staticmethod
    def _as_decision(row: dict[str, object], facts: Sequence[Fact]) -> StandardDecision:
        return StandardDecision(
            standard=str(row["standard"]),
            subject=str(row["subject"]),
            status=DecisionStatus(str(row["status"])),
            blocking=bool(row["blocking"]),
            reason=str(row["reason"]),
            remediation=RemediationAction(str(row["remediation"])),
            facts=list(facts),
        )
