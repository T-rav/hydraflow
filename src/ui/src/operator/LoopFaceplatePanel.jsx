/**
 * LoopFaceplatePanel — per-loop control faceplates (#10826).
 *
 * Pure presentational component. Consumes the `toLoopFaceplates(...)` view
 * model (one row per `control/fleet.yaml` entry, statically served by
 * `/api/diagnostics/loop-faceplates` and joined client-side against the
 * live `backgroundWorkers` WS slice) and renders:
 *
 *   - a header: "Loops" + one glanceable line ("65 loops · 2 convertible ·
 *     1 regulating");
 *   - one row per loop in the REGULATOR section (convertible + error_driven):
 *     worker name + PV label, the setpoint cell ("0.90 ±0.05 fraction" with
 *     an "unsigned" badge while the proposal awaits a human signature, or
 *     "signed: <by>"), the live PV (or —), the floor sigma when calibrated,
 *     and a mode lamp: AUTO (regulating, acting), QUIESCENT (regulating,
 *     in-band — silence is the correct output), or — (unconverted);
 *   - a collapsed census line for the exploratory + infrastructure classes —
 *     they carry no control surface, so they earn one line, not 45 rows.
 *
 * DEFERRED (deliberately absent):
 *   - Mode-dial WRITES (gain / threshold / cadence changes) — the supervisor
 *     panel precedent shipped read-only first, actions second (#11002).
 *   - Promotion to the primary-surface faceplate grid — the #10942 zone work
 *     (exception strip) governs that layout; this slice mounts in the vitals
 *     rail like its finder sibling.
 *   - Settling status: the sensing-ladder engines have no production
 *     producer yet — rendered as nothing, never invented.
 *
 * Honesty contracts the tests pin:
 *   - a loop without regulator keys in its live details renders — (mode
 *     unconverted), never a fabricated PV of 0;
 *   - an UNSIGNED setpoint shows its proposed value WITH the unsigned badge —
 *     visible but visibly inert;
 *   - QUIESCENT renders as a calm success tone — it is a correct state, not
 *     a fault;
 *   - an empty / failed feed renders a calm empty state, never a crash;
 *   - all colour / space from the token layer (inline-style + colour ratchets).
 */

import React from 'react'
import { useTokens, Text, Badge } from '../styles/primitives'
import {
  EMPTY_LOOP_FACEPLATES_VM,
  MODE_AUTO,
  MODE_QUIESCENT,
} from './model/loopFaceplates'

// mode → lamp { label, tone }. AUTO acts; QUIESCENT is calm-by-design;
// unconverted is neutral absence.
const MODE_LAMP = {
  [MODE_AUTO]: { label: 'AUTO', tone: 'warning' },
  [MODE_QUIESCENT]: { label: 'QUIESCENT', tone: 'success' },
}
const UNCONVERTED_LAMP = { label: '—', tone: 'neutral' }

const UNSIGNED_TITLE =
  'machine-proposed setpoint awaiting a human signature — inert until signed'

/** The regulator-shaped classes that earn a full faceplate row. */
const REGULATOR_CLASSES = new Set(['convertible', 'error_driven'])

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
    lamp: { display: 'inline-flex', alignItems: 'center', gap: t.space.xxs, flexShrink: 0 },
    // Census line under a token divider (borderTop longhand only — never the
    // `border` shorthand, per the border-shorthand guard).
    census: {
      marginTop: t.space.xs,
      paddingTop: t.space.xs,
      borderTop: `1px solid ${t.color.border}`,
    },
  }
}

function setpointLabel(sp) {
  const units = sp.units ? ` ${sp.units}` : ''
  return `${sp.value} ±${sp.band}${units}`
}

/** One labelled metric: a muted caption + its value. */
function Metric({ label, value, styles, testid }) {
  return (
    <span style={styles.metric} data-testid={testid}>
      <Text as="span" size="xs" tone="muted" uppercase>{label}</Text>
      <Text as="span" size="sm" weight="semibold">{value}</Text>
    </span>
  )
}

/** One regulator-class loop: identity + setpoint + live PV + mode lamp. */
function RegulatorRow({ row, styles }) {
  const lamp = MODE_LAMP[row.mode] ?? UNCONVERTED_LAMP
  return (
    <div data-testid={`loop-faceplate-row-${row.workerName}`} style={styles.row}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{row.workerName}</Text>
        <Text as="span" size="xs" tone="muted">{row.pvLabel || row.controlClass}</Text>
      </span>
      <span style={styles.metrics}>
        {row.setpoint && (
          <span style={styles.metric} data-testid={`loop-faceplate-setpoint-${row.workerName}`}>
            <Text as="span" size="xs" tone="muted" uppercase>sp</Text>
            <Text as="span" size="sm" weight="semibold">{setpointLabel(row.setpoint)}</Text>
            {row.setpoint.signed ? (
              <Badge tone="success" data-testid={`loop-faceplate-signed-${row.workerName}`}>
                signed: {row.setpoint.signedBy}
              </Badge>
            ) : (
              <Badge
                tone="warning"
                title={UNSIGNED_TITLE}
                data-testid={`loop-faceplate-unsigned-${row.workerName}`}
              >
                unsigned
              </Badge>
            )}
          </span>
        )}
        <Metric
          label="pv"
          value={row.live.pv == null ? '—' : row.live.pv}
          styles={styles}
          testid={`loop-faceplate-pv-${row.workerName}`}
        />
        {row.floorSigma != null && (
          <Metric
            label="σ floor"
            value={row.floorSigma}
            styles={styles}
            testid={`loop-faceplate-sigma-${row.workerName}`}
          />
        )}
      </span>
      <span style={styles.lamp}>
        <Badge tone={lamp.tone} data-testid={`loop-faceplate-mode-${row.workerName}`}>
          {lamp.label}
        </Badge>
      </span>
    </div>
  )
}

/**
 * @param {{ faceplates?: ReturnType<typeof import('./model/loopFaceplates').toLoopFaceplates> }} props
 */
export function LoopFaceplatePanel({ faceplates = EMPTY_LOOP_FACEPLATES_VM }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const { headerLabel, byClass, rows, regulatingCount } = faceplates
  const regulators = rows.filter(r => REGULATOR_CLASSES.has(r.controlClass))
  const exploratory = Number(byClass.exploratory ?? 0)
  const infrastructure = Number(byClass.infrastructure ?? 0)

  return (
    <div data-testid="loop-faceplate-panel" style={styles.card}>
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Control</Text>
        <Badge
          tone={regulatingCount > 0 ? 'success' : 'neutral'}
          data-testid="loop-faceplate-header"
        >
          {headerLabel}
        </Badge>
        <span style={styles.spacer} />
      </div>

      {rows.length === 0 ? (
        <Text size="sm" tone="muted" style={styles.empty} data-testid="loop-faceplate-empty">
          no control register — is control/fleet.yaml readable?
        </Text>
      ) : (
        <>
          {regulators.map(row => (
            <RegulatorRow key={row.workerName} row={row} styles={styles} />
          ))}
          <Text
            size="xs"
            tone="muted"
            style={styles.census}
            data-testid="loop-faceplate-census"
          >
            {exploratory} exploratory · {infrastructure} infrastructure — no plant
            setpoints (meta-setpoints only)
          </Text>
        </>
      )}
    </div>
  )
}

export default LoopFaceplatePanel
