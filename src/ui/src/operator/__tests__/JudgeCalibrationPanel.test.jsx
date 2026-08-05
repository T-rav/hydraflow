import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { JudgeCalibrationPanel } from '../JudgeCalibrationPanel'

// JudgeCalibrationPanel (#10836) consumes the `toJudgeCalibration(...)` view
// model and renders each review judge's proper-scoring report — calibration
// (ECE) and discrimination (AUC) shown as SEPARATE axes. Tests pass VM literals
// (not raw payloads) to stay decoupled from the adapter, mirroring the
// FinderFaceplatePanel / SupervisorPanel component-test pattern.

const scoredRow = (over = {}) => ({
  judgeId: 'post_verify',
  judgeFamily: 'review_advisor',
  nResolved: 10,
  scored: true,
  status: 'scored',
  brier: 0.083,
  brierLabel: '0.083',
  logScore: 0.29,
  calibrationError: 0.05,
  calibrationLabel: '0.05',
  discrimination: 0.82,
  discriminationLabel: '0.82',
  discriminationUndefined: false,
  lowConfidence: false,
  provisional: false,
  ...over,
})

const pendingRow = (over = {}) => ({
  judgeId: 'consult',
  judgeFamily: 'review_advisor',
  nResolved: 0,
  scored: false,
  status: 'pending',
  label: 'awaiting resolved verdicts',
  ...over,
})

const vm = (over = {}) => ({
  total: 2,
  scoredCount: 1,
  resolvedTotal: 14,
  graceWindowDays: 7,
  headerLabel: '1 of 2 scored · 14 resolved',
  scored: [scoredRow()],
  pending: [pendingRow()],
  ...over,
})

describe('JudgeCalibrationPanel — header + scored rows', () => {
  it('renders the header and the glanceable scored/resolved count', () => {
    render(<JudgeCalibrationPanel calibration={vm()} />)
    const panel = screen.getByTestId('judge-calibration-panel')
    expect(panel).toHaveTextContent('Judges')
    expect(screen.getByTestId('judge-header')).toHaveTextContent('1 of 2 scored · 14 resolved')
  })

  it('renders the grace-window note explaining why judges can still be pending', () => {
    render(<JudgeCalibrationPanel calibration={vm()} />)
    expect(screen.getByTestId('judge-grace')).toHaveTextContent('7-day grace window')
  })

  it('renders a scored row with calibration (ECE), discrimination (AUC) and brier — kept separate', () => {
    render(<JudgeCalibrationPanel calibration={vm()} />)
    const row = screen.getByTestId('judge-row-post_verify')
    expect(row).toHaveTextContent('post_verify')
    expect(row).toHaveTextContent('review_advisor · 10 resolved')
    expect(within(row).getByTestId('judge-cal-post_verify')).toHaveTextContent('0.05')
    expect(within(row).getByTestId('judge-disc-post_verify')).toHaveTextContent('0.82')
    expect(within(row).getByTestId('judge-brier-post_verify')).toHaveTextContent('0.083')
  })

  it('renders AUC as "n/a" with an explaining title when discrimination is undefined', () => {
    render(<JudgeCalibrationPanel calibration={vm({
      scored: [scoredRow({ judgeId: 'mid_flight', discrimination: null, discriminationLabel: 'n/a', discriminationUndefined: true })],
    })} />)
    const disc = screen.getByTestId('judge-disc-mid_flight')
    expect(disc).toHaveTextContent('n/a')
    expect(disc).toHaveAttribute('title', expect.stringContaining('AUC'))
  })

  it('shows a provisional caveat marker (with an explaining title) on a low-confidence judge', () => {
    render(<JudgeCalibrationPanel calibration={vm({
      scored: [scoredRow({ judgeId: 'precheck', provisional: true, lowConfidence: true })],
    })} />)
    const marker = screen.getByTestId('judge-provisional-precheck')
    expect(marker).toHaveTextContent('provisional')
    expect(marker).toHaveAttribute('title', expect.stringContaining('provisional'))
  })

  it('omits the provisional marker on a confident, well-resolved judge', () => {
    render(<JudgeCalibrationPanel calibration={vm()} />)
    expect(screen.queryByTestId('judge-provisional-post_verify')).toBeNull()
    expect(screen.getByTestId('judge-status-post_verify')).toHaveTextContent('scored')
  })
})

describe('JudgeCalibrationPanel — pending + empty states', () => {
  it('renders a not-yet-resolved judge as a calm pending row, never an error', () => {
    render(<JudgeCalibrationPanel calibration={vm()} />)
    const pending = screen.getByTestId('judge-pending-consult')
    expect(pending).toHaveTextContent('consult')
    expect(pending).toHaveTextContent('awaiting resolved verdicts')
    expect(screen.getByTestId('judge-status-consult')).toHaveTextContent('pending')
  })

  it('shows a calm empty state when there are no judges', () => {
    render(<JudgeCalibrationPanel calibration={vm({
      total: 0, scoredCount: 0, resolvedTotal: 0, graceWindowDays: 0, headerLabel: 'no judges', scored: [], pending: [],
    })} />)
    expect(screen.getByTestId('judge-empty')).toHaveTextContent('no judge calibration')
    expect(screen.queryByTestId('judge-row-post_verify')).toBeNull()
  })

  it('renders the empty state without a calibration prop (backward-compatible default)', () => {
    render(<JudgeCalibrationPanel />)
    expect(screen.getByTestId('judge-calibration-panel')).toBeInTheDocument()
    expect(screen.getByTestId('judge-empty')).toBeInTheDocument()
  })
})
