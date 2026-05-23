import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { theme } from '../theme'

const STEPS = ['Describe', 'Spec', 'Plan 01', 'Materialize locally']

const DEFAULT_FORM = {
  name: 'new-project',
  description: 'A HydraFlow-format project bootstrapped from the dashboard.',
  owner: 'T-rav',
  visibility: 'private',
  tech_stack: 'python',
  safety_guards: 'deterministic tests, quality gates, ADR review',
  coverage_floor: 80,
  package_name: '',
  label_prefix: 'hydraflow',
  main_branch: 'main',
  staging_branch: 'staging',
  output_dir: '',
}

function splitList(value) {
  return String(value || '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean)
}

function buildSpec(form) {
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    owner: form.owner.trim(),
    visibility: form.visibility,
    tech_stack: splitList(form.tech_stack),
    safety_guards: splitList(form.safety_guards),
    coverage_floor: Number(form.coverage_floor),
    package_name: form.package_name.trim() || null,
    label_prefix: form.label_prefix.trim(),
    main_branch: form.main_branch.trim(),
    staging_branch: form.staging_branch.trim(),
  }
}

function formFromSpec(spec, previous = DEFAULT_FORM) {
  if (!spec) return previous
  return {
    ...previous,
    name: spec.name || previous.name,
    description: spec.description || previous.description,
    owner: spec.owner || previous.owner,
    visibility: spec.visibility || previous.visibility,
    tech_stack: Array.isArray(spec.tech_stack) ? spec.tech_stack.join(', ') : previous.tech_stack,
    safety_guards: Array.isArray(spec.safety_guards) ? spec.safety_guards.join(', ') : previous.safety_guards,
    coverage_floor: spec.coverage_floor ?? previous.coverage_floor,
    package_name: spec.package_name || previous.package_name,
    label_prefix: spec.label_prefix || previous.label_prefix,
    main_branch: spec.main_branch || previous.main_branch,
    staging_branch: spec.staging_branch || previous.staging_branch,
  }
}

function buildPlanItems(spec) {
  return [
    `Create ${spec.name} with HydraFlow invariant-kernel files`,
    `Configure ${spec.main_branch} and ${spec.staging_branch} branch expectations`,
    `Set ${spec.coverage_floor}% coverage floor in generated quality tooling`,
    `Add ${spec.label_prefix}-scoped issue and PR templates`,
    'Run local smoke tests before GitHub provisioning',
    'Keep wizard-draft specs marked for refinement',
  ]
}

