// #11221 — WS event batching spec.
//
// Every WS frame used to dispatch its own reducer action, rebuilding the
// O(MAX_EVENTS) events array and changing the context value once per frame —
// fanning a full re-render out to every consumer (classic dashboard +
// operator console) at event rate. These tests pin the coalescing contract:
//
//   A. WS_BATCH folds queued actions SEQUENTIALLY through the same reducer,
//      so dedup / lastSeenId / repo-keying semantics stay byte-identical.
//   B. createWsBatcher is a THROTTLE (timer armed on the first queued frame,
//      fixed max cadence), not a debounce — written to die on mutation.
//   C. The provider wires ws.onmessage through the batcher, flushes on
//      visibilitychange, and never strands tail events.
//   D. A queued-but-unflushed batch survives a WS reconnect/backfill without
//      loss, duplication, or reordering.
//   E. REAL components from BOTH dashboards (classic MetricsPanel, operator
//      OperatorConsole) re-render once per flush window, not once per frame.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import React, { Profiler } from 'react'
import { render, act } from '@testing-library/react'
import { reducer, initialState, createWsBatcher } from '../HydraFlowContext'
import { WS_BATCH_FLUSH_MS, WS_BATCH_MAX_QUEUE } from '../../constants'

// ---------------------------------------------------------------------------
// A. WS_BATCH reducer semantics
// ---------------------------------------------------------------------------
describe('WS_BATCH reducer (#11221 sequential fold)', () => {
  const frame = (id, extra = {}) => ({
    type: 'log', timestamp: `t${id}`, data: {}, id, ...extra,
  })

  it('applies queued actions sequentially: a later duplicate id in the same batch is dropped against the earlier one (arrival-order dedup)', () => {
    const next = reducer(initialState, {
      type: 'WS_BATCH',
      actions: [frame(5), frame(5)],
    })
    expect(next.events.map(e => e.id)).toEqual([5])
    expect(next.lastSeenId).toBe(5)
  })

  it('arrival order within the batch is observable: [id5, id3] keeps only 5 (watermark advanced first), while [id3, id5] keeps both', () => {
    // Sequential fold: 5 lands, watermark moves to 5, then 3 <= 5 is dropped.
    const descending = reducer(initialState, {
      type: 'WS_BATCH',
      actions: [frame(5), frame(3)],
    })
    expect(descending.events.map(e => e.id)).toEqual([5])
    expect(descending.lastSeenId).toBe(5)

    // Reversed arrival: 3 lands first (watermark 3), then 5 > 3 lands too.
    const ascending = reducer(initialState, {
      type: 'WS_BATCH',
      actions: [frame(3), frame(5)],
    })
    expect(ascending.events.map(e => e.id)).toEqual([5, 3])
    expect(ascending.lastSeenId).toBe(5)
  })

  it('produces state byte-identical to dispatching the same actions one at a time', () => {
    const actions = [
      { type: 'worker_update', data: { issue: 5, status: 'active', worker: 1 }, id: 1, timestamp: 't1' },
      { type: 'transcript_line', data: { issue: 5, line: 'first' }, id: 2, timestamp: 't2' },
      { type: 'pr_created', data: { pr: 7, issue: 5 }, id: 3, timestamp: 't3' },
      { type: 'background_worker_status', data: { worker: 'pr_unsticker', status: 'ok', last_run: 'x', details: {} }, id: 4, timestamp: 't4' },
      { type: 'hitl_update', data: { issue: 5 }, id: 5, timestamp: 't5' },
      { type: 'session_start', data: { session_id: 's1', repo: 'org/repo' }, id: 6, timestamp: 't6' },
    ]
    const oneAtATime = actions.reduce((s, a) => reducer(s, a), initialState)
    const batched = reducer(initialState, { type: 'WS_BATCH', actions })
    expect(batched).toEqual(oneAtATime)
  })

  it('a session-resetting action mid-batch resets state for the REST of the batch (fold is stateful, not event-merge)', () => {
    // phase_change plan from idle clears workers + lastSeenId mid-batch; the
    // transcript_line AFTER it must apply against the reset state (its worker
    // is re-created fresh), and the reset lastSeenId must let a low id land.
    const next = reducer(
      { ...initialState, workers: { 42: { status: 'done', role: 'implementer', transcript: ['stale'] } }, lastSeenId: 50 },
      {
        type: 'WS_BATCH',
        actions: [
          { type: 'phase_change', data: { phase: 'plan' }, id: 1, timestamp: 't1' },
          { type: 'transcript_line', data: { issue: 42, line: 'fresh' }, id: 2, timestamp: 't2' },
        ],
      },
    )
    expect(next.phase).toBe('plan')
    expect(next.workers['42'].transcript).toEqual(['fresh'])
    expect(next.lastSeenId).toBe(2)
  })

  it('an empty batch is a strict no-op (same reference)', () => {
    const next = reducer(initialState, { type: 'WS_BATCH', actions: [] })
    expect(next).toBe(initialState)
  })

  it('preserves (repo, id)-keyed dedup across a batch under repo=__all__', () => {
    const agg = { ...initialState, selectedRepoSlug: '__all__' }
    const next = reducer(agg, {
      type: 'WS_BATCH',
      actions: [
        frame(5, { repo: 'owner-a' }),
        frame(5, { repo: 'owner-b' }),
        frame(5, { repo: 'owner-a' }), // exact (repo, id) duplicate — dropped
      ],
    })
    expect(next.events.map(e => e.repo).sort()).toEqual(['owner-a', 'owner-b'])
    // Aggregate view must not advance the single-repo watermark.
    expect(next.lastSeenId).toBe(-1)
  })
})

