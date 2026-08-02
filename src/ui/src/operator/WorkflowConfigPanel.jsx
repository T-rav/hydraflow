/**
 * WorkflowConfigPanel — the operator console's larger, stage-grouped
 * workflow-configuration surface (#10786).
 *
 * Complements the compact SettingsSummary strip and the classic flat
 * RuntimeSettingsPanel: it reads the SAME schema (`GET /api/control/settings-
 * schema`) and writes through the SAME mutation path (`PATCH /api/control/
 * config`, one field at a time with `persist: true`), but lays the fields out
 * grouped by the server-derived `section` (see `settings_registry`) so an
 * operator sees the pipeline knobs organised by stage/concern rather than as
 * one long searchable list.
 *
 * Grouping is delegated to the pure `toWorkflowConfig` view-model (total by
 * construction — no field is ever dropped). This component owns only the
 * fetch + edit/save state and presentation.
 *
 * Styling: every colour / space value resolves from `useTokens()` — no inline
 * `style={{…}}` object literals and no colour literals, so it satisfies the
 * operator inline-style + colour ratchet and themes with the console.
 *
 * Repo scoping mirrors RuntimeSettingsPanel: config writes require a specific
 * repo, so in the aggregate (`__all__`) view the controls are disabled and a
 * note explains why.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useTokens, Card, Text, Button, Badge } from '../styles/primitives'
import { useHydraFlow } from '../context/HydraFlowContext'
import { REPO_ALL } from '../constants'
import { toWorkflowConfig } from './model/workflowConfig'

/** snake/space/`&` → a stable, testid-safe slug ("Safety & Reliability" → "safety-reliability"). */
function slug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')
}

/** Humanize a snake_case field name for a label ("max_workers" → "Max Workers"). */
function humanize(name) {
  return String(name).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function makeStyles(t) {
  return {
    container: { display: 'flex', flexDirection: 'column', gap: t.space.md, padding: t.space.sm },
    section: { display: 'flex', flexDirection: 'column', gap: t.space.xs, padding: t.space.md },
    sectionHead: { marginBottom: t.space.xs },
    row: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      gap: t.space.md,
      padding: `${t.space.sm}px 0`,
      borderTop: `1px solid ${t.color.border}`,
    },
    label: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: t.space.xxs },
    name: { display: 'flex', alignItems: 'center', gap: t.space.sm, flexWrap: 'wrap' },
    control: { display: 'flex', alignItems: 'center', gap: t.space.sm, flexShrink: 0 },
    input: {
      background: t.color.surfaceInset,
      border: `1px solid ${t.color.border}`,
      borderRadius: t.radius.sm,
      color: t.color.text,
      padding: `${t.space.xs}px ${t.space.sm}px`,
      fontSize: t.type.size.sm,
      fontFamily: t.type.family.mono,
      minWidth: 96,
    },
    note: { padding: `${t.space.xs}px ${t.space.sm}px` },
    message: { padding: t.space.lg },
  }
}

/** The bool/enum/number/text control for a field — identical semantics to the
 * classic RuntimeSettingsPanel so the two never drift. */
