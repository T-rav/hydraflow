import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// `ctx.selectedRepoSlug` is mutable per-test; `fetchWithRepo` is a STABLE
// hoisted ref (like the real useCallback-memoized fetcher) so the polling
// effect that depends on it does not re-render-loop. It mirrors applyRepoParam
// and delegates to the per-test `global.fetch` stub.
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

import { MaintenanceView } from '../MaintenanceView'

const STATUS = {
  open_pr_url: 'https://github.com/acme/widget/pull/9012',
  open_pr_branch: 'wiki/foo',
  queue_depth: 3,
  queue_path: '/tmp/q',
  interval_seconds: 3600,
  auto_merge: false,
  coalesce: true,
}
const HEALTH = { store: 'populated', repos: 7, tribal: 'populated' }

beforeEach(() => {
  ctx.selectedRepoSlug = null
  global.fetch = vi.fn((url, opts) => {
    if (url === '/api/wiki/maintenance/status')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(STATUS) })
    if (url === '/api/wiki/health')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(HEALTH) })
    if (url.startsWith('/api/wiki/admin/') && opts && opts.method === 'POST')
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: 'queued' }),
      })
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
  })
})

describe('MaintenanceView', () => {
  it('renders run-status card with queue depth and interval', async () => {
    render(<MaintenanceView />)
    await waitFor(() => expect(screen.getByText('3')).toBeInTheDocument())
    expect(screen.getByText(/3600s/)).toBeInTheDocument()
  })

  it('renders the open-PR link when present', async () => {
    render(<MaintenanceView />)
    await waitFor(() => screen.getByRole('link'))
    const link = screen.getByRole('link')
    expect(link.getAttribute('href')).toBe(STATUS.open_pr_url)
  })

  it('renders health card with store + tribal status', async () => {
    render(<MaintenanceView />)
    await waitFor(() => screen.getAllByText(/populated/i).length > 0)
    expect(screen.getByText(/7 repos/i)).toBeInTheDocument()
  })

  it('posts to /api/wiki/admin/run-now when Run now is clicked', async () => {
    render(<MaintenanceView />)
    await waitFor(() => screen.getByRole('button', { name: /run now/i }))
    fireEvent.click(screen.getByRole('button', { name: /run now/i }))
    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((c) => c[0])
      expect(calls).toContain('/api/wiki/admin/run-now')
    })
  })

  it('scopes the maintenance fetch to the selected repo', async () => {
    ctx.selectedRepoSlug = 'org-x'
    render(<MaintenanceView />)
    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((c) => c[0])
      expect(calls).toContain('/api/wiki/maintenance/status?repo=org-x')
      expect(calls).toContain('/api/wiki/health?repo=org-x')
      expect(calls).toContain('/api/atlas/term-loops/status?repo=org-x')
    })
  })

  it('disables admin actions and fires no POST under "All repos"', async () => {
    ctx.selectedRepoSlug = '__all__'
    render(<MaintenanceView />)
    const runNow = await screen.findByRole('button', { name: /run now/i })
    expect(runNow).toBeDisabled()
    fireEvent.click(runNow)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /force compile/i })).toBeDisabled()
    })
    const posts = global.fetch.mock.calls.filter(
      (c) => c[1] && c[1].method === 'POST',
    )
    expect(posts).toHaveLength(0)
  })

  it('renders per-repo term-loop groups for the __all__ nested shape', async () => {
    ctx.selectedRepoSlug = '__all__'
    const NESTED = {
      repos: [
        { repo: 'org-a', loops: { term_proposer: { status: 'ok' } } },
        { repo: 'org-b', loops: { term_proposer: { status: 'idle' } } },
      ],
    }
    global.fetch = vi.fn((url) =>
      url.includes('/api/atlas/term-loops/status')
        ? Promise.resolve({ ok: true, json: () => Promise.resolve(NESTED) })
        : Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    )
    render(<MaintenanceView />)
    await waitFor(() => {
      expect(screen.getByTestId('term-loops-repo-org-a')).toBeInTheDocument()
      expect(screen.getByTestId('term-loops-repo-org-b')).toBeInTheDocument()
    })
  })
})
