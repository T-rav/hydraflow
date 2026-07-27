import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  useActivityFeed,
  matchesFilter,
  computeWindow,
  ACTIVITY_FILTERS,
} from '../useActivityFeed'

// `useActivityFeed` (epic #10556, Task 7) owns the interaction state for the
// demoted global ActivityDrawer: the active filter chip, collapsed/expanded
// state, the "N new since last looked" counter, and the lightweight windowing
// (slice-by-scroll) that keeps the expanded list bounded for a large feed.
//
// It consumes the *already-grouped* feed produced by `toActivityFeed(...)`
// (Task 1) — so grouping / the never-group-errors guarantee live in the
// adapter, and this hook only filters, windows, and tracks "new". Tests pass
// feed literals (not raw events) to stay decoupled from the adapter internals,
// mirroring the PipelineRail component-test pattern.

const row = (over = {}) => ({
  ts: '2026-07-26T12:00:00Z',
  type: 'transcript_line',
  severity: 'info',
  summary: 'writing file',
  groupKey: 'transcript:5',
  count: 1,
  ...over,
})

describe('matchesFilter — pure filter predicate', () => {
  it('"all" matches every row', () => {
    for (const r of [row(), row({ type: 'error', severity: 'error' }), row({ type: 'merge_update' })]) {
      expect(matchesFilter(r, 'all')).toBe(true)
    }
  })

  it('"errors" matches error-severity rows but never HITL rows (HITL has its own chip)', () => {
    expect(matchesFilter(row({ type: 'error', severity: 'error' }), 'errors')).toBe(true)
    expect(matchesFilter(row({ type: 'system_alert', severity: 'error' }), 'errors')).toBe(true)
    expect(matchesFilter(row({ type: 'hitl_escalation', severity: 'error' }), 'errors')).toBe(false)
    expect(matchesFilter(row({ type: 'transcript_line', severity: 'info' }), 'errors')).toBe(false)
  })

  it('"merges" matches only merge_update rows', () => {
    expect(matchesFilter(row({ type: 'merge_update' }), 'merges')).toBe(true)
    expect(matchesFilter(row({ type: 'error', severity: 'error' }), 'merges')).toBe(false)
  })

  it('"hitl" matches escalation and update rows only', () => {
    expect(matchesFilter(row({ type: 'hitl_escalation', severity: 'error' }), 'hitl')).toBe(true)
    expect(matchesFilter(row({ type: 'hitl_update', severity: 'error' }), 'hitl')).toBe(true)
    expect(matchesFilter(row({ type: 'error', severity: 'error' }), 'hitl')).toBe(false)
  })

  it('exposes the four canonical chips in order (all·errors·merges·hitl)', () => {
    expect(ACTIVITY_FILTERS.map(f => f.key)).toEqual(['all', 'errors', 'merges', 'hitl'])
  })
})

describe('computeWindow — slice-by-scroll math', () => {
  it('bounds the rendered slice regardless of total feed size', () => {
    const { start, end } = computeWindow({
      scrollTop: 0, rowHeight: 28, viewportHeight: 320, overscan: 4, total: 1000,
    })
    expect(start).toBe(0)
    // ceil(320/28)=12 visible + 2*4 overscan = 20 nodes, never 1000.
    expect(end - start).toBeLessThanOrEqual(20)
  })

  it('advances the window as the container scrolls', () => {
    const { start } = computeWindow({
      scrollTop: 280, rowHeight: 28, viewportHeight: 320, overscan: 4, total: 1000,
    })
    // floor(280/28)=10, minus overscan 4 = 6.
    expect(start).toBe(6)
  })

  it('clamps the window to the feed length near the tail', () => {
    const { start, end } = computeWindow({
      scrollTop: 100000, rowHeight: 28, viewportHeight: 320, overscan: 4, total: 15,
    })
    expect(end).toBe(15)
    expect(start).toBeGreaterThanOrEqual(0)
  })
})

describe('useActivityFeed — interaction state', () => {
  it('defaults to the "all" filter, collapsed, no new counter', () => {
    const { result } = renderHook(() => useActivityFeed([row()]))
    expect(result.current.filter).toBe('all')
    expect(result.current.expanded).toBe(false)
    expect(result.current.newCount).toBe(0)
    expect(result.current.latest).toEqual(expect.objectContaining({ summary: 'writing file' }))
  })

  it('setFilter narrows the filtered feed', () => {
    const feed = [
      row({ type: 'merge_update', severity: 'info', ts: '2026-07-26T12:00:03Z', groupKey: 'm' }),
      row({ type: 'error', severity: 'error', ts: '2026-07-26T12:00:02Z', groupKey: 'e' }),
      row({ type: 'transcript_line', severity: 'info', ts: '2026-07-26T12:00:01Z', groupKey: 't' }),
    ]
    const { result } = renderHook(() => useActivityFeed(feed))
    act(() => result.current.setFilter('errors'))
    expect(result.current.filter).toBe('errors')
    expect(result.current.filtered).toHaveLength(1)
    expect(result.current.filtered[0].type).toBe('error')
  })

  it('counts rows newer than the last-seen top, and markSeen resets it', () => {
    const initial = [row({ ts: '2026-07-26T12:00:02Z', groupKey: 'a' })]
    const { result, rerender } = renderHook(({ feed }) => useActivityFeed(feed), {
      initialProps: { feed: initial },
    })
    expect(result.current.newCount).toBe(0)

    const grown = [
      row({ ts: '2026-07-26T12:00:05Z', groupKey: 'c' }),
      row({ ts: '2026-07-26T12:00:04Z', groupKey: 'b' }),
      ...initial,
    ]
    rerender({ feed: grown })
    expect(result.current.newCount).toBe(2)

    act(() => result.current.markSeen())
    expect(result.current.newCount).toBe(0)
  })

  it('expanding the drawer marks the feed seen (clears the new counter)', () => {
    const initial = [row({ ts: '2026-07-26T12:00:02Z', groupKey: 'a' })]
    const { result, rerender } = renderHook(({ feed }) => useActivityFeed(feed), {
      initialProps: { feed: initial },
    })
    const grown = [row({ ts: '2026-07-26T12:00:05Z', groupKey: 'c' }), ...initial]
    rerender({ feed: grown })
    expect(result.current.newCount).toBe(1)

    act(() => result.current.toggle())
    expect(result.current.expanded).toBe(true)
    expect(result.current.newCount).toBe(0)
  })

  it('windows a large feed to a bounded number of visible rows', () => {
    const big = Array.from({ length: 1000 }, (_, i) =>
      row({ ts: `t${i}`, groupKey: `g${i}`, summary: `line ${i}` }),
    )
    const { result } = renderHook(() => useActivityFeed(big))
    expect(result.current.filtered).toHaveLength(1000)
    expect(result.current.visible.length).toBeLessThanOrEqual(result.current.maxWindow)
    expect(result.current.visible.length).toBeLessThan(50)
    // Total height still spans the whole feed so the scrollbar is honest.
    expect(result.current.totalHeight).toBe(1000 * result.current.rowHeight)
  })

  it('onScroll advances the visible window', () => {
    const big = Array.from({ length: 1000 }, (_, i) =>
      row({ ts: `t${i}`, groupKey: `g${i}`, summary: `line ${i}` }),
    )
    const { result } = renderHook(() => useActivityFeed(big))
    const firstIndex = result.current.visible[0].index
    act(() => result.current.onScroll({ target: { scrollTop: 5000 } }))
    expect(result.current.visible[0].index).toBeGreaterThan(firstIndex)
  })
})
