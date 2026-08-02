import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { PipelineRail } from '../PipelineRail'

// #10943: within each workflow column the in-flight items split into an ACTIVE
// sub-group (a worker is running that item) and a QUEUED sub-group (waiting),
// with a per-column filter chip and an honest "idle — N queued" header. These
// tests exercise that grouping; the flat-tile behaviour is covered by
// PipelineRail.test.jsx.

// A pipeline VM with a parameterised Build column, shaped like toPipeline output.
function pipelineWithBuild(items) {
  const stage = (key, label, its) => ({ key, label, count: its.length, slots: { used: 1, cap: 5 }, items: its, attention: { hitl: 0, failed: 0 } })
  return {
    stages: [
      stage('triage', 'Triage', []),
      stage('plan', 'Plan', []),
      stage('implement', 'Build', items),
      stage('review', 'Review', []),
      { key: 'hitl', label: 'HITL', count: 0, slots: null, items: [], attention: { hitl: 0, failed: 0 } },
      { key: 'merged', label: 'Merged', count: 0, slots: null, items: [], attention: { hitl: 0, failed: 0 } },
    ],
  }
}

// The acceptance case: 15 build items, one worker on one of them.
function build15() {
  return pipelineWithBuild([
    { id: 200, title: 'building', status: 'active' },
    ...Array.from({ length: 14 }, (_, i) => ({ id: 300 + i, title: `q${i}`, status: 'queued' })),
  ])
}

beforeEach(() => {
  if (typeof window !== 'undefined' && window.localStorage) window.localStorage.clear()
})

describe('PipelineRail — ACTIVE / QUEUED split (#10943)', () => {
  it('BUILD 15 (1 worker) shows exactly 1 under ACTIVE and 14 under QUEUED', () => {
    render(<PipelineRail pipeline={build15()} select={() => {}} />)
    const active = screen.getByTestId('phase-active-implement')
    const queued = screen.getByTestId('phase-queued-implement')
    expect(within(active).getByTestId('item-chip-200')).toBeInTheDocument()
    // ACTIVE holds exactly the one running item.
    expect(within(active).queryAllByTestId(/^item-chip-/)).toHaveLength(1)
    // QUEUED holds the rest — collapsed past 5 with a "+9 more" affordance.
    expect(within(queued).getByTestId('phase-more-implement')).toHaveTextContent('+9 more')
    expect(within(queued).queryAllByTestId(/^item-chip-/)).toHaveLength(5)
  })

  it('marks the ACTIVE item with a live pulse indicator', () => {
    render(<PipelineRail pipeline={build15()} select={() => {}} />)
    expect(screen.getByTestId('item-live-200')).toBeInTheDocument()
    // A queued item carries no live pulse.
    expect(screen.queryByTestId('item-live-300')).toBeNull()
  })

  it('expands the collapsed queue on demand', () => {
    render(<PipelineRail pipeline={build15()} select={() => {}} />)
    fireEvent.click(screen.getByTestId('phase-more-implement'))
    const queued = screen.getByTestId('phase-queued-implement')
    expect(within(queued).queryAllByTestId(/^item-chip-/)).toHaveLength(14)
    expect(screen.queryByTestId('phase-more-implement')).toBeNull()
  })

  it('the Queued filter hides the active item; the Active filter hides the queue', () => {
    render(<PipelineRail pipeline={build15()} select={() => {}} />)
    fireEvent.click(screen.getByTestId('phase-filter-implement-queued'))
    expect(screen.queryByTestId('phase-active-implement')).toBeNull()
    expect(screen.getByTestId('phase-queued-implement')).toBeInTheDocument()
    // Viewing Queued explicitly shows the whole queue (no collapse).
    expect(within(screen.getByTestId('phase-queued-implement')).queryAllByTestId(/^item-chip-/)).toHaveLength(14)

    fireEvent.click(screen.getByTestId('phase-filter-implement-active'))
    expect(screen.getByTestId('phase-active-implement')).toBeInTheDocument()
    expect(screen.queryByTestId('phase-queued-implement')).toBeNull()
  })

  it('reads "idle — N queued" for a phase with zero active items', () => {
    const pipeline = pipelineWithBuild(
      Array.from({ length: 3 }, (_, i) => ({ id: 400 + i, title: `q${i}`, status: 'queued' })),
    )
    render(<PipelineRail pipeline={pipeline} select={() => {}} />)
    expect(screen.getByTestId('phase-idle-implement')).toHaveTextContent('idle — 3 queued')
    // No ACTIVE group renders when nothing is running.
    expect(screen.queryByTestId('phase-active-implement')).toBeNull()
  })

  it('remembers the per-column filter across remounts (localStorage)', () => {
    const { unmount } = render(<PipelineRail pipeline={build15()} select={() => {}} />)
    fireEvent.click(screen.getByTestId('phase-filter-implement-queued'))
    unmount()
    render(<PipelineRail pipeline={build15()} select={() => {}} />)
    expect(screen.getByTestId('phase-filter-implement-queued')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByTestId('phase-active-implement')).toBeNull()
  })

  it('still emits select("item", id) from a grouped chip, without selecting the stage', () => {
    const select = vi.fn()
    render(<PipelineRail pipeline={build15()} select={select} />)
    fireEvent.click(screen.getByTestId('item-chip-200'))
    expect(select).toHaveBeenCalledWith('item', 200)
    expect(select).toHaveBeenCalledTimes(1)
  })
})
