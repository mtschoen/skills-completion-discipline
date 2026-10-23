---
name: docs-update
description: "Use when a change is verified (smoke test passed or prose-only N/A), no edits remain, and you are about to declare done, commit, push to main, or open a PR. Checks README, AGENTS.md, other repo docs and inline comments for drift; it runs once after the change settles."
---

# Docs Update

## Applicability

Use after you've finished and verified a change (smoke test passed, or smoke-test concluded N/A for a prose-only change) and have no further edits planned - before declaring work done, committing, pushing to main, or opening a PR. Checks whether the change made any documentation lie: README, AGENTS.md, other in-repo docs, inline doc comments. Most invocations end 'no docs affected' - that's healthy; the value is the check. Does NOT fire per-edit mid-work.

## The Problem This Solves

Code changes silently invalidate the prose that describes them. A renamed flag, a moved command, a changed default, a deleted helper - and now the README, the AGENTS.md build instructions, or a docstring is quietly lying. The next reader (often a future agent session) trusts the stale doc and wastes time, or worse, acts on it.

Updating docs after *every* edit is wasted effort - the change might get undone or redone differently. So there is no natural per-edit moment, and docs rot. The fix is to anchor the check to one specific moment: after the change has settled.

## Where This Fits

docs-update is the step right after smoke-test in the same completion ritual. It is a sibling skill, sequenced second:

```text
finish change -> project gates (tests / lint / coverage) -> smoke-test (does it work? may conclude N/A for prose-only changes) -> docs-update (do the docs still tell the truth?) -> declare done / commit / push / open PR
```

The guard that keeps this from firing per-edit: run it only once the change is **verified working AND you have no further edits planned**. Before that, any doc you touch might be invalidated again by your next edit. After that, the change is real and the docs either match it or they don't.

## When to Run

Run once, after smoke-test passes and before you declare done / commit / push to main / open a PR, whenever the change altered something a doc could describe.

## When NOT to Run

- Mid-work, between edits, when more changes are still coming. Wait until the change settles.
- Changes with no externally-describable surface: a comment-only edit, a whitespace pass, an internal variable rename that nothing documents.
- When the smoke test failed. Fix the code first; do not document a broken change.

## The Check

1. **What did this change alter that is described somewhere?** Public API, CLI flags, commands, setup / build / test steps, config keys, environment variables, architecture, conventions, observable behavior, defaults.
2. **For each surface below, ask: does this change make any statement here false or incomplete?**
3. **Update only what drifted.** Minimal, justified edits that bring the doc back in line with reality - not a gratuitous rewrite, not a style pass, not new documentation the change didn't call for.
4. **Bundle the doc edits into the same commit / PR as the code** so a reviewer sees the behavior change and the doc change side by side.
5. **If unsure whether a doc statement is load-bearing** (would removing or changing it mislead someone?), surface it to the user rather than silently editing or silently skipping.
6. **State the docs impact when you report completion** - even "no docs affected, checked README + AGENTS.md." Brief is fine. This is the docs analogue of smoke-test's "report what you verified."

## Surfaces To Check

| Surface | What drifts | Why it matters |
|---------|-------------|----------------|
| README | Usage, examples, flag / command references, feature list, install steps | First thing a human reads; wrong examples waste real time |
| AGENTS.md | Build / test commands, conventions, architecture pointers | A future agent session trusts these as ground truth; drift here actively misleads |
| Other in-repo docs | ARCHITECTURE.md, `docs/`, CHANGELOG, API reference | Longer-form descriptions of behavior the change may have altered |
| Inline doc comments | Docstrings, XML doc, module headers next to the changed code | The most local docs; easiest to leave stale after a refactor |

## State the Docs Impact

When you finish, say what you checked and what you changed - concretely, briefly:

- "Updated README usage example for the renamed `--out` flag and the docstring on `export()`. No other docs affected."
- "No docs affected - checked README and AGENTS.md, neither references the internal cache layer I changed."

A bare "done" hides whether you even looked. The one-line docs-impact note is the evidence that you did.

## When You'll Be Tempted To Skip

The check matters most exactly when you want to skip it:

- **Late in a long session**, when you just want to wrap up. This is when drift is most likely and least likely to be noticed.
- **After a "trivial" change** - a rename, a default flip, a moved command. These are precisely the changes that invalidate a one-line doc reference.
- **After a long debugging win**, when the fix finally landed and you want to call it done. The fix may have changed behavior a doc still describes the old way.
- **When the docs live somewhere slightly out of the way** (a `docs/` folder, a CHANGELOG you have to open). Out of sight is how docs rot.

In all of these: run the check. It is usually seconds, and it ends in "no docs affected" more often than not. The cost is small; the cost of a lying doc compounds.

## Non-Goals

- **Authoring brand-new documentation from scratch.** This skill fixes drift in docs the change touched, not missing docs in general.
- **Style, grammar, or formatting nitpicking.** Only fix statements the change made false or incomplete.
- **Updating docs for changes you did not make.** Pre-existing drift you happen to notice can be surfaced to the user, but it is not this change's job to fix it.
- **A hard gate.** This is a disposition, not a CI check that blocks. The judgment of "did this change make a doc lie" stays with you.
