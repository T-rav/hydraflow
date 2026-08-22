/**
 * RoutingMode — the read-only gateway Routing workspace (#11534, ADR-0138).
 *
 * Two URL-addressable views behind `?mode=routing&routingView=accounts|live`,
 * the sub-view keys the routing-control-plane design reserves. The remaining
 * design views (`effective`, `policies`, `audit`) belong to later phases of
 * epic #11531 and are deliberately absent — this phase observes, it does not
 * enforce.
 *
 * ACCOUNTS shows each compiled gateway account with its facts kept SEPARATE:
 * credential configured, administrative state, leases, in-flight requests,
 * observed traffic, and passive health. "Configured" is never drawn as
 * "healthy", "healthy" is never drawn as "currently routing", and `unverified`
 * is neutral rather than green. There is no eligibility badge: eligibility only
 * exists inside a route explanation, which this phase does not compute.
 *
 * LIVE shows leases, in-flight requests, and bounded recent terminal routes —
 * provider/account, project, role, requested vs served model, lease age, and
 * terminal status.
 *
 * Load-bearing contracts the tests pin:
 *   - an unavailable source renders an explicit degraded message, never an
 *     empty "no accounts" / "no traffic" state;
 *   - an account row shows configured / leases / in-flight / health separately;
 *   - a recent route shows requested vs served model and its terminal status;
 *   - the view toggle is URL-addressable through `select('routingView', ...)`;
 *   - every colour / space value resolves from the token layer via `useTokens()`
 *     — no inline `style={{…}}` literal, no hardcoded hex.
 */

import React from 'react'
import { Badge, Text, useTokens } from '../styles/primitives'
import {
  EMPTY_GATEWAY_ACCOUNTS_VM,
  EMPTY_GATEWAY_LIVE_VM,
} from './model/gatewayRouting'

export const ROUTING_VIEWS = [
  { key: 'accounts', label: 'Accounts' },
  { key: 'live', label: 'Live' },
]

const SOURCE_MESSAGES = {
  'not-configured': 'Gateway control token is not configured — set HYDRAFLOW_GATEWAY_CONTROL_TOKEN on the dashboard host.',
  unreachable: 'Gateway control plane is unreachable — this view cannot show accounts or routes.',
  invalid: 'Gateway returned an unrecognised payload — refusing to render an unverified view.',
}

function makeStyles(t) {
  return {
    wrap: { display: 'flex', flexDirection: 'column', gap: t.space.md },
    viewToggle: { display: 'flex', gap: t.space.xxs },
    viewButton: active => ({
      appearance: 'none',
      cursor: 'pointer',
      padding: `${t.space.xxs}px ${t.space.sm}px`,
      borderRadius: t.radius.pill,
      borderWidth: 1,
      borderStyle: 'solid',
      borderColor: active ? t.color.accent : t.color.border,
      background: active ? `color-mix(in srgb, ${t.color.accent} 14%, transparent)` : 'transparent',
      color: active ? t.color.accent : t.color.textMuted,
      fontFamily: t.type.family.sans,
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
    }),
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
    header: { display: 'flex', alignItems: 'baseline', gap: t.space.sm, flexWrap: 'wrap' },
    spacer: { flex: '1 1 auto' },
    note: { padding: `${t.space.xxs}px 0` },
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
    nameCol: { display: 'flex', flexDirection: 'column', minWidth: 0, flex: '1 1 auto' },
    name: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
    facts: { display: 'flex', alignItems: 'baseline', gap: t.space.sm, flexWrap: 'wrap', flexShrink: 0 },
    fact: { display: 'inline-flex', alignItems: 'baseline', gap: t.space.xxs },
    scroller: { overflowX: 'auto', maxWidth: '100%' },
    section: { display: 'flex', flexDirection: 'column', gap: t.space.xs },
  }
}

/** One labelled fact: a muted caption + its value. */
function Fact({ label, value, styles, testid }) {
  return (
    <span style={styles.fact} data-testid={testid}>
      <Text as="span" size="xs" tone="muted" uppercase>{label}</Text>
      <Text as="span" size="sm" weight="semibold">{value}</Text>
    </span>
  )
}

/** Explicit degraded state. An unavailable source is never an empty list. */
function SourceUnavailable({ sourceState, styles, testid }) {
  const message = SOURCE_MESSAGES[sourceState] || 'Gateway routing data is unavailable.'
  return (
    <div style={styles.note} data-testid={testid}>
      <Text role="alert" size="sm" tone="warning">{message}</Text>
    </div>
  )
}

