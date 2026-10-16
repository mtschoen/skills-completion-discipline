# Session chaining

Chain mode runs the normal wrap with Phase 0 branch **w** (wrap with a handoff), then hands off to a fresh Claude Code session that the owner starts from a printed launch command, or that opens in a new visible console window where the machine has a desktop. Each link has its own session id, name and transcript, resumable with `claude --resume`. The handoff and resume-prompt contract is harness-neutral; this launch procedure is for Claude Code.

## Triggers and order

The owner can say "wrap and keep going in a fresh session", "wrap and continue", "chain", or "hand off and keep going". The other trigger is agent-statusline's `wrap_nudge.py`, a `UserPromptSubmit` hook that fires once per session past 250K tokens of context. This is a soft nudge: finish the in-flight ask or plan task, then chain at the next natural stopping point. There is no hard ceiling; a session that needs to run long keeps going.

1. Announce **w plus chain mode** and the unfinished asks before Phase 1.
2. Run all normal wrap phases, preparing the handoff during memory offload and finalizing it after cleanup, before Phase 4's closing lines.
3. Apply the stop rule below, then print the launch command (or open the successor's window) when appropriate.
4. Finish with the launch line and the chained sentinel (see Final lines). The finished session simply ends at its sentinel; nothing kills it. Each continuation is a separate session, not `/clear`.

## Handoff contract

Write `~/.claude/handoffs/YYYY-MM-DD-<slug>.md`. Give each link a distinct file (include the chain name and link number in `<slug>`). The chain's ledger is the newest handoff plus the forge (PRs, issues, commits), not a pile of files. Start with this YAML header, filling the placeholders and choosing one status:

```yaml
---
chain: <kebab-case chain name, stable across links>
link: <n, 1-based; this session's position>
session_id: <this session's full id>
predecessor_handoff: <path of the previous link's handoff, or null>
status: continue | blocked | done
successor:            # omitted when status != continue
  name: <chain>-<n+1>
  launch: owner-started | window
  session_id: null | <full id>  # null for owner-started (pending); confirmed full session id for window
---
```

Start a new chain at link 1 with a null predecessor. A resumed link keeps the chain name, advances the link number and points to the handoff it read. Write the complete handoff before the launch step. For `status: continue`:

- An owner-started launch records `launch: owner-started` with `session_id: null`, because the session has not started yet and remains pending until the owner runs the printed command.
- A windowed launch opens a console window, confirms startup via `claude agents --json`, and records `launch: window` with the confirmed successor's full `session_id`.

**Consume the predecessor.** Once this link has read the predecessor handoff in full and written its own complete handoff, it deletes the predecessor handoff (the `predecessor_handoff` path) and the predecessor's sibling `.resume-prompt.txt`. Order matters: write the new handoff, verify it exists and parses, then delete the old files; never delete first. The newest handoff is self-contained by contract, so nothing is lost. A link that ends `blocked` or `done` deletes its predecessor the same way, and its own handoff remains as the chain's terminal record. Link 1 has no predecessor and deletes nothing.

Fast mode (`--fast`) defers predecessor deletion: SKILL.md and `references/fast-mode.md` guarantee that fast mode is additive only and never deletes files. Under `--fast`, leave the predecessor handoff and prompt files untouched and report the deferred file cleanup in the Phase 4 summary.

Omit the `successor` block for `blocked`, `done` and a cap stop. If window launch or confirmation fails, fall back to `launch: owner-started` with `session_id: null` and print the fallback command.

On a repeated wrap:

- If the handoff already recorded `launch: owner-started`, it remains pending: reprint the same launch command.
- If the handoff already recorded `launch: window`, verify liveness before reusing it: match its recorded session id in `claude agents --json`. If it is alive, keep its recorded identity and open no second window. If it is gone, stopped, or not listed, do not assume it is running: open a new window and confirm it (or fall back to printing the launch command with `launch: owner-started`).

Include every required section, writing "None" where empty:

- **Done this link:** what this link completed, with the forge or memory record of each item ("None" where empty)
- **Inherited owner rulings (do not reopen):** every ruling that still constrains future work, from the predecessor handoff's inherited block, its rulings of that session, and this session's new rulings, copied verbatim and each tagged with the link that made it ("None" only when no ruling is live). Drop a ruling once the work it governed is complete and verified AND its record exists on the forge (merged PR, closed issue, commit) or in a memory note; name that record in this link's "Done this link" section when dropping it. Rulings about standing policy (how to run things, what never to do) are always carried. Never summarize a carried ruling, so the newest handoff is self-contained.
- **Questions waiting for the owner (one per turn, through the question widget)**
- **Next steps, in order.** Every item must retain an explicit unchanged-carry count tag: `[carried: 0]` when newly introduced or when its scope is substantively modified; `[carried: <count + 1>]` when copied forward without material change from the predecessor handoff. An item carried unchanged for two links (`[carried: 2]`) reaches the limit: this link must either complete it (recorded in "Done this link"), convert it to a tracked forge issue, or drop it with a stated reason in the handoff; it cannot ride a third time (`[carried: 3]` is prohibited). Before deleting the predecessor handoff, the successor must inspect the predecessor's tags, update unchanged items to `[carried: <count + 1>]` (or `[carried: 0]` if substantively modified), enforce retirement on any item that reached the two-link limit, and verify that all carried items in the new handoff comply with the limit.
- **How to run the lanes:** which work went to subagents and which to external harnesses (codex, opencode, agy, kimi, local qwen), with the exact invocations that worked and what bit
- **Worktrees and in-flight work (PRs, background jobs)**

## Stop rule

Choose `continue` when actionable work remains, `blocked` when everything left needs an owner decision, or `done` when no work remains. A `blocked` or `done` handoff ends as a normal wrap without a successor. The safety cap is **10 links**: link 10 can wrap and preserve remaining work as `continue`, but must not launch link 11 or later. State the stop reason in Phase 4. A cancelled or interrupted wrap ends with the interrupted sentinel and no successor launch.

## Resume prompt

Use this fixed template verbatim, substituting the chain name, link numbers and absolute handoff path. Expand the home-directory form of the handoff path for the receiving session.

```text
You are link <n+1> of session chain "<chain>". Before anything else, read the
handoff <absolute handoff path> in full, then continue from its "Next steps,
in order". After writing your own complete handoff, delete that handoff and its
.resume-prompt.txt (defer deletion under --fast and report the deferred cleanup in the summary). Honor every ruling under "Inherited owner rulings" without reopening any of them, including those made in earlier links. Keep the standing
routing rules: dispatch subagents for well-specified lanes and route
sustained volume to external harnesses (codex, opencode, agy, kimi, local
qwen) as the handoff's "How to run the lanes" describes; the orchestrator
seat does triage, briefs, review and delicate steps only. Ask owner questions
one per turn through the question widget. When the wrap nudge fires and you
reach a natural stopping point, or the owner asks, wrap and continue the chain
as link <n+2>.
```

## Launch

The wrap does not start the successor itself in the background. After cleanup and before Phase 4's final lines it prints the exact launch command for the owner to run, so the owner sees the session start, answers its first permission prompt and controls its mode. This session's permission mode is not forwarded: the successor starts in the mode the owner's own settings give it.

**Printed command (the default, and the only path on a host with no desktop).** Print one line, copy-pasteable, to run from this session's working directory:

```text
claude -n <chain>-<n+1> --model <model> '<resume prompt>'
```

Fill `<model>` with this session's model alias or id (for example `opus`). Fill `<resume prompt>` with the fixed template above, filled in and collapsed to a single line (line breaks become spaces), and quote it literally for the owner's shell so the prompt arrives as one argument without shell evaluation. In a POSIX shell, wrap the prompt in single quotes (`'...'`) and escape each embedded single quote (`'`) as `'\''` (close single quote, escaped single quote, reopen single quote). Because single quotes suppress all POSIX shell substitutions, dollar signs (`$`), command substitutions (`$(...)`), backticks (``` `...` ```), backslashes (`\`), and double quotes (`"`) are preserved literally without expansion or execution. Print the command in a fenced block under a short lead-in naming the working directory to run it from. Also write the filled prompt to `~/.claude/handoffs/<same slug>.resume-prompt.txt`, beside the handoff, for the owner to paste from if the one-line form is awkward. Record `launch: owner-started` with `session_id: null` in the handoff header.

**New visible console window (optional, on a host with a desktop).** The prompt is read from the prompt file above, because Windows Terminal splits its command line at every semicolon and the prompt contains them. On Windows with Windows Terminal (`wt.exe` on PATH), from the PowerShell tool:

```text
wt.exe -w new -d "<this session's working directory>" pwsh -NoExit -File "<wrap skill directory>\scripts\launch-chain-successor.ps1" -Name "<chain>-<n+1>" -PermissionMode <this session's mode> -PromptFile "<absolute prompt file path>"
```

`scripts/launch-chain-successor.ps1` removes the variables the window inherits from the tool call (`NO_COLOR`, `CLAUDECODE`, `CLAUDE_PID`, every `CLAUDE_CODE_*`) and then runs `claude -n <name> --permission-mode <mode> <prompt>`. Never start `claude` in the new window without that scrub. The permission mode is the one this session is running in (for example `auto`, `acceptEdits` or `default`); when it cannot be determined, use `default`, never a more permissive mode.

**Confirmation and identity:** After opening the window, confirm that the successor actually started: run `claude agents --json` and match the returned successor name to an entry with kind `interactive`. Once confirmed, record `launch: window` and its full session id in the handoff header. If `wt.exe` fails to start, or if `claude agents --json` does not confirm a running successor within 20 seconds (for example, if `launch-chain-successor.ps1` failed on a missing or empty prompt file), treat the window launch as failed: do not record an unconfirmed window, set `launch: owner-started` with `session_id: null`, state plainly that window launch failed or was unconfirmed, and print the copy-pasteable command as the fallback.

This session's own full id (for the handoff's `session_id` field) is in the `CLAUDE_CODE_SESSION_ID` environment variable of any Bash or PowerShell tool call.

Observed on Windows (host chonkers, 2026-10-06): a window opened with `wt.exe -w new ... pwsh -NoExit -Command "claude ..."` and no scrub rendered without colors, because `NO_COLOR=1` was inherited. The same window opened through `launch-chain-successor.ps1` rendered in color, and `claude agents --json` listed it within 20 seconds with kind `interactive`, its name and its own full session id.

A printed command leaves nothing running, so Phase 2b has nothing to exclude. A confirmed windowed successor is the intended continuation: Phase 2b leaves it running.

## Final lines and failure behaviour

For a `continue` handoff, name the successor and give the launch line: repeat the printed command (or, for a confirmed window, say "open in a new terminal window") immediately before the sentinel. Then emit the chained sentinel verbatim as the last line, with `<n>` the current link number and `<chain>-<n+1>` the successor's session name (for example `settle-and-cure-6`):

> `That was a chained /wrap. Link <n> is closed; start <chain>-<n+1> with the command above.`

It is emitted only when the wrap printed a successor launch command or confirmed a window launch. A wrap that stops (status `blocked` or `done`, or the 10-link cap) has no successor and ends with the completed sentinel:

> That's a /wrap. Go ahead and close the session.

If a window launch fails or startup cannot be confirmed, keep the handoff, say plainly that window launch failed or was unconfirmed, set `launch: owner-started` with `session_id: null`, and print the exact copy-pasteable fallback command as above. Do not invent successor ids. A launch problem does not undo the completed wrap; a printed fallback command still ends with the chained sentinel. If the wrap itself was interrupted, use Phase 4's interrupted sentinel instead.
