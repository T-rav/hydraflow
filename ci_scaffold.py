"""CI workflow scaffolding for GitHub Actions.

Generates a `.github/workflows/quality.yml` workflow with stack-specific
lint/test/build-style checks for common ecosystems.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from manifest import detect_language  # noqa: F401 - re-export for compatibility tests
from polyglot_prep import detect_prep_stack


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


_PYTHON_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install ruff pyright pytest
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: Lint
        run: ruff check . || true
      - name: Test
        run: pytest -q || true
      - name: Build
        run: python -m compileall -q .
"""

_NODE_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        run: |
          if [ -f package-lock.json ]; then npm ci; else npm install; fi
      - name: Lint
        run: npm run lint --if-present
      - name: Test
        run: npm test --if-present
      - name: Build
        run: npm run build --if-present
"""

_MIXED_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install Python dependencies
        run: |
          pip install ruff pyright pytest
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: Install Node dependencies
        run: |
          if [ -f package-lock.json ]; then npm ci; else npm install; fi
      - name: Lint
        run: |
          ruff check . || true
          npm run lint --if-present
      - name: Test
        run: |
          pytest -q || true
          npm test --if-present
      - name: Build
        run: |
          python -m compileall -q .
          npm run build --if-present
"""

_JAVA_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Java
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '21'
      - name: Build and test (Maven/Gradle)
        run: |
          if [ -f pom.xml ]; then
            mvn -B verify;
          elif [ -f gradlew ]; then
            ./gradlew check build;
          elif [ -f build.gradle ] || [ -f build.gradle.kts ]; then
            gradle check build;
          fi
"""

_RUBY_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Ruby
        uses: ruby/setup-ruby@v1
      - name: Install dependencies
        run: bundle install --jobs 4 --retry 3
      - name: Lint
        run: bundle exec rubocop || true
      - name: Test
        run: bundle exec rspec || bundle exec rake test || true
      - name: Build
        run: bundle exec rake -T > /dev/null
"""

_RAILS_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Ruby
        uses: ruby/setup-ruby@v1
      - name: Install dependencies
        run: bundle install --jobs 4 --retry 3
      - name: Lint
        run: bundle exec rubocop || true
      - name: Test
        run: bundle exec rails test || bundle exec rspec || true
      - name: Build
        run: bundle exec rails runner "puts Rails.env"
"""

_CSHARP_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up .NET
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'
      - name: Restore
        run: dotnet restore
      - name: Build
        run: dotnet build --configuration Release --no-restore
      - name: Test
        run: dotnet test --configuration Release --no-build
"""

_GO_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Go
        uses: actions/setup-go@v5
        with:
          go-version: '1.22'
      - name: Lint
        run: go vet ./...
      - name: Test
        run: go test ./...
      - name: Build
        run: go build ./...
"""

_RUST_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint
        run: cargo fmt --check || true
      - name: Build
        run: cargo build --all-targets
      - name: Test
        run: cargo test --all-targets
"""

_CPP_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Configure
        run: |
          if [ -f CMakeLists.txt ]; then
            cmake -S . -B build;
          fi
      - name: Build
        run: |
          if [ -d build ]; then cmake --build build; fi
      - name: Test
        run: |
          if [ -d build ]; then ctest --test-dir build --output-on-failure || true; fi
"""

_UNKNOWN_WORKFLOW = """\
name: Quality
# prep-managed: quality-workflow

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run quality checks
        run: make quality
"""

_WORKFLOW_TEMPLATES: dict[str, str] = {
    "python": _PYTHON_WORKFLOW,
    "javascript": _NODE_WORKFLOW,
    "node": _NODE_WORKFLOW,
    "mixed": _MIXED_WORKFLOW,
    "java": _JAVA_WORKFLOW,
    "ruby": _RUBY_WORKFLOW,
    "rails": _RAILS_WORKFLOW,
    "csharp": _CSHARP_WORKFLOW,
    "go": _GO_WORKFLOW,
    "rust": _RUST_WORKFLOW,
    "cpp": _CPP_WORKFLOW,
    "unknown": _UNKNOWN_WORKFLOW,
}


def generate_workflow(language: str) -> str:
    """Return the GitHub Actions workflow YAML for the given language."""
    return _WORKFLOW_TEMPLATES.get(language, _UNKNOWN_WORKFLOW)


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
