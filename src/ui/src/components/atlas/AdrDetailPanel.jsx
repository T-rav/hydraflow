import React, { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { theme } from '../../theme'
import { useHydraFlow } from '../../context/HydraFlowContext'
import { splitNodeId } from './atlasNodeId'

export function AdrDetailPanel({ selectedNodeId }) {
  const { fetchWithRepo } = useHydraFlow()
  const [adr, setAdr] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!selectedNodeId) {
      setAdr(null)
      setError(null)
      return
    }
    // The ADR node id is "adr-<n>", namespaced under __all__ ("${slug}/adr-<n>").
    const { repo, bareId } = splitNodeId(selectedNodeId)
    const m = /^adr-(\d+)$/.exec(bareId)
    if (!m) {
      setAdr(null)
      setError(new Error('not an adr id'))
      return
    }
    const number = m[1]
    let cancelled = false
    const url = `/api/atlas/adrs/${encodeURIComponent(number)}`
    const req = repo
      ? fetch(`${url}?repo=${encodeURIComponent(repo)}`)
      : fetchWithRepo(url)
    req
      .then((r) => {
        if (!r.ok) throw new Error(`status ${r.status}`)
        return r.json()
      })
      .then((data) => {
        if (cancelled) return
        setAdr(data)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err)
        setAdr(null)
      })
    return () => {
      cancelled = true
    }
  }, [selectedNodeId, fetchWithRepo])

  const styles = {
    root: {
      padding: '14px 16px',
      fontSize: 12,
      lineHeight: 1.5,
      color: theme.text,
    },
    hint: { color: theme.textMuted, fontSize: 13 },
    label: {
      color: theme.textMuted,
      fontSize: 10,
      letterSpacing: 0.5,
      textTransform: 'uppercase',
    },
    name: { color: theme.textBright, fontSize: 15, marginTop: 4 },
    rule: {
      border: 'none',
      borderTop: `1px solid ${theme.border}`,
      margin: '12px 0',
    },
    body: {
      fontSize: 12,
      lineHeight: 1.55,
      color: theme.text,
      background: theme.surfaceInset,
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: 12,
    },
  }

  if (error) {
    return (
      <div style={styles.root}>
        <div style={styles.hint}>Unable to load ADR.</div>
      </div>
    )
  }
  if (!adr) {
    return (
      <div style={styles.root}>
        <div style={styles.hint}>Loading…</div>
      </div>
    )
  }

  return (
    <div style={styles.root}>
      <div style={styles.label}>Selected ADR</div>
      <div style={styles.name}>
        ADR-{String(adr.number).padStart(4, '0')}: {adr.title}
      </div>
      <div style={{ color: theme.textMuted }}>
        {adr.status} · {adr.date}
      </div>
      <hr style={styles.rule} />
      <div style={styles.body}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{adr.body || ''}</ReactMarkdown>
      </div>
    </div>
  )
}

export default AdrDetailPanel
