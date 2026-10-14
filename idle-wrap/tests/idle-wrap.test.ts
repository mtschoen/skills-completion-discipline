// Kept together so lifecycle race cases share the same mock-clock hook harness.
import { expect, mock, test } from 'claude-code/testing'

const TICK_MS = 60000
const FIFTY_MINUTES = 50 * 60000
const TEN_MINUTES = 10 * 60000
const ONE_MESSAGE = [{ role: 'user', text: 'hello', toolUses: [] }]

// Stubs every call the mod makes, records what it ran and showed, and starts
// the session. Returns the clock the test drives and the records.
async function start(
  $,
  on,
  {
    tokens = 150000,
    isInteractive = true,
    env = {},
    onCommandRun = null,
    onPromptSubmit = null,
    onUsage = null,
    onClockNow = null,
  }: {
    tokens?: number
    isInteractive?: boolean
    env?: Record<string, string>
    onCommandRun?: (($, e: any) => Promise<any> | any) | null
    onPromptSubmit?: (($, e: any) => Promise<any> | any) | null
    onUsage?: (() => Promise<any> | any) | null
    onClockNow?: ((nowMs: number) => Promise<any> | any) | null
  } = {}
) {
  let clockNowHandler: any = null
  const wrappedOn = (event: string, handler: any) => {
    if (event === 'clock.now') {
      clockNowHandler = handler
      return on(event, async (...args: any[]) => {
        const result = clockNowHandler(...args)
        if (onClockNow) {
          await onClockNow(result?.value)
        }
        return result
      })
    }
    return on(event, handler)
  }
  const clock = mock.clock(wrappedOn)
  mock.env(on, env)
  const ran: string[] = []
  const submitted: string[] = []
  const logged: string[] = []
  const statuses: string[] = []
  on('session.start', () => ({ cwd: '/work' }))
  on('session.end', () => ({ sessionId: 'abc123' }))
  on('turn.complete', () => ({ text: '' }))
  on('session.compact', () => ({ messages: ONE_MESSAGE }))
  on('session.usage', async () => {
    if (onUsage) return await onUsage()
    return { value: { context: { tokens, window: 1000000, percent: 15 }, rateLimits: [] } }
  })
  on('command.run', async ($, e) => {
    ran.push('/' + e.command + (e.args ? ' ' + e.args : ''))
    if (onCommandRun) return await onCommandRun($, e)
    return { text: '' }
  })
  on('prompt.submit', async ($, e) => {
    submitted.push(e.text)
    if (onPromptSubmit) return await onPromptSubmit($, e)
    return { text: e.text }
  })
  on('ui.log', ($, e) => {
    logged.push(e.text)
    return { value: undefined }
  })
  on('ui.status', ($, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  await $.session.start({ surface: isInteractive ? 'terminal' : null, isInteractive, cwd: '/work' })
  return { clock, ran, submitted, logged, statuses }
}

function completeTurn($) {
  return $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 10, isAborted: false, reason: 'answer', usage: null })
}