export function BootstrapWizard({ isOpen, onClose }) {
  const {
    createOnboardingDraft,
    chatOnboardingDraft,
    draftOnboardingSpec,
    saveOnboardingSpecDraft,
    draftOnboardingPlan,
    materializeOnboardingDraft,
    selectRepo,
  } = useHydraFlow()
  const [step, setStep] = useState(0)
  const [form, setForm] = useState(DEFAULT_FORM)
  const [draft, setDraft] = useState(null)
  const [chatInput, setChatInput] = useState('')
  const [specDraft, setSpecDraft] = useState('')
  const [planDraft, setPlanDraft] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [activityOpen, setActivityOpen] = useState(false)

  useEffect(() => {
    if (!isOpen) {
      setStep(0)
      setForm(DEFAULT_FORM)
      setDraft(null)
      setChatInput('')
      setSpecDraft('')
      setPlanDraft([])
      setSubmitting(false)
      setError('')
      setActivityOpen(false)
      return
    }
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  const spec = useMemo(() => buildSpec(form), [form])
  const planItems = useMemo(() => buildPlanItems(spec), [spec])

  const updateField = (field) => (event) => {
    setForm(prev => ({ ...prev, [field]: event.target.value }))
  }

  const ensureDraft = useCallback(async () => {
    if (draft) return draft
    setSubmitting(true)
    setError('')
    const result = await createOnboardingDraft(spec)
    setSubmitting(false)
    if (!result?.ok) {
      setError(result?.error || 'Draft failed')
      return null
    }
    setDraft(result.draft)
    setForm(prev => formFromSpec(result.draft?.spec, prev))
    setSpecDraft(result.draft?.spec_draft || '')
    setPlanDraft(result.draft?.plan_draft || [])
    return result.draft
  }, [createOnboardingDraft, draft, spec])

  const handleChatSubmit = useCallback(async () => {
    const message = chatInput.trim()
    if (!message || submitting) return
    const activeDraft = await ensureDraft()
    if (!activeDraft) return
    setSubmitting(true)
    setError('')
    const result = await chatOnboardingDraft?.(activeDraft.id, message)
    setSubmitting(false)
    if (!result?.ok) {
      setDraft(result?.draft || activeDraft)
      setError(result?.error || 'Design chat failed')
      return
    }
    setChatInput('')
    setDraft(result.draft)
    setForm(prev => formFromSpec(result.draft?.spec, prev))
    setSpecDraft(result.draft?.spec_draft || '')
    setPlanDraft(result.draft?.plan_draft || [])
  }, [chatInput, chatOnboardingDraft, ensureDraft, submitting])

  const generateSpecDraft = useCallback(async (activeDraft) => {
    const result = await draftOnboardingSpec?.(activeDraft.id)
    if (!result?.ok) {
      setDraft(result?.draft || activeDraft)
      setError(result?.error || 'Spec draft failed')
      return null
    }
    setDraft(result.draft)
    setSpecDraft(result.spec_draft || result.draft?.spec_draft || '')
    return result.draft
  }, [draftOnboardingSpec])

  const generatePlanDraft = useCallback(async (activeDraft) => {
    const result = await draftOnboardingPlan?.(activeDraft.id)
    if (!result?.ok) {
      setDraft(result?.draft || activeDraft)
      setError(result?.error || 'Plan draft failed')
      return null
    }
    setDraft(result.draft)
    setPlanDraft(result.plan_draft || result.draft?.plan_draft || [])
    return result.draft
  }, [draftOnboardingPlan])

  const saveSpecDraft = useCallback(async (activeDraft) => {
    const content = (specDraft || '').trim()
    if (!content) return activeDraft
    const result = await saveOnboardingSpecDraft?.(activeDraft.id, content)
    if (!result?.ok) {
      setDraft(result?.draft || activeDraft)
      setError(result?.error || 'Spec save failed')
      return null
    }
    setDraft(result.draft)
    setSpecDraft(result.spec_draft || result.draft?.spec_draft || content)
    return result.draft
  }, [saveOnboardingSpecDraft, specDraft])

  const handleNext = useCallback(async () => {
    if (step === 0) {
      const created = await ensureDraft()
      if (!created) return
      setSubmitting(true)
      setError('')
      const updated = await generateSpecDraft(created)
      setSubmitting(false)
      if (!updated) return
    }
    if (step === 1) {
      const activeDraft = await ensureDraft()
      if (!activeDraft) return
      setSubmitting(true)
      setError('')
      const saved = await saveSpecDraft(activeDraft)
      if (!saved) {
        setSubmitting(false)
        return
      }
      const updated = await generatePlanDraft(saved)
      setSubmitting(false)
      if (!updated) return
    }
    setStep(prev => Math.min(prev + 1, STEPS.length - 1))
  }, [ensureDraft, generatePlanDraft, generateSpecDraft, saveSpecDraft, step])

  const handleMaterialize = useCallback(async () => {
    const activeDraft = await ensureDraft()
    if (!activeDraft || submitting) return
    setSubmitting(true)
    setError('')
    setActivityOpen(false)
    const result = await materializeOnboardingDraft(activeDraft.id, {
      output_dir: form.output_dir.trim() || null,
    })
    setSubmitting(false)
    if (!result?.ok) {
      setDraft(result?.draft || activeDraft)
      setError(result?.error || 'Materialize failed')
      setActivityOpen(true)
      return
    }
    const nextDraft = result.draft
    setDraft(nextDraft)
    selectRepo?.(nextDraft?.spec?.name)
    onClose?.()
  }, [ensureDraft, form.output_dir, materializeOnboardingDraft, onClose, selectRepo, submitting])

  if (!isOpen) return null

  const events = draft?.events || []

  return (
    <div style={styles.overlay} onClick={(event) => { if (event.target === event.currentTarget) onClose?.() }} data-testid="bootstrap-wizard-overlay">
      <div style={styles.shell} role="dialog" aria-modal="true" aria-label="New project wizard">
        <div style={styles.header}>
          <div>
            <div style={styles.title}>New Project</div>
            <div style={styles.subtitle}>HydraFlow-format repo bootstrap</div>
          </div>
          <button type="button" style={styles.closeBtn} onClick={onClose} aria-label="Close new project wizard">x</button>
        </div>

        <div style={styles.stepRail}>
          {STEPS.map((label, index) => (
            <button
              key={label}
              type="button"
              disabled={index > step + 1}
              onClick={() => setStep(index)}
              style={index === step ? styles.stepActive : styles.step}
            >
              <span style={styles.stepIndex}>{index + 1}</span>
              <span>{label}</span>
            </button>
          ))}
        </div>

        <div style={styles.body}>
          {step === 0 && (
            <div style={styles.describeLayout}>
              <div style={styles.chatColumn}>
                <div style={styles.chatLog} data-testid="design-chat-log">
                  {(draft?.chat_messages || []).length === 0 ? (
                    <div style={styles.muted}>Describe the repo, runtime, UI, safety constraints, and coverage target.</div>
                  ) : draft.chat_messages.map((message, index) => (
                    <div key={`${message.role}-${index}`} style={message.role === 'assistant' ? styles.assistantMessage : styles.userMessage}>
                      <span style={styles.messageRole}>{message.role}</span>
                      <span>{message.content}</span>
                    </div>
                  ))}
                </div>
                <textarea
                  style={styles.chatInput}
                  value={chatInput}
                  onChange={(event) => setChatInput(event.target.value)}
                  placeholder="Build finance-tool as a public FastAPI React app with branch protection and 92% coverage."
                  aria-label="Design chat message"
                />
                <button type="button" style={submitting ? styles.primaryDisabled : styles.primary} disabled={submitting || !chatInput.trim()} onClick={handleChatSubmit}>
                  Send
                </button>
              </div>
              <div style={styles.grid}>
                <label style={styles.field}>Repo name<input style={styles.input} value={form.name} onChange={updateField('name')} /></label>
                <label style={styles.field}>Owner<input style={styles.input} value={form.owner} onChange={updateField('owner')} /></label>
                <label style={styles.fieldWide}>Description<textarea style={styles.textarea} value={form.description} onChange={updateField('description')} /></label>
                <label style={styles.field}>Visibility<select style={styles.input} value={form.visibility} onChange={updateField('visibility')}><option value="private">Private</option><option value="public">Public</option></select></label>
                <label style={styles.field}>Coverage floor<input style={styles.input} type="number" min="0" max="100" value={form.coverage_floor} onChange={updateField('coverage_floor')} /></label>
                <label style={styles.fieldWide}>Tech stack<input style={styles.input} value={form.tech_stack} onChange={updateField('tech_stack')} /></label>
                <label style={styles.fieldWide}>Safety guards<input style={styles.input} value={form.safety_guards} onChange={updateField('safety_guards')} /></label>
              </div>
            </div>
          )}

          {step === 1 && (
            <div style={styles.specBox}>
              <textarea
                style={styles.specTextarea}
                value={specDraft || JSON.stringify(spec, null, 2)}
                onChange={(event) => setSpecDraft(event.target.value)}
                aria-label="Generated spec draft"
              />
            </div>
          )}

          {step === 2 && (
            <div style={styles.planList}>
              {(planDraft.length ? planDraft : planItems).map(item => (
                <label key={item} style={styles.planItem}>
                  <input type="checkbox" checked readOnly />
                  <span>{item}</span>
                </label>
              ))}
            </div>
          )}

          {step === 3 && (
            <div style={styles.materializePanel}>
              <label style={styles.fieldWide}>Output directory<input style={styles.input} value={form.output_dir} onChange={updateField('output_dir')} placeholder="Default workspace directory" /></label>
              <button type="button" style={submitting ? styles.primaryDisabled : styles.primary} disabled={submitting} onClick={handleMaterialize} data-testid="materialize-project">
                {submitting ? 'Materializing...' : 'Materialize locally'}
              </button>
              <button type="button" style={styles.activityToggle} onClick={() => setActivityOpen(prev => !prev)}>
                Activity log {activityOpen ? 'up' : 'down'}
              </button>
              {activityOpen && (
                <div style={styles.activityLog} data-testid="wizard-activity-log">
                  {events.length === 0 ? <div style={styles.muted}>No activity yet</div> : events.map((event, index) => (
                    <div key={`${event.message}-${index}`} style={event.level === 'error' ? styles.eventError : styles.event}>
                      {event.message}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.footer}>
          <button type="button" style={styles.secondary} onClick={onClose}>Cancel</button>
          <div style={styles.footerRight}>
            <button type="button" style={step === 0 ? styles.secondaryDisabled : styles.secondary} disabled={step === 0} onClick={() => setStep(prev => Math.max(prev - 1, 0))}>Back</button>
            {step < STEPS.length - 1 && (
              <button type="button" style={submitting ? styles.primaryDisabled : styles.primary} disabled={submitting} onClick={handleNext}>Next</button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.6)',
    zIndex: 1200,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
  },
  shell: {
    width: 'min(760px, 100%)',
    maxHeight: '92vh',
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    display: 'flex',
    flexDirection: 'column',
    boxShadow: '0 16px 40px rgba(0,0,0,0.45)',
  },
  header: { display: 'flex', justifyContent: 'space-between', gap: 16, padding: 16, borderBottom: `1px solid ${theme.border}` },
  title: { fontSize: 16, fontWeight: 700, color: theme.textBright },
  subtitle: { fontSize: 12, color: theme.textMuted, marginTop: 4 },
  closeBtn: { border: 'none', background: 'transparent', color: theme.textMuted, fontSize: 16, cursor: 'pointer' },
  stepRail: { display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', borderBottom: `1px solid ${theme.border}` },
  step: { border: 'none', background: theme.surface, color: theme.textMuted, padding: '10px 8px', fontSize: 11, fontWeight: 600, cursor: 'pointer' },
  stepActive: { border: 'none', background: theme.accentSubtle, color: theme.textBright, padding: '10px 8px', fontSize: 11, fontWeight: 700, cursor: 'pointer' },
  stepIndex: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 18, height: 18, borderRadius: '50%', border: `1px solid ${theme.border}`, marginRight: 6, fontSize: 10 },
  body: { padding: 16, overflowY: 'auto' },
  describeLayout: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 280px), 1fr))', gap: 14 },
  chatColumn: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 },
  chatLog: { background: theme.surfaceInset, border: `1px solid ${theme.border}`, borderRadius: 8, padding: 10, minHeight: 192, maxHeight: 260, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 },
  userMessage: { alignSelf: 'flex-end', maxWidth: '88%', background: theme.accentSubtle, color: theme.text, borderRadius: 8, padding: '8px 10px', fontSize: 12, lineHeight: 1.4 },
  assistantMessage: { alignSelf: 'flex-start', maxWidth: '88%', background: theme.surface, color: theme.text, border: `1px solid ${theme.border}`, borderRadius: 8, padding: '8px 10px', fontSize: 12, lineHeight: 1.4 },
  messageRole: { display: 'block', color: theme.textMuted, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', marginBottom: 3 },
  chatInput: { background: theme.surfaceInset, border: `1px solid ${theme.border}`, borderRadius: 6, color: theme.text, padding: '8px 10px', fontSize: 12, minHeight: 72, resize: 'vertical' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))', gap: 12 },
  field: { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 600, color: theme.textMuted },
  fieldWide: { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 600, color: theme.textMuted, gridColumn: '1 / -1' },
  input: { background: theme.surfaceInset, border: `1px solid ${theme.border}`, borderRadius: 6, color: theme.text, padding: '8px 10px', fontSize: 12 },
  textarea: { background: theme.surfaceInset, border: `1px solid ${theme.border}`, borderRadius: 6, color: theme.text, padding: '8px 10px', fontSize: 12, minHeight: 76, resize: 'vertical' },
  specBox: { background: theme.surfaceInset, border: `1px solid ${theme.border}`, borderRadius: 8, padding: 12 },
  specTextarea: { width: '100%', minHeight: 360, boxSizing: 'border-box', background: theme.surfaceInset, border: 'none', color: theme.codeText, fontSize: 12, lineHeight: 1.5, resize: 'vertical', outline: 'none', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace' },
  pre: { margin: 0, color: theme.codeText, fontSize: 12, overflowX: 'auto' },
  planList: { display: 'flex', flexDirection: 'column', gap: 10 },
  planItem: { display: 'flex', alignItems: 'center', gap: 8, color: theme.text, fontSize: 12 },
  materializePanel: { display: 'flex', flexDirection: 'column', gap: 12 },
  activityToggle: { alignSelf: 'flex-start', border: `1px solid ${theme.border}`, background: theme.surfaceInset, color: theme.text, borderRadius: 6, padding: '6px 10px', cursor: 'pointer', fontSize: 12 },
  activityLog: { background: theme.surfaceInset, border: `1px solid ${theme.border}`, borderRadius: 8, padding: 10, maxHeight: 160, overflowY: 'auto' },
  event: { color: theme.text, fontSize: 12, padding: '3px 0' },
  eventError: { color: theme.red, fontSize: 12, padding: '3px 0' },
  muted: { color: theme.textMuted, fontSize: 12 },
  error: { margin: '0 16px 12px', color: theme.red, background: theme.redSubtle, border: `1px solid ${theme.red}`, borderRadius: 6, padding: '8px 10px', fontSize: 12 },
  footer: { display: 'flex', justifyContent: 'space-between', gap: 12, padding: 16, borderTop: `1px solid ${theme.border}` },
  footerRight: { display: 'flex', gap: 8 },
  primary: { border: 'none', borderRadius: 6, background: theme.accent, color: theme.white, padding: '8px 14px', fontSize: 12, fontWeight: 700, cursor: 'pointer' },
  primaryDisabled: { border: 'none', borderRadius: 6, background: theme.textMuted, color: theme.white, padding: '8px 14px', fontSize: 12, fontWeight: 700, cursor: 'not-allowed', opacity: 0.7 },
  secondary: { border: `1px solid ${theme.border}`, borderRadius: 6, background: theme.surfaceInset, color: theme.text, padding: '8px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer' },
  secondaryDisabled: { border: `1px solid ${theme.border}`, borderRadius: 6, background: theme.surfaceInset, color: theme.textMuted, padding: '8px 14px', fontSize: 12, fontWeight: 600, cursor: 'not-allowed', opacity: 0.5 },
}
