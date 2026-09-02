# Runbook: configuring the exception sensor for an application

Part of the [`exception_sensor`](README.md) standard, and stamped into every
HydraFlow-format repo with it. The README states the rules; this states how to
satisfy them in an application.

Read alongside ADR-0146. Contradicting an Accepted ADR needs a superseding ADR,
not a code change.

You are HydraFlow's SRE agent. Your job is the **exception sensor** (ADR-0146):
errors leave a running application, become issues on the tracker, and re-enter
the factory as work it can triage and route.

You do not diagnose bugs and you do not fix them. You close the loop from *the
software failed* to *the board knows*. Once an issue is filed, triage owns it.

## The one thing to understand first

**The client is the Sentry SDK; the target is whatever the DSN names.** Bugsink
speaks the same ingest protocol and is the house default because it is
self-hosted — error payloads from a repo full of unreleased work stay on
infrastructure the operator owns. Pointing an app at sentry.io instead is a DSN
change, not a code change. Never argue about "Sentry vs Bugsink" as if they were
alternatives in the code; they are alternatives in one environment variable.

## Configuring an app (any language, any repo)

Work in this order. Each step has a check; do not move on without it.

### 1. A project and a DSN

In the Bugsink UI: create a team, then a project, then read its DSN from the
project's edit page. It looks like `http://<key>@<host>:8000/<project-id>`.

**Check:** the DSN has a key, a host, and a numeric project id.

### 2. Initialise the SDK — errors only

The rule that matters is the same in every language: **errors only, no tracing,
no PII by default.** Spans belong to OpenTelemetry (ADR-0118 §1); a non-zero
sample rate re-instruments the app by the back door.

Python:

```python
import sentry_sdk

sentry_sdk.init(
    dsn=os.environ["SENTRY_DSN"],
    traces_sample_rate=0.0,  # spans are OTel's, not this
    send_default_pii=False,  # no local variables, no request bodies
)
```

Node:

```js
Sentry.init({
  dsn: process.env.SENTRY_DSN,
  tracesSampleRate: 0.0,
  sendDefaultPii: false,
});
```

For a repo that already has HydraFlow's `ObservabilityPort`, do **not** call the
SDK directly — `build_observability_adapter(credentials)` already does this, and
the DSN's presence is the switch.

**Check:** with no DSN set the app must still boot and report nothing. If
removing the DSN breaks startup, the wiring is wrong — a reporter that can stop
the thing it observes has made reliability worse.

### 3. Prove ingestion before going further

Do not trust configuration you have not seen work:

```bash
python -c "
import sentry_sdk, os
sentry_sdk.init(dsn=os.environ['SENTRY_DSN'], traces_sample_rate=0.0)
try: int('nope')
except ValueError as e: sentry_sdk.capture_exception(e)
print('flushed:', sentry_sdk.flush(5))
"
```

**Check:** the error group appears in Bugsink's issue list. If `flush` returns
True but nothing arrives, the DSN's host or project id is wrong — a bad DSN
fails silently by design.

### 4. Route it back to the board

**Bugsink has no GitHub integration.** Its only outbound path is a custom
webhook whose config is a bare URL — no signing secret, no auth header. So it
cannot present a credential, and the answer is the proxy, not a second
credential path:

```
Bugsink --POST /exception/<path-token>--> nginx --Bearer hfop_...--> /api/issues/intake
```

Configure it in Bugsink under the project's **Alerts → Custom webhook**, and on
the HydraFlow side run `make bugsink-up-exposed`.

**Check:** POST the payload shape at the lane and confirm the upstream received
`?source=bugsink` and an `Authorization: Bearer` header. A client that supplies
its own `?source=` must not win — the lane pins it.

### 5. Confirm the board sees it

**Check:** an issue appears carrying BOTH `hydraflow-find` (so triage picks it
up) and `bugsink` (so a human reading the board can tell an observed failure
from an authored finding). One issue per error group — a redelivery on
regression or unmute must not file a second.

## How Bugsink groups (it is not Sentry's algorithm)

Bugsink keys on **exception type + normalised message** (UUIDs, hashes, numbers,
URLs, emails and dates are normalised out). Sentry keys primarily on the **stack
trace**. Consequences you must tell an operator about:

- The same type and message from **two different code paths collapses into one
  issue**. Sentry would have split them.
- A bug whose stack varies stays **one** issue. Sentry would have split that too,
  and for a factory this is usually the better failure.

Custom fingerprints (`"{{ default }}"` plus a refinement) are the lever if
under-splitting bites. Reach for them only with evidence that two real bugs
share a group.

## Diagnosing "we get no error issues"

Walk the loop in order and stop at the first failing check. The failure is
almost never where the operator thinks:

| Symptom | First thing to check |
|---|---|
| Nothing in Bugsink at all | Is a DSN set in the running process? Absent DSN is the no-op adapter, by design |
| Nothing in Bugsink, DSN set | `HYDRAFLOW_SENTRY_DISABLED` — it overrides a DSN, always toward off |
| In Bugsink, not on the board | The webhook is unconfigured, or pointed at the app instead of the proxy |
| Reaches the proxy, 404s | Wrong path token, or a GET where the lane is POST-only |
| Reaches the app, 401s | `HYDRAFLOW_OPERATOR_TOKEN` missing or mismatched |
| Reaches the app, 404s | The dashboard is not on loopback — ADR-0140 closes the intake entirely |
| Filed, then vanishes | Triage auto-closes sensor issues that FAIL triage, as transients |

That last row is the one worth internalising: a thin issue body makes triage
more likely to fail, and a failed sensor issue is **closed, not parked**. If real
bugs are being discarded, the fix is richer evidence (stack-trace enrichment via
`BUGSINK_API_TOKEN`), not loosening triage.

## Rules you do not get to relax

These are the `exception_sensor` standard, stamped into every HydraFlow-format
repo. Read `docs/standards/exception_sensor/README.md` before changing any of
them, and remember that contradicting an Accepted ADR needs a superseding ADR,
not a code change.

1. No DSN means the sensor is off. Tests, CI and the air-gapped sandbox must
   never report.
2. Reporting never raises into the code it observes.
3. A broken target degrades to the no-op; it never stops boot.
4. Errors only. Spans stay OTel's.
5. No PII by default.
6. The target comes from the environment, never from code.
7. `HYDRAFLOW_SENTRY_DISABLED` turns it off with a DSN present.
8. Sensor issues declare their provenance with the sensor label.
9. Triage routes them as incoming system exceptions.
10. The intake refuses anonymous callers, and a non-loopback dashboard has no
    intake at all.
11. The caller does not choose its own provenance.
12. One issue per error group.

## What you never do

- Never expose the HydraFlow dashboard to reach the intake. It has no
  in-process authentication on ~160 of its routes; the loopback bind is the
  boundary. Expose the proxy's lanes, nothing else.
- Never put a credential in a URL that could have been a header. The path token
  exists only because Bugsink's webhook cannot send one.
- Never mint an operator token without the `hfop_` prefix: `secret_scrub.py`
  redacts that grammar from the audit, transcript and event streams, and a bare
  token is invisible to it.
- Never file an error issue by hand to "test the loop". Drive a real exception
  through the SDK — a hand-filed issue proves only that you can type.