function AccountRow({ account, styles }) {
  return (
    <div style={styles.row} data-testid={`routing-account-${account.accountId}`}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{account.displayName}</Text>
        <Text as="span" size="xs" tone="muted">
          {`${account.accountId} · ${account.providerBinding}${account.baseOrigin ? ` · ${account.baseOrigin}` : ''}`}
        </Text>
      </span>
      <span style={styles.facts}>
        <Badge
          tone={account.configured ? 'info' : 'warning'}
          data-testid={`routing-account-credential-${account.accountId}`}
        >
          {account.configured ? 'credential configured' : 'credential missing'}
        </Badge>
        <Badge tone="neutral" data-testid={`routing-account-admin-${account.accountId}`}>
          {account.administrativeState}
        </Badge>
        <Fact
          label="leases"
          value={String(account.leaseCount)}
          styles={styles}
          testid={`routing-account-leases-${account.accountId}`}
        />
        <Fact
          label="in flight"
          value={String(account.inFlightCount)}
          styles={styles}
          testid={`routing-account-inflight-${account.accountId}`}
        />
        <Fact
          label="observed"
          value={account.observed ? String(account.observedRequestCount) : 'none'}
          styles={styles}
          testid={`routing-account-observed-${account.accountId}`}
        />
        {account.observedErrorCount > 0 && (
          <Fact
            label="errors"
            value={`${account.observedErrorCount}/${
              account.observedRequestCount - account.observedAbortedCount
            }`}
            styles={styles}
            testid={`routing-account-errors-${account.accountId}`}
          />
        )}
        <Badge
          tone={account.healthTone}
          title={account.healthReason || undefined}
          data-testid={`routing-account-health-${account.accountId}`}
        >
          {account.health}
        </Badge>
      </span>
    </div>
  )
}

function AccountsView({ accounts, styles }) {
  if (!accounts.available) {
    return (
      <div style={styles.card} data-testid="routing-accounts">
        <Text size="sm" weight="semibold" uppercase>Accounts</Text>
        <SourceUnavailable
          sourceState={accounts.sourceState}
          styles={styles}
          testid="routing-accounts-unavailable"
        />
      </div>
    )
  }
  return (
    <div style={styles.card} data-testid="routing-accounts">
      <div style={styles.header}>
        <Text size="sm" weight="semibold" uppercase>Accounts</Text>
        <Text as="span" size="xs" tone="muted" data-testid="routing-accounts-summary">
          {`${accounts.summary.configured} configured · ${accounts.summary.leased} leased · ${accounts.summary.inFlight} in flight`}
        </Text>
        <span style={styles.spacer} />
        <Text as="span" size="xs" tone="muted">{`window ${accounts.windowSeconds}s`}</Text>
      </div>
      <div style={styles.rows}>
        {accounts.accounts.map(account => (
          <AccountRow key={account.accountId} account={account} styles={styles} />
        ))}
      </div>
      <Text as="span" size="xs" tone="muted" data-testid="routing-accounts-evidence">
        {`Observation evidence since ${accounts.evidenceSince || 'gateway start'}. Eligibility is not shown: it exists only inside a route explanation.`}
      </Text>
      {accounts.evidenceTruncated && (
        <Text as="span" size="xs" tone="warning" data-testid="routing-accounts-truncated">
          Older routes have been evicted from the gateway's bounded ring, so health is
          computed from a subsample of this window.
        </Text>
      )}
    </div>
  )
}

function LeaseRow({ lease, styles }) {
  return (
    <div style={styles.row} data-testid={`routing-lease-${lease.keyId}`}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{lease.repoSlug}</Text>
        <Text as="span" size="xs" tone="muted">{`${lease.accountId} · ${lease.role}`}</Text>
      </span>
      <span style={styles.facts}>
        <Fact label="age" value={lease.ageLabel} styles={styles} testid={`routing-lease-age-${lease.keyId}`} />
      </span>
    </div>
  )
}

