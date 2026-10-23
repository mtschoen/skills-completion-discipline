---
name: project-maintenance
description: "Use when asked for a repo maintenance pass, cleanup, end-of-session tidy-up or health check, or for fleet sweeps after project-tracker.find_stale_maintenance. Researches each finding for interactive approval or parent review and logs every action in the maintenance record."
---

# Project Maintenance

## Applicability

Use when the user asks for a maintenance pass, cleanup, end-of-session tidy-up, or health check on a repo. Triggers: 'clean up this project', 'run maintenance', 'end of session cleanup', fleet sweeps that follow project-tracker.find_stale_maintenance. Researched and interactive; every action is logged.

End-of-session cleanup for a single repo. Works in two modes:

- **Interactive** - running in a user-facing session. Walk the checklist, research each finding, and prompt the user per item before taking action.
- **Fleet subagent** - running under `fleet-orchestration`. Produce the same researched findings but return them to the parent as structured data. Do not prompt - the parent drives the approval loop with the user.

**Relationship to the `wrap` skill:** wrap owns the interactive, autonomous-fix, session-close version of per-session hygiene; this skill re-runs the same items detection-only in step 0, reading wrap's `references/hygiene-checklist.md` (in the installed wrap skill's directory) as the canonical list. For a full end-of-session pass across everything the session touched, use `/wrap` directly instead.

## Operating principles

1. **Verify before delete.** Never delete untracked files. For tracked files, delete only when (a) the working tree is clean and (b) you can state why the file has served its purpose. This governs every finding this skill produces, step 0's hygiene hits included (wrap's looser untracked-delete rule never applies here).
2. **Research before asking.** Each finding you surface must already include evidence, a recommendation, a confidence level, and the exact action you'd take on approval. The user should be able to y/n without opening any files themselves.
3. **Log everything.** Every automated action, every user-approved action, and every user-rejected proposal must appear in the final action log. Nothing the agent does should be invisible.
4. **Age is a hint, not a gate.** A day-old memory may already be obsolete; a month-old memory may still be load-bearing. Semantic checks (fix-implemented, dangling reference, superseded) decide staleness.

## Procedure

### 0. Hygiene survey (findings-only)

If the wrap skill is installed, run the read-only detection queries from its `references/hygiene-checklist.md` (the canonical per-session item list; consumed by reference, not duplicated here) against this repo. If wrap is not installed, check at minimum: uncommitted changes, unpushed commits, temp files, project-scoped stale memory, merged local branches, and stale worktrees.

Turn every hit into a normal finding per `references/finding-schema.md` (evidence, recommendation, confidence, exact action on approval) and feed it into step 2's research pass. Detection only: never execute a fix in this step, and never invoke the wrap skill itself - its interactive, whole-session close-out procedure is not part of a maintenance pass.

### 1. Bootstrap

If the project-tracker MCP server is available, call `project-tracker.get_maintenance_checklist(name=<project>)` first. This returns the combined mechanical status in one shot and saves you most of the shell work. Without it, run the mechanical checks from `references/checklist.md` by hand with git/shell.

`get_maintenance_checklist` does not yet know about the `clean_init_*` checks below - it emits no findings for them regardless of MCP availability. Always run the "Safe git clean + post-clean init" row of `references/checklist.md` by hand, even when the MCP server answered everything else.

