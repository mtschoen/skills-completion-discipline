---
name: wrap
description: Use when the user says /wrap, "wrap up", "close out this session", "finish the session", "wrap and keep going in a fresh session", or "wrap and continue". Also when asked to update memory, save learnings, or commit everything before exit, or at a natural stopping point after the soft 250K wrap nudge.
---

# wrap

The session-closing ritual for a coding agent session. Performs two equally-mandatory jobs: **externalize ephemeral working memory** (things the current agent knows from this conversation that no file/commit captures yet) into durable artifacts, and **bring every touched repo into a clean state** so the next session's agent doesn't waste cycles wading through obsolete context.

## When to use

- User types `/wrap` or says some variant of "wrap up this session", "close out", "let's finish for the day". `/wrap --fast` runs the same procedure non-interactively (no questions, safe actions only) - see "Fast mode" below.
- User explicitly asks you to update memory / save learnings / commit everything before exit.
- In Claude Code, the owner requests a fresh-session chain, or the soft 250K wrap nudge has fired and the current ask or plan task reaches a natural stopping point. See "Chain mode" below.

## When NOT to use

- User is exiting quickly to restart the session, reboot the machine, or context-switch. Some exits are quick exits; those are not wraps.
- Neither explicit wrap intent nor the chain-mode stopping-point trigger applies. The separate `SessionEnd` reminder only nudges the user.
- During an unfinished ask or plan task after the soft 250K nudge. Finish that work before chaining; there is no hard context ceiling.

## Operating principles

1. **Memory offload first, hygiene second.** The headline job is externalizing what is about to be destroyed. Repo cleanup is equally mandatory but conceptually secondary: if memory offload fails for a repo, do not proceed to destructive cleanup in that repo.

2. **Portable and tool-agnostic.** Wrap works in any repo with or without `project-tracker`, with or without superpowers, on any platform. Describe what needs to happen in prose; let the available tools decide how.

3. **Always fan out.** One `/wrap` covers every repo the session touched, not just the current working directory. Use your own recall of which paths you edited + a dirty-scan cross-check + user confirmation.

4. **Looser delete semantics than `project-maintenance`.** Wrap may delete untracked files **with explicit per-item approval**. project-maintenance forbids untracked-file deletion entirely. This divergence is intentional: externalizing scratch and then cleaning it up is wrap's whole purpose.

5. **Extract loose threads before deleting anything.** Any plan, scratch file, or stale memory being removed must first be scanned for "we should fix X later" / "Y might come up again" thoughts, which go to durable destinations *before* the source is removed. See `references/plan-classification.md`.

6. **Current-state driven.** Each invocation asks "what's true right now" and acts accordingly. Running `/wrap` twice in a row is safe - the second run finds nothing the first one already cleaned. In chain mode, handoff files carry the chain ledger; check the recorded successor before launching another.

7. **Verify before delete.** Every finding surfaces with evidence, a recommendation, a confidence level, and the exact action on approval. The user approves a batch of findings at once, not item-by-item, unless explicitly described otherwise below.

8. **Ask through the richest channel the session offers.** In an interactive session whose harness provides a structured question tool (`AskUserQuestion` or a platform equivalent), route wrap's questions through it: ordered options with visible descriptions and one-keystroke answers beat scrollback-buried prose at the end of a long session. Shape each question to the tool's constraints - at most 4 options, the default option listed first and marked "(Recommended)", per-option descriptions written against the actual repo state. A candidate list longer than the option cap stays as a numbered list, but inside the question text itself, not the message printed above the tool call - that text goes unread once the widget renders; the tool still carries only the decision about the batch (see Phase 2a). If the tool call is dismissed, declined, or errors, do not retry it - take the question's stated default, announce it in one line, or re-ask that one question in prose if the answer genuinely gates destruction. Batch *findings* into one question freely (principle 7); do not stack unrelated *questions*.

   **Prose fallback.** Everywhere else - a harness with no such tool, a non-interactive run, an eval where the tool is disallowed - write wrap's questions in your own message text, one question at a time, under the protocol below. The prose protocol is the portable baseline; the structured tool is an interactive rendering of it, and both present the same options with the same defaults.

   **Letters name actions; numbers index items** (prose rendering).

   - A fixed vocabulary of actions takes **mnemonic letters**, because the letter carries the meaning and the user learns it once: **p** push, **c** commit only, **l** leave as-is.
   - A list of candidates to pick from takes **numbers** - memory items, plan files, junk directories. These are not a vocabulary, and numbers subset naturally: *"2 and 5"*, *"1-4"*, *"all"*, *"none"*.
   - Put the token **outside** the word: `**p** - push and commit`, not `(p)ush`. A letter buried inside its own label is harder to scan and turns the label into a non-word.

   **Every question states its default, and the default never destroys.** In prose, name it in the question: *"if you answer with something I can't map, I'll take **l** and say so."* In the structured tool, the default is the first, "(Recommended)" option. Either way the default is the most reversible option; for anything touching the user's own work, that is the option that changes nothing.

   **At most one clarifying re-ask.** If an answer doesn't map to an option, re-ask once, naming the options again. If the second answer still doesn't map, take the stated default, say in one line which one you took and why, and continue. Never ask a third time.

   **Accept any answer form.** The token, the whole word, a number if the user counted, or a paraphrase - map generously. Re-ask only when the reading genuinely changes what gets destroyed or written.

