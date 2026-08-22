# ADR-0085 — Secrets never persist in the canonical audit stream

**Status:** Accepted
**Date:** 2026-05-30
**Enforcement:** enforced
**Enforced by:**
- pytest:tests/test_secret_scrub.py
- pytest:tests/regressions/test_issue_9143_codeql_suppression.py
- pytest:tests/regressions/test_gateway_token_scrub_11635.py

## Context

`file_util.append_jsonl` is the durable write helper for HydraFlow's canonical audit, transcript, and event JSONL streams (the post-hoc source of truth, dark-factory §2.3). It fsync'd for crash-safety but did **not** redact secrets. Any agent that surfaces a credential — a failing `gh` command echoing `GH_TOKEN`, an agent pasting an env dump into a transcript, a diagnosis quoting an `ANTHROPIC_API_KEY` — would persist it verbatim into the durable, fanned-out audit stream. The prompt-injection surface (ADR-0092) makes this **attacker-triggerable** (a crafted issue can induce the agent to echo the child env).

Redaction existed only on the API-response egress path (`server.py::_scrub`) and the screenshot scanner (`screenshot_scanner._SECRET_PATTERNS`) — not on the write path — and the pattern sets were duplicated (SEC-AUDIT-001/002/003).

## Decision

The **persistence boundary is the single scrub chokepoint**:

1. `src/secret_scrub.py` is the canonical secret-pattern set, with `scan_for_secrets(text)` (detect → labels) and `scrub_secrets(text)` (redact → `[REDACTED:<label>]`).
2. `file_util.append_jsonl` calls `scrub_secrets` on every record before writing, so no credential reaches the canonical audit stream regardless of which subsystem produced it.
3. `screenshot_scanner` reuses the shared patterns (consolidation — one source of truth).
4. Plain `open(path, "a")` JSONL writers route through `append_jsonl` for fsync + scrub — done here for `factory_metrics.jsonl` (the dashboard cost time-series, `trace_rollup`).

## Consequences

- **Secrets are redacted at the durability boundary**, labelled (`[REDACTED:<label>]`), and the scrubbed line remains valid JSON.
- **This is the persistence trust boundary, not the agent sandbox.** A secret in flight is still in the agent's process memory; this ADR only guarantees it does not leak into durable, retained, fanned-out logs.
- Patterns require specific structure (known prefixes, quoted assignments) to keep false-positive redaction of legitimate audit prose low; `scrub_secrets` is idempotent.
- **CodeQL companion (issue #9143).** Because `scrub_secrets` sanitizes the taint that CodeQL's `py/clear-text-storage-sensitive-data` query traces, that query reports a false positive at the `append_jsonl` write sink. The query's barrier set is a hardcoded QL `Sanitizer` class with no Models-as-Data `barrierModel` hook, so it cannot be taught via a data-extension model; the FP is instead suppressed at the sink with a scoped `# codeql[py/clear-text-storage-sensitive-data]` comment, applied to code scanning by the `advanced-security/dismiss-alerts` step in `codeql.yml`. `tests/regressions/test_issue_9143_codeql_suppression.py` guards that wiring against drift.
- **A credential is only covered once it has a grammar to anchor to (issue #11635).** The gateway's virtual key (`hfgw_{key_id}.{secret}`, minted by `hydraflow_gateway/keys.py`) went uncovered for its whole first life, so the credential every gateway-routed worker spawn holds in `ANTHROPIC_AUTH_TOKEN` persisted verbatim. Its pattern requires **both** halves and the dot, because ADR-0138's read plane publishes a bare `key_id` on purpose and this write path is append-only — over-matching destroys retained content with no way back, which is a failure of equal weight to under-matching. The gateway control token had no minter at all (`GatewaySettings` accepts any ≥32-byte ASCII value), so it is covered twice: by its `GATEWAY_CONTROL_TOKEN=`/`HYDRAFLOW_GATEWAY_CONTROL_TOKEN=` binding — the unquoted env-dump shape the quoted-only generic assignment pattern cannot see — and, for tokens minted in the canonical `hfgwctl_` grammar (`gateway/README.md`), standing alone. **Documented limit:** a legacy control token without that prefix, echoed bare with no variable name beside it, remains undetectable; the server stays permissive for backward compatibility, so closing that gap is an operator re-mint, not a code change. **Cost is part of the contract here:** a pattern of the shape `prefix + greedy-class + required-delimiter` is quadratic on attacker-shaped input, and this threat model is attacker-triggerable by construction (ADR-0092) on a path every loop writes through — the virtual key's `key_id` half is therefore ceilinged (`{8,64}`, 2.5x a ULID), turning 4.5 s per 160 KB record into 17 ms. Any future pattern with a required trailing delimiter needs the same ceiling.
- **Residual / follow-up:** other plain-`open` JSONL writers (`health_monitor` `decisions.jsonl`, the advisor session log) should also route through `append_jsonl`; and the disk-full silent-loss (suppressed `OSError` on the append path) must fail loud — both tracked as follow-up, not delivered here.
