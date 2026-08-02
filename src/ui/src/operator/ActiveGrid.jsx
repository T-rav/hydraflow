/**
 * ActiveGrid — the operator console's AGENT view (epic #10556; redesign #10944).
 *
 * The old "All active" grid was a flat wall of cards that mixed queued and
 * running work with no state — and the name was a lie (they were not all
 * active). This is now the agent drill-down: one card per LIVE/HELD worker,
 * each with an explicit STATE — RUNNING / PAUSED / STALLED / WAITING-CI /
 * BLOCKED — so an operator can actually supervise from it. Queued items are gone
 * from this view entirely (they live in the phase columns' QUEUED section,
 * #10943), so the "No transcript yet" cards vanish.
 *
 * All derivation is delegated to the shared, pure `deriveAgentStates(...)`
 * (model/agents.js): it fuses the granular `workers` registry (WorkerStatus incl.
 * `ci_wait`, the worker id, and `lastActivity` heartbeat for STALL detection)
 * with the pipeline claim signal and the factory credit/auth pause. The clock is
 * injected via `now` so states are deterministic under test. State filter chips
 * (`Running | Paused | Stalled | Waiting-CI | Blocked | All`) scope the grid and
 * remember the choice. The card header carries the operator numbers (worker id ·
 * phase · elapsed) and the state badge; the transcript tail is secondary — the
 * drill-down, not the headline. Clicking a card header drills back into Focus.
 *
 * Presentation only — no socket, no side effects. Every colour / space value
 * resolves from `useTokens()`; the state colours come from token BADGE tones, so
 * light + dark fall out of the console's ThemeProvider mode with no literals.
 */

import React, { useMemo, useState } from 'react'
import { useTokens, Card, Text, Badge } from '../styles/primitives'
import { toTranscript } from './model/transcript'
import { stageColorKey } from './model/pipeline'
import {
  deriveAgentStates,
  AGENT_STATE_ORDER,
  AGENT_STATE_META,
  WORKER_STATE,
} from './model/agents'
import { PULSE_ANIMATION } from '../constants'
import { TranscriptStream } from './TranscriptStream'

// State filter chips (#10944): the five agent states, plus All (the default).
const AGENT_FILTERS = [{ key: 'all', label: 'All' }].concat(
  AGENT_STATE_ORDER.map(state => ({ key: state, label: AGENT_STATE_META[state].label })),
)
const DEFAULT_AGENT_FILTER = 'all'
// Remembered across reloads (guarded localStorage, mirroring the phase columns).
const AGENT_FILTER_STORAGE_KEY = 'hydraflow.operator.agentFilter'

function readStoredAgentFilter() {
  if (typeof window === 'undefined' || !window.localStorage) return DEFAULT_AGENT_FILTER
  try {
    const stored = window.localStorage.getItem(AGENT_FILTER_STORAGE_KEY)
    return AGENT_FILTERS.some(f => f.key === stored) ? stored : DEFAULT_AGENT_FILTER
  } catch {
    return DEFAULT_AGENT_FILTER
  }
}

function writeStoredAgentFilter(value) {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(AGENT_FILTER_STORAGE_KEY, value)
  } catch {
    /* storage unavailable — session-local state still works */
  }
}

function makeStyles(t) {
  return {
    filterBar: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: t.space.xs,
      marginBottom: t.space.sm,
    },
    filterChip: (on) => ({
      border: `1px solid ${on ? t.color.accent : t.color.border}`,
      borderRadius: t.radius.md,
      background: on ? t.color.accent : t.color.surfaceInset,
      color: on ? t.color.bg : t.color.textMuted,
      cursor: 'pointer',
      padding: `2px ${t.space.sm}px`,
      font: 'inherit',
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
    }),
    grid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: t.space.md,
      minWidth: 0,
    },
    tile: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      minWidth: 0,
      background: t.color.surfaceInset,
      padding: t.space.sm,
      boxSizing: 'border-box',
    },
    headerRow: {
      display: 'flex',
      alignItems: 'baseline',
      justifyContent: 'space-between',
      gap: t.space.xs,
      minWidth: 0,
    },
    header: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.xs,
      minWidth: 0,
      flex: '1 1 auto',
      border: 'none',
      background: 'none',
      color: 'inherit',
      font: 'inherit',
      textAlign: 'left',
      cursor: 'pointer',
      padding: 0,
    },
    title: {
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      minWidth: 0,
    },
    // The operator-numbers row: worker id · phase · elapsed.
    metaRow: {
      display: 'flex',
      alignItems: 'center',
      flexWrap: 'wrap',
      gap: t.space.xs,
    },
    // The phase dot, painted in the stage's identity colour (classic palette,
    // resolved through the token bundle — no literal). Unknown phase → muted.
    phaseDot: (phase) => ({
      display: 'inline-block',
      width: 7,
      height: 7,
      borderRadius: t.radius.pill,
      background: t.color[stageColorKey(phase)] ?? t.color.textMuted,
      flexShrink: 0,
    }),
    // The RUNNING pulse — inherits the badge's (token) colour via currentColor,
    // so no literal colour is introduced.
    pulseDot: {
      display: 'inline-block',
      width: 6,
      height: 6,
      borderRadius: t.radius.pill,
      background: 'currentColor',
      animation: PULSE_ANIMATION,
      flexShrink: 0,
    },
    note: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: t.space.xxs,
    },
    empty: { padding: `${t.space.md}px ${t.space.xxs}px` },
  }
}

