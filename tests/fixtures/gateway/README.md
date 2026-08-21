# Gateway conformance fixtures

`conformance_manifest.json` is a deterministic replay artifact. The test suite
sends each checked-in upstream response both directly and through the real
gateway application, then verifies exact response bytes, pinned SHA-256 values,
status, and ordered response headers after excluding connection-scoped fields.

This artifact deliberately does not claim a live provider run. The separate
`scripts/gateway_probe.py` exercises a provider-selectable two-turn tool-use
session. With the gateway's explicit body-capture allowlist enabled, it compares
the downstream stream with the gateway-captured upstream response for the exact
same request, requires equal raw bytes/counts/SHA-256 values, deletes the raw
request and response captures, and stores only a sanitized versioned artifact.
This avoids the invalid comparison of two independent nondeterministic model
generations. Replay conformance remains the stable fixture-level direct-versus-
gateway comparison.

`live_provider_probe_evidence.json` records the 2026-08-20 real-provider run.
Both z.ai-bound turns compare the gateway-captured upstream response with the
bytes delivered downstream for the exact same request. The embedded queued
agent receipt records issue-specific planner outcomes separately from totals
over a shared gateway observation window; those totals are not evidence that
all counted requests belonged to the receipt's issue. The request named
`glm-5.2`; z.ai reported `glm-5.3` as the model served on both exact ledger
rows. The artifact preserves that observed divergence rather than treating a
requested model as proof of the model served.

`claude_cli_sandbox_evidence.json` records a separate confidence run made with
the actual Claude Code binary over real local TCP sockets through the gateway
to the deterministic Anthropic HTTP sandbox. It proves that the CLI completed
an agentic tool-result round trip without receiving a real provider credential.
It is intentionally marked `live_provider_session: false`; live-provider
burn-in remains a release-evidence step, not something this fixture claims.
