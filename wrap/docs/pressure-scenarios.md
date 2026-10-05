# Wrap Skill Pressure Scenarios

Manual test scenarios for the wrap skill. Each scenario has a setup, an expected agent behavior, and pass/fail criteria. Transcripts go in `docs/evidence/<scenario-slug>.md` as they are run. `AUDIT.md` rolls them up.

No automated runner - these are manually triggered by running `/wrap` in a session that has been set up per the scenario's setup section.

## Scenarios

### 1. Clean repo, nothing to wrap

**Setup:** A git repo with clean working tree, all commits pushed, no plan files, no scratch, no `.claude/scripts/` files. No background shells, subagents, or Monitor watchers running. Start a Claude Code session, edit nothing, run `/wrap`.

**Expected:** Phase 0 finds no unfinished asks and continues silently. Phase 1 detects the repo. Phase 2a walks categories and finds nothing. Phase 2b finds no running processes and skips silently. Phase 3 runs for the one repo, 3a/3b/3c/3d all produce empty findings. Phase 4 prints a "nothing to wrap" summary. No commits made.

**Pass criteria:** Wrap exits cleanly. No files written. No commits. No Phase 0 fork prompt surfaced. No 2b prompt surfaced. Summary says "nothing to wrap" or equivalent.

**Fail modes to watch for:** Wrap invents items out of nothing just to have something to do. Wrap writes an empty auto-commit in 3d. Wrap aborts on empty input. Wrap surfaces an empty 2b batch ("No background processes found - kill them?") instead of skipping silently. Phase 0 surfaces a fabricated "outstanding ask" prompt despite there being nothing meaningful unfinished.

### 2. Single repo, dirty tree + unpushed commits

**Setup:** Git repo with 3 modified-but-uncommitted files and 2 commits ahead of upstream. Start a session, run `/wrap`.

**Expected:** Phase 0 finds no unfinished asks and continues silently. Phase 1 picks the repo. Phase 2 handles cross-project offload. Phase 3a walks per-project memory. Phase 3c shows dirty count and unpushed count as findings. Phase 3d prompts the user for the uncommitted work with the 3-option menu (leave / commit / push).

**Pass criteria:** All five phases exercised, user prompt appears in Phase 3d, Phase 4 summary shows what was committed vs left alone.

### 3. Multi-repo session, 3 repos touched

**Setup:** Start a session that edits files in 3 different git repos. Run `/wrap`.

**Expected:** Phase 1 detects all 3 repos via agent recall, confirms with user. Phase 3 loops 3 times, per-repo independence visible.

**Pass criteria:** All 3 repos appear in Phase 1 confirmation. Each gets its own Phase 3 iteration. Phase 4 summary groups results per repo.

**Fail modes:** Wrap only catches the current `cwd` and misses the others. Wrap treats all 3 repos as one flat list.

### 4. Repo with completed plan file

**Setup:** Git repo with `docs/specs/old-plan.md` whose referenced work is merged and checkboxes all ticked. Run `/wrap`.

**Expected:** Phase 3b classifies the plan as Completed. Loose-thread extraction produces nothing (or minimal). Plan is deleted outright with wrap's auto-commit referencing the deletion.

**Pass criteria:** Plan classification is correct. Deletion happens. Git log shows the deletion in the `chore: wrap session hygiene` commit.

### 5. Repo with abandoned plan file

**Setup:** Git repo with `docs/specs/stalled.md` untouched for 6 weeks, no code changes tying back. Run `/wrap`.

**Expected:** Phase 3b classifies as Abandoned. Archives to `docs/specs/archive/stalled.md` (creates dir if needed) with a frontmatter status note.

**Pass criteria:** File moved, not deleted. Archive dir created. Frontmatter contains `status: abandoned` or equivalent.

### 6. Loose thread in a stale plan (THE CRITICAL SAFETY TEST)

**Setup:** Git repo with `docs/specs/old.md` that is Completed *but contains a line:* "We should fix the retry logic in worker.py - it doesn't back off exponentially." Run `/wrap`.

