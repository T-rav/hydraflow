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
    SRC,
    find_violations_in_source,
    find_violations_in_unit,
    iter_src_units,
    iter_supervised_loop_units,
)

# Ratchet allow-list, keyed by path relative to src/ (e.g. "foo_loop.py" or
# "foo_loop/_spawn.py"). MUST shrink toward empty and MUST NOT grow — every new
# supervised loop must reraise credit/auth from its own broad excepts before it
# lands.
_GRANDFATHERED: frozenset[str] = frozenset()

# Same contract, for the whole-src/ widening below. Empty because the
# #11664/#11666 sweep fixed every site it found; it must stay that way.
_SRC_GRANDFATHERED: frozenset[str] = frozenset()


def _violations_by_file() -> dict[str, list[int]]:
    """Return {path relative to src/: [try-block line numbers]} for every violator.

    Iterates loop UNITS, not files: a decomposed loop must be resolved with its
    sibling modules in scope or a spawn helper one file over reads as
    unreachable and the ratchet silently narrows (#11666). Results are still
    keyed per FILE so a failure names the file to edit.
    """
    offenders: dict[str, list[int]] = {}
    for unit in iter_supervised_loop_units():
        for path, violations in find_violations_in_unit(unit).items():
            offenders[path.relative_to(SRC).as_posix()] = [
                v.try_lineno for v in violations
            ]
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


def _src_violations_by_file() -> dict[str, list[int]]:
    """Same analysis, widened from the loop layer to every module in src/."""
    offenders: dict[str, list[int]] = {}
    for unit in iter_src_units():
        for path, violations in find_violations_in_unit(unit).items():
            offenders[path.relative_to(SRC).as_posix()] = [
                v.try_lineno for v in violations
            ]
    return offenders


