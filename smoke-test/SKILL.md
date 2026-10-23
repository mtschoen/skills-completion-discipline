---
name: smoke-test
description: "Use when finishing a feature, bugfix, refactor or configuration change affecting runtime behavior, before any completion claim, even if confident it is correct. Runs the changed artifact to verify it builds and does what was asked; prose-only deliverables conclude N/A with nothing to run."
---

# Smoke Test

## Applicability

Use when you finish implementing a feature, fixing a bug, refactoring, or changing configuration - any change that affects runtime behavior - before saying 'done', 'complete', 'finished', 'all set', 'ready to commit', or any variation, even if you're confident the change is correct. If you changed code, you smoke test it. Does NOT apply when the deliverable is prose (plan, spec, brainstorm doc, README, memory note, skill text): nothing runs, so say so and move on.

> **Modes:** Default - run a smoke test on your changes (everything below). `smoke-test --init` - instead, author a `SMOKE.md` for the current project; see [Creating a SMOKE.md](#creating-a-smokemd).

## The Problem This Solves

The user should never be the first person to discover that a change doesn't work. If they ask you to fix a bug and you say "done", then they try it and get a compile error - that's a failure of process, not just a failure of code. The smoke test catches these before the user ever sees them.

## What a Smoke Test Is

A smoke test answers two questions, in order:

1. **Does it build and run?** (the floor - compile errors, import failures, server crashes)
2. **Does it do what was asked?** (the actual bar - the feature works, the bug is fixed, the behavior changed)

Question 1 without question 2 is not a smoke test. Passing the build is necessary but not sufficient. If the user asked you to add a button that exports a CSV, and the project compiles, you still need to verify the button appears and the CSV downloads.

## When to Smoke Test

**Every time**, before you tell the user a runtime-affecting change is done. This includes:

- Feature implementation
- Bug fixes
- Refactors (yes, even "safe" ones)
- Config changes
- Dependency updates
- Build script changes

## What Does NOT Get Smoke Tested

Changes with no runtime behavior have nothing to run. If the deliverable is one of these, the skill discharges immediately - say "nothing to smoke test - prose-only change" and move on:

- Plans, specs, brainstorm documents
- README and other documentation-only edits
- Memory notes, skill text, code comments
- .gitignore and similar non-executable config

Concluding "not applicable" here is a pass, not a skipped check - same as a pushback round that correctly ends "no pushback needed". Do NOT manufacture a smoke test for prose: linting a markdown file or re-reading a plan you just wrote is not a smoke test, and running one anyway is the failure mode, not diligence.

## How to Smoke Test

### Check for a project SMOKE.md first

Before falling back to generic guidance, look for a `SMOKE.md` in the project root (and in the directory you're working in, for a monorepo). If one exists, **it is authoritative** - the project owner has written down exactly how to smoke test this project: the floor command(s), the bar command(s) that exercise real behavior, any setup (env vars, services to start), and any cleanup (e.g. killing a launched process). Follow it instead of guessing from the project type.

A `SMOKE.md` overrides the project-type defaults, which are the fallback when none is present. If a `SMOKE.md` exists but is clearly stale (its commands fail because the project moved on), fix the smoke test for the change at hand, then offer to update the `SMOKE.md` - don't silently work around it.

If the project has no `SMOKE.md` and it's one you'll touch again, consider authoring one: see [Creating a SMOKE.md](#creating-a-smokemd) or run `smoke-test --init`.

### No SMOKE.md? Use the project-type catalog

Floor and bar commands per project type (compiled, web frontend, web backend, Unity, scripts/CLI, configuration, test-only changes) live in `references/project-types.md`. Use the most specific approach that applies to what you changed.

## The Smoke Test Sequence

After you finish the implementation but before you declare completion:

1. **Identify the project type and what changed.** This tells you which smoke test applies.
2. **Run the floor check** (build/compile/start). If it fails, fix it and retry - no need to narrate intermediate failures.
3. **Run the bar check** (exercise the actual change). If it fails, fix it and retry.
4. **If you can't fix it after a thorough attempt** (3+ cycles of fix-and-retry, or you've hit something you genuinely don't understand), then report what you tried, what's still broken, and what you think the issue might be. The user should hear "I made the change but the server returns a 500 on the new endpoint - here's the stack trace, I tried X and Y but the issue seems to be Z" - not just "done."
5. **Report success with evidence.** Don't just say "done" - say what you verified. "Built the solution, ran the CLI with `--export csv`, confirmed the output file has the expected columns." Brief is fine, but concrete.

## Creating a SMOKE.md

When invoked as `smoke-test --init` (or asked to "set up a SMOKE.md" / "advertise this project's smoke test"), **don't run a smoke test - author one instead.** A `SMOKE.md` lets every future agent (and the user) run the right smoke test for this project without re-deriving it, which is what closes the gap between "I should smoke test" and "I ran the project's actual smoke test."

1. **Inspect the project.** Identify the build system and entry points from the project files (`*.csproj`, `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`), existing run/test scripts, CI config, and any `AGENTS.md`/`README` notes on building and running. Reuse commands that already exist - don't invent new ones.
2. **Draft the floor and bar.** The floor is the build/compile/start command. The bar is the command that exercises the changed behavior (run the CLI, hit the endpoint, run the relevant tests). Be concrete and copy-pasteable.
3. **Capture setup and cleanup.** Note any required env vars, services, or fixtures, and any cleanup the user expects (e.g. "kill the Unity process with `taskkill //IM Unity.exe //F` after launching").
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

<processes to kill, temp files to remove>

## Needs manual testing

<things an agent can't verify from the CLI - UI, device behavior, etc.>
````

## What "Fix It" Means

When a smoke test fails, don't just retry the same thing. Diagnose:

- Read the error message carefully
- Check if your change introduced the issue or exposed a pre-existing one
- If it's your change, fix the root cause
- If it's pre-existing, note it but don't get sidetracked fixing unrelated issues - focus on verifying your change works

A "thorough attempt" means you've actually investigated, not just retried the build three times hoping it works. But also don't spend 30 minutes chasing a rabbit hole - if you're stuck after genuine investigation, say so.

## When You'll Be Tempted to Skip

The smoke test matters most in exactly the moments you'll want to skip it:

- **Late in a long session** when you've been working for a while and just want to wrap up. This is when you're most likely to make mistakes and least likely to catch them.
- **After a "trivially correct" change** - renaming a variable, fixing a typo, moving an import. These changes can have surprising knock-on effects (broken references, import cycles, case sensitivity issues).
- **When testing requires non-trivial setup** - starting a full stack, seeding test data, configuring environment variables. The effort of setting up the test is exactly why the user can't easily verify it themselves. If you skip it, you're pushing that cost onto them.
- **When you just finished a long debugging session** and finally found a fix. The temptation is to say "got it!" but the fix might have side effects, or might not actually work outside the narrow scenario you were debugging.
- **On step 3 of a 5-step task** where you want to keep moving. Test the intermediate state anyway - compounding untested changes is how you end up with a broken mess at the end that's hard to diagnose.

In all of these cases: run the smoke test. It's usually cheap. Debugging a broken change the user reports back to you costs much more.

## Things That Are Not Smoke Tests

- "The linter passes" - linters don't run your code
- "The types check" - type checking doesn't catch runtime errors
- "I'm confident this is correct" - confidence is not evidence
- "The tests pass" (when you changed a feature, not a test) - tests might not cover what you changed
- "I reviewed the code and it looks right" - code review is not execution

These are all useful signals, but none of them substitute for actually running the changed code and seeing it work.

## When You Can't Fully Verify

Sometimes you genuinely can't complete the bar check - maybe you don't have browser access, or the change requires a running database you don't have, or it's a UI change in a native app. In these cases:

1. Do everything you can (build, start the server, run available tests)
2. Be explicit about what you verified and what you couldn't
3. Tell the user exactly what to check: "I verified it compiles and the unit tests pass. Please check in the browser that the modal closes after clicking Save - I couldn't test that from the CLI."

The user knowing what to test is far better than the user thinking everything was tested when it wasn't.

## After the Smoke Test Passes

Once the smoke test passes and you have no more changes to make, the change has settled. That is the moment to check whether it made any documentation lie. Use the **docs-update** skill - the sibling step to this one. It checks README, AGENTS.md, other in-repo docs, and inline doc comments for drift your change introduced, and bundles any fixes into the same commit. Most of the time nothing needs updating; the value is the check.

When several completion skills are in play, the order is: project gates (tests / lint / coverage - see maintaining-full-coverage) -> smoke-test -> docs-update -> declare done / commit.

If `superpowers:verification-before-completion` is also installed: that skill states the general rule that every completion claim needs evidence, whether the claim comes from a linter, a checklist, or a delegated subagent's report. Smoke-test is the runtime-code-specific instantiation of that rule - for a change that affects runtime behavior, the evidence is running the actual artifact (the floor/bar sequence above), not a proxy for it. The two compose rather than overlap: verification-before-completion covers the full range of completion claims, smoke-test owns the "run the actual artifact" discipline for code changes specifically.