for (const tc of [
  { id: 'baseline' },
  { id: 'deferred-usage-activity' },
  { id: 'deferred-usage-session-end' },
  { id: 'overlapping-deferred-ticks' },
  { id: 'rejected-slash-command' },
  { id: 'rejected-slash-command-recovery-overlap' },
  { id: 'rejected-plain-prompt-empty', dropReason: '' },
  { id: 'rejected-plain-prompt-nonempty', dropReason: 'prompt refused by hook' },
]) {
  test(`runs the wrap once the session has idled past the threshold [${tc.id}]`, async ($, on) => {
    if (tc.id === 'baseline') {
      const { clock, ran, logged } = await start($, on)
      await clock.advance(FIFTY_MINUTES - TICK_MS)
      expect(ran).toEqual([])
      await clock.advance(TICK_MS)
      expect(ran).toEqual(['/wrap --fast'])
      expect(logged.length).toBe(1)
      // Later ticks do not run a second wrap
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])
    } else if (tc.id === 'deferred-usage-activity') {
      let resolveUsage: any = null
      const { clock, ran } = await start($, on, {
        onUsage: () => new Promise((resolve) => {
          resolveUsage = resolve
        }),
      })
      await clock.advance(FIFTY_MINUTES)
      // Activity arrives while usage read is deferred
      await $.prompt.submit({ text: 'user is back', wait: false })
      resolveUsage({ value: { context: { tokens: 150000, window: 1000000, percent: 15 }, rateLimits: [] } })
      await clock.advance(TICK_MS)
      expect(ran).toEqual([])
    } else if (tc.id === 'deferred-usage-session-end') {
      let finalClockCount = 0
      let deferFinalClock: any = null
      const { clock, ran } = await start($, on, {
        onClockNow: (nowMs: number) => {
          if (nowMs >= FIFTY_MINUTES) {
            finalClockCount++
            // The tick at 50 min calls clock.now() twice:
            // 1. tick start (now = await $.clock.now())
            // 2. final clock read (nowAfter = await $.clock.now())
            if (finalClockCount === 2) {
              return new Promise((resolve) => {
                deferFinalClock = resolve
              })
            }
          }
        },
      })
      await clock.advance(FIFTY_MINUTES)
      expect(deferFinalClock).not.toBeNull()
      // Session ends while the final clock read is pending
      await $.session.end({ sessionId: 'abc123' })
      deferFinalClock()
      await clock.advance(TICK_MS)
      expect(ran).toEqual([])
    } else if (tc.id === 'overlapping-deferred-ticks') {
      let finalClockCount = 0
      let deferFirstTickClock: any = null
      const { clock, ran } = await start($, on, {
        onClockNow: (nowMs: number) => {
          if (nowMs >= FIFTY_MINUTES) {
            finalClockCount++
            // Defer final clock read of the first eligible tick at 50 min
            if (finalClockCount === 2) {
              return new Promise((resolve) => {
                deferFirstTickClock = resolve
              })
            }
          }
        },
      })
      await clock.advance(FIFTY_MINUTES)
      expect(deferFirstTickClock).not.toBeNull()
      // Advance to trigger a second tick while the first tick's final clock read is still pending
      await clock.advance(TICK_MS)
      expect(ran).toEqual(['/wrap --fast'])
      // Now resolve the first tick's final clock read; it must recheck latches and not submit a duplicate
      deferFirstTickClock()
      await clock.advance(TICK_MS)
      expect(ran).toEqual(['/wrap --fast'])
    } else if (tc.id === 'rejected-slash-command') {
      let rejectCommand: any = null
      let shouldReject = true
      const { clock, ran, statuses } = await start($, on, {
        onCommandRun: () => {
          if (shouldReject) {
            shouldReject = false
            return new Promise((_, reject) => {
              rejectCommand = () => reject(new Error('command run failed'))
            })
          }
          return { text: '' }
        },
      })
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])
      expect(statuses).toEqual([])
      // Compact does not claim the session was wrapped
      expect(await $.session.compact({ trigger: 'auto', messages: ONE_MESSAGE })).not.toEqual({
        skip: 'idle-wrap: the session was wrapped instead of compacted',
      })
      // User resumes with a new prompt while wrap submission is still pending
      await $.prompt.submit({ text: 'user turn while submission pending', wait: false })
      // Now the older submission rejects; stale failure must not clear user's busy state
      expect(rejectCommand).not.toBeNull()
      rejectCommand()
      await clock.advance(TICK_MS)
      // User's turn is unfinished; advancing past threshold must not submit a wrap
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])
      // User's turn completes
      await completeTurn($)
      // Now idling past threshold submits a new wrap
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast', '/wrap --fast'])
      // Once succeeded, subsequent ticks do not run another wrap
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast', '/wrap --fast'])
    } else if (tc.id === 'rejected-slash-command-recovery-overlap') {
      let clockNowCount = 0
      let deferRecoveryClock: any = null
      const { clock, ran } = await start($, on, {
        onCommandRun: () => {
          return Promise.reject(new Error('command run failed'))
        },
        onClockNow: (nowMs: number) => {
          if (nowMs >= FIFTY_MINUTES && !deferRecoveryClock) {
            clockNowCount++
            // Recovery clock read in handleSubmissionFailure is the 3rd clock.now() at 50 min
            if (clockNowCount === 3) {
              return new Promise((resolve) => {
                deferRecoveryClock = resolve
              })
            }
          }
        },
      })
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])
      expect(deferRecoveryClock).not.toBeNull()
      // Advance to trigger the next timer tick while recovery clock read is still pending
      await clock.advance(TICK_MS)
      // Must not submit a duplicate attempt while recovery clock read is pending
      expect(ran).toEqual(['/wrap --fast'])
      // Resolve the recovery clock read
      deferRecoveryClock()
      await clock.advance(TICK_MS)
      // Idling past another full threshold retries wrap submission
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast', '/wrap --fast'])
    } else if (tc.id.startsWith('rejected-plain-prompt')) {
      let promptOutcome: 'drop' | 'ok' = 'drop'
      const env = { IDLE_WRAP_PROMPT: 'reply with PING' }
      const { clock, submitted } = await start($, on, {
        env,
        onPromptSubmit: ($, e) => {
          if (e.text === 'reply with PING') {
            if (promptOutcome === 'drop') {
              promptOutcome = 'ok'
              return { drop: tc.dropReason }
            }
          }
          return { text: e.text }
        },
      })
      await clock.advance(FIFTY_MINUTES)
      expect(submitted).toEqual(['reply with PING'])
      // Retries after next threshold following explicit prompt refusal
      await clock.advance(FIFTY_MINUTES)
      expect(submitted).toEqual(['reply with PING', 'reply with PING'])
      // Once succeeded, subsequent ticks do not retry
      await clock.advance(FIFTY_MINUTES)
      expect(submitted).toEqual(['reply with PING', 'reply with PING'])
    }
  })
}

