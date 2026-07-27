import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { LoopsPanel } from '../LoopsPanel'

// LoopsPanel (epic #10556 follow-up) consumes the `toLoops(...)` view model and
// renders every background loop grouped by functional area: a collapsible
// category header with count + ok/total badge, and a per-loop row with a
// colour-coded status dot (the `ok`|`warn`|`bad`|`muted` class is the contract)
// plus the relevant recent message/error (truncated, click to expand).

function loop(over = {}) {
  return {
    id: 'ci_monitor',
    key: 'ci_monitor',
    name: 'CI Monitor',
    status: 'ok',
    severity: 'ok',
    lastMessage: 'filed=0',
    lastError: null,
    restarts: 0,
    lastRunTs: '2026-07-26T12:00:00Z',
    enabled: true,
    interval: 300,
    ...over,
  }
}

function vm(over = {}) {
  return {
    categories: [
      {
        key: 'repo_health',
        name: 'Repo Health',
        count: 2,
        ok: 1,
        loops: [
          loop({ id: 'flake_tracker', key: 'flake_tracker', name: 'Flake Tracker', severity: 'bad', status: 'error', lastError: 'Flake tracker loop error', lastMessage: null }),
          loop(),
        ],
      },
    ],
    totals: { ok: 1, total: 2, restarted: 0, disabled: 0 },
    ...over,
  }
}

describe('LoopsPanel', () => {
  // Collapse state is persisted to localStorage; isolate each test.
  beforeEach(() => window.localStorage.clear())

  // Categories start COLLAPSED — expand one to reveal its loop rows.
  const expand = (key = 'repo_health') =>
    fireEvent.click(screen.getByTestId(`loops-category-toggle-${key}`))

  it('renders the panel container', () => {
    render(<LoopsPanel loops={vm()} />)
    expect(screen.getByTestId('loops-panel')).toBeInTheDocument()
  })

  it('starts with every category collapsed (loop rows hidden)', () => {
    render(<LoopsPanel loops={vm()} />)
    expect(screen.getByTestId('loops-category-toggle-repo_health')).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('loop-row-ci_monitor')).toBeNull()
  })

  it('renders a category header with its count and ok/total badge', () => {
    render(<LoopsPanel loops={vm()} />)
    const header = screen.getByTestId('loops-category-toggle-repo_health')
    expect(header).toHaveTextContent('Repo Health')
    expect(header).toHaveTextContent('1/2')
  })

  it('renders a status dot per loop carrying its severity class', () => {
    render(<LoopsPanel loops={vm()} />)
    expand()
    expect(screen.getByTestId('loop-status-ci_monitor')).toHaveClass('ok')
    expect(screen.getByTestId('loop-status-flake_tracker')).toHaveClass('bad')
  })

  it('shows the live error on a bad loop and the stats line on an ok loop', () => {
    render(<LoopsPanel loops={vm()} />)
    expand()
    expect(screen.getByTestId('loop-message-flake_tracker')).toHaveTextContent('Flake tracker loop error')
    expect(screen.getByTestId('loop-message-ci_monitor')).toHaveTextContent('filed=0')
  })

  it('shows a restart badge when a loop has cycled', () => {
    render(<LoopsPanel loops={vm({
      categories: [{
        key: 'repo_health', name: 'Repo Health', count: 1, ok: 0,
        loops: [loop({ severity: 'warn', restarts: 3 })],
      }],
      totals: { ok: 0, total: 1, restarted: 1, disabled: 0 },
    })} />)
    expand()
    expect(screen.getByTestId('loop-restarts-ci_monitor')).toHaveTextContent('3')
  })

  it('expands a truncated message on click', () => {
    render(<LoopsPanel loops={vm()} />)
    expand()
    const msg = screen.getByTestId('loop-message-ci_monitor')
    expect(msg).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(msg)
    expect(msg).toHaveAttribute('aria-expanded', 'true')
  })

  it('toggles a category open then closed, showing/hiding its loop rows', () => {
    render(<LoopsPanel loops={vm()} />)
    expect(screen.queryByTestId('loop-row-ci_monitor')).toBeNull()
    expand()
    expect(screen.getByTestId('loop-row-ci_monitor')).toBeInTheDocument()
    expand()
    expect(screen.queryByTestId('loop-row-ci_monitor')).toBeNull()
  })

  it('remembers a category open state across remount (persisted)', () => {
    const { unmount } = render(<LoopsPanel loops={vm()} />)
    expand() // operator opens Repo Health
    expect(screen.getByTestId('loop-row-ci_monitor')).toBeInTheDocument()
    unmount()
    // Fresh mount (e.g. page reload): the remembered open state is restored.
    render(<LoopsPanel loops={vm()} />)
    expect(screen.getByTestId('loops-category-toggle-repo_health')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('loop-row-ci_monitor')).toBeInTheDocument()
  })

  it('renders the panel health badge from totals', () => {
    render(<LoopsPanel loops={vm()} />)
    expect(screen.getByTestId('loops-health')).toHaveTextContent('1/2')
  })

  it('shows an empty state when no loops have reported', () => {
    render(<LoopsPanel loops={{ categories: [], totals: { ok: 0, total: 0, restarted: 0, disabled: 0 } }} />)
    expect(screen.getByTestId('loops-empty')).toBeInTheDocument()
  })

  it('does not crash when given no loops prop', () => {
    render(<LoopsPanel />)
    expect(screen.getByTestId('loops-panel')).toBeInTheDocument()
    expect(screen.getByTestId('loops-empty')).toBeInTheDocument()
  })

  it('renders the canonical term as sub-text when the loop has one', () => {
    render(<LoopsPanel loops={vm({
      categories: [{
        key: 'repo_health', name: 'Repo Health', count: 1, ok: 1,
        loops: [loop({ name: 'Thrash Detector', term: 'Convergence Oscillation' })],
      }],
      totals: { ok: 1, total: 1, restarted: 0, disabled: 0 },
    })} />)
    expand()
    const term = screen.getByTestId('loop-term-ci_monitor')
    expect(term).toBeInTheDocument()
    expect(term).toHaveTextContent('Convergence Oscillation')
  })

  it('omits the term sub-text when the loop has no term', () => {
    render(<LoopsPanel loops={vm({
      categories: [{
        key: 'repo_health', name: 'Repo Health', count: 1, ok: 1,
        loops: [loop({ term: null })],
      }],
      totals: { ok: 1, total: 1, restarted: 0, disabled: 0 },
    })} />)
    expand()
    expect(screen.getByTestId('loop-row-ci_monitor')).toBeInTheDocument()
    expect(screen.queryByTestId('loop-term-ci_monitor')).toBeNull()
  })

  it('marks a disabled loop muted with an off badge', () => {
    render(<LoopsPanel loops={vm({
      categories: [{
        key: 'repo_health', name: 'Repo Health', count: 1, ok: 1,
        loops: [loop({ severity: 'muted', enabled: false })],
      }],
      totals: { ok: 1, total: 1, restarted: 0, disabled: 1 },
    })} />)
    expand()
    expect(screen.getByTestId('loop-status-ci_monitor')).toHaveClass('muted')
    expect(within(screen.getByTestId('loop-row-ci_monitor')).getByText('off')).toBeInTheDocument()
  })
})
