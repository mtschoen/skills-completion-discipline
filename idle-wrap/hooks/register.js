// idle-wrap: when an interactive session has sat idle long enough that idle
// compaction is about to summarize it, run the wrap in the same session
// instead, while the whole conversation is still in context and on the warm
// prompt cache. Compaction of an idle session is vetoed so the wrap is what
// the owner comes back to.

const TICK_MS = 60000
const DEFAULT_IDLE_MINUTES = 50
const DEFAULT_MIN_TOKENS = 60000
// A plain prompt, so the model decides: resume unfinished work, or wrap when
// nothing is in progress. A slash command here would run as typed instead.
const DEFAULT_PROMPT = [
  'Idle check from the idle-wrap mod: this session has sat idle long enough that it is about to be wrapped.',
  'First decide whether you were still in the middle of something when the last turn ended:',
  'a background command or subagent you were waiting on, a CI run, deploy or other external process',
  'you said you would check back on, or a next step you announced and had not started.',
  'If so, pick up exactly where you left off and finish it; do not wrap, and do not ask whether to continue.',
  'Only if nothing is in progress and nothing is left to do should you run /wrap --fast now.',
  'If this session has already been wrapped and nothing has happened since, reply with one short line and stop.',
].join(' ')
const WRAP_SKILL = 'wrap'
// The dim footer label (beside `focus`, `memory paused`) that says the mod is armed
const MODE_LABEL = 'idle-wrap'
const MAX_WRAP_ATTEMPTS = 3

// Settings for this activation, filled in by session.start
let idleMs = DEFAULT_IDLE_MINUTES * 60000
let minTokens = DEFAULT_MIN_TOKENS
let prompt = DEFAULT_PROMPT
let isDisabled = false

// Session lifecycle and activity
let isSessionActive = false
let isInteractive = false
let lastActivityAt = 0
let generation = 0
let isBusy = false

// Wrap state
let isWrapSubmitted = false
let isWrapInFlight = false
let isWrapDone = false
let hasWrapRun = false
let wrapAttempts = 0
let wrapAttemptSeq = 0
let activeAttemptId = 0
let pendingModSubmission = false
let timer = null

