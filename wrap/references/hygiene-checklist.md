# Phase 3c Hygiene Checklist

The per-session-hygiene items that run once per touched repo during Phase 3c. Each item produces zero or more findings; findings follow the shape in `finding-schema.md`.

**Important scope rule:** These items are the *wrap-scope* subset of hygiene. Rare-tier items (master→main, CLAUDE/AGENTS merge, missing README/LICENSE, dead code) are **not** wrap's job - they live in `project-maintenance`. Do not expand this checklist to include them. The **disk-health audit** also stays in project-maintenance: flagging large *tracked* files, repo-history bloat, and low-disk warnings is a maintenance concern, not a session-end one. Wrap's one disk-adjacent item is the **junk-files (ephemeral build & import artifacts)** check below - and only because clearing build output *the session itself generated* is a natural session-close concern. It is deliberately scoped to *gitignored, regenerable* dirs that **this session generated or refreshed**, defaults to **keep**, and never touches pre-existing artifacts on a repo the session didn't build. It is not a general large-file or disk-usage sweep.

## Items

| Check | What to look for | Research required |
|---|---|---|
| Uncommitted changes | `git status --porcelain` non-empty | Categorize files by whether wrap itself made the edit or the user did. Wrap's own edits auto-commit in Phase 3d; user edits get the user prompt. |
| Unpushed commits | `git log @{u}..HEAD` non-empty (if upstream exists) | List the commits with their subjects so the user sees what would be pushed. |
| Temp files - tracked | File matches `*.tmp`, `*.bak`, `scratch*`, or was added as a "scratch" commit | Run `git log -- <path>` to see why it was added. If the work has landed in permanent files, propose delete (recoverable from git). |
| Temp files - untracked | Same name patterns, not in git | Read the contents. If the scratch is spent, propose delete with per-item approval. Never bulk-approve untracked deletions. |
| Stale memory entries (project-scoped) | Entries in the harness's per-project memory (for instance Claude Code's `~/.claude/projects/.../memory/project_*.md`) or the project's own memory store that reference fixed issues, dangling files, or superseded decisions | Semantic check against current code. If a claim in the memory is no longer true, propose deletion with evidence (commit/line that invalidated it). |
| Merged local branches | `git branch --merged main` (excluding `main` itself) | Verify each branch is actually merged, not just name-matched. Propose pruning with `git branch -d`. |
| Stale worktrees (this session only) | Worktrees created during the session that are no longer needed | Wrap should only touch worktrees it has clear evidence the current session created. Inherited worktrees are untouched. Honor any project keep-warm directive (see "Junk files" → keep-warm carve-out). |
| `.claude/scripts/` one-offs | Any files present in `.claude/scripts/` | Per the user's AGENTS.md rule, one-offs should be deleted after use unless explicitly kept. Ask per file. |
| Junk files (ephemeral build & import artifacts) | Gitignored build/cache dirs **this session generated or refreshed** - Unity `Library/`, `node_modules/`, `target/`, `build/`, `bin/`+`obj/`, `__pycache__/`, etc. **Invisible to `git status`**, so a clean tree does NOT clear this check - scan the tree directly when session activity (ran a build, opened an IDE/Editor, installed deps) implies they exist. | Default recommendation is **keep** - deleting forces regeneration next session. Surface one compact keep-or-clear opt-in finding (dirs + total reclaimable size + per-dir regen cost). Never propose deleting non-regenerable gitignored content. See "Junk files" below. |
| Docs drift | For any repo this session changed code in, check whether those changes left existing docs stale. The **docs-update** skill owns the surface list and per-surface procedure - use it for this check. | Surface stale statements as per-repo opt-in findings (default: surface and let the user approve the edit). This is the catch-net for sessions that changed code but never reached a commit or PR moment where docs-update would normally fire. |

## Junk files (ephemeral build & import artifacts)

Build and import artifacts - *junk files* - are almost always gitignored, so they never appear in `git status`. A clean working tree does **not** mean this check is empty. The hygiene pass must **actively scan** the repo root (and one level down, for monorepos / Unity layouts) for them.

