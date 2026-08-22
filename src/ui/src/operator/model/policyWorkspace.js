/**
 * Routing-policy workspace view models (issue #11538, ADR-0140). Pure — no
 * fetch, no React.
 *
 * Four reducers over the `/api/gateway/policies*` payloads:
 *
 *   toPolicyWorkspace(raw)     -> the snapshot, its policies, and the write gate
 *   toEffectiveMatrix(raw)     -> the role x face grid, each cell pinned to one
 *                                 revision and carrying its own explanation
 *   toPolicyAudit(raw)         -> the append-only mutation history
 *   toPolicyPreview(raw)       -> a candidate edit's conflicts and moved routes
 *
 * The honesty rules mirror model/gatewayRouting.js and are load-bearing here for
 * the same reason:
 *
 *   - `state` survives into the VM, so a CORRUPT snapshot renders as an explicit
 *     degraded state and never as "this repo has no policies";
 *   - `editable` and `writeGate` survive too, so an editor renders read-only
 *     with the REASON rather than offering a save button that always fails;
 *   - a cell that no policy claims is `unmanaged` — "legacy routing decides this
 *     one" — never a failure badge. Shadow mode is still authoritative;
 *   - `loaded` distinguishes "not fetched yet" from "fetched and empty".
 *
 * No credential is ever part of a VM. The operator token lives in component
 * state for the lifetime of a page view and is passed straight to the save call.
 */

const EMPTY_LIST = Object.freeze([])

