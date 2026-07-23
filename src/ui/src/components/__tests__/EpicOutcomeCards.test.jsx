import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import {
  EpicOutcomeCards,
  EpicOutcomeCard,
  deriveEpicExecutionState,
} from '../EpicOutcomeCards'

const baseEpic = {
  epic_number: 10239,
  title: 'Epic Alpha',
  url: 'https://github.com/acme/webapp/issues/10239',
  status: 'active',
  percent_complete: 0,
  total_children: 8,
  completed: 3,
  failed: 1,
  in_progress: 2,
  merged_children: 3,
  active_children: 0,
  queued_children: 2,
  auto_decomposed: false,
  children: [
    { issue_number: 501, title: 'Child one', url: 'https://x/501', is_completed: true, is_failed: false },
    { issue_number: 502, title: 'Child two', url: 'https://x/502', is_completed: false, is_failed: true },
    { issue_number: 503, title: 'Child three', url: 'https://x/503', is_completed: false, is_failed: false },
  ],
}

describe('deriveEpicExecutionState', () => {
  it('returns "running" when a child is held by a worker', () => {
    expect(deriveEpicExecutionState({ ...baseEpic, active_children: 1 })).toBe('running')
  })

  it('returns "queued" when no child is running but one is queued', () => {
    expect(
      deriveEpicExecutionState({ ...baseEpic, active_children: 0, queued_children: 1 }),
    ).toBe('queued')
  })

  it('returns "paused" when open children exist but none are running or queued', () => {
    const state = deriveEpicExecutionState({
      ...baseEpic,
      active_children: 0,
      queued_children: 0,
      in_progress: 2,
    })
    expect(state).toBe('paused')
    expect(state).not.toBe('active')
  })

  it('returns "idle" when nothing is open, running, or queued', () => {
    expect(
      deriveEpicExecutionState({
        ...baseEpic,
        in_progress: 0,
        active_children: 0,
        queued_children: 0,
      }),
    ).toBe('idle')
  })

  it('prefers running over queued when both counts are non-zero', () => {
    expect(
      deriveEpicExecutionState({ ...baseEpic, active_children: 2, queued_children: 3 }),
    ).toBe('running')
  })

  it.each(['completed', 'blocked', 'stale', 'ready', 'releasing', 'released'])(
    'passes through the non-active status %s unchanged',
    (status) => {
      expect(deriveEpicExecutionState({ ...baseEpic, status })).toBe(status)
    },
  )

  it('tolerates a missing status by refining execution state', () => {
    const { status, ...noStatus } = baseEpic
    expect(deriveEpicExecutionState({ ...noStatus, queued_children: 0 })).toBe('paused')
  })
})

describe('EpicOutcomeCards (Outcomes tab)', () => {
  it('renders nothing when there are no epics', () => {
    const { container } = render(<EpicOutcomeCards epics={[]} />)
    expect(container.firstChild).toBeNull()
    expect(screen.queryByTestId('epic-outcome-cards')).not.toBeInTheDocument()
  })

  it('renders nothing when epics is undefined', () => {
    const { container } = render(<EpicOutcomeCards epics={undefined} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a card per epic with the Epics section header and count', () => {
    render(
      <EpicOutcomeCards
        epics={[baseEpic, { ...baseEpic, epic_number: 20000, title: 'Epic Beta' }]}
      />,
    )
    expect(screen.getByTestId('epic-outcome-cards')).toBeInTheDocument()
    expect(screen.getByText('Epics')).toBeInTheDocument()
    expect(screen.getByTestId('epic-outcome-card-10239')).toBeInTheDocument()
    expect(screen.getByTestId('epic-outcome-card-20000')).toBeInTheDocument()
  })

  it('orders non-completed epics ahead of completed ones', () => {
    render(
      <EpicOutcomeCards
        epics={[
          { ...baseEpic, epic_number: 1, status: 'completed', title: 'Done epic' },
          { ...baseEpic, epic_number: 2, status: 'active', title: 'Active epic' },
        ]}
      />,
    )
    const cards = screen.getAllByTestId(/^epic-outcome-card-/)
    const order = cards.map(c => c.getAttribute('data-testid'))
    expect(order).toEqual(['epic-outcome-card-2', 'epic-outcome-card-1'])
  })
})

describe('EpicOutcomeCard', () => {
  it('shows progress (completed/total + percent)', () => {
    render(<EpicOutcomeCard epic={baseEpic} />)
    const progress = screen.getByTestId('epic-progress-10239')
    expect(progress.textContent).toContain('3/8 done')
    // 3/8 = 37.5% -> rounds to 38%
    expect(progress.textContent).toContain('38%')
  })

  it('shows the counts as stat pills (children, merged, failed, in progress, queued)', () => {
    render(<EpicOutcomeCard epic={baseEpic} />)
    expect(screen.getByTestId('epic-stat-children').textContent).toContain('8')
    expect(screen.getByTestId('epic-stat-merged').textContent).toContain('3')
    expect(screen.getByTestId('epic-stat-failed').textContent).toContain('1')
    expect(screen.getByTestId('epic-stat-in progress').textContent).toContain('2')
    expect(screen.getByTestId('epic-stat-queued').textContent).toContain('2')
  })

  it('hides zero-value optional stat pills but always shows children', () => {
    render(
      <EpicOutcomeCard
        epic={{ ...baseEpic, failed: 0, merged_children: 0, in_progress: 0, queued_children: 0 }}
      />,
    )
    expect(screen.getByTestId('epic-stat-children')).toBeInTheDocument()
    expect(screen.queryByTestId('epic-stat-failed')).not.toBeInTheDocument()
    expect(screen.queryByTestId('epic-stat-merged')).not.toBeInTheDocument()
    expect(screen.queryByTestId('epic-stat-queued')).not.toBeInTheDocument()
  })

  it('renders the execution-state badge (paused, not active) when nothing runs or queues', () => {
    render(
      <EpicOutcomeCard
        epic={{ ...baseEpic, active_children: 0, queued_children: 0, in_progress: 2 }}
      />,
    )
    const badge = screen.getByTestId('epic-badge-10239')
    expect(badge.textContent).toBe('paused')
    expect(badge.style.color).not.toBe('var(--green)')
  })

  it('renders a green running badge when a child is held by a worker', () => {
    render(<EpicOutcomeCard epic={{ ...baseEpic, active_children: 1 }} />)
    const badge = screen.getByTestId('epic-badge-10239')
    expect(badge.textContent).toBe('running')
    expect(badge.style.color).toBe('var(--green)')
  })

  it('is collapsed by default and expands to child issues on click', () => {
    render(<EpicOutcomeCard epic={baseEpic} />)
    // Collapsed: no child rows yet
    expect(screen.queryByText('Child one')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('epic-outcome-card-10239').querySelector('[role="button"]'))

    const card = screen.getByTestId('epic-outcome-card-10239')
    expect(within(card).getByText('Child one')).toBeInTheDocument()
    expect(within(card).getByText('Child two')).toBeInTheDocument()
    expect(within(card).getByText('Child three')).toBeInTheDocument()
  })

  it('shows a fallback when expanded with no children', () => {
    render(<EpicOutcomeCard epic={{ ...baseEpic, children: [] }} />)
    fireEvent.click(screen.getByTestId('epic-outcome-card-10239').querySelector('[role="button"]'))
    expect(screen.getByText('No child issues found')).toBeInTheDocument()
  })
})
