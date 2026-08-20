# Gateway conformance fixtures

`conformance_manifest.json` is a deterministic replay artifact. The test suite
sends each checked-in upstream response both directly and through the real
gateway application, then verifies exact response bytes, pinned SHA-256 values,
status, and ordered response headers after excluding connection-scoped fields.

This artifact deliberately does not claim a live provider run. The separate
`scripts/gateway_probe.py` probe exercises a live-provider two-turn tool-use
session when provider credentials are available and stores only sanitized
hashes and counts. Replay conformance supplies the stable direct-versus-gateway
comparison without relying on two nondeterministic model generations.

`claude_cli_sandbox_evidence.json` records a separate confidence run made with
the actual Claude Code binary over real local TCP sockets through the gateway
to the deterministic Anthropic HTTP sandbox. It proves that the CLI completed
an agentic tool-result round trip without receiving a real provider credential.
It is intentionally marked `live_provider_session: false`; live-provider
burn-in remains a release-evidence step, not something this fixture claims.