for (const tc of [
  { id: 'empty-drop', kind: 'drop' as const, dropReason: '' },
  { id: 'nonempty-drop', kind: 'drop' as const, dropReason: 'refused by hook' },
  { id: 'rejected-prompt', kind: 'reject' as const, dropReason: '' },
  { id: 'F4-1-newer-drop-before-older-acceptance', kind: 'reverse' as const, dropReason: 'refused' },
  { id: 'F4-2-newer-empty-drop-before-older-acceptance', kind: 'reverse' as const, dropReason: '' },
  { id: 'F4-3-newer-rejection-before-older-acceptance', kind: 'reverse' as const },
  { id: 'F4-4-newer-completion-before-older-acceptance', kind: 'reverse' as const, isAborted: false },
  { id: 'F4-4-newer-abort-before-older-acceptance', kind: 'reverse' as const, isAborted: true },
]) {
  test(`a finished turn resets the idle clock [${tc.id}]`, async ($, on) => {
    if (tc.kind === 'reverse') {
      let acceptOlder: any = null
      const { clock, ran } = await start($, on, {
        onPromptSubmit: ($, e) => {
          if (e.text === 'older prompt') {
            return new Promise((resolve) => { acceptOlder = () => resolve({ text: e.text }) })
          }
          if (tc.dropReason !== undefined) return { drop: tc.dropReason }
          if (tc.isAborted !== undefined) return { text: e.text }
          throw new Error('newer submission rejected')
        },
      })
      const older = $.prompt.submit({ text: 'older prompt', wait: false })
      await $.prompt.submit({ text: 'newer prompt', wait: false }).catch(() => {})
      if (tc.isAborted !== undefined) {
        await $.turn.complete({ turnId: 'newer', answer: '', durationMs: 10,
          isAborted: tc.isAborted, reason: tc.isAborted ? 'aborted' : 'answer', usage: null })
      }
      expect(acceptOlder).not.toBeNull()
      acceptOlder()
      await older
      await clock.advance(FIFTY_MINUTES + TEN_MINUTES)
      expect(await $.session.compact({ trigger: 'auto', messages: ONE_MESSAGE })).toEqual({ messages: ONE_MESSAGE })
      expect(ran).toEqual([])
      await completeTurn($)
      await clock.advance(FIFTY_MINUTES - TICK_MS)
      expect(ran).toEqual([])
      await clock.advance(TICK_MS)
      expect(ran).toEqual(['/wrap --fast'])
      return
    }
    let deferredDropResolve: any = null
    let deferredRejectReject: any = null
    const { clock, ran } = await start($, on, {
      onPromptSubmit: ($, e) => {
        if (e.text === 'refused prompt' || e.text === 'refused while active') {
          return { drop: tc.dropReason }
        }
        if (e.text === 'rejected while active') {
          throw new Error('prompt submission failed')
        }
        if (e.text === 'deferred drop prompt') {
          return new Promise((resolve) => {
            deferredDropResolve = () => resolve({ drop: tc.dropReason })
          })
        }
        if (e.text === 'deferred reject prompt') {
          return new Promise((_, reject) => {
            deferredRejectReject = () => reject(new Error('deferred prompt failed'))
          })
        }
        return { text: e.text }
      },
    })

    if (tc.kind === 'drop') {
      // Refused user prompt does not leave session busy; idles past threshold and wraps
      await $.prompt.submit({ text: 'refused prompt', wait: false })
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])
      await completeTurn($)

      // Unfinished turn: session remains busy past threshold, no wrap submitted
      await $.prompt.submit({ text: 'long running turn', wait: false })

      // Refusal during an unfinished turn preserves active-turn state
      await $.prompt.submit({ text: 'refused while active', wait: false })
      await clock.advance(FIFTY_MINUTES + TEN_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])

      // Older deferred refusal settling after newer prompt acceptance preserves active-turn state
      const pendingDeferredDrop = $.prompt.submit({ text: 'deferred drop prompt', wait: false })
      await $.prompt.submit({ text: 'newer accepted prompt', wait: false })
      expect(deferredDropResolve).not.toBeNull()
      deferredDropResolve()
      await pendingDeferredDrop

      await clock.advance(FIFTY_MINUTES + TEN_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])

      // Completing the long turn resets idle clock; no wrap reported for this turn
      await completeTurn($)
      expect(ran).toEqual(['/wrap --fast'])

      // A finished turn resets the idle clock
      await clock.advance(FIFTY_MINUTES - TEN_MINUTES)
      await completeTurn($)
      await clock.advance(TEN_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])
      await clock.advance(FIFTY_MINUTES - TEN_MINUTES)
      expect(ran).toEqual(['/wrap --fast', '/wrap --fast'])
    } else {
      // Unfinished turn: session remains busy past threshold
      await $.prompt.submit({ text: 'long running turn', wait: false })

      // Older deferred rejection settling after newer prompt acceptance preserves active-turn state
      const pendingDeferredReject = $.prompt.submit({ text: 'deferred reject prompt', wait: false }).catch(() => {})
      await $.prompt.submit({ text: 'newer accepted prompt', wait: false })
      expect(deferredRejectReject).not.toBeNull()
      deferredRejectReject()
      await pendingDeferredReject

      // Newer turn is still unfinished: no wrap submitted
      await clock.advance(FIFTY_MINUTES + TEN_MINUTES)
      expect(ran).toEqual([])

      // Completing the turn resets idle clock; then idling past threshold wraps
      await completeTurn($)
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])
      await completeTurn($)

      // Start a second active turn and verify rejected submission during active turn preserves busy state
      await $.prompt.submit({ text: 'second running turn', wait: false })
      await $.prompt.submit({ text: 'rejected while active', wait: false }).catch(() => {})

      // Still unfinished: no new wrap submitted past threshold
      await clock.advance(FIFTY_MINUTES + TEN_MINUTES)
      expect(ran).toEqual(['/wrap --fast'])

      // Completing second turn resets idle clock; idling past threshold wraps again
      await completeTurn($)
      await clock.advance(FIFTY_MINUTES)
      expect(ran).toEqual(['/wrap --fast', '/wrap --fast'])
    }
  })
}

