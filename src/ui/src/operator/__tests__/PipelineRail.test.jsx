import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PipelineRail } from '../PipelineRail'

// The PipelineRail is the operator console's hero (epic #10556, Task 3). It
// consumes a `toPipeline(...)` view model (Task 1) and the `select(kind, value)`
// callback from `useOperatorSelection` (Task 2). It renders the six canonical
// stage tiles (Triage → Plan → Build → Review → HITL → Merged) with live
// counts/slots, an attention badge on the HITL tile equal to the HITL depth, a
// red badge on any failed item, and emits `select('stage', key)` /
// `select('item', id)` when a tile / chip is clicked.

// A pipeline VM literal shaped exactly like `toPipeline(...)` output. Keeping it
// a literal (rather than round-tripping through the adapter) decouples this
// component test from the adapter's internals.
function makePipeline(overrides = {}) {
  return {
    stages: [
      {
        key: 'triage', label: 'Triage', count: 1,
        slots: { used: 0, cap: 2 },
        items: [{ id: 101, title: 'Triage me', status: 'queued' }],
        attention: { hitl: 0, failed: 0 },
      },
      {
        key: 'plan', label: 'Plan', count: 0,
        slots: { used: 0, cap: 2 },
        items: [],
        attention: { hitl: 0, failed: 0 },
      },
      {
        key: 'implement', label: 'Build', count: 2,
        slots: { used: 2, cap: 5 },
        items: [
          { id: 201, title: 'Build A', status: 'active' },
          { id: 202, title: 'Build B', status: 'failed' },
        ],
        attention: { hitl: 0, failed: 1 },
      },
      {
        key: 'review', label: 'Review', count: 1,
        slots: { used: 1, cap: 3 },
        items: [{ id: 301, title: 'Review me', status: 'active' }],
        attention: { hitl: 0, failed: 0 },
      },
      {
        key: 'hitl', label: 'HITL', count: 4,
        slots: null,
        items: [
          { id: 401, title: 'Stuck 1', status: 'hitl' },
          { id: 402, title: 'Stuck 2', status: 'hitl' },
          { id: 403, title: 'Stuck 3', status: 'hitl' },
          { id: 404, title: 'Stuck 4', status: 'hitl' },
        ],
        attention: { hitl: 4, failed: 0 },
      },
      {
        key: 'merged', label: 'Merged', count: 9,
        slots: null,
        items: [{ id: 501, title: 'Done', status: 'done' }],
        attention: { hitl: 0, failed: 0 },
      },
    ],
    ...overrides,
  }
}

