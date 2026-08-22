/**
 * PolicyAuditPanel — `?mode=routing&routingView=audit` (#11538, ADR-0140).
 *
 * The append-only mutation history, kept deliberately separate from traffic.
 * The design document is explicit about that separation and it is not
 * cosmetic: a timeline that mixed "somebody changed a policy" with "a request
 * was served" invites reading a spike in one as evidence about the other.
 *
 * Two things this panel must never soften:
 *
 *   - **Verification is a headline, not a footnote.** If the chain does not
 *     verify, the history cannot be trusted as a rollback source and writes are
 *     already being refused — so it says so at the top, with the sequence that
 *     broke.
 *   - **A recovered record says it was recovered.** A row written by crash
 *     recovery rather than by an operator's own save is a different fact, and
 *     the `aborted` outcome — an intent that never reached the snapshot — is
 *     shown rather than hidden, because a gap in `seq` with no explanation is
 *     exactly what an audit exists to prevent.
 */

import React from 'react'
import { Badge, Text, useTokens } from '../styles/primitives'
import {
  EMPTY_POLICY_AUDIT_VM,
  feedIsCurrent,
  feedNotice,
} from './model/policyWorkspace'

function makeStyles(t) {
  return {
    card: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      padding: t.space.sm,
      borderRadius: t.radius.md,
      borderWidth: 1,
      borderStyle: 'solid',
      borderColor: t.color.border,
      background: t.color.surface,
      boxSizing: 'border-box',
    },
    header: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      flexWrap: 'wrap',
    },
    spacer: { flex: '1 1 auto' },
    rows: { display: 'flex', flexDirection: 'column', gap: t.space.xxs },
    row: {
      display: 'flex',
      alignItems: 'baseline',
      flexWrap: 'wrap',
      gap: t.space.sm,
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      borderRadius: t.radius.sm,
      background: `color-mix(in srgb, ${t.color.text} 4%, transparent)`,
    },
    nameCol: {
      display: 'flex',
      flexDirection: 'column',
      minWidth: 0,
      flex: '1 1 auto',
    },
    facts: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      flexWrap: 'wrap',
      flexShrink: 0,
    },
    note: { padding: `${t.space.xxs}px 0` },
  }
}

function changeSummary(record) {
  const parts = []
  if (record.added.length) parts.push(`+${record.added.join(', ')}`)
  if (record.removed.length) parts.push(`-${record.removed.join(', ')}`)
  if (record.changed.length) parts.push(`~${record.changed.join(', ')}`)
  return parts.join(' ') || 'no policy set change'
}

function AuditRow({ record, styles }) {
  return (
    <div style={styles.row} data-testid={`policy-audit-${record.seq}`}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold">
          {`r${record.priorRevision} → r${record.newRevision} · ${record.kind}${
            record.targetRevision == null ? '' : ` (target r${record.targetRevision})`
          }`}
        </Text>
        <Text as="span" size="xs" tone="muted">
          {`${record.actor} · ${record.recordedAt} · ${changeSummary(record)}`}
        </Text>
      </span>
      <span style={styles.facts}>
        <Badge
          tone={record.outcome === 'committed' ? 'info' : 'warning'}
          data-testid={`policy-audit-outcome-${record.seq}`}
        >
          {record.outcome}
        </Badge>
        {record.recovered && (
          <Badge tone="warning" data-testid={`policy-audit-recovered-${record.seq}`}>
            recovered
          </Badge>
        )}
      </span>
    </div>
  )
}

/** @param {{ audit?: object, sourceState?: string }} props */
export default function PolicyAuditPanel({
  audit = EMPTY_POLICY_AUDIT_VM,
  sourceState = 'loading',
}) {
  const t = useTokens()
  const styles = makeStyles(t)
  const notice = feedNotice(sourceState, audit.loaded)
  // `verified` is a THREE-state fact: verified, broken, or never read. Only the
  // first two are claims this panel is entitled to make — and only while the
  // source is still answering. A frozen last-known chain is not a verified one.
  const unread = audit.verified == null || !feedIsCurrent(sourceState)

  return (
    <div style={styles.card} data-testid="policy-audit">
      <div style={styles.header}>
        <Text size="sm" weight="semibold" uppercase>
          Policy audit
        </Text>
        <Text as="span" size="xs" tone="muted" data-testid="policy-audit-count">
          {audit.loaded ? `${audit.records.length} recorded mutations` : 'not read yet'}
        </Text>
        <span style={styles.spacer} />
        <Badge
          tone={unread ? 'neutral' : audit.verified ? 'info' : 'danger'}
          data-testid="policy-audit-verified"
        >
          {unread
            ? audit.loaded
              ? 'chain not re-read'
              : 'chain unread'
            : audit.verified
              ? 'chain verified'
              : 'chain broken'}
        </Badge>
      </div>
      {notice ? (
        <div style={styles.note} data-testid="policy-audit-feed-notice">
          <Text
            size="sm"
            tone={sourceState === 'unavailable' ? 'danger' : 'muted'}
            role={sourceState === 'unavailable' ? 'alert' : 'status'}
          >
            {notice}
          </Text>
        </div>
      ) : null}
      {audit.verified === false && (
        <div style={styles.note} data-testid="policy-audit-broken">
          <Text role="alert" size="sm" tone="danger">
            {`The hash-linked mutation chain does not verify${
              audit.brokenAtSeq == null ? '' : ` at seq ${audit.brokenAtSeq}`
            }. Rollback targets cannot be trusted and writes are refused until it is repaired.`}
          </Text>
        </div>
      )}
      {audit.loaded && audit.records.length === 0 ? (
        <Text role="status" size="sm" tone="muted" data-testid="policy-audit-empty">
          No policy mutation has been recorded for this repository.
        </Text>
      ) : (
        <div style={styles.rows}>
          {audit.records
            .slice()
            .reverse()
            .map(record => (
              <AuditRow key={record.seq} record={record} styles={styles} />
            ))}
        </div>
      )}
      {audit.truncated && (
        <Text as="span" size="xs" tone="warning" data-testid="policy-audit-truncated">
          Older mutations are not shown — this page did not return them. This view
          is not the complete history.
        </Text>
      )}
    </div>
  )
}
