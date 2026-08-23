# HydraFlow LLM gateway

`gateway/Dockerfile` runs the single-worker FastAPI gateway on port 8080. A
single worker is required while virtual keys are held in memory; process
restart intentionally expires every key.

Required runtime configuration:

- `GATEWAY_CONTROL_TOKEN` (at least 32 ASCII bytes). Mint it in the canonical
  `hfgwctl_` grammar —
  `python -c "import secrets; print('hfgwctl_' + secrets.token_urlsafe(32))"` —
  so the repo's canonical scrubber (`src/secret_scrub.py`, ADR-0085) recognises
  it and redacts it from the durable audit/transcript/event stream. The server
  still accepts any ≥32-byte ASCII token for backward compatibility, but a token
  without that prefix is only redactable when it is printed next to its
  `GATEWAY_CONTROL_TOKEN` (or `HYDRAFLOW_GATEWAY_CONTROL_TOKEN`) variable name,
  as an echoed child env prints it; a bare value is invisible to the scrubber.
  Virtual keys need no such convention:
  `hfgw_{key_id}.{secret}` is minted by the gateway itself and is always matched.
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

`GATEWAY_GOVERNED_REPOS` (empty by default) is the server-owned, comma-separated
list of repositories whose keys **must** be route-bound (ADR-0141). Either
spelling works — the canonical `owner/repo` or the path-safe `owner-repo` — and
both sides of the comparison are reduced to one form, so neither the operator's
spelling nor the caller's can open the boundary.
While a slug is listed, `POST /control/v1/keys` refuses that repository and the
data plane turns away any key without a route binding — so a caller cannot
declare itself ungoverned. It is a deployment control on the far side of the
trust boundary from HydraFlow's own canary dial, and the two are disarmed in a
fixed order: clear `HYDRAFLOW_GATEWAY_ENFORCEMENT_CANARY_REPO` first (routing
reverts on the next spawn), then remove the slug here. Clearing this one first,
or clearing only the HydraFlow dial, leaves that repository's gateway spawns
failing **closed** at the mint — loudly, and in the safe direction.

`GATEWAY_ACCOUNTS_FILE` (unset by default) names the server-owned document that
declares accounts beyond ADR-0138's two compiled legacy ones (ADR-0142). Its
absence is the pre-pool deployment exactly: those two accounts, one candidate
per model, and nowhere for a fallback hop to go. It is **restart-required** — an
account's credential and origin are deployment facts, and reloading them under
live leases would let a key minted against one origin be served by another. The
file never contains a credential: an account names the **variable** that
configures it (`credential_env`), and that name must match
`^GATEWAY_[A-Z0-9_]+$`. That constraint is load-bearing rather than cosmetic —
the `GATEWAY_` namespace is what HydraFlow's worker-environment scrub
(`subprocess_util.scrub_gateway_spawn_env`) strips, so a credential variable
named outside it would be inherited by every routed worker. A document carrying
an `api_key`, or a `credential_env` outside the namespace, is refused at load.

`GATEWAY_ACCOUNT_STATE_DIR` (`.hydraflow/gateway/accounts` by default) is where
the audited administrative overlay and its hash chain live. It needs the same
durable, non-root-writable mount discipline as `GATEWAY_LEDGER_PATH`.

`GATEWAY_MAX_FALLBACK_HOPS` (1 by default) is the hard ceiling on bounded
fallback, and a ceiling rather than a target: the effective bound is always the
smaller of this and the candidate list, so a pool can never be walked in a loop.
`0` disables fallback entirely — every request is served by its first eligible
candidate or fails there.

## Read-only account and route visibility (ADR-0138)

Three authenticated GET endpoints sit behind the same control-token boundary
and change no routing or mint behaviour:

- `GET /control/v2/accounts?window_seconds=<60..86400>` — one sanitized account
  per provider binding (`legacy-anthropic`, `legacy-zai-harness`), configured or
  not, with `configured`, administrative state, lease/in-flight counts, observed
  traffic, and passive health kept as **independent** fields;
- `GET /control/v2/routes/active` — current leases and streaming requests;
- `GET /control/v2/routes/recent?limit=<1..200>` — the bounded in-memory ring of
  terminal routes (200 by default), with `truncated` and `evidence_since` so the
  view never claims a complete history.

No provider key, control token, virtual token, token digest, credential
fingerprint, or captured-body handle appears in any of these payloads; accounts
publish the upstream **origin** and the **name** of the variable that configures
them, never its value. `tests/test_gateway_secret_absence.py` is the proof.
HydraFlow's dashboard proxies all three under `/api/gateway/...`, holding the
control token server-side so the browser never receives one.

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
