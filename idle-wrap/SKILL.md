---
name: idle-wrap
description: "Use when the owner asks how idle wrap works, why a Claude Code session wrapped itself or resumed on its own, or how to tune or disable it. Explains the mod that prompts the open session near the idle prompt-cache cliff to resume unfinished work or run /wrap --fast, preserving context instead of letting idle compaction summarize it."
disable-model-invocation: true
---

# idle-wrap

## Applicability

Explains the idle-wrap mod, which prompts the open Claude Code session when it has sat idle near the prompt-cache cliff: resume whatever was left unfinished, or run /wrap --fast when nothing is in progress, instead of letting idle compaction summarize it. Use when the owner asks how idle wrap works, why a session wrapped itself or resumed on its own, or how to tune or disable it.

A Claude Code mod, not a procedure. The directory carries a plugin manifest
and a hooks module, so Claude Code loads it in every session from the skills
directory, as `idle-wrap@skills-dir`. Claude Code only: no other harness has
the idle-compaction cliff or the mods API.

## What it does

- Records the time of every prompt and every finished main-loop turn.
- Once a minute, in an interactive session, checks how long the session has
  been idle and how many context tokens it holds.
- When the idle time reaches the threshold (default 50 minutes, just ahead of
  idle compaction at about 54) and the context is above the minimum (default
  60,000 tokens), submits the idle-wrap prompt as the owner's own words. The
  default prompt asks the model to decide: if the last turn ended while
  waiting on something (a background command, a subagent, a CI run, an
  announced next step), pick up where it left off and do not wrap; only when
  nothing is in progress run `/wrap --fast`. Either way the turn runs in the
  same session with the whole conversation still in context and still on the
  one-hour prompt cache.
- Knows which way the model went by watching for the `wrap` skill expanding
  during that turn. A turn that resumed work instead arms the mod again, so
  the next idle stretch prompts once more; resumes count against the same
  three-attempt cap as failed submissions, so a session cannot resume forever.
- Vetoes automatic compaction of an idle session, so the owner comes back to
  a wrap, never a summary. Manual `/compact` and compaction during live work
  pass through untouched.
- After the turn finishes, shows one status line under the prompt: either
  read the summary, then `/exit` so the session id stays one start-to-wrap arc, or that it resumed unfinished work and
  wraps on the next idle stretch.

## Tune or disable it

Per-session environment overrides, read at session start:

| Variable | Effect |
| --- | --- |
| `IDLE_WRAP_IDLE_MINUTES` | Minutes idle before the wrap prompt is submitted |
| `IDLE_WRAP_MIN_TOKENS` | Context tokens below which the session is left alone |
| `IDLE_WRAP_PROMPT` | The text submitted instead of the default prompt; plain text goes to the model, a slash command (such as `/wrap --fast`) runs as typed with no resume check |
| `IDLE_WRAP_DISABLED` | `1` turns the mod off for the session |

Durable values go through `/plugin configure idle-wrap` or the
`pluginConfigs` key in user settings. Pair the mod with
`"idleCompaction": false` in user settings so nothing compacts an idle
session even when the mod does not load.

## Verify a change

From the `idle-wrap` directory: `claude plugin validate .` lists the events
and calls, `claude plugin test` runs `tests/idle-wrap.test.ts` on a mock
clock. For a live check, start a throwaway session with
`IDLE_WRAP_IDLE_MINUTES=2 IDLE_WRAP_MIN_TOKENS=1 claude --plugin-dir <path>`,
send one prompt, and wait two minutes.
