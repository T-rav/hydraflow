import React, { useState, useEffect, useRef } from 'react'
import { theme } from '../theme'

export function TranscriptPreview({ transcript, maxCollapsedLines = 3, maxHeight = 375 /* ~25 lines × (fontSize 10 × lineHeight 1.5 = 15px) */, inline = false }) {
  const [expanded, setExpanded] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [expanded, transcript])

  if (!transcript || transcript.length === 0) return null

  const visibleLines = expanded
    ? transcript
    : transcript.slice(-maxCollapsedLines)

  const linesStyle = expanded ? { ...styles.lines, maxHeight, overflowY: 'auto' } : styles.lines

  return (
    <div style={inline ? styles.containerInline : styles.container} data-testid={inline ? 'transcript-preview-inline' : 'transcript-preview'}>
      <div
        ref={scrollRef}
        style={linesStyle}
      >
        {visibleLines.map((line, i) => (
          <div key={transcript.length - visibleLines.length + i} style={styles.line}>
            {line}
          </div>
        ))}
      </div>
      {(expanded || transcript.length > maxCollapsedLines) && (
        <div
          style={styles.toggle}
          onClick={() => setExpanded(v => !v)}
          data-testid="transcript-toggle"
        >
          {expanded ? 'Collapse' : `Show all (${transcript.length} lines)`}
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    borderTop: `1px solid ${theme.border}`,
    marginTop: 4,
    paddingTop: 4,
  },
  containerInline: {
    paddingTop: 0,
  },
  lines: {
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
  },
  line: {
    padding: '1px 0',
  },
  toggle: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
    paddingTop: 4,
  },
}
