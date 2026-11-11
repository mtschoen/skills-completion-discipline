---
name: smoke-test
description: "Use when finishing a feature, bugfix, refactor or configuration change affecting runtime behavior, before any completion claim, before handing a check to the owner, or after a merge or deploy, even if confident it is correct. Runs the changed artifact to verify it builds and does what was asked; prose-only deliverables conclude N/A with nothing to run."
---

# Smoke Test

## Applicability and finish line

Use before claiming runtime behavior works, before handoff, and after deployment when deployment is in scope. First identify the requested outcome, acceptance criteria and target environments from the task. State missing assumptions briefly; ask only when the answer changes the work. Do not shrink the finish line to match completed work or expand it with unrelated improvements.

Scale verification to the changed behavior and consequence. One real consumer invocation may settle a one-line config change; a release needs its agreed behavior and target matrix. Reuse existing checks; do not create ceremony to fill stages.

Pure prose (plans, specs, README and other docs, memory notes, skill text, code comments) has no runtime smoke test: say "nothing to smoke test - prose-only change" and move on. That is a pass, not a skipped check, and linting markdown is not a smoke test. Executable examples, operational configuration and agent steering are not pure prose; they need their relevant consumer or scenario check before rollout. `smoke-test --init` authors a SMOKE.md without claiming its commands ran.

