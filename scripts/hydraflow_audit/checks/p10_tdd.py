"""P10 — TDD workflow discipline (ADR-0044)."""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

# ``false_close`` lives in ``src`` (#10365) — ``src`` must never import from
# ``scripts`` (the container runs ``PYTHONPATH=src``). The package ``__init__``
# adds ``src`` to ``sys.path`` so this top-level import resolves under both
# ``make audit`` (root on path) and the test suite (root + src on path).
from false_close import SKIP_REGRESSION_RE as _SKIP_REGRESSION_RE
from false_close import UI_TEST_RE as _UI_TEST_RE
from false_close import closing_issue_refs as _closing_issue_refs
from false_close import has_regression_delta as _has_regression_delta
from false_close import product_paths as _product_paths

from ..layout import src_candidates
from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import finding


@register("P10.1")
def _claude_md_documents_tdd(ctx: CheckContext) -> Finding:
    claude = ctx.root / "CLAUDE.md"
    if not claude.exists():
        return finding("P10.1", Status.FAIL, "CLAUDE.md missing")
    text = claude.read_text(encoding="utf-8", errors="replace")
    names_skill = "test-driven-development" in text
    mentions_test_first = bool(
        re.search(
            r"\btest[- ]first\b|\bwrite.*test.*before\b|\bTDD\b", text, re.IGNORECASE
        )
    )
    if names_skill and mentions_test_first:
        return finding("P10.1", Status.PASS)
    missing: list[str] = []
    if not names_skill:
        missing.append("`superpowers:test-driven-development` skill reference")
    if not mentions_test_first:
        missing.append("a test-first / TDD mention")
    return finding(
        "P10.1",
        Status.WARN,
        f"CLAUDE.md missing: {', '.join(missing)}",
    )


@register("P10.2")
def _every_module_has_a_test(ctx: CheckContext) -> Finding:
    src = ctx.src_root()
    tests = ctx.root / "tests"
    if not src.is_dir():
        return finding("P10.2", Status.NA, f"no {ctx.rel(src)}/")
    if not tests.is_dir():
        return finding("P10.2", Status.FAIL, "tests/ missing")

    src_modules: dict[str, Path] = {}
    for module in src.rglob("*.py"):
        if _skip_module(module) or module.stem.startswith("_"):
            continue
        src_modules[module.stem] = module
    src_stems = set(src_modules)

    # A module is "covered" by any test whose stem matches it exactly OR
    # starts with ``<module>_`` — pr_manager.py is covered by
    # test_pr_manager_observability.py, not just test_pr_manager.py.
    # Longest-prefix wins so that test_state_tracking.py is credited to
    # state_tracking (when that module exists), not to state.
    covered: set[str] = set()
    for tp in tests.rglob("test_*.py"):
        test_stem = tp.stem.removeprefix("test_")
        best: str | None = None
        for src_stem in src_stems:
            if (test_stem == src_stem or test_stem.startswith(src_stem + "_")) and (
                best is None or len(src_stem) > len(best)
            ):
                best = src_stem
        if best is not None:
            covered.add(best)

    orphans = sorted(
        src_modules[stem].relative_to(ctx.root).as_posix()
        for stem in src_stems - covered
    )
    total = len(src_stems)
    if not orphans:
        return finding("P10.2", Status.PASS)
    ratio = len(orphans) / total if total else 0
    if ratio < 0.2:
        return finding(
            "P10.2",
            Status.PASS,
            f"{len(orphans)}/{total} modules without matching test ({ratio:.0%})",
        )
    sample = ", ".join(orphans[:3])
    return finding(
        "P10.2",
        Status.WARN,
        f"{len(orphans)}/{total} {ctx.rel(src)}/ modules have no "
        f"test_<module>.py counterpart ({sample})",
    )


def _skip_module(path: Path) -> bool:
    name = path.name
    return (
        name == "__init__.py"
        or name.endswith("_pb2.py")
        or "/migrations/" in path.as_posix()
    )


_FIX_COMMIT_RE = re.compile(r"^(fix|bugfix|bug)[\(:]", re.IGNORECASE)
_BASELINE_FILE = ".hydraflow-audit-baseline"
# ISO date (2026-07-02) or timestamp (2026-07-02T21:00:00Z). Anything else
# in the baseline file is treated as a commit-ish.
_DATE_BASELINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].+)?$")


