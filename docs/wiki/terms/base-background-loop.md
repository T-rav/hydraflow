---
id: "01KQV37D10M06PGF32CF77W6K5"
name: "BaseBackgroundLoop"
kind: "loop"
bounded_context: "shared-kernel"
code_anchor: "src/base_background_loop.py:BaseBackgroundLoop"
aliases: ["base background loop", "loop base class"]
related: [{"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K3"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KTAN3MGDRZ1MGQ21Z2Q2XM8Z"}]
evidence: ["01KQNYZRM4B7DX9MWDQFHF488E", "01KQNYZRM4B7DX9MWDQFHF488H", "01KQP0XFBGMB32VFGNPV8GZ268", "01KQP0XFBGMB32VFGNPV8GZ26F", "01KQP0XFBGMB32VFGNPV8GZ26P", "01KRBX2N4QP7VW8FGH3J5YD0M3", "01KRBX2N4QP7VW8FGH3J5YD0M5"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668776+00:00"
updated_at: "2026-06-06T01:07:16.635794+00:00"
---

## Definition

Abstract base class for every concurrent worker loop in the HydraFlow orchestrator (ADR-0001, ADR-0029). Owns the run-loop skeleton — enabled-check, interval management, status callbacks, BACKGROUND_WORKER_STATUS event publishing, error reporting, and trigger-based early wake-up — leaving subclasses to implement only the domain-specific _do_work and _get_default_interval hooks.

## Invariants

- Subclasses must implement abstract methods _do_work and _get_default_interval.
- AuthenticationError, AuthenticationRetryError, and CreditExhaustedError propagate; all other exceptions are logged and the loop retries on the next cycle.
- Shared dependencies (event_bus, stop_event, status_cb, enabled_cb, sleep_fn, interval_cb) are bundled into a LoopDeps record passed to __init__.
