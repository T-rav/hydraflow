/**
 * PolicyWorkspacePanel — the `?mode=routing&routingView=policies` editor
 * (#11538, ADR-0140).
 *
 * The rules this panel exists to make visible, in the order an operator meets
 * them:
 *
 *   - **It says whether it may write, and why not.** `write_gate` comes down on
 *     the read payload, so a dashboard bound beyond loopback renders the reason
 *     instead of a save button that would always 403.
 *   - **It edits only this repository's rules.** An inherited class or global
 *     rule renders with an `inherited` badge and no actions. There is no repo
 *     field in the form: the repository comes from the loaded workspace, and a
 *     field for it would be a field for escaping the scope.
 *   - **It previews before it writes.** Save is disabled until a preview says
 *     the edit is writable, and the preview lists every validation issue and
 *     every live route the edit would move.
 *   - **It saves against the revision it loaded.** A 409 renders the revision
 *     that won and asks for a reload rather than retrying over it.
 *   - **The operator token is never stored.** It lives in component state for
 *     this page view, is passed straight to the save call, and reaches no view
 *     model, no URL, and no browser storage.
 */

import React from 'react'
import { Badge, Button, Text, useTokens } from '../styles/primitives'
import {
  EMPTY_POLICY_DRAFT,
  EMPTY_POLICY_WORKSPACE_VM,
  PROVIDER_LOCK_CHOICES,
  REQUIREMENT_CHOICES,
  WORKER_ROLE_CHOICES,
  draftToPolicy,
  policyToDraft,
  rejectionMessage,
  snapshotTone,
  writeGateMessage,
} from './model/policyWorkspace'

const CORRUPT_MESSAGE =
  'The policy snapshot on disk cannot be read. It is NOT "no policies" — the resolver holds every route until it is repaired, and writes are refused so the revision counter cannot restart.'

function makeStyles(t) {
  return {
    wrap: { display: 'flex', flexDirection: 'column', gap: t.space.md },
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
    selectedRow: {
      display: 'flex',
      alignItems: 'baseline',
      flexWrap: 'wrap',
      gap: t.space.sm,
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      borderRadius: t.radius.sm,
      background: `color-mix(in srgb, ${t.color.accent} 12%, transparent)`,
    },
    nameCol: {
      display: 'flex',
      flexDirection: 'column',
      minWidth: 0,
      flex: '1 1 auto',
    },
    actions: { display: 'flex', gap: t.space.xxs, flexShrink: 0, flexWrap: 'wrap' },
    linkButton: {
      appearance: 'none',
      background: 'transparent',
      borderWidth: 0,
      padding: 0,
      cursor: 'pointer',
      textAlign: 'left',
    },
    form: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
      gap: t.space.sm,
    },
    field: { display: 'flex', flexDirection: 'column', gap: t.space.xxs },
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
    roleSelect: {
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
      minHeight: 96,
    },
    checkboxRow: { display: 'flex', alignItems: 'center', gap: t.space.xxs },
    note: { padding: `${t.space.xxs}px 0` },
    issues: { display: 'flex', flexDirection: 'column', gap: t.space.xxs },
  }
}

/** Explicit degraded / advisory line. Never an empty list standing in for one. */
function Notice({ tone, children, styles, testid }) {
  return (
    <div style={styles.note} data-testid={testid}>
      <Text role="alert" size="sm" tone={tone}>
        {children}
      </Text>
    </div>
  )
}

function Field({ label, children, styles }) {
  return (
    <label style={styles.field}>
      <Text as="span" size="xs" tone="muted" uppercase>
        {label}
      </Text>
      {children}
    </label>
  )
}

