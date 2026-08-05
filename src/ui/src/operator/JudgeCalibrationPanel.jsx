/**
 * JudgeCalibrationPanel — the review-judge proper-scoring readout (#10836).
 *
 * Pure presentational component. Consumes the `toJudgeCalibration(...)` view
 * model (one row per review judge — each judge's calibration + discrimination
 * scored against the escape ledger) and renders, in the vitals column:
 *
 *   - a header: "Judges" + one glanceable count ("1 of 2 scored · 14 resolved"),
 *     plus a muted grace-window note (why a judge can still be awaiting outcomes);
 *   - one row per SCORED judge — judge id + family/resolved-count, then the two
 *     axes kept DELIBERATELY SEPARATE: `cal` (calibration error / ECE, lower is
 *     better) and `disc` (discrimination / AUC, higher is better; 0.5 = coin
 *     flip), plus `brier` (the overall proper score). A judge with too few
 *     resolved verdicts shows a `provisional` marker — its scores exist but
 *     aren't authoritative. AUC renders as "n/a" (never a fake 0.5) when every
 *     resolved outcome is one class;
 *   - the pending judges beneath — those with no resolved verdicts yet, each a
 *     calm "awaiting resolved verdicts". Pending is not an error.
 *
 * DEFERRED (later phases, deliberately absent here):
 *   - No reliability curve: the endpoint hands `calibration_bins` (mean_confidence
 *     vs empirical_rate per decile), but the console has no bar/chart primitive
 *     and a per-judge reliability diagram is a future phase — this slice shows the
 *     scalar ECE instead.
 *   - No auto-grading: calibration and discrimination are reported as raw numbers,
 *     never blended into a single pass/fail — collapsing the two axes hides the
 *     exact failure the instrument exists to surface.
 *
 * Load-bearing contracts the tests pin:
 *   - a scored row shows its calibration (ECE) / discrimination (AUC) / brier;
 *   - a low-confidence judge renders the warning-toned `provisional` marker;
 *   - an undefined-AUC judge shows "n/a" with a title explaining why;
 *   - a pending judge renders the calm awaiting state, never an error;
 *   - an empty / failed feed renders a calm empty state, never a crash;
 *   - every colour / space value resolves from the token layer via `useTokens()`
 *     — no inline `style={{…}}` literal, no hardcoded hex — so light + dark fall
 *     out of the console's ThemeProvider (inline-style + colour + border ratchets).
 */

import React from 'react'
import { useTokens, Text, Badge } from '../styles/primitives'
import { EMPTY_JUDGE_CALIBRATION_VM } from './model/judgeCalibration'

const PROVISIONAL_TITLE = 'too few resolved verdicts — scores are provisional, not authoritative'
const AUC_UNDEFINED_TITLE = 'every resolved outcome was one class — AUC (discrimination) is undefined'

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
    grace: { padding: `${t.space.xxs}px 0` },
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
    // The pending judges sit below a token divider (borderTop longhand only —
    // never mixed with the `border` shorthand, per the border-shorthand guard).
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

/** One labelled metric: a muted caption + its value (e.g. "cal 0.05"). An
 * optional title annotates a caveated value (e.g. an undefined AUC). */
function Metric({ label, value, styles, testid, title }) {
  return (
    <span style={styles.metric} data-testid={testid} title={title}>
      <Text as="span" size="xs" tone="muted" uppercase>{label}</Text>
      <Text as="span" size="sm" weight="semibold">{value}</Text>
    </span>
  )
}

/** One scored judge: identity + calibration (ECE) / discrimination (AUC) / brier. */
function ScoredRow({ row, styles }) {
  return (
    <div data-testid={`judge-row-${row.judgeId}`} style={styles.row}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{row.judgeId}</Text>
        <Text as="span" size="xs" tone="muted">{`${row.judgeFamily} · ${row.nResolved} resolved`}</Text>
      </span>
      <span style={styles.metrics}>
        <Metric label="cal" value={row.calibrationLabel} styles={styles} testid={`judge-cal-${row.judgeId}`} />
        <Metric
          label="disc"
          value={row.discriminationLabel}
          styles={styles}
          testid={`judge-disc-${row.judgeId}`}
          title={row.discriminationUndefined ? AUC_UNDEFINED_TITLE : undefined}
        />
        <Metric label="brier" value={row.brierLabel} styles={styles} testid={`judge-brier-${row.judgeId}`} />
      </span>
      <span style={styles.markers}>
        {row.provisional && (
          <Badge tone="warning" title={PROVISIONAL_TITLE} data-testid={`judge-provisional-${row.judgeId}`}>
            provisional
          </Badge>
        )}
        <Badge
          tone={row.provisional ? 'warning' : 'neutral'}
          data-testid={`judge-status-${row.judgeId}`}
        >
          scored
        </Badge>
      </span>
    </div>
  )
}

/** One pending judge: identity + a calm "awaiting resolved verdicts". */
function PendingRow({ row, styles }) {
  return (
    <div data-testid={`judge-pending-${row.judgeId}`} style={styles.row}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{row.judgeId}</Text>
        <Text as="span" size="xs" tone="muted">{row.judgeFamily}</Text>
      </span>
      <Text size="sm" tone="muted" style={styles.pendingMsg}>{row.label}</Text>
      <Badge tone="neutral" data-testid={`judge-status-${row.judgeId}`}>pending</Badge>
    </div>
  )
}

/**
 * @param {{ calibration?: ReturnType<typeof import('./model/judgeCalibration').toJudgeCalibration> }} props
 */
export function JudgeCalibrationPanel({ calibration = EMPTY_JUDGE_CALIBRATION_VM }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const { headerLabel, scored, pending, graceWindowDays } = calibration
  const isEmpty = scored.length === 0 && pending.length === 0

  return (
    <div data-testid="judge-calibration-panel" style={styles.card}>
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Judges</Text>
        <Badge tone="neutral" data-testid="judge-header">{headerLabel}</Badge>
        <span style={styles.spacer} />
      </div>

      {isEmpty ? (
        <Text size="sm" tone="muted" style={styles.empty} data-testid="judge-empty">
          no judge calibration — awaiting resolved verdicts
        </Text>
      ) : (
        <>
          {graceWindowDays > 0 && (
            <Text size="xs" tone="muted" style={styles.grace} data-testid="judge-grace">
              {`outcomes resolve after a ${graceWindowDays}-day grace window`}
            </Text>
          )}
          {scored.map(row => (
            <ScoredRow key={row.judgeId} row={row} styles={styles} />
          ))}
          {pending.length > 0 && (
            <div style={styles.pendingWrap} data-testid="judge-pending">
              {pending.map(row => (
                <PendingRow key={row.judgeId} row={row} styles={styles} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default JudgeCalibrationPanel
