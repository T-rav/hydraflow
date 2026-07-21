"""Factory validation: supervised loops must propagate credit/auth (#9101).

The credit-swallow bug class recurs: a supervised ``BaseBackgroundLoop``
subclass spawns an LLM, the spawn raises ``CreditExhaustedError``, but a
broad ``except (ValueError, RuntimeError)`` / ``except Exception`` one layer
up in the loop's own ``*_loop.py`` re-swallows it — ``CreditExhaustedError``
subclasses ``RuntimeError`` (``src/subprocess_util.py``) — so
``BaseBackgroundLoop`` never pauses and the loop burns attempt budget
against an exhausted account.

The existing WS-2.2 containment ratchets
(``test_telemetry_source_completeness.py``,
``test_subprocess_runner_contract_completeness.py``) check that a spawn
module *contains* a credit detector but cannot prove the signal reaches a
pause handler one layer up — that gap is what this ratchet closes,
structurally, for every supervised ``src/*_loop.py``.

SCOPE OF THE GUARANTEE: see ``tests/_credit_reraise_audit.py`` for the full
detection heuristic and its documented over-approximation. ``_GRANDFATHERED``
must shrink toward empty and must never grow — it is empty today because a
prior manual pass (WS-2.2 self-review M1; see ``term_proposer_loop.py`` and
``entry_evidence_loop.py``) already fixed every known instance of this
pattern in the current supervised-loop set. New violations must be fixed on
sight, not added to this set as a matter of convenience.

Ref: ADR-0055 (telemetry/credit contract for spawn paths),
``docs/wiki/dark-factory.md`` §2.2, ``src/exception_classify.py``.
"""

from __future__ import annotations

from tests._credit_reraise_audit import (
    find_violations_in_file,
    find_violations_in_source,
    iter_supervised_loop_files,
)

# Ratchet allow-list, keyed by filename relative to src/. MUST shrink toward
# empty and MUST NOT grow — every new supervised loop must reraise credit/auth
# from its own broad excepts before it lands.
_GRANDFATHERED: frozenset[str] = frozenset()


def _violations_by_file() -> dict[str, list[int]]:
    """Return {loop filename: [try-block line numbers]} for every real violator."""
    offenders: dict[str, list[int]] = {}
    for path in iter_supervised_loop_files():
        violations = find_violations_in_file(path)
        if violations:
            offenders[path.name] = [v.try_lineno for v in violations]
    return offenders


def test_no_supervised_loop_swallows_credit_in_a_broad_except() -> None:
    all_offenders = _violations_by_file()
    offenders = {
        name: lines
        for name, lines in all_offenders.items()
        if name not in _GRANDFATHERED
    }
    assert not offenders, (
        "These supervised loops have a broad `except Exception` / "
        "`except (..., RuntimeError)` guarding a call path that reaches an "
        f"LLM spawn without reraising credit/auth first: {offenders} "
        "(file -> try-block line numbers). CreditExhaustedError and "
        "AuthenticationError both subclass RuntimeError, so the broad except "
        "silently swallows them and BaseBackgroundLoop never pauses — the "
        "loop keeps spawning against an exhausted account. Fix by making "
        "`reraise_on_credit_or_bug(exc)` (from `exception_classify`) the "
        "FIRST statement in the handler, or by adding a narrower "
        "`except (AuthenticationError, CreditExhaustedError): raise` clause "
        "ahead of the broad one. If this is a deliberate, reviewed exception, "
        "add the filename to `_GRANDFATHERED` with a comment explaining why."
    )


def test_credit_reraise_grandfather_list_is_empty() -> None:
    """Documents intent: no supervised loop should need this escape hatch.

    Unlike the telemetry ratchet's grandfather list (blocked on a real
    constructor-threading migration), there is no known reason a loop can't
    just call `reraise_on_credit_or_bug(exc)` first — it's a one-line fix.
    """
    assert frozenset() == _GRANDFATHERED, (
        "_GRANDFATHERED must stay empty — every supervised loop's broad "
        f"excepts already reraise credit/auth. Found exemptions: "
        f"{sorted(_GRANDFATHERED)}"
    )


def test_credit_reraise_grandfather_only_real_violators() -> None:
    """A stale grandfather entry (no longer a violator) must be removed."""
    offenders = set(_violations_by_file())
    stale = sorted(_GRANDFATHERED - offenders)
    assert not stale, (
        f"_GRANDFATHERED has stale entries that no longer swallow credit: "
        f"{stale}. Remove them — the ratchet is already satisfied for these "
        "files."
    )


# --- Self-tests: prove the ratchet is neither vacuous nor overzealous -----
#
# These feed synthetic AST snippets directly to the detector (bypassing the
# filesystem) so the ratchet's own logic is under test, independent of
# whatever real `src/*_loop.py` happens to contain today.

