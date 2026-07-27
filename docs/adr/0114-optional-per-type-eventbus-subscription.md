# ADR-0114: Optional per-type EventBus subscription

**Status:** Accepted
**Date:** 2026-07-27
**Enforcement:** enforced
**Enforced by:** pytest:tests/test_events.py::TestEventBusTypedSubscription::test_typed_subscriber_receives_only_subscribed_types

**Precedent:** Publish–subscribe messaging — the type/topic-filtered message-bus tradition (Eugster et al., "The Many Faces of Publish/Subscribe", ACM Computing Surveys 2003; the JMS/AMQP topic-subscription model, where a subscriber declares the subjects it wants and the broker filters before delivery)
**Divergence:** that tradition assumes a broker with effectively unbounded (or spillable) per-subscriber buffers and at-least-once delivery, so a subscriber can drain a firehose without losing what it cared about; here the bus is in-process `asyncio` queues with a fixed 500-slot buffer that drops the *oldest* event under overflow, so an unfiltered high-volume type (e.g. `TRANSCRIPT_LINE`) can evict events a consumer needed — the forcing condition #10660 names — and the rule is that a subscriber MAY opt into a publish-time per-type filter so its bounded queue only holds the types it asked for, with fan-out remaining the default (receipt: #10660)

## Context

HydraFlow's `EventBus` (`src/events.py`) has always been a pure **fan-out** bus:
`EventBus.subscribe()` / `EventBus.subscription()` took no `EventType`, and
`EventBus.publish()` enqueued **every** event to **every** subscriber. Each
subscriber owns a bounded `asyncio.Queue` (default 500 slots) that drops its
oldest entry when full. This was correct while the only consumer was the
dashboard WebSocket endpoint, which genuinely wants the whole stream and drains
it fast.

That assumption breaks as *loops* begin to consume events. Issue #10599's wake
router subscribes so it can react to a handful of low-frequency types, but under
the fan-out contract its 500-slot queue also receives the high-volume types it
will never act on — chiefly `TRANSCRIPT_LINE`, emitted continuously by every
running agent. Two costs follow:

1. **Wasted drain.** The consumer pays to dequeue and discard events it filters
   out client-side — the bus offered no way to say "only these types".
2. **Overflow drops.** A burst of an ignored high-volume type fills the bounded
   queue and evicts (oldest-first) the low-frequency events the consumer
   *did* care about, before it ever gets to look at them. Client-side filtering
   cannot fix this: by the time the consumer inspects an event, the one it
   wanted has already been pushed out.

The `EventBus` contract is a shared fan-out bus documented as such in the
architecture extractor (`src/arch/extractors/events.py`) and its generated doc
(`docs/arch/generated/events.md`). Changing what a subscription delivers is a
change to that contract, so it is recorded here rather than slipped in.

## Decision

Give `EventBus.subscribe()` and `EventBus.subscription()` an **optional**
`types: frozenset[EventType] | None = None` parameter, and apply it as a filter
**at publish time**:

- **`types is None` (default) — unchanged fan-out.** The subscriber receives
  every published event, exactly as before. Existing untyped subscribers (the
  dashboard WebSocket) are byte-for-byte unaffected: this is backward
  compatible.
- **`types` is a frozenset — publish-time filter.** `EventBus.publish()` only
  enqueues an event to that subscriber when `event.type in types`. The check
  runs **before** the `queue.put_nowait`, so a filtered-out type never occupies
  one of the subscriber's bounded slots and therefore can never trigger the
  overflow eviction of a type the consumer wanted. This is the property
  client-side filtering could not provide.

All other bus semantics are preserved: queue size, the drop-oldest overflow
policy, `EventBus`-managed history and persistence (a filter is delivery-only —
history still records every non-ephemeral event), unsubscribe, and thread/async
behavior. Internally the subscriber registry moves from a `list` of queues to an
insertion-ordered `dict` mapping each queue to its optional filter, preserving
FIFO fan-out order.

The architecture extractor is updated in lockstep so the self-documenting
topology stays honest: a `subscribe(types={EventType.X, ...})` call site is now
recognized as a **typed subscriber** (`src/arch/_models.py:TypedSubscriber`),
distinct from a fan-out consumer, and the generated event-bus doc
(`src/arch/generators/event_bus.py`) lists typed consumers and attributes them
to the specific events they filter on.

## Consequences

**Positive**
- A loop-level consumer subscribes to only the types it acts on and its bounded
  queue can no longer be overrun — or drained — by an ignored high-volume type.
  This is the concrete unblock for the #10599 wake router.
- The default is unchanged, so the change is additive and backward compatible;
  no existing subscriber is touched.
- The typed-vs-fan-out distinction is now visible in the generated architecture
  doc, so future readers see which consumers are selective.

**Negative**
- The subscriber registry is now a `dict`, so any code inspecting the private
  `EventBus._subscribers` as a list must adapt (only tests did; updated here).

**Neutral**
- The filter is delivery-only: it does not change what enters history or the
  on-disk event log, which remain complete.

## Alternatives considered

**Keep pure fan-out; filter client-side (status quo).** Rejected: it cannot
prevent the overflow drop — an ignored burst still fills the bounded queue and
evicts wanted events before the consumer inspects them.

**Per-subscriber unbounded queues.** Rejected: unbounded queues trade a bounded,
observable drop for an unbounded memory-growth risk under a slow consumer — the
exact failure the 500-slot cap exists to prevent.

**A separate typed-bus class.** Rejected: it forks the publish path and the
history/persistence machinery, doubling the surface that must stay in sync, to
express what is one optional parameter on the existing bus.

## Related

- [ADR-0113](0113-adr-lineage-precedent-and-divergence.md) — the lineage
  (Precedent/Divergence) convention this record follows
- `src/events.py:EventBus` — `EventBus.subscribe`, `EventBus.subscription`, and
  `EventBus.publish` carry the optional filter and apply it at publish time
- `src/arch/extractors/events.py`, `src/arch/generators/event_bus.py` — recognize
  and render typed subscribers so the topology doc reflects the new shape
- #10660 (this decision's receipt), #10599 (the wake-router consumer that
  motivates it)