// ---------------------------------------------------------------------------
// B. createWsBatcher — pure throttle/queue semantics
// ---------------------------------------------------------------------------
describe('createWsBatcher (#11221 pure throttle logic)', () => {
  let dispatch

  beforeEach(() => {
    dispatch = vi.fn()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const batchOf = () => (dispatch.mock.calls.length ? dispatch.mock.calls[0][0] : null)

  it('does not dispatch before the flush window elapses', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    batcher.enqueue({ type: 'log', id: 1 })
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS - 1)
    expect(dispatch).not.toHaveBeenCalled()
  })

  it('flushes the queued frame as one WS_BATCH dispatch once the window elapses', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    batcher.enqueue({ type: 'log', id: 1 })
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS)
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(batchOf()).toMatchObject({ type: 'WS_BATCH', actions: [{ type: 'log', id: 1 }] })
  })

  it('coalesces a burst within one window into a single dispatch, in arrival order', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    for (let i = 0; i < 10; i += 1) batcher.enqueue({ type: 'log', id: i })
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS)
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(batchOf().actions.map(a => a.id)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
  })

  it('is a THROTTLE, not a debounce: a frame at the last instant before the deadline does not push the flush out', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    batcher.enqueue({ type: 'log', id: 1 })
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS - 1)
    // Debounce mutation: this re-arms, pushing the deadline to ~2x the window.
    batcher.enqueue({ type: 'log', id: 2 })
    vi.advanceTimersByTime(1) // total elapsed == exactly WS_BATCH_FLUSH_MS
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(batchOf().actions.map(a => a.id)).toEqual([1, 2])
  })

  it('sustained traffic flushes at the FIXED cadence — a frame per interval never starves the flush (debounce bound)', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    // A frame every 50ms, sustained across two full flush windows. Trace:
    // window 1 opens at t=0 and closes at t=220 (frames 0..200 = 5); window 2
    // opens at t=250 (first frame after the flush) and closes at t=470
    // (frames 250..400 = 4). A debounce — re-arming on every frame — would
    // never fire at all under this traffic: 0 dispatches, unbounded delay.
    const frameEvery = 50
    const total = 2 * WS_BATCH_FLUSH_MS
    for (let t = 0; t < total; t += frameEvery) {
      batcher.enqueue({ type: 'log', id: t })
      vi.advanceTimersByTime(frameEvery)
    }
    // Clock is now at t=450: window 1 flushed at 220; window 2's deadline
    // (470) is still pending — exactly one flush so far.
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(dispatch.mock.calls[0][0].actions).toHaveLength(Math.ceil(WS_BATCH_FLUSH_MS / frameEvery))

    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS)
    expect(dispatch).toHaveBeenCalledTimes(2)
    expect(dispatch.mock.calls[1][0].actions).toHaveLength(4)
  })

  it('re-arms the timer after firing: a second burst is coalesced and flushed again (multi-cycle)', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    batcher.enqueue({ type: 'log', id: 1 })
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS)
    expect(dispatch).toHaveBeenCalledTimes(1)

    // Second burst, after the first flush — must be coalesced into a NEW
    // window and dispatched again, not dropped, not stuck.
    batcher.enqueue({ type: 'log', id: 2 })
    batcher.enqueue({ type: 'log', id: 3 })
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS - 1)
    expect(dispatch).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1)
    expect(dispatch).toHaveBeenCalledTimes(2)
    expect(dispatch.mock.calls[1][0].actions.map(a => a.id)).toEqual([2, 3])
  })

  it('flushes immediately once maxQueue frames are pending, without waiting for the timer', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    for (let i = 0; i < WS_BATCH_MAX_QUEUE; i += 1) batcher.enqueue({ type: 'log', id: i })
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(batchOf().actions).toHaveLength(WS_BATCH_MAX_QUEUE)
  })

  it('a frame right after a threshold flush starts a fresh window (re-arm post-threshold-flush)', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    for (let i = 0; i < WS_BATCH_MAX_QUEUE; i += 1) batcher.enqueue({ type: 'log', id: i })
    expect(dispatch).toHaveBeenCalledTimes(1)

    batcher.enqueue({ type: 'log', id: 999 })
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS - 1)
    expect(dispatch).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1)
    expect(dispatch).toHaveBeenCalledTimes(2)
    expect(dispatch.mock.calls[1][0].actions.map(a => a.id)).toEqual([999])
  })

  it('flush() drains the pending queue immediately (the visibilitychange/unmount trigger)', () => {
    vi.useFakeTimers()
    const batcher = createWsBatcher(dispatch)
    batcher.enqueue({ type: 'log', id: 1 })
    batcher.enqueue({ type: 'log', id: 2 })
    batcher.flush()
    expect(dispatch).toHaveBeenCalledTimes(1)
    expect(batchOf().actions.map(a => a.id)).toEqual([1, 2])
    // The armed timer must be cancelled — no second, empty flush later.
    vi.advanceTimersByTime(WS_BATCH_FLUSH_MS * 2)
    expect(dispatch).toHaveBeenCalledTimes(1)
  })

  it('flush() on an empty queue dispatches nothing', () => {
    const batcher = createWsBatcher(dispatch)
    batcher.flush()
    expect(dispatch).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// C + D. Provider wiring (real HydraFlowProvider, mock WebSocket)
// ---------------------------------------------------------------------------
describe('WS event batching wiring (#11221)', () => {
  let originalWebSocket
  let wsInstances

  const sendFrame = (ws, { type = 'log', id, timestamp, repo, data = {} }) => {
    ws.onmessage({ data: JSON.stringify({ type, data, timestamp, id, repo }) })
  }

  beforeEach(() => {
    originalWebSocket = global.WebSocket
    wsInstances = []
    vi.useFakeTimers()
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url.includes('/api/events?since=')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.includes('/api/system/workers')) return Promise.resolve({ ok: true, json: async () => ({ workers: [] }) })
      if (url.includes('/api/repos')) return Promise.resolve({ ok: true, json: async () => ({ repos: [] }) })
      if (url.includes('/api/runtimes')) return Promise.resolve({ ok: true, json: async () => ({ runtimes: [] }) })
      if (url.includes('/api/sessions')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.includes('/api/epics')) return Promise.resolve({ ok: true, json: async () => ({ epics: [] }) })
      if (url.includes('/api/pipeline')) return Promise.resolve({ ok: true, json: async () => ({ stages: {} }) })
      return Promise.resolve({ ok: true, json: async () => ({}) })
    })
    global.WebSocket = class MockWS {
      constructor() { wsInstances.push(this) }
      close() {}
    }
  })

  afterEach(() => {
    global.WebSocket = originalWebSocket
    document.body.removeAttribute('data-connected')
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.resetModules()
  })

  async function mountWithProbe() {
    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let captured = null
    function Probe() { captured = useHydraFlow(); return null }
    let mounted
    await act(async () => {
      mounted = render(
        <HydraFlowProvider>
          <Probe />
        </HydraFlowProvider>
      )
    })
    return { getCaptured: () => captured, unmount: mounted.unmount }
  }

  it('does not apply a single WS frame to context state until the flush window elapses', async () => {
    const { getCaptured } = await mountWithProbe()
    const ws = wsInstances[0]

    await act(async () => { sendFrame(ws, { id: 1, timestamp: 't1' }) })
    expect(getCaptured().events).toHaveLength(0)

    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS - 1) })
    expect(getCaptured().events).toHaveLength(0)

    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(getCaptured().events.map(e => e.id)).toEqual([1])
  })

  it('coalesces a burst within one window into a single context update, in arrival order', async () => {
    const { getCaptured } = await mountWithProbe()
    const ws = wsInstances[0]

    await act(async () => {
      for (let i = 0; i < 10; i += 1) sendFrame(ws, { id: i, timestamp: `t${i}` })
    })
    expect(getCaptured().events).toHaveLength(0)

    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS) })
    expect(getCaptured().events.map(e => e.id)).toEqual([9, 8, 7, 6, 5, 4, 3, 2, 1, 0])
    expect(getCaptured().lastSeenId).toBe(9)
  })

  it('keeps transcript_line order within a batch (arrival order through the sequential fold)', async () => {
    const { getCaptured } = await mountWithProbe()
    const ws = wsInstances[0]

    await act(async () => {
      sendFrame(ws, { type: 'transcript_line', id: 1, timestamp: 't1', data: { issue: 5, line: 'first' } })
      sendFrame(ws, { type: 'transcript_line', id: 2, timestamp: 't2', data: { issue: 5, line: 'second' } })
      sendFrame(ws, { type: 'transcript_line', id: 3, timestamp: 't3', data: { issue: 5, line: 'third' } })
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS) })
    expect(getCaptured().workers['5'].transcript).toEqual(['first', 'second', 'third'])
  })

  it('is throttled end-to-end: a mid-window frame does not push the flush past the fixed deadline', async () => {
    const { getCaptured } = await mountWithProbe()
    const ws = wsInstances[0]

    await act(async () => { sendFrame(ws, { id: 1, timestamp: 't1' }) })
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS - 1) })
    await act(async () => { sendFrame(ws, { id: 2, timestamp: 't2' }) })
    // Exactly one window has elapsed since frame 1 — a throttle must flush
    // now; a debounce (re-arm on frame 2) would still be holding the batch.
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(getCaptured().events.map(e => e.id).sort()).toEqual([1, 2])
  })

  it('re-arms after firing so a second burst is coalesced and dispatched again (multi-cycle, end-to-end)', async () => {
    const { getCaptured } = await mountWithProbe()
    const ws = wsInstances[0]

    await act(async () => { sendFrame(ws, { id: 1, timestamp: 't1' }) })
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS) })
    expect(getCaptured().events.map(e => e.id)).toEqual([1])

    await act(async () => {
      sendFrame(ws, { id: 2, timestamp: 't2' })
      sendFrame(ws, { id: 3, timestamp: 't3' })
    })
    // Second window hasn't elapsed — the second burst must still be held.
    expect(getCaptured().events.map(e => e.id)).toEqual([1])
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS) })
    expect(getCaptured().events.map(e => e.id).sort()).toEqual([1, 2, 3])
  })

  it('flushes immediately once WS_BATCH_MAX_QUEUE frames arrive (no timer wait)', async () => {
    const { getCaptured } = await mountWithProbe()
    const ws = wsInstances[0]

    await act(async () => {
      for (let i = 0; i < WS_BATCH_MAX_QUEUE; i += 1) sendFrame(ws, { id: i, timestamp: `t${i}` })
    })
    expect(getCaptured().events).toHaveLength(WS_BATCH_MAX_QUEUE)
  })

  it('flushes the pending queue when the document becomes hidden (visibilitychange — no stranded tail)', async () => {
    const { getCaptured } = await mountWithProbe()
    const ws = wsInstances[0]

    await act(async () => {
      sendFrame(ws, { id: 1, timestamp: 't1' })
      sendFrame(ws, { id: 2, timestamp: 't2' })
    })
    expect(getCaptured().events).toHaveLength(0)

    const original = Object.getOwnPropertyDescriptor(document, 'visibilityState')
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    try {
      await act(async () => { document.dispatchEvent(new Event('visibilitychange')) })
      expect(getCaptured().events.map(e => e.id).sort()).toEqual([1, 2])
    } finally {
      if (original) Object.defineProperty(document, 'visibilityState', original)
      else delete document.visibilityState
    }
  })

  it('unmounting the provider flushes/cancels cleanly — no late dispatch errors, no stale timer firing', async () => {
    const { unmount } = await mountWithProbe()
    const ws = wsInstances[0]
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})

    await act(async () => { sendFrame(ws, { id: 1, timestamp: 't1' }) })
    await act(async () => { unmount() })
    // Advancing past the (now cancelled) flush window must be a no-op —
    // flush-on-unmount drained the queue and disarmed the timer.
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS * 2) })
    expect(errors).not.toHaveBeenCalled()
    errors.mockRestore()
  })

  it('preserves a queued-but-unflushed batch across a WS reconnect/backfill without loss, duplication, or reordering', async () => {
    // Backfill returns one event the live queue never saw (id 99).
    global.fetch.mockImplementation((input) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url.includes('/api/events?since=')) {
        return Promise.resolve({
          ok: true,
          json: async () => ([{ type: 'log', timestamp: 't-backfill', data: {}, id: 99 }]),
        })
      }
      if (url.includes('/api/system/workers')) return Promise.resolve({ ok: true, json: async () => ({ workers: [] }) })
      if (url.includes('/api/repos')) return Promise.resolve({ ok: true, json: async () => ({ repos: [] }) })
      if (url.includes('/api/runtimes')) return Promise.resolve({ ok: true, json: async () => ({ runtimes: [] }) })
      if (url.includes('/api/sessions')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.includes('/api/epics')) return Promise.resolve({ ok: true, json: async () => ({ epics: [] }) })
      if (url.includes('/api/pipeline')) return Promise.resolve({ ok: true, json: async () => ({ stages: {} }) })
      return Promise.resolve({ ok: true, json: async () => ({}) })
    })

    const { getCaptured } = await mountWithProbe()

    // Open the first connection so the reconnect backfill cursor is armed.
    await act(async () => { wsInstances[0].onopen && wsInstances[0].onopen() })
    await act(async () => {
      sendFrame(wsInstances[0], { id: 1, timestamp: 't1' })
      sendFrame(wsInstances[0], { id: 2, timestamp: 't2' })
    })
    // Still queued — the flush window hasn't elapsed when the socket drops.
    expect(getCaptured().events.some(e => e.id === 1 || e.id === 2)).toBe(false)

    // Drop the connection (non-1008 → reconnect backoff armed). The queue is
    // owned by the provider, not the socket, so it must survive the drop.
    await act(async () => { wsInstances[0].onclose({ code: 1006 }) })

    // Advance past the reconnect delay AND the flush window — a new socket
    // opens while the pre-disconnect batch flushes through.
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS + 1000) })
    expect(wsInstances.length).toBe(2)

    // The new connection's onopen fires the backfill seeded from
    // lastEventTsRef (updated synchronously per frame, NOT at flush time).
    await act(async () => { wsInstances[1].onopen && wsInstances[1].onopen() })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    const ids = getCaptured().events.map(e => e.id).filter(id => id !== -1).sort((a, b) => a - b)
    expect(ids).toEqual([1, 2, 99]) // no loss, no duplication
  })

  it('updates the reconnect backfill cursor (lastEventTs) synchronously per frame, not at flush time', async () => {
    const requests = []
    global.fetch.mockImplementation((input) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url.includes('/api/events?since=')) {
        requests.push(url)
        return Promise.resolve({ ok: true, json: async () => [] })
      }
      if (url.includes('/api/system/workers')) return Promise.resolve({ ok: true, json: async () => ({ workers: [] }) })
      if (url.includes('/api/repos')) return Promise.resolve({ ok: true, json: async () => ({ repos: [] }) })
      if (url.includes('/api/runtimes')) return Promise.resolve({ ok: true, json: async () => ({ runtimes: [] }) })
      if (url.includes('/api/sessions')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.includes('/api/epics')) return Promise.resolve({ ok: true, json: async () => ({ epics: [] }) })
      if (url.includes('/api/pipeline')) return Promise.resolve({ ok: true, json: async () => ({ stages: {} }) })
      return Promise.resolve({ ok: true, json: async () => ({}) })
    })

    await mountWithProbe()

    await act(async () => { wsInstances[0].onopen && wsInstances[0].onopen() })
    await act(async () => {
      sendFrame(wsInstances[0], { id: 1, timestamp: '2026-08-20T10:00:05Z' })
      sendFrame(wsInstances[0], { id: 2, timestamp: '2026-08-20T10:00:09Z' })
    })
    // Frame 2 is the high-water timestamp even though neither has flushed.
    await act(async () => { wsInstances[0].onclose({ code: 1006 }) })
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS + 1000) })
    await act(async () => { wsInstances[1].onopen && wsInstances[1].onopen() })

    const since = requests.find(r => r.includes('/api/events?since='))
    expect(since).toContain(encodeURIComponent('2026-08-20T10:00:09Z'))
  })
})

