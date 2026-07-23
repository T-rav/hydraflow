"""Pure change-spread sensor (#10105): files-touched + modules-crossed per change.

`compute` mirrors the purity contract of
`disturbance.detectors.base.ViolationDetector.detect` — reads only, no side
effects — but is change-scoped: it takes an explicit list of changed file
paths (NOT a repo root) plus the arch module graph, so it composes with any
diff source and is unit-testable with synthetic inputs, no git dependency
required. `changed_files_for_range` is a thin git-diff adapter that wraps it
for real commit ranges; `compute` itself never shells out.

Do NOT wire this into `disturbance.registry.DIMENSIONS` — the parent epic
(#10104) explains why: `ViolationDetector.detect(repo_root)` is a per-file
static snapshot of the repo as it is now; change-spread needs the diff as
input, which that protocol structurally can't express. The caretaker loop
and issue-filing actuator that consume `SpreadFinding` are sibling issues
(#10106/#10107), not this one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from arch._models import ModuleGraph
from arch.extractors.modules import package_of
from erosion.models import SpreadFinding

_GIT_TIMEOUT_S = 60
_SRC_DIRNAME = "src"

# Used only for lexical path arithmetic inside `package_of`
# (`Path.relative_to` / `Path.with_suffix`, both pure — no filesystem I/O),
# so synthetic (non-existent) changed-file paths behave identically to real
# ones in unit tests.
_FAKE_REPO_ROOT = Path("/repo")


def _module_for_file(rel_path: str, known_modules: set[str]) -> str | None:
    """Map one repo-root-relative changed-file path to its dotted module name.

    Reuses `arch.extractors.modules.package_of` — the SAME file→module
    mapping `extract_module_graph` uses to build the module graph itself —
    rather than hand-rolling a second mapping (see module docstring).
    Returns ``None`` when the file isn't under `src/`, or its derived
    package isn't a node the current module graph actually knows about
    (e.g. a deleted file, or a directory that never contained a scanned
    `.py`).
    """
    parts = PurePosixPath(rel_path).parts
    if not parts or parts[0] != _SRC_DIRNAME:
        return None
    candidate = package_of(_FAKE_REPO_ROOT / rel_path, _FAKE_REPO_ROOT / _SRC_DIRNAME)
    return candidate if candidate in known_modules else None


def compute(changed_files: list[str], module_graph: ModuleGraph) -> SpreadFinding:
    """Pure: files-touched + modules-crossed for one change. No I/O.

    *changed_files* are repo-root-relative paths (as `git diff --name-only`
    emits); *module_graph* is an `arch._models.ModuleGraph` (e.g. from
    `arch.extractors.modules.extract_module_graph`) — its node names are
    the set of modules a file can validly map to. Defensively deduplicates
    *changed_files* (a real git diff never repeats a path, but synthetic
    callers might).
    """
    known_modules = {node.name for node in module_graph.nodes}
    unique_files = list(dict.fromkeys(changed_files))
    modules: set[str] = set()
    unmapped: list[str] = []
    for f in unique_files:
        module = _module_for_file(f, known_modules)
        if module is None:
            unmapped.append(f)
        else:
            modules.add(module)
    return SpreadFinding(
        files_touched=len(unique_files),
        modules_crossed=len(modules),
        modules=tuple(sorted(modules)),
        unmapped_files=tuple(sorted(unmapped)),
    )


def changed_files_for_range(repo_root: Path, commit_range: str) -> list[str] | None:
    """Return changed file paths (repo-root-relative) for *commit_range*.

    Thin `git diff --name-only` wrapper — NOT part of the pure sensor;
    `compute` never calls this itself, and it has side effects (shells
    out) by design. Mirrors the sync-subprocess-with-timeout convention
    used by `arch.generators.traceability_matrix._run_git`. Returns
    ``None`` on any git failure (missing git, non-repo, bad range,
    timeout) so callers can distinguish "no changes" (``[]``) from
    "couldn't determine changes" (``None``).
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", commit_range],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
