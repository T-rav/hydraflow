/**
 * FinderFaceplatePanel — the noise-floor-vs-live-rate readout (#10826).
 *
 * Pure presentational component. Consumes the `toFinderFaceplates(...)` view
 * model (one row per generative finder — each finder's measured noise floor
 * joined against its live finding-rate) and renders, in the vitals column:
 *
 *   - a header: "Finders" + one glanceable count ("2 of 6 calibrated; 1 above
 *     floor"), so an operator sees at a glance how much of the fleet is measured
 *     and how many finders are firing above their own noise;
 *   - one row per CALIBRATED finder — finder id + signal class, the noise floor
 *     (mean ± sigma, or "±0 deterministic" for a zero-variance floor), the
 *     actuation threshold, the live finding-rate, and a status chip. A finder
 *     whose live rate sits WITHIN its floor (calm) is a gain-down candidate; one
 *     ABOVE floor (⚠) is earning its keep. A provisional marker flags a floor
 *     measured against an unvetted baseline or too few samples; a stale marker
 *     flags an aged baseline;
 *   - the uncalibrated (deferred LLM) finders beneath, each rendering a calm
 *     "pending — run calibration" — pending is not an error.
 *
 * DEFERRED (later phases, deliberately absent here):
 *   - No sparkline: the endpoint hands a single point value per finder (the
 *     latest floor + a windowed live rate), not a time series — a floor/live-rate
 *     history feed is a future phase.
 *   - No setpoint line / auto-quiescent-manual dial: a control setpoint needs the
 *     floor→setpoint conversion from #10824, which this slice does not yet carry.
 *
 * Load-bearing contracts the tests pin:
 *   - a calibrated row shows its floor / threshold / live rate + status chip;
 *   - an above-floor finder renders the ⚠ warning-toned chip;
 *   - a provisional (low-confidence / unvetted-baseline) floor shows a caveat
 *     marker whose title explains it;
 *   - an uncalibrated finder renders the calm pending state, never an error;
 *   - an empty / failed feed renders a calm empty state, never a crash;
 *   - every colour / space value resolves from the token layer via `useTokens()`
 *     — no inline `style={{…}}` literal, no hardcoded hex — so light + dark fall
 *     out of the console's ThemeProvider (inline-style + colour + border ratchets).
 */

import React from 'react'
import { useTokens, Text, Badge } from '../styles/primitives'
import {
  EMPTY_FINDER_FACEPLATES_VM,
  STATUS_ABOVE_FLOOR,
  STATUS_WITHIN_FLOOR,
} from './model/finderFaceplates'

// status → the status chip's { label, tone }. within_floor is calm (the finder
// is indistinguishable from its own noise); above_floor warns; uncalibrated is
// neutral "pending".
const STATUS_CHIP = {
  [STATUS_WITHIN_FLOOR]: { label: 'within floor', tone: 'success' },
  [STATUS_ABOVE_FLOOR]: { label: '⚠ above', tone: 'warning' },
}
const PENDING_CHIP = { label: 'pending', tone: 'neutral' }

const PROVISIONAL_TITLE = 'floor from an unvetted baseline — treat as provisional'
const STALE_TITLE = 'baseline has aged past its freshness window — re-vet the golden baseline'

function makeStyles(t) {
  return {
    card: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      padding: t.space.sm,
      boxSizing: 'border-box',
    },
    header: { display: 'flex', alignItems: 'baseline', gap: t.space.sm },
    spacer: { flex: '1 1 auto' },
    empty: { padding: `${t.space.xs}px 0` },
    row: {
      display: 'flex',
      alignItems: 'baseline',
      flexWrap: 'wrap',
      gap: t.space.sm,
      padding: `${t.space.xxs}px ${t.space.xs}px`,
    },
    nameCol: { display: 'flex', flexDirection: 'column', minWidth: 0, flex: '1 1 auto' },
    name: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    metrics: { display: 'flex', alignItems: 'baseline', gap: t.space.sm, flexShrink: 0 },
    metric: { display: 'inline-flex', alignItems: 'baseline', gap: t.space.xxs },
    markers: { display: 'inline-flex', alignItems: 'center', gap: t.space.xxs, flexShrink: 0 },
    pendingMsg: { flex: '1 1 auto', minWidth: 0 },
    // The uncalibrated finders sit below a token divider (borderTop longhand only
    // — never mixed with the `border` shorthand, per the border-shorthand guard).
    pendingWrap: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xxs,
      marginTop: t.space.xs,
      paddingTop: t.space.xs,
      borderTop: `1px solid ${t.color.border}`,
    },
  }
}

