"""CLI entry point for the architecture knowledge runner.

Two modes:
- ``--emit``: regenerate everything to ``docs/arch/generated/`` and update
  ``.meta.json``.
- ``--check``: regenerate to a tmpdir, diff against the committed
  ``docs/arch/generated/``, exit 1 if any artifact is stale.

Both modes share the same ``_compute_artifacts()`` core. The runner replaces
the ``{{ARCH_FOOTER}}`` sentinel with a stable ``<!-- arch:generated -->``
HTML comment so the body of every emitted file is byte-stable across
branches.

The committed ``.meta.json`` is a DETERMINISTIC content digest: every value
derives from artifact CONTENT, never from git HEAD or the wall-clock, so two
emits of identical source produce a byte-identical ``.meta.json``. That is
what lets ``DiagramLoop``'s no-diff gate fire when the architecture is
unchanged instead of opening a churn PR every interval. The volatile live
stamp (commit SHA + UTC timestamp) that drives the freshness badge lives in a
gitignored ``docs/arch/.meta.local.json`` sidecar — never committed, so it
cannot cause a diff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from adr_index import scan_adr_directory
from arch._functional_areas_schema import load_functional_areas
from arch._models import CommitInfo, TraceCommitInfo
from arch.extractors.adr_xref import extract_adr_refs
from arch.extractors.events import extract_event_topology
from arch.extractors.labels import extract_labels
from arch.extractors.loops import extract_loops
from arch.extractors.mockworld import extract_mockworld_map
from arch.extractors.modules import extract_module_graph
from arch.extractors.ports import extract_ports
from arch.generators.adr_assertion_density_report import (
    render_adr_assertion_density,
)
from arch.generators.adr_conformance import render_adr_conformance
from arch.generators.adr_cross_reference import render_adr_cross_reference
from arch.generators.adr_enforcement import render_adr_enforcement
from arch.generators.adr_falsifiability_report import render_adr_falsifiability
from arch.generators.ai_system_inventory import render_ai_system_inventory
from arch.generators.changelog import render_changelog
from arch.generators.coverage_matrix import render_coverage_matrix
from arch.generators.event_bus import render_event_bus
from arch.generators.functional_areas import render_functional_areas
from arch.generators.gauntlet_calibration import render_gauntlet_calibration
from arch.generators.label_state import render_label_state
from arch.generators.loop_registry import render_loop_registry
from arch.generators.mockworld_map import render_mockworld_map
from arch.generators.module_graph import render_module_graph
from arch.generators.port_map import render_port_map
from arch.generators.ports_and_loops_standard import (
    render_blocks as render_ports_and_loops_blocks,
)
from arch.generators.traceability_matrix import (
    collect_trace_commits,
    render_traceability_matrix,
)
from arch.generators.vitals_methodology_report import render_vitals_methodology
from disturbance.detectors.traceability import sync_traceability_baseline

_ARTIFACT_FILES = [
    "loops.md",
    "ports.md",
    "labels.md",
    "modules.md",
    "events.md",
    "adr_xref.md",
    "mockworld.md",
    "changelog.md",
    "functional_areas.md",
    "coverage_matrix.md",
    "ubiquitous-language.md",
    "ubiquitous-language-context-map.md",
    "adr-conformance.md",
    "adr-enforcement.md",
    "adr-assertion-density.md",
    "adr-falsifiability.md",
    "vitals-methodology.md",
    "ai_system_inventory.md",
    "traceability_matrix.md",
    "gauntlet-calibration.md",
]


def _run(cmd: list[str], cwd: Path) -> str:
    # Timeout guards against thread-pool exhaustion when ``emit`` is
    # called from ``DiagramLoop._regen_pr``'s generate callback via
    # ``asyncio.to_thread``. Same deadlock class as PR #8454.
    # 60s covers the heaviest call here (``git log --since=90.days.ago``
    # with several pathspecs).
    try:
        res = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=60
        )
    except subprocess.TimeoutExpired:
        return ""
    return res.stdout


def _commit_sha(repo_root: Path) -> str:
    sha = _run(["git", "rev-parse", "HEAD"], repo_root).strip()
    return sha or "unknown"


def _git_log_changelog(repo_root: Path) -> list[CommitInfo]:
    pathspecs = ["docs/arch/", "docs/adr/", "docs/wiki/", "src/arch/", "mkdocs.yml"]
    fmt = "%H%x09%cs%x09%s"
    raw = _run(
        [
            "git",
            "log",
            "--since=90.days.ago",
            f"--pretty=format:{fmt}",
            "--",
            *pathspecs,
        ],
        repo_root,
    )
    out: list[CommitInfo] = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        sha, iso_date, subject = parts
        pr_num: int | None = None
        if subject.endswith(")") and "(#" in subject:
            try:
                pr_num = int(subject.rsplit("(#", 1)[-1].rstrip(")"))
            except ValueError:
                pr_num = None
        out.append(
            CommitInfo(sha=sha, iso_date=iso_date, subject=subject, pr_number=pr_num)
        )
    return out


def _git_log_traceability(repo_root: Path) -> list[TraceCommitInfo]:
    """Collect the traceability population: recent PR-squash-merge commits.

    Delegates to ``collect_trace_commits`` so the generator, the ratchet
    baseline sync, and the ``TraceabilityDetector``'s marker verification
    all compute the fraction through ONE code path (CH-5 convergence review
    finding 3). Branch work-in-progress commits never match the ``(#NNNN)``
    suffix, so regenerating on a PR branch yields the same population as
    its base — keeping the drift check stable while a PR is open.
    Unavailable history renders as an empty population (matching the
    previous stdout-swallowing behavior); the detector-side regression
    check is what turns that into a loud signal.
    """
    return collect_trace_commits(repo_root) or []


def _compute_artifacts(repo_root: Path) -> dict[str, str]:
    """Run all extractors and generators; return {filename: markdown}."""
    src_dir = repo_root / "src"
    fakes_dir = repo_root / "src/mockworld/fakes"
    scenarios_dir = repo_root / "tests/scenarios"
    adr_dir = repo_root / "docs/adr"
    fa_path = repo_root / "docs/arch/functional_areas.yml"

    loops = extract_loops(src_dir)
    ports = extract_ports(src_dir=src_dir, fakes_dir=fakes_dir)
    adrs = scan_adr_directory(adr_dir)

    artifacts = {
        "loops.md": render_loop_registry(loops),
        "ports.md": render_port_map(ports),
        "labels.md": render_label_state(extract_labels(src_dir)),
        "modules.md": render_module_graph(extract_module_graph(src_dir)),
        "events.md": render_event_bus(extract_event_topology(src_dir)),
        "adr_xref.md": render_adr_cross_reference(extract_adr_refs(adr_dir), adrs),
        "mockworld.md": render_mockworld_map(
            extract_mockworld_map(fakes_dir=fakes_dir, scenarios_dir=scenarios_dir)
        ),
        "changelog.md": render_changelog(_git_log_changelog(repo_root)),
        "coverage_matrix.md": render_coverage_matrix(loops, ports, repo_root=repo_root),
        "adr-conformance.md": render_adr_conformance(adrs),
        "adr-enforcement.md": render_adr_enforcement(adrs, repo_root=repo_root),
        "adr-assertion-density.md": render_adr_assertion_density(adrs),
        "adr-falsifiability.md": render_adr_falsifiability(adrs, repo_root=repo_root),
        "vitals-methodology.md": render_vitals_methodology(),
        "ai_system_inventory.md": render_ai_system_inventory(
            loops, repo_root=repo_root
        ),
        "traceability_matrix.md": render_traceability_matrix(
            _git_log_traceability(repo_root), repo_root=repo_root
        ),
        # Deterministic instrument-spec version (#10371): live values render on
        # the dashboard panel from the runtime ledger, never baked into the
        # committed arch artifact (would drift against a populated data_root).
        "gauntlet-calibration.md": render_gauntlet_calibration(None),
    }
    if fa_path.exists():
        fa = load_functional_areas(fa_path)
        artifacts["functional_areas.md"] = render_functional_areas(
            fa, loops=loops, ports=ports
        )
    else:
        # Plan A → Plan B transition state: emit explicit placeholder so the
        # runner emits 9 artifacts even if the YAML hasn't landed in this
        # branch yet.
        artifacts["functional_areas.md"] = (
            "# Functional Area Map\n\n"
            "_(awaiting docs/arch/functional_areas.yml — Plan B Task 4)_\n\n{{ARCH_FOOTER}}\n"
        )

    # Ubiquitous-language views are generated by ubiquitous_language.py
    # (not by arch.runner), but they live in docs/arch/generated/ and must
    # be kept in sync with docs/wiki/terms/. Including them in _compute_artifacts
    # lets arch.runner --check catch stale glossary views alongside the other
    # architecture artifacts.
    terms_dir = repo_root / "docs" / "wiki" / "terms"
    if terms_dir.is_dir():
        from ubiquitous_language import (  # noqa: PLC0415
            TermStore,
            render_context_map,
            render_glossary,
        )

        terms = TermStore(terms_dir).list()
        artifacts["ubiquitous-language.md"] = render_glossary(terms)
        artifacts["ubiquitous-language-context-map.md"] = render_context_map(terms)
    else:
        artifacts["ubiquitous-language.md"] = (
            "# Ubiquitous Language\n\n"
            "_(awaiting docs/wiki/terms/ — ADR-0053)_\n\n{{ARCH_FOOTER}}\n"
        )
        artifacts["ubiquitous-language-context-map.md"] = (
            "# Ubiquitous Language — Context Map\n\n"
            "_(awaiting docs/wiki/terms/ — ADR-0053)_\n\n{{ARCH_FOOTER}}\n"
        )

    return artifacts


# Committed metadata file (deterministic content digest) and its gitignored
# volatile sidecar (wall-clock + HEAD sha, for the live freshness badge).
_META_NAME = ".meta.json"
_META_LOCAL_NAME = ".meta.local.json"


def _sha256(text: str) -> str:
    """Hex SHA-256 of a UTF-8 string — the content digest primitive."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stamp_footer(body: str) -> str:
    """Replace {{ARCH_FOOTER}} with a stable, branch-agnostic placeholder.

    The committed artifact body carries NO sha and NO timestamp — only a
    ``<!-- arch:generated -->`` HTML comment — so two emits of the same source
    produce byte-identical bodies across branches, eliminating an entire class
    of footer-only merge conflict (the MergeStateWatcher recovery cost). The
    content digest lives in the committed ``.meta.json``; the volatile stamp
    (sha, timestamp, badge) lives in the gitignored ``.meta.local.json``
    sidecar. The MkDocs site re-emits fresh artifacts on every Pages deploy and
    reads the live stamp from that sidecar, so readers still see current data.
    """
    return body.replace("{{ARCH_FOOTER}}", "<!-- arch:generated -->")


def emit(*, repo_root: Path, out_dir: Path) -> None:
    repo_root = Path(repo_root).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts = _compute_artifacts(repo_root)
    per_artifact_sha: dict[str, str] = {}
    for name, body in artifacts.items():
        stamped = _stamp_footer(body)
        (out_dir / name).write_text(stamped)
        per_artifact_sha[name] = _sha256(stamped)

    # Committed ``.meta.json`` is DETERMINISTIC: every value derives from
    # artifact CONTENT (not git HEAD, not the wall-clock), so identical source →
    # byte-identical ``.meta.json``. This is the flux-source fix — two
    # consecutive regens of unchanged architecture produce zero diff, so
    # DiagramLoop stops opening a churn PR every interval. Keys are sorted so
    # dict-insertion order can never introduce a diff.
    #
    # ``_DRIFT_EXEMPT`` artifacts are EXCLUDED from the digest. They derive from
    # a moving ``git log`` window, not from source, so their content is a
    # function of the branch's commit graph — two branches with byte-identical
    # architecture still produce different bytes for them. Hashing them broke
    # the "identical source -> byte-identical .meta.json" contract stated above
    # and made ``.meta.json`` conflict on essentially every rebase and staging
    # advance. That conflict needed the custom ``merge=arch-meta`` driver, which
    # ``.gitattributes`` names but which only exists where ``make ensure-hooks``
    # has run -- never in a fresh clone, a CI checkout, or GitHub's server-side
    # merge, so the conflict returned exactly where it was least convenient.
    # Excluding them makes ``.meta.json`` branch-stable by construction: a
    # conflict in it now means the architecture genuinely diverged.
    digested = {n: v for n, v in per_artifact_sha.items() if n not in _DRIFT_EXEMPT}
    overall_sha = _sha256("".join(digested[n] for n in sorted(digested)))
    meta = {
        "content_sha": overall_sha,
        "artifacts": {n: {"content_sha": digested[n]} for n in sorted(digested)},
    }
    (out_dir.parent / _META_NAME).write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n"
    )

    # Volatile provenance → gitignored sidecar. Preserves the live freshness
    # signal (regenerated_at + HEAD sha, consumed by arch.freshness.compute_badge
    # / the MkDocs site) WITHOUT committing a churning file. Never staged by any
    # caller, so it cannot cause a diff or a merge conflict.
    sha = _commit_sha(repo_root)
    local_meta = {
        "regenerated_at": datetime.now(UTC).isoformat(),
        "commit_sha": sha,
        "content_sha": overall_sha,
        "artifacts": {n: {"source_sha": sha} for n in sorted(per_artifact_sha)},
    }
    (out_dir.parent / _META_LOCAL_NAME).write_text(
        json.dumps(local_meta, indent=2) + "\n"
    )


