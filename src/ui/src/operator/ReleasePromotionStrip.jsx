/**
 * ReleasePromotionStrip — the operator console's staging↔main promotion readout
 * (epic #10556 follow-up).
 *
 * Pure presentational component. Consumes the `toReleasePromotion(...)` view
 * model and renders a single compact, horizontal strip: a colour-coded state
 * badge (in sync / behind / promoting / unknown) with a matching status dot, the
 * staging-ahead count, the open RC promotion PR (linked to GitHub when a URL is
 * known), the last-RC marker, the cadence, and the StagingPromotionLoop's health
 * dot.
 *
 * The colour-coding is the contract the tests pin: the state carries an
 * `ok` | `warn` | `info` | `muted` severity and every colour resolves from the
 * token layer via `useTokens()` — no hardcoded hex — so light + dark both fall
 * out of the console's ThemeProvider mode. Presentation only: no socket, no side
 * effects.
 */

import React from 'react'
import { useTokens, Card, Text, Badge } from '../styles/primitives'

// State -> { label, Badge tone, status-dot token colour key }. `unknown` reads as
// an inactive / not-yet-reported promotion pipeline.
const STATE_META = {
  in_sync: { label: 'in sync', tone: 'success', colorKey: 'green' },
  behind: { label: 'behind', tone: 'warning', colorKey: 'yellow' },
  promoting: { label: 'promoting', tone: 'info', colorKey: 'cyan' },
  unknown: { label: 'unknown', tone: 'neutral', colorKey: 'textInactive' },
}

// Loop-health severity -> status-dot token colour key (mirrors LoopsPanel).
const LOOP_COLOR_KEY = { ok: 'green', warn: 'yellow', bad: 'red', muted: 'textInactive' }

// The empty readout so the strip renders (unknown) even with no prop.
const EMPTY = {
  state: 'unknown',
  enabled: false,
  commitsAhead: null,
  openPr: null,
  lastRc: null,
  cadenceHours: null,
  cadenceProgressHours: null,
  loop: null,
}

function makeStyles(t) {
  return {
    strip: {
      display: 'flex',
      alignItems: 'center',
      flexWrap: 'wrap',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.sm}px`,
      minWidth: 0,
    },
    label: { flexShrink: 0 },
    spacer: { flex: '1 1 auto' },
    dot: (colorKey) => ({
      flexShrink: 0,
      width: 8,
      height: 8,
      borderRadius: t.radius.pill,
      backgroundColor: t.color[colorKey] ?? t.color.textMuted,
    }),
    link: {
      color: t.color.accent,
      textDecoration: 'none',
      fontFamily: t.type.family.mono,
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
    },
    loopWrap: { display: 'inline-flex', alignItems: 'center', gap: t.space.xs, flexShrink: 0 },
  }
}

/**
 * @param {{ release?: {
 *   state: string, enabled: boolean, commitsAhead: (number|null),
 *   openPr: ({number: number, url: (string|null)}|null),
 *   lastRc: ({name: (string|null), ts: (string|null)}|null),
 *   cadenceHours: (number|null), cadenceProgressHours: (number|null),
 *   loop: ({status: string, severity: string}|null),
 * } }} props
 */
export function ReleasePromotionStrip({ release }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const vm = release ?? EMPTY
  const meta = STATE_META[vm.state] ?? STATE_META.unknown
  const lastRcLabel = vm.lastRc ? (vm.lastRc.name ?? vm.lastRc.ts) : null

  return (
    <Card as="section" data-testid="release-promotion-strip" style={styles.strip} aria-label="Release promotion">
      <Text size="xs" weight="semibold" tone="muted" uppercase style={styles.label}>Release</Text>
      <span
        data-testid="release-state-dot"
        className={`release-state ${vm.state}`}
        style={styles.dot(meta.colorKey)}
        aria-hidden="true"
      />
      <Badge tone={meta.tone} data-testid="release-state">{meta.label}</Badge>

      {typeof vm.commitsAhead === 'number' && vm.commitsAhead > 0 && (
        <Badge tone="neutral" data-testid="release-commits-ahead">{`↑${vm.commitsAhead}`}</Badge>
      )}

      {vm.openPr ? (
        vm.openPr.url ? (
          <a
            data-testid="release-open-pr"
            href={vm.openPr.url}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.link}
          >
            {`RC #${vm.openPr.number}`}
          </a>
        ) : (
          <Text as="span" size="xs" tone="accent" data-testid="release-open-pr">{`RC #${vm.openPr.number}`}</Text>
        )
      ) : null}

      <span style={styles.spacer} />

      {lastRcLabel ? (
        <Text as="span" size="xs" tone="muted" data-testid="release-last-rc">{`last RC ${lastRcLabel}`}</Text>
      ) : null}

      {typeof vm.cadenceHours === 'number' ? (
        <Badge tone="neutral" data-testid="release-cadence">{`every ${vm.cadenceHours}h`}</Badge>
      ) : null}

      {vm.loop ? (
        <span data-testid="release-loop" style={styles.loopWrap}>
          <span
            className={`release-loop-status ${vm.loop.severity}`}
            style={styles.dot(LOOP_COLOR_KEY[vm.loop.severity] ?? 'textMuted')}
            aria-label={`loop ${vm.loop.severity}`}
          />
          <Text as="span" size="xs" tone="muted">loop</Text>
        </span>
      ) : null}
    </Card>
  )
}

export default ReleasePromotionStrip
