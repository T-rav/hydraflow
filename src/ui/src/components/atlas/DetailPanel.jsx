import React from 'react'
import { theme } from '../../theme'
import { TermDetailPanel } from './TermDetailPanel'
import { AdrDetailPanel } from './AdrDetailPanel'
import { splitNodeId } from './atlasNodeId'

/**
 * Routes the selected-node detail render to the right panel by id shape:
 *   "adr-<n>" → AdrDetailPanel
 *   anything else → TermDetailPanel
 *
 * Lives at this level so DomainView and GraphView can share selection state
 * without each owning its own panel routing.
 */
export function DetailPanel({ selectedNodeId }) {
  if (!selectedNodeId) {
    return (
      <div
        style={{
          padding: '14px 16px',
          fontSize: 13,
          color: theme.textMuted,
        }}
      >
        Pick a node in the graph to see details.
      </div>
    )
  }
  // Under repo=__all__ the id is namespaced (`${slug}/adr-59`); route on the
  // bare id so the adr-vs-term shape test still matches.
  const { bareId } = splitNodeId(selectedNodeId)
  if (/^adr-\d+$/.test(bareId)) {
    return <AdrDetailPanel selectedNodeId={selectedNodeId} />
  }
  return <TermDetailPanel selectedNodeId={selectedNodeId} />
}

export default DetailPanel