def test_no_src_module_swallows_credit_in_a_broad_except() -> None:
    """The same guarantee, for all of src/ — not just the loop layer.

    The loop-layer ratchet above could only ever see loops, and the swallow
    that matters most often is not IN a loop: the #11664/#11666 sweep found
    ``TranscriptSummarizer.summarize_and_comment`` burying every error as
    ``return False`` — including credit exhaustion from its own summarization
    spawn — with all five phase callers re-swallowing on top. Six sites, none
    of them a loop, none of them visible to the loop-layer ratchet.

    src/ is clean as of this test landing, so this starts with an EMPTY
    grandfather list and exists to keep it that way. Without it the guards
    added by that sweep have no gate at all, which is precisely how the #6855
    guard went missing for months while its own regression test passed.
    """
    offenders = {
        name: lines
        for name, lines in _src_violations_by_file().items()
        if name not in _SRC_GRANDFATHERED
    }
    assert not offenders, (
        "These src/ modules have a broad `except Exception` / "
        "`except (..., RuntimeError)` guarding a call path that reaches an "
        f"LLM spawn without reraising credit/auth first: {offenders} "
        "(file -> try-block line numbers). Make "
        "`reraise_on_credit_or_bug(exc)` (from `exception_classify`) the "
        "FIRST statement in the handler. Note that fixing only the INNERMOST "
        "site is cosmetic if its callers also swallow — walk the whole chain, "
        "as the transcript-summary fix had to."
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

# --- Cross-module (decomposed-loop) fixtures, #11666 ----------------------
#
# The shape a god-class decomposition produces: the `try` ends up in one mixin
# file and the spawn helper it wraps ends up in a sibling. Analysed per FILE,
# `_spawn_helper` is an unresolvable name and the try reads as spawn-free — the
# ratchet goes quiet at exactly the moment the loop gets decomposed. Analysed
# per LOOP UNIT, the sibling is in scope and the swallow is caught.

_DECOMPOSED_TRY_SIDE = """
class FooLoop(BaseBackgroundLoop):
    async def _do_work(self):
        try:
            return await self._spawn_helper("prompt")
        except Exception as exc:
            logger.warning("failed: %s", exc)
            return None
"""

_DECOMPOSED_SPAWN_SIDE = """
from runner_utils import run_lightweight_agent


class FooSpawnMixin:
    async def _spawn_helper(self, prompt):
        return await run_lightweight_agent(
            runner=get_default_runner(),
            config=self._config,
            tool="claude",
            model="sonnet",
            prompt=prompt,
            source="foo",
        )
"""

_DECOMPOSED_TRY_SIDE_GUARDED = """
from exception_classify import reraise_on_credit_or_bug


class FooLoop(BaseBackgroundLoop):
    async def _do_work(self):
        try:
            return await self._spawn_helper("prompt")
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("failed: %s", exc)
            return None
"""


def test_ratchet_resolves_a_spawn_helper_in_a_sibling_module() -> None:
    """The #11666 regression: cross-module resolution within one loop package."""
    assert find_violations_in_source(
        _DECOMPOSED_TRY_SIDE, sibling_sources=[_DECOMPOSED_SPAWN_SIDE]
    ), (
        "a broad `except Exception` wrapping a call to a spawn-reaching helper "
        "defined in a SIBLING module of the same loop package must be flagged. "
        "Resolving per-file instead of per-loop-unit makes `_spawn_helper` an "
        "unknown name, the try reads as spawn-free, and the ratchet silently "
        "narrows the moment a loop is decomposed (#11666)."
    )


def test_ratchet_per_file_scope_is_what_missed_the_sibling_spawn() -> None:
    """Pins WHY the fix was needed, so a revert to per-file scope fails loudly.

    Without sibling context the very same source is NOT flagged. This asserts
    the old, narrow behaviour explicitly: if someone later widens single-file
    analysis, this test tells them the unit-scoped path is what the ratchet
    depends on rather than letting the guarantee quietly change shape.
    """
    assert not find_violations_in_source(_DECOMPOSED_TRY_SIDE), (
        "sanity: analysed alone, the try side has no resolvable spawn — this "
        "is the blind spot `find_violations_in_unit` exists to close"
    )


def test_ratchet_passes_decomposed_loop_that_reraises() -> None:
    """Cross-module resolution must not manufacture a false positive."""
    assert not find_violations_in_source(
        _DECOMPOSED_TRY_SIDE_GUARDED, sibling_sources=[_DECOMPOSED_SPAWN_SIDE]
    ), (
        "the sibling spawn IS reachable, but the handler's first action is "
        "`reraise_on_credit_or_bug(exc)` — it must not be flagged"
    )


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


_ISINSTANCE_GUARD_PEP604 = """
from runner_utils import run_lightweight_agent


def spawn():
    try:
        return await run_lightweight_agent(
            runner=get_default_runner(), config=None,
            tool="claude", model="sonnet", prompt="x", source="y",
        )
    except Exception as exc:
        if isinstance(exc, AuthenticationError | CreditExhaustedError | OSError):
            raise
        logger.warning("soft failure")
        return None
"""

_ISINSTANCE_GUARD_WRONG_TYPES = """
from runner_utils import run_lightweight_agent


def spawn():
    try:
        return await run_lightweight_agent(
            runner=get_default_runner(), config=None,
            tool="claude", model="sonnet", prompt="x", source="y",
        )
    except Exception as exc:
        if isinstance(exc, TimeoutError):
            raise
        logger.warning("soft failure")
        return None
"""


def test_ratchet_accepts_isinstance_guard_in_pep604_form() -> None:
    """`if isinstance(exc, Auth | Credit | OSError): raise` is protected.

    The PEP 604 spelling is what `diagnostic_loop.py` and
    `post_merge_handler.py` actually use, so the detector must parse it.
    """
    assert not find_violations_in_source(_ISINSTANCE_GUARD_PEP604), (
        "an isinstance guard naming BOTH fatal types with a bare `raise` "
        "intercepts credit/auth before the soft path — not a violation"
    )


def test_ratchet_flags_isinstance_guard_on_unrelated_types() -> None:
    """The narrow read: re-raising some OTHER type is not a credit guard.

    Before the #11664 review this returned True for ANY `if isinstance(...):
    raise`, so this handler — which swallows credit on every path where the
    check is false — read as protected.
    """
    assert find_violations_in_source(_ISINSTANCE_GUARD_WRONG_TYPES), (
        "`if isinstance(exc, TimeoutError): raise` does not intercept "
        "CreditExhaustedError/AuthenticationError; the handler still swallows "
        "them and must be flagged"
    )


# --- "First action" shapes that do NOT swallow ---------------------------
#
# Both were live false positives when this audit was first run outside the loop
# layer (#11664/#11666 sweep). Neither handler can swallow anything, so the
# detector must recognise them or its findings cannot be trusted.

_GUARD_BEHIND_A_DEFERRED_IMPORT = """
from runner_utils import run_lightweight_agent


def build_runner(config):
    try:
        return await run_lightweight_agent(
            runner=get_default_runner(), config=config,
            tool="claude", model="sonnet", prompt="x", source="y",
        )
    except Exception as exc:
        from exception_classify import reraise_on_credit_or_bug

        reraise_on_credit_or_bug(exc)
        logger.warning("construction failed")
        return None
"""

_CLEANUP_THEN_UNCONDITIONAL_BARE_RAISE = """
from runner_utils import run_lightweight_agent


def spawn(collector):
    try:
        return await run_lightweight_agent(
            runner=get_default_runner(), config=None,
            tool="claude", model="sonnet", prompt="x", source="y",
        )
    except Exception:
        if collector is not None:
            collector.finalize(success=False)
        raise
"""

_CLEANUP_THEN_RAISE_BUT_ONE_PATH_RETURNS = """
from runner_utils import run_lightweight_agent


def spawn(collector):
    try:
        return await run_lightweight_agent(
            runner=get_default_runner(), config=None,
            tool="claude", model="sonnet", prompt="x", source="y",
        )
    except Exception:
        if collector is not None:
            return None
        raise
"""


def test_ratchet_sees_past_a_deferred_import_to_the_guard() -> None:
    """An `import` cannot swallow, so the guard behind it is still first."""
    assert not find_violations_in_source(_GUARD_BEHIND_A_DEFERRED_IMPORT), (
        "docker_runner.py imports `reraise_on_credit_or_bug` inside the "
        "handler to dodge a module cycle; counting that import as the "
        "handler's first action reported a protected site as a violation"
    )


def test_ratchet_accepts_cleanup_followed_by_unconditional_reraise() -> None:
    """`except: <cleanup>; raise` never swallows, wherever the raise sits."""
    assert not find_violations_in_source(_CLEANUP_THEN_UNCONDITIONAL_BARE_RAISE), (
        "base_runner.py finalizes its trace collector and then re-raises "
        "unconditionally — every path out of the handler is the bare `raise`, "
        "so nothing is swallowed"
    )


def test_ratchet_still_flags_a_trailing_raise_some_paths_skip() -> None:
    """The narrow read of the above: a `return` before the raise DOES swallow."""
    assert find_violations_in_source(_CLEANUP_THEN_RAISE_BUT_ONE_PATH_RETURNS), (
        "a handler ending in `raise` is only safe when no path exits first — "
        "`if collector is not None: return None` swallows credit on that "
        "branch and must still be flagged"
    )
