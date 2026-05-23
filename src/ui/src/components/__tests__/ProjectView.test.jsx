import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { ProjectView } = await import('../ProjectView')

describe('ProjectView', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue({
      pushOnboardingDraft: vi.fn().mockResolvedValue({ ok: false, error: 'Push failed (404)' }),
    })
  })

  it('renders nothing for non-local projects', () => {
    const { container } = render(<ProjectView project={{ slug: 'acme/app' }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows local-only state and disabled push action', () => {
    render(<ProjectView project={{
      slug: 'finance-tool',
      full_name: 'finance-tool',
      path: '/tmp/finance-tool',
      local_only: true,
      onboarding_draft_id: 'draft-1',
      onboarding_events: [{ level: 'info', message: 'materialized invariant kernel' }],
    }} />)

    expect(screen.getByText('local only')).toBeInTheDocument()
    expect(screen.getByText('Ready locally')).toBeInTheDocument()
    expect(screen.getByText('Push to GitHub')).not.toBeDisabled()
    fireEvent.click(screen.getByText('Activity down'))
    expect(screen.getByTestId('project-activity-log')).toHaveTextContent('materialized invariant kernel')
  })

  it('calls the push endpoint and shows failure state', async () => {
    const pushOnboardingDraft = vi.fn().mockResolvedValue({ ok: false, error: 'Push endpoint unavailable' })
    mockUseHydraFlow.mockReturnValue({ pushOnboardingDraft })

    render(<ProjectView project={{
      slug: 'finance-tool',
      local_only: true,
      onboarding_draft_id: 'draft-1',
      onboarding_events: [],
    }} />)

    fireEvent.click(screen.getByText('Push to GitHub'))
    await waitFor(() => expect(pushOnboardingDraft).toHaveBeenCalledWith('draft-1'))
    expect(screen.getByText('Push failed')).toBeInTheDocument()
    expect(screen.getByText('Push endpoint unavailable')).toBeInTheDocument()
  })
})