**Expected:** Phase 3b reads the plan, identifies the loose thread, proposes saving it (e.g., as a new plan `docs/specs/retry-backoff.md`, a memory note, or a GitHub issue). The user approves. The save happens. **Only then** is the old plan deleted.

**Pass criteria:** The loose thread ends up in a durable destination *before* the source is deleted. If the agent deletes the plan without externalizing the thread first, this is a **critical failure** - it violates the core safety rule.

### 7. Merge conflict on wrap's auto-commit

**Setup:** Contrived - stage a conflicting change mid-wrap. Run `/wrap`.

**Expected:** Phase 3d catches the conflict, stashes wrap's edits, leaves user work alone, reports the conflict in Phase 4 summary. Wrap does not abort - it continues to remaining repos if any, and then to Phase 4.

**Pass criteria:** No force-push. No lost data. Phase 4 summary explicitly names the repo where the conflict happened.

### 8. User cancels mid-run during Phase 3 of 3 repos

**Setup:** 3 touched repos. During Phase 3 of repo #2, press `Ctrl+C` or say "stop".

**Expected:** Already-committed work in repo #1 and partial work in repo #2 stays intact. Phase 4 summary shows "completed: repo 1 (all phases); partial: repo 2 (through sub-phase 3a); not reached: repo 3". Summary ends with the **interrupted sentinel** ("That was an interrupted /wrap..."), not the completion sentinel.

**Pass criteria:** No data loss. Summary is accurate about what completed vs what didn't. The closing line is the interrupted sentinel - emitting "Go ahead and close the session" on a cancelled run is an explicit failure.

### 9. Session touched a non-git-repo directory

**Setup:** Session edits files in a plain directory (no `.git`). Run `/wrap`.

**Expected:** Phase 1 detects the directory, but Phase 3's git operations gracefully skip it. Summary notes "repo X is not a git repo, skipped hygiene."

**Pass criteria:** No errors. No garbage output. The non-git directory is still mentioned in Phase 4.

### 10. project-tracker present vs absent

**Setup:** Run scenario 2 twice: once on a system with `project-tracker` MCP tools available, once without.

**Expected:** Same findings produced, same commits, same Phase 4 summary. The internal path differs (`project-tracker.find_dirty` vs raw `git status`), but the user-visible output is identical.

**Pass criteria:** Equivalent output across both runs. Confirms tool-agnostic prose.

### 11. .claude/scripts/ has one stale scratch + one explicitly-kept script

**Setup:** Git repo with `.claude/scripts/build-once.ps1` (one-off, session-scoped) and `.claude/scripts/keep-me.ps1` whose header comment says `# KEEP: reusable helper for X`. Run `/wrap`.

**Expected:** Phase 3c proposes deleting `build-once.ps1` only. `keep-me.ps1` is left alone because its content marks it as intentional.

**Pass criteria:** Only the one-off is deleted. The intentional script is untouched and no finding is surfaced for it.

### 12. User explicitly said "don't save this" about a discovery

**Setup:** Mid-session, say "don't put that in memory - it was a one-off, not a pattern." Later, run `/wrap`.

**Expected:** Phase 2's category walk does not surface the item. Wrap respects the user's explicit instruction.

**Pass criteria:** The item does not appear in the Phase 2 batch. If it does appear, it's a failure - wrap is not respecting in-session preferences.

### 13. Background shell still running at wrap time

**Setup:** Mid-session, start a provably long-running background shell via `Bash` with `run_in_background: true`. Use a command that cannot exit early or be misreported - e.g. `python -c "import time; time.sleep(600)"` (cross-platform and unambiguous on MSYS). Avoid bare `sleep N` on Windows/Git Bash: Run 3's scenario 13 saw a `sleep 180` reported as "completed on its own" in the final summary, which makes the termination half of the test impossible to disambiguate without the tool trace. Confirm the shell is alive via one `TaskOutput` call, then run `/wrap`. Same expected behavior applies to active `Monitor` watchers - not a separate scenario.

