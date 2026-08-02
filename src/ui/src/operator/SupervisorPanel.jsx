/**
 * SupervisorPanel — the window into the Tier-2 goal-supervisor (#10733, ADR-0124).
 *
 * Pure presentational component. Consumes the `toSupervisorThread(...)` view
 * model (the supervisor's append-only observation thread — newest first, healthy
 * ticks omitted) and renders, in the vitals column:
 *
 *   - one glanceable liveness verdict up top (healthy / N escalations pending /
 *     degraded), derived from the newest observation;
 *   - the chronological thread (newest first). Each row is COLLAPSED by default
 *     — timestamp + assessment + bucket counts — and expands on click to mine its
 *     full detail (health snapshot, insights, nudges taken, escalations,
 *     deferred). An observation carrying escalations is visually distinct (a red
 *     left rail) — those want a human;
 *   - a small set of human action buttons. Resume / Pause are LIVE (wired to the
 *     existing `/api/control/start` + `/api/control/stop` endpoints via the
 *     socket handlers the console already threads). Restart-loop and Ack-
 *     escalation are DEFERRED: rendered but disabled, with a title explaining the
 *     backend seam is not built yet — never a fabricated call to a missing route.
 *
 * Load-bearing contracts the tests pin:
 *   - an empty / failed feed renders a calm empty state, never a crash;
 *   - a row expands on click and re-collapses on a second click;
 *   - escalation rows carry `data-escalation="true"`;
 *   - every colour / space value resolves from the token layer via `useTokens()`
 *     — no inline `style={{…}}` literal, no hardcoded hex — so light + dark fall
 *     out of the console's ThemeProvider (inline-style + colour + border ratchets).
 */

import React, { useState } from 'react'
import { useTokens, Text, Badge, Button } from '../styles/primitives'
import { EMPTY_SUPERVISOR_VM } from './model/supervisorThread'

// Verdict → the Badge tone that renders its severity colour.
const VERDICT_TONE = {
  healthy: 'success',
  degraded: 'warning',
  escalations: 'danger',
  empty: 'neutral',
}

// The bucket badges shown collapsed on each row: key → { label, tone }.
const BUCKETS = [
  { key: 'insights', label: 'insight', tone: 'info' },
  { key: 'nudges', label: 'nudge', tone: 'accent' },
  { key: 'escalations', label: 'escalation', tone: 'danger' },
  { key: 'deferred', label: 'deferred', tone: 'neutral' },
]

