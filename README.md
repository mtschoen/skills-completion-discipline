# Completion discipline

Eight skills that decide what an agent owes the work at the point it stops.

Coding agents are systematically overconfident about being finished. They
report success from the absence of an error rather than the presence of
evidence, they declare a feature finished without running it, and they quietly
lower a bar rather than clear it. None of that is a knowledge gap: the agent
usually knows what it should have checked. It just stopped one step early,
because stopping felt like finishing.

Stopping is not a single moment. An agent stops when it claims a change is
done, and it stops again when the session ends and the change is left sitting
in a repo alongside everything else the work disturbed: an unpushed branch, a
plan that no longer matches what shipped, scratch directories that outlived
their purpose. Both are handovers, and the last step goes unpaid at either one.
These skills are the gates that make the agent pay it. Each fires at a handover
and asks a question that has to be answered before the work can be handed over.

| Skill | The question it forces |
| --- | --- |
| [`smoke-test`](smoke-test/) | Did you actually run it? |
| [`maintaining-full-coverage`](maintaining-full-coverage/) | Did the coverage and lint bars hold, or did you move them? |
| [`docs-update`](docs-update/) | Did this change make any documentation lie? |
| [`escalate-over-shortcut`](escalate-over-shortcut/) | Is this a solution, or a suppression of the problem? |
| [`reconcile-tasks`](reconcile-tasks/) | Does the plan still describe what actually shipped? |
| [`wrap`](wrap/) | Is the session actually closed out, or just abandoned? |
| [`project-maintenance`](project-maintenance/) | What did the work leave behind in the repo? |
| [`machine-maintenance`](machine-maintenance/) | What did the sessions leave behind on the whole machine? |

One companion is a Claude Code mod rather than a skill: [`idle-wrap`](idle-wrap/)
runs `/wrap --fast` in a session that has sat idle near the prompt-cache cliff,
so an abandoned session is wrapped instead of compacted.

They compose deliberately, and in that order. The first four settle the change
itself: `smoke-test` proves it runs, `maintaining-full-coverage` proves it did
not cost quality elsewhere, `docs-update` catches the prose it invalidated, and
`escalate-over-shortcut` catches the case where the agent's own draft is a
dressed-up workaround. The last four settle everything around it:
`reconcile-tasks` makes the project's written record agree with its commit
history, `wrap` closes the session so nothing is left stranded on an unpushed
branch, `project-maintenance` sweeps what accumulated in the repo across
however many sessions the work took, and `machine-maintenance` sweeps what
accumulated across the host itself.

Most invocations end with nothing to report. That is the healthy case. The
value is the check, not the finding.

## Design notes

**Gates, not advice.** Each skill defines a concrete condition and a concrete
verification command, because a gate that can be satisfied by an agent's own
judgement is not a gate.

**No silent lowering.** Every one of these treats moving the bar as the failure
mode rather than the remedy. A red result is a worklist, not a verdict on
whether the bar was right.

**Portable.** These name actions, not tools. Where a specific tool would make a
step easier it is a soft dependency with a written fallback: `project-tracker`
hands `reconcile-tasks` and `project-maintenance` their data, and without it
both read `PLAN.md`, `TODO.md`, and `git log` themselves. Every skill here
works on a machine that has none of it.

## Installing

These skills are distributed through the
[skills-dev](https://github.com/mtschoen/skills-dev) umbrella, which carries
the installer and can mirror them into Claude Code, Codex, opencode,
Antigravity, and Hermes. Each skill directory here is self-contained: `SKILL.md`
at its root plus optional `references/`, `scripts/`, and `assets/`.

## Related families

- [skills-working-method](https://github.com/mtschoen/skills-working-method) -
  habits applied while the work is happening, rather than gates at the end.
- [skills-orchestration](https://github.com/mtschoen/skills-orchestration) -
  what changes when work outgrows one agent, one machine, or one budget.
