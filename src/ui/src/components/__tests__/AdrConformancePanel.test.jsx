import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { AdrConformancePanel } = await import('../AdrConformancePanel')

function defaultContext(overrides = {}) {
  return {
    adrConformance: {},
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultContext())
})

describe('AdrConformancePanel', () => {
  it('shows empty state when adrConformance is empty', () => {
    render(<AdrConformancePanel />)
    expect(screen.getByTestId('adr-conformance-panel-root')).toBeInTheDocument()
    expect(screen.getByText('No ADR conformance data available yet.')).toBeInTheDocument()
  })

  it('shows empty state when adrConformance is null', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({ adrConformance: null }))
    render(<AdrConformancePanel />)
    expect(screen.getByText('No ADR conformance data available yet.')).toBeInTheDocument()
  })

  it('renders per-ADR rows with adr_id, kind, outcome, and check count', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      adrConformance: {
        'ADR-0100': {
          adr_id: 'ADR-0100',
          kind: 'enforced',
          outcome: 'pass',
          checks: [
            { check: 'pytest tests/test_adr_conformance.py', outcome: 'pass', duration_s: 1.2, detail: null },
          ],
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<AdrConformancePanel />)
    expect(screen.getByTestId('adr-conformance-row-ADR-0100')).toBeInTheDocument()
    expect(screen.getByTestId('adr-conformance-id-ADR-0100')).toBeInTheDocument()
    expect(screen.getByText('enforced')).toBeInTheDocument()
    expect(screen.getByTestId('adr-conformance-outcome-badge-pass')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('renders manual and decision-of-record kinds', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      adrConformance: {
        'ADR-0042': {
          adr_id: 'ADR-0042',
          kind: 'manual',
          outcome: 'manual',
          checks: [],
          timestamp: '2026-06-30T00:00:00Z',
        },
        'ADR-0001': {
          adr_id: 'ADR-0001',
          kind: 'decision-of-record',
          outcome: 'skipped',
          checks: [],
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<AdrConformancePanel />)
    expect(screen.getAllByText('manual').length).toBeGreaterThan(0)
    expect(screen.getByText('decision-of-record')).toBeInTheDocument()
    expect(screen.getByTestId('adr-conformance-outcome-badge-manual')).toBeInTheDocument()
    expect(screen.getByTestId('adr-conformance-outcome-badge-skipped')).toBeInTheDocument()
  })

  it('color-codes fail and unresolved outcomes distinctly from pass', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      adrConformance: {
        'ADR-0002': {
          adr_id: 'ADR-0002',
          kind: 'enforced',
          outcome: 'fail',
          checks: [],
          timestamp: '2026-06-30T00:00:00Z',
        },
        'ADR-0003': {
          adr_id: 'ADR-0003',
          kind: 'enforced',
          outcome: 'unresolved',
          checks: [],
          timestamp: '2026-06-30T00:00:00Z',
        },
        'ADR-0004': {
          adr_id: 'ADR-0004',
          kind: 'enforced',
          outcome: 'pass',
          checks: [],
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<AdrConformancePanel />)
    const failBadge = screen.getByTestId('adr-conformance-outcome-badge-fail')
    const unresolvedBadge = screen.getByTestId('adr-conformance-outcome-badge-unresolved')
    const passBadge = screen.getByTestId('adr-conformance-outcome-badge-pass')
    expect(failBadge.style.color).not.toBe(passBadge.style.color)
    expect(unresolvedBadge.style.color).not.toBe(passBadge.style.color)
  })

  it('sorts rows by adr_id alphabetically', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      adrConformance: {
        'ADR-0100': { adr_id: 'ADR-0100', kind: 'enforced', outcome: 'pass', checks: [], timestamp: '2026-06-30T00:00:00Z' },
        'ADR-0001': { adr_id: 'ADR-0001', kind: 'enforced', outcome: 'pass', checks: [], timestamp: '2026-06-30T00:00:00Z' },
        'ADR-0042': { adr_id: 'ADR-0042', kind: 'enforced', outcome: 'pass', checks: [], timestamp: '2026-06-30T00:00:00Z' },
      },
    }))
    render(<AdrConformancePanel />)
    const rows = screen.getByTestId('adr-conformance-rows')
    const rowElements = rows.querySelectorAll('[data-testid^="adr-conformance-row-"]')
    const ids = Array.from(rowElements).map(el => el.getAttribute('data-testid').replace('adr-conformance-row-', ''))
    expect(ids).toEqual(['ADR-0001', 'ADR-0042', 'ADR-0100'])
  })

  it('renders individual check names and outcomes', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      adrConformance: {
        'ADR-0100': {
          adr_id: 'ADR-0100',
          kind: 'enforced',
          outcome: 'fail',
          checks: [
            { check: 'make quality', outcome: 'fail', duration_s: 3.4, detail: 'boom' },
            { check: 'pytest tests/test_x.py', outcome: 'pass', duration_s: 0.5, detail: null },
          ],
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<AdrConformancePanel />)
    const checksEl = screen.getByTestId('adr-conformance-checks')
    expect(checksEl).toBeInTheDocument()
    expect(checksEl.textContent).toContain('make quality')
    expect(checksEl.textContent).toContain('pytest tests/test_x.py')
  })

  it('renders zero checks as "0", not blank', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      adrConformance: {
        'ADR-0007': {
          adr_id: 'ADR-0007',
          kind: 'decision-of-record',
          outcome: 'skipped',
          checks: [],
          timestamp: '2026-06-30T00:00:00Z',
        },
      },
    }))
    render(<AdrConformancePanel />)
    const row = screen.getByTestId('adr-conformance-row-ADR-0007')
    expect(row.textContent).toContain('0')
  })
})
