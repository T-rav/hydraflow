import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ConsoleHeader } from '../ConsoleHeader'

// The ConsoleHeader (epic #10556, Task 8) is the operator console's header slot.
// It consumes the Task-1 vitals view model (`toVitals`) for the run-state pill
// (+ credit reason when paused) and aggregate vitals, the Task-2 breadcrumb +
// `select` for the clickable trail, and the existing orchestrator control calls
// (`startOrchestrator` / `stopOrchestrator` / `clearCreditPause`, the same ones
// the legacy Header.jsx uses) threaded in as `onStart` / `onStop` / `onClear`.
// Presentation only — no socket, no endpoint logic reinvented here.

function makeVitals(overrides = {}) {
  return {
    factory: { state: 'running', reason: null },
    loopsHealthy: { ok: 11, total: 12 },
    restarts: [],
    credits: { paused: false, pausedUntil: null, provider: null },
    mainStagingSync: { state: 'in_sync', openPrNumber: null },
    ...overrides,
  }
}

function makeBreadcrumb() {
  return [
    { kind: 'repo', label: 'All repos', value: null },
    { kind: 'repo', label: 'acme/web', value: 'acme/web' },
    { kind: 'stage', label: 'Plan', value: 'plan' },
  ]
}

describe('ConsoleHeader', () => {
  it('renders the header container and embeds the breadcrumb trail', () => {
    render(<ConsoleHeader vitals={makeVitals()} breadcrumb={makeBreadcrumb()} select={() => {}} />)
    expect(screen.getByTestId('console-header')).toBeInTheDocument()
    // The breadcrumb is embedded and reflects the current depth.
    expect(screen.getByTestId('operator-breadcrumb')).toBeInTheDocument()
    expect(screen.getByTestId('console-header')).toHaveTextContent('acme/web')
    expect(screen.getByTestId('console-header')).toHaveTextContent('Plan')
  })

  it('run-state pill reflects the orchestrator status', () => {
    const { rerender } = render(<ConsoleHeader vitals={makeVitals({ factory: { state: 'running', reason: null } })} />)
    const pill = screen.getByTestId('console-header-runstate')
    expect(pill).toHaveTextContent(/running/i)
    expect(pill).toHaveAttribute('data-state', 'running')

    rerender(<ConsoleHeader vitals={makeVitals({ factory: { state: 'idle', reason: null } })} />)
    expect(screen.getByTestId('console-header-runstate')).toHaveTextContent(/idle/i)
    expect(screen.getByTestId('console-header-runstate')).toHaveAttribute('data-state', 'idle')
  })

  it('shows the credit reason when the factory is paused on credits', () => {
    const vitals = makeVitals({
      factory: { state: 'paused', reason: 'credits paused until 2026-07-26T18:00:00Z' },
      credits: { paused: true, pausedUntil: '2026-07-26T18:00:00Z', provider: 'anthropic' },
    })
    render(<ConsoleHeader vitals={vitals} />)
    expect(screen.getByTestId('console-header-runstate')).toHaveAttribute('data-state', 'paused')
    const reason = screen.getByTestId('console-header-credit-reason')
    expect(reason).toHaveTextContent('credits paused until 2026-07-26T18:00:00Z')
    // The provider that ran out of credits is surfaced too.
    expect(reason).toHaveTextContent('anthropic')
  })

  it('does not render a credit reason when the factory is not credit-paused', () => {
    render(<ConsoleHeader vitals={makeVitals()} />)
    expect(screen.queryByTestId('console-header-credit-reason')).toBeNull()
  })

  it('renders aggregate vitals (loop health)', () => {
    render(<ConsoleHeader vitals={makeVitals({ loopsHealthy: { ok: 9, total: 12 } })} />)
    expect(screen.getByTestId('console-header-loops')).toHaveTextContent('9/12')
  })

  it('invokes the existing stop control when Stop is clicked while running', () => {
    const onStop = vi.fn()
    render(<ConsoleHeader vitals={makeVitals({ factory: { state: 'running', reason: null } })} connected onStop={onStop} />)
    const stop = screen.getByTestId('console-header-stop')
    expect(stop).not.toBeDisabled()
    fireEvent.click(stop)
    expect(onStop).toHaveBeenCalledTimes(1)
  })

  it('invokes the existing start control when Start is clicked while idle', () => {
    const onStart = vi.fn()
    render(<ConsoleHeader vitals={makeVitals({ factory: { state: 'idle', reason: null } })} connected onStart={onStart} />)
    const start = screen.getByTestId('console-header-start')
    expect(start).not.toBeDisabled()
    fireEvent.click(start)
    expect(onStart).toHaveBeenCalledTimes(1)
  })

  it('invokes the existing clear-credit-pause control when Clear is clicked while paused', () => {
    const onClear = vi.fn()
    const vitals = makeVitals({
      factory: { state: 'paused', reason: 'credits paused until X' },
      credits: { paused: true, pausedUntil: 'X', provider: 'anthropic' },
    })
    render(<ConsoleHeader vitals={vitals} connected onClear={onClear} />)
    const clear = screen.getByTestId('console-header-clear')
    expect(clear).not.toBeDisabled()
    fireEvent.click(clear)
    expect(onClear).toHaveBeenCalledTimes(1)
  })

  it('disables the controls when disconnected from the server', () => {
    render(<ConsoleHeader vitals={makeVitals({ factory: { state: 'idle', reason: null } })} connected={false} onStart={() => {}} />)
    expect(screen.getByTestId('console-header-start')).toBeDisabled()
  })

  it('breadcrumb segments call select to pop to that depth', () => {
    const select = vi.fn()
    render(<ConsoleHeader vitals={makeVitals()} breadcrumb={makeBreadcrumb()} select={select} />)
    fireEvent.click(screen.getByTestId('breadcrumb-crumb-1'))
    expect(select).toHaveBeenCalledWith('repo', 'acme/web')
  })

  it('does not crash with no vitals / no handlers', () => {
    render(<ConsoleHeader />)
    expect(screen.getByTestId('console-header')).toBeInTheDocument()
  })
})
