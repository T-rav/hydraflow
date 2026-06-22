---
id: "01KQV37D10M06PGF32CF77W6K4"
name: "StateTracker"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/state/__init__.py:StateTracker"
aliases: ["state tracker", "state facade", "state mixin facade"]
related: []
evidence: ["01KQP0AJ4Y4348S0D9AKRTCPP7", "01KQP0AJ4Z2MY1EXMWW9BTXN97", "01KQP0DZNDCVJVV0YHTG430T31", "01KQP0V9KK99G77287P414NFQY", "01KQP0V9KK99G77287P414NFRQ", "01KV2R9KH9H5QWCWT9K2NEYR0W"]
evidence: ["01KQP0AJ4Y4348S0D9AKRTCPP7", "01KQP0AJ4Z2MY1EXMWW9BTXN97", "01KQP0DZNDCVJVV0YHTG430T31", "01KQP0V9KK99G77287P414NFQY", "01KQP0V9KK99G77287P414NFRQ"]
evidence: ["01KQP0AJ4Y4348S0D9AKRTCPP7", "01KQP0AJ4Z2MY1EXMWW9BTXN97", "01KQP0AJ4Z2MY1EXMWW9BTXN99", "01KQP0DZNDCVJVV0YHTG430T31", "01KQP0V9KK99G77287P414NFQY", "01KV254C264KNTZ962PHQ8SZ2M"]
evidence: ["01KQP0AJ4Y4348S0D9AKRTCPP7", "01KQP0AJ4Z2MY1EXMWW9BTXN97", "01KQP0AJ4Z2MY1EXMWW9BTXN99", "01KQP0DZNDCVJVV0YHTG430T31", "01KQP0V9KK99G77287P414NFQY"]
evidence: ["01KQP0AJ4Y4348S0D9AKRTCPP7", "01KQP0AJ4Z2MY1EXMWW9BTXN97", "01KQP0AJ4Z2MY1EXMWW9BTXN99", "01KQP0AJ4Z2MY1EXMWW9BTXN9H", "01KQP0DZNDCVJVV0YHTG430T31", "01KQP0V9KK99G77287P414NFQY", "01KRBX2N4QP7VW8FGH3J5YD0M6"]
evidence: ["01KQP0AJ4Y4348S0D9AKRTCPP7", "01KQP0AJ4Z2MY1EXMWW9BTXN97", "01KQP0DZNDCVJVV0YHTG430T31", "01KQP0V9KK99G77287P414NFQY", "01KQP0V9KK99G77287P414NFRQ", "01KQP0V9KK99G77287P414NFRR"]
evidence: ["01KQP0AJ4Y4348S0D9AKRTCPP7", "01KQP0AJ4Z2MY1EXMWW9BTXN97", "01KQP0AJ4Z2MY1EXMWW9BTXN99", "01KQP0DZNDCVJVV0YHTG430T31", "01KRBX2N4QP7VW8FGH3J5YD0M6"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668771+00:00"
updated_at: "2026-06-14T14:02:43.251372+00:00"
updated_at: "2026-06-14T09:02:32.894574+00:00"
updated_at: "2026-06-14T04:41:09.432376+00:00"
updated_at: "2026-06-14T04:08:25.937221+00:00"
updated_at: "2026-06-13T05:06:24.709864+00:00"
updated_at: "2026-06-20T02:19:44.961938+00:00"
updated_at: "2026-06-13T05:04:53.216762+00:00"
---

## Definition

JSON-file backed state service for crash recovery. Composes ~30 domain mixins (issue, workspace, HITL, review, route-back, epic, session, worker, principles audit, sentry, trust fleet, ...) into a single facade that writes <repo_root>/.hydraflow/state.json after every mutation and rotates timestamped backups so a corrupt primary file can be restored from .bak.

## Invariants

- Every mutating method persists state to disk before returning.
- Issue/PR/epic numbers are stored as string keys; helpers convert to int on read.
- On corrupt primary file, load() falls back to the most recent .bak before defaulting to an empty StateData.