test('leaves a small session alone', async ($, on) => {
  const { clock, ran } = await start($, on, { tokens: 20000 })
  await clock.advance(FIFTY_MINUTES * 2)
  expect(ran).toEqual([])
})

test('does nothing in a non-interactive session', async ($, on) => {
  const { clock, ran } = await start($, on, { isInteractive: false })
  await clock.advance(FIFTY_MINUTES * 2)
  expect(ran).toEqual([])
})

test('environment overrides change the delay, threshold, and command', async ($, on) => {
  const env = { IDLE_WRAP_IDLE_MINUTES: '2', IDLE_WRAP_MIN_TOKENS: '1000', IDLE_WRAP_PROMPT: '/idle-wrap' }
  const { clock, ran } = await start($, on, { tokens: 5000, env })
  await clock.advance(2 * 60000)
  expect(ran).toEqual(['/idle-wrap'])
})

test('a prompt without a slash goes to the model as a prompt', async ($, on) => {
  const env = { IDLE_WRAP_IDLE_MINUTES: '1', IDLE_WRAP_MIN_TOKENS: '1', IDLE_WRAP_PROMPT: 'reply with the word PING' }
  const { clock, ran, submitted } = await start($, on, { tokens: 10, env })
  await clock.advance(60000)
  expect(ran).toEqual([])
  expect(submitted).toEqual(['reply with the word PING'])
})

