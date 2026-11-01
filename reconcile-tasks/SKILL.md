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

The response root contains project metadata, `locations`, freshness metadata,
and `truncated`:

- `project_name` and `project_status` identify the project.
- `cache_age_seconds` is the cache age in seconds, or `null` when freshness is
  unknown.
- `cache_refreshed` is `true` if this call triggered a `git-wizard` refresh.
- `truncated` is `true` when any returned collection hit the `--limit` cap and
  omitted entries.

Each entry in `locations` contains:

- `path` - the absolute project-location path.
- `role` - the location's role, which may be `null`.
- `unchecked_tasks` - tasks that are **unchecked AND not abandoned** at this
  location. Each task has `source_file_absolute`, location-relative
  `source_file`, `line_number`, `title`, and `heading`. project-tracker's
  parser already excludes titles wrapped in `~~...~~` (strikethrough). If an
  abandoned task appears, that's a project-tracker bug - tell the user.
- `recent_commits` - this location's recent commits, newest first, verbatim
  from the `git-wizard` (<https://github.com/mtschoen/git-wizard>) cache.

Task and commit collections exist only inside each location. Missing
response-root `unchecked_tasks` and `recent_commits` fields are expected and
do not mean the project is empty.

If the user explicitly requested a location, audit only that location.
Otherwise iterate every returned location independently. Keep each `path` and
`role` attached to its findings. Never silently choose the first location or
combine unrelated locations' task and commit lists.

Check root `truncated` before matching tasks or reporting remaining-task
counts. The CLI caps returned collections, including `locations` and their
nested collections, at `--limit` (default 100, maximum 10000). This limit does
not replace the independent `--max-commits` history window. When `truncated`
is `true`, retry with a larger limit such as
`project-tracker reconciliation <project_name> --limit 1000 --json` (up to
`--limit 10000`). If `truncated` remains `true` at the CLI maximum, read the
in-scope task files directly for their full task lists or explicitly report a
partial audit before presenting findings or remaining-task counts. Omitted
locations also prevent an exhaustive project summary.

**Fallback without the CLI:** for each in-scope location, parse that
location's `PLAN.md`/`TODO.md` for unchecked `- [ ]` tasks yourself (skip
titles wrapped in `~~...~~`), collect `git log --oneline -100` in the same
location, and proceed with the same matching workflow below. Do not use one
location's files or history for another location.

### 3. Handle cache freshness before presenting anything

Read freshness once from the response root, not from individual locations,
and carry its caveat to every audited location's findings. This matters
because the #1 failure mode of reconciliation is a stale cache that doesn't
contain the commits the user just shipped. Look at both root fields and
decide:

| Situation | What to do |
|---|---|
| `cache_refreshed: true` | Mention "freshly refreshed from git" in your findings. High confidence. |
| `cache_age_seconds` < 300 (5 min) | Data is current. No freshness caveat needed. |
| `cache_age_seconds` between 300 and max_cache_age_seconds, `cache_refreshed: false` | Data is slightly stale. Mention it briefly. |
| `cache_age_seconds` > max_cache_age_seconds and `cache_refreshed: false` | **Refresh was attempted but failed.** Surface this prominently: "Warning: I tried to refresh the `git-wizard` cache but it failed, so this audit is running against a cache that's N minutes old. Results may miss recently-completed work." Then suggest the user run `project-tracker refresh-git` manually, or that you retry with `--max-cache-age-seconds 0` once they've confirmed `git-wizard` is on PATH. |
| `cache_age_seconds: null` | Freshness is unknown, not zero. Say so and do not describe the data as current. |
| A location's `recent_commits` is empty | Record that this location has no history to match and continue auditing other locations. Do not guess from filesystem state. Describe project-wide absent history only after all in-scope locations have complete, empty histories. |

If the user is auditing a project they just worked in, proactively suggest
passing `--max-cache-age-seconds 0` to force a fresh refresh before
presenting findings. The default 1-hour threshold is generous and will miss
commits you just shipped.

### 4. Match tasks to commits using judgment

For each task in a location's `unchecked_tasks`, scan only that same
location's `recent_commits` for commits that plausibly completed it. Never use
another location's history as evidence. "Plausibly" means:

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

**Each entry MUST include the location path, its role when non-null, and the
raw task line from `source_file_absolute` with a line number**, not a
paraphrased version. The user is reasoning about specific lines in their file -
they need to see exactly where the task lives and what it says. Use
`source_file_absolute` for file reads. If you display relative `source_file`,
qualify it with the location path so it cannot be confused with another
location's file.

Format each entry like this:

```text
**Location:** `/example/active` (implementation)
**Task:** `/example/active/PLAN.md:3`
`- [ ] Add export command`

**Reasoning:** <one-line "why this looks done / doesn't / is ambiguous">

**Evidence from this location:**
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

For each approved operation, keep the location path with the task identity.
Read and edit `source_file_absolute`, check the returned `line_number`, and use
the task's `title` as the expected title. Never resolve a relative
`source_file` against a different location. Use the right tool:

- **Check** -> `project-tracker task toggle example /example/active/PLAN.md 3 --expected-title "Add export command" --json`.
  Note the ABSOLUTE path from `source_file_absolute`, not `source_file`. The
  line number and expected title protect against a changed task. Fallback
  without the CLI: Edit tool on the same absolute file - change `- [ ]` to
  `- [x]` only after confirming that exact line and title.

- **Cross out** -> Edit tool on the task's `source_file_absolute`. Wrap the
  task title in `~~...~~`, preserving the `- [ ]` checkbox prefix. Example:

  ```text
  - [ ] **Heuristic pass**: for each unchecked task...
  ```

  becomes:

  ```text
  - [ ] ~~**Heuristic pass**: for each unchecked task...~~
  ```

- **Add note** -> Edit tool on the task's `source_file_absolute`. Insert a
  blank line and an indented italicized note immediately below the task line.
  Example:

  ```text
  - [x] **LLM pass (optional)**: ...

    *Note (YYYY-MM-DD): <explanation>*
  ```

- **Leave alone** -> no-op.

### 8. Confirm what changed

After executing, briefly summarize by location and absolute task file:
"At `/example/active`, checked `/example/active/PLAN.md` line 3. This location
has 0 unchecked tasks remaining." Keep remaining-task counts location-specific
and derive them only from complete data for that location. Do not aggregate an
exhaustive project count when any in-scope location or nested collection was
omitted.

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

- If a location's `unchecked_tasks` is empty, that location returned no
  unchecked, non-abandoned tasks. Don't invent work, but don't claim another
  location or every plan checkbox is complete. Describe project-wide absence
  only after all in-scope locations returned complete, empty task lists.
- If a location's `recent_commits` is empty, that location has no returned
  history for matching. Continue with other locations and don't guess from
  filesystem state. Describe project-wide absent history only after all
  in-scope locations returned complete, empty histories.

**Noise:**

- If a commit clearly belongs to a *different* feature than any task
  describes, just don't mention it. The output should be tight, not
  exhaustive.

**Freshness:**

- "Freshly refreshed" data is the gold standard. If root `cache_refreshed:
  true`, you can be confident in your matches.
- If the cache was stale but refresh failed (see Step 3), downgrade
  your confidence and tell the user explicitly for every audited location.
- If root `cache_age_seconds` is `null`, freshness is unknown. Don't treat it
  as zero or describe the data as current.
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
