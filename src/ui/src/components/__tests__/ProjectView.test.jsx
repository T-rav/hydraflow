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
      continueOnboardingPlan: vi.fn().mockResolvedValue({ ok: false, error: 'Continue plan failed (404)' }),
      upgradeOnboardingFormat: vi.fn().mockResolvedValue({ ok: false, error: 'Format upgrade failed (404)' }),
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

  it('calls the continue endpoint when a completed onboarding plan has a draft id', async () => {
    const continueOnboardingPlan = vi.fn().mockResolvedValue({ ok: true, plan: 'Plan 02' })
    mockUseHydraFlow.mockReturnValue({ continueOnboardingPlan, pushOnboardingDraft: vi.fn() })

    render(<ProjectView project={{
      slug: 'finance-tool',
      onboarding_draft_id: 'draft-1',
      onboarding_current_plan: 'Plan 01',
      plan_progress: { completed: 2, total: 2 },
    }} />)

    fireEvent.click(screen.getByText('Continue to next plan'))
    await waitFor(() => expect(continueOnboardingPlan).toHaveBeenCalledWith('draft-1', {
      current_plan: 'Plan 01',
    }))
    expect(screen.getByText('Plan continued')).toBeInTheDocument()
  })

  it('shows continue failure state and opens activity', async () => {
    const continueOnboardingPlan = vi.fn().mockResolvedValue({ ok: false, error: 'Issue creation failed' })
    mockUseHydraFlow.mockReturnValue({ continueOnboardingPlan, pushOnboardingDraft: vi.fn() })

    render(<ProjectView project={{
      slug: 'finance-tool',
      onboarding_draft_id: 'draft-1',
      onboarding_current_plan: 'Plan 01',
      plan_progress: { completed: 1, total: 1 },
      onboarding_events: [{ level: 'error', message: 'gh auth failed' }],
    }} />)

    fireEvent.click(screen.getByText('Continue to next plan'))
    await waitFor(() => expect(continueOnboardingPlan).toHaveBeenCalledWith('draft-1', {
      current_plan: 'Plan 01',
    }))
    expect(screen.getByText('Issue creation failed')).toBeInTheDocument()
    expect(screen.getByTestId('project-activity-log')).toHaveTextContent('gh auth failed')
  })

  it('calls the upgrade endpoint when a draft-backed project has upgrade metadata', async () => {
    const upgradeOnboardingFormat = vi.fn().mockResolvedValue({ ok: true, pr_url: 'https://github.com/T-rav/finance-tool/pull/7' })
    mockUseHydraFlow.mockReturnValue({ upgradeOnboardingFormat, continueOnboardingPlan: vi.fn(), pushOnboardingDraft: vi.fn() })

    render(<ProjectView project={{
      slug: 'finance-tool',
      onboarding_draft_id: 'draft-1',
      format_upgrade_available: true,
    }} />)

    fireEvent.click(screen.getByText('Upgrade format'))
    await waitFor(() => expect(upgradeOnboardingFormat).toHaveBeenCalledWith('draft-1'))
    expect(screen.getByText('Upgrade PR opened')).toBeInTheDocument()
  })

  it('shows format upgrade failure state and opens activity', async () => {
    const upgradeOnboardingFormat = vi.fn().mockResolvedValue({ ok: false, error: 'PR create failed' })
    mockUseHydraFlow.mockReturnValue({ upgradeOnboardingFormat, continueOnboardingPlan: vi.fn(), pushOnboardingDraft: vi.fn() })

    render(<ProjectView project={{
      slug: 'finance-tool',
      onboarding_draft_id: 'draft-1',
      upgrade_available: true,
      onboarding_events: [{ level: 'error', message: 'gh pr create failed' }],
    }} />)

    fireEvent.click(screen.getByText('Upgrade format'))
    await waitFor(() => expect(upgradeOnboardingFormat).toHaveBeenCalledWith('draft-1'))
    expect(screen.getByText('PR create failed')).toBeInTheDocument()
    expect(screen.getByTestId('project-activity-log')).toHaveTextContent('gh pr create failed')
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

  it('shows pushed state after push succeeds', async () => {
    const pushOnboardingDraft = vi.fn().mockResolvedValue({ ok: true, repo_url: 'https://github.com/T-rav/finance-tool' })
    mockUseHydraFlow.mockReturnValue({ pushOnboardingDraft })

    render(<ProjectView project={{
      slug: 'finance-tool',
      local_only: true,
      onboarding_draft_id: 'draft-1',
      onboarding_events: [],
    }} />)

    fireEvent.click(screen.getByText('Push to GitHub'))
    await waitFor(() => expect(pushOnboardingDraft).toHaveBeenCalledWith('draft-1'))
    expect(screen.getByText('Pushed')).toBeInTheDocument()
  })
})