test('IDLE_WRAP_DISABLED turns the mod off', async ($, on) => {
  const { clock, ran } = await start($, on, { env: { IDLE_WRAP_DISABLED: '1' } })
  await clock.advance(FIFTY_MINUTES * 2)
  expect(ran).toEqual([])
})

test('vetoes automatic compaction of an idle session and lets the rest through', async ($, on) => {
  const { clock } = await start($, on)
  // Active session: the context-window compaction goes ahead
  await clock.advance(TEN_MINUTES)
  expect(await $.session.compact({ trigger: 'auto', messages: ONE_MESSAGE })).toEqual({ messages: ONE_MESSAGE })

  // Long active turn: compaction goes ahead even past the threshold
  await $.prompt.submit({ text: 'working on a long task', wait: false })
  await clock.advance(FIFTY_MINUTES)
  expect(await $.session.compact({ trigger: 'auto', messages: ONE_MESSAGE })).toEqual({ messages: ONE_MESSAGE })
  await completeTurn($)

  // Active wrap: compaction during the wrap turn passes through
  await clock.advance(FIFTY_MINUTES)
  expect(await $.session.compact({ trigger: 'auto', messages: ONE_MESSAGE })).toEqual({ messages: ONE_MESSAGE })

  // Idle session after wrap: vetoed
  await completeTurn($)
  const vetoed = await $.session.compact({ trigger: 'auto', messages: ONE_MESSAGE })
  expect(vetoed.skip).toBeDefined()

  // A manual /compact is always the owner's call
  expect(await $.session.compact({ trigger: 'manual', messages: ONE_MESSAGE })).toEqual({ messages: ONE_MESSAGE })
})

test('shows a status line when the wrap turn finishes and re-arms on the next user prompt', async ($, on) => {
  const { clock, ran, statuses } = await start($, on)

  // Unfinished turn does not emit wrap status
  await $.prompt.submit({ text: 'unfinished turn', wait: false })
  await clock.advance(TEN_MINUTES)
  await completeTurn($)
  expect(statuses.some((s) => s.includes('wrapped while idle'))).toBe(false)

  // Idle session reaches threshold and wrap is submitted
  await clock.advance(FIFTY_MINUTES)
  expect(ran).toEqual(['/wrap --fast'])

  // Aborted wrap completion does not emit successful wrap status and restores retry eligibility
  await $.turn.complete({ turnId: 't-aborted', answer: '', durationMs: 10, isAborted: true, reason: 'aborted', usage: null })
  expect(statuses.some((s) => s.includes('wrapped while idle'))).toBe(false)

  // Retries after next threshold
  await clock.advance(FIFTY_MINUTES)
  expect(ran).toEqual(['/wrap --fast', '/wrap --fast'])

  // Successful wrap completion shows status line
  await completeTurn($)
  expect(statuses.length).toBeGreaterThan(0)
  expect(statuses[statuses.length - 1]).toMatch(/wrapped while idle/)

  // Command-only resumption clears status and re-arms without starting a model turn
  await $.command.run({ command: 'help', args: '' })
  expect(statuses[statuses.length - 1]).toBe('')
  await clock.advance(FIFTY_MINUTES)
  expect(ran).toEqual(['/wrap --fast', '/wrap --fast', '/help', '/wrap --fast'])
  await completeTurn($)
  expect(statuses[statuses.length - 1]).toMatch(/wrapped while idle/)

  // Prompt resumption clears status and re-arms
  await $.prompt.submit({ text: 'continue with the next issue', wait: false })
  expect(statuses[statuses.length - 1]).toBe('')
  await completeTurn($)
  await clock.advance(FIFTY_MINUTES)
  expect(ran).toEqual(['/wrap --fast', '/wrap --fast', '/help', '/wrap --fast', '/wrap --fast'])
})
