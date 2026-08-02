import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { ActiveGrid } from '../ActiveGrid'

// ActiveGrid is the operator console's AGENT view (redesign #10944): one card
// per LIVE/HELD worker, each with an explicit STATE — RUNNING / PAUSED /
// STALLED / WAITING-CI / BLOCKED — plus state filter chips. Derivation is
// delegated to the pure `deriveAgentStates(...)`; tests drive the component with
// a hand-built `workers` slice / pipeline VM + an injected `now`, so states are
// deterministic (mirrors the model-level agents.test.js seam).

const NOW = Date.parse('2026-08-01T12:00:00Z')
const minsAgo = (m) => new Date(NOW - m * 60_000).toISOString()

// A `workers` slice entry shaped like the HydraFlowContext reducer stores it.
function worker(role, status, { worker: id = 1, pr = null, lastMins = 1, title = '' } = {}) {
  return {
    role,
    status,
    worker: id,
    ...(pr != null ? { pr } : {}),
    title,
    transcript: [],
    lastActivity: { timestamp: minsAgo(lastMins) },
  }
}

function pipelineWith({ implement = [] } = {}) {
  const stage = (key, label, items) => ({ key, label, count: items.length, slots: null, items, attention: { hitl: 0, failed: 0 } })
  return {
    stages: [
      stage('triage', 'Triage', []),
      stage('plan', 'Plan', []),
      stage('implement', 'Build', implement),
      stage('review', 'Review', []),
      stage('hitl', 'HITL', []),
      stage('merged', 'Merged', []),
    ],
  }
}

beforeEach(() => {
  if (typeof window !== 'undefined' && window.localStorage) window.localStorage.clear()
})

describe('ActiveGrid — agent view', () => {
  it('renders one card per live worker with an explicit state badge', () => {
    const workers = {
      '101': worker('implementer', 'running', { worker: 4, title: 'Fix login' }),
      'review-202': worker('reviewer', 'ci_wait', { worker: 2, pr: 202 }),
    }
    render(<ActiveGrid workers={workers} now={NOW} />)
    expect(screen.getByTestId('active-tile-101')).toBeInTheDocument()
    expect(screen.getByTestId('agent-state-101')).toHaveAttribute('data-state', 'running')
    expect(screen.getByTestId('active-tile-202')).toBeInTheDocument()
    expect(screen.getByTestId('agent-state-202')).toHaveAttribute('data-state', 'waiting-ci')
  })

  it('excludes queued workers entirely (no "No transcript yet" cards)', () => {
    const workers = {
      '1': { role: 'implementer', status: 'queued', worker: 0, transcript: [] },
      '2': worker('implementer', 'running', { worker: 1 }),
    }
    render(<ActiveGrid workers={workers} now={NOW} />)
    expect(screen.queryByTestId('active-tile-1')).toBeNull()
    expect(screen.getByTestId('active-tile-2')).toBeInTheDocument()
  })

  it('flags a stalled worker distinctly (no output past the threshold)', () => {
    const workers = { '55': worker('implementer', 'running', { worker: 1, lastMins: 45 }) }
    render(<ActiveGrid workers={workers} now={NOW} />)
    expect(screen.getByTestId('agent-state-55')).toHaveAttribute('data-state', 'stalled')
    // The silent-failure catch is called out explicitly.
    expect(screen.getByTestId('agent-stall-55')).toBeInTheDocument()
  })

  it('shows a paused agent with its reason + provider when the factory is credit-paused', () => {
    const workers = { '55': worker('implementer', 'running', { worker: 1 }) }
    const factory = { state: 'paused', reason: 'credits paused until 2026-08-01T13:00:00Z' }
    const credits = { pausedUntil: '2026-08-01T13:00:00Z', provider: 'anthropic' }
    render(<ActiveGrid workers={workers} factory={factory} credits={credits} now={NOW} />)
    expect(screen.getByTestId('agent-state-55')).toHaveAttribute('data-state', 'paused')
    const reason = screen.getByTestId('agent-reason-55')
    expect(reason).toHaveTextContent('credits paused')
    expect(reason).toHaveTextContent('anthropic')
  })

  it('marks an escalated worker as BLOCKED', () => {
    const workers = { '77': worker('triage', 'escalated', { worker: 3 }) }
    render(<ActiveGrid workers={workers} now={NOW} />)
    expect(screen.getByTestId('agent-state-77')).toHaveAttribute('data-state', 'blocked')
  })

  it('surfaces a pipeline-active item with no worker record as a running agent', () => {
    const pipeline = pipelineWith({ implement: [{ id: 42, title: 'Fix login', status: 'active' }] })
    const events = [{ type: 'transcript_line', timestamp: minsAgo(1), data: { issue: 42, line: 'go' } }]
    render(<ActiveGrid pipeline={pipeline} events={events} now={NOW} />)
    expect(screen.getByTestId('active-tile-42')).toBeInTheDocument()
    expect(screen.getByTestId('agent-state-42')).toHaveAttribute('data-state', 'running')
  })

  it('filters by state via the chips (Running hides ci_wait; All restores it)', () => {
    const workers = {
      '101': worker('implementer', 'running', { worker: 1 }),
      'review-202': worker('reviewer', 'ci_wait', { worker: 2, pr: 202 }),
    }
    render(<ActiveGrid workers={workers} now={NOW} />)
    fireEvent.click(screen.getByTestId('agent-filter-running'))
    expect(screen.getByTestId('active-tile-101')).toBeInTheDocument()
    expect(screen.queryByTestId('active-tile-202')).toBeNull()
    fireEvent.click(screen.getByTestId('agent-filter-waiting-ci'))
    expect(screen.queryByTestId('active-tile-101')).toBeNull()
    expect(screen.getByTestId('active-tile-202')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('agent-filter-all'))
    expect(screen.getByTestId('active-tile-101')).toBeInTheDocument()
    expect(screen.getByTestId('active-tile-202')).toBeInTheDocument()
  })

  it('remembers the filter choice across remounts (localStorage)', () => {
    const workers = { '101': worker('implementer', 'running', { worker: 1 }) }
    const { unmount } = render(<ActiveGrid workers={workers} now={NOW} />)
    fireEvent.click(screen.getByTestId('agent-filter-running'))
    unmount()
    render(<ActiveGrid workers={workers} now={NOW} />)
    expect(screen.getByTestId('agent-filter-running')).toHaveAttribute('aria-pressed', 'true')
  })

  it('drills into Focus on the clicked agent (mode then item)', () => {
    const select = vi.fn()
    const workers = { '101': worker('implementer', 'running', { worker: 1 }) }
    render(<ActiveGrid workers={workers} now={NOW} select={select} />)
    fireEvent.click(screen.getByTestId('active-tile-header-101'))
    expect(select).toHaveBeenCalledWith('mode', 'focus')
    expect(select).toHaveBeenCalledWith('item', 101)
  })

  it('shows an empty state when nothing is live', () => {
    render(<ActiveGrid workers={{}} pipeline={pipelineWith()} now={NOW} />)
    expect(screen.getByTestId('active-grid-empty')).toBeInTheDocument()
  })

  it('renders the worker id and phase in the operator card header', () => {
    const workers = { '101': worker('implementer', 'running', { worker: 7, title: 'Fix login' }) }
    render(<ActiveGrid workers={workers} now={NOW} />)
    const tile = screen.getByTestId('active-tile-101')
    expect(within(tile).getByTestId('agent-worker-101')).toHaveTextContent('W7')
    expect(within(tile).getByTestId('agent-phase-101')).toHaveTextContent('Build')
  })
})
