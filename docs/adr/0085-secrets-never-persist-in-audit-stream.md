# ADR-0085 — Secrets never persist in the canonical audit stream

**Status:** Accepted
**Date:** 2026-05-30
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_secret_scrub.py

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
- **Residual / follow-up:** other plain-`open` JSONL writers (`health_monitor` `decisions.jsonl`, the advisor session log) should also route through `append_jsonl`; and the disk-full silent-loss (suppressed `OSError` on the append path) must fail loud — both tracked as follow-up, not delivered here.
