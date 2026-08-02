import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// WorkflowConfigPanel (#10786) reads the settings schema (now carrying a
// server-derived `section`) and renders the fields grouped by section, editable
// one field at a time via PATCH /api/control/config. These tests pin the WIRING
// (grouping, edit → save PATCH, validation, live/restart, error, aggregate).

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { WorkflowConfigPanel } = await import('../WorkflowConfigPanel')

const SCHEMA = {
  settings: [
    {
      name: 'queue_strategy', group: 'Work Queue', section: 'Work Queue',
      live: true, type: 'enum', description: 'How the work picker orders issues',
      default: 'weighted_mix', value: 'weighted_mix', min: null, max: null,
      choices: ['fifo', 'priority', 'weighted_mix'],
    },
    {
      name: 'max_workers', group: 'Concurrency', section: 'Workers & Batch',
      live: true, type: 'int', description: 'Concurrent implement workers',
      default: 1, value: 2, min: 1, max: 10, choices: null,
    },
    {
      name: 'staging_enabled', group: 'Branching & Release', section: 'Merge & Release',
      live: false, type: 'bool', description: 'Two-tier branch model master switch',
      default: false, value: false, min: null, max: null, choices: null,
    },
    {
      name: 'merge_policy_enabled', group: 'Reliability', section: 'Safety & Reliability',
      live: true, type: 'bool', description: 'Merge-policy gate', default: true,
      value: true, min: null, max: null, choices: null,
    },
  ],
  provider_keys: {},
}

function makeFetch({ schema = SCHEMA, schemaOk = true, patchOk = true, patchMessage = 'out of bounds' } = {}) {
  return vi.fn(async (url) => {
    if (String(url).includes('settings-schema')) {
      return { ok: schemaOk, json: async () => schema }
    }
    return {
      ok: patchOk,
      json: async () => (patchOk ? { status: 'ok' } : { message: patchMessage }),
    }
  })
}

function mockContext(overrides = {}) {
  mockUseHydraFlow.mockReturnValue({
    selectedRepoSlug: 'org/repo',
    fetchWithRepo: makeFetch(),
    ...overrides,
  })
}

beforeEach(() => {
  mockUseHydraFlow.mockReset()
})

describe('WorkflowConfigPanel', () => {
  it('renders sections in display order with a control per field by type', async () => {
    mockContext()
    render(<WorkflowConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('workflow-config-panel')).toBeInTheDocument())

    // Section headings rendered, ordered by SECTION_ORDER.
    const headings = ['Work Queue', 'Workers & Batch', 'Merge & Release', 'Safety & Reliability']
    for (const h of headings) expect(screen.getByText(h)).toBeInTheDocument()

    // enum → select with all choices
    const queue = screen.getByTestId('wf-input-queue_strategy')
    expect(queue.tagName).toBe('SELECT')
    expect(queue.querySelectorAll('option')).toHaveLength(3)
    // int → number input with current value + bounds
    const mw = screen.getByTestId('wf-input-max_workers')
    expect(mw.type).toBe('number')
    expect(mw.value).toBe('2')
    expect(mw.min).toBe('1')
    // bool → checkbox
    expect(screen.getByTestId('wf-input-staging_enabled').type).toBe('checkbox')
  })

  it('places each field under its server-derived section', async () => {
    mockContext()
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('wf-section-workers-batch')).toBeInTheDocument())

    const workers = screen.getByTestId('wf-section-workers-batch')
    expect(workers).toContainElement(screen.getByTestId('wf-field-max_workers'))
    const safety = screen.getByTestId('wf-section-safety-reliability')
    expect(safety).toContainElement(screen.getByTestId('wf-field-merge_policy_enabled'))
  })

  it('shows live vs restart badges from the schema flag', async () => {
    mockContext()
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('wf-badge-max_workers')).toBeInTheDocument())
    expect(screen.getByTestId('wf-badge-max_workers').textContent).toContain('live')
    expect(screen.getByTestId('wf-badge-staging_enabled').textContent).toContain('restart')
  })

  it('edits a field and saves only that field via PATCH with persist', async () => {
    const fetchWithRepo = makeFetch()
    mockContext({ fetchWithRepo })
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('wf-input-max_workers')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('wf-input-max_workers'), { target: { value: '5' } })
    fireEvent.click(screen.getByTestId('wf-save-max_workers'))

    await waitFor(() => {
      const patch = fetchWithRepo.mock.calls.find(([, opts]) => opts && opts.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect(JSON.parse(patch[1].body)).toEqual({ max_workers: 5, persist: true })
    })
    await waitFor(() => expect(screen.getByTestId('wf-saved-max_workers').textContent).toContain('saved'))
  })

  it('shows the restart-to-apply notice after saving a restart-required field', async () => {
    mockContext()
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('wf-input-staging_enabled')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('wf-input-staging_enabled'))
    fireEvent.click(screen.getByTestId('wf-save-staging_enabled'))

    await waitFor(() =>
      expect(screen.getByTestId('wf-saved-staging_enabled').textContent).toContain('restart'),
    )
  })

  it('validates bounds and blocks save while out of range', async () => {
    mockContext()
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('wf-input-max_workers')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('wf-input-max_workers'), { target: { value: '99' } })
    expect(screen.queryByTestId('wf-save-max_workers')).not.toBeInTheDocument()
    expect(screen.getByTestId('wf-fielderror-max_workers').textContent).toContain('max 10')
  })

  it('surfaces the response message when PATCH is rejected', async () => {
    mockContext({ fetchWithRepo: makeFetch({ patchOk: false, patchMessage: 'process-global; cannot set per-repo' }) })
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('wf-input-max_workers')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('wf-input-max_workers'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('wf-save-max_workers'))

    await waitFor(() =>
      expect(screen.getByTestId('wf-saved-max_workers').textContent).toContain('process-global'),
    )
  })

  it('disables editing and notes why in the aggregate (all-repos) view', async () => {
    mockContext({ selectedRepoSlug: '__all__' })
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('workflow-aggregate-note')).toBeInTheDocument())
    expect(screen.getByTestId('wf-input-max_workers')).toBeDisabled()
  })

  it('renders an error state (not a blank panel) when the schema fetch fails', async () => {
    mockContext({ fetchWithRepo: makeFetch({ schemaOk: false }) })
    render(<WorkflowConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('workflow-config-error')).toBeInTheDocument())
    expect(screen.queryByTestId('workflow-config-panel')).not.toBeInTheDocument()
  })
})
