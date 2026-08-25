"""CI workflow scaffolding for GitHub Actions.

Generates a `.github/workflows/quality.yml` workflow with stack-specific
lint/test/build-style checks for common ecosystems.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from polyglot_prep import (
    detect_language,  # noqa: F401 - re-export for compatibility tests
    detect_prep_stack,
)
from prep_ignore import PREP_IGNORED_DIRS


@dataclasses.dataclass
class CIScaffoldResult:
    """Result of CI workflow scaffolding."""

    created: bool
    skipped: bool
    skip_reason: str = ""
    language: str = ""
    workflow_path: str = ""


def has_quality_workflow(repo_root: Path) -> tuple[bool, str]:
    """Check whether an existing quality workflow already exists.

    Scans `.github/workflows/*.yml` and `*.yaml` for either:
    - `prep-managed: quality-workflow`
    - legacy `make quality`
    """
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return False, ""

    for pattern in ("*.yml", "*.yaml"):
        for wf_file in sorted(workflows_dir.glob(pattern)):
            try:
                contents = wf_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if (
                "prep-managed: quality-workflow" in contents
                or "make quality" in contents
            ):
                return True, wf_file.name

    return False, ""


_IGNORED_DIRS_LITERAL = ", ".join(f'"{name}"' for name in sorted(PREP_IGNORED_DIRS))

#: Job key of the aggregator that fans in every dynamic `quality` matrix leg.
QUALITY_GATE_JOB = "quality-gate"

#: The ONE check context a stamped repo's branch protection may require for
#: quality (#11715). Never require the bare `quality` job (matrix-expanded, so
#: that context is never reported) nor its legs (discovered at runtime, so they
#: are unknowable at stamp time). Consumers -- notably the kernel writer's
#: generated `scripts/setup_branch_protection.py` -- import this name rather
#: than restating the string, so the workflow and the protection payload cannot
#: drift apart.
QUALITY_GATE_CONTEXT = "Quality Gate"

_UNIVERSAL_WORKFLOW_TEMPLATE = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: __TRIGGER_BRANCHES__
  push:
    branches: __TRIGGER_BRANCHES__

jobs:
  discover-projects:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.scan.outputs.matrix }}
    steps:
      - uses: actions/checkout@v4
      - name: Discover project paths
        id: scan
        shell: bash
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          root = Path(".")
          ignored = {
              __PREP_IGNORED_DIRS__
          }
          markers = {
              "Makefile", "makefile", "GNUmakefile",
              "pyproject.toml", "requirements.txt", "setup.py",
              "package.json", "go.mod", "Cargo.toml", "pom.xml",
              "build.gradle", "build.gradle.kts", "Gemfile",
              "CMakeLists.txt"
          }

          paths = set()
          submodule_roots = set()
          gitmodules = root / ".gitmodules"
          if gitmodules.is_file():
              for line in gitmodules.read_text(encoding="utf-8").splitlines():
                  line = line.strip()
                  if not line.startswith("path ="):
                      continue
                  rel = line.split("=", 1)[1].strip()
                  if rel:
                      submodule_roots.add((root / rel).resolve())

          for path in root.rglob("*"):
              if any(part in ignored for part in path.parts):
                  continue
              resolved = path.resolve()
              if any(sm == resolved or sm in resolved.parents for sm in submodule_roots):
                  continue
              if not path.is_file():
                  continue
              if (
                  path.name in markers
                  or path.name.endswith(".sln")
                  or path.name.endswith(".csproj")
              ):
                  rel = path.parent.relative_to(root)
                  paths.add(str(rel) if str(rel) else ".")

          items = [{"project_dir": p} for p in sorted(paths)]
          payload = json.dumps({"include": items})
          with open(".github_output", "w", encoding="utf-8") as f:
              f.write(f"matrix={payload}\\n")
          print(f"matrix={payload}")
          PY
          cat .github_output >> "$GITHUB_OUTPUT"

  quality:
    runs-on: ubuntu-latest
    needs: discover-projects
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.discover-projects.outputs.matrix) }}
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        if: ${{ hashFiles(format('{0}/pyproject.toml', matrix.project_dir), format('{0}/requirements.txt', matrix.project_dir), format('{0}/setup.py', matrix.project_dir)) != '' }}
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Set up Node
        if: ${{ hashFiles(format('{0}/package.json', matrix.project_dir)) != '' }}
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Set up Java
        if: ${{ hashFiles(format('{0}/pom.xml', matrix.project_dir), format('{0}/build.gradle', matrix.project_dir), format('{0}/build.gradle.kts', matrix.project_dir)) != '' }}
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '21'
      - name: Set up Ruby
        if: ${{ hashFiles(format('{0}/Gemfile', matrix.project_dir)) != '' }}
        uses: ruby/setup-ruby@v1
      - name: Set up .NET
        if: ${{ hashFiles(format('{0}/*.sln', matrix.project_dir), format('{0}/*.csproj', matrix.project_dir)) != '' }}
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'
      - name: Set up Go
        if: ${{ hashFiles(format('{0}/go.mod', matrix.project_dir)) != '' }}
        uses: actions/setup-go@v5
        with:
          go-version: '1.22'
      - name: Quality Lite
        shell: bash
        run: |
          set -euo pipefail
          cd "${{ matrix.project_dir }}"
          if [ -f Makefile ] || [ -f makefile ] || [ -f GNUmakefile ]; then
            make quality-lite
            exit 0
          fi
          echo "Missing Makefile in ${{ matrix.project_dir }}. Run 'make prep' to scaffold make targets." >&2
          exit 1
      - name: Quality Full
        shell: bash
        run: |
          set -euo pipefail
          cd "${{ matrix.project_dir }}"
          if [ -f Makefile ] || [ -f makefile ] || [ -f GNUmakefile ]; then
            make quality
            exit 0
          fi
          echo "Missing Makefile in ${{ matrix.project_dir }}. Run 'make prep' to scaffold make targets." >&2
          exit 1
      - name: Smoke
        shell: bash
        run: |
          set -euo pipefail
          cd "${{ matrix.project_dir }}"
          if [ -f Makefile ] || [ -f makefile ] || [ -f GNUmakefile ]; then
            if make -n smoke >/dev/null 2>&1; then
              make smoke
            else
              echo "Smoke target not found in ${{ matrix.project_dir }}; skipping."
            fi
            exit 0
          fi
          echo "Missing Makefile in ${{ matrix.project_dir }}. Run 'make prep' to scaffold make targets." >&2
          exit 1

  # The single stable check context for branch protection (#11715).
  #
  # `quality` is matrix-expanded from a matrix DISCOVERED AT RUNTIME, so GitHub
  # reports its check runs as `quality (<project_dir>)` and never a bare
  # `quality`. A stamped repo therefore cannot enumerate its own required
  # contexts at stamp time: requiring `quality` blocks every PR forever
  # ("expected -- waiting for status"), and requiring the legs is impossible
  # because the leg set is not known until discover-projects runs.
  #
  # This job is the aggregator (the shape HydraFlow's own `ci.yml` uses for
  # `CI Gate`): ONE fixed context that summarises however many legs ran.
  __QUALITY_GATE_JOB__:
    name: __QUALITY_GATE_CONTEXT__
    runs-on: ubuntu-latest
    needs: [discover-projects, quality]
    # `if: always()` is LOAD-BEARING. Without it, a failed or cancelled `quality`
    # SKIPS this job, so the one required context never reports a verdict of its
    # own -- and what GitHub then does with it is exactly the ambiguity that
    # produced this bug: a job-level skip is reported as Success (green over a
    # red matrix), while a never-expanded matrix stays "expected" (blocked
    # forever). Both are failures of the gate as a gate. `always()` removes the
    # question: the job runs on every outcome and reports a real pass/fail.
    if: always()
    steps:
      - name: Require every quality matrix leg to have succeeded
        env:
          RESULTS: ${{ join(needs.*.result, ' ') }}
        shell: bash
        run: |
          set -uo pipefail
          echo "Upstream job results: $RESULTS"
          if [ -z "${RESULTS// /}" ]; then
            echo "::error::No upstream results -- the quality matrix never ran."
            exit 1
          fi
          for r in $RESULTS; do
            # Anything other than success fails the gate, `skipped` included:
            # `quality` is skipped when discover-projects fails or emits an
            # empty matrix, and passing that through would be a silent green.
            if [ "$r" != "success" ]; then
              echo "::error::A required quality job did not succeed (result=$r)."
              exit 1
            fi
          done
          echo "All quality matrix legs succeeded."
"""

