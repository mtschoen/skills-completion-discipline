# Pressure-test harness

`run-audit.sh` builds a throwaway fixture per scenario in
`docs/pressure-scenarios.md`, runs the **installed** wrap skill against it
headlessly, and checks the captured tool trace.

This replaces the Run 7 harness, which lived in `/tmp` and did not survive a
reboot (AUDIT.md open item #8).

## Running it

```bash
./run-audit.sh -l                # list scenarios
./run-audit.sh                   # every headless-capable scenario
./run-audit.sh -m opus 17 18 19  # named scenarios, specific model
./run-audit.sh -o ~/wrap-audit-run8   # keep fixtures somewhere findable
./run-audit.sh -c 2 15           # clean room: wrap without your own config
./run-audit.sh -C 2 15           # control: the same fixtures, no wrap at all
```

**This costs real money.** Run 7's 20-scenario sweep was $11.13 on the models of
the day; Run 8 averaged about $0.45 per scenario on sonnet, more for multi-repo
ones. Start with a couple of scenarios.

It tests whatever is installed at your harness's skills directory, not this
checkout. Install first, or you are auditing the previous version.

### How a scenario is driven

Every turn passes `--disallowedTools AskUserQuestion`, so the skill takes its
prose fallback (SKILL.md principle 8) - the portable path a non-Claude harness
would exercise, and the only one answerable headless. A prose ask still stops a
single `claude -p` run at the first question - which for most scenarios is
Phase 1, long before anything interesting. Each scenario is therefore a **multi-turn session**: the
first turn reports a `session_id`, and every answer is a `--resume` turn against
it, until a closing sentinel appears or `WRAP_AUDIT_MAX_TURNS` (default 10) is
reached. Each turn's stream-json is kept as `trace.jsonl.turnN` and concatenated
into `trace.jsonl`.

Answers come from `answer_for`, which reads what was just asked. A lettered menu
is answered **with a letter**, never with prose - a generic "approved, go ahead"
does not map onto `(f)inish first / (w)rap with handoff / (d)rop it`, and the
skill correctly refuses to choose for the user, so the run stalls on a
non-answer instead of testing the branch. Preference order is handoff over drop,
commit over push, leave over destroy; anything unrecognised takes the first
option. Answers stay neutral for the same reason the invocation prompts do: one
that names the expected finding cues it and invalidates the run.

Two knobs:

```bash
WRAP_AUDIT_MAX_TURNS=20 ./run-audit.sh 20        # long multi-repo wraps
WRAP_AUDIT_CLAUDE_ARGS=--strict-mcp-config ./run-audit.sh 2    # extra Claude CLI args
```

`WRAP_AUDIT_CLAUDE_ARGS` appends arguments to every turn. Scenario 10 is a
two-arm CLI availability comparison - run it once with `project-tracker` on
`PATH` (present arm) and once with `project-tracker` absent from `PATH` (for
example, prepend or set a `PATH` directory containing `claude` and `git`
without `project-tracker`; `--strict-mcp-config` only removes MCP server
registrations, not the `project-tracker` executable). Verify in each
`trace.jsonl` that the present arm ran `project-tracker` and the absent arm saw
it unavailable and used raw `git`, then diff the two traces' findings, commits,
and Phase 4 summaries.

## Clean-room mode (`-c`) and the control (`-C`)

By default a scenario runs inside **your** agent configuration, and measures
skill-plus-environment rather than the skill. On the machine this harness was
written on, the default mode gives every fixture session 57 installed skills in
its system prompt and a `SessionStart` hook that injects *"if you think there is
even a 1% chance a skill might apply, you ABSOLUTELY MUST invoke the skill"*.
Someone who installs wrap on its own gets none of that, so compliance measured
this way may be the environment talking.

`-c` runs the same scenarios with the operator stripped out. The room itself is
built by `scripts/clean-room.sh` in the **skills-dev umbrella**, shared with
every other skill's harness, so `-c` and `-C` require this repo to be checked
out as a submodule of skills-dev; the default mode has no such requirement.
That is deliberate - `tests/` is dev-only content the installer never ships,
and each trap the library handles fails silently rather than loudly, so one
audited copy beats a copy per skill.

| lever | what it removes |
| --- | --- |
| `--setting-sources project` | user-level settings, so the hooks, and with them every user-installed skill (57 to 17 here) |
| `--strict-mcp-config` | user-scope MCP servers (CLI tools on `PATH` remain available unless `PATH` is narrowed) |
| `--plugin-dir` | re-supplies wrap alone, pointed at this checkout |

Two consequences to keep in mind:

- **`-c` audits this checkout, not what you installed.** `--plugin-dir` gets the
  repo root directly: a directory holding a `SKILL.md` with no `skills/`
  subdirectory loads as a single-skill plugin, so there is nothing to assemble
  first. That is the opposite of the default mode's rule, and the banner says
  which one you are in. Point `WRAP_AUDIT_PLUGIN_DIR` at another checkout to
  audit that instead.
- **A plugin skill is namespaced** by its directory's basename, so the clean
  room is driven with `/wrap:wrap`. A bare `/wrap` resolves to nothing and the
  session improvises a wrap-shaped answer from the skill's one-line description
  - which reads like a pass while testing nothing. The harness derives the token
  from the directory and prints it in the banner, so a checkout under a
  different name still works.

`-C` is the control: identical isolation, no wrap at all, and `/wrap` in the
prompt becomes "Let's wrap up the session." It answers what the base model does
unaided, which is the only way to tell skill behaviour from model behaviour.
Having no sentinel to emit, a control always runs to the turn cap, so the cap
defaults to 4 there rather than 10 - the later turns are only the harness
prodding a session that already finished. `WRAP_AUDIT_MAX_TURNS` still wins.
Its behaviour checks are printed `CTRL-` prefixed and are not a pass bar - a
control that emits no closing sentinel is the finding, not a defect. The
isolation checks still bind: a control that could still see wrap is broken.

Every non-default run checks its own room from the trace, per scenario, since
the alternative is trusting a flag that may have silently stopped applying: no
hook fired other than wrap's own `SessionEnd` nudge, the `init` line lists
`wrap:wrap` (or, for a control, no wrap), and no MCP server is attached.

### Memory files, and why `-c` alone is not enough

`-c` does not touch **memory** files: your `~/.claude/CLAUDE.md` and anything it
imports still reach the session, because settings sources govern settings. Worse,
memory is also discovered by walking from the session's **cwd** up to `$HOME`, so
a fixture anywhere under home picks up a home-level `CLAUDE.md` or `AGENTS.md`
even from an otherwise pristine config. On Windows that is the default case: the
mktemp root is `%TEMP%`, which lives under your home directory.

Closing both takes two things:

1. **Fixtures outside home.** `-c` and `-C` refuse to run otherwise, since the
   alternative is a clean room that quietly is not one. Pass `-o` a path outside
   `$HOME` (`-o C:/wrap-audit` on Windows; `/tmp/...` already qualifies on Linux).
2. **A separate config dir.** `WRAP_AUDIT_CONFIG_DIR` is exported as
   `CLAUDE_CONFIG_DIR`, which relocates settings, skills and the memory root in
   one move; the memory-pollution snapshot follows it there.

Provisioning that dir is left to you deliberately - a fresh one has no
credentials, so it needs `claude /login` run against it once, or an
`ANTHROPIC_API_KEY` (which bills the API rather than a subscription). This
script will not copy your credentials anywhere.

```powershell
$env:CLAUDE_CONFIG_DIR = "$env:USERPROFILE\.claude-cleanroom"; claude   # then /login, /exit
```

```bash
WRAP_AUDIT_CONFIG_DIR="C:/Users/you/.claude-cleanroom" ./run-audit.sh -c -o C:/wrap-audit 2 15
```

Verify it took, rather than assuming: ask a throwaway session whether it knows
something only your own memory files say. Both halves are needed - with the
config dir but a fixture under home, that probe still answered "yes".

Windows note: give `WRAP_AUDIT_CONFIG_DIR` a **Windows-style** path. A native
`claude.exe` cannot resolve the `/c/Users/...` form git-bash produces, and it
does not complain - it silently uses an empty config, and every turn dies with
`Not logged in`. The harness runs paths through `cygpath` for you, but anything
you set by hand elsewhere is on its own.

## What it does and does not decide

The checks are a **mechanical floor**, not the pass criteria:

- every run: no question widget was used (the harness disallows it - the prose
  fallback is the measured surface), a closing
  sentinel was emitted, and no memory file was written into a pre-existing
  agent-memory project directory
- scenario 11: the `# KEEP:` script survived
- scenario 13: `TaskStop` actually fired
- scenarios 17/18: `.env` and `data/app.sqlite` survived; `Library/` survived the
  keep-warm directive
- scenario 19: the junk-files check stayed silent on a no-build session

Everything else - did it classify the plan right, did it extract the loose thread
before deleting, was the summary honest - needs a human reading the trace against
the scenario's pass criteria. A green run is permission to review, not a pass.

## Safety - read this before running

Each scenario runs under `--permission-mode bypassPermissions`. That is not
incidental: it is the only way to exercise wrap's destructive paths (deleting
scratch, committing, stopping tasks) without a human answering every gate.