def _strip_footer(text: str) -> str:
    """Remove the stable `<!-- arch:generated -->` placeholder line for diffs.

    The footer is now a branch-agnostic HTML comment rather than a live
    SHA+timestamp line, so `check()` strips it before diffing to keep the
    no-sha contract: two emits of the same source must compare equal.
    """
    lines = text.splitlines()
    out = [line for line in lines if "<!-- arch:generated -->" not in line]
    return "\n".join(out)


# Artifacts inherently time-varying; not subject to drift detection.
# They still emit fresh content every run.
# - changelog.md: derives from `git log` output; changes with every commit.
# - traceability_matrix.md: same moving `git log` window instability as
#   changelog.md. In CI the drift check regenerates from the PR *merge
#   commit*, so any squash-merge landing on the base branch between the
#   author's regen and the CI run shifts the commit window — once the
#   untraced percentage is below 100 that is a deterministic drift failure
#   on unrelated PRs. The load-bearing staleness/forgery invariant is
#   enforced by the traceability disturbance ratchet instead: the baseline
#   (disturbance/baselines/traceability.yaml) only lowers from a fraction
#   RECOMPUTED from git history, and the TraceabilityDetector flags a
#   committed marker that deviates from that recompute (the marker itself
#   is display-only — CH-5 convergence review finding 3).
_DRIFT_EXEMPT = {"changelog.md", "traceability_matrix.md"}