If available, also call `project-tracker.find_stale_memory(days=30)` and scope the result to the current project (without the MCP server, skim the project's memory directory for stale entries yourself).

### 2. Research each finding

For every item the checklist returned, enrich it into a full finding. The schema is in `references/finding-schema.md`. Never surface a finding without evidence you have actually inspected:

- **Temp files (untracked):** read the contents. Is this scratch still in progress? Was it copied somewhere? Recommend `delete` only if you can explain why it's spent.
- **Temp files (tracked):** use `git log -- <path>` to see when it last changed and why. If the work has landed elsewhere, recommend `delete` (it's recoverable).
- **Dead code:** grep for references to the symbol across the repo and the user's other projects. Don't recommend removal without evidence nothing consumes it.
- **TODO comments:** check whether the referenced condition still holds in current code. Often the fix is already in place and only the comment remains.
- **Stale memory:** read the memory, then verify each claim it makes against current code. If the referenced issue is fixed, recommend deletion with the commit/line that fixed it as evidence. If it's still valid, keep it. Keep-or-delete is not the only outcome: a multi-item memory (e.g. a handoff note listing follow-ups) where some items are now verifiably done should be **updated in place** - mark the closed items done with the verifying evidence, leave the still-open items untouched.
- **Branches:** refresh tracking refs with `git fetch --prune` before triage relying on them. In Phase 2, this fetch may run automatically (logged under `automated`); in Phase 1 (the default), obtain user approval (interactive mode) or parent approval (fleet subagent mode) before fetching. If the required refresh is not approved, defer stale-ref-based triage. Without a prune, `refs/remotes/` still holds tracking refs for branches deleted upstream, and `git branch -vv` prints them as `[origin/X]` or even `[origin/X: behind 3]` - which reads as a live remote branch with unmerged work. Triage built on stale refs proposes `git push origin --delete` for branches that have had no remote copy in months. When checking a specific branch, do not suppress stderr: `git ls-remote --heads <bogus-remote> <branch>` fails on stderr with empty stdout, so a `[ -n "$out" ]` guard reports "no remote copy" identically to a real absence - check the exit status instead. Then run `git merge-base --is-ancestor <tip> <target>` to confirm the branch's tip commit is fully merged into the target branch. If the branch is **not** merged (the common case - agent work branches that were force-pushed, rebased, or abandoned), diff it against the target: `git diff <target>..<branch> --stat` at minimum. Generic commit messages ("chore: wrap session hygiene", "chore: cleanup") can mask significant unmerged WIP - the diff is the only way to know. If the diff is non-trivial, surface it to the user. If the branch **is** fully merged, also check whether it still exists on any remote (`git ls-remote --heads <remote> <branch>`): deleting only the local copy leaves the remote one lingering, and `git fetch --prune` never deletes the remote branch itself. Propose `git push <remote> --delete <branch>` alongside the local delete.
- **Empty directory husks:** untracked directories containing zero files (`find . -type d -empty -not -path "./.git/*"`). Git tracks files, not directories, so these are invisible to `git status` and survive dirty-tree checks indefinitely - typically leftovers from cleaned-out test workspaces. Principle 1's "never delete untracked files" does not block removal (there are no files to lose), but still surface as a finding: confirm the directory name doesn't signal reserved future use before deleting.
- **Multi-remote mirror drift:** when the repo pushes to two remotes (e.g. `origin` on Gitea + `github`), fetch both and compare default-branch heads: `git rev-list --left-right --count origin/main...github/main`. Non-zero counts mean the mirrors have diverged - usually from one-way automation pushing to a single host. Identify the orphan commits on each side (`git log --oneline origin/main..github/main` and the reverse) and recommend merge-reconcile, not force-push, unless the user decides one side is disposable.
- **Agent-instruction file convention** (`agents_convention` findings): the canonical layout is **AGENTS.md as the single source of truth**, with `CLAUDE.md` and `GEMINI.md` as thin **`@AGENTS.md` import pointers**. Claude Code and Gemini CLI auto-expand the `@`-import into context; a plain markdown link does NOT load, so a linked pointer is flagged for upgrade. The exact target shapes (bare pointer vs. pointer + platform-specific addendum) and the test for what counts as "platform-specific" are in `references/cross-project-config.md`. Per finding kind:
  - `agents_source_missing` - a `CLAUDE.md`/`GEMINI.md` holds real content and no `AGENTS.md` exists. Draft: move the content into a new `AGENTS.md`, then rewrite the tool file to the `@AGENTS.md` pointer. The migrated content goes to the user for approval, not straight to disk.
  - `agents_pointer_divergent` - `AGENTS.md` exists but the tool file has its own content. Separate the genuinely platform-specific part (Claude-Code-only / Gemini-only rules) from the shared part. Fold the shared part into `AGENTS.md`; rewrite the tool file as `@AGENTS.md` plus the platform-specific addendum below the import line. If nothing is platform-specific (the common case), it becomes a bare `@AGENTS.md`.
  - `agents_pointer_weak_link` - the tool file points at `AGENTS.md` via a markdown link. Mechanical fix: replace the link line with `@AGENTS.md` (keep any addendum below it).
- **Docs content drift** (`docs_content_drift` findings): check whether the repo's docs still tell the truth about the code. The **docs-update** skill owns the surface list and per-surface procedure - use it (its `SKILL.md` is readable even when not installed as a skill). Cite the stale statement and the line or commit that contradicts it - the finding must be specific enough that the user can y/n without opening the file themselves. This is distinct from `agents_convention`, which validates import shape; `docs_content_drift` asks whether the content is still accurate.
- **Cross-project config drift** (`onsave_hook`, `ci`, `aislop` findings): a code repo missing a fleet-standard config. Each is **low confidence** - confirm the repo's languages and judge whether it warrants the config before surfacing (a tiny script repo may not need an aislop gate). Draft the fix from the canonical shape in `references/cross-project-config.md`:
  - `onsave_hook` - no `PostToolUse` Write|Edit linter hook in the project-local settings for the current agent. Or raise a flag if settings for other agents exist but don't have the linter hook.
  - `ci` - no `.gitea/workflows/` or `.github/workflows/`.
  - `aislop` - no `.aislop/config.yml` quality gate.
- **local settings tracking** (`agents_settings` findings): the `.agents/` (or `.claude/`, `.gemini/`) shared-vs-local settings convention. Target shapes and the full rationale are in `references/cross-project-config.md`. Per finding kind:
  - `agents_settings_local_tracked` (**high**, mechanical) - `.agents/settings.local.json`, `.claude/settings.local.json`, etc. is tracked. It is the per-machine local override the permission flow churns each session; tracking it can smuggle in an over-broad grant. `action_on_approval` is `git rm --cached .agents/settings.local.json` then commit - the working copy stays on disk and the ignore rule catches it afterward. Do NOT delete the working file. A `.gitignore` rule added after the commit does not retroactively untrack it.
  - `missing_agents_settings_ignore` (**low**) - the repo tracks `.agents/settings.local.json`, `.claude/settings.local.json`, etc. but `.gitignore` lacks the `.agents/*` + `!.agents/settings.json` convention; append those two lines. Low confidence; the other tracked `.agents/` files (AGENTS.md, notes/) are intentional and not flagged.
- **Safe git clean + post-clean init** (`clean_init_*` findings): the invariant that `git clean -ffxd` is always safe to run - see `references/cross-project-config.md`'s "Safe git clean + post-clean init" section for the canonical target shapes. Per finding kind:
  - `clean_init_load_bearing_untracked` (**high**) - a tracked file, hook, CI workflow, or other script references a path under `.claude/scripts/` (gitignored via `.claude/*`). Grep for the reference; the fix is to move the file to a tracked `scripts/` directory and update every reference (including the untracked `.claude/settings.local.json`, updated in place but never committed). A spent one-off script with no remaining references is deleted instead of moved.
  - `clean_init_maintenance_json_ignored` (**high**, mechanical) - `.maintenance.json` is gitignored instead of tracked. Nothing regenerates its record of actioned/rejected findings. Fix: remove the ignore line, add the `!.maintenance.json` negation, `git add .maintenance.json`. Expect this to fire on repos maintained through project-tracker's `write_maintenance_state` helper: as of the currently installed release, that helper itself writes the ignore line this finding flags (`fleet-orchestration`'s `references/maintenance-format.md` documents the defect and the workaround) - fixing the finding here does not fix the helper, so it recurs on the next run until the helper is patched upstream.
  - `clean_init_scripts_missing` (**medium**) - the repository root lacks `init.ps1`, `init.bat`, or `init.sh`. Confirm the repo actually needs all three (a Linux-only project has no reason for `init.ps1`); draft from the reference implementation named in `cross-project-config.md`, adapted to the repo's own build/restore commands.
  - `clean_init_aislop_docs_missing` (**medium**, mechanical) - `.aislop/config.yml` exists but `.claude/AISLOP.md` does not. Fix: run `aislop hook install claude --project` once, then confirm the tracked `.claude/settings.json` has no content diff afterward (a line-ending-only rewrite is expected and safe to leave, or restore per the init-script guard if it bothers a clean `git diff`).
  - `clean_init_gitattributes_missing` (**low**) - `.gitattributes` lacks the `*.sh text eol=lf` / `*.bat` and `*.cmd text eol=crlf` rules while the repo tracks scripts of those types. Append the rules and their comments from `cross-project-config.md`; do not add the rule for a script type the repo doesn't have.

### 3. Interactive approval loop (interactive mode only)

For each researched finding:

1. Show: **what / evidence / recommendation / confidence / action on approval**.
2. Ask: `[y]es / [n]o / [s]kip / [e]dit the action`.
3. Execute or record accordingly.
4. Append the outcome to the in-memory action log under one of: `automated`, `user_authorized`, `rejected`.

In fleet-subagent mode, skip the loop - return findings to the parent and let it drive approval.

### 4. Safe auto-fixes (Phase 2 only - see rollout)

When Phase 2 is enabled, the following may run without per-item prompting. Log every one under `automated`:

- **Rename `master` to `main`** - only on a clean working tree. Steps:
  - `git branch -m master main`
  - If a remote exists: `git push -u origin main`
  - If GitHub remote: `gh api -X PATCH repos/:owner/:repo -f default_branch=main`
  - `git push origin --delete master`
  - Grep the repo for hard-coded `master` references (CI, README badges, scripts) first; abort the auto-fix and escalate if any exist.
- **`git fetch --prune`** - runs before branch triage to refresh tracking refs and prune deleted upstream branches. In Phase 1, surface for approval before fetching; if not approved, defer stale-ref-based triage.
- **Delete merged local branches** - only delete branches whose tips are **confirmed merged** into the target branch (`git branch --merged main` already guarantees this; each returned branch's tip is an ancestor of main, so its content is safe). **Do not use this auto-fix for branches that are not merged** - those must be researched per Step 2 (merge-base check + diff) and treated as Phase 1 findings.
- **Breadcrumb update** - always runs; see step 5.

In Phase 1, treat these as researched findings too: surface them for approval, don't execute unasked.

### 5. Finalize

Build the summary:

```json
{
  "timestamp": "<ISO-8601 UTC>",
  "head": "<git HEAD sha>",
  "automated": [ ... ],
  "user_authorized": [ ... ],
  "rejected": [ ... ]
}
```

Call `project-tracker.record_maintenance_run(name=<project>, summary=<summary>)` to persist the mechanical log in `.maintenance.json` (or append the entry to `.maintenance.json` directly when the MCP server is absent).

Return to the user (interactive) or parent (fleet):

- The same action log, plus a short natural-language report describing anything the agent found judgment-worthy: surprises, patterns across findings, suggested follow-ups.

## Rollout phase

Check `~/.agents/project-maintenance/phase` (file containing `1` or `2`). If absent, assume **Phase 1**. In Phase 1, skip the Phase-2-only auto-fixes above and treat them as researched findings.

## References

- `references/checklist.md` - the full checklist with each check's purpose
- `references/finding-schema.md` - exact shape of a finding dict
- `references/interactive-loop.md` - the prompt wording and decision tree