def _baseline_selector(baseline: str) -> str:
    """Turn the declared baseline into a ``git log`` selector argument.

    Dates become ``--since=`` filters, which are branch-independent: they
    work on PR merge commits into staging AND on main, with no requirement
    that the baseline commit be an ancestor of HEAD (squash-based RC
    promotion means no post-promotion staging SHA ever is). Bare dates get
    an explicit midnight because git's approxidate fills missing
    time-of-day fields from the *current* clock — ``--since=2026-07-02``
    run at 14:00 silently excludes that morning's commits. Anything
    non-date-shaped is treated as a commit-ish range start.
    """
    if not _DATE_BASELINE_RE.match(baseline):
        return f"{baseline}..HEAD"
    if "T" in baseline or " " in baseline:
        return f"--since={baseline}"
    return f"--since={baseline}T00:00:00"


@register("P10.3")
def _bug_fixes_land_with_regression_tests(ctx: CheckContext) -> Finding:  # noqa: PLR0911 — fast-path NA returns are clearer than a chain
    """Measure recent fix commits against regression-test discipline.

    The principle's intent is "every bug fix *from now on* lands with a
    regression test." Historical drift predates the principle's adoption.
    Two mechanisms keep the check honest:

    1. A `.hydraflow-audit-baseline` file (commit SHA or ISO date) lets a
       project declare the point at which the rule took effect; earlier
       fix commits are excluded.
    2. The threshold is 60% compliance on *recent* fixes — a project
       improving its discipline reaches PASS before rewriting history.
    """
    if not (ctx.root / ".git").exists():
        return finding("P10.3", Status.NA, "not a git repo")
    baseline = _read_baseline(ctx.root)
    git_args = ["git", "log", "--no-merges", "-n", "50", "--format=%H%x09%s"]
    if baseline is not None:
        git_args.append(_baseline_selector(baseline))
    try:
        result = subprocess.run(
            git_args,
            check=False,
            cwd=ctx.root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return finding("P10.3", Status.NA, "git log timed out")
    if result.returncode != 0:
        return finding("P10.3", Status.NA, "git log failed")
    fix_commits = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()
        if "\t" in line and _FIX_COMMIT_RE.match(line.split("\t", 1)[1])
    ]
    # A `fix(...)` commit that touches ONLY files under tests/ is test
    # maintenance (updating a test to match intended behaviour, adding a
    # regression test), not a product bug fix — demanding it add *another*
    # regression test is nonsensical, and such commits would otherwise drag
    # the ratio down purely on their conventional-commit prefix. Exclude
    # them: the principle is "every bug fix in *product code* lands with a
    # regression test."
    fix_commits = [
        sha for sha in fix_commits if not _is_test_only_commit(ctx.root, sha)
    ]
    if baseline is None:
        scope = "last 50 commits"
    elif _DATE_BASELINE_RE.match(baseline):
        scope = f"since baseline {baseline}"
    else:
        scope = f"since baseline {baseline[:7]}"
    if not fix_commits:
        return finding(
            "P10.3", Status.PASS, f"no fix/bug commits {scope} — nothing to audit"
        )
    missing: list[str] = []
    for sha in fix_commits:
        if not _touched_regressions(ctx.root, sha):
            missing.append(sha[:7])
    covered = len(fix_commits) - len(missing)
    ratio = covered / len(fix_commits)
    if not missing:
        return finding(
            "P10.3",
            Status.PASS,
            f"{len(fix_commits)} fix commit(s) {scope} all touched regressions/",
        )
    if ratio >= 0.6:
        return finding(
            "P10.3",
            Status.PASS,
            f"{covered}/{len(fix_commits)} fix commits {scope} carry regression tests ({ratio:.0%})",
        )
    sample = ", ".join(missing[:3])
    return finding(
        "P10.3",
        Status.WARN,
        f"{len(missing)}/{len(fix_commits)} fix commits {scope} without a regression test ({sample}) — "
        "telemetry only (#9902): this scans MERGED history, so it cannot "
        "blame the PR under test and never fails PR CI; per-PR enforcement "
        "is P10.6",
    )


def _read_baseline(root: Path) -> str | None:
    """Return a commit SHA or ISO date the user declared as the rule's start point."""
    path = root / _BASELINE_FILE
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return None
    # Strip a leading `#`-prefixed comment line if present.
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return lines[0] if lines else None


