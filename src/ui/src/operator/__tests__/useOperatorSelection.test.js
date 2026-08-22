import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useOperatorSelection, readSelectionFromUrl } from '../useOperatorSelection'

// The operator console is URL-addressable (spec §3): `?repo=&stage=&item=&mode=`,
// extending App's existing `_initialTabFromUrl` read pattern. These tests pin the
// two-way contract: selection <-> URL query.

function setUrl(search) {
  window.history.replaceState({}, '', search ? `/?${search}` : '/')
}

describe('readSelectionFromUrl — pure URL parse', () => {
  it('returns an empty selection (mode defaults to focus) for a bare URL', () => {
    expect(readSelectionFromUrl('')).toEqual({
      repo: null,
      stage: null,
      item: null,
      mode: 'focus',
      routingView: 'accounts',
    })
  })

  it('restores every selection level from a fully-qualified query', () => {
    const sel = readSelectionFromUrl('repo=acme%2Fweb&stage=plan&item=42&mode=all-active')
    expect(sel).toEqual({
      repo: 'acme/web',
      stage: 'plan',
      item: '42',
      mode: 'all-active',
      routingView: 'accounts',
    })
  })

  it('coerces an unknown mode back to the focus default', () => {
    expect(readSelectionFromUrl('mode=bogus').mode).toBe('focus')
  })

  it('accepts mode=supervisor (#11207)', () => {
    expect(readSelectionFromUrl('mode=supervisor').mode).toBe('supervisor')
  })

  it('accepts mode=routing (#11534)', () => {
    expect(readSelectionFromUrl('mode=routing').mode).toBe('routing')
  })

  it('restores the routing sub-view from the query', () => {
    expect(readSelectionFromUrl('mode=routing&routingView=live').routingView).toBe('live')
  })

  it('coerces an unimplemented routing sub-view back to accounts', () => {
    // `policies` is reserved by the routing-control-plane design for a later
    // phase; until it exists the URL must not select an empty workspace.
    expect(readSelectionFromUrl('routingView=policies').routingView).toBe('accounts')
  })
})