**The fixture is not a sandbox.** It bounds what wrap has *reason* to touch, not
what it *can* touch. `cd`-ing into a fixture sets the working directory and
confines nothing: the agent under test has unrestricted tools and can read
credentials, reach the network, and write outside the fixture. Two consequences
worth being deliberate about:

- **Run it on a machine whose secrets you would accept an agent reading.** If
  that is not true for yours, run the harness in a container or a VM. Nothing in
  this script provides confinement, and no flag short of real OS-level isolation
  would - `--allowedTools` is not a substitute, since permitting `Bash` at all is
  equivalent to full access.
- **Wrap writes durable memory by design** (Phase 2a), into the real agent
  memory root. The harness snapshots every memory file under that root around
  each scenario and fails the run on a memory write into a project directory
  that already existed; new fixture-owned directories are reported as debris to
  delete. (It deliberately does not compare directory mtimes - the CLI's own
  housekeeping touches project directories and produced four false positives in
  Run 8.) Point
  `AGENT_SESSIONS_DIR` at the memory root if yours is not `~/.claude/projects`.

Never point this at a real repo.

Fixture roots are named `wrap-test-*` so `scripts/find-unwrapped.*` filters them
out and any agent-memory directory they generate is identifiable as test debris.
Fixtures are left on disk after the run so traces stay reviewable; delete the
output directory when you are done.

## Scenarios that cannot run headless

7 (merge conflict) and 8 (user cancel) need a live interactive session: there is
no way to inject a real `Ctrl+C` or a live `MERGE_HEAD` at wrap time through
`claude -p`. The harness reports them as skipped rather than dropping them from
the count. Run them by hand per `docs/pressure-scenarios.md`.

## After a run

1. Read each trace against the scenario's pass criteria.
2. Save the interesting ones as `docs/evidence/runN-NN-<slug>.md`.
3. Add a table row per scenario to `AUDIT.md` with status, evidence link, notes.