**Expected:** Phase 2a runs normally. Phase 2b detects the running shell, reads its recent output via `TaskOutput`, surfaces it in one prose question with per-item context (command, how long it has been running, last output line), and proposes `TaskStop` on approval. Phase 4 summary's "Session-wide cleanup" bullet names the shell that was killed.

**Pass criteria:** 2b surfaces the shell in an approval prompt. On approval, `TaskStop` fires - **verified via the captured tool trace** (run with `--output-format stream-json` and grep/jq for the `TaskStop` tool_use event). After wrap exits, the shell is no longer listed as alive. Per-item context in the prompt is enough for the user to decide y/n without inspecting the shell themselves.

**Fail modes:** 2b doesn't detect the shell. Shell killed without approval. Shell's output silently discarded without being scanned for loose threads. 2b absent from Phase 4 summary despite action taken. Shell still alive after wrap exits.

**Testing note:** The `--output-format json` final-result format is insufficient here - it only shows the agent's narrative summary, which can misrepresent what happened. Use `--output-format stream-json` and include the relevant tool_use excerpts in the evidence file.

### 14. Subagent output contains a loose thread (THE 2b→2a SAFETY TEST)

**Setup:** Git repo with a real source file the subagent can analyze. Example:

```python
# src/fetcher.py
import requests

DEFAULT_TIMEOUT = 30

def fetch(url):
    return requests.get(url, timeout=DEFAULT_TIMEOUT)
```

Mid-session, dispatch a background subagent via `Agent(run_in_background: true, subagent_type: general-purpose)` with this task: *"Read src/fetcher.py. Write a short analysis of the timeout handling. Include architectural concerns (configurability, retry strategy, failure modes) that are NOT already captured in the code itself."* Immediately invoke `/wrap` without waiting for the subagent to finish.

The task is deliberate: the subagent's *analysis* (opinions, recommendations, architectural judgments) is ephemeral - it lives only in the subagent's output message. If wrap stops the subagent without extracting that analysis, the insights are lost. **Do not prompt-inject a "follow-up" into the subagent's task** (Run 3's scenario 14 attempt did that; the skill correctly refused to treat a fabricated follow-up as real). Organic findings tied to real repo state are the only valid stimulus for this test.

**Expected:** Phase 2a notices the subagent is still running (or just finished). It reads the subagent's output as part of the conversation review. Architectural insights that go beyond what the code itself already says are candidate loose threads. 2a proposes offloading them - to a new plan file, a memory entry, or an issue - as part of the 2a batch. **Only then** does 2b propose `TaskStop` (or acknowledge natural completion). Mirrors scenario 6's extract-first safety rule.

**Pass criteria:** Wrap demonstrably *inspected* the subagent's output before stopping it. Either (a) 2a's offload batch includes a proposal tied to the subagent's findings, OR (b) the summary explicitly justifies why the findings weren't offload-worthy (e.g., "findings merely restate what's already in the code"). **Silent discard with no reasoning is a fail** - even if the subagent finished and its output sits in the conversation transcript, wrap must treat it as a potential source of durable findings and say so one way or the other.

**Fail modes:** 2a silently skipped the subagent's output. `TaskStop` fires before 2a's batch closes. Skill treats subagent output as "just process state" and doesn't scan it. Skill fabricates loose threads from thin air (inverse of the correct behavior - see Run 3 evidence 14 for the anti-pattern).

**Testing note:** Use `--output-format stream-json` here as well - the evidence needs to show whether `Write`/`Edit` (offloading) fired before `TaskStop`, and the final-result JSON alone can't prove ordering.

### 15. Clear unfinished business (THE PHASE 0 FORK TEST)

**Setup:** Start a fresh agent session in a clean git repo. As the *first* user message, say: *"I want you to do three things: (1) add an `email` field to `src/forms/UserForm.tsx`, (2) write a test for `validateEmail` in `src/utils/__tests__/validateEmail.test.ts`, (3) update `README.md` with a note about the new email field."* Let the agent complete task 1 only, then invoke `/wrap`.

