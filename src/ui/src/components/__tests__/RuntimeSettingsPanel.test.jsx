import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { RuntimeSettingsPanel, humanize, providerKeyStatus } = await import('../RuntimeSettingsPanel')

const SCHEMA = {
  settings: [
    {
      name: 'max_workers', group: 'Concurrency', live: true, type: 'int',
      description: 'Concurrent implement workers', default: 1, value: 2,
      min: 1, max: 10, choices: null,
    },
    {
      name: 'staging_enabled', group: 'Branching & Release', live: false,
      type: 'bool', description: 'Master switch', default: false, value: false,
      min: null, max: null, choices: null,
    },
    {
      name: 'review_mode', group: 'Concurrency', live: true, type: 'enum',
      description: 'How review runs', default: 'ci_only', value: 'ci_only',
      min: null, max: null, choices: ['ci_only', 'llm_review'],
    },
  ],
}

const ROUTING_SCHEMA = {
  settings: [
    {
      name: 'openrouter_base_url', group: 'Model Routing', live: true, type: 'str',
      description: 'OpenRouter base URL', default: '', value: 'https://openrouter.ai/api/v1',
      min: null, max: null, choices: null,
    },
    {
      name: 'zai_base_url', group: 'Model Routing', live: true, type: 'str',
      description: 'z.ai base URL', default: '', value: 'https://api.z.ai/api/paas/v4',
      min: null, max: null, choices: null,
    },
    {
      name: 'repo_provider', group: 'Model Routing', live: true, type: 'enum',
      description: 'Repo-wide harness backend override', default: 'claude', value: 'zai',
      min: null, max: null, choices: ['claude', 'zai'],
    },
  ],
  provider_keys: { openrouter: true, zai: false },
}