def check(*, repo_root: Path, generated_dir: Path) -> int:
    """Regenerate to a tmpdir, diff against `generated_dir`, return rc 0/1.

    `changelog.md` and `traceability_matrix.md` are exempt from drift
    detection (see `_DRIFT_EXEMPT`): both derive from a moving `git log`
    window, so regenerating from CI's merge commit legitimately differs
    from the committed artifact.
    """
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "generated"
        emit(repo_root=repo_root, out_dir=tmp)
        for name in _ARTIFACT_FILES:
            if name in _DRIFT_EXEMPT:
                continue
            actual = generated_dir / name
            expected = tmp / name
            if not actual.exists():
                print(f"[arch-check] missing: {name}")
                return 1
            # Compare body sans footer (footer has timestamps that change every run)
            a = _strip_footer(actual.read_text())
            b = _strip_footer(expected.read_text())
            if a != b:
                print(f"[arch-check] drift in {name}")
                # Show a unified-diff snippet so CI logs reveal exactly what differs
                import difflib

                diff_lines = list(
                    difflib.unified_diff(
                        a.splitlines(keepends=False),
                        b.splitlines(keepends=False),
                        fromfile=f"committed/{name}",
                        tofile=f"regenerated/{name}",
                        lineterm="",
                        n=3,
                    )
                )
                # Cap to first 80 diff lines to avoid log floods
                for line in diff_lines[:80]:
                    print(line)
                if len(diff_lines) > 80:
                    print(f"... ({len(diff_lines) - 80} more diff lines truncated)")
                # When the drift is in modules.md, dump the inventory of .py
                # files under src/ that import `state` — the drift is +1 weight
                # on the src→src.state edge and we need to know which extra
                # file CI sees.
                if name == "modules.md":
                    src_dir = Path(repo_root) / "src"
                    print("[arch-check-debug] flat src/*.py files importing state:")
                    importers = []
                    for py in sorted(src_dir.glob("*.py")):
                        try:
                            text = py.read_text()
                        except OSError:
                            continue
                        if (
                            "from state " in text
                            or "\nimport state\n" in text
                            or text.startswith("import state\n")
                        ):
                            importers.append(py.name)
                    print(f"[arch-check-debug]   total: {len(importers)}")
                    for n in importers:
                        print(f"[arch-check-debug]   {n}")
                return 1
    return 0


