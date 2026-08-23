/**
 * RoutingMode — the gateway Routing workspace
 * (#11534 ADR-0138, #11538 ADR-0140, #11540 ADR-0142).
 *
 * All five URL-addressable views the routing-control-plane design reserves, at
 * `?mode=routing&routingView=accounts|effective|policies|live|audit`. P0 shipped
 * the two read-only ones; P2 fills in the remaining three, and one of them —
 * POLICIES — is the console's first write surface. Enforcement is still not
 * built: editing a policy changes what the shadow resolver would decide and
 * records the disagreement; legacy routing still decides every live spawn.
 *
 * ACCOUNTS shows each compiled gateway account with its facts kept SEPARATE:
 * credential configured, administrative state, pool capacity, circuit state,
 * leases, in-flight requests, observed traffic, and passive health.
 * "Configured" is never drawn as "healthy", "healthy" is never drawn as
 * "currently routing", and `unverified` is neutral rather than green. There is
 * no eligibility badge: eligibility only exists inside a route explanation,
 * which this phase does not compute.
 *
 * ACCOUNTS is also the console's HOST-ADMIN surface (#11540, ADR-0142). Its
 * rules mirror `PolicyWorkspacePanel`'s, because they are the same rules:
 *   - it says whether it may write, and why not — the backend's `write_gate`
 *     comes down on the audit read, so a dashboard bound beyond loopback
 *     renders the reason instead of buttons that would always 403;
 *   - it acts against the revision it was LOADED with, never the one the live
 *     poll is showing, so a lost update produces the 409 it should;
 *   - a 409 says "reload, someone else changed this" — not "error";
 *   - revoking leases needs a second, explicit confirmation: it ends live work
 *     on every spawn holding a key for that account;
 *   - the operator token lives in component state for this page view and
 *     reaches no view model, no URL, and no browser storage.
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
import { Badge, Button, Text, useTokens } from '../styles/primitives'
import EffectiveRoutesPanel from './EffectiveRoutesPanel'
import PolicyAuditPanel from './PolicyAuditPanel'
import PolicyWorkspacePanel from './PolicyWorkspacePanel'
import {
  EMPTY_ACCOUNT_ADMIN_VM,
  EMPTY_GATEWAY_ACCOUNTS_VM,
  EMPTY_GATEWAY_LIVE_VM,
  accountWriteGateMessage,
  adminRejectionMessage,
} from './model/gatewayRouting'
import {
  EMPTY_EFFECTIVE_MATRIX_VM,
  EMPTY_POLICY_AUDIT_VM,
  EMPTY_POLICY_WORKSPACE_VM,
} from './model/policyWorkspace'

export const ROUTING_VIEWS = [
  { key: 'accounts', label: 'Accounts' },
  { key: 'effective', label: 'Effective routes' },
  { key: 'policies', label: 'Policies' },
  { key: 'live', label: 'Live' },
  { key: 'audit', label: 'Audit' },
]

/** The administrative states an operator can move an account into. */
export const ADMIN_STATE_CONTROLS = [
  { state: 'enabled', label: 'Enable' },
  { state: 'draining', label: 'Drain' },
  { state: 'disabled', label: 'Disable' },
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
    actions: { display: 'flex', gap: t.space.xxs, flexShrink: 0, flexWrap: 'wrap' },
    field: { display: 'flex', flexDirection: 'column', gap: t.space.xxs, minWidth: 240 },
    input: {
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      borderRadius: t.radius.sm,
      borderWidth: 1,
      borderStyle: 'solid',
      borderColor: t.color.border,
      background: t.color.bg,
      color: t.color.text,
      fontFamily: t.type.family.mono,
      fontSize: t.type.size.sm,
      boxSizing: 'border-box',
      width: '100%',
    },
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

/**
 * The enable / drain / disable / revoke controls for one account.
 *
 * Rendered ALWAYS once the admin feed has been read, and disabled rather than
 * hidden when the write gate is closed — mirroring how `PolicyWorkspacePanel`
 * treats `editable`. A control that vanished would leave an operator wondering
 * whether this build has the capability at all; a disabled one plus the gate's
 * reason answers that.
 */
function AccountAdminControls({ account, styles, writable, confirming, onSetState, onRevoke, onConfirm, onCancel }) {
  const id = account.accountId
  return (
    <span style={styles.actions} data-testid={`routing-account-controls-${id}`}>
      {ADMIN_STATE_CONTROLS.map(({ state, label }) => (
        <Button
          key={state}
          variant="ghost"
          size="sm"
          data-testid={`routing-account-${state}-${id}`}
          // The state already in force is not offered: writing it would burn a
          // revision to change nothing, and every other tab's pinned revision
          // with it.
          disabled={!writable || account.administrativeState === state}
          onClick={() => onSetState(account, state)}
        >
          {label}
        </Button>
      ))}
      {confirming ? (
        <>
          <Button
            variant="danger"
            size="sm"
            data-testid={`routing-account-revoke-confirm-${id}`}
            disabled={!writable}
            onClick={() => onRevoke(account)}
          >
            {`Confirm — end ${account.leaseCount} lease(s)`}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            data-testid={`routing-account-revoke-cancel-${id}`}
            onClick={onCancel}
          >
            Cancel
          </Button>
        </>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          data-testid={`routing-account-revoke-${id}`}
          disabled={!writable}
          onClick={() => onConfirm(id)}
        >
          Revoke leases
        </Button>
      )}
    </span>
  )
}

function AccountRow({ account, styles, admin, controls }) {
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
          value={account.leaseCapacityLabel}
          styles={styles}
          testid={`routing-account-leases-${account.accountId}`}
        />
        <Fact
          label="in flight"
          value={account.requestCapacityLabel}
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
          tone={account.circuitTone}
          data-testid={`routing-account-circuit-${account.accountId}`}
        >
          {`circuit ${account.circuitState}`}
        </Badge>
        {account.circuitState === 'open' && (
          // Only when OPEN: a reset time and a trip condition on a closed
          // breaker are last-time facts, and rendering them beside "closed"
          // would read as a lane that is currently refused.
          <Fact
            label="opened"
            value={`${account.circuitLastCondition || 'unknown condition'} · ${
              account.circuitResetAt
                ? `resets ${account.circuitResetAt}`
                : 'no reset time published'
            } · ${account.circuitConsecutiveFailures} consecutive`}
            styles={styles}
            testid={`routing-account-circuit-detail-${account.accountId}`}
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
      {admin.available && (
        <AccountAdminControls account={account} styles={styles} {...controls} />
      )}
    </div>
  )
}

function AccountsView({ accounts, admin, styles, onSetAccountState, onRevokeLeases }) {
  const [token, setToken] = React.useState('')
  const [confirming, setConfirming] = React.useState(null)
  const [conflict, setConflict] = React.useState(null)
  // The revision these controls act AGAINST — pinned to the one the operator
  // actually saw, never re-read from the live poll at click time. Reading
  // `admin.revision` on click would make `expected_revision` the WINNER's
  // revision, so the 409 that stops a lost update could never fire from this
  // console (the same trap ADR-0140 D3 named for the policy form).
  const [basis, setBasis] = React.useState(null)

  React.useEffect(() => {
    if (!admin.available) return
    setBasis(prev => (prev === null ? admin.revision : prev))
  }, [admin.available, admin.revision])

  const pinned = basis === null ? admin.revision : basis
  // Somebody else's revision landed under this view. The action is not
  // necessarily wrong, but it was chosen against an overlay that no longer
  // exists, so it may not be sent until the operator re-reads.
  const rebased = basis !== null && admin.available && admin.revision !== basis
  const writable = admin.editable && !!token && !rebased && pinned != null

  const rebase = () => {
    setBasis(admin.revision)
    setConflict(null)
    setConfirming(null)
  }

  const commit = async body => {
    setConfirming(null)
    const result = await body()
    setConflict(result && result.ok === false ? result : null)
    // `?? basis`, never `?? null`: dropping the pin would restore the unpinned
    // behaviour where `expected_revision` follows the live poll.
    if (result && result.ok) setBasis(result.revision ?? basis)
  }

  const controls = {
    writable,
    onSetState: (account, state) =>
      commit(() =>
        onSetAccountState(
          account.accountId,
          { administrativeState: state, expectedRevision: pinned },
          token,
        ),
      ),
    onRevoke: account =>
      commit(() =>
        onRevokeLeases(account.accountId, { expectedRevision: pinned }, token),
      ),
    onConfirm: setConfirming,
    onCancel: () => setConfirming(null),
  }

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
        {admin.available && (
          <Text as="span" size="xs" tone="muted" data-testid="routing-admin-revision">
            {`overlay revision ${admin.revision}`}
          </Text>
        )}
        <span style={styles.spacer} />
        <Text as="span" size="xs" tone="muted">{`window ${accounts.windowSeconds}s`}</Text>
      </div>
      {admin.available && !admin.editable && (
        <div style={styles.note} data-testid="routing-admin-write-gate">
          <Text role="alert" size="sm" tone="warning">
            {admin.chainVerified
              ? accountWriteGateMessage(admin.writeGate) ||
                'Account administration is unavailable on this dashboard.'
              : adminRejectionMessage('audit-chain-broken')}
          </Text>
        </div>
      )}
      {admin.available && admin.editable && (
        <label style={styles.field}>
          <Text as="span" size="xs" tone="muted" uppercase>
            operator token (never stored)
          </Text>
          <input
            style={styles.input}
            type="password"
            autoComplete="off"
            data-testid="routing-admin-token"
            value={token}
            onChange={event => setToken(event.target.value)}
          />
        </label>
      )}
      {rebased && (
        <div style={styles.note} data-testid="routing-admin-rebased">
          <Text role="alert" size="sm" tone="warning">
            {`${adminRejectionMessage('stale-revision')} This view was loaded against revision ${basis}; revision ${admin.revision} is current.`}
          </Text>
          <Button
            variant="ghost"
            size="sm"
            data-testid="routing-admin-rebase-button"
            onClick={rebase}
          >
            {`Re-base on r${admin.revision}`}
          </Button>
        </div>
      )}
      {conflict && (
        <div style={styles.note} data-testid="routing-admin-conflict">
          <Text role="alert" size="sm" tone="danger">
            {adminRejectionMessage(conflict.code)}
          </Text>
        </div>
      )}
      <div style={styles.rows}>
        {accounts.accounts.map(account => (
          <AccountRow
            key={account.accountId}
            account={account}
            admin={admin}
            controls={{ ...controls, confirming: confirming === account.accountId }}
            styles={styles}
          />
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
 * @param {{
 *   accounts?: object, admin?: object, live?: object, workspace?: object,
 *   matrix?: object, audit?: object, policySourceState?: string,
 *   preview?: object|null, rejection?: string|null,
 *   routingView?: string, routingSelection?: string|null, select?: Function,
 *   onPreviewPolicy?: Function, onSavePolicy?: Function, onClearPreview?: Function,
 *   onSetAccountState?: Function, onRevokeLeases?: Function,
 * }} props
 */
export default function RoutingMode({
  accounts = EMPTY_GATEWAY_ACCOUNTS_VM,
  admin = EMPTY_ACCOUNT_ADMIN_VM,
  live = EMPTY_GATEWAY_LIVE_VM,
  workspace = EMPTY_POLICY_WORKSPACE_VM,
  matrix = EMPTY_EFFECTIVE_MATRIX_VM,
  audit = EMPTY_POLICY_AUDIT_VM,
  policySourceState = 'loading',
  preview = null,
  rejection = null,
  routingView = 'accounts',
  routingSelection = null,
  select = () => {},
  onPreviewPolicy = () => {},
  onSavePolicy = () => {},
  onClearPreview = () => {},
  onSetAccountState = () => ({ ok: false, code: 'gateway-not-configured' }),
  onRevokeLeases = () => ({ ok: false, code: 'gateway-not-configured' }),
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
      {renderView({
        view,
        accounts,
        admin,
        live,
        workspace,
        matrix,
        audit,
        policySourceState,
        preview,
        rejection,
        routingSelection,
        select,
        onPreviewPolicy,
        onSavePolicy,
        onClearPreview,
        onSetAccountState,
        onRevokeLeases,
        styles,
      })}
    </div>
  )
}

/** One place deciding which view is showing, so the toggle cannot drift from it. */
function renderView({
  view,
  accounts,
  admin,
  live,
  workspace,
  matrix,
  audit,
  policySourceState,
  preview,
  rejection,
  routingSelection,
  select,
  onPreviewPolicy,
  onSavePolicy,
  onClearPreview,
  onSetAccountState,
  onRevokeLeases,
  styles,
}) {
  if (view === 'live') return <LiveView live={live} styles={styles} />
  if (view === 'effective') {
    return (
      <EffectiveRoutesPanel
        matrix={matrix}
        sourceState={policySourceState}
        selection={routingSelection}
        select={select}
      />
    )
  }
  if (view === 'policies') {
    return (
      <PolicyWorkspacePanel
        workspace={workspace}
        preview={preview}
        rejection={rejection}
        audit={audit}
        sourceState={policySourceState}
        selection={routingSelection}
        select={select}
        onPreview={onPreviewPolicy}
        onSave={onSavePolicy}
        onClearPreview={onClearPreview}
      />
    )
  }
  if (view === 'audit')
    return <PolicyAuditPanel audit={audit} sourceState={policySourceState} />
  return (
    <AccountsView
      accounts={accounts}
      admin={admin}
      styles={styles}
      onSetAccountState={onSetAccountState}
      onRevokeLeases={onRevokeLeases}
    />
  )
}
