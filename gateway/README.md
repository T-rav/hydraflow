# HydraFlow LLM gateway

`gateway/Dockerfile` runs the single-worker FastAPI gateway on port 8080. A
single worker is required while virtual keys are held in memory; process
restart intentionally expires every key.

Required runtime configuration:

- `GATEWAY_CONTROL_TOKEN` (at least 32 ASCII bytes; generate with a secure
  random source such as `secrets.token_urlsafe(32)`)
- one complete provider pair:
  `GATEWAY_ANTHROPIC_BASE_URL` + `GATEWAY_ANTHROPIC_API_KEY`, or
  `GATEWAY_ZAI_HARNESS_BASE_URL` + `GATEWAY_ZAI_HARNESS_API_KEY`
- `GATEWAY_LEDGER_PATH` and `GATEWAY_BODY_DIR` for durable mounted storage

The long-running gateway must remain non-root. Pre-create mounted metadata and
body directories for UID/GID 10001. Metadata may be group-readable (`0750`) by
the HydraFlow dashboard's group; raw body storage must remain owner-only
(`0700`) and must never be mounted into HydraFlow workers.

Optional bounds are `GATEWAY_MAX_KEY_TTL_SECONDS` (86,400 seconds by default;
the runner requests at least its subprocess timeout plus a 60-second cleanup
grace), `GATEWAY_MAX_REQUEST_BYTES`, and
`GATEWAY_MAX_CONTROL_REQUEST_BYTES`. Captured artifacts are reaped after
`GATEWAY_BODY_RETENTION_SECONDS` (seven days by default). Full body capture is
disabled by default
and requires both `repo_class=hydraflow` and an
exact repository slug listed in the server-owned, comma-separated
`GATEWAY_BODY_CAPTURE_REPOS` allowlist. The control API is
`POST /control/v1/keys` with a bearer control token. Data-plane requests use
the returned virtual `token` as either a bearer token or `x-api-key`; the
gateway rejects missing, expired, or ambiguous credentials and never supports
a direct-provider bypass.

After a canary has soaked, HydraFlow's terminal fleet profile is enabled with
`HYDRAFLOW_GATEWAY_FLEET_RATCHET_ENABLED=true` plus
`HYDRAFLOW_GATEWAY_BASE_URL` and `HYDRAFLOW_GATEWAY_CONTROL_TOKEN`. The profile
promotes untouched provider dials to `gateway` and rejects any explicitly
configured direct Claude/z.ai harness role. It is intentionally off by default
for installations that have not deployed this service.

The sandbox can override the image command with
`python -m hydraflow_gateway.sandbox_upstream`. It exposes a deterministic
Anthropic SSE `/v1/messages`, `/healthz`, and a sanitized
`/observations/latest` endpoint.

Run `scripts/gateway_probe.py` against a live gateway for the forced two-turn
tool-use confidence probe. The gateway must use the same `GATEWAY_LEDGER_PATH`
and `GATEWAY_BODY_DIR` passed to the probe, the probe process needs read/delete
access to both paths, and `GATEWAY_BODY_CAPTURE_REPOS` must contain the exact
`--repo-slug`. For a z.ai harness canary:

```bash
.venv/bin/python scripts/gateway_probe.py \
  --provider-binding zai-harness \
  --model glm-5.2 \
  --ledger-path "$GATEWAY_LEDGER_PATH" \
  --body-dir "$GATEWAY_BODY_DIR" \
  --live-provider-session \
  --artifact /path/to/sanitized-gateway-evidence.json
```

The probe mints one short-lived, full-capture key. For each turn it resolves the
matching ledger row, hashes the response bytes captured on the gateway's
upstream side and those received downstream, requires exact byte equality, and
then deletes both raw request and response captures. Cleanup also runs on
failure and key revocation. The artifact is finalized only after the key's
revocation is acknowledged. It contains only the versioned schema, provider,
requested and provider-served model names, status codes, byte counts and SHA-256
hashes, completion flags, and explicit sanitization/cleanup/revocation
claims—never prompts, outputs, paths, IDs, headers, raw bodies, or credentials.
The successful-evidence schema rejects blank requested/served models, any
non-2xx turn, and byte counts or hashes that differ across the two sides.

`--agent-session-receipt` can merge a separately collected queued-agent canary
receipt into the artifact. That input is validated with an extra-fields-forbid
schema limited to runtime/version, role and issue number, model/provider, tool
call/result counts, the live-provider flag, validated-output and
issue-transition signals, shared-gateway-observation-window totals for 200 and
expected marker-termination 499 rows, and capture policy. Those gateway totals
must not be attributed to the receipt's issue when the observation window
contained concurrent keys. Session IDs and transcripts are intentionally not
accepted. Omit
`--live-provider-session` for fake or sandbox runs so the artifact cannot
silently claim live-provider evidence.
