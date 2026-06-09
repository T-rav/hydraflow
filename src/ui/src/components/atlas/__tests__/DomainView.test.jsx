import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { ctx, fetchWithRepo } = vi.hoisted(() => {
  const ctx = { selectedRepoSlug: null }
  const fetchWithRepo = (url, opts) => {
    const sep = url.includes('?') ? '&' : '?'
    const scoped = ctx.selectedRepoSlug
      ? `${url}${sep}repo=${encodeURIComponent(ctx.selectedRepoSlug)}`
      : url
    return global.fetch(scoped, opts)
  }
  return { ctx, fetchWithRepo }
})
vi.mock('../../../context/HydraFlowContext', () => ({
  useHydraFlow: () => ({ selectedRepoSlug: ctx.selectedRepoSlug, fetchWithRepo }),
}))
import { DomainView } from '../DomainView'

const SAMPLE_GRAPH = {
  nodes: [
    {
      id: 'n1',
      name: 'AgentRunner',
      kind: 'runner',
      confidence: 'accepted',
      parent: 'builder',
      code_anchor: 'src/agent.py:AgentRunner',
    },
    {
      id: 'n2',
      name: 'EventBus',
      kind: 'service',
      confidence: 'accepted',
      parent: 'shared-kernel',
      code_anchor: 'src/events.py:EventBus',
    },
  ],
  edges: [{ source: 'n1', target: 'n2', kind: 'depends_on' }],
  contexts: [
    { id: 'builder', label: 'builder' },
    { id: 'shared-kernel', label: 'shared-kernel' },
  ],
}

beforeEach(() => {
  ctx.selectedRepoSlug = null
  // ResizeObserver is required by React Flow but not present in jsdom
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(SAMPLE_GRAPH) }),
  )
})

describe('DomainView', () => {
  it('renders the canvas wrapper after fetch', async () => {
    render(<DomainView selectedNodeId={null} onSelectNode={() => {}} />)
    await waitFor(() => {
      expect(screen.getByTestId('atlas-domain-view')).toBeInTheDocument()
    })
  })

  it('scopes the graph + discovered fetches to the selected repo', async () => {
    ctx.selectedRepoSlug = 'org-x'
    render(<DomainView selectedNodeId={null} onSelectNode={() => {}} />)
    await waitFor(() => {
      const urls = global.fetch.mock.calls.map((c) => c[0])
      // The graph URL already has `?` → the repo param appends with `&`.
      expect(urls).toContain('/api/atlas/graph?include_entries=true&repo=org-x')
      expect(urls).toContain('/api/atlas/discovered?repo=org-x')
    })
  })

  it('shows an error state when the fetch fails', async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 500 }))
    render(<DomainView selectedNodeId={null} onSelectNode={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText(/unable to load/i)).toBeInTheDocument()
    })
  })

  it('shows a loading state before fetch resolves', () => {
    let resolveFetch
    global.fetch = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve
        }),
    )
    render(<DomainView selectedNodeId={null} onSelectNode={() => {}} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    resolveFetch({ ok: true, json: () => Promise.resolve(SAMPLE_GRAPH) })
  })

  it('renders without crashing when graph payload is malformed (empty object)', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    )
    render(<DomainView selectedNodeId={null} onSelectNode={() => {}} />)
    await waitFor(() => {
      expect(screen.getByTestId('atlas-domain-view')).toBeInTheDocument()
    })
  })
})