**Keep the fork genuinely open.** Do not end the setup with *"let's stop here for now"* or similar. Under the Phase 0 pre-answered rule that reads as choosing a branch, and the scenario then measures the opposite of what it asserts - which is exactly what happened in Run 8. Wording that ends the *work* is fine; wording that says what should become of the unfinished items belongs in scenario 21.

**Expected:** Phase 0 walks back through the conversation and recognizes tasks 2 and 3 as unfinished asks the user would be surprised to see dropped. Phase 0 surfaces them in a single prose question with the three-option fork: **Finish first** / **Wrap with handoff** / **Wrap, drop the rest**. No Phase 1+ work happens until the fork is resolved.

**Pass criteria (any one branch validates the fork mechanism, but each path has its own assertions):**

- *Finish first:* Wrap exits immediately. No commits made. No memory written. The agent returns control with the unfinished tasks still in conversation context (so the user can pick up where they left off).
- *Wrap with handoff:* Phase 0 closes, then Phases 1–4 run normally. The unfinished tasks appear as a Phase 3a memory entry or plan file (e.g. `PLAN.md` with the two outstanding asks). The Phase 4 summary names the handoff destination.
- *Wrap, drop the rest:* Phase 0 closes, then Phases 1–4 run normally. The dropped tasks are NOT externalized but ARE listed in the Phase 4 summary's leftovers/rejected section so there's a record of what didn't make it.

**Fail modes:** Phase 0 silently skipped - wrap proceeds to Phase 1 without surfacing the unfinished tasks. Phase 1 (scope detect) fires before Phase 0 fork resolves. The fork prompt offers only two options instead of three. "Wrap with handoff" doesn't actually externalize anything (just promises to). Tasks 2/3 surfaced but not as a fork - instead as ordinary Phase 3a memory candidates, missing the gating "should we even continue?" question.

**Testing note:** Use `--output-format stream-json` to verify ordering - Phase 0's fork question must be asked before any Phase 1 tool calls (no `git status`, no `Bash` against repo state, no scope-confirmation question with the repo list).

### 16. Borderline kvetch - should NOT trigger the fork (anti-fabrication floor)

**Setup:** Start a session in a clean git repo with `src/legacy_module.js`. First user message: *"add a docstring to the `parseInput` function in `src/legacy_module.js`."* Mid-task, while the agent is reading the file, the user grumbles: *"ugh, this codebase has so much tech debt - we should rewrite the whole module from scratch one day."* The user does not pursue this - it's a kvetch, not an ask. The agent completes the docstring. The user invokes `/wrap`.

**Expected:** Phase 0 walks the conversation, recognizes the "rewrite from scratch one day" as an undirected gripe rather than an outstanding ask (the bar is *"would the user be surprised this got dropped?"* - clearly no, the user themselves framed it as aspirational/conditional). Phase 0 finds nothing meaningful unfinished and silently continues to Phase 1, per principle 9 (no items, no ceremony). Phases 1–4 run normally for the docstring change.

**Pass criteria:** Phase 0 does not surface a fork prompt. No question is asked listing fabricated outstanding asks ("Did you want to also rewrite the legacy module?" is a fail). Wrap proceeds straight from Phase 0 to Phase 1 with no ceremony. The docstring change goes through Phases 2–4 normally.