_UNIVERSAL_WORKFLOW = (
    _UNIVERSAL_WORKFLOW_TEMPLATE.replace("__PREP_IGNORED_DIRS__", _IGNORED_DIRS_LITERAL)
    .replace("__QUALITY_GATE_JOB__", QUALITY_GATE_JOB)
    .replace("__QUALITY_GATE_CONTEXT__", QUALITY_GATE_CONTEXT)
)

_WORKFLOW_TEMPLATES: dict[str, str] = {
    "python": _UNIVERSAL_WORKFLOW,
    "javascript": _UNIVERSAL_WORKFLOW,
    "node": _UNIVERSAL_WORKFLOW,
    "mixed": _UNIVERSAL_WORKFLOW,
    "java": _UNIVERSAL_WORKFLOW,
    "ruby": _UNIVERSAL_WORKFLOW,
    "rails": _UNIVERSAL_WORKFLOW,
    "csharp": _UNIVERSAL_WORKFLOW,
    "go": _UNIVERSAL_WORKFLOW,
    "rust": _UNIVERSAL_WORKFLOW,
    "cpp": _UNIVERSAL_WORKFLOW,
    "unknown": _UNIVERSAL_WORKFLOW,
}


#: Default protected branch the workflow triggers on. Callers that protect more
#: than one branch (the two-tier main/staging model, ADR-0042) must pass them
#: all — see ``generate_workflow``.
DEFAULT_TRIGGER_BRANCHES: tuple[str, ...] = ("main",)


