# wrap

A skill that runs the session-closing ritual: externalizes ephemeral working memory into durable artifacts, then brings every touched repo into a clean state for the next session.

**Repo:** <https://github.com/mtschoen/skills-wrap>

## Design

Wrap has two equally-mandatory jobs: **externalize** what the agent knows but no file records yet, and **leave no mess behind** in any repo the session touched. The framing is *"externalize what's about to be destroyed, then clean up."*

Non-goals, all deliberate:

- **Never auto-runs.** Not from a `SessionEnd` hook, not from a `Stop` hook, not invoked by another skill. The user asks or it doesn't run.
- **Not a repo audit.** Rare-tier checks (default-branch renames, CLAUDE.md/AGENTS.md merges, missing README/LICENSE, dead code, large files, disk warnings) belong to `project-maintenance`. See `references/hygiene-checklist.md` for how the two partition the work.
- **Not stateful.** Wrap keeps no record of its own runs. Each invocation asks "what's true right now", which is what makes re-runs safe.
- **Not tool-coupled.** `SKILL.md` is tool-agnostic prose. The agent picks whatever is available at runtime.
- **Not cross-session.** Wrap only sees what *this* session did.

**Why intentional-only.** Not every session exit is a wrap. Restarting the agent, rebooting, or context-switching are quick exits where cleanup would be wrong and annoying; a wrap is for when a line of work is actually done. Only the user knows which one they're in, so only the user starts a wrap. The `SessionEnd` hook may *nudge* (see `references/session-end-reminder.md`), never invoke.

## Status

Stable, pressure-tested through Run 9b across 21 scenarios (18 headless-capable scenarios re-baselined in the clean room, scenario 10 verified in installed mode, scenarios 7 and 8 remain manual-only). No safety violations in any run.

Interactive wrap gates open in the harness's question tool when available and permitted: one short question, with the items and actions visible in 2 to 4 options. If the decision will not fit, wrap gives the full context and ends the turn on a prose question. Headless runs and evals use the prose protocol.

The 2026-08-05 audits (Runs 8, 9 and 9b) exercised the prose protocol in a **clean room**: wrap alone, without the operator's hooks, skills, MCP servers or memory files. A no-skill control ran alongside. `tests/run-audit.sh` makes both repeatable. See `AUDIT.md` for results and open scenarios.

This skill is part of the completion suite: `maintaining-full-coverage`, `smoke-test`, `docs-update`, `escalate-over-shortcut`, and `wrap`. Suite skills install separately (each lives in its own repo) but are designed to be installed together, and they reference each other directly. Each works standalone; treat cross-references to missing suite members as optional.

## Install

1. Copy the repo contents (`SKILL.md`, `references/`, `hooks/`) to `~/.agents/skills/wrap/` (or wherever your agent harness reads skills).
2. Register a session-end hook in the agent's settings - use the `update-config` skill, pointing it at `hooks/session-end-reminder.sh` (Unix/macOS) or `hooks/session-end-reminder.ps1` (Windows). This step depends on the harness supporting session-end hooks; not every harness does.
3. (Optional) The `scripts/find-unwrapped.sh` / `.ps1` companions are diagnostics that scan the agent's session transcripts and are not required for `/wrap` itself - copy `scripts/` too if you want them, or just run them from a checkout of this repo. Override the default transcript root with the `AGENTS_SESSIONS_DIR` env var.

Wrap ships no packaging of its own, by policy: installation is a concern of the whole skill collection, not of one skill. The supported path is the `skills-dev` collection's own installer. A standalone clone of this repo is a hand-install, as above.

## Invocation

Type `/wrap` at the end of a session when you are ready to close out. Wrap is always intentional - it never auto-runs.