_FRESH_VIOLATION = """
from subprocess_util import AuthenticationError, CreditExhaustedError
from runner_utils import run_lightweight_agent


class DemoLoop(BaseBackgroundLoop):
    async def _do_work(self):
        try:
            result = await run_lightweight_agent(
                runner=get_default_runner(),
                config=self._config,
                tool="claude",
                model="sonnet",
                prompt="demo",
                source="demo",
            )
        except (ValueError, RuntimeError) as exc:
            logger.warning("demo spawn failed: %s", exc)
            return None
        return result
"""

_PROTECTED_VIA_RERAISE_HELPER = """
from exception_classify import reraise_on_credit_or_bug
from runner_utils import run_lightweight_agent


class DemoLoop(BaseBackgroundLoop):
    async def _do_work(self):
        try:
            result = await run_lightweight_agent(
                runner=get_default_runner(),
                config=self._config,
                tool="claude",
                model="sonnet",
                prompt="demo",
                source="demo",
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("demo spawn failed: %s", exc)
            return None
        return result
"""

_PROTECTED_VIA_NARROW_HANDLER_FIRST = """
from subprocess_util import AuthenticationError, CreditExhaustedError
from runner_utils import run_lightweight_agent


class DemoLoop(BaseBackgroundLoop):
    async def _do_work(self):
        try:
            result = await run_lightweight_agent(
                runner=get_default_runner(),
                config=self._config,
                tool="claude",
                model="sonnet",
                prompt="demo",
                source="demo",
            )
        except (AuthenticationError, CreditExhaustedError):
            raise
        except (ValueError, RuntimeError) as exc:
            logger.warning("demo spawn failed: %s", exc)
            return None
        return result
"""

_PROTECTED_VIA_HELPER_CLASS = """
from runner_utils import run_lightweight_agent
from exception_classify import reraise_on_credit_or_bug


class _CLIDemoLLM:
    async def complete(self, prompt):
        result = await run_lightweight_agent(
            runner=get_default_runner(),
            config=self._config,
            tool="claude",
            model="sonnet",
            prompt=prompt,
            source="demo",
        )
        return result.stdout


class DemoLoop(BaseBackgroundLoop):
    async def _demo_complete(self, prompt):
        return await self._demo_llm.complete(prompt)

    async def _do_work(self):
        try:
            raw = await self._demo_complete("hi")
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("demo failed: %s", exc)
            return None
        return raw
"""

_UNRELATED_BROAD_EXCEPT_NO_SPAWN = """
class DemoLoop(BaseBackgroundLoop):
    async def _cleanup_worktree(self, worktree_dir):
        try:
            await self._run_git(["git", "worktree", "remove", "--force", str(worktree_dir)])
        except Exception:
            logger.warning("cleanup failed for %s", worktree_dir, exc_info=True)
"""


def test_ratchet_flags_a_broad_except_that_swallows_credit() -> None:
    violations = find_violations_in_source(_FRESH_VIOLATION)
    assert violations, (
        "the ratchet must flag a broad `except (ValueError, RuntimeError)` "
        "guarding a `run_lightweight_agent` spawn whose first action is not "
        "a reraise"
    )


def test_ratchet_passes_when_reraise_helper_is_first_action() -> None:
    assert not find_violations_in_source(_PROTECTED_VIA_RERAISE_HELPER), (
        "a broad except whose FIRST statement is "
        "`reraise_on_credit_or_bug(exc)` must not be flagged"
    )


def test_ratchet_passes_when_narrow_handler_precedes_broad_one() -> None:
    assert not find_violations_in_source(_PROTECTED_VIA_NARROW_HANDLER_FIRST), (
        "an `except (AuthenticationError, CreditExhaustedError): raise` "
        "ahead of the broad handler already intercepts credit/auth — the "
        "broad handler below it must not be flagged"
    )


def test_ratchet_follows_spawn_through_a_same_module_helper() -> None:
    assert not find_violations_in_source(_PROTECTED_VIA_HELPER_CLASS), (
        "the spawn is reached indirectly via `self._demo_llm.complete(...)` "
        "-> `_CLIDemoLLM.complete` -> `run_lightweight_agent`; the ratchet's "
        "call-graph resolution must follow it and recognize the guarding "
        "except IS protected (mirrors issue_refinement_loop.py's "
        "_CLIRefinementLLM pattern)"
    )


def test_ratchet_ignores_a_broad_except_that_never_reaches_a_spawn() -> None:
    assert not find_violations_in_source(_UNRELATED_BROAD_EXCEPT_NO_SPAWN), (
        "a broad except around a plain subprocess call (git, not an LLM "
        "spawn) must not be flagged — this is the staging_bisect_loop.py "
        "shape: `run_simple` without an agent argv is NOT a spawn marker"
    )
