"""Drift guard for the CodeQL false-positive suppression on the ADR-0085
scrub_secrets audit-write path (issue #9143).

CodeQL's ``py/clear-text-storage-sensitive-data`` query flags
``file_util.append_jsonl``'s ``f.write(scrub_secrets(data) + "\\n")`` as
clear-text storage because it cannot be taught that ``scrub_secrets`` is a
redaction sanitizer: that query's barrier set is a *hardcoded* QL ``Sanitizer``
class (``CleartextStorageQuery.qll``: ``isBarrier(n){ n instanceof Sanitizer }``)
with **no** Models-as-Data ``barrierModel``/``ModelOutput`` hook, so a MaD
sanitizer/neutral model is inert for it. The only supported lever is a scoped
inline suppression *at the sink*, applied to code scanning via the
``advanced-security/dismiss-alerts`` workflow step (GitHub code scanning does not
natively honor inline suppressions).

These structural checks fail loudly the moment that wiring rots — the function
is renamed/moved, ``append_jsonl`` stops scrubbing, the ``# codeql[...]`` comment
drifts off the sink line, or the workflow step is dropped — because any of those
silently re-opens the false positive that gates the ``rc/* -> main`` promotion PR.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRET_SCRUB = REPO_ROOT / "src" / "secret_scrub.py"
FILE_UTIL = REPO_ROOT / "src" / "file_util.py"
CODEQL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "codeql.yml"

SUPPRESS_RULE = "py/clear-text-storage-sensitive-data"
SUPPRESS_COMMENT = f"# codeql[{SUPPRESS_RULE}]"


def test_scrub_secrets_is_a_function_in_secret_scrub() -> None:
    """The modeled sanitizer symbol must actually exist as a function.

    A stale suppression whose target was renamed/moved silently re-opens the FP.
    """
    tree = ast.parse(SECRET_SCRUB.read_text(encoding="utf-8"))
    funcs = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "scrub_secrets" in funcs, (
        "scrub_secrets() is gone from src/secret_scrub.py — the CodeQL "
        "suppression in file_util.append_jsonl is now stale (see issue #9143)."
    )


def test_append_jsonl_still_scrubs_on_the_write_path() -> None:
    """append_jsonl must still route its write through scrub_secrets().

    If the scrub is removed the suppression is no longer load-bearing (and would
    now be masking a *real* clear-text-storage write).
    """
    tree = ast.parse(FILE_UTIL.read_text(encoding="utf-8"))
    append_jsonl = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "append_jsonl"
        ),
        None,
    )
    assert append_jsonl is not None, "append_jsonl() vanished from src/file_util.py"
    calls_scrub = any(
        isinstance(call.func, ast.Name) and call.func.id == "scrub_secrets"
        for call in ast.walk(append_jsonl)
        if isinstance(call, ast.Call)
    )
    assert calls_scrub, (
        "append_jsonl no longer calls scrub_secrets() — the ADR-0085 scrub "
        "chokepoint was broken; the CodeQL suppression must be revisited (#9143)."
    )


def test_suppression_comment_sits_immediately_above_the_sink() -> None:
    """The `# codeql[...]` line must be immediately above the scrub_secrets write.

    CodeQL's inline suppression applies to the *next* line only, so the comment
    and the ``f.write(scrub_secrets(...))`` sink must stay adjacent.
    """
    lines = FILE_UTIL.read_text(encoding="utf-8").splitlines()
    suppress_idx = next(
        (i for i, line in enumerate(lines) if line.strip() == SUPPRESS_COMMENT),
        None,
    )
    assert suppress_idx is not None, (
        f"'{SUPPRESS_COMMENT}' suppression comment missing from src/file_util.py "
        "(issue #9143)."
    )
    assert suppress_idx + 1 < len(lines), "suppression comment is the last line"
    next_line = lines[suppress_idx + 1].strip()
    assert next_line.startswith("f.write(scrub_secrets("), (
        "the CodeQL suppression comment is no longer immediately above the "
        f"scrub_secrets write sink; found next line: {next_line!r}"
    )


def _codeql_analyze_steps() -> list[dict]:
    workflow = yaml.safe_load(CODEQL_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    assert isinstance(steps, list)
    return steps


def test_codeql_analyze_step_writes_local_sarif() -> None:
    """The analyze step must expose an id + local SARIF for dismiss-alerts."""
    analyze = next(
        (
            step
            for step in _codeql_analyze_steps()
            if str(step.get("uses", "")).startswith("github/codeql-action/analyze")
        ),
        None,
    )
    assert analyze is not None, "codeql.yml lost its analyze step"
    assert analyze.get("id") == "analyze", "analyze step must have `id: analyze`"
    assert analyze.get("with", {}).get("output") == "sarif-results", (
        "analyze step must write SARIF locally via `output:` for dismiss-alerts"
    )


def test_codeql_workflow_applies_inline_suppressions() -> None:
    """The dismiss-alerts step must be wired, scoped to python + default branch.

    Without it the inline `# codeql[...]` suppression is inert in GitHub code
    scanning and the FP returns on the next promotion PR (issue #9143).
    """
    dismiss = next(
        (
            step
            for step in _codeql_analyze_steps()
            if str(step.get("uses", "")).startswith("advanced-security/dismiss-alerts")
        ),
        None,
    )
    assert dismiss is not None, (
        "codeql.yml is missing the advanced-security/dismiss-alerts step that "
        "applies inline suppressions to code scanning (issue #9143)."
    )
    condition = dismiss.get("if", "")
    assert "matrix.language == 'python'" in condition, (
        "dismiss-alerts must be scoped to the python matrix leg"
    )
    assert "refs/heads/main" in condition, (
        "dismiss-alerts must run only on the default branch, never on PR runs"
    )
    with_block = dismiss.get("with", {})
    assert "sarif-id" in with_block and "sarif-file" in with_block, (
        "dismiss-alerts needs both sarif-id and sarif-file inputs"
    )
