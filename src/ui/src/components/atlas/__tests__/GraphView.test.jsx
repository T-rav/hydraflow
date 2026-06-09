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
import { GraphView } from '../GraphView'

const SAMPLE_GRAPH = {
  nodes: [
    {
      id: 'n1',
      type: 'term',
      name: 'AgentRunner',
      kind: 'runner',
      confidence: 'accepted',
      parent: 'builder',
    },
    {
      id: 'n2',
      type: 'term',
      name: 'EventBus',
      kind: 'service',
      confidence: 'accepted',
      parent: 'shared-kernel',
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
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(SAMPLE_GRAPH) }),
  )
})

describe('GraphView', () => {
  it('scopes the graph + discovered fetches to the selected repo', async () => {
    ctx.selectedRepoSlug = 'org-x'
    render(<GraphView selectedNodeId={null} onSelectNode={() => {}} filters={{}} />)
    await waitFor(() => {
      const urls = global.fetch.mock.calls.map((c) => c[0])
      expect(urls).toContain('/api/atlas/graph?include_entries=true&repo=org-x')
      expect(urls).toContain('/api/atlas/discovered?repo=org-x')
    })
  })

  it('renders the canvas wrapper after fetch', async () => {
    render(<GraphView selectedNodeId={null} onSelectNode={() => {}} filters={{}} />)
    await waitFor(() => {
      expect(screen.getByTestId('atlas-graph-view')).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 500 }))
    render(<GraphView selectedNodeId={null} onSelectNode={() => {}} filters={{}} />)
    await waitFor(() => {
      expect(screen.getByText(/unable to load/i)).toBeInTheDocument()
    })
  })
})