9. **No items, no ceremony.** Each phase only asks its question when its research has surfaced actual candidates. If a phase finds nothing, skip the question and continue. If *all* phases find nothing - including Phase 1's scope detection landing on a fully clean state - go straight to Phase 4 with a terse "nothing to wrap" summary. **Do not invent items out of nothing just to have something to do.** That is an explicit failure mode (see scenario 1 in `docs/pressure-scenarios.md`). Empty sweeps are a pass condition, not a problem to work around. Idempotent re-runs and clean-state invocations both look the same: detect nothing, summarize nothing, exit. A question the invocation itself already answered is ceremony too - see Phase 0. What is *not* ceremony: the one line stating which branch you took and which items it affects. Skipping a question is economy; skipping the statement is hiding a decision.

10. **Orchestrator retains override authority.** Parts of Phase 3 fan out to per-repo sonnet subagents to keep verbose tool output (file reads, status walls, plan-file contents) out of main context - *where the harness permits subagent dispatch at all* (see Phase 3's no-fan-out carve-out). The orchestrator (this conversation) is still in charge: it may at any time read repo contents directly, bypass a subagent's draft, or pull per-repo work back into main context if subagent output feels thin, suspicious, or incomplete. Subagents are an optimization, not a delegation contract. The judgment-heavy work - deciding what's worth saving, reviewing drafts, assembling the user-approval batch, writing the final summary - stays with the orchestrator.

## Fast mode (`--fast`)

`/wrap --fast` runs the **same five phases in the same sequence**, but non-interactively: it skips every approval gate and performs **only safe, additive actions** automatically. Use it to externalize and tidy a session without sitting through approval batches when you don't plan to revisit this session.

**Two hard invariants:**

- **No questions.** Every approval gate in Phases 0-3 is skipped; each takes its fast-mode default from the table below. Fast mode never blocks on the user.
- **Safe actions only.** Fast mode **writes** (memory files, AGENTS.md edits, wrap's own hygiene commit) but never **destroys or moves** data: no file deletes, no archiving/moving plan files, no stashing, and no committing or pushing the user's pre-existing work. Every destructive or user-facing action is recorded in the Phase 4 summary as *deferred*, not performed.

**Over-share, don't curate.** Because nobody is coming back to this session, lower the bar for what gets saved. When unsure whether a memory item is worth keeping, keep it. Fast mode deliberately trades a fatter memory footprint for zero lost context.

**Don't deliberate.** With no destructive action to gate and no approval batch to assemble, the careful per-finding review (principle 10) collapses: extract loose threads, write them, move on. Take subagent findings at face value for the memory writes - there is nothing to delete that a wrong call would punish.

The per-phase fast-mode defaults (what each approval gate resolves to) live in `references/fast-mode.md` - read it before running a `--fast` wrap.

A `--fast` run that finishes normally emits the **completed** closing sentinel; one the user interrupts emits the interrupted sentinel. Everything else in the Procedure below still applies - fast mode only changes how gates resolve, not the phase order or the failure-handling rules.

## Chain mode

In Claude Code, "wrap and keep going in a fresh session", "wrap and continue", "chain", or "hand off and keep going" selects **w** (wrap with handoff) plus chain mode. The soft 250K wrap nudge selects the same mode at the next natural stopping point, after the current ask or plan task finishes. It is not a hard ceiling; work that needs longer keeps going.

Run the normal phases and write the handoff using `references/chain.md` in full. Stop without a successor when its status is `blocked` or `done`, or the next session would exceed the safety cap of **10 links**. Otherwise, after cleanup and before Phase 4's final lines, launch from the same working directory with `claude --bg -n "<chain>-<n+1>" --permission-mode <this session's mode> "<resume prompt>"`. Confirm it through `claude agents --json` and record its short and full session ids in the handoff. The reference supplies the fixed resume prompt and failure procedure.

End with the successor's name and `claude attach <shortid>`, then the unchanged closing sentinel. A failed launch keeps the handoff and ends with the failure and exact manual launch command before the sentinel. The finished session ends naturally at its sentinel.

## Procedure

Wrap runs five phases in strict sequence (0 → 1 → 2 → 3 → 4) - but they are independently fault-tolerant. A failure in phase N does not undo phases 1..N-1, and (for most failures) does not abort phases N+1..last. Phase 4 (the summary) always runs, even after cancellation or failure.

The orchestrator runs Phases 0, 1, 2, 3a, and 3d directly. Phases 3b and 3c fan out to per-repo subagents (see "Subagent dispatch" below). Phase 4 stitches subagent fragments together with the orchestrator's cross-repo narrative.

### Phase 0 - Outstanding-asks check

Before scoping or sweeping anything, scan the conversation for asks the user made that haven't been resolved this session - features partway through, tasks 1-of-3 done, follow-ups pushed off "until later." This is conversation-level recall, not a filesystem scan. The output is a fork.

1. **Recall the user's asks.** Walk back through the session: what did the user ask for, what got done, what didn't, what got deferred? Read background-task output (e.g. via `TaskOutput`) for any subagent results that flagged unfinished items.
2. **Filter to the meaningful ones.** Trivial side-asks the user themselves dropped don't count. The bar is *"would the user be surprised this got dropped?"*
3. **If nothing meaningful is unfinished:** continue silently to Phase 1. Per principle 9, no ceremony.
4. **If unfinished items exist:** list them in one message and ask (through principle 8's channel) which of three ways to proceed:
   - **f** - **finish first.** Exit wrap immediately. No scope detect, no commits, nothing to undo. Return control so the user can continue the work - they can re-invoke `/wrap` once they're done.
   - **w** - **wrap with handoff** (the default). Continue normally; the unfinished-asks list becomes a seed for Phase 3a memory offload - it gets externalized as a handoff plan file or memory entry rather than being lost.
   - **d** - **wrap, drop the rest.** User decides the unfinished items aren't worth handing off. Continue normally; surface the dropped items in the Phase 4 summary so there's a record of what didn't make it.

**Do not ask a fork the invocation already answered - but say which branch you took.** If the user's own wording picked a branch - *"/wrap with a handoff"*, *"wrap it up and drop the rest"*, *"I'll finish this bit first, wrap the rest"* - take that branch and **say so in that same message, before Phase 1 starts**: which branch, and the wording that chose it. One line.

Chain wording (or the soft nudge at a natural stopping point) selects **w plus chain mode**. Announce that branch and the asks being handed off before Phase 1, as principle 9 requires. Write the chain handoff even when no asks remain, with status `done`; the stop rule then closes normally.

The announcement is not bookkeeping. An unannounced branch is indistinguishable from Phase 0 being skipped entirely, and the user's only chance to correct a misread is *before* the work happens. Re-asking a question the user has already answered is ceremony (principle 9); taking the branch silently is worse than ceremony.

**Treat it as an ordering constraint, not as a message.** Name the unfinished items and the branch **before wrap performs its first action** - before any write, commit, archive, delete, or push. Collapsing Phases 0-3 into one message is normal for a small wrap and changes nothing here: what matters is that the user reads which items are being dropped or handed off *while they can still object*, not after the commits have landed. **Reporting it only in the Phase 4 summary is the failure mode**, and it is the one that actually happens - the summary line reads as diligent, so it is easy to write and easy to mistake for compliance.

**The bar is wording about the wrap, not about the work.** *"/wrap with a handoff"* and *"wrap it up and drop the rest"* pick a branch. *"let's stop there"*, *"that's enough for today"*, *"we can finish this later"* end the working session and say nothing about what should become of the unfinished items - that fork is still open, so ask it. The default when the fork must be asked is **w** (wrap with handoff): it is the only branch that loses nothing.

### Phase 1 - Detect scope

Determine which repos the session touched. The repo containing the cwd at the time `/wrap` was invoked is **implicitly in scope** - the user ran the slash command from there with intent, even if the session never edited a file in it. Phase 1's recall then determines what *additional* repos beyond the cwd were touched. In order of precedence:

1. **Recall.** Review the conversation and list every path you edited, created, or ran git commands against. This is the primary source of truth for *additional* repos beyond the cwd.
2. **Dirty-scan cross-check.** For each recalled path plus the cwd (and their parent repos), check whether the working tree is dirty or has unpushed commits. Use whatever dirty-detection tooling is available - if `project-tracker` MCP tools are present, use them; otherwise run `git status` and `git log @{u}..HEAD` directly.
3. **Confirm with the user.** Present the detected repo list in one message and ask: *"I'll wrap these repos: [list]. Add or remove any?"*

**Not in scope:** Repos the session only *read*, other than the cwd. Reading is not touching, but the cwd is treated as in-scope regardless of whether the session edited it.

**Output of Phase 1:** An ordered list of touched-repo roots. Store it in working memory for Phases 2–4.

### Phase 2 - Session-wide sweep

Cross-cutting things not tied to any one project. Only done once per wrap, before per-repo work begins. Two sub-phases: memory offload, then background process sweep. Both run in the orchestrator's main context - they are intrinsically conversation-bound and don't benefit from subagent isolation.

**2a. Memory offload.**

1. Review your conversation context (plus the on-disk session transcript, if your harness persists one, when your context has been compacted and you need to recover earlier content). Include recent output from any background shells or subagents (read via `TaskOutput` or the platform equivalent) - loose threads hiding in their output count, including output from tasks that completed during the session but whose results you never explicitly harvested.
2. Walk the **cross-project categories** section of `references/categories.md` in order. For each category, ask yourself *"is there anything in this category from this session worth saving?"* and draft candidate items.
3. Each draft item is a concrete: what to save, where to save it, and why.
4. Surface the full set as one **numbered** list - one line per item saying what, where, and why. The default is **save all**: ask for exceptions, not for per-item approval. The numbered list always lives in the question text itself, not the message text (principle 8); a memory batch routinely outgrows any structured tool's option cap, so the tool never carries the items themselves. In the structured channel, the question carries only the batch decision - *"Save all N (Recommended)"* / *"Save none"* - and exceptions like *"drop 3 and 5"* arrive as a free-form answer. In prose: *"Save all of these? Or tell me which to drop or change - e.g. 'drop 3 and 5'."* Answers select by number; `all` and `none` both work. Do not turn the list into an item-by-item interrogation (principle 7), and do not silently shorten it because the set feels long.
5. Execute the approved writes - create or update memory files, modify `MEMORY.md` index entries, etc.

**Checklist-driven:** Walk every category even if you think it is empty. Quiet sessions should not silently skip memory offload.

**2b. Background process sweep.**

Explicitly terminate anything this session started in the background before declaring the session closed. The one exception is a confirmed chain successor recorded in a handoff header (chain mode, `references/chain.md`): it is the intended continuation, so exclude it from the roster and from every stop below, and leave it running. The harness *may* reap these on process exit, but that behavior is undocumented - explicit shutdown gives predictable results and a clean summary line.

**Enumerate, then verify - for every item below, not just teammates.** Two disciplines apply to all three categories, and both are learned-the-hard-way (see the incident notes under item 3):

- **Build the roster from the harness, not from recall.** Ask the platform what exists - a task-listing command (e.g. `/tasks`), the task-output directory, a process scan - and reconcile it against your memory of what you spawned. Recall alone systematically misses tasks: you remember the ones whose results you used.
- **Confirm each one is actually stopped.** Having read *a* task's output is not evidence that *every* task ended, and an output file existing is not evidence its task exited - a task that never terminates leaves an empty one. Check the roster off item by item and report the count in Phase 4.

1. Background Bash shells (`run_in_background: true`) - the platform treats these as tasks. Read their output (e.g. via `TaskOutput`, or by reading the output file) before stopping them, then confirm termination.

   Watch for **wait-loops that can never exit**: a backgrounded `while <process X is running>; do sleep N; done` never terminates when a scheduler respawns X on a cycle (a driver loop, a cron, a supervisor restart). This shape looks finished - it was "waiting for one thing" - and is easy to mark harvested when it is still spinning. Observed 2026-08-19: a loop polling for `merge-train run` to disappear outlived the wrap because the session had just re-armed the driver that respawns it every 5 minutes. Wait on a specific PID or a terminal log line instead, and treat any surviving poll loop as an item to stop, not a finished task.
2. Task/Agent subagents (`run_in_background: true`) - same rule: read output first, *then* terminate. **Recently-completed-but-unharvested tasks are in scope** - a subagent that finished 2 seconds ago is as much a source of ephemeral findings as one still mid-run. Do not skip the scan just because the task is no longer running; what matters is whether its output has been absorbed yet.
3. **Named teammate agents** (spawned via the Agent tool with a `name:`, addressable through `SendMessage`). These do NOT exit when their task ends - they linger idle (emitting `idle_notification` heartbeats) and survive past the wrap unless explicitly shut down. The sweep is a **roster-driven, verified shutdown** - four steps, and *sending a shutdown request is NOT the same as stopping an agent*:
   1. **Build the roster first.** List every named agent spawned this session, from your own recall of Agent-tool calls, spawn results, and `idle_notification` traffic. Where the harness offers an agent-listing tool (Claude Code has `ListAgents`), query it and reconcile against that recall rather than trusting either alone - a listing can report only *reachable* agents, and recall misses the ones whose results you never used. The sweep is judged complete against the reconciled roster.
   2. **Harvest owed reports.** An agent that went idle WITHOUT posting its final report owes one - ping it via `SendMessage` and absorb the reply before shutting it down.
   3. **Send each a shutdown request:** `{"type": "shutdown_request", "reason": "session wrap complete"}`. A healthy agent replies `shutdown_approved` and the harness emits a `teammate_terminated` confirmation for it.
   4. **Verify N/N against the roster, then force-stop stragglers.** Check off each `teammate_terminated` confirmation against the roster. Any agent still unconfirmed once its peers have confirmed (or after ~a minute) gets `TaskStop` with its teammate name as `task_id` - TaskStop resolves teammate names and kills the in-process teammate task deterministically. Do not declare the sweep complete until every rostered agent is confirmed down; report the count ("9/9 teammates down") in the Phase 4 summary.

   Skipping the sweep leaves a fleet of idle agents outliving the closed session (observed 2026-07-01: nine idle teammates lingering hours past their work). Treating "requests sent" as "agents stopped" leaves a partial fleet behind (observed 2026-07-09: 3 of 9 shutdown requests silently stalled - no approval, no termination - and only per-name `TaskStop` cleared them, after the user pointed out the survivors).
4. Active `Monitor` watchers - cancel each.
5. **GUI applications running as session children** (e.g. a Unity Editor or browser launched via a backgrounded shell earlier in the session). These are children of the session process tree: they hold the session open at exit, and closing the session (or stopping their task) kills them - so "keep it open" is NOT a valid sweep outcome for a session-child app. If the user wants the app to survive the wrap, **relaunch it detached first** (Windows: the PowerShell tool's `Start-Process -FilePath <exe> -ArgumentList ...`; POSIX: `setsid`/`nohup ... & disown`), verify the new process is parented outside the session, and only then stop the original task. Observed 2026-07-06: an Editor "kept open" as a session child blocked `/exit` and then died when its task was stopped anyway - the exact both-worlds-lost outcome this item prevents.

Surface the full set (running and recently-completed-but-unharvested) as one question, with per-item context (what it is, how long it has been running or how recently it completed, last output line or final summary). If inspecting any surfaces a new loose thread, loop back and amend the 2a offload batch before terminating. Use the platform's task-stop tool (e.g. `TaskStop`, which currently handles background shells, subagents, AND named teammates uniformly - teammate names work as `task_id`) to terminate tasks; for named teammates, follow item 3's roster-verify-escalate protocol (polite `shutdown_request` first, per-name `TaskStop` for any agent that doesn't confirm). If nothing is running or unharvested, skip silently - per principle 9, no ceremony.

This sweep does *not* terminate the wrap subagents dispatched in Phase 3; those are part of the wrap and finish on their own.

### Phase 3 - Per-repo work

Phase 3 covers per-repo memory offload (3a), plans sweep (3b), hygiene pass (3c), and the per-repo commit/push prompt (3d). The orchestrator does 3a directly across all touched repos. 3b and 3c fan out to per-repo sonnet subagents (with a bucketing cap) *where the harness allows it*. The orchestrator reviews their findings, asks one combined approval question, and either executes inline or dispatches sonnet executors. 3d returns to the orchestrator for the user-facing commit prompt.

**Per-repo independence rule:** if any sub-phase fails partway through a repo, record the failure in the running Phase 4 summary, skip remaining sub-phases for *that* repo (especially never push if commit failed), and continue to the next repo. Do not abort the whole wrap.

**Skip-fan-out option:** If a repo's expected 3b/3c work is trivially small (e.g. one or two files, no plans, no scratch), the orchestrator may skip the subagent dispatch and do 3b/3c inline. Subagent dispatch has fixed first-turn cost; for tiny work it can exceed the savings. Use judgment.

**No-fan-out harnesses.** Some harnesses forbid subagent dispatch outright - a standing instruction from the user or from the harness itself, a permission layer that denies the Agent tool, or a platform with no subagent primitive. Treat it exactly like the skip-fan-out option above: do 3b/3c inline for every repo, with the MUST-load rule below still in force. Don't ask permission to fan out and don't narrate the constraint - fan-out is a context-cost optimization, never a correctness requirement (principle 10).

When taking the inline path, the orchestrator MUST still load the relevant references - `Read references/plan-classification.md` before doing 3b inline, and `Read references/hygiene-checklist.md` before doing 3c inline. The references contain the per-state action tables and the "Common mistakes to avoid" sections that per-repo subagents would otherwise load on their own; skipping the read recreates the conservative-keep drift those sections were added to prevent.

**Junk-files check runs even when `git status` is clean (Phase 3c).** One 3c item is invisible to `git status`: ephemeral build & import artifacts - *junk files* like `node_modules/`, Unity `Library/`, `bin/`+`obj/`, `target/`, `build/`, `dist/`, `__pycache__/`. They are gitignored, so a clean working tree does **not** mean 3c is empty, and "nothing to commit" is **not** "nothing to wrap." If this session generated or refreshed them (ran a build/compile, opened an IDE or the Unity Editor, installed dependencies), Phase 3c must actively scan for them and surface them as a single *keep-or-clear* opt-in finding - default **keep**, but surfaced, not silently skipped. Pre-existing artifacts on a repo the session never built are out of scope (that's `project-maintenance`'s disk audit). Hard exclusions (secrets, local data) and the keep-warm carve-out are in `references/hygiene-checklist.md`.

**3a. Per-repo memory offload (orchestrator, all repos sequentially).**

For each repo in the Phase 1 list, walk the **per-project categories** section of `references/categories.md` and draft candidate items in the orchestrator's main context - project learnings, decisions, AGENTS.md updates, gotchas. This step has no verbose tool output: it is recall-driven drafting against the conversation context already loaded. Subagent isolation buys nothing here, and the nuance cost of fanning it out outweighs the savings.

The 3a drafts are not yet executed or shown to the user. Hold them in working memory; they are combined with 3b/3c findings before the approval question in the per-repo review step below. The drafts are also passed into each subagent's brief as cross-reference material so subagents don't duplicate them.

**3b + 3c. Plans sweep + hygiene pass (per-repo subagents).**

After 3a is complete for all touched repos, dispatch per-repo subagents (model: sonnet) to do 3b and 3c work in their own contexts. Each subagent reads `references/plan-classification.md` and `references/hygiene-checklist.md` on demand - those references are not loaded into the orchestrator's context. The hygiene pass now includes a docs-drift check: for any repo with code changes this session, it reads the relevant doc surfaces and flags stale statements (see `references/hygiene-checklist.md` and the docs-update skill for the per-surface procedure).

**Bucketing.** Cap at 4 subagents to avoid first-turn cache-miss overhead. The most-edited repo (where the bulk of the session's work happened) gets its own subagent. Remaining repos are bucketed by weight; a subagent assigned multiple light repos still wins on cost because it does the verbose tool work in its own context, just sequentially across its assigned repos.

**Brief structure.** The Agent tool's prompt is the only channel from orchestrator to subagent. Load it with session-grounded pointers rather than expecting the subagent to rediscover them. A few sharp pointers beats an exhaustive briefing - too much in the prompt dilutes attention.

For each subagent (per repo or per bucket), the prompt should include:

1. **Why this repo is in scope** - one sentence from the orchestrator's recall, e.g. *"This session refactored the auth middleware and added two new test files; that's why this repo is in the wrap."*
2. **Pre-flagged hotspots** - specific files, plan paths, or directories the orchestrator already half-noticed and wants the subagent to look at first, e.g. *"Pay particular attention to `plans/auth-rewrite.md` (likely completed this session), the untracked `notes/scratch-2.md` (looks like loose-thread material), and check whether `AGENTS.md` mentions the deprecated `validateSession` helper - we removed it."* This is the "leading content" that converts the subagent from "explore cold" to "verify these specific suspicions and surface anything else nearby."
3. **3a drafts already produced for this repo** - so the subagent can cross-reference and not duplicate, e.g. *"The orchestrator has already drafted these per-project memory items: [list]. If your 3b/3c findings overlap, flag the duplication rather than re-drafting."*
4. **What to do** - *"Follow `references/plan-classification.md` for 3b and `references/hygiene-checklist.md` for 3c. Return findings (not actions) - the orchestrator will assemble the user-approval batch and dispatch executors after approval."*
5. **Return schema** - match `references/finding-schema.md`. Also include a short repo-level summary fragment (commits expected, plans found by state, hygiene findings count) for Phase 4 to stitch into the final summary.

**Review and combine.** When subagents return, the orchestrator reviews each subagent's findings against its own knowledge of the session. This is the natural choke point where opus's judgment earns its keep:

- *"Did the subagent miss something I noticed during the session?"* - if yes, add it.
- *"Is this finding actually worth surfacing, or is it noise?"* - drop noise.
- *"Does this classification feel right given how the session actually went?"* - override if not.

If a subagent's findings feel thin, generic, or wrong, the orchestrator may bypass them entirely (principle 10): read the repo directly, do 3b/3c inline for that repo, and produce its own findings. This is a first-class option, not an emergency escape.

After review, combine 3a drafts + reviewed 3b/3c findings into one approval question per repo (or one covering several repos if total volume is small). Get approval.

**Execution.** After approval, execution can stay in the orchestrator (small/single-repo cases) or fan back out to sonnet executor subagents (large or multi-repo cases). Executors receive the approved findings + their `action_on_approval` strings, and report what they actually did. Auto-commit (commit #1 in 3d) happens in the repo where the writes landed, regardless of who executed them.

Critical: destructive actions in 3c gate on 3a + 3b having completed successfully for this repo. If memory offload or plans sweep failed or was cancelled, skip 3c's destructive items too (still show the read-only summary in the final report).

**3d. Commit + push decision (orchestrator).**

This sub-phase produces **two separate commits** (at most) per repo, in this order: first wrap's own edits auto-commit, then the user-work prompt runs. Never combine them - they must be distinguishable in git history.

**Wrap's own edits (commit #1, automatic).** Everything wrap wrote during 2, 3a, 3b, 3c (memory updates, AGENTS.md edits, archived plans, deleted scratch) auto-commits in one commit per repo with this message format:

```text
chore: wrap session hygiene

- <one bullet per category of change, e.g. "Archived 2 completed plans">
- <e.g. "Updated AGENTS.md with 3 new project facts">

Wrap-Session-Id: <current session id if known, else a timestamp>
```

The `Wrap-Session-Id:` trailer lets future tooling distinguish wrap commits from user work.

**User work (commit #2, prompted).** Uncommitted changes that existed *before* wrap started. After wrap's own commit lands, show `git status` + `git log @{u}..HEAD` and ask the user per repo:

```text
**l** - leave as-is: change nothing (the default)
**c** - commit only: commit locally, leave unpushed
**p** - push: commit the changes, then push
```

Describe each option against the *actual* repo state - name the files and the commit count - rather than repeating the generic labels.

Rules for this prompt:

- **Exactly these three options**, through principle 8's channel: structured-tool options with leave-as-is first and "(Recommended)", or lettered prose choices with the token outside the word. Do not drop one as inapplicable, and do not add more. Stash and branch-off were removed deliberately (2026-08-05): parking or forking uncommitted work is a *working* decision, not a *closing* one - a user who wants either can say so in a free-form answer, and the agent honors it.
- **The default is `l` - change nothing.** This is the one gate where the default must be inert: everything else in wrap is wrap's own work, but this is the user's. If two answers in a row don't map to an option, take `l`, say so in one line, and move on - never fall through to a commit or a push.
- Never pick an option for the user *silently*. The stated default fires only after one clarifying re-ask or a dismissed structured question (principle 8), and firing it is always announced.
- Never push without the explicit `p` choice.
- Never force-push. If the push is rejected as non-fast-forward, report "push rejected, commits stay local" and continue.
- If there is no upstream, `p` degrades to `c` for that repo; inform the user in the option's description rather than omitting it.

### Phase 4 - Session summary

Always runs, even on cancel or abort. Subagents return short repo-level summary fragments as part of their Phase 3 output (commits made, plans closed, hygiene findings, leftovers per repo); the orchestrator stitches the fragments together and adds the cross-repo narrative no individual subagent has the context to write - the session's overall arc, what's still hanging across repos, what feels worth flagging for next time.

The summary covers:

- **Accomplishments per repo:** commits made this session, files touched, plans closed, loose threads captured. (Subagent fragments slot in here.)
- **Memory offload totals:** how many entries written, to which destinations (grouped by memory type).
- **Session-wide cleanup:** background shells killed, subagents stopped, monitors cancelled (counts + one line each). Omit the bullet entirely if 2b found nothing.
- **Rejected or flagged:** anything the agent surfaced that the user declined, and anything explicitly flagged as needing human judgment.
- **Leftovers:** per-repo, what is still dirty, unpushed, or in-progress after the wrap. Naming each explicitly so the user can decide whether to come back to it.

Spot-check before publishing: cross-reference subagent fragments against `git log` and the actual state on disk. Subagents occasionally over-claim what they accomplished; an opus pass to verify "did the subagent actually do what it reported?" is part of the summary's quality. If a discrepancy turns up, correct the summary and note the discrepancy.

Keep the summary terse - specific numbers, specific paths, specific decisions. No filler.

**Empty case:** If Phases 0–3 found nothing (clean state, idempotent re-run, or genuinely-quiet session), the entire summary is one or two lines: *"Nothing to wrap. \<repo names\> are clean, no memory items to offload, no background processes running."* Do not pad with bullet points for empty categories. Per principle 9, the empty path is a valid pass - emit it directly and exit.

**Chain-mode closing lines.** After following `references/chain.md`, name the confirmed successor and give `claude attach <shortid>` (or `claude agents` for agent view) immediately before the sentinel. If launch failed or could not be confirmed, say so plainly, keep the handoff, and give the exact filled launch command to run by hand. If status or the 10-link cap stopped the chain, state that reason instead. An interrupted wrap follows the cancellation path without launching a successor.

**Closing sentinel (mandatory, every path).** The very last line of the Phase 4 summary MUST be a sentinel marker. Which sentinel depends on whether the wrap ran to its natural end or was cancelled/interrupted partway:

- **Completed wrap** (normal, empty, or proceeded through all phases despite per-repo failures):

  > That's a /wrap. Go ahead and close the session.

- **Cancelled or interrupted wrap** (user stopped the wrap mid-procedure, refused a critical approval question, or the wrap aborted before reaching Phase 4 on its own):

  > That was an interrupted /wrap. The session is NOT in a clean wrap state - some items may still be dirty, uncommitted, or unsaved.

The two sentinels are distinct on purpose: the "go ahead and close" line is the user's signal that the wrap procedure ran to its end. An interrupted wrap must **NOT** emit that line - it would falsely tell the user the session is safely closeable when it isn't. The interrupted sentinel makes the partial state explicit instead. No variations, no embellishments, no emoji on either. Pick one and only one; both are session-end markers so the transcript shows what actually happened.

## Failure handling

- **Phase independence:** failure in phase N leaves phases 1..N-1 intact and continues to phase N+1. Phase 4's summary records what completed and what didn't.
- **Per-repo independence inside Phase 3:** repo-level failures are logged and wrap moves to the next repo.
- **Subagent failure / timeout:** treat as "no findings for this bucket." The orchestrator may fall back to doing 3b/3c directly for the affected repos (principle 10), or skip with a note in the Phase 4 summary. Never silently lose a repo from the wrap.
- **Subagent over-claim:** if Phase 4's spot-check finds a subagent reported a commit / write / deletion that didn't actually happen, correct the summary and execute the missing action inline if still appropriate.
- **Destructive-action gate:** deletes and archives run only after memory offload succeeds for that repo.
- **User cancel (`Ctrl+C` / stop / a refused approval question):** whatever was already approved + executed stays done. Print a "cancelled - completed: X / pending: Y" summary immediately, ending with the **interrupted sentinel** (see Phase 4) - never the "go ahead and close" line. Cancellation also stops any in-flight subagents - wrap does not leave wrap-spawned subagents running after the user cancels.
- **Git errors:**
  - Merge conflict on wrap's auto-commit → stash wrap's edits, leave user work alone, record the conflict in the summary.
  - Non-fast-forward push rejection → never force-push; report and continue.
  - No upstream → treat as "commit only, no push" and continue.
- **Untracked deletions** - always per-item approval. Each approval logged in the summary with the full path. Rejections logged with the reason.
- **Idempotent re-run** - running `/wrap` twice in a row is safe. Second run finds nothing unless new state appeared between runs.

## References

- `references/chain.md` - chain handoff contract, fixed resume prompt, launch confirmation and failure handling.
- `references/categories.md` - memory-offload category checklist for Phases 2 and 3a.
- `references/plan-classification.md` - plan-file classifier + the extract-loose-threads-first safety rule for Phase 3b. Loaded by the per-repo subagent that handles 3b, not by the orchestrator.
- `references/hygiene-checklist.md` - Phase 3c items with research notes per check. Loaded by the per-repo subagent that handles 3c.
- `references/finding-schema.md` - the shape of a finding and of the summary's action log (copied from `project-maintenance`, divergence OK). Loaded by both orchestrator and subagents.
- `references/session-end-reminder.md` - spec for the decoupled `SessionEnd` nudge hook. Wrap does not read or touch the hook's marker file; it is a separate system.

## Companion scripts

User-facing diagnostic utilities shipped alongside the skill, scanning the agent's session transcripts, overridable via the `AGENTS_SESSIONS_DIR` env var. Not invoked during the wrap procedure itself.

- `scripts/find-unwrapped.sh` (bash) and `scripts/find-unwrapped.ps1` (PowerShell) - list recent agent sessions that did NOT end with `/wrap`. Useful for recovering after a crash, a culled agent process, or just answering *"did I leave anything dangling?"*. They apply default recency, size, and scratch-project filters; each script's own help documents those defaults, the reasoning behind them, and how to override them. Run with `--help` (bash) or `Get-Help` (PS).
