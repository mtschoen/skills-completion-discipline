---
name: reconcile-tasks
description: "Use when asked to audit completed work, check off tasks, or reconcile one project's PLAN.md/TODO.md with recent git history. Matches tasks to commits using the project-tracker CLI or direct file and git-log reads, and presents evidence for approved task updates."
---

# Reconciling Tasks Against Git History

## Applicability

Use when the user asks the agent to reconcile a project's PLAN.md/TODO.md against its recent git history - e.g. 'what's actually done in project-tracker?', 'audit completed work for this project', 'any tasks I should check off?', 'reconcile the plan with what shipped'. Uses the project-tracker CLI when installed; otherwise reads PLAN.md/TODO.md and git log directly. Per-project, not fleet-wide.

When the user asks for an audit of completed-but-unchecked tasks, your job is
to look at one project's unchecked tasks and recent commit history together,
decide which tasks the commits actually completed, and present findings.
project-tracker gives you the data; you do the matching using your judgment.

There is no scoring layer in project-tracker - you read the JSON directly and apply
language understanding. This is intentional: an LLM is better at "does this
commit complete this task" than any keyword-overlap heuristic, and handles
design pivots, partial completion, and multi-commit arcs that a scorer can't.

## Steps

### 1. Identify the project

If the user is in a project's working directory, use that project's name.
If they're not, ask which project. Don't reconcile "all projects" - this
skill is single-project by design.

### 2. Read reconciliation data

Run `project-tracker reconciliation <project_name> --json`. Defaults are
usually fine. When auditing just-committed work, add
`--max-cache-age-seconds 0` to force a fresh refresh.

**Fallback without the CLI:** parse the project's `PLAN.md`/`TODO.md`
for unchecked `- [ ]` tasks yourself (skip titles wrapped in `~~...~~`),
collect `git log --oneline -100`, and proceed with the same matching
workflow below.

The response includes:

- `unchecked_tasks` - tasks that are **unchecked AND not abandoned**.
  project-tracker's parser already excludes tasks whose titles are wrapped in
  `~~...~~` (strikethrough), so you will never see abandoned tasks here.
  If you somehow do, that's a project-tracker bug - tell the user.