function PolicyRow({ policy, selected, editable, onSelect, onEdit, onDisable, styles }) {
  return (
    <div
      style={selected ? styles.selectedRow : styles.row}
      data-testid={`policy-row-${policy.id}`}
    >
      <span style={styles.nameCol}>
        <button
          type="button"
          style={styles.linkButton}
          data-testid={`policy-select-${policy.id}`}
          onClick={() => onSelect(policy.id)}
        >
          <Text size="sm" weight="semibold">
            {policy.id}
          </Text>
        </button>
        <Text as="span" size="xs" tone="muted">
          {policy.summary}
        </Text>
      </span>
      <Badge
        tone={policy.enabled ? 'info' : 'neutral'}
        data-testid={`policy-enabled-${policy.id}`}
      >
        {policy.enabled ? 'enabled' : 'disabled'}
      </Badge>
      <Badge
        tone={policy.editable ? 'accent' : 'neutral'}
        data-testid={`policy-scope-${policy.id}`}
      >
        {policy.editable ? 'this repo' : 'inherited'}
      </Badge>
      {policy.editable && editable && (
        <span style={styles.actions}>
          <Button
            variant="ghost"
            size="sm"
            data-testid={`policy-edit-${policy.id}`}
            onClick={() => onEdit(policy)}
          >
            Edit
          </Button>
          {policy.enabled && (
            <Button
              variant="ghost"
              size="sm"
              data-testid={`policy-disable-${policy.id}`}
              onClick={() => onDisable(policy)}
            >
              Disable
            </Button>
          )}
        </span>
      )}
    </div>
  )
}

function PreviewSummary({ preview, styles }) {
  if (!preview) {
    return (
      <Text as="span" size="xs" tone="muted" data-testid="policy-preview-empty">
        Preview an edit to see which live routes it would move.
      </Text>
    )
  }
  return (
    <div style={styles.issues} data-testid="policy-preview">
      <Text as="span" size="xs" tone="muted">
        {`Revision ${preview.expectedRevision} → ${preview.nextRevision} · ${preview.movedCells.length} route(s) move`}
      </Text>
      {preview.stale && (
        <Notice tone="warning" styles={styles} testid="policy-preview-stale">
          {rejectionMessage('stale-revision')}
        </Notice>
      )}
      {preview.rejection && (
        <Notice tone="danger" styles={styles} testid="policy-preview-rejection">
          {rejectionMessage(preview.rejection)}
        </Notice>
      )}
      {preview.issues.map(issue => (
        <Text
          key={`${issue.code}-${issue.policyId}`}
          as="span"
          size="xs"
          tone="danger"
          data-testid={`policy-issue-${issue.code}`}
        >
          {`${issue.policyId}: ${issue.code}${issue.detail ? ` (${issue.detail})` : ''}`}
        </Text>
      ))}
      {preview.movedCells.map(cell => (
        <Text
          key={cell.key}
          as="span"
          size="xs"
          tone="muted"
          data-testid={`policy-moved-${cell.key}`}
        >
          {`${cell.key} · ${cell.before?.state || '—'} → ${cell.after?.state || '—'}`}
        </Text>
      ))}
    </div>
  )
}

/**
 * @param {{
 *   workspace?: object, preview?: object|null, rejection?: string|null,
 *   audit?: object, selection?: string|null, select?: Function,
 *   onPreview?: Function, onSave?: Function, onClearPreview?: Function,
 * }} props
 */