> **Modes:** Default - run a smoke test on your changes (everything below). `smoke-test --init` - instead, author a `SMOKE.md` for the current project; see [Creating a SMOKE.md](#creating-a-smokemd).

## The Problem This Solves

The user should never be the first person to discover that a change doesn't work. If a bug fix is reported finished and then fails to compile on the user's machine, that's a failure of process, not just a failure of code. The smoke test catches these before the user ever sees them.

## What a Smoke Test Is

A smoke test answers two questions, in order:

1. **Does it build and run?** (the floor - compile errors, import failures, server crashes)
2. **Does it do what was asked?** (the actual bar - the feature works, the bug is fixed, the behavior changed)

Question 1 without question 2 is not a smoke test. Passing the build is necessary but not sufficient. If the user asked you to add a button that exports a CSV, and the project compiles, you still need to verify the button appears and the CSV downloads.

## How to Smoke Test

### Check for a project SMOKE.md first

Before falling back to generic guidance, look for a `SMOKE.md` in the project root (and in the directory you're working in, for a monorepo). If one exists, **it is authoritative** - the project owner has written down exactly how to smoke test this project: the floor command(s), the bar command(s) that exercise real behavior, any setup (env vars, services to start), and any cleanup (e.g. stopping a launched process). Follow it instead of guessing from the project type.

A `SMOKE.md` overrides the project-type defaults, which are the fallback when none is present. If a `SMOKE.md` exists but is clearly stale (its commands fail because the project moved on), fix the smoke test for the change at hand, then offer to update the `SMOKE.md` - don't silently work around it.

If the project has no `SMOKE.md` and it's one you'll touch again, consider authoring one: see [Creating a SMOKE.md](#creating-a-smokemd) or run `smoke-test --init`.

### No SMOKE.md? Use the project-type catalog

Floor and bar commands per project type (compiled, web frontend, web backend, desktop GUI, Unity, scripts/CLI, configuration, test-only changes) live in `references/project-types.md`. Use the most specific approach that applies to what you changed.

## Validation ladder

1. **Gates on the diff.** Run the repository's required checks. Build or resolve the exact artifact under test.
2. **Exercise it yourself, in isolation.** The writer runs the requested behavior first, before review, through the real entry point with relevant inputs, scale and transitions. A reviewer then independently exercises the highest-risk behavior. Any state the run writes (home and config directories, database path) is redirected to a temporary location, by environment variable or the tool's own flag; a worktree alone does not isolate runtime state. An in-process test runner, `--help` or a launch alone is not exercising the entry point.
3. **After deployment, prove runtime identity, not liveness.** Use the authorized deployment procedure, then inspect each named target's running artifact and effective configuration (loaded version, revision or process start time compared with the merge). A checkout's HEAD, an install command's success or a health check does not establish it. Then exercise the deployed behavior within that procedure's limits. Crew seats report post-merge work to the owning agent and do not deploy shared services.
4. **Reach the seam.** For each remaining criterion, try the available, authorized automation, hardware and platform routes relevant to the acceptance criteria. Separate setup friction from a firm seam (next section). Never bypass access controls or disturb shared services to get evidence. An isolated seam proves only the behavior downstream of it.
5. **Then an attended run, targeted.** Only after the agent-reachable checks are settled, request a short, organized attended run with the receipt below. Attended checks do not block a code pull request; known defects and ordinary merge gates still do. Keep the remaining acceptance on an owned durable item after merge. A merge that automatically activates something risky (a migration, a deploy) is an activation question to settle before merge.
6. **If the attended run fails,** finish the remaining safe, independent checks of that one planned run, mark dependent or unsafe steps as not run, then return all findings to agent work. Fix and re-exercise them before requesting another attended run.

Record each claimed pass with artifact and revision, host or environment, action or command, input, expected and observed result, and where the evidence lives and when it was taken. Attribute imported evidence to its actual runner. Mark unrun checks explicitly. Keep useful output as session or CI artifacts, not committed raw logs.

## Status vocabulary

A report names the words that apply, each with scope and evidence. None implies another.

| Word | Meaning | Evidence |
| --- | --- | --- |
| Implemented | The requested artifact exists. | The diff or deliverable. |
| Merged | The change is on the named target branch. | Pull request link and resulting revision. |
| Running | The named host or process is using the intended artifact or configuration. | Runtime identity (loaded version, revision or process start time compared with the merge) and when it was observed. A checkout's HEAD or a health check alone is not runtime identity. |
| Exercised | Named acceptance behavior passed through that artifact. | Action or command, input, expected and observed result, where the evidence is. Say whether it ran in a sandbox or on the deployed target. |
| Accepted | The agreed finish line is met, including owner approval where required. | The criteria receipts and the approval. |
| Logged | An idea or out-of-scope observation was recorded for later and nothing was built or dispatched. | Link or path to the record. |

`Blocked: <step, reason, next actor>` qualifies any of them. Unknown, not run and not applicable never mean passed. A job runner's internal `done` value is not a product claim.

## Creating a SMOKE.md

When invoked as `smoke-test --init` (or asked to "set up a SMOKE.md" / "advertise this project's smoke test"), **don't run a smoke test - author one instead.** A `SMOKE.md` lets every future agent (and the user) run the right smoke test for this project without re-deriving it, which is what closes the gap between "I should smoke test" and "I ran the project's actual smoke test."

1. **Inspect the project.** Identify the build system and entry points from the project files (`*.csproj`, `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`), existing run/test scripts, CI config, and any `AGENTS.md`/`README` notes on building and running. Reuse commands that already exist - don't invent new ones.
2. **Draft the floor and bar.** The floor is the build/compile/start command. The bar is the command that exercises the changed behavior (run the CLI, hit the endpoint, run the relevant tests). Be concrete and copy-pasteable.
3. **Capture setup and cleanup.** Note any required env vars, services, or fixtures, and any cleanup the user expects (e.g. "stop the process this run started, by the PID it printed").
4. **Write `SMOKE.md` to the project root** using the template below, then show it to the user for confirmation. Keep it short - a smoke test someone will actually run, not a test plan.

### SMOKE.md template

````markdown
# Smoke Test

How to verify a change works in this project before declaring it done.

## Floor - does it build/run?

```bash
<build or start command>
```

## Bar - does it do what was asked?

```bash
<command(s) that exercise the changed behavior>
```

Verify: <what the output should show>

## Setup (if any)

<env vars, services to start, fixtures to seed>

## Cleanup (if any)

<processes to stop by the identity the run started, temp files to remove>

## Remaining acceptance

<criterion; agent attempts and evidence; exact blocked seam; next actor; tracking link>
````

## What "Fix It" Means

When a smoke test fails, don't just retry the same thing. Diagnose:

- Read the error message carefully
- Check if your change introduced the issue or exposed a pre-existing one
- If it's your change, fix the root cause
- If it's pre-existing, note it but don't get sidetracked fixing unrelated issues - focus on verifying your change works

A thorough attempt means you've actually investigated. Repeated identical attempts are not investigation. A genuine unresolved blocker gets the failed criterion, the observed cause, the next action and who owns it, not a generic request that the owner test everything.

## When You'll Be Tempted to Skip

The smoke test matters most in exactly the moments you'll want to skip it:

- **Late in a long session** when you've been working for a while and just want to wrap up. This is when you're most likely to make mistakes and least likely to catch them.
- **After a "trivially correct" change** - renaming a variable, fixing a typo, moving an import. These changes can have surprising knock-on effects (broken references, import cycles, case sensitivity issues).
- **When testing requires non-trivial setup** - starting a full stack, seeding test data, configuring environment variables. The effort of setting up the test is exactly why the user can't easily verify it themselves. If you skip it, you're pushing that cost onto them.
- **When you just finished a long debugging session** and finally found a fix. The temptation is to say "got it!" but the fix might have side effects, or might not actually work outside the narrow scenario you were debugging.
- **Midway through a multi-step task** where you want to keep moving. Test the intermediate state anyway - compounding untested changes is how you end up with a broken mess at the end that's hard to diagnose.

In all of these cases: run the smoke test. It's usually cheap. Debugging a broken change the user reports back to you costs much more.

## Things That Are Not Smoke Tests

- "The linter passes" - linters don't run your code
- "The types check" - type checking doesn't catch runtime errors
- "I'm confident this is correct" - confidence is not evidence
- "The tests pass" (when you changed a feature, not a test) - tests might not cover what you changed
- "I reviewed the code and it looks right" - code review is not execution
- A merge, a green build or an empty pull request queue - those are Merged at most, not Running or Exercised

These are all useful signals, but none of them substitute for actually running the changed code and seeing it work.

## Setup friction versus a firm seam

Setup friction is the agent's job: starting a server or a temporary database, driving a desktop window (see the `fixing-desktop-ui-bugs` skill), taking a screenshot, running the project's scripted smoke. A firm seam is photons on a physical display or headset, human judgment of taste, an elevation prompt when nobody is at the desk, or missing authority. When the owner is at the desk, an elevation prompt is not a seam: the agent runs the elevated command and the owner approves the prompt. If a feature has no command-line or unelevated route to its behavior, building that seam is part of the work when the task's scope allows.

At a firm seam, get as close as the routes allow, name exactly what could not be reached, and hand over a targeted run with this receipt. The agent runs every shell command; the owner only observes and approves.

```text
Before attendance
Target: <artifact/revision, host, observation time>
Exercised: <criteria; actions and inputs; expected -> observed; evidence links>
Remaining: <exact human-only seam; agent routes attempted and their limits>
Run: <bounded steps using the exact on-screen control labels, expected observations, safe stop condition>
Ownership: <tracking link; agent runs commands, owner approves/observes>

After a failed run
Target/run: <same identity; time; evidence link>
Finding | Step | Expected -> observed | Evidence | Impact | Next agent action
<one row per observed defect; hypotheses explicitly marked>
Unrun: <dependent or unsafe steps and reasons>
Next: <owning agent; fix and re-exercise; criteria for another attended run>
```

## After the Smoke Test Passes

Once the smoke test passes and you have no more changes to make, the change has settled. That is the moment to check whether it made any documentation lie. Use the **docs-update** skill - the sibling step to this one. It checks README, AGENTS.md, other in-repo docs, and inline doc comments for drift your change introduced, and bundles any fixes into the same commit. Most of the time nothing needs updating; the value is the check.

When several completion skills are in play, the order before publication is: project gates (tests / lint / coverage - see maintaining-full-coverage) -> isolated behavior checks -> docs-update -> scoped evidence report. After an authorized deployment: runtime identity -> deployed behavior -> any remaining attended acceptance. Publication is not acceptance.

If `superpowers:verification-before-completion` is also installed: that skill states the general rule that every completion claim needs evidence, whether the claim comes from a linter, a checklist, or a delegated subagent's report. Smoke-test is the runtime-code-specific instantiation of that rule - for a change that affects runtime behavior, the evidence is running the actual artifact (the ladder above), not a proxy for it. The two compose rather than overlap: verification-before-completion covers the full range of completion claims, smoke-test owns the "run the actual artifact" discipline for code changes specifically.