- `recent_commits` - up to 100 recent commits, newest first, verbatim
  from the `git-wizard` (<https://github.com/mtschoen/git-wizard>) cache -
  the git-data caching layer project-tracker uses.
- `cache_age_seconds` - how fresh the data actually is.
- `cache_refreshed` - `true` if this call triggered a `git-wizard` refresh.

### 3. Handle cache freshness before presenting anything

This matters because the #1 failure mode of reconciliation is a stale cache
that doesn't contain the commits the user just shipped. Look at both fields
and decide:

| Situation | What to do |
|---|---|
| `cache_refreshed: true` | Mention "freshly refreshed from git" in your findings. High confidence. |
| `cache_age_seconds` < 300 (5 min) | Data is current. No freshness caveat needed. |
| `cache_age_seconds` between 300 and max_cache_age_seconds, `cache_refreshed: false` | Data is slightly stale. Mention it briefly. |
| `cache_age_seconds` > max_cache_age_seconds and `cache_refreshed: false` | **Refresh was attempted but failed.** Surface this prominently: "Warning: I tried to refresh the `git-wizard` cache but it failed, so this audit is running against a cache that's N minutes old. Results may miss recently-completed work." Then suggest the user run `project-tracker refresh-git` manually, or that you retry with `--max-cache-age-seconds 0` once they've confirmed `git-wizard` is on PATH. |
| No `recent_commits` at all | Tell the user there's no history to reconcile against and stop. Don't guess from filesystem state. |

If the user is auditing a project they just worked in, proactively suggest
passing `--max-cache-age-seconds 0` to force a fresh refresh before
presenting findings. The default 1-hour threshold is generous and will miss
commits you just shipped.

### 4. Match tasks to commits using judgment

For each unchecked task, scan the commit list for commits that plausibly
completed it. "Plausibly" means:

- The commit message references the same feature, function, file, or
  concept the task describes.
- Completion-intent verbs appear ("add", "implement", "ship", "feat:",
  "wire up").
- Multiple commits forming an arc that together completed the task
  counts too - don't require a single one-to-one match.
- Be willing to say "no match" for tasks that don't have evidence.
  False positives are worse than false negatives - the user will
  manually check anything you flag.

### 5. Present findings - ONE ENTRY PER TASK, RAW CONTEXT

This is the most important presentation rule. **Each task gets its own
entry.** Do not group related tasks into a single paragraph even if they
share a theme (e.g. "three sub-bullets of a design-pivoted feature").

**Each entry MUST include the raw PLAN.md line with a line number**, not
a paraphrased version. The user is reasoning about specific lines in their
file - they need to see exactly what those lines say, not your summary of
what they mean.

Format each entry like this:

```text
**`PLAN.md:41`**
`- [ ] **Heuristic pass**: for each unchecked task, scan recent commit messages for keyword overlap with the task title...`

**Reasoning:** <one-line "why this looks done / doesn't / is ambiguous">

**Evidence:**
- `<hash>` - <commit message>
- `<hash>` - <commit message>

**Recommended operation:** <check | cross out | add note | leave alone>
```

Lead with the tasks you're most confident about. Mention confidence in
prose ("high confidence", "borderline", "worth a look") - don't invent a
numeric score. If a task has no match, either don't mention it at all OR
present it with "no evidence found" explicitly when you suspect it
might be done from older pre-cache-window work (see calibration notes).

### 6. Explain the four operations available per task

project-tracker can apply four distinct operations to a task in PLAN.md:

1. **Check** - mark as done. Use when the commits clearly describe
   completion of exactly what the task says. Implemented with the CLI's
   `task toggle` command (which only toggles `[ ] <-> [x]`).

2. **Cross out (abandoned)** - wrap the title in `~~...~~` strikethrough,
   leaving the checkbox unchecked. Use when the task was deliberately not
   done - design pivoted, requirement changed, sub-task obsoleted. This
   visually marks "we're not going to do this" while preserving the
   original text as a historical record. **Requires a direct file edit**
   because `task toggle` only handles the checkbox, not the title wrap.

3. **Add note** - append an indented italicized line below the task
   explaining context: why it was skipped, what replaced it, what's still
   pending, what the real status is. Use when the task has complicated
   partial status that check-or-cross can't capture. Also a direct file
   edit.

4. **Leave alone** - the default. Use for tasks with no evidence or
   ambiguous status, where any action would be premature.

Ask the user which operation(s) they want per task. They can reply with
task names, line numbers, operation words ("check 44, cross out 41-43,
leave the rest"), or "none."

### 7. Execute the chosen operations

For each approved operation, use the right tool:

- **Check** -> `project-tracker task toggle example /repo/PLAN.md 8 --expected-title "Raw task title" --json`.
  Note the ABSOLUTE path (use `source_file_absolute` from the reconciliation
  response, not `source_file`). The expected title protects against a changed
  line. Fallback without the CLI: Edit tool on the file - change `- [ ]` to
  `- [x]` on that exact line.

- **Cross out** -> Edit tool on the PLAN.md file. Wrap the task title in
  `~~...~~`, preserving the `- [ ]` checkbox prefix. Example:

  ```text
  - [ ] **Heuristic pass**: for each unchecked task...
  ```

  becomes:

  ```text
  - [ ] ~~**Heuristic pass**: for each unchecked task...~~
  ```

- **Add note** -> Edit tool on the PLAN.md file. Insert a blank line
  and an indented italicized note immediately below the task line.
  Example:

  ```text
  - [x] **LLM pass (optional)**: ...

    *Note (YYYY-MM-DD): <explanation>*
  ```

- **Leave alone** -> no-op.

### 8. Confirm what changed

After executing, briefly summarize: "Checked lines 44. Crossed out lines
41-43 as abandoned. PLAN.md has 2 unchecked tasks remaining."

## What this skill is NOT

- **Not auto-toggle.** Always ask before flipping any checkbox or editing
  any line. The user (or a future you) can revert with another call, but
  a wrongly-modified task that no one notices is the worst outcome.

- **Not a rewriter.** Never rewrite the original task text. The only
  operations are check, cross-out (strikethrough), add note, or
  leave-alone. If the task description is now inaccurate (e.g. the feature
  was built with a different architecture than the task describes), add a
  note explaining the delta rather than editing the original text. The
  original text is a historical record.

- **Not a ranking algorithm.** project-tracker returns raw data. You apply
  judgment. No numeric scores, no confidence percentages.

- **Not cross-project.** Reconciliation is per-project. If the user wants
  a fleet sweep, decline and suggest running this skill once per project.

- **Not a replacement for find-task.** find-task surfaces tasks to *do*;
  reconcile-tasks finds tasks already *done*. Different intents.

## Calibration notes

**Empty states:**

- If `unchecked_tasks` is empty, tell the user the plan file is fully
  checked. Don't invent work.
- If `recent_commits` is empty (project has no commits at all, or
  `git-wizard` doesn't know about it), tell the user there's no history to
  reconcile against and stop. Don't guess from filesystem state.

**Noise:**

- If a commit clearly belongs to a *different* feature than any task
  describes, just don't mention it. The output should be tight, not
  exhaustive.

**Freshness:**

- "Freshly refreshed" data is the gold standard. If `cache_refreshed:
  true`, you can be confident in your matches.
- If the cache was stale but refresh failed (see Step 3), downgrade
  your confidence and tell the user explicitly.
- When the user just committed work and is asking "did this land?",
  proactively use `--max-cache-age-seconds 0` to force fresh data. The
  default threshold is too generous for just-shipped work.

**Partial completion:**

- A task with multiple sub-bullets might have some sub-bullets done in
  commits and others not. Don't flag the parent as "done" if only half
  its sub-bullets shipped. Present the partial state to the user and
  suggest the **add note** operation to capture the mixed status.

**Design pivots:**

- When a task describes an architecture we consciously replaced with a
  different one mid-implementation, the task is neither "done" nor
  "pending" - it's **abandoned**. Use the cross-out operation on the
  original sub-items and pair it with a note on the replacement
  explaining the pivot.
- The commit history alone can't always distinguish "design pivot" from
  "not done yet." If you're unsure, present both possibilities to the
  user and let them decide.

**No recent evidence, but might already be done from older work:**

- A task may have been completed long before the 100-commit cache window
  (`git-wizard`'s default). If the task sounds like it might describe
  functionality that already exists in the codebase, say so explicitly:
  "No evidence in the 100-commit window, but `find_stale_projects`
  already exists in `core/queries.py` - this task might be done from
  older work. Worth checking the code before deciding." Don't guess;
  flag it as worth investigation.
