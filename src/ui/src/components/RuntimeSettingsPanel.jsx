import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { REPO_ALL } from '../constants'

// Schema-derived runtime settings screen. Every field comes from
// GET /api/control/settings-schema (backed by settings_registry + the Pydantic
// model) — type, description, bounds, choices, current value, and the
// live/restart flag. Adding a field to the backend registry makes it appear
// here automatically; there is no per-field UI code.

export function humanize(name) {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function RuntimeSettingsPanel() {
  const { selectedRepoSlug, fetchWithRepo } = useHydraFlow()
  const isAggregate = selectedRepoSlug === REPO_ALL
  const [rows, setRows] = useState(null)
  const [search, setSearch] = useState('')
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

  const groups = useMemo(() => {
    if (!rows) return []
    const q = search.trim().toLowerCase()
    const filtered = q
      ? rows.filter(
          (r) =>
            r.name.toLowerCase().includes(q) ||
            (r.description || '').toLowerCase().includes(q) ||
            r.group.toLowerCase().includes(q),
        )
      : rows
    const byGroup = {}
    for (const r of filtered) (byGroup[r.group] ||= []).push(r)
    return Object.entries(byGroup)
  }, [rows, search])

  if (error) return <div style={styles.message} data-testid="settings-error">{error}</div>
  if (!rows) return <div style={styles.message} data-testid="settings-loading">Loading settings…</div>

  return (
    <div style={styles.container} data-testid="runtime-settings-panel">
      <input
        type="text"
        placeholder="Search settings…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={styles.search}
        data-testid="settings-search"
      />
      {isAggregate && (
        <div style={styles.aggregateNote} data-testid="settings-aggregate-note">
          Select a specific repo to edit settings.
        </div>
      )}
      {groups.map(([group, groupRows]) => (
        <section key={group} style={styles.group}>
          <h3 style={styles.groupTitle}>{group}</h3>
          {groupRows.map((row) => (
            <SettingRow
              key={row.name}
              row={row}
              value={valueOf(row)}
              dirty={row.name in drafts}
              savedState={saved[row.name]}
              disabled={isAggregate}
              onChange={(v) => setDraft(row.name, v)}
              onSave={() => save(row)}
            />
          ))}
        </section>
      ))}
      {groups.length === 0 && (
        <div style={styles.message} data-testid="settings-empty">
          No settings match “{search}”.
        </div>
      )}
    </div>
  )
}

function SettingRow({ row, value, dirty, savedState, disabled, onChange, onSave }) {
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
    <div style={styles.row} data-testid={`setting-${row.name}`}>
      <div style={styles.rowLabel}>
        <div style={styles.rowName}>
          {humanize(row.name)}
          <span
            style={row.live ? styles.badgeLive : styles.badgeRestart}
            data-testid={`badge-${row.name}`}
            title={row.live ? 'Applies immediately' : 'Saved now; takes effect after restart'}
          >
            {row.live ? '⟳ live' : '⚠ restart'}
          </span>
        </div>
        {row.description && <div style={styles.rowDesc}>{row.description}</div>}
      </div>
      <div style={styles.rowControl}>
        <SettingInput row={row} value={value} disabled={disabled} onChange={handle} />
        {fieldError && <span style={styles.fieldError}>{fieldError}</span>}
        {dirty && !fieldError && (
          <button
            onClick={onSave}
            disabled={disabled}
            style={styles.saveBtn}
            data-testid={`save-${row.name}`}
          >
            Save
          </button>
        )}
        {savedState === 'ok' && <span style={styles.savedOk} data-testid={`saved-${row.name}`}>saved</span>}
        {savedState === 'restart' && (
          <span style={styles.savedRestart} data-testid={`saved-${row.name}`}>
            saved — restart to apply
          </span>
        )}
        {savedState && savedState !== 'ok' && savedState !== 'restart' && (
          <span style={styles.fieldError} data-testid={`saved-${row.name}`}>{savedState}</span>
        )}
      </div>
    </div>
  )
}

function SettingInput({ row, value, disabled, onChange }) {
  if (row.type === 'bool') {
    return (
      <input
        type="checkbox"
        checked={!!value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={`input-${row.name}`}
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
        data-testid={`input-${row.name}`}
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
      data-testid={`input-${row.name}`}
    />
  )
}

const badgeBase = {
  marginLeft: 8,
  fontSize: 10,
  padding: '1px 6px',
  borderRadius: 4,
  fontWeight: 600,
  verticalAlign: 'middle',
}

const styles = {
  container: { display: 'flex', flexDirection: 'column', gap: 16, padding: 4 },
  message: { color: theme.textMuted, padding: 16 },
  search: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    color: theme.text,
    padding: '8px 12px',
    fontSize: 13,
    width: '100%',
    maxWidth: 360,
  },
  aggregateNote: { color: theme.yellow, fontSize: 12 },
  group: {
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
  },
  groupTitle: {
    color: theme.textBright,
    fontSize: 13,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    margin: '0 0 8px 0',
  },
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 16,
    padding: '8px 0',
    borderTop: `1px solid ${theme.border}`,
  },
  rowLabel: { flex: 1, minWidth: 0 },
  rowName: { color: theme.text, fontSize: 13, fontWeight: 500 },
  rowDesc: { color: theme.textMuted, fontSize: 11, marginTop: 2 },
  rowControl: { display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 },
  input: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 4,
    color: theme.text,
    padding: '4px 8px',
    fontSize: 13,
    minWidth: 90,
  },
  saveBtn: {
    background: theme.btnGreen,
    border: 'none',
    borderRadius: 4,
    color: theme.white,
    padding: '4px 10px',
    fontSize: 12,
    cursor: 'pointer',
  },
  savedOk: { color: theme.green, fontSize: 11 },
  savedRestart: { color: theme.orange, fontSize: 11 },
  fieldError: { color: theme.red, fontSize: 11 },
  badgeLive: { ...badgeBase, background: theme.greenSubtle, color: theme.green },
  badgeRestart: { ...badgeBase, background: theme.orangeSubtle, color: theme.orange },
}
