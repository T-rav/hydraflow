import React, { useState } from 'react'
import { theme } from '../../theme'
import { DomainView } from './DomainView'
import { TermDetailPanel } from './TermDetailPanel'
import { ArticlesView } from './ArticlesView'
import { MaintenanceView } from './MaintenanceView'

const SUBTABS = [
  { id: 'domain', label: 'Domain' },
  { id: 'articles', label: 'Articles' },
  { id: 'maintenance', label: 'Maintenance' },
]

export function AtlasExplorer() {
  const [activeSubtab, setActiveSubtab] = useState('domain')
  const [selectedNodeId, setSelectedNodeId] = useState(null)

  const styles = {
    root: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: theme.bg,
      color: theme.text,
      minHeight: 0,
    },
    tabBar: {
      display: 'flex',
      gap: 4,
      padding: '8px 16px',
      borderBottom: `1px solid ${theme.border}`,
      background: theme.surface,
    },
    tab: (isActive) => ({
      padding: '4px 12px',
      borderRadius: 3,
      border: 'none',
      cursor: 'pointer',
      background: isActive ? theme.surfaceInset : 'transparent',
      color: isActive ? theme.textBright : theme.textMuted,
      fontSize: 13,
    }),
    content: {
      flex: 1,
      overflow: 'auto',
      minHeight: 0,
      display: 'flex',
    },
    domainPane: {
      flex: 1,
      minWidth: 0,
      display: 'flex',
    },
    detailPane: {
      width: '38%',
      minWidth: 280,
      borderLeft: `1px solid ${theme.border}`,
      overflowY: 'auto',
    },
  }

  return (
    <div style={styles.root}>
      <div style={styles.tabBar}>
        {SUBTABS.map((t) => (
          <button
            key={t.id}
            type="button"
            style={styles.tab(activeSubtab === t.id)}
            onClick={() => setActiveSubtab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div style={styles.content}>
        {activeSubtab === 'domain' && (
          <>
            <div style={styles.domainPane}>
              <DomainView
                selectedNodeId={selectedNodeId}
                onSelectNode={setSelectedNodeId}
              />
            </div>
            <div style={styles.detailPane}>
              <TermDetailPanel selectedNodeId={selectedNodeId} />
            </div>
          </>
        )}
        {activeSubtab === 'articles' && <ArticlesView />}
        {activeSubtab === 'maintenance' && <MaintenanceView />}
      </div>
    </div>
  )
}

export default AtlasExplorer