# ---------------------------------------------------------------------------
# Inline generated blocks
#
# Some generated content belongs inside an otherwise hand-written document
# rather than in its own file under ``docs/arch/generated/``. A standard's
# registry table is the case: the contract around it is prose a person writes,
# the inventory inside it is an extract nobody should be typing. The block
# markers are the ``scripts/gen_gates.py`` pattern
# (``docs/standards/branch_protection/README.md``), joined here to the arch
# runner so ``make arch-regen`` fixes the drift ``make arch-check`` reports —
# one loop rather than a second command to remember.
#
# These are written by ``--emit`` and diffed by ``--check``. They deliberately
# live outside ``emit()``: ``check()`` calls ``emit()`` against a tmpdir, and
# an in-place rewrite of a repo file has no tmpdir equivalent.
# ---------------------------------------------------------------------------

_PORTS_AND_LOOPS_STANDARD = "docs/standards/ports-and-loops/README.md"


def _compute_inline_blocks(
    repo_root: Path,
) -> dict[str, dict[tuple[str, str], str]]:
    """``{repo-relative file: {(begin, end): rendered body}}``."""
    src_dir = repo_root / "src"
    loops = extract_loops(src_dir)
    ports = extract_ports(src_dir=src_dir, fakes_dir=repo_root / "src/mockworld/fakes")
    return {
        _PORTS_AND_LOOPS_STANDARD: render_ports_and_loops_blocks(
            loops, ports, repo_root=repo_root
        ),
    }