describe('useOperatorSelection', () => {
  let originalHref

  beforeEach(() => {
    originalHref = window.location.href
    setUrl('')
  })

  afterEach(() => {
    window.history.replaceState({}, '', originalHref)
  })

  it('initialises an empty selection from a bare URL', () => {
    const { result } = renderHook(() => useOperatorSelection())
    expect(result.current.repo).toBeNull()
    expect(result.current.stage).toBeNull()
    expect(result.current.item).toBeNull()
    expect(result.current.mode).toBe('focus')
  })

  it('restores selection depth (repo/stage/item/mode) from the URL on init', () => {
    setUrl('repo=acme%2Fweb&stage=plan&item=42&mode=all-active')
    const { result } = renderHook(() => useOperatorSelection())
    expect(result.current.repo).toBe('acme/web')
    expect(result.current.stage).toBe('plan')
    expect(result.current.item).toBe('42')
    expect(result.current.mode).toBe('all-active')
  })

  it('selecting a stage updates state AND the URL query', () => {
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('stage', 'plan'))
    expect(result.current.stage).toBe('plan')
    expect(new URLSearchParams(window.location.search).get('stage')).toBe('plan')
  })

  it('selecting an item updates state AND the URL query', () => {
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('item', 42))
    expect(result.current.item).toBe('42')
    expect(new URLSearchParams(window.location.search).get('item')).toBe('42')
  })

  it('selecting a repo clears any deeper stage/item selection', () => {
    setUrl('repo=old&stage=plan&item=42')
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('repo', 'acme/web'))
    expect(result.current.repo).toBe('acme/web')
    expect(result.current.stage).toBeNull()
    expect(result.current.item).toBeNull()
    const params = new URLSearchParams(window.location.search)
    expect(params.get('repo')).toBe('acme/web')
    expect(params.get('stage')).toBeNull()
    expect(params.get('item')).toBeNull()
  })

  it('selecting a stage clears the deeper item selection', () => {
    setUrl('repo=acme%2Fweb&stage=plan&item=42')
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('stage', 'review'))
    expect(result.current.stage).toBe('review')
    expect(result.current.item).toBeNull()
  })

  it('selecting a level with a null value pops that level and everything deeper', () => {
    setUrl('repo=acme%2Fweb&stage=plan&item=42')
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('stage', null))
    expect(result.current.stage).toBeNull()
    expect(result.current.item).toBeNull()
    expect(result.current.repo).toBe('acme/web')
    expect(new URLSearchParams(window.location.search).get('stage')).toBeNull()
  })

  it('mode round-trips through the URL (all-active written, focus cleared)', () => {
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('mode', 'all-active'))
    expect(result.current.mode).toBe('all-active')
    expect(new URLSearchParams(window.location.search).get('mode')).toBe('all-active')
    act(() => result.current.select('mode', 'focus'))
    expect(result.current.mode).toBe('focus')
    expect(new URLSearchParams(window.location.search).get('mode')).toBeNull()
  })

  it('?mode=supervisor round-trips through the URL (#11207)', () => {
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('mode', 'supervisor'))
    expect(result.current.mode).toBe('supervisor')
    expect(new URLSearchParams(window.location.search).get('mode')).toBe('supervisor')

    setUrl('mode=supervisor')
    const restored = renderHook(() => useOperatorSelection())
    expect(restored.result.current.mode).toBe('supervisor')
  })

  it('preserves unrelated query params (e.g. ?tab) when writing selection', () => {
    setUrl('tab=system')
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('stage', 'plan'))
    const params = new URLSearchParams(window.location.search)
    expect(params.get('tab')).toBe('system')
    expect(params.get('stage')).toBe('plan')
  })

  it('breadcrumb starts at the root ("All repos") with no selection', () => {
    const { result } = renderHook(() => useOperatorSelection())
    expect(result.current.breadcrumb).toHaveLength(1)
    expect(result.current.breadcrumb[0]).toMatchObject({ kind: 'repo', value: null })
    expect(result.current.breadcrumb[0].label).toMatch(/all repos/i)
  })

  it('breadcrumb array grows with selection depth (repo -> stage -> item)', () => {
    setUrl('repo=acme%2Fweb&stage=plan&item=42')
    const { result } = renderHook(() => useOperatorSelection())
    const crumbs = result.current.breadcrumb
    expect(crumbs).toHaveLength(4) // root, repo, stage, item
    expect(crumbs.map(c => c.kind)).toEqual(['repo', 'repo', 'stage', 'item'])
    expect(crumbs[1].value).toBe('acme/web')
    expect(crumbs[2].value).toBe('plan')
    expect(crumbs[2].label).toBe('Plan') // human stage label from OPERATOR_STAGES
    expect(crumbs[3].value).toBe('42')
    expect(crumbs[3].label).toBe('#42')
  })

  it('breadcrumb shrinks after popping a level', () => {
    setUrl('repo=acme%2Fweb&stage=plan&item=42')
    const { result } = renderHook(() => useOperatorSelection())
    expect(result.current.breadcrumb).toHaveLength(4)
    act(() => result.current.select('repo', null))
    expect(result.current.breadcrumb).toHaveLength(1)
  })
})

describe('routing sub-view selection (#11534)', () => {
  let originalHref

  beforeEach(() => {
    originalHref = window.location.href
    setUrl('')
  })

  afterEach(() => {
    window.history.replaceState({}, '', originalHref)
  })

  it('defaults to the accounts view', () => {
    const { result } = renderHook(() => useOperatorSelection())
    expect(result.current.routingView).toBe('accounts')
  })

  it('mirrors a selected sub-view into the URL', () => {
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('routingView', 'live'))
    expect(new URLSearchParams(window.location.search).get('routingView')).toBe('live')
  })

  it('omits the default sub-view from the URL', () => {
    setUrl('routingView=live')
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('routingView', 'accounts'))
    expect(new URLSearchParams(window.location.search).get('routingView')).toBeNull()
  })

  it('does not clear the drill-down when the sub-view changes', () => {
    setUrl('repo=acme%2Fweb&stage=plan&item=42')
    const { result } = renderHook(() => useOperatorSelection())
    act(() => result.current.select('routingView', 'live'))
    expect(result.current.item).toBe('42')
  })
})
