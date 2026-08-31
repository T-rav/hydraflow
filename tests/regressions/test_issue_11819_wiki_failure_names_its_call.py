"""Regression (#11819): a wiki model failure must name the call that failed.

Measured 2026-08-31. The breaker opened after three consecutive 300s timeouts
and every log line read:

    Wiki compilation model failed (rc=-1: timed out after 300s)

Nothing named the topic. Identifying the culprit required diffing the failures
against the SUCCESS lines (which do name their topic) and taking the one that
was absent — `architecture`. That is not a diagnosis an operator should have to
reconstruct.

It is worse than one missing word, because `_call_model` has SIX callers —
compile_topic, _flow_synthesize, detect_contradictions, generalize_pair,
judge_adr_draft, synthesize_ingest — sharing ONE circuit breaker. Three
consecutive failures across six unrelated operations trip the circuit for all
of them, and the log distinguished none. The shared breaker is deliberate (one
model, one budget), so the fix is to name the operation, not to split it.
"""

from __future__ import annotations

import inspect
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

import wiki_compiler as wc
from circuit_breaker import CircuitBreaker

#: ``src/``. Not derived from ``wc.__file__``: that is the package ``__init__``
#: since #11547 batch 8, and ``parents[N]`` would silently change depth the day
#: the module becomes a package (or stops being one).
_SRC = Path(__file__).resolve().parents[2] / "src"

#: Every caller of `_call_model`, by reference rather than by hand-copied list:
#: a new caller that forgets its label should fail this, which a literal list
#: could never notice (docs/standards/parametrised_guards).
_EXPECTED_CALLERS = (
    "compile_topic",
    "_flow_synthesize",
    "detect_contradictions",
    "generalize_pair",
    "judge_adr_draft",
    "synthesize_ingest",
)


def _owner_files() -> list[Path]:
    """Every file that defines a piece of ``WikiCompiler``, from its own MRO.

    By reference, not by filename: #11547 batch 8 split the class across a
    package, moving ``_call_model`` and four of its six callers out of the file
    ``wc.__file__`` names. A guard anchored to that one filename would have gone
    on passing while seeing almost none of its subject.
    """
    return sorted(
        {
            Path(inspect.getfile(base)).resolve()
            for base in wc.WikiCompiler.__mro__
            if base is not object
        }
    )


def _source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _owner_files())


def _wiki_call_sites() -> list[str]:
    """Every WikiCompiler._call_model call site across src/, by reference.

    Scoping this to wiki_compiler.py is how the first version of this guard
    missed `repo_wiki_loop.py`, which calls `compiler._call_model(prompt)` on a
    WikiCompiler it holds. A sweep is only as wide as its predicate: the caller
    need not live in the callee's module.

    Scoped by WHERE THE METHOD IS DEFINED, not by receiver name:
    `transcript_summarizer` has its own unrelated `_call_model` (different
    class, `issue_labels` kwarg) and self-calls it, so a bare `self._call_model`
    match wrongly flags it. Only `self.` calls inside the module that defines
    WikiCompiler count, plus any `compiler._call_model` whose receiver names a
    WikiCompiler explicitly.
    """
    owners = set(_owner_files())
    sites: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        for i, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if "def _call_model" in line:
                continue
            is_owner_self = path.resolve() in owners and "self._call_model(" in line
            is_explicit = "compiler._call_model(" in line
            if is_owner_self or is_explicit:
                sites.append(f"{path.name}:{i}:{line.strip()}")
    return sites


def test_every_call_site_passes_a_context_label() -> None:
    """Scoped to src/, not one file — the module-scoped version missed one."""
    bare = [
        s
        for s in _wiki_call_sites()
        if s.endswith("_call_model(prompt)") or '_call_model(prompt, "")' in s
    ]
    assert not bare, f"call sites without a context label: {bare}"


def test_the_call_site_sweep_is_not_empty() -> None:
    """Anti-vacuity: the assertion above passes trivially against an empty sweep."""
    assert len(_wiki_call_sites()) >= 7


def test_every_known_caller_is_still_present() -> None:
    """Anti-drift: if a caller is renamed or added, this file must be revisited.

    Without it the guard above stays green while a new unlabelled path appears
    under a name nobody listed.
    """
    src = _source()
    for name in _EXPECTED_CALLERS:
        assert f"def {name}" in src, f"caller {name} vanished — update this guard"


def test_compile_topic_label_carries_the_topic() -> None:
    """The specific datum whose absence cost the diagnosis."""
    assert 'self._call_model(prompt, f"compile:{topic}")' in _source()


@pytest.mark.parametrize(
    ("max_failures", "expected_level"),
    [(5, logging.WARNING), (1, logging.ERROR)],
)
def test_failure_log_names_the_context_at_both_levels(
    max_failures: int, expected_level: int, caplog: pytest.LogCaptureFixture
) -> None:
    """Both branches must carry it — the ERROR fires once, on the transition to
    OPEN, and that single line is the one an operator actually sees.

    Uses a REAL CircuitBreaker rather than a stand-in: the branch under test is
    a state transition, and a hand-written fake would be asserting my guess at
    the transition rather than the collaborator's. max_failures=1 opens on the
    first failure; 5 leaves it closed.
    """
    compiler = wc.WikiCompiler.__new__(wc.WikiCompiler)
    compiler._model_breaker = CircuitBreaker(
        "test-breaker", max_failures=max_failures, reset_timeout=1800.0
    )

    with caplog.at_level(logging.DEBUG, logger="hydraflow.wiki_compiler"):
        compiler._record_model_failure("timed out after 300s", "compile:architecture")

    # getMessage() renders msg % args once; formatting by hand double-applies it.
    assert any(
        "compile:architecture" in r.getMessage() for r in caplog.records
    ), "the failure log did not name the failing call"
    assert any(r.levelno == expected_level for r in caplog.records)


def test_open_transition_says_the_breaker_is_shared(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The named call TRIPPED the breaker; it is not necessarily the only one
    affected. Without that note the log invites fixing the wrong operation.

    Asserted against the EMITTED record, not by grepping the source for the
    word — a source grep passes if "shared" appears in any unrelated comment.
    """
    compiler = wc.WikiCompiler.__new__(wc.WikiCompiler)
    compiler._model_breaker = CircuitBreaker(
        "test-breaker", max_failures=1, reset_timeout=1800.0
    )

    with caplog.at_level(logging.DEBUG, logger="hydraflow.wiki_compiler"):
        compiler._record_model_failure("timed out", "generalize_pair")

    opened = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert opened, "no ERROR emitted on the transition to OPEN"
    message = opened[0].getMessage()
    assert "generalize_pair" in message
    assert "shared" in message.lower()