function makeStyles(t) {
  return {
    card: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.sm,
      padding: t.space.sm,
      boxSizing: 'border-box',
    },
    header: { display: 'flex', alignItems: 'baseline', gap: t.space.sm },
    spacer: { flex: '1 1 auto' },
    actions: { display: 'flex', flexWrap: 'wrap', gap: t.space.xs },
    empty: { padding: `${t.space.xs}px 0` },
    thread: { display: 'flex', flexDirection: 'column', gap: t.space.xs },
    row: (escalated) => ({
      display: 'flex',
      flexDirection: 'column',
      borderLeft: `3px solid ${escalated ? t.color.red : t.color.border}`,
      borderRadius: t.radius.sm,
      backgroundColor: `color-mix(in srgb, ${t.color.textMuted} 8%, transparent)`,
      overflow: 'hidden',
    }),
    toggle: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      width: '100%',
      textAlign: 'left',
      background: 'transparent',
      border: 'none',
      cursor: 'pointer',
      padding: `${t.space.xs}px ${t.space.sm}px`,
      font: 'inherit',
      color: 'inherit',
    },
    ts: { flexShrink: 0 },
    assessment: {
      minWidth: 0,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      flex: '1 1 auto',
    },
    counts: { display: 'flex', gap: t.space.xxs, flexShrink: 0 },
    detail: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.sm}px ${t.space.sm}px`,
    },
    snapshot: { display: 'flex', flexWrap: 'wrap', gap: t.space.xs },
    section: { display: 'flex', flexDirection: 'column', gap: t.space.xxs },
    listItem: { paddingLeft: t.space.sm, wordBreak: 'break-word' },
  }
}

/** Collapsed bucket-count badges (only the non-zero buckets render). */
function CountBadges({ counts, styles }) {
  const shown = BUCKETS.filter(b => counts[b.key] > 0)
  if (shown.length === 0) return null
  return (
    <span style={styles.counts}>
      {shown.map(b => (
        <Badge key={b.key} tone={b.tone}>{`${counts[b.key]} ${b.label}${counts[b.key] === 1 ? '' : 's'}`}</Badge>
      ))}
    </span>
  )
}

/** The active degradation signals of one snapshot, as subtle chips. */
function SnapshotSignals({ snapshot, styles }) {
  const chips = []
  const healthTone = snapshot.healthy === false ? 'danger' : 'success'
  const healthText = snapshot.healthy === false ? 'unhealthy' : 'healthy'
  chips.push(<Badge key="health" tone={healthTone}>{healthText}</Badge>)
  if (snapshot.vitalsVerdict) {
    const vitTone = snapshot.vitalsVerdict === 'diverging' ? 'danger'
      : snapshot.vitalsVerdict === 'watch' ? 'warning' : 'success'
    chips.push(<Badge key="vitals" tone={vitTone}>{`vitals: ${snapshot.vitalsVerdict}`}</Badge>)
  }
  if (snapshot.stalledLoops.length > 0) chips.push(<Badge key="stalled" tone="warning">{`stalled: ${snapshot.stalledLoops.join(', ')}`}</Badge>)
  if (snapshot.errorLoops.length > 0) chips.push(<Badge key="error" tone="danger">{`error: ${snapshot.errorLoops.join(', ')}`}</Badge>)
  if (snapshot.creditFailoverActive) chips.push(<Badge key="failover" tone="warning">credit failover</Badge>)
  if (snapshot.creditProbeOverdue) chips.push(<Badge key="probe" tone="warning">credit probe overdue</Badge>)
  if (snapshot.bootShaStale) chips.push(<Badge key="boot" tone="warning">boot SHA stale</Badge>)
  if (snapshot.eventLoopStalled) chips.push(<Badge key="evloop" tone="danger">event loop stalled</Badge>)
  if (snapshot.commitsBehind > 0) chips.push(<Badge key="behind" tone="warning">{`${snapshot.commitsBehind} behind`}</Badge>)
  return <div style={styles.snapshot} data-testid="supervisor-snapshot">{chips}</div>
}

/** A titled bucket list inside the expanded detail (nothing renders when empty). */
function DetailSection({ testid, title, items, tone, styles }) {
  if (!items || items.length === 0) return null
  return (
    <div style={styles.section} data-testid={testid}>
      <Text size="xs" weight="semibold" tone="muted" uppercase>{title}</Text>
      {items.map((item, i) => (
        <Text key={i} size="sm" tone={tone} style={styles.listItem}>{item}</Text>
      ))}
    </div>
  )
}

/** One observation: collapsed header (click to expand) + mined detail. */
function ObservationRow({ obs, index, open, onToggle, styles }) {
  return (
    <div
      data-testid={`supervisor-obs-${index}`}
      data-escalation={obs.hasEscalations ? 'true' : 'false'}
      style={styles.row(obs.hasEscalations)}
    >
      <button
        type="button"
        data-testid={`supervisor-obs-${index}-toggle`}
        aria-expanded={open}
        onClick={onToggle}
        style={styles.toggle}
      >
        <Text as="span" size="xs" tone="muted" style={styles.ts}>{obs.ts}</Text>
        <Text as="span" size="sm" tone={obs.hasEscalations ? 'danger' : 'default'} style={styles.assessment}>
          {obs.assessment || '(no assessment)'}
        </Text>
        <CountBadges counts={obs.counts} styles={styles} />
      </button>
      {open && (
        <div style={styles.detail} data-testid={`supervisor-obs-${index}-detail`}>
          <SnapshotSignals snapshot={obs.snapshot} styles={styles} />
          <DetailSection testid={`supervisor-obs-${index}-insights`} title="Insights" items={obs.insights} tone="muted" styles={styles} />
          <DetailSection testid={`supervisor-obs-${index}-nudges`} title="Nudges taken (pending)" items={obs.nudges} tone="accent" styles={styles} />
          <DetailSection testid={`supervisor-obs-${index}-escalations`} title="Escalations (want a human)" items={obs.escalations} tone="danger" styles={styles} />
          <DetailSection testid={`supervisor-obs-${index}-deferred`} title="Deferred (transient)" items={obs.deferred} tone="muted" styles={styles} />
        </div>
      )}
    </div>
  )
}

/**
 * Human action buttons. Resume / Pause are live (existing control endpoints);
 * restart-loop + ack-escalation are deferred (disabled, titled) until a backend
 * seam exists — never a fabricated call to a missing route.
 */
function ActionButtons({ onResume, onPause, styles }) {
  return (
    <div style={styles.actions} data-testid="supervisor-actions">
      <Button
        variant="success"
        size="sm"
        data-testid="supervisor-action-resume"
        disabled={typeof onResume !== 'function'}
        onClick={onResume}
        title="Resume the factory (POST /api/control/start)"
      >
        Resume
      </Button>
      <Button
        variant="danger"
        size="sm"
        data-testid="supervisor-action-pause"
        disabled={typeof onPause !== 'function'}
        onClick={onPause}
        title="Pause the factory (POST /api/control/stop)"
      >
        Pause
      </Button>
      <Button
        variant="ghost"
        size="sm"
        data-testid="supervisor-action-restart-loop"
        disabled
        title="Deferred: restarting a specific loop needs a small backend control endpoint (bg_workers.restart is not exposed as a route yet)."
      >
        Restart loop
      </Button>
      <Button
        variant="ghost"
        size="sm"
        data-testid="supervisor-action-ack"
        disabled
        title="Deferred: acknowledging an escalation needs a small backend endpoint to record the ack on the thread."
      >
        Ack escalation
      </Button>
    </div>
  )
}

/**
 * @param {{ supervisor?: ReturnType<typeof import('./model/supervisorThread').toSupervisorThread>,
 *           onResume?: Function, onPause?: Function }} props
 */
export function SupervisorPanel({ supervisor = EMPTY_SUPERVISOR_VM, onResume, onPause }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const [expanded, setExpanded] = useState(() => new Set())
  const { verdict, verdictLabel, count, observations } = supervisor

  const toggle = (id) => setExpanded(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  return (
    <div data-testid="supervisor-panel" style={styles.card}>
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Supervisor</Text>
        <Badge tone={VERDICT_TONE[verdict] ?? 'neutral'} data-testid="supervisor-verdict">{verdictLabel}</Badge>
        <span style={styles.spacer} />
        {count > 0 && (
          <Text as="span" size="xs" tone="muted" data-testid="supervisor-count">
            {`${count} observation${count === 1 ? '' : 's'}`}
          </Text>
        )}
      </div>

      <ActionButtons onResume={onResume} onPause={onPause} styles={styles} />

      {observations.length === 0 ? (
        <Text size="sm" tone="muted" style={styles.empty} data-testid="supervisor-empty">
          no supervisor observations — the goal-supervisor writes only when a tick is non-trivial
        </Text>
      ) : (
        <div style={styles.thread} data-testid="supervisor-thread">
          {observations.map((obs, index) => (
            <ObservationRow
              key={obs.id}
              obs={obs}
              index={index}
              open={expanded.has(obs.id)}
              onToggle={() => toggle(obs.id)}
              styles={styles}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default SupervisorPanel
