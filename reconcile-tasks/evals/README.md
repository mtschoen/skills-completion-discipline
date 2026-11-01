# Per-location reconciliation regression walkthrough

This is a manual prose/behavior regression check for the response contract in
`../SKILL.md`. It does not test a parser or replace an automated agent
evaluation.

## Input

Read [`fixtures/two-locations.json`](fixtures/two-locations.json) as the JSON
response to `project-tracker reconciliation example-project --json`.

The response has root project, freshness, and truncation metadata, but no root
`unchecked_tasks` or `recent_commits`. Its first location, `/example/empty`,
has no tasks or commits. Its second location, `/example/active`, has one
unchecked task and one matching commit. The task belongs to
`/example/active/PLAN.md` at line 3.

Validate the fixture with:

```bash
python -m json.tool reconcile-tasks/evals/fixtures/two-locations.json
```

## Baseline failure

Before the contract correction, applying the skill to this fixture exposed
these failures:

- Step 2 described nonexistent response-root task and commit collections, so
  it did not locate the populated location's actual data.
- The no-history rules could stop the audit at the empty first location. The
  skill did not define how to continue to the populated location.
- The empty-state rules treated an empty task collection as a fully checked
  plan without preserving location scope, which could hide the second
  location's unchecked task.

## Walkthrough

1. Read `truncated` before matching or counting. For the unmodified fixture,
   its `false` value permits exhaustive observations for the returned data.
2. Read `cache_age_seconds` and `cache_refreshed` once from the response root.
   The values `10` and `false` describe fresh data for every location. Do not
   look for freshness fields inside a location.
3. With no explicitly requested location, process both entries of `locations`
   independently. Keep each location's `path` and `role` with its findings.
4. At `/example/empty`, record that this location returned no unchecked,
   non-abandoned tasks and no history. Continue to the next location instead
   of making a project-wide claim or stopping.
5. At `/example/active`, compare its `unchecked_tasks` only with its own
   `recent_commits`. Match "Add export command" to the commit
   `feat: add export command`.
6. Present the candidate with location `/example/active`, role
   `implementation`, absolute source `/example/active/PLAN.md:3`, the raw task
   line `- [ ] Add export command`, and the matching commit evidence. A
   relative display such as `PLAN.md:3` must name its location.
7. Do not edit the task. Present the four existing operations and wait for
   owner approval. If check is approved, use `source_file_absolute`, line 3,
   and expected title "Add export command".
8. Report remaining-task counts by location. Do not claim that the project is
   fully checked or has no history.

## Expected observations

The walkthrough passes only when the empty first location is reported locally
and does not stop the audit, and the populated second location produces a
candidate with its own commit evidence and `/example/active/PLAN.md:3`.
Freshness comes from the root, no task is edited without approval, and no
project-wide fully-checked or no-history claim is made.

## Failure conditions

Fail the walkthrough if it looks for root task or commit arrays, stops after
the first empty location, combines locations' histories, loses the absolute
task-file path, treats a null cache age as zero, or reports an exhaustive
project summary from partial data.

## Manual variations

Change the fixture in memory only and repeat the relevant steps:

- **Reverse location order.** The findings and candidate evidence stay the
  same; location order does not change the audit result.
- **Add an unmatched task to the empty location while leaving its history
  empty.** Report no evidence for that task at `/example/empty`. Do not borrow
  the `/example/active` commit, and continue processing other locations.
- **Set root freshness to stale and unrefreshed, or set its age to null.**
  Carry the stale-cache warning to every audited location. A null age means
  freshness is unknown, not fresh or zero seconds old.
- **Set `truncated: true`.** Retry with a larger limit. If truncation remains
  at the maximum, use the direct-file fallback or label the audit partial
  before any counts or project-wide summary. Omitted locations also prevent an
  exhaustive project summary.