/**
 * A single agent card: the operator-numbers header (id + title, worker id,
 * phase, elapsed) with an always-present STATE badge, an optional reason line
 * (why paused / stalled), and a secondary transcript tail (the drill-down).
 */
function AgentTile({ agent, events, styles, select }) {
  const rows = useMemo(() => toTranscript(events, agent.id), [events, agent.id])
  const meta = AGENT_STATE_META[agent.state] ?? AGENT_STATE_META[WORKER_STATE.RUNNING]

  const onFocus = () => {
    select?.('mode', 'focus')
    select?.('item', agent.id)
  }

  return (
    <Card as="div" data-testid={`active-tile-${agent.id}`} data-item-id={agent.id} data-state={agent.state} style={styles.tile}>
      <div style={styles.headerRow}>
        <button
          type="button"
          data-testid={`active-tile-header-${agent.id}`}
          onClick={onFocus}
          style={styles.header}
          title="Focus this agent"
        >
          <Text as="span" size="md" weight="bold" tone="bright">#{agent.id}</Text>
          {agent.title != null && agent.title !== '' && (
            <Text as="span" size="sm" tone="muted" style={styles.title}>{agent.title}</Text>
          )}
        </button>
        <Badge tone={meta.tone} data-testid={`agent-state-${agent.id}`} data-state={agent.state}>
          {meta.pulse && <span aria-hidden="true" style={styles.pulseDot} />}
          {meta.label}
        </Badge>
      </div>

      <div style={styles.metaRow}>
        <span
          data-testid={`agent-phase-dot-${agent.id}`}
          data-stage-color={stageColorKey(agent.phase) ?? ''}
          aria-hidden="true"
          style={styles.phaseDot(agent.phase)}
        />
        {agent.phaseLabel != null && agent.phaseLabel !== '' && (
          <Text as="span" size="xs" tone="muted" uppercase data-testid={`agent-phase-${agent.id}`}>
            {agent.phaseLabel}
          </Text>
        )}
        {agent.workerId != null && (
          <Text as="span" size="xs" tone="muted" data-testid={`agent-worker-${agent.id}`}>
            W{agent.workerId}
          </Text>
        )}
        {agent.elapsed !== '' && (
          <Text as="span" size="xs" tone="muted" data-testid={`agent-elapsed-${agent.id}`}>
            {agent.elapsed}
          </Text>
        )}
      </div>

      {agent.state === WORKER_STATE.PAUSED && (agent.reason || agent.resumeEta) && (
        <div style={styles.note} data-testid={`agent-reason-${agent.id}`}>
          <Text as="span" size="xs" tone="warning">
            {agent.reason || 'paused'}
            {agent.provider ? ` (${agent.provider})` : ''}
          </Text>
        </div>
      )}
      {agent.state === WORKER_STATE.STALLED && (
        <div style={styles.note} data-testid={`agent-stall-${agent.id}`}>
          <Text as="span" size="xs" tone="danger">no output — possible silent failure</Text>
        </div>
      )}

      <TranscriptStream rows={rows} active={false} />
    </Card>
  )
}

/**
 * @param {{
 *   pipeline?: { stages?: Array },
 *   workers?: Object,
 *   events?: Array,
 *   factory?: { state?: string, reason?: string|null },
 *   credits?: { pausedUntil?: string|null, provider?: string|null },
 *   now?: number,
 *   select?: Function,
 * }} props
 */
export function ActiveGrid({ pipeline, workers, events = [], factory, credits, now = Date.now(), select }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const [filter, setFilter] = useState(() => readStoredAgentFilter())

  const agents = useMemo(
    () => deriveAgentStates({ workers, pipeline, events, factory, credits, now }),
    [workers, pipeline, events, factory, credits, now],
  )

  const chooseFilter = (value) => {
    setFilter(value)
    writeStoredAgentFilter(value)
  }

  const visible = filter === 'all' ? agents : agents.filter(a => a.state === filter)

  return (
    <div data-testid="active-grid">
      <div style={styles.filterBar} role="group" aria-label="Agent state filter">
        {AGENT_FILTERS.map(f => (
          <button
            key={f.key}
            type="button"
            data-testid={`agent-filter-${f.key}`}
            aria-pressed={filter === f.key}
            style={styles.filterChip(filter === f.key)}
            onClick={() => chooseFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div data-testid="active-grid-items" style={styles.grid}>
        {visible.length === 0 ? (
          <Text as="div" size="sm" tone="muted" data-testid="active-grid-empty" style={styles.empty}>
            {agents.length === 0 ? 'No agents running right now.' : 'No agents in this state.'}
          </Text>
        ) : (
          visible.map(agent => (
            <AgentTile key={agent.key} styles={styles} agent={agent} events={events} select={select} />
          ))
        )}
      </div>
    </div>
  )
}

export default ActiveGrid
