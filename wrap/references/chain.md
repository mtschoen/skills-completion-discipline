# Session chaining

Chain mode runs the normal wrap with Phase 0 branch **w** (wrap with a handoff), then continues in a fresh Claude Code background session. Each link has its own session id, name and transcript, resumable with `claude --resume`. The handoff and resume-prompt contract is harness-neutral; this launch procedure is for Claude Code.

## Triggers and order

The owner can say "wrap and keep going in a fresh session", "wrap and continue", "chain", or "hand off and keep going". The other trigger is agent-statusline's `wrap_nudge.py`, a `UserPromptSubmit` hook that fires once per session past 250K tokens of context. This is a soft nudge: finish the in-flight ask or plan task, then chain at the next natural stopping point. There is no hard ceiling; a session that needs to run long keeps going.

1. Announce **w plus chain mode** and the unfinished asks before Phase 1.
2. Run all normal wrap phases, preparing the handoff during memory offload and finalizing it after cleanup, before Phase 4's closing lines.
3. Apply the stop rule below, then launch and confirm a successor when appropriate.
4. Finish with the attach instructions and wrap sentinel. The finished session simply ends at its sentinel; nothing kills it. Each continuation is a separate session, not `/clear`.

## Handoff contract

Write `~/.claude/handoffs/YYYY-MM-DD-<slug>.md`. Give each link a distinct file (include the chain name and link number in `<slug>`) so the chain's handoffs form its ledger. Start with this YAML header, filling the placeholders and choosing one status:

```yaml
---
chain: <kebab-case chain name, stable across links>
link: <n, 1-based; this session's position>
session_id: <this session's full id>
predecessor_handoff: <path of the previous link's handoff, or null>
status: continue | blocked | done
successor:            # filled after launch; omitted when status != continue
  name: <chain>-<n+1>
  short_id: <shortid>
  session_id: <full id>
---
```

Start a new chain at link 1 with a null predecessor. A resumed link keeps the chain name, advances the link number and points to the handoff it read. Write the complete handoff before launching; add the `successor` block only after confirmation. Omit that block when no successor was confirmed, including a cap stop or failed launch. An existing confirmed successor is reused on a repeated wrap, not launched twice. "Reuse" means verifying it is still alive first: match its recorded session id in `claude agents --json`. If it is alive, keep its recorded identity in the header and launch nothing. If it is gone or stopped, launch a new successor under the same name rule, confirm it, and record the new identity in place of the old one.

Include every required section, writing "None" where empty:

- **Inherited owner rulings (do not reopen):** every ruling copied forward from the predecessor handoff's own inherited block plus its rulings of that session, then this session's new rulings, each tagged with the link that made it ("None" only on link 1 with no rulings). Copy forward in full and never summarize them away, so the newest handoff is self-contained and no ruling disappears after two or more links.
- **Questions waiting for the owner (one per turn, through the question widget)**
- **Next steps, in order**
- **How to run the lanes:** which work went to subagents and which to external harnesses (codex, opencode, agy, kimi, local qwen), with the exact invocations that worked and what bit
- **Worktrees and in-flight work (PRs, background jobs)**

## Stop rule

Choose `continue` when actionable work remains, `blocked` when everything left needs an owner decision, or `done` when no work remains. A `blocked` or `done` handoff ends as a normal wrap without a successor. The safety cap is **10 links**: link 10 can wrap and preserve remaining work as `continue`, but must not launch link 11 or later. State the stop reason in Phase 4. A cancelled or interrupted wrap ends with the interrupted sentinel and no successor launch.

## Resume prompt

Use this fixed template verbatim, substituting the chain name, link numbers and absolute handoff path. Expand the home-directory form of the handoff path for the receiving session.

```text
You are link <n+1> of session chain "<chain>". Before anything else, read the
handoff <absolute handoff path> in full, then continue from its "Next steps,
in order". Honor every ruling under "Inherited owner rulings" without reopening any of them, including those made in earlier links. Keep the standing
routing rules: dispatch subagents for well-specified lanes and route
sustained volume to external harnesses (codex, opencode, agy, kimi, local
qwen) as the handoff's "How to run the lanes" describes; the orchestrator
seat does triage, briefs, review and delicate steps only. Ask owner questions
one per turn through the question widget. When the wrap nudge fires and you
reach a natural stopping point, or the owner asks, wrap and continue the chain
as link <n+2>.
```

## Launch and confirmation

From the same working directory as this session, run:

```text
claude --bg -n "<chain>-<n+1>" --permission-mode <this session's mode> "<resume prompt>"
```

This session's own full id (for the handoff's `session_id` field) is in the `CLAUDE_CODE_SESSION_ID` environment variable of any Bash or PowerShell tool call. The permission mode is the one this session is running in (for example `auto`, `acceptEdits` or `default`); when it cannot be determined, use `default`, never a more permissive mode.

Fill every placeholder and quote for the current shell so the complete resume prompt, including its embedded quotes, arrives as one argument. Pass the current session's permission mode explicitly; do not infer it from defaults or select a more permissive mode.

**Verified on 2026-10-02** on Windows (host chonkers), using Claude Code with `CLAUDE_CODE_CHILD_SESSION=1` inherited from the Bash tool:

- The launch prints `backgrounded - <shortid> - <name>` plus `claude attach <shortid>`.
- `claude agents --json` lists the successor with kind `background`, its full session id and its name.
- Its transcript lands at `~/.claude/projects/<slug>/<session id>.jsonl`.
- Without explicit `--permission-mode`, the background session started in "manual" mode rather than the launching session's mode. That is why the flag is required.

Run `claude agents --json` after launch and match the returned successor name and identity to the background entry. The launch message alone is not confirmation. Record its name, short id and full session id in the handoff header only once confirmed. This successor starts after the Phase 2b cleanup sweep and is the intended continuation. On a repeated wrap the already-confirmed successor exists before Phase 2b, so Phase 2b must leave it running: it is excluded from the sweep and is never stopped as session-started background work.

## Final lines and failure behaviour

For a confirmed successor, name it and give `claude attach <shortid>` (or agent view via `claude agents`), then emit the existing wrap sentinel verbatim as the last line:

> That's a /wrap. Go ahead and close the session.

If launch fails, keep the handoff, say plainly that launch failed and print the exact filled, shell-quoted command for the owner to run by hand from the same working directory. If `claude agents --json` cannot confirm the launch, report it as unconfirmed rather than running; inspect the roster before any retry to avoid a duplicate. Include that uncertainty with the manual command. Do not invent successor ids. A launch failure does not undo the completed wrap; the normal closing sentinel still ends it. If the wrap itself was interrupted, use Phase 4's interrupted sentinel instead.