function FieldInput({ row, value, disabled, onChange, styles }) {
  if (row.type === 'bool') {
    return (
      <input
        type="checkbox"
        checked={!!value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={`wf-input-${row.name}`}
      />
    )
  }
  if (row.type === 'enum') {
    return (
      <select
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        style={styles.input}
        data-testid={`wf-input-${row.name}`}
      >
        {(row.choices || []).map((c) => (
          <option key={String(c)} value={c}>{String(c)}</option>
        ))}
      </select>
    )
  }
  const inputType = row.type === 'int' || row.type === 'float' ? 'number' : 'text'
  return (
    <input
      type={inputType}
      value={value ?? ''}
      disabled={disabled}
      min={row.min ?? undefined}
      max={row.max ?? undefined}
      onChange={(e) => onChange(e.target.value)}
      style={styles.input}
      data-testid={`wf-input-${row.name}`}
    />
  )
}

function FieldRow({ row, value, dirty, savedState, disabled, onChange, onSave, styles }) {
  const [fieldError, setFieldError] = useState(null)

  const handle = useCallback((raw) => {
    let v = raw
    if (row.type === 'int') v = raw === '' ? '' : parseInt(raw, 10)
    else if (row.type === 'float') v = raw === '' ? '' : parseFloat(raw)
    if ((row.type === 'int' || row.type === 'float') && v !== '') {
      if (row.min != null && v < row.min) setFieldError(`min ${row.min}`)
      else if (row.max != null && v > row.max) setFieldError(`max ${row.max}`)
      else setFieldError(null)
    } else {
      setFieldError(null)
    }
    onChange(v)
  }, [row, onChange])

  return (
    <div style={styles.row} data-testid={`wf-field-${row.name}`}>
      <div style={styles.label}>
        <div style={styles.name}>
          <Text size="sm" weight="medium">{humanize(row.name)}</Text>
          <Badge tone={row.live ? 'success' : 'warning'} data-testid={`wf-badge-${row.name}`}>
            {row.live ? 'live' : 'restart'}
          </Badge>
        </div>
        {row.description && <Text size="xs" tone="muted">{row.description}</Text>}
      </div>
      <div style={styles.control}>
        <FieldInput row={row} value={value} disabled={disabled} onChange={handle} styles={styles} />
        {fieldError && (
          <Text size="xs" tone="danger" data-testid={`wf-fielderror-${row.name}`}>{fieldError}</Text>
        )}
        {dirty && !fieldError && (
          <Button
            variant="success"
            size="sm"
            disabled={disabled}
            onClick={onSave}
            data-testid={`wf-save-${row.name}`}
          >
            Save
          </Button>
        )}
        {savedState === 'ok' && (
          <Text size="xs" tone="success" data-testid={`wf-saved-${row.name}`}>saved</Text>
        )}
        {savedState === 'restart' && (
          <Text size="xs" tone="warning" data-testid={`wf-saved-${row.name}`}>
            saved — restart to apply
          </Text>
        )}
        {savedState && savedState !== 'ok' && savedState !== 'restart' && (
          <Text size="xs" tone="danger" data-testid={`wf-saved-${row.name}`}>{savedState}</Text>
        )}
      </div>
    </div>
  )
}

export function WorkflowConfigPanel() {
  const t = useTokens()
  const styles = makeStyles(t)
  const { selectedRepoSlug, fetchWithRepo } = useHydraFlow()
  const isAggregate = selectedRepoSlug === REPO_ALL

  const [rows, setRows] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [saved, setSaved] = useState({})
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const resp = await fetchWithRepo('/api/control/settings-schema')
      if (!resp.ok) { setError('Failed to load settings'); return }
      const data = await resp.json()
      setRows(data.settings || [])
    } catch {
      setError('Failed to load settings')
    }
  }, [fetchWithRepo])

  useEffect(() => { load() }, [load])

  const valueOf = useCallback(
    (row) => (row.name in drafts ? drafts[row.name] : row.value),
    [drafts],
  )

  const setDraft = useCallback((name, value) => {
    setDrafts((d) => ({ ...d, [name]: value }))
  }, [])

  const save = useCallback(async (row) => {
    if (isAggregate) return
    const value = row.name in drafts ? drafts[row.name] : row.value
    try {
      const resp = await fetchWithRepo('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [row.name]: value, persist: true }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        setSaved((s) => ({ ...s, [row.name]: body.message || 'Save failed' }))
        return
      }
      setSaved((s) => ({ ...s, [row.name]: row.live ? 'ok' : 'restart' }))
      setDrafts((d) => { const n = { ...d }; delete n[row.name]; return n })
      setRows((rs) => rs.map((r) => (r.name === row.name ? { ...r, value } : r)))
    } catch {
      setSaved((s) => ({ ...s, [row.name]: 'Save failed' }))
    }
  }, [drafts, fetchWithRepo, isAggregate])

  const sections = useMemo(() => toWorkflowConfig(rows), [rows])

  if (error) {
    return <Text as="div" tone="danger" style={styles.message} data-testid="workflow-config-error">{error}</Text>
  }
  if (!rows) {
    return <Text as="div" tone="muted" style={styles.message} data-testid="workflow-config-loading">Loading workflow config…</Text>
  }

  return (
    <div style={styles.container} data-testid="workflow-config-panel">
      {isAggregate && (
        <Text as="div" tone="warning" style={styles.note} data-testid="workflow-aggregate-note">
          Select a specific repo to edit workflow config.
        </Text>
      )}
      {sections.map(({ section, rows: sectionRows }) => (
        <Card as="section" key={section} style={styles.section} data-testid={`wf-section-${slug(section)}`}>
          <div style={styles.sectionHead}>
            <Text size="xs" weight="semibold" tone="muted" uppercase>{section}</Text>
          </div>
          {sectionRows.map((row) => (
            <FieldRow
              key={row.name}
              row={row}
              value={valueOf(row)}
              dirty={row.name in drafts}
              savedState={saved[row.name]}
              disabled={isAggregate}
              onChange={(v) => setDraft(row.name, v)}
              onSave={() => save(row)}
              styles={styles}
            />
          ))}
        </Card>
      ))}
    </div>
  )
}

export default WorkflowConfigPanel
