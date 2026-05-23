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

  it('renders nothing when no project is selected', () => {
    const { container } = render(<ProjectView project={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows factory repo plan progress for selected repos', () => {
    render(<ProjectView project={{
      slug: 'acme/app',
      full_name: 'acme/app',
      current_plan: 'Plan 02',
      plan_progress: { completed: 3, total: 8 },
      running: true,
    }} />)

    expect(screen.getByTestId('project-view')).toHaveTextContent('selected repo')
    expect(screen.getByText('Plan 02')).toBeInTheDocument()
    expect(screen.getByText('3/8 issues complete')).toBeInTheDocument()
    expect(screen.getByText('Factory pipeline active')).toBeInTheDocument()
  })

  it('shows local-only state and disabled push action', () => {
    render(<ProjectView project={{
      slug: 'finance-tool',
      full_name: 'finance-tool',
      path: '/tmp/finance-tool',
      local_only: true,
      onboarding_draft_id: 'draft-1',
      onboarding_plan_draft: ['Create invariant kernel', 'Build UI scaffold'],
      onboarding_events: [{ level: 'info', message: 'materialized invariant kernel' }],
    }} />)

    expect(screen.getByText('local only')).toBeInTheDocument()
    expect(screen.getByText('Ready locally')).toBeInTheDocument()
    expect(screen.getByText('0/2 issues complete')).toBeInTheDocument()
    expect(screen.getByText('Push to GitHub')).not.toBeDisabled()
    fireEvent.click(screen.getByText('Activity down'))
    expect(screen.getByTestId('project-activity-log')).toHaveTextContent('materialized invariant kernel')
  })

  it('surfaces next-plan and upgrade affordances from project metadata', () => {
    render(<ProjectView project={{
      slug: 'acme/app',
      current_plan: 'Plan 01',
      plan_progress: { completed: 4, total: 4 },
      upgrade_available: true,
    }} />)

    expect(screen.getByText('Continue to next plan')).toBeInTheDocument()
    expect(screen.getByText('Upgrade format')).toBeInTheDocument()
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
