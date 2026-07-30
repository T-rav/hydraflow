import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TimelinePanel } from '../TimelinePanel'
import { stageColorKey } from '../model/pipeline'

// TimelinePanel (feat/operator-timeline) consumes the `toTimeline(...)` view
// model and renders a vertical timeline: one collapsible phase-container card per
// entry, each hung off a stage-coloured rail node, with the phase's event bullets
// and any PR/commit diff rows folded inside. Colours resolve through
// `stageColorKey` + the token layer — the same mapping the pipeline rail uses.

function entry(over = {}) {
  return {
    id: '5',
    phase: 'implement',
    phaseLabel: 'Build',
    issue: 10812,
    startTs: '2026-07-26T12:05:00Z',
    endTs: '2026-07-26T12:17:00Z',
    durationLabel: '12m',
    events: [{ ts: '2026-07-26T12:10:00Z', kind: 'pr', text: 'PR #10820 opened' }],
    diffs: [{ id: '6', prNumber: 10820, url: 'https://gh/x/y/pull/10820' }],
    ...over,
  }
}

const reviewEntry = () => ({
  id: '7',
  phase: 'review',
  phaseLabel: 'Review',
  issue: 10812,
  startTs: '2026-07-26T12:17:00Z',
  endTs: null,
  durationLabel: '4m',
  events: [{ ts: '2026-07-26T12:18:00Z', kind: 'review', text: 'PR #10820 → request-changes' }],
  diffs: [],
})

const vm = (entries = [entry(), reviewEntry()]) => ({ entries })

describe('TimelinePanel', () => {
  // Collapse state is persisted to localStorage; isolate each test.
  beforeEach(() => window.localStorage.clear())

  it('renders the panel container', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-panel')).toBeInTheDocument()
  })

  it('renders one container per timeline entry', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-entry-5')).toBeInTheDocument()
    expect(screen.getByTestId('timeline-entry-7')).toBeInTheDocument()
  })

  it('renders the phase label for each container', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-phase-implement')).toHaveTextContent('Build')
    expect(screen.getByTestId('timeline-phase-review')).toHaveTextContent('Review')
  })

  it('paints the rail node in the classic stage colour (same mapping as the rail)', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-node-5')).toHaveAttribute('data-stage-color', stageColorKey('implement'))
    expect(screen.getByTestId('timeline-node-7')).toHaveAttribute('data-stage-color', stageColorKey('review'))
  })

  it('shows the phase duration and issue', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-duration-5')).toHaveTextContent('12m')
    expect(screen.getByTestId('timeline-issue-5')).toHaveTextContent('#10812')
  })

  it('renders the phase event bullets (expanded by default)', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-event-5-0')).toHaveTextContent('PR #10820 opened')
  })

  it('renders a diff row with a linked PR when a url is present', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-diff-6')).toHaveTextContent('PR #10820')
    const link = screen.getByTestId('timeline-diff-link-6')
    expect(link).toHaveAttribute('href', 'https://gh/x/y/pull/10820')
  })

  it('renders no diff region for a phase with no diffs', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.queryByTestId('timeline-diffs-7')).toBeNull()
    expect(screen.queryByTestId('timeline-diff-8')).toBeNull()
  })

  it('degrades gracefully — a diff with only a PR number renders unlinked, no invented stats', () => {
    render(<TimelinePanel timeline={vm([entry({ diffs: [{ id: '9', prNumber: 555 }] })])} />)
    expect(screen.getByTestId('timeline-diff-9')).toHaveTextContent('PR #555')
    // No url → no link; no file/line stats fabricated.
    expect(screen.queryByTestId('timeline-diff-link-9')).toBeNull()
    expect(screen.queryByTestId('timeline-diff-sha-9')).toBeNull()
    expect(screen.queryByTestId('timeline-diff-stat-9')).toBeNull()
  })

  it('renders commit sha + line stats when the diff carries them', () => {
    render(<TimelinePanel timeline={vm([entry({
      diffs: [{ id: '3', prNumber: 7, commitSha: 'a1b2c3d4', additions: 42, deletions: 7, filesChanged: 3 }],
    })])} />)
    expect(screen.getByTestId('timeline-diff-sha-3')).toHaveTextContent('a1b2c3d')
    const stat = screen.getByTestId('timeline-diff-stat-3')
    expect(stat).toHaveTextContent('+42')
    expect(stat).toHaveTextContent('−7')
  })

  it('collapses a container on toggle, hiding its events + diffs', () => {
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-event-5-0')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('timeline-toggle-5'))
    expect(screen.getByTestId('timeline-toggle-5')).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('timeline-event-5-0')).toBeNull()
    expect(screen.queryByTestId('timeline-diff-6')).toBeNull()
  })

  it('remembers a collapsed container across remount (persisted)', () => {
    const { unmount } = render(<TimelinePanel timeline={vm()} />)
    fireEvent.click(screen.getByTestId('timeline-toggle-5')) // operator collapses Build
    unmount()
    render(<TimelinePanel timeline={vm()} />)
    expect(screen.getByTestId('timeline-toggle-5')).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('timeline-event-5-0')).toBeNull()
  })

  it('shows an empty state when there are no phases', () => {
    render(<TimelinePanel timeline={{ entries: [] }} />)
    expect(screen.getByTestId('timeline-empty')).toBeInTheDocument()
  })

  it('does not crash when given no timeline prop', () => {
    render(<TimelinePanel />)
    expect(screen.getByTestId('timeline-panel')).toBeInTheDocument()
    expect(screen.getByTestId('timeline-empty')).toBeInTheDocument()
  })
})
