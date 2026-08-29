"""Pure classification of the #10223 false-close signature (P10.6/P10.7 core).

An issue-closing change is a *false close* when its own diff carries neither a
non-test product-source change nor a ``tests/regressions/`` delta, and no
``Skip-Regression: <justification>`` opt-out trailer justifies the gap. The
#10223 regression-rot audit found this shape in 42/64 closed issues: "done"
was emitted with nothing that could have fixed the bug — an open control loop.

Two consumers share this one signature so the sensor and the actuator can
never disagree on what "false close" means:

* **P10.7** (``checks/p10_tdd.py``) — the *detector*: a merged-history scan
  that WARNs on delta-less ``Closes #N`` commits (telemetry, never blocks CI).
* **The close-verification controller** (``src/close_verification.py``, #10358)
  — the *actuator*: a post-merge observer that REOPENS + re-triages an issue
  the just-merged PR closed with this signature.

Everything here is pure (regex + list filtering) with no dependency on the
audit framework, so the ``src`` observer can import it without dragging in the
check registry. ``checks/p10_tdd.py`` re-imports these back so P10.6/P10.7 keep
classifying through the same code.
"""

from __future__ import annotations

import re

# GitHub's issue-closing keywords (close/closes/closed, fix/fixes/fixed,
# resolve/resolves/resolved) followed by ``#<number>``. A ``fix:`` conventional
# prefix does not match — the ``:``/`` `` between the word and ``#`` breaks it.
CLOSE_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b",
    re.IGNORECASE,
)

# The greppable opt-out trailer P10.6 honours (``Skip-Regression: <why>``);
# its justification survives into the squash-merge body.
SKIP_REGRESSION_RE = re.compile(r"^Skip-Regression:\s*(\S.*)$", re.MULTILINE)

# UI regression coverage: a test delta under the UI tree counts for UI-only
# fixes, so such paths are excluded from the "product source" fix-delta set.
#
# The package segment is optional because two src layouts are in the wild: flat
# ``src/ui/`` (this repo) and packaged ``src/<pkg>/ui/`` (what
# ``onboarding/kernel_writer`` stamps). Anchored on a literal ``src/ui/`` this
# matched nothing on a stamped repo, so a UI-only fix there was read as an
# uncovered Python fix and P10.6's WARN failed the audit gate (#11709).
UI_TEST_RE = re.compile(
    r"^src/(?:[A-Za-z_][A-Za-z0-9_]*/)?ui/.*(?:__tests__/|\.test\.[jt]sx?$)"
)


def closing_issue_refs(body: str) -> set[int]:
    """Issue numbers a commit/PR message declares it closes."""
    return {int(m) for m in CLOSE_KEYWORD_RE.findall(body)}


def has_regression_delta(paths: list[str]) -> bool:
    """True when any changed path lives under ``tests/regressions/``."""
    return any(path.startswith("tests/regressions/") for path in paths)


def product_paths(paths: list[str]) -> list[str]:
    """Changed paths that are non-test product source (the P10.6 fix-delta set).

    Excludes tests, docs, CI workflow, and UI test files — the same filter the
    per-PR gate uses to decide whether a regression test is even applicable.
    """
    return [
        path
        for path in paths
        if not path.startswith(("tests/", "docs/", ".github/"))
        and not UI_TEST_RE.match(path)
    ]


def has_fix_delta(paths: list[str]) -> bool:
    """True when the change carries a fix delta: a regression test OR product source."""
    return has_regression_delta(paths) or bool(product_paths(paths))


def has_skip_regression(message: str) -> bool:
    """True when *message* carries a ``Skip-Regression:`` opt-out trailer."""
    return bool(SKIP_REGRESSION_RE.search(message))


def is_false_close(paths: list[str], message: str) -> bool:
    """True when a close carries the #10223 false-close signature.

    A close is a *false close* when its own diff (*paths*) carries neither a
    ``tests/regressions/`` delta nor non-test product source, AND its *message*
    carries no ``Skip-Regression:`` opt-out trailer. This is exactly what P10.7
    flags — the controller reuses it verbatim so detector and actuator agree.
    """
    if has_skip_regression(message):
        return False
    return not has_fix_delta(paths)