function num(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function str(value) {
  return value == null ? '' : String(value)
}

function orNull(value) {
  return value == null || value === '' ? null : String(value)
}

function list(value) {
  return Array.isArray(value) ? value : EMPTY_LIST
}

/** `{kind, value}` rendered as the `kind:value` selector the API accepts. */
export function requirementLabel(raw) {
  const kind = str(raw?.kind)
  const value = str(raw?.value)
  return kind && value ? `${kind}:${value}` : ''
}

/** Snapshot-state tone. `absent` is normal, `corrupt` is not. */
export function snapshotTone(state) {
  if (state === 'corrupt') return 'danger'
  if (state === 'ok') return 'success'
  return 'neutral'
}

/** Matrix-cell tone. `unmanaged` is neutral: no policy is not a fault. */
export function cellTone(state) {
  if (state === 'managed') return 'success'
  if (state === 'held') return 'warning'
  if (state === 'rejected' || state === 'unavailable') return 'danger'
  return 'neutral'
}

const WRITE_GATE_MESSAGES = Object.freeze({
  'workspace-disabled':
    'The routing policy workspace is switched off (gateway_policy_workspace_enabled). Policies are read-only.',
  'dashboard-not-loopback':
    'Policy writes are disabled because the dashboard is bound beyond loopback. There is no operator authorization boundary on a shared socket (ADR-0138 D5).',
  'no-operator-identity':
    'Policy writes need an authenticated operator identity. Set HYDRAFLOW_OPERATOR_TOKEN on the dashboard host, then enter it below.',
})

/** Why the write plane is closed, in the words an operator can act on. */
export function writeGateMessage(gate) {
  return WRITE_GATE_MESSAGES[gate] || ''
}

const REJECTION_MESSAGES = Object.freeze({
  'stale-revision':
    'Someone else saved a newer revision while this form was open. Reload before saving.',
  'snapshot-corrupt':
    'The policy snapshot on disk cannot be read. Repair it before writing; a write would restart the revision counter.',
  'audit-chain-broken':
    'The mutation history does not verify, so no rollback target can be trusted. Repair the chain before writing.',
  'journal-unreadable':
    'An interrupted policy transaction could not be read. Repair or remove the journal before writing again.',
  'policy-not-found': 'That policy is not in this revision.',
  'policy-already-exists': 'A policy with that id already exists in this revision.',
  'out-of-scope':
    'This editor writes rules scoped to exactly this repository. Class, global, and system-safety rules belong to a host-admin scope.',
  'unknown-revision': 'That revision is not in this repository’s mutation history.',
  'malformed-mutation': 'This edit is missing something the mutation needs.',
  'credential-shaped-value':
    'A policy value looks like a credential. Policies are stored unredacted and served to the browser — no secret may go in one.',
  'validation-failed': 'The resulting policy set is not admissible.',
  'unauthenticated-operator':
    'The operator token was not accepted. Check HYDRAFLOW_OPERATOR_TOKEN on the dashboard host.',
  'storage-unavailable': 'The policy store could not be written.',
})

/** A refusal code turned into prose. Unknown codes fall back to the code. */
export function rejectionMessage(code) {
  if (!code) return ''
  return REJECTION_MESSAGES[code] || String(code)
}

export const UNAVAILABLE_MESSAGE =
  'The policy plane did not answer. This is NOT "no policy" — nothing below has been read from this repository, and no write should be attempted until it loads.'

export const LOADING_MESSAGE =
  'Reading this repository’s policy state…'

export const STALE_MESSAGE =
  'The policy plane has stopped answering. Everything below is the last state that loaded, not the current one — reload before writing.'

export const AGGREGATE_MESSAGE =
  'Pick a repository to see its effective routes and mutation history. Aggregate mode reads the per-repository summary only.'

/**
 * The one line a panel renders instead of an empty state it has not earned.
 *
 * `unavailable` is checked FIRST, and deliberately: the hook keeps the
 * last-known view model on failure, so a feed that succeeded once and then died
 * would otherwise go completely silent while the panel kept rendering a frozen
 * revision as though it were current — and the audit badge kept asserting a
 * chain verification it can no longer back. Returning `''` is reserved for a
 * feed that is genuinely current, so a truly empty repository still gets its
 * calm "no policy has been written" copy.
 */
export function feedNotice(sourceState, loaded) {
  if (sourceState === 'aggregate') return loaded ? '' : AGGREGATE_MESSAGE
  if (sourceState === 'unavailable') return loaded ? STALE_MESSAGE : UNAVAILABLE_MESSAGE
  return loaded ? '' : LOADING_MESSAGE
}

/** Whether a panel may still make a positive claim about what it is showing. */
export function feedIsCurrent(sourceState) {
  return sourceState !== 'unavailable'
}

export const EMPTY_POLICY_WORKSPACE_VM = Object.freeze({
  loaded: false,
  scope: 'repo',
  repo: '',
  state: 'absent',
  revision: 0,
  contentHash: '',
  policies: EMPTY_LIST,
  issues: EMPTY_LIST,
  writeGate: 'no-operator-identity',
  editable: false,
  repos: EMPTY_LIST,
})

export const EMPTY_EFFECTIVE_MATRIX_VM = Object.freeze({
  loaded: false,
  repo: '',
  policyRevision: 0,
  snapshotHash: '',
  snapshotState: 'absent',
  cells: EMPTY_LIST,
})

export const EMPTY_POLICY_AUDIT_VM = Object.freeze({
  loaded: false,
  records: EMPTY_LIST,
  // `null`, NOT `true`. A chain nobody has read yet has not been verified, and
  // a badge claiming otherwise would be a positive tamper-evidence claim about
  // bytes this session never saw — the one lie this panel exists to prevent.
  verified: null,
  brokenAtSeq: null,
  truncated: false,
  rollbackTargets: EMPTY_LIST,
})

function toRequirementMapping(raw) {
  return {
    requirement: requirementLabel(raw?.requirement),
    effectiveModel: str(raw?.effective_model),
  }
}

/** One policy row, with the summary line the list renders instead of raw JSON. */
export function toPolicyRow(raw, editableIds) {
  const match = raw?.match || {}
  const action = raw?.action || {}
  const requirementMap = list(action.requirement_map).map(toRequirementMapping)
  const id = str(raw?.id)
  const providerLock = orNull(action.provider_lock)
  const mappings = requirementMap
    .map(entry => `${entry.requirement}→${entry.effectiveModel}`)
    .join(', ')
  return {
    id,
    enabled: raw?.enabled !== false,
    priority: num(raw?.priority),
    systemSafety: raw?.system_safety === true,
    editable: editableIds.has(id),
    repoIds: list(match.repo_ids).map(str),
    repoClasses: list(match.repo_classes).map(str),
    roles: list(match.roles).map(str),
    principalIds: list(match.principal_ids).map(str),
    requestFaces: list(match.request_faces).map(str),
    modelRequirements: list(match.model_requirements).map(requirementLabel),
    providerLock,
    accountPool: list(action.account_pool).map(str),
    requirementMap,
    allowedPatterns: list(action.allowed_patterns).map(str),
    onUnavailable: str(action.on_unavailable) || 'hold',
    summary: [providerLock || 'no provider lock', mappings || 'no model mapping']
      .filter(Boolean)
      .join(' · '),
  }
}

function toIssue(raw) {
  return {
    code: str(raw?.code),
    policyId: str(raw?.policy_id),
    detail: str(raw?.detail),
  }
}

function toRepoSummary(raw) {
  return {
    repo: str(raw?.repo),
    slug: str(raw?.slug),
    state: str(raw?.state) || 'absent',
    revision: num(raw?.revision),
    policyCount: num(raw?.policy_count),
    editableCount: num(raw?.editable_count),
    issueCount: num(raw?.issue_count),
  }
}

/** @param {object} raw @returns {typeof EMPTY_POLICY_WORKSPACE_VM} */
export function toPolicyWorkspace(raw) {
  if (!raw || typeof raw !== 'object') return EMPTY_POLICY_WORKSPACE_VM
  const editableIds = new Set(list(raw.editable_policy_ids).map(str))
  return {
    loaded: true,
    scope: str(raw.scope) || 'repo',
    repo: str(raw.repo),
    state: str(raw.state) || 'absent',
    revision: num(raw.revision),
    contentHash: str(raw.content_hash),
    policies: list(raw.policies).map(policy => toPolicyRow(policy, editableIds)),
    issues: list(raw.issues).map(toIssue),
    writeGate: str(raw.write_gate) || 'no-operator-identity',
    editable: raw.editable === true,
    repos: list(raw.repos).map(toRepoSummary),
  }
}

function toCell(raw) {
  const state = str(raw?.state) || 'unmanaged'
  return {
    key: str(raw?.key),
    role: str(raw?.role),
    requestFace: str(raw?.request_face),
    requirement: requirementLabel(raw?.requirement),
    state,
    tone: cellTone(state),
    outcome: str(raw?.outcome),
    reason: str(raw?.reason),
    policySource: str(raw?.policy_source),
    policyId: orNull(raw?.policy_id),
    policyRevision: num(raw?.policy_revision),
    accountId: orNull(raw?.account_id),
    providerBinding: orNull(raw?.provider_binding),
    effectiveModel: orNull(raw?.effective_model),
    // The pinned trace, carried WITH the cell: selecting one must never
    // re-resolve against a newer revision than the grid was drawn from.
    explanation: raw?.explanation && typeof raw.explanation === 'object' ? raw.explanation : null,
  }
}

/** @param {object} raw @returns {typeof EMPTY_EFFECTIVE_MATRIX_VM} */
export function toEffectiveMatrix(raw) {
  if (!raw || typeof raw !== 'object') return EMPTY_EFFECTIVE_MATRIX_VM
  return {
    loaded: true,
    repo: str(raw.repo),
    policyRevision: num(raw.policy_revision),
    snapshotHash: str(raw.snapshot_hash),
    snapshotState: str(raw.snapshot_state) || 'absent',
    cells: list(raw.cells).map(toCell),
  }
}

function toAuditRecord(raw) {
  const payload = raw?.payload || {}
  const diff = payload.diff || {}
  return {
    seq: num(raw?.seq),
    recordedAt: str(raw?.recorded_at),
    kind: str(payload.kind),
    outcome: str(payload.outcome),
    actor: str(payload.actor),
    recovered: payload.recovered === true,
    priorRevision: num(payload.prior_revision),
    newRevision: num(payload.new_revision),
    targetRevision: payload.target_revision == null ? null : num(payload.target_revision),
    added: list(diff.added).map(str),
    removed: list(diff.removed).map(str),
    changed: list(diff.changed).map(str),
  }
}

/** @param {object} raw @returns {typeof EMPTY_POLICY_AUDIT_VM} */
export function toPolicyAudit(raw) {
  if (!raw || typeof raw !== 'object') return EMPTY_POLICY_AUDIT_VM
  const records = list(raw.records).map(toAuditRecord)
  return {
    loaded: true,
    records,
    // Three states, not two: a payload that did not carry the field has not
    // told us anything, and `true` would be a verification claim we invented.
    verified: raw.verified == null ? null : raw.verified !== false,
    brokenAtSeq: raw.broken_at_seq == null ? null : num(raw.broken_at_seq),
    truncated: raw.truncated === true,
    // Revision 0 is a real target — the state before any policy was written —
    // so it is offered alongside every committed revision. Deduped and sorted:
    // two records can only claim one `new_revision` after an out-of-band
    // snapshot repair, and a duplicate would render as a duplicate control.
    rollbackTargets: [
      ...new Set([
        0,
        ...records
          .filter(record => record.outcome === 'committed')
          .map(record => record.newRevision),
      ]),
    ].sort((left, right) => left - right),
  }
}

export const REQUIREMENT_CHOICES = Object.freeze([
  'capability:balanced',
  'capability:high-reasoning',
  'literal_family:claude-opus',
  'literal_family:claude-sonnet',
])

export const PROVIDER_LOCK_CHOICES = Object.freeze(['', 'anthropic', 'zai-harness'])

export const WORKER_ROLE_CHOICES = Object.freeze([
  'explorer',
  'planner',
  'architect',
  'implementer',
  'debugger',
  'test_adequacy',
  'reviewer',
])

export const EMPTY_POLICY_DRAFT = Object.freeze({
  id: '',
  enabled: true,
  priority: 0,
  roles: EMPTY_LIST,
  providerLock: '',
  requirement: 'capability:balanced',
  effectiveModel: '',
  onUnavailable: 'hold',
})

/** Split a `kind:value` selector back into the API's `{kind, value}` pair. */
export function parseRequirement(selector) {
  const [kind, ...rest] = String(selector || '').split(':')
  return { kind, value: rest.join(':') }
}

/**
 * Turn an editor draft into the policy body the API accepts.
 *
 * The repository is supplied by the CALLER from the workspace it loaded, never
 * typed: this editor writes rules scoped to exactly one repository, and a form
 * field for the repo id would be a field for escaping that scope.
 */
export function draftToPolicy(draft, repo) {
  const model = String(draft?.effectiveModel || '').trim()
  const lock = String(draft?.providerLock || '')
  return {
    id: String(draft?.id || '').trim(),
    enabled: draft?.enabled !== false,
    priority: num(draft?.priority),
    system_safety: false,
    match: { repo_ids: [repo], roles: list(draft?.roles).map(str) },
    action: {
      provider_lock: lock || null,
      requirement_map: model
        ? [
            {
              requirement: parseRequirement(draft?.requirement),
              effective_model: model,
            },
          ]
        : [],
      on_unavailable: String(draft?.onUnavailable || 'hold'),
    },
  }
}

/** Load an existing policy row back into the editor. */
export function policyToDraft(row) {
  const mapping = list(row?.requirementMap)[0] || {}
  return {
    id: str(row?.id),
    enabled: row?.enabled !== false,
    priority: num(row?.priority),
    roles: list(row?.roles).map(str),
    providerLock: str(row?.providerLock),
    requirement: str(mapping.requirement) || 'capability:balanced',
    effectiveModel: str(mapping.effectiveModel),
    onUnavailable: str(row?.onUnavailable) || 'hold',
  }
}

export const EMPTY_POLICY_PREVIEW_VM = Object.freeze({
  loaded: false,
  writable: false,
  stale: false,
  rejection: null,
  expectedRevision: 0,
  nextRevision: 0,
  issues: EMPTY_LIST,
  added: EMPTY_LIST,
  removed: EMPTY_LIST,
  changed: EMPTY_LIST,
  movedCells: EMPTY_LIST,
})

/** @param {object} raw @returns {typeof EMPTY_POLICY_PREVIEW_VM} */
export function toPolicyPreview(raw) {
  if (!raw || typeof raw !== 'object') return EMPTY_POLICY_PREVIEW_VM
  const diff = raw.diff || {}
  return {
    loaded: true,
    writable: raw.writable === true,
    stale: raw.stale === true,
    rejection: orNull(raw.rejection),
    expectedRevision: num(raw.expected_revision),
    nextRevision: num(raw.next_revision),
    issues: list(raw.issues).map(toIssue),
    added: list(diff.added).map(str),
    removed: list(diff.removed).map(str),
    changed: list(diff.changed).map(str),
    movedCells: list(raw.cells)
      .filter(entry => entry?.changed === true)
      .map(entry => ({
        key: str(entry?.key),
        changedFields: list(entry?.changed_fields).map(str),
        before: entry?.before ? toCell(entry.before) : null,
        after: entry?.after ? toCell(entry.after) : null,
      })),
  }
}
