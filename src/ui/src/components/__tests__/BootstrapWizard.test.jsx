import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { BootstrapWizard } = await import('../BootstrapWizard')

function makeContext(overrides = {}) {
  return {
    createOnboardingDraft: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        events: [{ level: 'info', message: 'draft created' }],
      },
    }),
    materializeOnboardingDraft: vi.fn().mockResolvedValue({
      ok: true,
      draft: {
        id: 'draft-1',
        spec: { name: 'finance-tool' },
        events: [{ level: 'info', message: 'materialized invariant kernel' }],
      },
      materialized: { path: '/tmp/finance-tool' },
    }),
    selectRepo: vi.fn(),
    ...overrides,
  }
}

describe('BootstrapWizard', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(makeContext())
  })

  it('does not render when closed', () => {
    const { container } = render(<BootstrapWizard isOpen={false} onClose={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('creates a draft before entering the spec step', async () => {
    const createOnboardingDraft = vi.fn().mockResolvedValue({
      ok: true,
      draft: { id: 'draft-2', spec: { name: 'new-project' }, events: [] },
    })
    mockUseHydraFlow.mockReturnValue(makeContext({ createOnboardingDraft }))

    render(<BootstrapWizard isOpen onClose={() => {}} />)
    fireEvent.click(screen.getByText('Next'))

    await waitFor(() => expect(createOnboardingDraft).toHaveBeenCalled())
    expect(screen.getByText(/"name": "new-project"/)).toBeInTheDocument()
  })

  it('materializes the active draft and selects the generated repo', async () => {
    const materializeOnboardingDraft = vi.fn().mockResolvedValue({
      ok: true,
      draft: { id: 'draft-1', spec: { name: 'finance-tool' }, events: [] },
    })
    const selectRepo = vi.fn()
    const onClose = vi.fn()
    mockUseHydraFlow.mockReturnValue(makeContext({ materializeOnboardingDraft, selectRepo }))

    render(<BootstrapWizard isOpen onClose={onClose} />)
    fireEvent.click(screen.getByText('Next'))
    await screen.findByText(/"name": "new-project"/)
    fireEvent.click(screen.getByText('Next'))
    fireEvent.click(screen.getByText('Next'))
    fireEvent.click(screen.getByTestId('materialize-project'))

    await waitFor(() => expect(materializeOnboardingDraft).toHaveBeenCalledWith('draft-1', { output_dir: null }))
    expect(selectRepo).toHaveBeenCalledWith('finance-tool')
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps the wizard open and expands activity on materialize failure', async () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      materializeOnboardingDraft: vi.fn().mockResolvedValue({
        ok: false,
        error: 'Draft could not be materialized',
        draft: {
          id: 'draft-1',
          spec: { name: 'new-project' },
          events: [{ level: 'error', message: 'target directory already exists' }],
        },
      }),
    }))

    render(<BootstrapWizard isOpen onClose={() => {}} />)
    fireEvent.click(screen.getByText('Next'))
    await screen.findByText(/"name": "new-project"/)
    fireEvent.click(screen.getByText('Next'))
    fireEvent.click(screen.getByText('Next'))
    fireEvent.click(screen.getByTestId('materialize-project'))

    await screen.findByText('Draft could not be materialized')
    expect(screen.getByTestId('wizard-activity-log')).toHaveTextContent('target directory already exists')
  })
})