/** One labelled metric: a muted caption + its value (e.g. "floor 15 ±0 deterministic"). */
function Metric({ label, value, styles, testid }) {
  return (
    <span style={styles.metric} data-testid={testid}>
      <Text as="span" size="xs" tone="muted" uppercase>{label}</Text>
      <Text as="span" size="sm" weight="semibold">{value}</Text>
    </span>
  )
}

/** One calibrated finder: identity + floor / threshold / live rate + status chip. */
function CalibratedRow({ row, styles }) {
  const chip = STATUS_CHIP[row.status] ?? PENDING_CHIP
  return (
    <div data-testid={`faceplate-row-${row.finderId}`} style={styles.row}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{row.finderId}</Text>
        <Text as="span" size="xs" tone="muted">{row.signalClass}</Text>
      </span>
      <span style={styles.metrics}>
        <Metric label="floor" value={row.floorLabel} styles={styles} testid={`faceplate-floor-${row.finderId}`} />
        <Metric label="thr" value={row.threshold} styles={styles} testid={`faceplate-threshold-${row.finderId}`} />
        <Metric
          label="live"
          value={row.liveRate == null ? '—' : row.liveRate}
          styles={styles}
          testid={`faceplate-live-${row.finderId}`}
        />
      </span>
      <span style={styles.markers}>
        {row.provisional && (
          <Badge tone="warning" title={PROVISIONAL_TITLE} data-testid={`faceplate-provisional-${row.finderId}`}>
            provisional
          </Badge>
        )}
        {row.stale && (
          <Badge tone="warning" title={STALE_TITLE} data-testid={`faceplate-stale-${row.finderId}`}>
            stale
          </Badge>
        )}
        <Badge tone={chip.tone} data-testid={`faceplate-status-${row.finderId}`}>{chip.label}</Badge>
      </span>
    </div>
  )
}

/** One uncalibrated finder: identity + a calm "pending — run calibration". */
function PendingRow({ row, styles }) {
  return (
    <div data-testid={`faceplate-pending-${row.finderId}`} style={styles.row}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{row.finderId}</Text>
        <Text as="span" size="xs" tone="muted">{row.signalClass}</Text>
      </span>
      <Text size="sm" tone="muted" style={styles.pendingMsg}>{row.label}</Text>
      <Badge tone={PENDING_CHIP.tone} data-testid={`faceplate-status-${row.finderId}`}>{PENDING_CHIP.label}</Badge>
    </div>
  )
}

/**
 * @param {{ faceplates?: ReturnType<typeof import('./model/finderFaceplates').toFinderFaceplates> }} props
 */
export function FinderFaceplatePanel({ faceplates = EMPTY_FINDER_FACEPLATES_VM }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const { headerLabel, aboveFloorCount, calibrated, pending } = faceplates
  const isEmpty = calibrated.length === 0 && pending.length === 0

  return (
    <div data-testid="finder-faceplate-panel" style={styles.card}>
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Finders</Text>
        <Badge tone={aboveFloorCount > 0 ? 'warning' : 'neutral'} data-testid="faceplate-header">
          {headerLabel}
        </Badge>
        <span style={styles.spacer} />
      </div>

      {isEmpty ? (
        <Text size="sm" tone="muted" style={styles.empty} data-testid="faceplate-empty">
          no finder faceplates — run calibration
        </Text>
      ) : (
        <>
          {calibrated.map(row => (
            <CalibratedRow key={row.finderId} row={row} styles={styles} />
          ))}
          {pending.length > 0 && (
            <div style={styles.pendingWrap} data-testid="faceplate-pending">
              {pending.map(row => (
                <PendingRow key={row.finderId} row={row} styles={styles} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default FinderFaceplatePanel
