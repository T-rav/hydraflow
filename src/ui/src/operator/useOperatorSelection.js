/**
 * Operator-console selection hook (epic #10556, Task 2).
 *
 * The operator console is URL-addressable (spec §3): the current selection is
 * mirrored into the query string `?repo=&stage=&item=&mode=` so a view is
 * shareable and survives reload. This extends App.jsx's existing
 * `_initialTabFromUrl` read pattern (read from `new URLSearchParams(
 * window.location.search)`) with a write path via `window.history.replaceState`
 * — a non-navigating URL update that keeps unrelated params (e.g. `?tab`)
 * intact and does not spam the back/forward history.
 *
 * Public shape (Task 2 interface):
 *   useOperatorSelection() -> {
 *     repo, stage, item, mode,     // current selection (strings | null)
 *     select(kind, value),         // kind ∈ 'repo'|'stage'|'item'|'mode'
 *     breadcrumb,                  // [{ kind, label, value }], root-first
 *   }
 *
 * Selection is a strict drill-down hierarchy: repo → stage → item. Choosing a
 * shallower level clears everything deeper (picking a new repo drops the stage
 * and item; picking a stage drops the item). Passing `null` pops that level and
 * everything below it — which is exactly what a breadcrumb "jump up" needs.
 * `mode` (focus | all-active | instruments) is orthogonal to depth and never cleared by drill.
 */

import { useCallback, useMemo, useState } from 'react'
import { OPERATOR_STAGES } from './model/pipeline'

const DEFAULT_MODE = 'focus'
const VALID_MODES = new Set([DEFAULT_MODE, 'all-active', 'instruments'])

/** Human label for a stage key, falling back to the raw key. */
function stageLabel(key) {
  const match = OPERATOR_STAGES.find(s => s.key === key)
  return match ? match.label : key
}

/** Normalise a raw query value: treat empty string as absent. */
function cleanParam(value) {
  if (value == null) return null
  const trimmed = String(value).trim()
  return trimmed === '' ? null : trimmed
}

/**
 * Pure parse of a query string into a selection object. Exported so callers
 * (and tests) can derive a selection without a React render, and so the hook's
 * lazy initialiser can reuse it. `search` defaults to the live location.
 * @param {string} [search] - query string, with or without a leading '?'
 * @returns {{ repo: string|null, stage: string|null, item: string|null, mode: string }}
 */
export function readSelectionFromUrl(search) {
  const source =
    search != null
      ? search
      : typeof window !== 'undefined'
        ? window.location.search
        : ''
  const params = new URLSearchParams(source)
  const rawMode = cleanParam(params.get('mode'))
  return {
    repo: cleanParam(params.get('repo')),
    stage: cleanParam(params.get('stage')),
    item: cleanParam(params.get('item')),
    mode: rawMode && VALID_MODES.has(rawMode) ? rawMode : DEFAULT_MODE,
  }
}

/** Set a query param when the value is present, delete it when null. */
function setOrDelete(params, key, value) {
  if (value == null || value === '') params.delete(key)
  else params.set(key, String(value))
}

/**
 * Mirror a selection into the URL query without navigating, preserving any
 * unrelated params already on the URL. `mode` is only written when non-default
 * so a plain view stays a clean URL.
 */
function writeSelectionToUrl(selection) {
  if (typeof window === 'undefined' || !window.history?.replaceState) return
  const params = new URLSearchParams(window.location.search)
  setOrDelete(params, 'repo', selection.repo)
  setOrDelete(params, 'stage', selection.stage)
  setOrDelete(params, 'item', selection.item)
  setOrDelete(params, 'mode', selection.mode === DEFAULT_MODE ? null : selection.mode)
  const qs = params.toString()
  const next = `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`
  window.history.replaceState(window.history.state, '', next)
}

/** Apply a single `select(kind, value)` to the previous selection, enforcing
 * the drill-down hierarchy. Returns a new selection object. */
export function applySelect(prev, kind, value) {
  const v = value === '' || value === undefined ? null : value
  switch (kind) {
    case 'repo':
      // New repo (or clearing it) resets the drill-down beneath it.
      return { ...prev, repo: v == null ? null : String(v), stage: null, item: null }
    case 'stage':
      return { ...prev, stage: v == null ? null : String(v), item: null }
    case 'item':
      return { ...prev, item: v == null ? null : String(v) }
    case 'mode':
      return { ...prev, mode: v && VALID_MODES.has(v) ? v : DEFAULT_MODE }
    default:
      return prev
  }
}

/** Build the root-first breadcrumb from a selection. Each entry carries the
 * `select` args needed to jump back to that depth. */
export function buildBreadcrumb(selection) {
  const crumbs = [{ kind: 'repo', label: 'All repos', value: null }]
  if (selection.repo) crumbs.push({ kind: 'repo', label: selection.repo, value: selection.repo })
  if (selection.stage) crumbs.push({ kind: 'stage', label: stageLabel(selection.stage), value: selection.stage })
  if (selection.item) crumbs.push({ kind: 'item', label: `#${selection.item}`, value: selection.item })
  return crumbs
}

/**
 * React hook: current operator-console selection, two-way bound to the URL.
 */
export function useOperatorSelection() {
  const [selection, setSelection] = useState(readSelectionFromUrl)

  const select = useCallback((kind, value) => {
    setSelection(prev => {
      const next = applySelect(prev, kind, value)
      writeSelectionToUrl(next)
      return next
    })
  }, [])

  const breadcrumb = useMemo(() => buildBreadcrumb(selection), [selection])

  return {
    repo: selection.repo,
    stage: selection.stage,
    item: selection.item,
    mode: selection.mode,
    select,
    breadcrumb,
  }
}