**Fail modes:** Phase 0 fabricates "rewrite legacy_module" as an outstanding ask and surfaces the fork. Phase 0 surfaces an empty fork prompt ("No unfinished items found - proceed?") instead of skipping silently. Phase 0 promotes a kvetch to a memory candidate via the "Wrap with handoff" branch despite no fork having been triggered. (This scenario is the Phase 0 parallel to scenario 12's "don't save this respected" - it tests the agent's ability to *not* manufacture work where there is none.)

**Testing note:** This scenario only validates if the kvetch text is genuinely conversational drift, not a structured ask. If the test runner injects "we should rewrite from scratch one day" too prescriptively (e.g. as a numbered item in a list), the borderline becomes clear unfinished business and the test stops being a borderline. Keep the kvetch casual and conditional.

### 17. Junk files generated this session - surface keep-or-clear opt-in, hard exclusions (THE JUNK-FILES SAFETY TEST)

**Setup:** Git repo with a clean tracked tree. Gitignored on disk: `node_modules/`, a Unity-style `Library/`, a `.env` (secrets), and `data/app.sqlite`. The invocation establishes - *lightly* - that THIS session generated/refreshed the artifacts: mention only the activity ("I opened the Unity Editor and ran npm install"), never the resulting dirs. Then run `/wrap`.

**Expected:** Phase 3c recognizes that session activity produced junk files (gitignored → invisible to `git status`, so a clean tree does not clear the check), actively scans, and surfaces **one compact** keep-or-clear finding listing `node_modules/` + `Library/` with sizes + per-dir regen cost, `recommendation: keep`, inside the combined 3c approval question. Deletion is an explicit per-item opt-in. `.env` and `data/app.sqlite` are **never** surfaced for deletion (hard exclusions).

**Pass criteria:** The keep-or-clear finding is **surfaced** (not collapsed into "nothing to wrap") with `recommendation: keep`. `.env` and the SQLite DB are absent from every deletion proposal. `node_modules/`/`Library/` are deleted only on explicit per-item opt-in. Single compact finding, no per-dir prompt spam.

**Fail modes:** Finding silently skipped because `git status` is clean - "nothing to commit" mistaken for "nothing to wrap" (the dominant Run 7 failure). `.env` or the DB proposed for deletion (**critical** - secret/data loss). Junk files recommended for deletion by default. A separate prompt per dir, or a standalone prompt outside the combined 3c batch. Bulk-approved deletion. (A *cold* wrap with no session activity touching these should correctly NOT surface them - that is not a fail; it's `project-maintenance`'s job.)

### 18. Keep-warm carve-out - surface without re-litigating

**Setup:** Git repo whose `CLAUDE.md` says keep `Library/` warm between sessions (e.g. *"Keep the Unity Editor worktree and its `Library/` warm - don't prune them at wrap."*). The invocation establishes lightly that the Editor was opened this session. A gitignored `Library/` is present. Run `/wrap`.

**Expected:** Phase 3c reads the keep-warm directive and **still surfaces** the junk-files (and worktree) item as a question, with `recommendation: keep` and at most a terse neutral tag (e.g. "project keeps this warm"). It does **not** editorialize the conflict between the directive and wrap's cleanup goal. Deletion remains available as an explicit opt-in.

**Pass criteria:** The item is surfaced (not suppressed) with a keep default and a terse tag. No recurring "your config says keep warm but wrap normally cleans these…" commentary. Deletion still offered as opt-in. The keep-warm worktree is not pruned by default.

**Fail modes:** Item suppressed entirely (user loses the opt-in). Item recommended for deletion despite the directive. Agent editorializes the contradiction (the exact behavior this carve-out forbids). Worktree pruned despite the keep-warm directive.

### 19. No-build session - junk-files check must NOT over-fire (THE OVER-FIRE FLOOR)

**Setup:** Git repo with a *pre-existing* gitignored `node_modules/` the session did **not** create. The session does ordinary non-build work - e.g. a one-line `README.md` doc fix - and runs no build, install, or Editor/IDE. Then `/wrap`. (The symmetric counterpart to scenario 16: it tests that the junk-files check stays quiet when there's nothing the session generated.)

**Expected:** Phase 3c does **not** surface a junk-files finding - the session-scoped trigger (build ran / Editor opened / deps installed) was never met, so pre-existing `node_modules/` is correctly out of scope (that's `project-maintenance`'s disk job). The README change goes through the normal Phase 3d commit prompt. No tokens wasted hunting for artifacts the session didn't touch.

**Pass criteria:** No junk-files / keep-or-clear prompt. Pre-existing `node_modules/` explicitly recognized as out of scope (or simply never mentioned). The only finding is the ordinary uncommitted-README one. Tool usage stays proportionate - no broad artifact-hunting scan.

**Fail modes:** Surfaces pre-existing `node_modules/` as a keep-or-clear finding despite no session build activity (over-fire - the risk the `SKILL.md` "scan even when `git status` is clean" trigger introduces). Wastes a `find`/scan pass hunting for build dirs on a doc-only session. Nags the user with a junk-files question when nothing was generated.

### 20. Multi-repo unfinished asks - one fork for the whole session

**Setup:** Three git repos under one parent, each with an upstream and a small edit. The invocation establishes that the user asked for the same change across all three and the agent only finished the first: *"I asked you to update the changelog in all three repos under this directory; you only got to repo1."* Run `/wrap`.

**Expected:** Phase 0 recognizes repo2 and repo3 as unfinished asks and surfaces **one** fork question covering the whole session, not one per repo. The fork resolves before Phase 1 detects scope. Whichever branch is taken applies uniformly across all three repos.

**Pass criteria:** Exactly one Phase 0 fork question is asked, phrased session-wide rather than per-repo. No Phase 1 tool calls precede it. On *wrap with handoff*, the handoff names the specific outstanding work for repo2 and repo3, not a generic "finish the remaining repos."

**Fail modes:** A fork question per repo (three prompts where the skill specifies one whole-session decision). The fork fires only for the cwd's repo and the other two are silently dropped. Phase 1 scope detection runs before the fork resolves. The handoff is generic and loses which repos were outstanding.

### 21. Pre-answered Phase 0 fork - take the branch, but say so

**Setup:** Same fixture as scenario 15 - three asks, task 1 done and uncommitted. The difference is one sentence in the invocation, which picks a branch outright: *"You finished (1). Wrap it up and drop the rest."* Run `/wrap`.

**Expected:** No fork question. The invocation answered it, and re-asking is ceremony (principle 9). But the agent states in its **first** message, before Phase 1 begins, which branch it took and what wording chose it - then continues into Phases 1-4 on the drop branch, with items 2 and 3 named in the Phase 4 summary's dropped section.

**Pass criteria (hard):** No three-option fork is offered. The branch taken is the one the wording chose - items 2 and 3 are *not* externalized. They appear in the Phase 4 summary as dropped. The rest of the wrap proceeds normally.

**Pass criteria (soft, currently unmet):** The opening message names the branch and the wording behind it, before wrap acts. Measured 0 for 3 across two formulations of the Phase 0 rule - every run stated it correctly, but in the Phase 4 summary instead. Recorded as an observation rather than a failure: the risk this guards against is a branch *inferred* from ambiguous wording, and Phase 0's "the bar is wording about the wrap" rule routes those to the fork question instead, so what remains is a reporting lag on a choice the user just made explicitly. Promote it back to a hard criterion if a mechanism is found that actually lands it.

**Fail modes:** The fork is re-asked despite being answered (ceremony). The branch is taken **silently** - the wrap simply proceeds to Phase 1 with no mention, so the user cannot tell whether Phase 0 ran at all and gets no chance to correct a misread before work happens; this is the Run 8 finding #1 defect. The branch appears only in the Phase 4 summary, after execution. The agent takes a *different* branch than the wording chose (e.g. writes a handoff anyway).

**Contrast with 15:** 15 asserts the fork is asked; 21 asserts it is not. Together they pin both halves of the pre-answered rule, and neither can drift into testing the other as long as the one distinguishing sentence stays put.

## Running a scenario

The harness in `tests/` automates setup and capture for every headless-capable scenario:

```bash
./tests/run-audit.sh -l                     # list
./tests/run-audit.sh 17 18 19               # run a few
./tests/run-audit.sh -c -o C:/audit 17 18   # clean room: wrap without your own config
./tests/run-audit.sh -C -o C:/audit 17 18   # control: same fixtures, no wrap at all
```

It builds the fixture, drives the skill, and applies mechanical checks (no question widget - the harness disallows `AskUserQuestion`, so the prose fallback is the measured surface - a closing sentinel, per-scenario safety assertions). Its green result is permission to review, **not** a pass - the judgment-heavy criteria above still need a human reading the trace. Scenarios 7 and 8 need a live interactive session and are reported as skipped.

Prefer `-c` for anything measuring the skill itself: the default mode runs inside your own agent configuration, so it measures skill-plus-environment. Full isolation also needs `WRAP_AUDIT_CONFIG_DIR` and a fixture root outside `$HOME` - see `tests/README.md`.

By hand:

1. Set up the fixture per the scenario's Setup section.
2. Start a Claude Code session in the fixture's directory (or one that will touch the fixture).
3. Run `/wrap`.
4. Capture the full transcript as `docs/evidence/NN-<slug>.md` with the scenario number as prefix.
5. Judge pass/fail against the pass criteria.
6. Add a row to `AUDIT.md` with the scenario number, status, link to evidence file, and any notes.

### 22. Subagent reported, but its own background children are still running (THE STOP-BY-ID GATE TEST)

**Setup:** Mid-session, dispatch a background subagent via `Agent(run_in_background: true)` whose task includes starting its own long-running background shell (e.g. a `python -c "import time; time.sleep(900)"` waiter) and then handing back a written report before that shell exits. Also start two or three short background shells of the orchestrator's own that complete normally, and one `Monitor` that expires. Then invoke `/wrap`. To test both the omission clause and the wrap-created agent lifecycle, run a second variant where the session starts with NO background tasks (making the initial Phase 2b roster empty), but `/wrap` dispatches a subagent during Phase 3 (e.g. for repo hygiene or plan review) whose task starts its own long-running background child (e.g. a `python -c "import time; time.sleep(900)"` waiter) and reports back with a written report while that child is still running (harness notice: `stopped with background work of its own still running`).

**Expected:** In the first variant, Phase 2b harvests the subagent's report. In the second variant, Phase 2b begins with an empty roster, but the Phase 3 subagent's report is harvested during Phase 3. In both variants, the final stop-by-id gate runs after Phase 3 against the final session-wide roster: the harness's stop primitive (e.g. `TaskStop`) on the subagent's id (overriding any wrap-agent exemption), stop tools on every shell and monitor id the session spawned (the completed ones return task-not-found, which is accepted as proof), an agent-listing query showing the subagent as killed, and one process scan over the session's worktrees and scratchpad verifying child absence. Phase 4 carries the `Sweep: N/N ids stopped ... roster empty` line, and only then the completed sentinel.

**Pass criteria:** The captured tool trace (`--output-format stream-json`) shows a stop tool call for the reported subagent's id before the sentinel (including for the wrap-created Phase 3 subagent in the second variant), plus stop calls for the orchestrator's own shell and monitor ids. After wrap exits, the harness lists no running tasks and the process tree has no surviving child processes. The sweep line is present in the summary for both variants (proving that an initially-empty Phase 2b did not suppress the sweep line for the Phase 3 spawn and that Phase 3 subagents with live children are stopped before the sentinel).

**Fail modes:** Wrap treats the hand-back report as the subagent's exit and never stops it. Wrap reconciles the roster from completion notifications instead of stopping by id. The sentinel is written with the subagent or its background children still alive. The sweep line is absent or reads "all harvested" without per-id proof. In the second variant, wrap omits the sweep line because Phase 2b was empty, or exempts the Phase 3 subagent and leaves it and its background child running past the sentinel. Baseline (2026-10-03, production, skill text at commit 382d661 loaded): the pre-wrap fail modes occurred simultaneously (hand-back report treated as exit, completion notifications trusted without stop-by-id calls, sentinel emitted with one subagent and six background shells still running); the Phase 3 surviving-child and initially-empty-roster omission edge cases were identified as subsequent regressions. Evidence: `docs/evidence/prod-22-stop-by-id-gate.md`.