function makeFetch({ schema = SCHEMA, patchOk = true } = {}) {
  return vi.fn(async (url) => {
    if (String(url).includes('settings-schema')) {
      return { ok: true, json: async () => schema }
    }
    return {
      ok: patchOk,
      json: async () => (patchOk ? { status: 'ok' } : { message: 'out of bounds' }),
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

describe('humanize', () => {
  it('title-cases snake_case field names', () => {
    expect(humanize('max_workers')).toBe('Max Workers')
  })
})

describe('providerKeyStatus', () => {
  const keys = { openrouter: true, zai: false }

  it('maps a <provider>_base_url field to its key presence', () => {
    expect(providerKeyStatus('openrouter_base_url', keys)).toBe(true)
    expect(providerKeyStatus('zai_base_url', keys)).toBe(false)
  })

  it('returns null for a non-base_url field (no badge)', () => {
    expect(providerKeyStatus('max_workers', keys)).toBeNull()
  })

  it('returns null when the provider has no key entry', () => {
    expect(providerKeyStatus('mistral_base_url', keys)).toBeNull()
    expect(providerKeyStatus('zai_base_url', {})).toBeNull()
  })

  it('badges repo_provider with its zai key presence only when "zai" is selected', () => {
    expect(providerKeyStatus('repo_provider', keys, 'zai')).toBe(false)
    expect(providerKeyStatus('repo_provider', keys, 'claude')).toBeNull()
  })
})

describe('RuntimeSettingsPanel', () => {
  it('renders settings grouped, with derived inputs per type', async () => {
    mockContext()
    render(<RuntimeSettingsPanel />)

    await waitFor(() => expect(screen.getByTestId('setting-max_workers')).toBeInTheDocument())
    // Groups
    expect(screen.getByText('Concurrency')).toBeInTheDocument()
    expect(screen.getByText('Branching & Release')).toBeInTheDocument()
    // int → number input with current value + bounds
    const mw = screen.getByTestId('input-max_workers')
    expect(mw.type).toBe('number')
    expect(mw.value).toBe('2')
    expect(mw.min).toBe('1')
    // bool → checkbox
    expect(screen.getByTestId('input-staging_enabled').type).toBe('checkbox')
    // enum → select with choices
    const sel = screen.getByTestId('input-review_mode')
    expect(sel.tagName).toBe('SELECT')
    expect(sel.querySelectorAll('option')).toHaveLength(2)
  })

  it('shows live vs restart badges from the schema flag', async () => {
    mockContext()
    render(<RuntimeSettingsPanel />)
    await waitFor(() => expect(screen.getByTestId('badge-max_workers')).toBeInTheDocument())
    expect(screen.getByTestId('badge-max_workers').textContent).toContain('live')
    expect(screen.getByTestId('badge-staging_enabled').textContent).toContain('restart')
  })

  it('filters by search across name/description/group', async () => {
    mockContext()
    render(<RuntimeSettingsPanel />)
    await waitFor(() => expect(screen.getByTestId('setting-max_workers')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('settings-search'), { target: { value: 'staging' } })
    expect(screen.queryByTestId('setting-max_workers')).not.toBeInTheDocument()
    expect(screen.getByTestId('setting-staging_enabled')).toBeInTheDocument()
  })

  it('edits and saves a field via PATCH with persist', async () => {
    const fetchWithRepo = makeFetch()
    mockContext({ fetchWithRepo })
    render(<RuntimeSettingsPanel />)
    await waitFor(() => expect(screen.getByTestId('input-max_workers')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('input-max_workers'), { target: { value: '5' } })
    fireEvent.click(screen.getByTestId('save-max_workers'))

    await waitFor(() => {
      const patch = fetchWithRepo.mock.calls.find(
        ([url, opts]) => opts && opts.method === 'PATCH',
      )
      expect(patch).toBeTruthy()
      const body = JSON.parse(patch[1].body)
      expect(body).toEqual({ max_workers: 5, persist: true })
    })
    // Live field → "saved"
    await waitFor(() => expect(screen.getByTestId('saved-max_workers').textContent).toContain('saved'))
  })

  it('restart-required field shows the restart-to-apply notice after save', async () => {
    mockContext()
    render(<RuntimeSettingsPanel />)
    await waitFor(() => expect(screen.getByTestId('input-staging_enabled')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('input-staging_enabled'))
    fireEvent.click(screen.getByTestId('save-staging_enabled'))

    await waitFor(() =>
      expect(screen.getByTestId('saved-staging_enabled').textContent).toContain('restart'),
    )
  })

  it('validates bounds and blocks save while out of range', async () => {
    mockContext()
    render(<RuntimeSettingsPanel />)
    await waitFor(() => expect(screen.getByTestId('input-max_workers')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('input-max_workers'), { target: { value: '99' } })
    // over max=10 → no Save button, an inline error instead
    expect(screen.queryByTestId('save-max_workers')).not.toBeInTheDocument()
    expect(screen.getByText(/max 10/)).toBeInTheDocument()
  })

  it('disables editing in the aggregate (all-repos) view', async () => {
    mockContext({ selectedRepoSlug: '__all__' })
    render(<RuntimeSettingsPanel />)
    await waitFor(() => expect(screen.getByTestId('settings-aggregate-note')).toBeInTheDocument())
    expect(screen.getByTestId('input-max_workers')).toBeDisabled()
  })

  it('badges API-key presence on provider base-URL fields', async () => {
    mockContext({ fetchWithRepo: makeFetch({ schema: ROUTING_SCHEMA }) })
    render(<RuntimeSettingsPanel />)
    await waitFor(() =>
      expect(screen.getByTestId('setting-openrouter_base_url')).toBeInTheDocument(),
    )
    // openrouter key present → "detected"; zai key absent → "not set".
    expect(screen.getByTestId('keystatus-openrouter_base_url').textContent).toContain('detected')
    expect(screen.getByTestId('keystatus-zai_base_url').textContent).toContain('not set')
    // repo_provider (#11211) is seeded at "zai" with no zai key → also "not set",
    // so an operator who selects GLM for a repo sees the missing-key warning on
    // the dial itself, not just on the unrelated zai_base_url row.
    expect(screen.getByTestId('keystatus-repo_provider').textContent).toContain('not set')
  })

  it('never renders a key badge on a non-provider field', async () => {
    mockContext()
    render(<RuntimeSettingsPanel />)
    await waitFor(() => expect(screen.getByTestId('setting-max_workers')).toBeInTheDocument())
    expect(screen.queryByTestId('keystatus-max_workers')).not.toBeInTheDocument()
  })
})