function InFlightRow({ route, styles }) {
  return (
    <div style={styles.row} data-testid={`routing-inflight-${route.requestId}`}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{route.repoSlug}</Text>
        <Text as="span" size="xs" tone="muted">
          {`${route.accountId} · ${route.role}${route.issueNumber ? ` · #${route.issueNumber}` : ''}`}
        </Text>
      </span>
      <span style={styles.facts}>
        <Fact label="age" value={route.ageLabel} styles={styles} testid={`routing-inflight-age-${route.requestId}`} />
        <Badge tone="accent">streaming</Badge>
      </span>
    </div>
  )
}

function RecentRow({ route, styles }) {
  return (
    <div style={styles.row} data-testid={`routing-recent-${route.requestId}`}>
      <span style={styles.nameCol}>
        <Text size="sm" weight="semibold" style={styles.name}>{route.repoSlug}</Text>
        <Text as="span" size="xs" tone="muted">
          {`${route.accountId} · ${route.role}${route.issueNumber ? ` · #${route.issueNumber}` : ''}`}
        </Text>
      </span>
      <span style={styles.facts}>
        <Fact
          label="requested"
          value={route.modelRequested || '—'}
          styles={styles}
          testid={`routing-recent-requested-${route.requestId}`}
        />
        <Fact
          label="served"
          value={route.modelServed || '—'}
          styles={styles}
          testid={`routing-recent-served-${route.requestId}`}
        />
        <Fact label="latency" value={route.latencyLabel} styles={styles} />
        <Fact label="cost" value={route.costLabel} styles={styles} />
        <Badge tone={route.statusTone} data-testid={`routing-recent-status-${route.requestId}`}>
          {`${route.status} ${route.statusCode}`}
        </Badge>
      </span>
    </div>
  )
}

function LiveView({ live, styles }) {
  if (!live.available) {
    return (
      <div style={styles.card} data-testid="routing-live">
        <Text size="sm" weight="semibold" uppercase>Live routes</Text>
        <SourceUnavailable
          sourceState={live.sourceState}
          styles={styles}
          testid="routing-live-unavailable"
        />
      </div>
    )
  }
  return (
    <div style={styles.card} data-testid="routing-live">
      <div style={styles.header}>
        <Text size="sm" weight="semibold" uppercase>Live routes</Text>
        <Text as="span" size="xs" tone="muted" data-testid="routing-live-summary">
          {`${live.leases.length} leases · ${live.inFlight.length} in flight · ${live.recent.length} recent`}
        </Text>
      </div>
      <div style={styles.section}>
        <Text as="span" size="xs" tone="muted" uppercase>In flight</Text>
        {live.inFlight.length === 0 ? (
          <Text role="status" size="sm" tone="muted" data-testid="routing-inflight-empty">
            No request is streaming right now.
          </Text>
        ) : (
          <div style={styles.rows}>
            {live.inFlight.map(route => (
              <InFlightRow key={route.requestId} route={route} styles={styles} />
            ))}
          </div>
        )}
      </div>
      <div style={styles.section}>
        <Text as="span" size="xs" tone="muted" uppercase>Leases</Text>
        {live.leases.length === 0 ? (
          <Text role="status" size="sm" tone="muted" data-testid="routing-leases-empty">
            No unexpired virtual key is bound to an account.
          </Text>
        ) : (
          <div style={styles.rows}>
            {live.leases.map(lease => (
              <LeaseRow key={lease.keyId} lease={lease} styles={styles} />
            ))}
          </div>
        )}
      </div>
      <div style={styles.section}>
        <Text as="span" size="xs" tone="muted" uppercase>Recent</Text>
        {live.recent.length === 0 ? (
          <Text role="status" size="sm" tone="muted" data-testid="routing-recent-empty">
            No terminal route observed since the gateway started.
          </Text>
        ) : (
          <div style={styles.scroller}>
            <div style={styles.rows}>
              {live.recent.map(route => (
                <RecentRow key={route.requestId} route={route} styles={styles} />
              ))}
            </div>
          </div>
        )}
        {live.truncated && (
          <Text as="span" size="xs" tone="warning" data-testid="routing-recent-truncated">
            Older routes are not shown — the gateway's ring has evicted them, or this page
            did not return them. This view is not a complete history.
          </Text>
        )}
      </div>
    </div>
  )
}

/**
 * @param {{ accounts?: object, live?: object, routingView?: string, select?: Function }} props
 */
export default function RoutingMode({
  accounts = EMPTY_GATEWAY_ACCOUNTS_VM,
  live = EMPTY_GATEWAY_LIVE_VM,
  routingView = 'accounts',
  select = () => {},
}) {
  const t = useTokens()
  const styles = makeStyles(t)
  const view = ROUTING_VIEWS.some(v => v.key === routingView) ? routingView : 'accounts'

  return (
    <div style={styles.wrap} data-testid="routing-mode">
      <div style={styles.viewToggle} role="tablist" aria-label="Routing views">
        {ROUTING_VIEWS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={view === key}
            data-testid={`routing-view-${key}`}
            style={styles.viewButton(view === key)}
            onClick={() => select('routingView', key)}
          >
            {label}
          </button>
        ))}
      </div>
      {view === 'live' ? (
        <LiveView live={live} styles={styles} />
      ) : (
        <AccountsView accounts={accounts} styles={styles} />
      )}
    </div>
  )
}
