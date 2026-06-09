import { describe, it, expect } from 'vitest'
import { splitNodeId } from '../atlasNodeId'

describe('splitNodeId', () => {
  it('splits a namespaced id into repo + bare id', () => {
    expect(splitNodeId('org-a/01TERM000')).toEqual({ repo: 'org-a', bareId: '01TERM000' })
    expect(splitNodeId('org-b/adr-59')).toEqual({ repo: 'org-b', bareId: 'adr-59' })
  })

  it('returns a null repo for un-prefixed (single-repo) ids', () => {
    expect(splitNodeId('01TERM000')).toEqual({ repo: null, bareId: '01TERM000' })
    expect(splitNodeId('adr-59')).toEqual({ repo: null, bareId: 'adr-59' })
  })

  it('only splits on the first slash and ignores a leading slash', () => {
    expect(splitNodeId('org-a/entry-acme-widgets-7')).toEqual({
      repo: 'org-a',
      bareId: 'entry-acme-widgets-7',
    })
    expect(splitNodeId('/x')).toEqual({ repo: null, bareId: '/x' })
  })

  it('handles empty / non-string input', () => {
    expect(splitNodeId('')).toEqual({ repo: null, bareId: '' })
    expect(splitNodeId(null)).toEqual({ repo: null, bareId: null })
  })
})