describe('PipelineRail', () => {
  it('renders the six canonical stage tiles in lifecycle order', () => {
    const { container } = render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    const tiles = container.querySelectorAll('[data-testid^="stage-tile-"]')
    expect(tiles).toHaveLength(6)
    for (const key of ['triage', 'plan', 'implement', 'review', 'hitl', 'merged']) {
      expect(screen.getByTestId(`stage-tile-${key}`)).toBeInTheDocument()
    }
    // Labels render through ('implement' shows as 'Build').
    expect(screen.getByTestId('stage-tile-implement')).toHaveTextContent('Build')
    expect(screen.getByTestId('stage-tile-hitl')).toHaveTextContent('HITL')
  })

  it('renders per-stage counts from the VM', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    expect(screen.getByTestId('stage-count-implement')).toHaveTextContent('2')
    expect(screen.getByTestId('stage-count-merged')).toHaveTextContent('9')
    expect(screen.getByTestId('stage-count-plan')).toHaveTextContent('0')
  })

  it('renders worker slots as used/cap for role-bearing stages and omits them for no-role stages', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    expect(screen.getByTestId('stage-slots-implement')).toHaveTextContent('2/5')
    expect(screen.getByTestId('stage-slots-triage')).toHaveTextContent('0/2')
    // HITL and Merged have no worker slots.
    expect(screen.queryByTestId('stage-slots-hitl')).toBeNull()
    expect(screen.queryByTestId('stage-slots-merged')).toBeNull()
  })

  it('shows an attention badge on the HITL tile equal to the HITL depth', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    const badge = screen.getByTestId('stage-hitl-badge-hitl')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveTextContent('4')
    // Clean stages carry no HITL badge.
    expect(screen.queryByTestId('stage-hitl-badge-triage')).toBeNull()
  })

  it('shows a red badge on a failed item and a stage-level failed badge', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    // The failed Build item (202) carries a red danger badge.
    const failedBadge = screen.getByTestId('item-failed-202')
    expect(failedBadge).toBeInTheDocument()
    expect(failedBadge).toHaveAttribute('data-tone', 'danger')
    // A non-failed item carries no failed badge.
    expect(screen.queryByTestId('item-failed-201')).toBeNull()
    // The Build tile surfaces a stage-level failed badge of 1.
    const stageFailed = screen.getByTestId('stage-failed-badge-implement')
    expect(stageFailed).toHaveTextContent('1')
    expect(stageFailed).toHaveAttribute('data-tone', 'danger')
  })

  it('emits select("stage", key) when a stage tile is clicked', () => {
    const select = vi.fn()
    render(<PipelineRail pipeline={makePipeline()} select={select} />)
    fireEvent.click(screen.getByTestId('stage-tile-plan'))
    expect(select).toHaveBeenCalledWith('stage', 'plan')
  })

  it('emits select("item", id) when an item chip is clicked, without also selecting the stage', () => {
    const select = vi.fn()
    render(<PipelineRail pipeline={makePipeline()} select={select} />)
    fireEvent.click(screen.getByTestId('item-chip-201'))
    expect(select).toHaveBeenCalledWith('item', 201)
    expect(select).toHaveBeenCalledTimes(1)
  })

  it('marks the currently-selected stage as active', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} stage="implement" />)
    expect(screen.getByTestId('stage-tile-implement')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('stage-tile-triage')).toHaveAttribute('aria-pressed', 'false')
  })

  // ── Stage health color bar (#10556 follow-up) ─────────────────────────────
  // A thin bar across the top of each tile encodes stage health, precedence
  // failed > hitl > flowing > idle, exposed via data-severity for testability.

  it('renders a health color bar for every stage tile', () => {
    const { container } = render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    const bars = container.querySelectorAll('[data-testid^="stage-colorbar-"]')
    expect(bars).toHaveLength(6)
    for (const key of ['triage', 'plan', 'implement', 'review', 'hitl', 'merged']) {
      expect(screen.getByTestId(`stage-colorbar-${key}`)).toBeInTheDocument()
    }
  })

  it('marks a failed stage bar as bad (failed outranks everything)', () => {
    // The Build stage has attention.failed === 1.
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    expect(screen.getByTestId('stage-colorbar-implement')).toHaveAttribute('data-severity', 'bad')
  })

  it('marks an HITL stage bar as warn when it has HITL depth but no failures', () => {
    // The HITL stage has attention.hitl === 4, attention.failed === 0.
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    expect(screen.getByTestId('stage-colorbar-hitl')).toHaveAttribute('data-severity', 'warn')
  })

  it('marks an active (flowing) stage bar as ok when it has count but no attention', () => {
    // The Review stage has count === 1, hitl === 0, failed === 0.
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    expect(screen.getByTestId('stage-colorbar-review')).toHaveAttribute('data-severity', 'ok')
  })

  it('marks an empty/idle stage bar as muted when count is zero and no attention', () => {
    // The Plan stage has count === 0 and no attention.
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    expect(screen.getByTestId('stage-colorbar-plan')).toHaveAttribute('data-severity', 'muted')
  })

  // ── Stage identity colour = classic PIPELINE_STAGES palette (#10) ──────────
  // The tile's top bar is painted in the stage's classic-dashboard identity
  // colour (token key exposed via data-stage-color), while the severity signal
  // is preserved on data-severity + the attention badges.

  it('paints each stage bar in its classic-palette identity colour', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    const expected = {
      triage: 'yellow',
      plan: 'purple',
      implement: 'accent',
      review: 'orange',
      hitl: 'red',
      merged: 'green',
    }
    for (const [key, colorKey] of Object.entries(expected)) {
      expect(screen.getByTestId(`stage-colorbar-${key}`)).toHaveAttribute('data-stage-color', colorKey)
    }
  })

  it('keeps the severity signal on the bar alongside the identity colour', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    // The Build stage identity colour is accent, but it still signals bad severity.
    const bar = screen.getByTestId('stage-colorbar-implement')
    expect(bar).toHaveAttribute('data-stage-color', 'accent')
    expect(bar).toHaveAttribute('data-severity', 'bad')
  })

  // ── Terminal stages (hitl, merged) list issue ids (#14) ────────────────────

  it('lists the issue ids for the hitl and merged terminal stages', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    const hitl = screen.getByTestId('stage-items-hitl')
    expect(hitl).toHaveTextContent('401')
    expect(hitl).toHaveTextContent('404')
    const merged = screen.getByTestId('stage-items-merged')
    expect(merged).toHaveTextContent('501')
  })

  it('selecting a terminal-stage issue id drills into that item', () => {
    const select = vi.fn()
    render(<PipelineRail pipeline={makePipeline()} select={select} />)
    fireEvent.click(screen.getByTestId('stage-item-hitl-401'))
    expect(select).toHaveBeenCalledWith('item', 401)
  })

  it('does not render heavy id+title chips for the terminal stages', () => {
    render(<PipelineRail pipeline={makePipeline()} select={() => {}} />)
    // hitl/merged use the compact id chips, not the workflow-stage item-chip.
    expect(screen.queryByTestId('item-chip-401')).toBeNull()
    expect(screen.queryByTestId('item-chip-501')).toBeNull()
    // Workflow stages keep their full chips.
    expect(screen.getByTestId('item-chip-201')).toBeInTheDocument()
  })

  it('does not crash on an empty pipeline VM', () => {
    const { container } = render(<PipelineRail pipeline={{ stages: [] }} select={() => {}} />)
    expect(container.querySelector('[data-testid="pipeline-rail"]')).toBeInTheDocument()
    expect(container.querySelectorAll('[data-testid^="stage-tile-"]')).toHaveLength(0)
  })
})
