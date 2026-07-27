import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { ActivityDrawer } from '../ActivityDrawer'

// ActivityDrawer (epic #10556, Task 7) is the demoted global activity feed that
// replaces today's raw firehose EventLog. Collapsed it is a single strip —
// latest line + filter chips (all·errors·merges·hitl) + "N new"; expanded it is
// a virtualized, grouped list. It consumes the already-grouped feed from
// `toActivityFeed(...)` (Task 1), so the never-group-errors guarantee is the
// adapter's; this component only renders count badges, filters, and windows.
//
// Tests pass feed literals shaped exactly like `toActivityFeed(...)` output,
// decoupling the component from the adapter (mirrors the PipelineRail test).

const feedRow = (over = {}) => ({
  ts: '2026-07-26T12:00:00Z',
  type: 'transcript_line',
  severity: 'info',
  summary: 'writing file',
  groupKey: 'transcript:5',
  count: 1,
  ...over,
})

function mixedFeed() {
  return [
    feedRow({ type: 'merge_update', severity: 'info', summary: 'PR #528 merged', ts: '2026-07-26T12:00:09Z', groupKey: 'm528' }),
    feedRow({ type: 'error', severity: 'error', summary: 'boom in build', ts: '2026-07-26T12:00:08Z', groupKey: 'err-1' }),
    feedRow({ type: 'transcript_line', severity: 'info', summary: 'writing file', count: 11, ts: '2026-07-26T12:00:07Z', groupKey: 'transcript:10493' }),
    feedRow({ type: 'hitl_escalation', severity: 'error', summary: '#7 escalated to HITL', ts: '2026-07-26T12:00:06Z', groupKey: 'hitl-7' }),
  ]
}

describe('ActivityDrawer', () => {
  it('renders without crashing on an empty feed', () => {
    render(<ActivityDrawer activity={[]} />)
    expect(screen.getByTestId('activity-drawer')).toBeInTheDocument()
  })

  it('collapsed by default: shows the latest event and hides the list', () => {
    render(<ActivityDrawer activity={mixedFeed()} />)
    // Newest-first, so the latest row is the PR #528 merge.
    expect(screen.getByTestId('activity-latest')).toHaveTextContent('PR #528 merged')
    // The virtualized list is not mounted while collapsed.
    expect(screen.queryByTestId('activity-list')).toBeNull()
  })

  it('renders the four filter chips', () => {
    render(<ActivityDrawer activity={mixedFeed()} />)
    for (const key of ['all', 'errors', 'merges', 'hitl']) {
      expect(screen.getByTestId(`activity-filter-${key}`)).toBeInTheDocument()
    }
  })

  it('expands to show the grouped list when the strip is toggled', () => {
    render(<ActivityDrawer activity={mixedFeed()} />)
    fireEvent.click(screen.getByTestId('activity-toggle'))
    expect(screen.getByTestId('activity-list')).toBeInTheDocument()
    expect(screen.getAllByTestId('activity-row').length).toBeGreaterThan(0)
  })

  it('a grouped row shows its collapse count', () => {
    render(<ActivityDrawer activity={mixedFeed()} />)
    fireEvent.click(screen.getByTestId('activity-toggle'))
    // The 11-collapsed transcript run surfaces a count badge.
    const grouped = screen.getByText('writing file', { selector: '[data-testid="activity-row"] *' }).closest('[data-testid="activity-row"]')
    expect(within(grouped).getByTestId('activity-count')).toHaveTextContent('11')
  })

  it('filter chips narrow the list by type', () => {
    render(<ActivityDrawer activity={mixedFeed()} />)
    fireEvent.click(screen.getByTestId('activity-toggle'))
    fireEvent.click(screen.getByTestId('activity-filter-errors'))
    const rows = screen.getAllByTestId('activity-row')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveAttribute('data-severity', 'error')
    expect(rows[0]).toHaveTextContent('boom in build')
    // The active chip is reflected as pressed.
    expect(screen.getByTestId('activity-filter-errors')).toHaveAttribute('aria-pressed', 'true')
  })

  it('the hitl chip isolates HITL rows (which are distinct from generic errors)', () => {
    render(<ActivityDrawer activity={mixedFeed()} />)
    fireEvent.click(screen.getByTestId('activity-toggle'))
    fireEvent.click(screen.getByTestId('activity-filter-hitl'))
    const rows = screen.getAllByTestId('activity-row')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('escalated to HITL')
  })

  it('error and hitl rows are NEVER grouped — each renders as its own row with no count badge', () => {
    // Two distinct errors + two distinct HITL rows, all count:1 (the adapter
    // never collapses these). The drawer must render four separate rows and
    // never a group-count badge on any of them.
    const feed = [
      feedRow({ type: 'error', severity: 'error', summary: 'boom A', ts: '2026-07-26T12:00:04Z', groupKey: 'e-a' }),
      feedRow({ type: 'error', severity: 'error', summary: 'boom B', ts: '2026-07-26T12:00:03Z', groupKey: 'e-b' }),
      feedRow({ type: 'hitl_escalation', severity: 'error', summary: '#1 escalated to HITL', ts: '2026-07-26T12:00:02Z', groupKey: 'h-1' }),
      feedRow({ type: 'hitl_escalation', severity: 'error', summary: '#2 escalated to HITL', ts: '2026-07-26T12:00:01Z', groupKey: 'h-2' }),
    ]
    render(<ActivityDrawer activity={feed} />)
    fireEvent.click(screen.getByTestId('activity-toggle'))
    const rows = screen.getAllByTestId('activity-row')
    expect(rows).toHaveLength(4)
    expect(screen.queryByTestId('activity-count')).toBeNull()
  })

  it('virtualizes a large feed: only a bounded number of row nodes render', () => {
    const big = Array.from({ length: 1000 }, (_, i) =>
      feedRow({ ts: `2026-07-26T13:${String(i % 60).padStart(2, '0')}:00Z`, groupKey: `g${i}`, summary: `line ${i}` }),
    )
    render(<ActivityDrawer activity={big} />)
    fireEvent.click(screen.getByTestId('activity-toggle'))
    const rows = screen.getAllByTestId('activity-row')
    expect(rows.length).toBeGreaterThan(0)
    expect(rows.length).toBeLessThan(50)
  })

  it('surfaces a "N new" indicator when newer rows arrive while collapsed', () => {
    const initial = [feedRow({ ts: '2026-07-26T12:00:02Z', groupKey: 'a', summary: 'old' })]
    const { rerender } = render(<ActivityDrawer activity={initial} />)
    // Nothing new on first mount.
    expect(screen.queryByTestId('activity-new-count')).toBeNull()

    const grown = [
      feedRow({ ts: '2026-07-26T12:00:05Z', groupKey: 'c', summary: 'newest' }),
      feedRow({ ts: '2026-07-26T12:00:04Z', groupKey: 'b', summary: 'newer' }),
      ...initial,
    ]
    rerender(<ActivityDrawer activity={grown} />)
    expect(screen.getByTestId('activity-new-count')).toHaveTextContent('2')
  })
})
