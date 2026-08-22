import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { FinderFaceplatePanel } from '../FinderFaceplatePanel'

// FinderFaceplatePanel (#10826) consumes the `toFinderFaceplates(...)` view model
// and renders each generative finder's noise floor vs its live finding-rate.
// Tests pass VM literals (not raw payloads) to stay decoupled from the adapter
// internals, mirroring the CostPanel / SupervisorPanel component-test pattern.

const calibratedRow = (over = {}) => ({
  finderId: 'edge_proposer',
  signalClass: 'edges',
  calibrated: true,
  status: 'above_floor',
  liveRate: 41,
  floorMean: 39,
  floorSigma: 1.5,
  floorLabel: '39 ± 1.5',
  threshold: 39,
  sampleCount: 5,
  lowConfidence: false,
  baselineVetted: true,
  baselineStale: false,
  baselineSha: 'abc1234',
  lastCalibrated: '2026-08-01T00:00:00+00:00',
  driftDays: 2,
  provisional: false,
  stale: false,
  label: 'live 41 vs floor 39 ± 1.5',
  ...over,
})

const pendingRow = (over = {}) => ({
  finderId: 'erosion_metrics',
  signalClass: 'erosion',
  calibrated: false,
  status: 'uncalibrated',
  liveRate: null,
  label: 'pending — run calibration',
  ...over,
})

const vm = (over = {}) => ({
  total: 2,
  calibratedCount: 1,
  aboveFloorCount: 1,
  headerLabel: '1 of 2 calibrated; 1 above floor',
  calibrated: [calibratedRow()],
  pending: [pendingRow()],
  ...over,
})

describe('FinderFaceplatePanel — header + rows', () => {
  it('renders the header and the glanceable calibrated/above-floor count', () => {
    render(<FinderFaceplatePanel faceplates={vm()} />)
    const panel = screen.getByTestId('finder-faceplate-panel')
    expect(panel).toHaveTextContent('Finders')
    expect(screen.getByTestId('faceplate-header')).toHaveTextContent('1 of 2 calibrated; 1 above floor')
  })

  it('renders a calibrated row with its floor, threshold and live rate', () => {
    render(<FinderFaceplatePanel faceplates={vm()} />)
    const row = screen.getByTestId('faceplate-row-edge_proposer')
    expect(row).toHaveTextContent('edge_proposer')
    expect(row).toHaveTextContent('edges')
    expect(within(row).getByTestId('faceplate-floor-edge_proposer')).toHaveTextContent('39 ± 1.5')
    expect(within(row).getByTestId('faceplate-threshold-edge_proposer')).toHaveTextContent('39')
    expect(within(row).getByTestId('faceplate-live-edge_proposer')).toHaveTextContent('41')
  })

  it('renders a deterministic zero-variance floor as "±0 deterministic"', () => {
    render(<FinderFaceplatePanel faceplates={vm({
      calibrated: [calibratedRow({ finderId: 'wiki_rot', floorSigma: 0, floorLabel: '15 ±0 deterministic', threshold: 15, liveRate: 18 })],
    })} />)
    expect(screen.getByTestId('faceplate-floor-wiki_rot')).toHaveTextContent('15 ±0 deterministic')
  })

  it('renders the ⚠ above-floor warning chip for an above_floor finder', () => {
    render(<FinderFaceplatePanel faceplates={vm()} />)
    expect(screen.getByTestId('faceplate-status-edge_proposer')).toHaveTextContent('above')
  })

  it('renders the calm within-floor chip for a within_floor (gain-down candidate) finder', () => {
    render(<FinderFaceplatePanel faceplates={vm({
      calibrated: [calibratedRow({ finderId: 'entry_evidence', status: 'within_floor', liveRate: 0, threshold: 0, floorLabel: '0 ±0 deterministic' })],
      aboveFloorCount: 0,
    })} />)
    expect(screen.getByTestId('faceplate-status-entry_evidence')).toHaveTextContent('within floor')
  })

  it('shows a provisional caveat marker (with an explaining title) on a low-confidence / unvetted floor', () => {
    render(<FinderFaceplatePanel faceplates={vm({
      calibrated: [calibratedRow({ finderId: 'wiki_rot', provisional: true })],
    })} />)
    const marker = screen.getByTestId('faceplate-provisional-wiki_rot')
    expect(marker).toHaveTextContent('provisional')
    expect(marker).toHaveAttribute('title', expect.stringContaining('unvetted baseline'))
  })

  it('omits the provisional marker on a confident, vetted floor', () => {
    render(<FinderFaceplatePanel faceplates={vm()} />)
    expect(screen.queryByTestId('faceplate-provisional-edge_proposer')).toBeNull()
  })

  it('shows a staleness marker when the baseline is stale', () => {
    render(<FinderFaceplatePanel faceplates={vm({
      calibrated: [calibratedRow({ finderId: 'wiki_rot', stale: true, baselineStale: true })],
    })} />)
    expect(screen.getByTestId('faceplate-stale-wiki_rot')).toHaveTextContent('stale')
  })
})

describe('FinderFaceplatePanel — pending + empty states', () => {
  it('renders an uncalibrated finder as a calm pending row, never an error', () => {
    render(<FinderFaceplatePanel faceplates={vm()} />)
    const pending = screen.getByTestId('faceplate-pending-erosion_metrics')
    expect(pending).toHaveTextContent('erosion_metrics')
    expect(pending).toHaveTextContent('pending — run calibration')
    expect(screen.getByTestId('faceplate-status-erosion_metrics')).toHaveTextContent('pending')
  })

  it('shows a calm empty state when there are no finders', () => {
    render(<FinderFaceplatePanel faceplates={vm({
      total: 0, calibratedCount: 0, aboveFloorCount: 0, headerLabel: 'no finders', calibrated: [], pending: [],
    })} />)
    expect(screen.getByTestId('faceplate-empty')).toHaveTextContent('no finder faceplates')
    expect(screen.queryByTestId('faceplate-row-edge_proposer')).toBeNull()
  })

  it('renders the empty state without a faceplates prop (backward-compatible default)', () => {
    render(<FinderFaceplatePanel />)
    expect(screen.getByTestId('finder-faceplate-panel')).toBeInTheDocument()
    expect(screen.getByTestId('faceplate-empty')).toBeInTheDocument()
  })
})
