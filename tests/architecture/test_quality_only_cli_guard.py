"""Quality-only CLI guard (#9411) — the Quality-vs-CI-runner wedge class.

The GitHub **Quality** workflow runs on a runner image that ships ripgrep
(``rg``); the leaner **CI / Tests** runner does not. Code in ``src/`` that
shells out to a Quality-only CLI without a ``shutil.which(...)`` guard passes
local ``make quality`` and the Quality runner, then crashes only on the
CI/Tests runner — invisible until CI. #9403→#9404 was exactly this
(``FakeCoverageAuditorLoop._grep_scenario_for_helper`` shelled out to ``rg``
unguarded and blew up on the CI/Tests runner).

This guard turns the next one into a red unit test at PR time: it AST-scans
every ``src/`` module for subprocess call sites that invoke a Quality-only
CLI and asserts each one is protected by a nearby ``shutil.which("<tool>")``
guard (or sits in the grandfathered baseline). The baseline only shrinks
(ratchet, mirroring ``tests/test_disturbance_ratchet.py`` and
``tests/architecture/test_sandbox_seam_completeness.py``): a NEW unguarded
Quality-only-CLI shell-out reddens, and covering a grandfathered one requires
pruning its entry in the same change so the baseline stays honest.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from tests.architecture.quality_only_cli_scan import (
    QUALITY_ONLY_CLIS,
    ratchet_diff,
    scan_cli_sites,
    scan_source,
    signature_tool,
    unguarded_signatures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# The load-bearing real site: it exists as long as HydraFlow's fake-coverage
# auditor greps its scenario tree with ``rg``. Pinned by the anti-vacuity
# canary so a broken scan (scope regression, primitive-set typo) cannot pass
# every assertion here vacuously on an empty result.
_KNOWN_GUARDED_SITE = (
    "src/fake_coverage_auditor_loop.py::"
    "FakeCoverageAuditorLoop._grep_scenario_for_helper::rg"
)

# Grandfathered UNGUARDED Quality-only-CLI shell-outs, keyed ``{signature:
# count}`` (see quality_only_cli_scan.scan_cli_sites). EMPTY by design: the
# only real ``rg`` shell-out in ``src/`` is already guarded with
# ``shutil.which("rg")`` (#9404). The guard is preventive. DO NOT ADD
# ENTRIES: a new Quality-only-CLI shell-out must be guarded with
# ``shutil.which("<tool>")`` and a fallback, the way
# ``FakeCoverageAuditorLoop._grep_scenario_for_helper`` is. Remove entries as
# sites gain guards — the ratchet only shrinks.
GRANDFATHERED_UNGUARDED_BASELINE: dict[str, int] = {}


def test_quality_only_cli_set_is_curated() -> None:
    """The curated set is a small named constant, trivially extensible."""
    assert "rg" in QUALITY_ONLY_CLIS
    assert "ripgrep" in QUALITY_ONLY_CLIS


def test_scanner_flags_unguarded_command_list() -> None:
    """A ``rg`` command list with no ``shutil.which`` guard is unguarded."""
    source = dedent(
        """
        import subprocess

        def scan(pattern):
            return subprocess.run(["rg", "-n", pattern])
        """
    )
    sites = scan_source(source, "src/synthetic.py")
    sig = "src/synthetic.py::scan::rg"
    assert sig in sites
    assert sites[sig].guarded is False
    assert sig in unguarded_signatures(sites)


def test_scanner_flags_unguarded_direct_arg() -> None:
    """The direct-arg idiom (``run_subprocess_result("rg", ...)``) is caught."""
    source = dedent(
        """
        def scan(pattern):
            return run_subprocess_result("rg", "-l", pattern)
        """
    )
    sites = scan_source(source, "src/synthetic.py")
    sig = "src/synthetic.py::scan::rg"
    assert sig in sites
    assert sites[sig].guarded is False


def test_scanner_treats_which_guarded_site_as_guarded() -> None:
    """The same command list becomes guarded once ``shutil.which`` protects it."""
    source = dedent(
        """
        import shutil
        import subprocess

        def scan(pattern):
            if shutil.which("rg") is not None:
                return subprocess.run(["rg", "-n", pattern])
            return grep_fallback(pattern)
        """
    )
    sites = scan_source(source, "src/synthetic.py")
    sig = "src/synthetic.py::scan::rg"
    assert sig in sites
    assert sites[sig].guarded is True
    assert sig not in unguarded_signatures(sites)


def test_which_call_is_not_itself_a_site() -> None:
    """``shutil.which("rg")`` alone is a guard, not a shell-out site."""
    source = dedent(
        """
        import shutil

        def probe():
            return shutil.which("rg") is not None
        """
    )
    assert scan_source(source, "src/synthetic.py") == {}


def test_scan_finds_real_rg_site_and_marks_it_guarded() -> None:
    """Anti-vacuity canary on the live ``src/`` tree.

    The one real ``rg`` shell-out — ``FakeCoverageAuditorLoop.
    _grep_scenario_for_helper`` — must be detected AND classified as guarded
    (it wraps the ``rg`` command list in ``if shutil.which("rg") is not
    None:`` with a stdlib fallback). If the scan scope or primitive set
    regresses, this reddens instead of letting the ratchet pass vacuously.
    """
    sites = scan_cli_sites(REPO_ROOT)
    assert _KNOWN_GUARDED_SITE in sites, (
        "scanner no longer detects the known rg shell-out in "
        "fake_coverage_auditor_loop.py — scan scope or CLI set regressed"
    )
    assert sites[_KNOWN_GUARDED_SITE].guarded is True
    assert signature_tool(_KNOWN_GUARDED_SITE) == "rg"


def test_no_new_unguarded_quality_only_cli_shellouts() -> None:
    """The ratchet: no unguarded Quality-only-CLI shell-out beyond baseline."""
    unguarded = unguarded_signatures(scan_cli_sites(REPO_ROOT))
    new, _resolved = ratchet_diff(unguarded, GRANDFATHERED_UNGUARDED_BASELINE)
    assert not new, (
        f"Unguarded Quality-only-CLI shell-outs in src/ (beyond baseline): "
        f"{new}. The Quality runner has these CLIs (e.g. `rg`); the CI/Tests "
        "runner does not, so this crashes only on CI/Tests — invisible to "
        'local `make quality`. Guard the call with `shutil.which("<tool>")` '
        "and a fallback, the way "
        "FakeCoverageAuditorLoop._grep_scenario_for_helper does. Do NOT grow "
        "GRANDFATHERED_UNGUARDED_BASELINE — the ratchet only shrinks."
    )


def test_grandfathered_baseline_only_shrinks() -> None:
    """Covering a grandfathered site requires pruning its baseline entry."""
    unguarded = unguarded_signatures(scan_cli_sites(REPO_ROOT))
    _new, resolved = ratchet_diff(unguarded, GRANDFATHERED_UNGUARDED_BASELINE)
    assert not resolved, (
        f"Baseline lists unguarded shell-outs no longer present or now "
        f"guarded: {resolved}. Prune them from "
        "GRANDFATHERED_UNGUARDED_BASELINE in this change so the baseline "
        "stays honest."
    )