def _is_test_only_commit(root: Path, sha: str) -> bool:
    """True when every file *sha* touched lives under ``tests/``.

    Such a commit is test maintenance, not a product bug fix, so P10.3
    excludes it from the regression-test-discipline ratio. A commit that
    touches no files (empty) is not treated as test-only (returns False) so
    it can't silently drop out. Errors return False — never exclude a
    commit we couldn't inspect, so the check fails safe toward *counting*.
    """
    try:
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", sha],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not files:
        return False
    return all(f.startswith("tests/") for f in files)


def _touched_regressions(root: Path, sha: str) -> bool:
    try:
        # --name-only (not --stat): --stat truncates long paths with `...`,
        # so a real regression test like
        # tests/regressions/test_issue_9419_9421_adr_drift.py is silently
        # dropped from the output, false-flagging the commit as missing a
        # test. --name-only emits full, untruncated paths.
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", sha],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return True  # don't false-alarm on errors
    return "tests/regressions/" in result.stdout


_PR_BASE_ENV = "HYDRAFLOW_AUDIT_PR_BASE"


def _resolve_merge_base(root: Path, base: str) -> str | None:
    """Return the merge-base sha of HEAD and *base* (trying origin/ first)."""
    for candidate in (f"origin/{base}", base):
        try:
            result = subprocess.run(
                ["git", "merge-base", candidate, "HEAD"],
                check=False,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _pr_fix_shas(root: Path, merge_base: str) -> list[str] | None:
    """Fix-prefixed, non-test-only commit shas in the PR's own range."""
    try:
        result = subprocess.run(
            ["git", "log", "--no-merges", "--format=%H%x09%s", f"{merge_base}..HEAD"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    shas = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()
        if "\t" in line and _FIX_COMMIT_RE.match(line.split("\t", 1)[1])
    ]
    return [sha for sha in shas if not _is_test_only_commit(root, sha)]


def _skip_regression_reason(root: Path, merge_base: str) -> str | None:
    """Return the first Skip-Regression: trailer justification in the range."""
    try:
        result = subprocess.run(
            ["git", "log", "--no-merges", "--format=%B", f"{merge_base}..HEAD"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    match = _SKIP_REGRESSION_RE.search(result.stdout)
    return match.group(1).strip() if match else None


def _ui_prefixes(ctx: CheckContext) -> tuple[str, ...]:
    """Repo-relative prefixes a UI product file can sit under, both layouts.

    Diff paths are repo-relative strings, so this is the string-prefix twin of
    ``ctx.src_dir("ui")``. A literal ``"src/ui/"`` matched nothing on a repo the
    kernel writer stamped, so its UI-only fixes fell through to P10.6's WARN —
    which is NOT in ``runner._NON_BLOCKING_WARN_CHECKS`` and therefore failed
    the audit gate outright (#11709).
    """
    return tuple(
        f"{ctx.rel(candidate)}/"
        for candidate in src_candidates(ctx.root, ("ui",), ctx.src_packages)
    )


def _evaluate_pr_regression_delta(ctx: CheckContext, merge_base: str) -> Finding:
    """Judge the PR's own diff for regression coverage (P10.6 core)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{merge_base}..HEAD"],
            check=False,
            cwd=ctx.root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return finding("P10.6", Status.NA, "git diff failed")
    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if _has_regression_delta(paths):
        return finding(
            "P10.6", Status.PASS, "fix PR carries a tests/regressions/ delta"
        )
    product = _product_paths(paths)
    if not product:
        # No product code changed — the PR only touches CI/workflow (.github/),
        # docs, and/or tests. A Python/UI regression test is not applicable to a
        # `fix(ci): ...`, `fix(docs): ...`, or test-only fix; requiring one here
        # was a false failure that reddened every such PR.
        return finding(
            "P10.6",
            Status.PASS,
            "no product-code delta (CI/workflow/docs/test-only changes) — a "
            "regression test is not applicable",
        )
    ui_prefixes = _ui_prefixes(ctx)
    ui_only = bool(product) and all(path.startswith(ui_prefixes) for path in product)
    if ui_only and any(_UI_TEST_RE.match(path) for path in paths):
        return finding(
            "P10.6",
            Status.PASS,
            "UI-only fix carries a UI test delta (accepted as regression "
            "coverage — no token Python test required)",
        )
    return finding(
        "P10.6",
        Status.WARN,
        "fix(...) commits in THIS PR have no regression-test delta — add a "
        "test under tests/regressions/ (or a UI test delta under "
        f"{' / '.join(ui_prefixes)} for UI-only fixes), or opt out with a "
        "`Skip-Regression: <justification>` commit trailer when coverage "
        "legitimately lives elsewhere",
    )


def _pr_gate_preflight(root: Path) -> tuple[str | None, Finding | None]:
    """Resolve the PR merge base, or the NA finding explaining why not."""
    if not (root / ".git").exists():
        return None, finding("P10.6", Status.NA, "not a git repo")
    base = os.environ.get(_PR_BASE_ENV, "").strip()
    if not base:
        return None, finding(
            "P10.6", Status.NA, f"not a PR context ({_PR_BASE_ENV} unset)"
        )
    merge_base = _resolve_merge_base(root, base)
    if merge_base is None:
        return None, finding("P10.6", Status.NA, f"base ref {base!r} not resolvable")
    return merge_base, None


@register("P10.6")
def _fix_prs_carry_regression_delta(ctx: CheckContext) -> Finding:
    """Per-PR enforcement of the regression-test principle (#9902).

    Unlike P10.3 (a history-scan TELEMETRY metric that cannot blame the PR
    under test), this gate reads the PR's OWN merge-base diff and fails
    only the offending PR. Off-PR contexts (local audits, push builds) are
    NA — the branch-history metric covers them. The base branch arrives
    via ``HYDRAFLOW_AUDIT_PR_BASE`` (the CI workflow passes
    ``github.base_ref``).
    """
    merge_base, na = _pr_gate_preflight(ctx.root)
    if na is not None:
        return na
    assert merge_base is not None
    fix_shas = _pr_fix_shas(ctx.root, merge_base)
    if fix_shas is None:
        return finding("P10.6", Status.NA, "git log failed")
    if not fix_shas:
        return finding("P10.6", Status.PASS, "no product fix(...) commits in this PR")
    reason = _skip_regression_reason(ctx.root, merge_base)
    if reason:
        return finding(
            "P10.6",
            Status.PASS,
            f"Skip-Regression trailer present: {reason} (justification "
            "survives into the squash body)",
        )
    return _evaluate_pr_regression_delta(ctx, merge_base)


_CLOSE_SCAN_COUNT = 100


def _recent_commits_with_bodies(root: Path, count: int) -> list[tuple[str, str]] | None:
    """The last *count* non-merge commits as ``(sha, full_message)`` pairs."""
    sep_record = "\x1e"
    sep_field = "\x1f"
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--no-merges",
                "-n",
                str(count),
                f"--format={sep_record}%H{sep_field}%B",
            ],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    commits: list[tuple[str, str]] = []
    for record in result.stdout.split(sep_record):
        if sep_field not in record:
            continue
        sha, body = record.split(sep_field, 1)
        commits.append((sha.strip(), body))
    return commits


def _commit_paths(root: Path, sha: str) -> list[str]:
    """Files touched by *sha* — for a squash merge, the whole PR delta."""
    try:
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", sha],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


@register("P10.7")
def _closed_issues_carry_fix_delta(ctx: CheckContext) -> Finding:
    """Detector: an issue closed with no fix delta is a suspected false-close.

    The #10223 regression-rot audit found 42/64 closed issues where no fix
    actually landed — the "done" signal fired without any change that could
    have fixed the bug. This history-scan detector reuses P10.6's fix-delta
    classification (``tests/regressions/`` OR non-test product source, with the
    same ``Skip-Regression:`` opt-out) and applies it at the *issue-close*
    trigger: a ``Closes #N`` commit whose own diff carries neither is flagged
    for re-triage.

    Like P10.3 this scans MERGED history, so it cannot blame the PR under test
    and is telemetry — it reports WARN but never fails PR CI (per-PR
    enforcement is P10.6; the controller that refuses the close lives at the
    orchestration close path, tracked as the #10354 follow-up).
    """
    if not (ctx.root / ".git").exists():
        return finding("P10.7", Status.NA, "not a git repo")
    commits = _recent_commits_with_bodies(ctx.root, _CLOSE_SCAN_COUNT)
    if commits is None:
        return finding("P10.7", Status.NA, "git log failed")
    scanned = 0
    flagged: list[str] = []
    for sha, body in commits:
        issues = _closing_issue_refs(body)
        if not issues:
            continue
        scanned += 1
        if _SKIP_REGRESSION_RE.search(body):
            continue  # explicit, greppable justification — legitimate close
        paths = _commit_paths(ctx.root, sha)
        if _has_regression_delta(paths) or _product_paths(paths):
            continue  # a real fix delta landed
        for number in sorted(issues):
            flagged.append(f"#{number} ({sha[:7]})")
    if scanned == 0:
        return finding(
            "P10.7",
            Status.PASS,
            f"no Closes-#N commits in the last {_CLOSE_SCAN_COUNT} — nothing to audit",
        )
    if not flagged:
        return finding(
            "P10.7",
            Status.PASS,
            f"all {scanned} issue-close(s) in the last {_CLOSE_SCAN_COUNT} commits "
            "carried a source or regression fix delta",
        )
    sample = ", ".join(flagged[:5])
    return finding(
        "P10.7",
        Status.WARN,
        f"{len(flagged)} issue-close(s) carried no non-test source and no "
        f"tests/regressions/ delta — the #10223 false-close signature: {sample}. "
        "Re-triage/re-open, or add a `Skip-Regression: <why>` trailer when the "
        "fix legitimately lives elsewhere. Telemetry only (#10354): scans MERGED "
        "history, never fails PR CI (per-PR enforcement is P10.6).",
    )


@register("P10.4")
def _test_names_describe_behaviour(ctx: CheckContext) -> Finding:
    tests = ctx.root / "tests"
    if not tests.is_dir():
        return finding("P10.4", Status.NA, "no tests/")
    sampled = 0
    bad: list[str] = []
    for py in tests.rglob("test_*.py"):
        if sampled >= 300:
            break
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                sampled += 1
                if _is_implementation_named(node.name):
                    bad.append(f"{py.name}::{node.name}")
                if sampled >= 300:
                    break
    if sampled == 0:
        return finding("P10.4", Status.NA, "no test functions to sample")
    ratio = len(bad) / sampled
    if ratio < 0.1:
        return finding(
            "P10.4",
            Status.PASS,
            f"{len(bad)}/{sampled} tests with implementation-shaped names ({ratio:.0%})",
        )
    sample = ", ".join(bad[:3])
    return finding(
        "P10.4",
        Status.WARN,
        f"{len(bad)}/{sampled} tests named after functions (not behaviour): {sample}",
    )


def _is_implementation_named(test_name: str) -> bool:
    """Flag names like `test_merge_function` or `test_handler` that echo identifiers."""
    suffix = test_name.removeprefix("test_")
    # Heuristic: single word or camel-free snake = likely implementation name.
    # Behavioural names contain `_when_`, `_if_`, `_after_`, `_returns_`, etc.
    behavioural_markers = (
        "_when_",
        "_if_",
        "_given_",
        "_returns_",
        "_raises_",
        "_fails_",
        "_passes_",
        "_warns_",
        "_handles_",
        "_rejects_",
        "_accepts_",
        "_emits_",
    )
    if any(marker in test_name for marker in behavioural_markers):
        return False
    return "_" not in suffix or suffix.endswith(
        ("_function", "_method", "_handler", "_class")
    )


@register("P10.5")
def _tests_use_3as(ctx: CheckContext) -> Finding:
    """Heuristic: a test with ≥3 assertions in a row is likely conflating scenarios.

    Not a universal rule (parametrised tests with one assert are fine; some
    state-machine tests need two), so we only warn when the ratio is high.
    """
    tests = ctx.root / "tests"
    if not tests.is_dir():
        return finding("P10.5", Status.NA, "no tests/")
    multi_assert = 0
    total = 0
    for py in tests.rglob("test_*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                total += 1
                assert_count = sum(
                    1 for n in ast.walk(node) if isinstance(n, ast.Assert)
                )
                if assert_count >= 4:
                    multi_assert += 1
    if total == 0:
        return finding("P10.5", Status.NA, "no test functions")
    ratio = multi_assert / total
    if ratio < 0.1:
        return finding(
            "P10.5",
            Status.PASS,
            f"{multi_assert}/{total} tests with ≥4 assertions ({ratio:.0%})",
        )
    return finding(
        "P10.5",
        Status.WARN,
        f"{multi_assert}/{total} tests have ≥4 assertions — possible 3As violation",
    )
