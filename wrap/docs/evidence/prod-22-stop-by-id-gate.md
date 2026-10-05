# Scenario 22 - Subagent reported, its own background children still running (THE STOP-BY-ID GATE TEST)

## Variant 1: Pre-wrap subagent reported, background children still running (2026-10-03 baseline - RED)

**Date:** 2026-10-03 (evening, llamabox)
**Skill version:** commit `382d661` (the Phase 2b text already said "build the roster from the harness" and "confirm each one is actually stopped"; two corpus notes, `gotcha_subagent_background_shells_survive_wrap` and `gotcha_subagent_background_shells_outlive_the_lane`, already described this failure)
**Run mode:** interactive Claude Code session, auto mode, user away; `/wrap` invoked by standing instruction

### What the session had spawned

Five `Agent` lanes (four reported and exited; one, a salvage lane, handed back its report while its own preflight waiters were still running - the harness notice read `stopped with background work of its own still running`), nine `run_in_background` shells (all reported completed), three `Monitor` watchers (all expired).

### What the wrap did (RED)

Phase 2b was reconciled from recall and completion notifications. No `TaskStop` was called on any id. The Phase 4 summary read "5 background waiters and 1 kimi lane completed and harvested; 3 monitors expired; 5 Agent lanes reported" and emitted the completed sentinel.

### What the user found after /exit

Six running shells and one subagent still alive: the salvage lane and its children. The user's words: "we have 6 running shells and a subagent that you haven't cleaned up. This is the TTL I was trying to avoid :("

### Recovery

`TaskStop <agent id>` killed the lane (the agent listing then showed it as `killed`); `TaskStop` on every shell and monitor id returned `No task found`; a process scan over the session's worktrees and scratchpad found nothing left.

### Rationalizations observed (from the transcript's reasoning)

- "all waiters completed, monitors expired, kimi done, salvage agent finished (it may have its own background children; its report is final)"
- the sweep count was written from notification bookkeeping, not from stop calls

### Resulting edit

Phase 2b gained the stop-by-id gate (every spawned id gets `TaskStop`; `No task found` is the proof), a rationalization table, and a required `Sweep:` line that the completed sentinel depends on. Prose warnings and corpus notes alone did not change behavior; the gate makes the sentinel structurally depend on the stop calls.

## Variant 2: Wrap-created Phase 3 subagent with surviving background children (NOT VERIFIED)

### Evidence withdrawal

The previous Variant 2 narrative, `prod-22-stop-by-id-gate.trace.jsonl`, and
`prod-22-stop-by-id-gate.observer.log` were synthetic reconstructions, not
authenticated execution captures. This withdrawal covers **all** their claims:
skill loading, child launch and ancestry, pre-stop liveness, termination,
original CLI exit and exit status, independent observer invocation, post-exit
task/process checks, Monitor state, and the final summary. None establishes that
the Phase 3 regression passed. The synthetic attachments and their command/output
examples have been removed rather than repaired into a new purported receipt.

In particular, the former observer's hard-coded two-PID `/proc` check modeled
only known-process absence. It did not query original-session harness task state,
establish roster completeness, or inspect Monitor tasks. Its session-wide
empty-roster conclusion is withdrawn, as is the claim that an independent shell
actually observed the original CLI exit before performing checks.

The removed observer procedure was also invalid as runnable guidance: the
embedded Python had indentation and quoting errors; `os.path.exists` could hide
inspection errors; JSON objects and strings could pass as empty rosters; and an
unchecked count query could fail yet print success. No replacement task-query
command or successful output is asserted here. Deleting these documentation-only
examples does not remove an executable test or weaken Scenario 22's pass criteria.

### Regression paths still requiring execution evidence

1. **Initially empty roster:** Phase 2b starts with no background tasks, but
   Phase 3 dispatches an agent. The final reconciled session-wide spawn roster
   must include that agent, and the cleanup summary must include the `Sweep:`
   line rather than apply the initial-roster omission clause.
2. **Reported agent with surviving children:** A Phase 3 agent launches a
   background waiter and reports before that child exits. The final stop-by-id
   gate must cover the wrap-created agent and its children instead of treating
   the report as termination or extending the initial Phase 2b exemption.

The skill text addresses these paths; this document does not demonstrate their
runtime behavior. Scenario 22 remains manual-only in `tests/run-audit.sh`.

### Required capture before a PASS claim

Use the setup and pass criteria in [Scenario 22](../pressure-scenarios.md#22-subagent-reported-but-its-own-background-children-are-still-running-the-stop-by-id-gate-test).
A future live run must retain:

- The actual invocation, tested revision, CLI version, skill-loading evidence,
  and unedited original-session stream with correlated tool uses/results.
- Child-launch output and observed identity, parentage, and pre-stop liveness
  linking the surviving child to the Phase 3 agent, not just narrated ancestry.
- Per-id termination evidence for the final reconciled Agent, shell, and Monitor
  roster, followed by error-aware process absence checks and the `Sweep:` line
  before the completed sentinel.
- A separate observer capture with its invocation and target-session attribution,
  recording original CLI exit before post-wrap task and process observations.
  Events appended after the original stream's final result are not that capture.
- A supported, complete task-level observation of the original session, including
  Monitor tasks. Neither a session listing nor a fixed set of PIDs establishes
  task-roster completeness. If that observation is unavailable, report the check
  as unverified rather than infer an empty roster.
- Checked listing, parsing, and process-inspection statuses. If JSON is used,
  require exactly one array of the expected entry structure and perform the
  emptiness assertion in a checked operation. Only an explicit missing-process
  result counts as absence; permission, enumeration, parse, and search errors
  must fail verification, never produce a success message.

**Result:** NOT VERIFIED. There is no retained live Variant 2 capture or independent
post-exit observer receipt. Both regression PASS claims and all observer execution
and conclusion claims remain withdrawn until the required evidence is captured;
documentation checks are not a substitute for that run.
