# Sentry Integration Design

**Date:** 2026-03-26
**Status:** Draft
**Beads:** ops-audit-fixes-cnd, ops-audit-fixes-hb1, ops-audit-fixes-v0r, ops-audit-fixes-9qm

## Problem

HydraFlow runs unattended as an orchestrator for hours/days at a time. When errors occur in agent runners, review phases, or background loops, they're logged but not surfaced proactively. Recurring patterns (like the ADR pre-validation spam) go unnoticed until someone manually checks. There's no error grouping, no regression detection, and no performance visibility.

## Goal

Add Sentry for error tracking and performance monitoring. Sentry should be opt-in (no-op when DSN is unset), lightweight, and provide:
- Automatic exception capture with context (repo, phase, issue number)
- Performance tracing for pipeline phases
- Sensitive data scrubbing (GH tokens, API keys)

## Existing Error Infrastructure

HydraFlow already has strong error handling patterns:
- **259 exception handlers** across 53 source files
- **81 `logger.error`/`logger.exception` calls** across 26 files
- **`is_likely_bug(exc)`** function (39 usages) — distinguishes real bugs from transient errors like API timeouts, auth retries, network blips
- **`reraise_on_credit_or_bug(exc)`** — re-raises `CreditExhaustedError` and `TypeError`/`AttributeError` (likely bugs)
- **Custom exception hierarchy:**
  - `AuthenticationError` / `AuthenticationRetryError` — transient, auto-retried
  - `CreditExhaustedError` — budget limit, should alert
  - `SubprocessTimeoutError` — agent hung, should track frequency
  - `SelfReviewError` — review process issue
  - `BeadsNotInstalledError` — missing tool
  - `IncompleteIssueFetchError` — partial data

## Design

### 1. SDK Setup (`server.py:main()`)

```python
def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    # Initialize Sentry before anything else
    sentry_dsn = os.environ.get("SENTRY_DSN", "")
    if sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=os.environ.get("HYDRAFLOW_ENV", "development"),
            release=f"hydraflow@{_get_version()}",
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            profiles_sample_rate=float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.1")),
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
            ],
            before_send=_scrub_sensitive_data,
            before_send_transaction=_scrub_sensitive_data,
        )
```

### 2. Config Field

```python
# In config.py — NOT in HydraFlowConfig (Sentry initializes before config loads)
# Sentry DSN is read directly from os.environ in server.py:main()
```

Sentry must initialize before `load_runtime_config()` so it captures config-loading errors. The DSN comes from `SENTRY_DSN` env var (standard Sentry convention), not from `HydraFlowConfig`. This also means `.env` loading (via `load_dotenv()`) must happen before Sentry init — which it already does.

Additional Sentry settings via env vars (standard Sentry SDK behavior):
- `SENTRY_DSN` — the DSN (empty = disabled)
- `SENTRY_TRACES_SAMPLE_RATE` — transaction sampling rate (default 0.1)
- `SENTRY_PROFILES_SAMPLE_RATE` — profiling rate (default 0.1)
- `HYDRAFLOW_ENV` — environment tag (default "development")

### 3. Sensitive Data Scrubbing

```python
_SENSITIVE_PATTERNS = re.compile(
    r"(ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|"
    r"sk-[a-zA-Z0-9]{48}|Bearer\s+[a-zA-Z0-9._-]+)",
    re.IGNORECASE,
)

def _scrub_sensitive_data(event, hint):
    """Remove GitHub tokens, API keys, and bearer tokens from Sentry events."""
    def _scrub(obj):
        if isinstance(obj, str):
            return _SENSITIVE_PATTERNS.sub("[REDACTED]", obj)
        if isinstance(obj, dict):
            return {k: _scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_scrub(v) for v in obj]
        return obj
    return _scrub(event)
```

### 4. Structured Context Tags

Set context at key execution points:

**Orchestrator loop entry** (`orchestrator.py`):
```python
import sentry_sdk

# At the start of each phase loop iteration
sentry_sdk.set_tag("hydraflow.phase", "implement")
sentry_sdk.set_tag("hydraflow.repo", self._config.repo)
```

**Runner execution** (`base_runner.py:_execute()`):
```python
sentry_sdk.set_tag("hydraflow.issue", str(issue_id))
sentry_sdk.set_tag("hydraflow.worker_id", str(worker_id))
sentry_sdk.set_context("hydraflow", {
    "phase": event_data.get("source", "unknown"),
    "issue": issue_id,
    "model": self._config.model,
    "tool": self._config.implementation_tool,
})
```

