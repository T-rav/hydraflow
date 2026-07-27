import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { IdleState } from '../states/IdleState'
import { PausedState } from '../states/PausedState'
import { DisconnectedBanner } from '../states/DisconnectedBanner'
import { LoadingState } from '../states/LoadingState'
import { OperatorConsoleView } from '../OperatorConsole'

// Task 10: the operator console's four "not-the-happy-path" screens — a calm
// idle/empty state, a paused state (reason + resume), a non-blocking
// disconnected banner that retains the last-known content, and a loading
// skeleton that holds the layout so nothing jumps when data arrives. Unit tests
// exercise each component in isolation; the integration block drives them
// through OperatorConsoleView against socket fixtures to prove the wiring.

// ---------------------------------------------------------------------------
// Unit: IdleState
// ---------------------------------------------------------------------------
describe('IdleState', () => {
  it('renders a calm idle panel', () => {
    render(<IdleState />)
    expect(screen.getByTestId('operator-idle-state')).toBeInTheDocument()
  })

  it('does NOT use the anxious "Waiting for issues…" copy', () => {
    render(<IdleState />)
    expect(screen.queryByText(/waiting for issues/i)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Unit: PausedState
// ---------------------------------------------------------------------------
describe('PausedState', () => {
  it('renders the pause reason', () => {
    render(<PausedState reason="credits paused until 2026-07-27T00:00:00Z" />)
    expect(screen.getByTestId('operator-paused-state')).toBeInTheDocument()
    expect(screen.getByText(/credits paused until/i)).toBeInTheDocument()
  })

  it('surfaces the provider that ran out when supplied', () => {
    render(<PausedState reason="credits paused" provider="anthropic" />)
    expect(screen.getByTestId('operator-paused-state')).toHaveTextContent('anthropic')
  })

  it('offers a resume control that invokes onResume', () => {
    const onResume = vi.fn()
    render(<PausedState reason="credits paused" onResume={onResume} />)
    fireEvent.click(screen.getByTestId('operator-paused-resume'))
    expect(onResume).toHaveBeenCalledTimes(1)
  })

  it('does not crash when onResume is omitted', () => {
    render(<PausedState reason="credits paused" />)
    fireEvent.click(screen.getByTestId('operator-paused-resume'))
    expect(screen.getByTestId('operator-paused-state')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Unit: DisconnectedBanner
// ---------------------------------------------------------------------------
describe('DisconnectedBanner', () => {
  it('renders a status banner', () => {
    render(<DisconnectedBanner />)
    const banner = screen.getByTestId('operator-disconnected-banner')
    expect(banner).toBeInTheDocument()
    expect(banner).toHaveAttribute('role', 'status')
  })

  it('communicates that reconnection is in progress', () => {
    render(<DisconnectedBanner />)
    expect(screen.getByText(/reconnect/i)).toBeInTheDocument()
  })

  it('invokes onRetry when a retry control is provided and clicked', () => {
    const onRetry = vi.fn()
    render(<DisconnectedBanner onRetry={onRetry} />)
    fireEvent.click(screen.getByTestId('operator-disconnected-retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('renders no retry control when onRetry is omitted', () => {
    render(<DisconnectedBanner />)
    expect(screen.queryByTestId('operator-disconnected-retry')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Unit: LoadingState
// ---------------------------------------------------------------------------
describe('LoadingState', () => {
  it('renders a loading skeleton', () => {
    render(<LoadingState />)
    expect(screen.getByTestId('operator-loading-state')).toBeInTheDocument()
  })

  it('renders multiple skeleton placeholders (no spinner, no copy churn)', () => {
    render(<LoadingState />)
    expect(screen.getAllByTestId('operator-skeleton').length).toBeGreaterThanOrEqual(3)
  })
})

// ---------------------------------------------------------------------------
// Integration: OperatorConsoleView state wiring
// ---------------------------------------------------------------------------
describe('OperatorConsoleView — state wiring (Task 10)', () => {
  let originalHref

  beforeEach(() => {
    originalHref = window.location.href
    window.history.replaceState({}, '', '/')
  })

  afterEach(() => {
    window.history.replaceState({}, '', originalHref)
  })

  const emptyStages = { triage: [], plan: [], implement: [], review: [], hitl: [], merged: [] }

  it('an idle repo (empty pipeline) shows the calm idle state, not "Waiting for issues…"', () => {
    const { container } = render(
      <OperatorConsoleView socket={{ connected: true, events: [], pipelineIssues: emptyStages, pipelineStats: null }} />,
    )
    expect(screen.getByTestId('operator-idle-state')).toBeInTheDocument()
    expect(screen.queryByText(/waiting for issues/i)).toBeNull()
    // The pipeline hero still renders its six stages — idle is calm, not blank.
    expect(container.querySelectorAll('[data-testid^="stage-tile-"]')).toHaveLength(6)
  })

  it('a credit-paused factory shows the paused state with reason + a resume control', () => {
    const clearCreditPause = vi.fn()
    render(
      <OperatorConsoleView
        socket={{
          connected: true,
          clearCreditPause,
          pipelineIssues: {
            ...emptyStages,
            implement: [{ issue_number: 7, title: 'Build thing', status: 'active' }],
          },
          events: [
            {
              type: 'orchestrator_status',
              timestamp: '2026-07-26T12:00:00Z',
              id: 1,
              data: {
                status: 'running',
                credits_paused_until: '2026-07-27T00:00:00Z',
                credits_paused_provider: 'anthropic',
              },
            },
          ],
        }}
      />,
    )
    const paused = screen.getByTestId('operator-paused-state')
    expect(paused).toBeInTheDocument()
    // Reason is shown in the paused banner itself (the header also echoes it).
    expect(within(paused).getByText(/credits paused until/i)).toBeInTheDocument()
    fireEvent.click(within(paused).getByTestId('operator-paused-resume'))
    expect(clearCreditPause).toHaveBeenCalledTimes(1)
  })

  it('a socket disconnect shows a non-blocking banner AND retains the last state', () => {
    render(
      <OperatorConsoleView
        socket={{
          connected: false,
          disconnected: true,
          pipelineIssues: {
            ...emptyStages,
            implement: [{ issue_number: 42, title: 'Fix login', status: 'active' }],
          },
          events: [
            { type: 'transcript_line', timestamp: '2026-07-26T12:00:02Z', id: 3, data: { issue: 42, line: 'running tests' } },
          ],
        }}
      />,
    )
    // Non-blocking banner is present…
    expect(screen.getByTestId('operator-disconnected-banner')).toBeInTheDocument()
    // …and the last-known content is retained (pipeline hero + detail workspace
    // still mounted; the banner does not replace them).
    expect(screen.getByTestId('pipeline-rail')).toBeInTheDocument()
    expect(screen.getByTestId('item-workspace')).toBeInTheDocument()
    // Not a loading skeleton — we keep the stale view, not a blank one.
    expect(screen.queryByTestId('operator-loading-state')).toBeNull()
  })

  it('initial load (not-yet-connected, no data) shows skeletons in the same container — no layout jump', () => {
    render(
      <OperatorConsoleView socket={{ connected: false, events: [], pipelineIssues: emptyStages }} />,
    )
    expect(screen.getByTestId('operator-loading-state')).toBeInTheDocument()
    expect(screen.getAllByTestId('operator-skeleton').length).toBeGreaterThanOrEqual(3)
    // The skeleton lives inside the same operator-console shell, so swapping to
    // the loaded grid does not remount/relayout the page.
    expect(screen.getByTestId('operator-console')).toBeInTheDocument()
    // The real hero is not mounted yet while loading.
    expect(screen.queryByTestId('pipeline-rail')).toBeNull()
  })

  it('a bare {} socket keeps the existing full-shell contract (connected===undefined ≠ loading)', () => {
    const { container } = render(<OperatorConsoleView socket={{}} />)
    expect(screen.getByTestId('operator-console')).toBeInTheDocument()
    expect(screen.queryByTestId('operator-loading-state')).toBeNull()
    expect(container.querySelectorAll('[data-testid^="stage-tile-"]')).toHaveLength(6)
  })
})