def substitute_blocks(
    rel: str, current: str, blocks: dict[tuple[str, str], str]
) -> str:
    """Return ``current`` with each delimited region replaced by its body."""
    for (begin, end), body in blocks.items():
        if begin not in current or end not in current:
            raise ValueError(
                f"{rel} is missing the {begin} … {end} block; the generator "
                "has nowhere to write"
            )
        start = current.index(begin)
        stop = current.index(end) + len(end)
        current = current[:start] + f"{begin}\n{body}\n{end}" + current[stop:]
    return current


def emit_inline_blocks(*, repo_root: Path) -> list[str]:
    """Rewrite every inline generated block in place; return what changed.

    A host document that is absent is skipped rather than fatal: ``--emit``
    runs against synthetic trees in tests and against partially-stamped repos,
    where "that document does not exist here" is a legitimate answer. The
    asymmetry is deliberate — ``check_inline_blocks`` treats the same absence
    as drift, so a document that goes missing in a repo that should have one
    reddens rather than quietly stopping being generated.
    """
    repo_root = Path(repo_root).resolve()
    written: list[str] = []
    for rel, blocks in _compute_inline_blocks(repo_root).items():
        path = repo_root / rel
        if not path.exists():
            continue
        current = path.read_text()
        updated = substitute_blocks(rel, current, blocks)
        if updated != current:
            path.write_text(updated)
            written.append(rel)
    return written