function positiveNumber(text, fallback) {
  const value = Number(text)
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function isPromptDropped(result) {
  return Boolean(result && typeof result.drop === 'string')
}

async function readSettings($, options) {
  // The manifest's userConfig values, then environment overrides for tests
  // and one-off sessions. Every name is a literal so validate can list them.
  const envIdle = await $.env.get('IDLE_WRAP_IDLE_MINUTES')
  const envTokens = await $.env.get('IDLE_WRAP_MIN_TOKENS')
  const envPrompt = await $.env.get('IDLE_WRAP_PROMPT')
  const envDisabled = await $.env.get('IDLE_WRAP_DISABLED')
  idleMs = positiveNumber(envIdle ?? options.idleMinutes, DEFAULT_IDLE_MINUTES) * 60000
  minTokens = positiveNumber(envTokens ?? options.minTokens, DEFAULT_MIN_TOKENS)
  prompt = (envPrompt ?? options.prompt ?? DEFAULT_PROMPT).trim() || DEFAULT_PROMPT
  isDisabled = envDisabled === '1' || envDisabled === 'true'
}

async function idleFor($) {
  const now = await $.clock.now()
  return now - lastActivityAt
}

async function contextTokens($) {
  const usage = await $.session.usage()
  return usage?.context?.tokens ?? 0
}

function parsePrompt(text) {
  const trimmed = text.trim()
  if (!trimmed.startsWith('/')) return null
  const space = trimmed.indexOf(' ')
  const command = space < 0 ? trimmed.slice(1) : trimmed.slice(1, space)
  const args = space < 0 ? '' : trimmed.slice(space + 1).trim()
  return { command, args }
}

function isModCommand(e) {
  const parsed = parsePrompt(prompt)
  if (!parsed) return false
  return e.command === parsed.command && (e.args ?? '').trim() === parsed.args
}

function isModPrompt(text) {
  return text.trim() === prompt
}

// A slash-command prompt is the wrap itself; a plain prompt leaves the
// outcome to the model, so the wrap skill running during the turn is the
// evidence that it wrapped.
function isOutcomeDecidedByModel() {
  return parsePrompt(prompt) === null
}

function promptLabel() {
  return isOutcomeDecidedByModel() ? 'the idle-wrap prompt' : prompt
}

// A prompt that starts with a slash is a command or skill: it runs as if the
// person typed it. Anything else goes to the model as a prompt.
async function submitPrompt($) {
  pendingModSubmission = true
  try {
    const parsed = parsePrompt(prompt)
    if (parsed) {
      return await $.command.run({ command: parsed.command, args: parsed.args })
    }
    return await $.prompt.submit({ text: prompt })
  } finally {
    pendingModSubmission = false
  }
}

function isEligible(startGen) {
  if (!isSessionActive || !isInteractive || isDisabled || isWrapSubmitted || isWrapInFlight || isBusy) {
    return false
  }
  if (wrapAttempts >= MAX_WRAP_ATTEMPTS) return false
  if (startGen !== undefined && generation !== startGen) return false
  return true
}

async function handleSubmissionFailure($, attemptGen, attemptId, errorMsg) {
  if (!isSessionActive || generation !== attemptGen || attemptId !== activeAttemptId) return
  $.ui.log('could not run ' + promptLabel() + ': ' + errorMsg)
  const errNow = await $.clock.now()
  if (!isSessionActive || generation !== attemptGen || attemptId !== activeAttemptId) return
  wrapAttempts++
  noteActivity(errNow)
  isWrapSubmitted = false
  isWrapInFlight = false
  isWrapDone = false
  hasWrapRun = false
  activeAttemptId = 0
}

async function tick($) {
  if (!isEligible()) return

  const startGen = generation
  const now = await $.clock.now()
  if (!isEligible(startGen)) return
  if (now - lastActivityAt < idleMs) return

  const tokens = await contextTokens($)
  if (!isEligible(startGen)) return
  if (tokens < minTokens) return

  const nowAfter = await $.clock.now()
  if (!isEligible(startGen)) return
  if (nowAfter - lastActivityAt < idleMs) return

  isWrapSubmitted = true
  isWrapInFlight = true
  const attemptGen = generation
  const attemptId = ++wrapAttemptSeq
  activeAttemptId = attemptId
  hasWrapRun = false
  $.ui.log('idle for ' + Math.round(idleMs / 60000) + ' min with ' + tokens + ' context tokens: running ' + promptLabel())

  // Resolves when the queued run finishes; catch transient submission failure or drop
  submitPrompt($)
    .then(async (result) => {
      if (isPromptDropped(result)) {
        const reason = result.drop
        await handleSubmissionFailure($, attemptGen, attemptId, 'prompt dropped: ' + reason)
      }
    })
    .catch(async (error) => {
      await handleSubmissionFailure(
        $,
        attemptGen,
        attemptId,
        error && error.message ? error.message : String(error)
      )
    })
}

function noteActivity(now) {
  lastActivityAt = now
  generation++
}

function resetForUser() {
  isWrapSubmitted = false
  isWrapInFlight = false
  isWrapDone = false
  hasWrapRun = false
  wrapAttempts = 0
  activeAttemptId = 0
}

async function onSessionStart($, e, options) {
  await readSettings($, options ?? {})
  isSessionActive = true
  isInteractive = e.isInteractive === true
  isBusy = false
  wrapAttemptSeq = 0
  activeAttemptId = 0
  resetForUser()
  noteActivity(await $.clock.now())
  if (timer) timer.cancel()
  timer = $.clock.every(TICK_MS, () => tick($))
}

async function onPromptSubmit($, e, next) {
  if (e.agentId) return next(e)
  const isFromMod = pendingModSubmission && isModPrompt(e.text)
  if (isFromMod) {
    pendingModSubmission = false
    return next(e)
  }
  const now = await $.clock.now()
  noteActivity(now)
  resetForUser()
  $.ui.status(undefined)
  const result = await next(e)
  // Acceptance starts unfinished work regardless of newer submission attempts.
  // Refusals cannot clear it; only main-loop completion ends the busy interval.
  if (!isPromptDropped(result)) {
    isBusy = true
  }
  return result
}

async function onCommandRun($, e, next) {
  if (e.agentId) return next(e)
  const isFromMod = pendingModSubmission && isModCommand(e)
  if (isFromMod) {
    pendingModSubmission = false
    return next(e)
  }
  const now = await $.clock.now()
  noteActivity(now)
  resetForUser()
  $.ui.status(undefined)
  return next(e)
}

// The wrap skill expanding on the main loop during the mod's turn: the model
// chose to wrap rather than resume.
async function onSkillPrompt($, e, next) {
  const isIdleAttempt = !e.agentId && isSessionActive && isWrapInFlight && activeAttemptId > 0
  const attemptId = activeAttemptId
  const attemptGen = generation
  // Latched only once the expansion beneath succeeded for this same idle
  // attempt: a rejected or stale delivery is not a wrap.
  const result = await next(e)
  if (
    isIdleAttempt &&
    isSessionActive &&
    isWrapInFlight &&
    activeAttemptId === attemptId &&
    generation === attemptGen
  ) {
    hasWrapRun = true
  }
  return result
}

async function onTurnComplete($, e, next) {
  if (e.agentId) return next(e)
  isBusy = false
  noteActivity(await $.clock.now())
  if (isWrapInFlight) {
    isWrapInFlight = false
    activeAttemptId = 0
    const didWrap = hasWrapRun || !isOutcomeDecidedByModel()
    hasWrapRun = false
    if (e.isAborted) {
      isWrapSubmitted = false
      isWrapDone = false
      wrapAttempts++
    } else if (didWrap) {
      isWrapDone = true
      wrapAttempts = 0
      $.ui.status('wrapped while idle; read the summary above, then /exit')
    } else {
      // Resumed unfinished work instead: arm again for the next idle stretch,
      // counted against the attempt cap so a session cannot resume forever.
      isWrapSubmitted = false
      isWrapDone = false
      wrapAttempts++
      $.ui.status('idle check resumed unfinished work; it wraps on the next idle stretch')
    }
  }
  return next(e)
}

// The armed state lives in the prompt footer's mode labels; the status line
// is kept for the outcome alone, once the idle turn has run.
async function onSessionModeRender($, e, next) {
  if (!isSessionActive || !isInteractive || isDisabled) return next(e)
  const modes = e.props.modes ?? []
  if (modes.includes(MODE_LABEL)) return next(e)
  return next({ ...e, props: { ...e.props, modes: [...modes, MODE_LABEL] } })
}

async function onSessionCompact($, e, next) {
  if (e.agentId || e.trigger === 'manual' || !isInteractive || isDisabled || !isSessionActive) {
    return next(e)
  }
  if (isBusy || isWrapInFlight) {
    return next(e)
  }
  if (isWrapDone) {
    return { skip: 'idle-wrap: the session was wrapped instead of compacted' }
  }
  if ((await idleFor($)) >= idleMs) {
    return { skip: 'idle-wrap: wrapping the idle session instead of compacting it' }
  }
  return next(e)
}

export function register(on, options) {
  on('session.start', async ($, e, next) => {
    await onSessionStart($, e, options)
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    isSessionActive = false
    generation++
    isBusy = false
    activeAttemptId = 0
    if (timer) timer.cancel()
    timer = null
    return next(e)
  })

  on('prompt.submit', onPromptSubmit).catch(async ($, e, next) => next(e))

  on('command.run', onCommandRun).catch(async ($, e, next) => next(e))

  on('skill.prompt', { skill: WRAP_SKILL }, onSkillPrompt)

  on('turn.complete', onTurnComplete)

  on('session.compact', onSessionCompact).catch(async ($, e, next) => next(e))

  on('ui.render', { component: 'SessionMode' }, onSessionModeRender)
}
