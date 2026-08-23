"""Tests for P9 (persistence + data layout) check functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p9_persistence  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# Every P9 check reads one repo tree and reports a status. Each case below
# writes a single source file into an otherwise-empty root and pins the status
# the check reports for it; the `id` is the name the case carried before it
# became a row here.
@pytest.mark.parametrize(
    ("rel_path", "content", "check_id", "expected"),
    [
        # --- data_root field + override ------------------------------------
        pytest.param(
            "src/config.py",
            "from pathlib import Path\nfrom pydantic import Field\n\nclass C:\n    data_root: Path = Field(default=Path('.data'))\n",
            "P9.1",
            Status.PASS,
            id="data_root_field_detected",
        ),
        pytest.param(
            "src/config.py",
            "class C: pass\n",
            "P9.1",
            Status.FAIL,
            id="data_root_field_missing_fails",
        ),
        pytest.param(
            "src/config.py",
            "import os\npath = os.environ.get('PROJ_DATA_ROOT', '.data')\n",
            "P9.2",
            Status.PASS,
            id="env_override_detected",
        ),
        pytest.param(
            "src/config.py",
            "path = '.data'\n",
            "P9.2",
            Status.FAIL,
            id="env_override_missing_fails",
        ),
        pytest.param(
            "src/paths.py",
            "def root(data_root, repo_slug):\n    return data_root / repo_slug\n",
            "P9.3",
            Status.PASS,
            id="repo_slug_scoping_detected",
        ),
        # Scoping is advisory, not required: absent repo_slug WARNs, never FAILs.
        pytest.param(
            "src/paths.py",
            "def root(data_root):\n    return data_root / 'x'\n",
            "P9.3",
            Status.WARN,
            id="repo_slug_scoping_missing_warns",
        ),
        # --- State abstractions --------------------------------------------
        pytest.param(
            "src/state.py",
            "class StateTracker:\n    def write(self, data): ...\n",
            "P9.4",
            Status.PASS,
            id="state_tracker_detected",
        ),
        pytest.param(
            "src/dedup_store.py",
            "class DedupStore:\n    def has(self, key): ...\n",
            "P9.5",
            Status.PASS,
            id="dedup_store_detected",
        ),
        # --- Atomic writes ---------------------------------------------------
        pytest.param(
            "src/w.py",
            "import os\ndef write():\n    os.replace('tmp', 'final')\n",
            "P9.6",
            Status.PASS,
            id="os_replace_counts_as_atomic",
        ),
        pytest.param(
            "src/w.py",
            "def write():\n    open('x', 'w').write('x')\n",
            "P9.6",
            Status.FAIL,
            id="non_atomic_writes_fail",
        ),
        # --- Gitignore + write paths ----------------------------------------
        pytest.param(
            ".gitignore",
            ".hydraflow/\n",
            "P9.7",
            Status.PASS,
            id="gitignore_contains_data_root",
        ),
        pytest.param(
            ".gitignore",
            "*.pyc\n",
            "P9.7",
            Status.WARN,
            id="gitignore_missing_data_root_warns",
        ),
        pytest.param(
            "src/bad.py",
            "def f():\n    with open('output.txt', 'w') as fh:\n        fh.write('x')\n",
            "P9.8",
            Status.WARN,
            id="opens_outside_data_root_warn",
        ),
        pytest.param(
            "src/good.py",
            "def f(data_root):\n    with open(data_root / 'x', 'w') as fh:\n        fh.write('x')\n",
            "P9.8",
            Status.PASS,
            id="opens_inside_data_root_pass",
        ),
    ],
)
def test_p9_check_status_for_source(
    tmp_path: Path, rel_path: str, content: str, check_id: str, expected: Status
) -> None:
    _write(tmp_path / rel_path, content)

    assert _run(check_id, _ctx(tmp_path)).status is expected


# The "abstraction absent entirely" half of P9.4/P9.5 writes NO file — an empty
# `src/` is the input — so these two cannot be rows in the table above.
@pytest.mark.parametrize(
    "check_id",
    ["P9.4", "P9.5"],
    ids=["state_tracker_missing_fails", "dedup_store_missing_fails"],
)
def test_p9_state_abstraction_missing_fails(tmp_path: Path, check_id: str) -> None:
    (tmp_path / "src").mkdir()

    assert _run(check_id, _ctx(tmp_path)).status is Status.FAIL