// ---------------------------------------------------------------------------
// E. Both dashboards re-render at the throttled cadence — REAL components
// ---------------------------------------------------------------------------
describe('WS batching fan-out: real components from both dashboards (#11221)', () => {
  let originalWebSocket
  let wsInstances

  const sendFrame = (ws, { type = 'log', id, timestamp, repo, data = {} }) => {
    ws.onmessage({ data: JSON.stringify({ type, data, timestamp, id, repo }) })
  }

  beforeEach(() => {
    originalWebSocket = global.WebSocket
    wsInstances = []
    vi.useFakeTimers()
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url.includes('/api/system/workers')) return Promise.resolve({ ok: true, json: async () => ({ workers: [] }) })
      if (url.includes('/api/repos')) return Promise.resolve({ ok: true, json: async () => ({ repos: [] }) })
      if (url.includes('/api/runtimes')) return Promise.resolve({ ok: true, json: async () => ({ runtimes: [] }) })
      if (url.includes('/api/sessions')) return Promise.resolve({ ok: true, json: async () => [] })
      if (url.includes('/api/epics')) return Promise.resolve({ ok: true, json: async () => ({ epics: [] }) })
      if (url.includes('/api/pipeline')) return Promise.resolve({ ok: true, json: async () => ({ stages: {} }) })
      if (url.includes('/api/human-input')) return Promise.resolve({ ok: true, json: async () => ({}) })
      if (url.startsWith('/api/costs') || url.includes('/api/diagnostics/supervisor') || url.includes('/api/diagnostics/trust-fleet') || url.includes('/finders') || url.includes('/judges') || url.includes('/loops/register')) {
        return Promise.resolve({ ok: true, json: async () => null })
      }
      return Promise.resolve({ ok: true, json: async () => ({}) })
    })
    global.WebSocket = class MockWS {
      constructor() { wsInstances.push(this) }
      close() {}
    }
  })

  afterEach(() => {
    global.WebSocket = originalWebSocket
    document.body.removeAttribute('data-connected')
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.resetModules()
  })

  // Mounts the REAL classic-dashboard MetricsPanel (useHydraFlow) and the
  // REAL operator console (default OperatorConsole → useHydraFlowSocket)
  // under one real HydraFlowProvider, with Profiler-backed render counters.
  async function mountBothDashboards() {
    const { HydraFlowProvider } = await import('../HydraFlowContext')
    const { MetricsPanel } = await import('../../components/MetricsPanel')
    const { default: OperatorConsole } = await import('../../operator/OperatorConsole')

    const counts = { classic: 0, operator: 0 }
    const onRender = key => (_id, phase) => {
      if (phase === 'update') counts[key] += 1
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <Profiler id="classic-dashboard" onRender={onRender('classic')}>
            <MetricsPanel />
          </Profiler>
          <Profiler id="operator-console" onRender={onRender('operator')}>
            <OperatorConsole />
          </Profiler>
        </HydraFlowProvider>
      )
    })
    // Let mount-time fetch polls settle before taking the baseline.
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    counts.classic = 0
    counts.operator = 0
    return counts
  }

  it('a burst of frames re-renders both dashboards exactly ONCE per flush window, not once per frame', async () => {
    const counts = await mountBothDashboards()
    const ws = wsInstances[0]

    const burstSize = 10
    // Each frame in its own act — separate React commits, exactly as separate
    // WS message macrotasks commit separately in a real browser. Pre-#11221
    // this burst fanned out one re-render per frame; the batcher must hold
    // all of them until the window closes.
    for (let i = 0; i < burstSize; i += 1) {
      await act(async () => { sendFrame(ws, { id: i, timestamp: `t${i}` }) })
    }
    // Held inside the window: zero re-renders from the burst.
    expect(counts.classic).toBe(0)
    expect(counts.operator).toBe(0)

    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS) })
    expect(counts.classic).toBe(1)
    expect(counts.operator).toBe(1)
  })

  it('two flush windows over sustained traffic re-render both dashboards exactly TWICE (throttled cadence, multi-cycle)', async () => {
    const counts = await mountBothDashboards()
    const ws = wsInstances[0]

    // Window 1: burst, then flush.
    await act(async () => {
      for (let i = 0; i < 5; i += 1) sendFrame(ws, { id: i, timestamp: `t${i}` })
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS) })
    expect(counts.classic).toBe(1)
    expect(counts.operator).toBe(1)

    // Window 2: a second burst coalesced into its OWN flush — the timer
    // re-armed, so this is a second single re-render, not zero (stuck) and
    // not five (per-frame). Each frame is sent in its OWN act so React
    // commits each one separately — per-frame dispatching would produce one
    // commit (and one fan-out re-render) per frame; the batcher must still
    // coalesce all five into the single window-2 flush commit.
    for (let i = 5; i < 10; i += 1) {
      await act(async () => { sendFrame(ws, { id: i, timestamp: `t${i}` }) })
    }
    expect(counts.classic).toBe(1)
    expect(counts.operator).toBe(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(WS_BATCH_FLUSH_MS) })
    expect(counts.classic).toBe(2)
    expect(counts.operator).toBe(2)
  })

  it('counter control: an UNBATCHED dispatch still re-renders both dashboards (the Profiler counts real renders)', async () => {
    // Sanity anchor for the assertions above: the provider's REST human-input
    // poll (3000ms) dispatches HUMAN_INPUT_REQUESTS straight through the
    // reducer — deliberately NOT batched (it's not a WS frame). Advancing
    // exactly one poll interval must produce exactly one re-render on both
    // dashboards, proving the counters move on real re-renders — so the
    // one-per-flush-window numbers above are meaningful, not a stuck counter.
    const counts = await mountBothDashboards()

    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(counts.classic).toBe(1)
    expect(counts.operator).toBe(1)
  })
})