**When to surface (session-scoped - this is the part that makes it wrap's job, not a disk audit).** Surface junk files only when *this session* generated or refreshed them - ran a build/compile, opened an IDE or the Unity Editor, installed dependencies, etc. The trigger is **session activity, not mere presence on disk**. A cold wrap of a repo the session never built must NOT surface pre-existing artifacts; clearing those belongs to `project-maintenance`'s disk audit. But when the session *did* generate them, do not let a clean `git status` short-circuit the scan - these dirs are gitignored and will never show there.

**Curated allowlist (candidates once the session-activity trigger is met):** `node_modules/`, `bin/`, `obj/`, `target/`, `build/`, `dist/`, `out/`, `.next/`, `.turbo/`, `__pycache__/`, `.pytest_cache/`, `.gradle/`, `.venv/`, `venv/`, `coverage/`, and Unity / Xcode build state: `Library/`, `Temp/`, `Obj/`, `Build/`, `Logs/`, `DerivedData/`.

**Judgment extension ("vibes"):** a directory *not* on the list may be flagged **only if** (a) it is gitignored or clearly not source, **and** (b) you can name how it is regenerated. If you can't articulate the regeneration path, don't surface it.

**Hard exclusions - never propose deleting, even when gitignored:**

- Secrets / config: `.env*`, `*.key`, `*.pem`, credential files.
- Local data: `*.sqlite`, `*.db`, database dumps, anything that looks like irreplaceable local state.
- A repo's own working/scratch dir that holds real work (e.g. a gitignored `workspace/`).

When you cannot tell whether a gitignored dir is regenerable build output or precious local state, treat it as precious and **do not surface it**.

**Default is KEEP, but surface it anyway (this item inverts the usual 3c bias).** Every other check here recommends deletion; this one recommends `keep`. Deleting build output forces a slow regeneration next session (npm install, Unity reimport) - the opposite of wrap's "ready for the next session" purpose. **But `keep` does not mean silent:** the whole point is to give the user a one-line *keep-or-clear* choice (e.g. to reclaim disk before shelving a project). Do not collapse "default keep" into "skip silently." Deletion is an **explicit, per-item opt-in**, never the default and never bulk-approved.

**One compact finding, not one per dir.** Roll all detected artifacts for a repo into a single finding: list the dirs, the total reclaimable size, and the per-dir regeneration cost. It rides inside the existing combined 3c approval question - it must not spawn a separate prompt.

### Keep-warm carve-out

Some projects deliberately keep build state warm between sessions - e.g. a Unity project that leaves an Editor worktree open so `Library/` doesn't have to re-import. Such a project declares this in its own `AGENTS.md` (a "keep worktrees/artifacts warm" directive). Check for that directive before surfacing junk-file or worktree deletion.

When a keep-warm directive is present for the repo:

- **Still surface the item as a question.** Don't suppress it - the user may still choose to clear the artifacts (reclaiming disk, shelving the project). The finding stays, with `recommendation: keep`.
- **Honor the directive as the default**, tagged with at most a terse neutral note (e.g. "project keeps this warm").
- **Do not re-litigate the contradiction.** Do *not* editorialize, on every wrap, that clearing would conflict with the project's directive or with wrap's cleanup goal. State the default quietly and move on. The recurring "but your config says X while wrap wants Y" commentary is the failure mode this carve-out exists to prevent.

This carve-out applies to the **Stale worktrees** check as well: a keep-warm worktree is kept by default, surfaced as a quiet opt-in, with no recurring contradiction commentary.

## Operating rules (reused from project-maintenance)

1. **Verify before delete.** Never delete untracked files without per-item approval. Tracked files may be deleted only when (a) the working tree is otherwise clean and (b) the agent can state why the file has served its purpose.
2. **Research before asking.** Every finding surfaces with evidence, a recommendation, a confidence level, and the exact action on approval. The user should be able to y/n without opening files themselves.
3. **Log everything.** Every automated action, every user-approved action, and every user-rejected proposal appears in the final summary (Phase 4). Nothing invisible.

## Relationship to project-maintenance

Wrap's hygiene checklist is a *subset* of project-maintenance's former checklist. The two checklist FILES partition the item rows - per-session items live only here, rare-tier items only in project-maintenance's `references/checklist.md` - so no row is maintained in two places. The CHECKS themselves overlap on purpose: project-maintenance does not invoke wrap, but project-maintenance's step 0 re-runs the read-only detection side of this very table, findings-only, against the single repo it is auditing, and feeds any hits into its own propose/approve flow. This file is the single canonical source for the per-session items; project-maintenance consumes it by reference. Wrap remains the sole owner of the interactive, autonomous-fix, whole-session version of these checks.

## Tooling

Use `project-tracker find-dirty --json` and `project-tracker find-stale-memory --json` for fleet-wide dirty and stale-memory scans when the CLI is installed. Use `project-tracker find-unpushed --json` for unpushed commits. Scope the results to the repos in this wrap, and use raw git/grep/find for local checks or when the CLI is not installed.