export default function PolicyWorkspacePanel({
  workspace = EMPTY_POLICY_WORKSPACE_VM,
  preview = null,
  rejection = null,
  audit = null,
  selection = null,
  select = () => {},
  onPreview = () => {},
  onSave = () => {},
  onClearPreview = () => {},
}) {
  const t = useTokens()
  const styles = makeStyles(t)
  const [draft, setDraft] = React.useState(EMPTY_POLICY_DRAFT)
  const [kind, setKind] = React.useState('create')
  const [token, setToken] = React.useState('')
  const [conflict, setConflict] = React.useState(null)

  const editable = workspace.editable && workspace.scope === 'repo'
  const set = (key, value) => {
    setDraft(prev => ({ ...prev, [key]: value }))
    onClearPreview()
  }

  const mutation = () => ({
    kind,
    expected_revision: workspace.revision,
    policy: draftToPolicy(draft, workspace.repo),
  })

  const startEdit = policy => {
    setDraft(policyToDraft(policy))
    setKind('update')
    setConflict(null)
    onClearPreview()
    select('routingSelection', policy.id)
  }

  const startCreate = () => {
    setDraft(EMPTY_POLICY_DRAFT)
    setKind('create')
    setConflict(null)
    onClearPreview()
  }

  const commit = async body => {
    const result = await onSave(body, token)
    setConflict(result && result.ok === false ? result : null)
  }

  if (workspace.scope === 'aggregate') {
    return (
      <div style={styles.card} data-testid="policy-workspace-aggregate">
        <Text size="sm" weight="semibold" uppercase>
          Policies (all repos)
        </Text>
        <Notice tone="warning" styles={styles} testid="policy-aggregate-readonly">
          Aggregate mode is read-only. Pick one repository to edit its routing
          policy; class and global rules belong to a host-admin scope.
        </Notice>
        <div style={styles.rows}>
          {workspace.repos.map(row => (
            <div style={styles.row} key={row.repo} data-testid={`policy-repo-${row.slug}`}>
              <span style={styles.nameCol}>
                <Text size="sm" weight="semibold">
                  {row.repo}
                </Text>
                <Text as="span" size="xs" tone="muted">
                  {`revision ${row.revision} · ${row.policyCount} policies · ${row.editableCount} editable`}
                </Text>
              </span>
              <Badge tone={snapshotTone(row.state)}>{row.state}</Badge>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div style={styles.wrap} data-testid="policy-workspace">
      <div style={styles.card}>
        <div style={styles.header}>
          <Text size="sm" weight="semibold" uppercase>
            Policies
          </Text>
          <Text as="span" size="xs" tone="muted" data-testid="policy-revision">
            {`${workspace.repo || 'this repo'} · revision ${workspace.revision}`}
          </Text>
          <Badge tone={snapshotTone(workspace.state)} data-testid="policy-snapshot-state">
            {workspace.state}
          </Badge>
          <span style={styles.spacer} />
          {editable ? (
            <Button variant="ghost" size="sm" data-testid="policy-new" onClick={startCreate}>
              New policy
            </Button>
          ) : null}
        </div>
        {workspace.state === 'corrupt' && (
          <Notice tone="danger" styles={styles} testid="policy-snapshot-corrupt">
            {CORRUPT_MESSAGE}
          </Notice>
        )}
        {!editable && (
          <Notice tone="warning" styles={styles} testid="policy-write-gate">
            {writeGateMessage(workspace.writeGate) ||
              'Policy writes are unavailable on this dashboard.'}
          </Notice>
        )}
        {workspace.policies.length === 0 ? (
          <Text role="status" size="sm" tone="muted" data-testid="policy-empty">
            No policy has been written for this repository. Legacy routing decides
            every route until one is.
          </Text>
        ) : (
          <div style={styles.rows}>
            {workspace.policies.map(policy => (
              <PolicyRow
                key={policy.id}
                policy={policy}
                selected={selection === policy.id}
                editable={editable}
                styles={styles}
                onSelect={id => select('routingSelection', id)}
                onEdit={startEdit}
                onDisable={row =>
                  commit({
                    kind: 'disable',
                    expected_revision: workspace.revision,
                    policy_id: row.id,
                  })
                }
              />
            ))}
          </div>
        )}
        {workspace.issues.map(issue => (
          <Text
            key={`${issue.code}-${issue.policyId}`}
            as="span"
            size="xs"
            tone="danger"
            data-testid={`policy-snapshot-issue-${issue.code}`}
          >
            {`${issue.policyId}: ${issue.code}`}
          </Text>
        ))}
      </div>

      {editable && (
        <div style={styles.card} data-testid="policy-editor">
          <div style={styles.header}>
            <Text size="sm" weight="semibold" uppercase>
              {kind === 'create' ? 'New policy' : `Edit ${draft.id}`}
            </Text>
            <Text as="span" size="xs" tone="muted">
              {`scoped to ${workspace.repo}`}
            </Text>
          </div>
          <div style={styles.form}>
            <Field label="policy id" styles={styles}>
              <input
                style={styles.input}
                data-testid="policy-field-id"
                value={draft.id}
                readOnly={kind !== 'create'}
                onChange={event => set('id', event.target.value)}
              />
            </Field>
            <Field label="provider lock" styles={styles}>
              <select
                style={styles.input}
                data-testid="policy-field-lock"
                value={draft.providerLock}
                onChange={event => set('providerLock', event.target.value)}
              >
                {PROVIDER_LOCK_CHOICES.map(choice => (
                  <option key={choice || 'none'} value={choice}>
                    {choice || 'none'}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="requirement" styles={styles}>
              <select
                style={styles.input}
                data-testid="policy-field-requirement"
                value={draft.requirement}
                onChange={event => set('requirement', event.target.value)}
              >
                {REQUIREMENT_CHOICES.map(choice => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="effective model" styles={styles}>
              <input
                style={styles.input}
                data-testid="policy-field-model"
                value={draft.effectiveModel}
                onChange={event => set('effectiveModel', event.target.value)}
              />
            </Field>
            <Field label="priority" styles={styles}>
              <input
                style={styles.input}
                type="number"
                data-testid="policy-field-priority"
                value={draft.priority}
                onChange={event => set('priority', event.target.value)}
              />
            </Field>
            <Field label="when unavailable" styles={styles}>
              <select
                style={styles.input}
                data-testid="policy-field-unavailable"
                value={draft.onUnavailable}
                onChange={event => set('onUnavailable', event.target.value)}
              >
                <option value="hold">hold</option>
                <option value="reject">reject</option>
              </select>
            </Field>
            <Field label="roles (empty = any)" styles={styles}>
              <select
                multiple
                style={styles.roleSelect}
                data-testid="policy-field-roles"
                value={draft.roles}
                onChange={event =>
                  set(
                    'roles',
                    Array.from(event.target.selectedOptions).map(option => option.value),
                  )
                }
              >
                {WORKER_ROLE_CHOICES.map(role => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="operator token (never stored)" styles={styles}>
              <input
                style={styles.input}
                type="password"
                autoComplete="off"
                data-testid="policy-field-token"
                value={token}
                onChange={event => setToken(event.target.value)}
              />
            </Field>
          </div>
          <label style={styles.checkboxRow}>
            <input
              type="checkbox"
              data-testid="policy-field-enabled"
              checked={draft.enabled}
              onChange={event => set('enabled', event.target.checked)}
            />
            <Text as="span" size="xs" tone="muted">
              enabled
            </Text>
          </label>
          <PreviewSummary preview={preview} styles={styles} />
          {conflict && (
            <Notice tone="danger" styles={styles} testid="policy-conflict">
              {`${rejectionMessage(conflict.code)}${
                conflict.actualRevision == null
                  ? ''
                  : ` Current revision is ${conflict.actualRevision}.`
              }`}
            </Notice>
          )}
          {rejection && !conflict && (
            <Notice tone="danger" styles={styles} testid="policy-rejection">
              {rejectionMessage(rejection)}
            </Notice>
          )}
          <div style={styles.actions}>
            <Button
              variant="ghost"
              size="sm"
              data-testid="policy-preview-button"
              onClick={() => onPreview(mutation())}
            >
              Preview
            </Button>
            <Button
              variant="primary"
              size="sm"
              data-testid="policy-save-button"
              disabled={!preview || !preview.writable || !token}
              onClick={() => commit(mutation())}
            >
              Save revision {workspace.revision + 1}
            </Button>
          </div>
        </div>
      )}

      {editable && audit && audit.rollbackTargets.length > 0 && (
        <div style={styles.card} data-testid="policy-rollback">
          <Text size="sm" weight="semibold" uppercase>
            Roll back
          </Text>
          <Text as="span" size="xs" tone="muted">
            A rollback restores a revision’s policies as a NEW revision. It never
            rewrites history, and it leaves inherited rules alone.
          </Text>
          <div style={styles.actions}>
            {audit.rollbackTargets.map(target => (
              <Button
                key={target}
                variant="ghost"
                size="sm"
                data-testid={`policy-rollback-${target}`}
                disabled={!token}
                onClick={() =>
                  commit({
                    kind: 'rollback',
                    expected_revision: workspace.revision,
                    target_revision: target,
                  })
                }
              >
                {`to r${target}`}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