def check_inline_blocks(*, repo_root: Path) -> int:
    """Diff every inline generated block against source; return rc 0/1.

    A missing host document is drift, not a skip. Fail-closed here is the
    whole point: the alternative is a staleness gate that stops having a
    subject the moment somebody deletes the file it was watching.
    """
    repo_root = Path(repo_root).resolve()
    rc = 0
    for rel, blocks in _compute_inline_blocks(repo_root).items():
        path = repo_root / rel
        if not path.exists():
            print(f"[arch-check] missing: {rel} (carries generated blocks)")
            rc = 1
            continue
        current = path.read_text()
        expected = substitute_blocks(rel, current, blocks)
        if expected == current:
            continue
        rc = 1
        print(f"[arch-check] drift in {rel}; run `make arch-regen`")
        import difflib

        diff_lines = list(
            difflib.unified_diff(
                current.splitlines(),
                expected.splitlines(),
                fromfile=f"committed/{rel}",
                tofile=f"regenerated/{rel}",
                lineterm="",
                n=1,
            )
        )
        for line in diff_lines[:80]:
            print(line)
        if len(diff_lines) > 80:
            print(f"... ({len(diff_lines) - 80} more diff lines truncated)")
    return rc


def _main() -> int:
    p = argparse.ArgumentParser(
        prog="arch.runner",
        description="Regenerate architecture knowledge artifacts.",
    )
    p.add_argument("--emit", action="store_true", help="Write to docs/arch/generated/.")
    p.add_argument(
        "--check",
        action="store_true",
        help="Dry-run; exit 1 if generated/ is stale relative to source.",
    )
    p.add_argument("--repo-root", default=".", type=Path)
    args = p.parse_args()

    repo_root = args.repo_root.resolve()
    generated = repo_root / "docs/arch/generated"
    if args.emit:
        emit(repo_root=repo_root, out_dir=generated)
        for rel in emit_inline_blocks(repo_root=repo_root):
            print(f"[arch-regen] refreshed generated block(s) in {rel}")
        # Keep the traceability ratchet baseline in lockstep with the fresh
        # matrix (prune-only). Lives here rather than in emit() so check()'s
        # tmpdir regeneration stays a pure read of the repo.
        if sync_traceability_baseline(repo_root):
            print("[arch-regen] pruned disturbance/baselines/traceability.yaml")
        return 0
    if args.check:
        # Both halves run: a stale artifact and a stale inline block are
        # separate edits with separate fixes, and CI should report both.
        artifacts_rc = check(repo_root=repo_root, generated_dir=generated)
        blocks_rc = check_inline_blocks(repo_root=repo_root)
        return max(artifacts_rc, blocks_rc)
    p.error("specify --emit or --check")
    return 2


if __name__ == "__main__":
    sys.exit(_main())
