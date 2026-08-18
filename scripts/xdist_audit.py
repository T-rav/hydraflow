"""xdist-isolation audit: find tests that fail under ``-n auto`` but pass serially.

A test that shares process-global state (a leaked module mock, an OTel provider,
a subprocess-group reap race) passes single-threaded but flakes under
cross-worker scheduling. The standard remediation is to move it into
``PYTEST_SERIAL_PATHS`` (the serial lane). Detecting *which* tests need that has
been a manual chore (issue #10141); this audit automates the detection half.

The signal cannot be mined from the normal CI JUnit, which is green by design
(``--reruns`` rescues transients; hard failures block the merge). So this runs a
dedicated two-phase probe:

1. Run the target suite **in parallel** (``-n auto``), no reruns, capturing raw
   failures.
2. Re-run *only* those failures **serially** (no xdist).
3. A test that failed in parallel but passes serially is xdist-unsafe: moving it
   to the serial lane would fix it.

Output is a small JSON (``xdist-audit.json``) consumed downstream by
``FlakeTrackerLoop`` (windowed so a one-off transient never triggers a
quarantine). The classify/parse core is pure and unit-tested; ``main`` only
orchestrates the two pytest subprocesses.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404  # invokes pytest with a fixed, non-shell argv
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_outcomes(xml_bytes: bytes) -> dict[str, str]:
    """Return ``{test_id: "pass"|"fail"}`` per testcase in a JUnit XML document.

    ``test_id`` is ``{classname}.{name}`` (matching ``FlakeTrackerLoop``'s
    ``parse_junit_xml``). A case is ``fail`` if it has any ``<failure>`` or
    ``<error>`` child; ``skipped`` counts as ``pass`` (a skip is not a flake).
    """
    outcomes: dict[str, str] = {}
    root = ET.fromstring(xml_bytes)  # nosec B314  # JUnit from our own CI run
    for case in root.iter("testcase"):
        cls = case.get("classname") or ""
        name = case.get("name") or ""
        test_id = f"{cls}.{name}".lstrip(".")
        failed = any(child.tag in ("failure", "error") for child in case)
        # A test id can appear more than once (rerun plugins emit repeats); once
        # it has failed anywhere, keep it failed.
        if outcomes.get(test_id) == "fail":
            continue
        outcomes[test_id] = "fail" if failed else "pass"
    return outcomes


def failed_ids(outcomes: dict[str, str]) -> list[str]:
    """Sorted test ids that failed."""
    return sorted(tid for tid, outcome in outcomes.items() if outcome == "fail")


def classify_xdist_unsafe(
    parallel: dict[str, str], serial: dict[str, str]
) -> list[str]:
    """Tests that failed in the parallel run but pass the serial recheck.

    Pure: the whole point is that quarantining these to the serial lane fixes
    them. A parallel failure with no serial verdict (recheck didn't cover it) is
    NOT classified — we only assert xdist-unsafe when serial evidence says pass.
    """
    return sorted(tid for tid in failed_ids(parallel) if serial.get(tid) == "pass")


def build_report(parallel: dict[str, str], serial: dict[str, str]) -> dict:
    """Assemble the JSON report payload (no timestamp — the caller stamps it)."""
    unsafe = classify_xdist_unsafe(parallel, serial)
    return {
        "xdist_unsafe": unsafe,
        "parallel_failures": failed_ids(parallel),
        "serial_rechecked": sorted(serial),
        "counts": {
            "parallel_total": len(parallel),
            "parallel_failures": len(failed_ids(parallel)),
            "xdist_unsafe": len(unsafe),
        },
    }


def render_summary(report: dict) -> str:
    """A GitHub step-summary (Markdown) so a human sees the verdict immediately."""
    unsafe = report["xdist_unsafe"]
    lines = ["## xdist-isolation audit", ""]
    if not unsafe:
        pf = report["counts"]["parallel_failures"]
        lines.append(
            f"No xdist-unsafe tests found "
            f"({pf} parallel failure(s), none passed the serial recheck)."
        )
        return "\n".join(lines) + "\n"
    lines += [
        f"**{len(unsafe)} test(s) fail under `-n auto` but pass serially** — "
        "candidates for `PYTEST_SERIAL_PATHS` quarantine:",
        "",
    ]
    lines += [f"- `{tid}`" for tid in unsafe]
    lines.append("")
    return "\n".join(lines) + "\n"


def _run_pytest(args: list[str]) -> None:
    """Run pytest, tolerating a non-zero exit (failures are the whole point)."""
    subprocess.run(  # nosec B603  # fixed argv, no shell
        [sys.executable, "-m", "pytest", *args],
        check=False,
    )


def _parallel_args(target: str, ignores: list[str], junit: Path) -> list[str]:
    args = [target]
    for ig in ignores:
        args.append(f"--ignore={ig}")
    args += [
        "-n",
        "auto",
        "--dist",
        "loadscope",
        "-p",
        "no:randomly",
        "-q",
        f"--junitxml={junit}",
    ]
    return args


def _serial_args(ids: list[str], junit: Path) -> list[str]:
    return [*ids, "-p", "no:xdist", "-p", "no:randomly", "-q", f"--junitxml={junit}"]


def run_audit(target: str, ignores: list[str], workdir: Path) -> dict:
    """Two-phase probe → report dict. Shells out to pytest twice."""
    parallel_xml = workdir / "parallel.xml"
    _run_pytest(_parallel_args(target, ignores, parallel_xml))
    parallel = (
        parse_outcomes(parallel_xml.read_bytes()) if parallel_xml.exists() else {}
    )

    failures = failed_ids(parallel)
    serial: dict[str, str] = {}
    if failures:
        serial_xml = workdir / "serial.xml"
        _run_pytest(_serial_args(failures, serial_xml))
        if serial_xml.exists():
            serial = parse_outcomes(serial_xml.read_bytes())
    return build_report(parallel, serial)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="xdist-isolation audit")
    parser.add_argument("--target", default="tests/")
    parser.add_argument("--ignore", action="append", default=[], dest="ignores")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    ns = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as td:
        report = run_audit(ns.target, ns.ignores, Path(td))

    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if ns.summary:
        ns.summary.write_text(render_summary(report), encoding="utf-8")
    print(render_summary(report))
    # Always exit 0: an xdist-unsafe finding is a report, not a CI failure — the
    # nightly job should stay green and let the downstream loop act on the JSON.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
