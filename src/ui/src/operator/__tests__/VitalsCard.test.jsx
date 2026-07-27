import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { VitalsCard } from '../VitalsCard'

// VitalsCard (epic #10556, Task 6) consumes the Task-1 `toVitals(...)` view
// model and renders one color-coded row per vital: factory run-state, loop
// health (ok/total), recently-restarted loops, credit state, and main↔staging
// sync. Each row carries an `ok` | `warn` | `bad` severity class so operators
// can read factory health at a glance. These tests pin the severity → class
// mapping per row, since the class *is* the color-coding contract.

// A fully-healthy vitals VM — every row should read `ok`.
function healthyVitals(overrides = {}) {
  return {
    factory: { state: 'running', reason: null },
    loopsHealthy: { ok: 12, total: 12 },
    restarts: [],
    credits: { paused: false, pausedUntil: null, provider: null },
    mainStagingSync: { state: 'in_sync', openPrNumber: null },
    ...overrides,
  }
}

describe('VitalsCard', () => {
  it('renders every vital with the ok class for a fully-healthy VM', () => {
    render(<VitalsCard vitals={healthyVitals()} />)
    expect(screen.getByTestId('vitals-card')).toBeInTheDocument()
    for (const key of ['factory', 'loops', 'restarts', 'credits', 'sync']) {
      expect(screen.getByTestId(`vital-${key}`)).toHaveClass('ok')
    }
  })

  it('shows a restarted loop as bad and names the loop + count', () => {
    render(
      <VitalsCard vitals={healthyVitals({ restarts: [{ loop: 'triage_loop', count: 2 }] })} />,
    )
    const row = screen.getByTestId('vital-restarts')
    expect(row).toHaveClass('bad')
    expect(row).toHaveTextContent('triage_loop')
    expect(row).toHaveTextContent('2')
  })

  it('shows a paused factory as warn with its reason', () => {
    const vm = healthyVitals({
      factory: { state: 'paused', reason: 'credits paused until 2026-07-29T00:00:00Z' },
    })
    render(<VitalsCard vitals={vm} />)
    const row = screen.getByTestId('vital-factory')
    expect(row).toHaveClass('warn')
    expect(row).toHaveTextContent('credits paused until 2026-07-29T00:00:00Z')
  })

  it('marks loop health bad when not all loops are healthy', () => {
    render(<VitalsCard vitals={healthyVitals({ loopsHealthy: { ok: 10, total: 12 } })} />)
    const row = screen.getByTestId('vital-loops')
    expect(row).toHaveClass('bad')
    expect(row).toHaveTextContent('10/12')
  })

  it('marks credits bad when paused and shows provider + resume time', () => {
    const vm = healthyVitals({
      credits: { paused: true, pausedUntil: '2026-07-29T00:00:00Z', provider: 'anthropic' },
    })
    render(<VitalsCard vitals={vm} />)
    const row = screen.getByTestId('vital-credits')
    expect(row).toHaveClass('bad')
    expect(row).toHaveTextContent('anthropic')
    expect(row).toHaveTextContent('2026-07-29T00:00:00Z')
  })

  it('marks main↔staging sync warn when behind and shows the open RC PR number', () => {
    render(
      <VitalsCard
        vitals={healthyVitals({ mainStagingSync: { state: 'behind', openPrNumber: 555 } })}
      />,
    )
    const row = screen.getByTestId('vital-sync')
    expect(row).toHaveClass('warn')
    expect(row).toHaveTextContent('555')
  })

  it('marks main↔staging sync warn when the promotion signal is unknown', () => {
    render(
      <VitalsCard
        vitals={healthyVitals({ mainStagingSync: { state: 'unknown', openPrNumber: null } })}
      />,
    )
    expect(screen.getByTestId('vital-sync')).toHaveClass('warn')
  })
})
