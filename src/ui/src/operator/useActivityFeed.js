/**
 * useActivityFeed — interaction state for the operator console's demoted global
 * ActivityDrawer (epic #10556, Task 7).
 *
 * The heavy lifting (grouping consecutive heartbeats / transcript runs, and the
 * LOAD-BEARING guarantee that error / hitl / alert rows are NEVER grouped) lives
 * upstream in `toActivityFeed(...)` (Task 1). This hook consumes that already
 * grouped feed and owns only presentation state:
 *
 *   - the active filter chip (`all · errors · merges · hitl`),
 *   - collapsed / expanded state,
 *   - the "N new" counter (rows newer than the last time the operator looked),
 *   - lightweight windowing (slice-by-scroll) so the expanded list renders a
 *     bounded number of DOM nodes even for a feed of thousands — no new runtime
 *     dependency, per the plan's "no new dep" constraint.
 *
 * The feed is newest-first (as the HydraFlowContext reducer stores events), so
 * `latest` is the head of the filtered feed and "new" rows are those at the head
 * with a `ts` greater than the last-seen top.
 */

import { useCallback, useMemo, useState } from 'react'

/** The four canonical filter chips, in display order. */
export const ACTIVITY_FILTERS = [
  { key: 'all', label: 'all' },
  { key: 'errors', label: 'errors' },
  { key: 'merges', label: 'merges' },
  { key: 'hitl', label: 'hitl' },
]

const HITL_TYPES = new Set(['hitl_escalation', 'hitl_update'])

function isHitlRow(row) {
  return HITL_TYPES.has(row?.type)
}

/**
 * Pure predicate: does a feed row belong under the given filter chip?
 * `errors` deliberately excludes HITL rows — HITL has its own chip, so the two
 * partitions stay distinct.
 */
export function matchesFilter(row, filter) {
  switch (filter) {
    case 'errors':
      return row?.severity === 'error' && !isHitlRow(row)
    case 'merges':
      return row?.type === 'merge_update'
    case 'hitl':
      return isHitlRow(row)
    case 'all':
    default:
      return true
  }
}

/**
 * Pure slice-by-scroll math. Given the scroll offset and geometry, return the
 * `[start, end)` slice of rows to render. The slice size is bounded by the
 * viewport height plus an overscan margin — never the total feed size — and is
 * clamped to the feed so the tail renders correctly.
 */
export function computeWindow({ scrollTop = 0, rowHeight, viewportHeight, overscan, total }) {
  const visibleCount = Math.max(1, Math.ceil(viewportHeight / rowHeight))
  const windowNodes = visibleCount + overscan * 2
  const maxStart = Math.max(0, total - windowNodes)
  const rawStart = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
  const start = Math.min(rawStart, maxStart)
  const end = Math.min(total, start + windowNodes)
  return { start, end, windowNodes, visibleCount }
}

const DEFAULTS = { rowHeight: 28, viewportHeight: 320, overscan: 4 }

/**
 * @param {Array<{ts,type,severity,summary,groupKey,count}>} feed
 *   The grouped activity feed from `toActivityFeed(...)`, newest-first.
 * @param {{rowHeight?:number, viewportHeight?:number, overscan?:number}} [options]
 */
export function useActivityFeed(feed = [], options = {}) {
  const { rowHeight, viewportHeight, overscan } = { ...DEFAULTS, ...options }

  const rows = feed || []
  const [filter, setFilterState] = useState('all')
  const [expanded, setExpanded] = useState(false)
  const [scrollTop, setScrollTop] = useState(0)
  // Seed the "seen" marker to the current head so a fresh mount shows 0 new.
  const [seenTs, setSeenTs] = useState(() => rows[0]?.ts ?? null)

  const filtered = useMemo(
    () => rows.filter(r => matchesFilter(r, filter)),
    [rows, filter],
  )

  const latest = filtered[0] ?? rows[0] ?? null

  // Count head rows newer than the last-seen top. The feed is newest-first, so
  // stop at the first row that is not newer than the marker.
  const newCount = useMemo(() => {
    if (rows.length === 0) return 0
    if (seenTs == null) return rows.length
    let n = 0
    for (const r of rows) {
      if (r?.ts != null && r.ts > seenTs) n += 1
      else break
    }
    return n
  }, [rows, seenTs])

  const total = filtered.length
  const win = useMemo(
    () => computeWindow({ scrollTop, rowHeight, viewportHeight, overscan, total }),
    [scrollTop, rowHeight, viewportHeight, overscan, total],
  )
  const visible = useMemo(
    () => filtered.slice(win.start, win.end).map((row, i) => ({ row, index: win.start + i })),
    [filtered, win.start, win.end],
  )

  const markSeen = useCallback(() => {
    setSeenTs(rows[0]?.ts ?? null)
  }, [rows])

  const toggle = useCallback(() => {
    const opening = !expanded
    setExpanded(opening)
    // Opening the drawer acknowledges everything currently at the head.
    if (opening) setSeenTs(rows[0]?.ts ?? null)
  }, [expanded, rows])

  const setFilter = useCallback((key) => {
    setFilterState(key)
    // Switching chips resets the scroll window to the top of the new list.
    setScrollTop(0)
  }, [])

  const onScroll = useCallback((event) => {
    setScrollTop(event?.target?.scrollTop ?? 0)
  }, [])

  return {
    filter,
    setFilter,
    filters: ACTIVITY_FILTERS,
    expanded,
    setExpanded,
    toggle,
    filtered,
    latest,
    newCount,
    markSeen,
    visible,
    onScroll,
    windowStart: win.start,
    windowEnd: win.end,
    maxWindow: win.windowNodes,
    totalHeight: total * rowHeight,
    offsetTop: win.start * rowHeight,
    rowHeight,
    viewportHeight,
  }
}

export default useActivityFeed