def generate_workflow(
    language: str, *, branches: Sequence[str] = DEFAULT_TRIGGER_BRANCHES
) -> str:
    """Return the GitHub Actions workflow YAML for the given language.

    ``branches`` are the base branches the workflow triggers on. It MUST cover
    every branch whose protection requires a context this workflow produces:
    ``on.pull_request.branches`` filters by BASE branch, so a PR into a branch
    the workflow does not trigger on never reports that context, and the PR sits
    at "expected -- waiting for status" forever. That is the same never-reported
    hard block as requiring the bare matrix-expanded `quality` job (#11715), and
    it bites the stamped kernel specifically: its own CLAUDE.md tells agents to
    target `staging`, and its protection script protects `staging` too.
    """
    assert branches, "generate_workflow needs at least one trigger branch"
    template = _WORKFLOW_TEMPLATES.get(language, _UNIVERSAL_WORKFLOW)
    return template.replace(
        "__TRIGGER_BRANCHES__", "[" + ", ".join(dict.fromkeys(branches)) + "]"
    )


_WORKFLOW_REL_PATH = ".github/workflows/quality.yml"


def scaffold_ci(repo_root: Path, *, dry_run: bool = False) -> CIScaffoldResult:
    """Scaffold a GitHub Actions CI workflow for common stacks."""
    found, existing_name = has_quality_workflow(repo_root)
    if found:
        return CIScaffoldResult(
            created=False,
            skipped=True,
            skip_reason=(
                f"Existing workflow '{existing_name}' already runs quality checks"
            ),
        )

    language = detect_prep_stack(repo_root)
    content = generate_workflow(language)
    workflow_path = repo_root / _WORKFLOW_REL_PATH

    if not dry_run:
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(content, encoding="utf-8")

    return CIScaffoldResult(
        created=not dry_run,
        skipped=False,
        language=language,
        workflow_path=_WORKFLOW_REL_PATH,
    )