**Background loops** (`base_background_loop.py:_run_loop()`):
```python
sentry_sdk.set_tag("hydraflow.loop", self._name)
```

### 5. Transaction Spans for Pipeline Phases

Wrap each pipeline phase iteration in a Sentry transaction:

**Implement phase** (`implement_phase.py`):
```python
with sentry_sdk.start_transaction(
    op="pipeline.implement",
    name=f"implement:#{issue.id}",
) as txn:
    txn.set_tag("issue", str(issue.id))

    with txn.start_child(op="agent.run", description="Implementation agent"):
        result = await self._agents.run(issue, worktree_path, branch)

    with txn.start_child(op="quality.gate", description="Quality gate"):
        quality = await self._run_quality_gate(worktree_path)

    with txn.start_child(op="pr.create", description="Create PR"):
        await self._prs.create_pr(branch, issue)
```

Same pattern for plan, review, triage, and HITL phases.

### 6. Error Classification

Leverage the existing `is_likely_bug` function to control what Sentry captures:

```python
# In phase_utils.py or a new sentry_utils.py
def capture_if_bug(exc: Exception, **context) -> None:
    """Send to Sentry only if the exception looks like a real bug."""
    if is_likely_bug(exc):
        sentry_sdk.capture_exception(exc)
    else:
        # Transient errors: just set breadcrumb for context
        sentry_sdk.add_breadcrumb(
            category="transient_error",
            message=str(exc),
            level="warning",
            data=context,
        )
```

This prevents flooding Sentry with:
- Network timeouts (transient)
- GitHub API rate limits (expected)
- OAuth token refresh blips (auto-retried)
- Agent subprocess non-zero exits (normal failure path)

While still capturing:
- `TypeError` / `AttributeError` in production code (real bugs)
- Unhandled exceptions that escape try/except blocks
- `CreditExhaustedError` (operational alert)

### 7. Breadcrumbs for Agent Transcripts

Add truncated agent transcripts as breadcrumbs so Sentry events have context:

```python
# In base_runner.py after agent execution
sentry_sdk.add_breadcrumb(
    category="agent.transcript",
    message=transcript[:1024],  # truncated to 1KB
    level="info",
    data={
        "issue": issue_id,
        "source": event_data.get("source"),
        "full_length": len(transcript),
    },
)
```

### 8. Alerts Worth Configuring in Sentry UI

After deployment, configure these alerts in the Sentry dashboard:

| Alert | Condition | Action |
|-------|-----------|--------|
| Pipeline stall | No transactions for 30 min during business hours | Slack/email |
| Error spike | >5 errors in 10 min (grouped) | Slack |
| Credit exhaustion | `CreditExhaustedError` captured | Immediate alert |
| New issue type | First occurrence of a new error group | Slack |
| Slow agent | Transaction `agent.run` > 10 min | Warning |

### 9. What NOT to Send to Sentry

- Full agent transcripts (too large, may contain code)
- Issue body content (may contain sensitive project info)
- `.env` file contents
- Git diffs (too large)
- Full subprocess command lines (may contain tokens)

The `_scrub_sensitive_data` function handles token removal. For size, Sentry's built-in 100KB event limit naturally truncates large payloads.

## Files to Modify

| File | Change |
|------|--------|
| `pyproject.toml` | Add `sentry-sdk[fastapi]` dependency |
| `src/server.py` | Init Sentry in `main()` before config |
| `src/base_runner.py` | Add context tags + transcript breadcrumbs |
| `src/base_background_loop.py` | Add loop name tag |
| `src/orchestrator.py` | Add phase + repo tags at loop entry |
| `src/implement_phase.py` | Transaction spans |
| `src/plan_phase.py` | Transaction spans |
| `src/review_phase.py` | Transaction spans |
| `src/triage_phase.py` | Transaction spans |
| `src/hitl_phase.py` | Transaction spans |
| `src/phase_utils.py` | Add `capture_if_bug()` helper |
| `tests/test_sentry_integration.py` | Verify init, scrubbing, context |

## Implementation Order

1. Config + SDK init + scrubbing (beads cnd + hb1)
2. Context tags on runners + orchestrator (bead v0r)
3. Transaction spans on phases (bead 9qm)
4. Tests throughout

## What This Does NOT Include (Future)

- Datadog metrics (wait for multi-tenant hosted deployment)
- Custom Sentry dashboards (configure in Sentry UI post-deploy)
- User feedback integration (not applicable — no end users)
- Source maps for React dashboard (add separately if needed)
