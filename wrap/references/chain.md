# Session chaining

Chain mode runs the normal wrap with Phase 0 branch **w** (wrap with a handoff), then hands off to a fresh Claude Code session. The wrap starts that session itself, in a new terminal window or a tmux session, whenever the automatic-launch gates pass; otherwise it prints a launch command for the owner to paste. Each link has its own session id, name and transcript, resumable with `claude --resume`. The handoff and resume-prompt contract is harness-neutral; this launch procedure is for Claude Code, with codex and opencode adapters under Launch.

## Triggers and order

The owner can say "wrap and keep going in a fresh session", "wrap and continue", "chain", or "hand off and keep going". The other trigger is agent-statusline's `wrap_nudge.py`, a `UserPromptSubmit` hook that fires once per session past 250K tokens of context. This is a soft nudge: finish the in-flight ask or plan task, then chain at the next natural stopping point. There is no hard ceiling; a session that needs to run long keeps going.

1. Announce **w plus chain mode** and the unfinished asks before Phase 1.
2. Run all normal wrap phases, preparing the handoff during memory offload and finalizing it after cleanup, before Phase 4's closing lines.
3. Apply Chain scope and the stop rule below, choose the successor's model, then run the automatic-launch gates: start the successor, or print its launch command with the reason it was not started.
4. Finish with the launch state and the matching chained sentinel (see Final lines). The finished session simply ends at its sentinel; nothing kills it. Each continuation is a separate session, not `/clear`.

## Handoff contract

Write `~/.claude/handoffs/YYYY-MM-DD-<slug>.md`. Give each link a distinct file (include the chain name and link number in `<slug>`). The chain's ledger is the newest handoff plus the forge (PRs, issues, commits), not a pile of files. Start with this YAML header, filling the placeholders and choosing one status:

```yaml
---
chain: <kebab-case chain name naming its goal; stable until the chain ends or re-scopes>
goal: <one line: what finished looks like for this chain>
link: <n, 1-based; this session's position>
session_id: <this session's full id>
predecessor_handoff: <path of the previous link's handoff, or null>
rescoped_from: <old chain>-<n>   # only on link 1 of a re-scoped chain; see Chain scope
status: continue | blocked | done
attendance: attended | unattended   # always present; see Attendance
auto_through: <link number>         # always present; 10 at link 1; see Link budget
estimated_links_remaining: <k>      # only when the chain paused at its link budget
successor:            # omitted when status != continue
  name: <chain>-<n+1>
  model: <model alias or id chosen for the successor; see Successor model>
  launch: window | tmux | owner-started
  session_id: null | <full id>  # null for owner-started (pending); confirmed full session id for window and tmux
  not_started_reason: <reason>  # only for owner-started; one of the reasons under Automatic launch
---
```

Start a new chain at link 1 with a null predecessor, a name that says what the chain is for, and a `goal` line. A resumed link keeps the chain name and goal, advances the link number and points to the handoff it read, unless Chain scope below ends or re-scopes the chain. A handoff written before the `goal` field existed takes its goal from the chain name and its link 1 work. Write the complete handoff before the launch step. For `status: continue`:

- An automatic launch opens a terminal window or a tmux session, confirms startup via `claude agents --json`, and records `launch: window` or `launch: tmux` with the confirmed successor's full `session_id`.
- An owner-started launch records `launch: owner-started` with `session_id: null` and its `not_started_reason`, because the session has not started yet and remains pending until the owner runs the printed command.

**Consume the predecessor.** Once this link has read the predecessor handoff in full and written its own complete handoff, it deletes the predecessor handoff (the `predecessor_handoff` path) and the predecessor's sibling `.resume-prompt.txt`. Order matters: write the new handoff, verify it exists and parses, then delete the old files; never delete first. The newest handoff, with the memory notes it names, is self-contained by contract, so nothing is lost. A link that ends `blocked` or `done` deletes its predecessor the same way, and its own handoff remains as the chain's terminal record. Link 1 has no predecessor and deletes nothing.

Fast mode (`--fast`) defers predecessor deletion: SKILL.md and `references/fast-mode.md` guarantee that fast mode is additive only and never deletes files. Under `--fast`, leave the predecessor handoff and prompt files untouched and report the deferred file cleanup in the Phase 4 summary.

Omit the `successor` block for `blocked` and `done`. If an automatic launch or its confirmation fails, fall back to `launch: owner-started` with `session_id: null` and print the fallback command.

On a repeated wrap:

- If the handoff already recorded `launch: owner-started`, it remains pending: reprint the same launch command.
- If the handoff already recorded `launch: window` or `launch: tmux`, verify liveness before reusing it: match its recorded session id in `claude agents --json`. If it is alive, keep its recorded identity and start no second successor. If it is gone, stopped, or not listed, do not assume it is running: launch again and confirm it (or fall back to printing the launch command with `launch: owner-started`).

Include every required section, writing "None" where empty:

- **Done this link:** at most ten one-line entries, each naming its forge or memory record ("None" where empty). This section is never carried into the next handoff.
- **Inherited owner rulings (do not reopen):** only rulings that still constrain the next steps, one line each, tagged with the link that made it ("None" when none is live). A ruling about work still in flight is quoted verbatim, trimmed to its operative sentence. A standing-policy ruling (how to run things, what never to do) does not ride in the handoff: the first link that carries it records it in a memory note (or the repository's `AGENTS.md` when it is repository policy) and the handoff keeps a one-line pointer naming that record, only while the next steps depend on it. Drop a ruling once the work it governed is complete and its record exists on the forge or in memory, naming that record under "Done this link". Drop a one-time answer in the link that carries it out. When the owner gives the same answer again (for example granting the same permission-mode switch), update the existing line's link tag; never add a second line.
- **Questions waiting for the owner (one per turn, through the question widget):** links to the `owner-decision` items filed for questions still open at wrap (see Owner questions at wrap); only the link-budget question may be written out here, since it belongs to the session chain
- **Next steps, in order.** Every item must retain an explicit unchanged-carry count tag: `[carried: 0]` when newly introduced or when its scope is substantively modified; `[carried: <count + 1>]` when copied forward without material change from the predecessor handoff. An item carried unchanged for two links (`[carried: 2]`) reaches the limit: this link must either complete it (recorded in "Done this link"), convert it to a tracked forge issue, or drop it with a stated reason in the handoff; it cannot ride a third time (`[carried: 3]` is prohibited). Before deleting the predecessor handoff, the successor must inspect the predecessor's tags, update unchanged items to `[carried: <count + 1>]` (or `[carried: 0]` if substantively modified), enforce retirement on any item that reached the two-link limit, and verify that all carried items in the new handoff comply with the limit.
- **How to run the lanes:** only what this link learned or what differs from the lane recipes already recorded; stable invocations live in a memory note or skill and are named, not copied
- **Worktrees and in-flight work (PRs, background jobs)**

**Size budget.** A handoff stays under 12 KB (`wc -c`) and aims for about 6 KB; the successor reads all of it before its first action, so every kilobyte is paid again on every link. Check the size after writing and before deleting the predecessor. Over budget means cut: move standing policy and stable recipes into memory notes and leave pointers, shorten "Done this link", and retire carried steps to forge issues. Never split the handoff into a second file.

## Attendance

The `attendance` header field tells the successor whether the owner is there to answer questions. Every handoff sets it.

- Set `unattended` when the owner said in this link that they are leaving or not to wait for them (for example "going to bed", "heading out", "full send", "don't ask", "keep going without me"), or when the predecessor handoff says `unattended` and the owner has sent no message in this link besides the resume prompt.
- Set `attended` in every other case. Any owner message in this link besides the resume prompt makes it `attended`, unless that message itself says the owner is leaving or not to wait.

An unattended link runs to its stopping point without waiting on the owner:

- It never calls the question widget and never ends a turn with a question. Owner questions it cannot ask become `owner-decision` items at wrap (see Owner questions at wrap).
- On a reversible choice it takes the conventional default, records the choice and its reason under Done this link, and files the matching question so the owner can overturn it.
- It parks irreversible or owner-only steps in Next steps and moves on to the next step. These include merging to a protected branch, closing issues or PRs, force-pushing, deleting branches, and anything sent to an outside person or service. An inherited ruling that approves that specific action unparks it.
- It still stops at a permission prompt, which no wording can prevent. An unattended successor is always started in `auto` permission mode (see Successor permission mode).

## Chain scope

A chain exists to reach its `goal`, not to carry whatever work is left. At every chain wrap, before applying the stop rule, compare this link's work and the remaining Next steps with the goal:

- **Goal met.** The chain is finished: choose `done`, even when unrelated work remains. Unrelated leftovers become forge issues, memory notes or `owner-decision` items; if they need a continuing session, start a new chain for them as described under Pivot. Never keep a finished chain alive to carry leftovers. The link that ends a chain `done` closes it out in the mode the owner asked for: a requested `--fast` is never silently upgraded to a full wrap. A full wrap, after the consume step, removes whatever the chain left behind: earlier handoffs and `.resume-prompt.txt` files of this chain that deferred deletions left in the handoffs folder, chain artifact folders whose content is recorded on the forge or in memory, and the chain's merged worktrees, through the normal Phase 3 approval batch. Under `--fast`, keep the terminal handoff, defer every close-out deletion like any other fast-mode deletion, and list the deferred cleanup in the Phase 4 summary; a later wrap the owner explicitly requests as a full wrap performs them. An unattended link parks the same cleanup in Next steps for the owner. Its own terminal handoff stays as the record in every mode.
- **Pivot.** The chain has drifted when the lead Next step, and most of the rest, serve a different goal (for example a feature chain whose remaining work is now maintenance and status checks). Re-scope instead of carrying the old name forward. Write this link's handoff as link 1 of a new chain: a new `chain` name and `goal` for the work that remains, `rescoped_from: <old chain>-<n>`, and `predecessor_handoff` still pointing at the handoff this link read, so the consume step works unchanged. Steps that still serve the old goal stay in Next steps only when the new goal covers them; otherwise they become forge issues. Carry counts, rulings and questions carry over unchanged. The successor is `<new chain>-2`, and the link budget restarts with the new chain (`auto_through: 10`). The owner asking mid-session to pivot or change the goal is a re-scope the owner has already approved: the next handoff is link 1 of the new chain.
- **Still on goal.** Keep the name and goal and apply the stop rule.

Sweeps and audits file unrelated or new-scope findings, and any findings after the goal is met, as forge issues for a later campaign; findings required to meet the existing goal stay in Next steps, while unrelated or post-goal findings do not extend this chain's goal or Next steps unless the owner moves the finish line (a re-scope the owner approved).

## Owner questions at wrap

A question still open when the link ends becomes an `owner-decision` issue on the forge of the right repo, created with the label in the creation request and carrying the decision context and the recommended answer. The handoff section lists the links instead of holding the question. Attended sessions still ask one question per turn through the widget; this covers only what is open at wrap.

Announce an end or a re-scope with the w plus chain mode announcement before Phase 1, naming the old chain, the new one and the reason, and repeat it in Phase 4. An attended link proposes the new name in that announcement, and the owner can rename it. An unattended link never re-scopes on its own, because re-scoping restarts the link budget: it keeps the chain name and files the proposed re-scope as an `owner-decision` item. Ending a chain whose goal is met (`done`) needs no owner.

## Stop rule

Apply Chain scope first. Choose `continue` when actionable work remains, `blocked` when everything left needs an owner decision, or `done` when no work remains. For an unattended link, parked steps count as needing an owner decision, so a link with only parked steps left chooses `blocked`. A `blocked` or `done` handoff ends as a normal wrap without a successor. State the stop reason in Phase 4. A cancelled or interrupted wrap ends with the interrupted sentinel and no successor launch. A `continue` handoff always has a successor; the link budget and the other gates under Automatic launch decide only whether the wrap starts it or the owner does.

## Link budget

`auto_through` is the highest link number the wrap may start automatically. Link 1 writes `auto_through: 10`. Every later link copies the value from the handoff it read; only the owner changes it. A handoff written before the field existed counts as `auto_through: 10`.

When this is link `n` with status `continue` and `n+1` is greater than `auto_through`, the chain pauses instead of launching:

1. Estimate how many more links the goal needs: one number `k`, with a one-line basis taken from the remaining Next steps. Write it as `estimated_links_remaining` and state it in Phase 4.
2. Attended, outside `--fast`: ask one question before the launch step, with the estimate in the question text. The options are: authorize automatic links through link `n+k`; continue in manual mode, one pasted command per link; stop here.
   - **Authorize:** write `auto_through: <n+k>`, remove `estimated_links_remaining` and `successor.not_started_reason`, and retire the answered budget question from Questions waiting for the owner before running the remaining gates now. If another gate fails, record that gate's reason; the budget authorization still stands.
   - **Manual mode:** leave `auto_through` unchanged and print the launch command with reason `manual mode`. Record the choice as an inherited owner ruling so it travels to the next link. Every later link is also past the budget, so it prints its command the same way without asking again, until the owner raises the budget. A handoff whose header records `launch: owner-started` with `not_started_reason: manual mode` carries that ruling: the successor honors it, asks no budget question at startup or at its own wrap, and prints the command with reason `manual mode`.
   - **Stop here:** print the launch command with reason `link budget`, so the chain can be picked up later.
3. Unattended, under `--fast`, or when the question is dismissed: print the launch command with reason `link budget`. An attended successor asks the question in step 2 as its first owner question only for an unresolved budget pause: the predecessor records `successor.launch: owner-started` with `successor.not_started_reason: link budget`, and the successor's current link number exceeds `auto_through`. Use the recorded estimate. An inherited manual-mode ruling is never reopened, so that successor prints its own launch command with reason `manual mode` instead of asking. An unattended successor does not ask: it keeps the budget question in its handoff under Questions waiting for the owner, does its work, and at its own wrap prints the launch command with reason `link budget` again.

When an extended budget runs out, the chain pauses again the same way. Never get past the budget by renaming the chain, re-scoping it, or starting a new chain for the same goal: a new name for the same goal is not a pivot, and the link count carries. Only a re-scope under Chain scope restarts the budget.

## Successor model

Choose the successor's model on purpose, for the work its first Next steps need. This session's model is not the default. The choice is a judgment call; for example, a link that opens with design, ideation or an ambiguous decision suits the strongest model available (Fable, where the account has it), and a link that executes a written plan or well-defined tasks suits Opus. Weigh quota headroom as well (see the quota gate under Automatic launch).

Record the choice as `successor.model`, pass it as `--model` in every launch form, and say in one Phase 4 line which model the next link runs on and why.

## Resume prompt

Use this fixed template verbatim, substituting the chain name, link numbers and absolute handoff path. Expand the home-directory form of the handoff path for the receiving session.

```text
You are link <n+1> of session chain <chain>. Before anything else, read the
handoff <absolute handoff path> in full, then continue from its section Next steps,
in order. After writing your own complete handoff, delete that handoff and its
.resume-prompt.txt (defer deletion under --fast and report the deferred cleanup in the summary). Honor every ruling under Inherited owner rulings without reopening any of them, including those made in earlier links. Keep the standing
routing rules: dispatch subagents for well-specified lanes and route
sustained volume to external harnesses (codex, opencode, agy, kimi, local
qwen) as the handoff section How to run the lanes describes; the orchestrator
seat does triage, briefs, review and delicate steps only. Obey the attendance
field in the handoff header. When it is unattended, the owner is away: never
call the question widget or end a turn on a question; file open owner questions as
owner-decision items, take the conventional default on reversible choices and record
it, park irreversible or owner-only steps and move on, and wrap with status
blocked once only parked steps remain. Any owner message in this session
besides this resume prompt makes it attended, unless that message says the
owner is leaving or not to wait, which makes it unattended. When it is
attended, ask owner questions one per turn through the
question widget. Copy auto_through from the handoff header into your own
handoff unchanged unless the owner changes it. Ask the startup link budget
question only when this session is attended, the predecessor records
successor.launch: owner-started with successor.not_started_reason: link budget,
and your current link number exceeds auto_through. For that unresolved pause,
ask the question from the wrap skill chain reference before other work, using
estimated_links_remaining. An estimate alone does not reopen an authorization.
Even a one-link extension is checked again only at your wrap, when deciding
whether to start the following link. When the header records
not_started_reason: manual mode, an inherited manual-mode ruling is never
reopened, so print the launch command with reason manual mode at your wrap
instead of asking. When the wrap nudge fires and you
reach a natural stopping point, or the owner asks, wrap and continue the chain
as link <n+2>.
```

## Launch

### Automatic launch

Automatic launch is the rule. After cleanup and before Phase 4's final lines, the wrap starts the successor itself whenever every gate below passes, whether the handoff is attended or unattended, and prints no launch command. Attendance changes how the successor behaves, never how it is started. The successor is always a visible interactive session, never a background one (`claude --bg`). A wrap the owner asked to run without chaining launches nothing.

Check the gates in order. The first one that fails ends the launch step: write the handoff as `launch: owner-started` with that `not_started_reason`, and print the launch command under the line `Not auto-started: <reason>`.

1. **Link budget.** `n+1` is no greater than `auto_through` (see Link budget). Reasons: `link budget`, `manual mode`.
2. **Quota.** Take a fresh reading for the pool the successor's model draws from, using whatever quota surface the host has (a quota command, the status line's rate-limit data, or a limit or extra-usage warning seen in this session). A reading from session start is stale. When the pool is exhausted or the account is spending extra usage, choose another model whose pool has headroom if one suits the work and record the change; otherwise do not launch. Reason: `quota` (add the reset time when known). When no reading is available, launch and say "quota unmeasured" in Phase 4.
3. **Launcher.** This session can open a new terminal window or a tmux session (see Launcher choice). Reason: `no launcher`.
4. **Confirmed start.** The launched successor is confirmed by its exact successor name, or by a session id this launch independently tied to it (see Confirmation and identity). Reasons: `launch failed`, or `launch denied` when a permission layer refused the launch command. Do not work around a denial.

### Launcher choice

Pick by what this session can open; the first match wins.

1. **New terminal window.** The session runs inside a graphical desktop where it can open another terminal window: on Windows, Windows Terminal (`wt.exe` on PATH) and no `SSH_CONNECTION`; elsewhere, a graphical session (`XDG_SESSION_TYPE` of `x11` or `wayland`) with a terminal emulator, no `SSH_CONNECTION` and no `TMUX`.
2. **tmux session.** No new-window metaphor and `tmux` is installed: an SSH session (`SSH_CONNECTION` set), a console TTY at the machine's head (`XDG_SESSION_TYPE=tty` or `TERM=linux`), or a session already inside tmux (`TMUX` set). A display alone does not qualify for a window: a console TTY has one and still uses tmux. Never take another TTY for the successor.
3. **Neither.** Print the command with reason `no launcher`.

When the signals are ambiguous, use tmux: a tmux session the owner has to attach to is harmless, and a window opened on a desktop nobody is sitting at is invisible.

Every automatic launch forwards the successor's chosen model and its permission mode (see Successor permission mode). Both forms read the prompt from the `.resume-prompt.txt` file described under Printed command, so write that file first.

### Successor permission mode

`<successor mode>` in the launch commands below is defined here once:

- **Unattended successor (`attendance: unattended` in the new handoff):** always `auto`, whatever mode this session runs in. In every launch form, including the printed command, the successor starts with `--permission-mode auto` (or the launcher's mode parameter set to `auto`).
- **Attended successor:** this session's actual mode, read from its transcript, never guessed. The newest `permission-mode` record in `<Claude config dir, default ~/.claude>/projects/*/<CLAUDE_CODE_SESSION_ID>.jsonl` is the mode, skipping `plan`: plan is transient and is never forwarded. Records look like `{"type":"permission-mode","permissionMode":"auto","sessionId":"..."}`. From the Bash tool:

  ```text
  jq -r 'select(.type=="permission-mode" and .permissionMode!="plan") | .permissionMode' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/projects/*/"$CLAUDE_CODE_SESSION_ID".jsonl | tail -n 1
  ```

  From the PowerShell tool:

  ```text
  Get-Content -LiteralPath (Get-ChildItem "$($env:CLAUDE_CONFIG_DIR ?? "$HOME/.claude")/projects/*/$env:CLAUDE_CODE_SESSION_ID.jsonl" | Select-Object -First 1).FullName | Where-Object { $_ -like '*"permission-mode"*' } | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.type -eq 'permission-mode' -and $_.permissionMode -ne 'plan' } | Select-Object -Last 1 -ExpandProperty permissionMode
  ```

  When neither prints a mode (no such record or no transcript), use `default` and say in Phase 4 that this session's mode was undetermined.

### Printed command

The printed command is what the owner pastes when a gate failed. Print one line, copy-pasteable, to run from this session's working directory:

```text
claude -n <chain>-<n+1> --model <model> <quoted resume prompt>
```

Fill `<model>` with the successor's chosen model alias or id (see Successor model). The printed command adds `--permission-mode <successor mode>` after `--model <model>` whenever the successor is unattended, so it does not start in `default` mode when the owner launches it on the way out. Fill `<resume prompt>` with the fixed template above, substituting `<chain>` (kebab-case `[a-z0-9-]+`), `<n+1>`, `<n+2>`, and the exact existing `<absolute handoff path>` without stripping or altering any characters from the path, then collapse it to a single line (line breaks become spaces). Quote `<resume prompt>` for the receiving shell the owner pastes into (not by the host OS) to form `<quoted resume prompt>`, so the prompt arrives as one literal argument without shell evaluation:

- **POSIX shells (`sh`, `bash`, `zsh`, Git Bash):** wrap `<resume prompt>` in single quotes (`'...'`) and escape each embedded single quote (`'`) as `'\''` (close single quote, escaped single quote, reopen single quote). Single quotes suppress all POSIX shell substitutions, so dollar signs (`$`), command substitutions (`$(...)`), backticks (``` `...` ```), backslashes (`\`), and double quotes (`"`) are preserved literally without expansion or execution, and `'\''` preserves apostrophes in existing paths such as `/home/O'Brien/.claude/handoffs/...`.
- **PowerShell (`pwsh`, `powershell`):** wrap `<resume prompt>` in single quotes (`'...'`) and escape every character that PowerShell treats as a single-quote delimiter - the ASCII apostrophe (`'`, U+0027) and the typographic single quotes U+2018 (left single quotation mark), U+2019 (right single quotation mark), U+201A (single low-9 quotation mark), and U+201B (single high-reversed-9 quotation mark) - by doubling that character with itself (for example `''` for `'`, and two consecutive U+2019 characters for U+2019). Never use PowerShell double quotes (`"..."`), which are expandable and evaluate `$` variables, `$(...)` subexpressions, and backtick (`` ` ``) escapes. PowerShell single-quoted strings are verbatim literals: `$`, `$HOME`, `$(...)`, backticks, backslashes (`\`), percent signs (`%`), exclamation marks (`!`), and double quotes (`"`) are preserved without evaluation, and doubling every PowerShell single-quote delimiter (`'` and U+2018/U+2019/U+201A/U+201B) preserves ASCII and typographic apostrophes in existing paths such as `C:\Users\O'Brien\.claude\handoffs\...`.
- **`cmd.exe` (Windows Command Prompt):** wrap `<resume prompt>` in double quotes (`"..."`). Because the fixed template contains no double quotes (`"`) and ends with a period (`.`), never a backslash (`\`), and `cmd.exe` treats single quotes (`'`), dollar signs (`$`), `$(...)`, and backticks (`` ` ``) as literal characters inside `"..."`, ordinary Windows paths - including paths with spaces, backslashes, `$`, `$(...)`, or apostrophes such as `C:\Users\O'Brien\.claude\handoffs\...` - round-trip unchanged with no escaping. Because `cmd.exe` expands `%VAR%` and (under delayed expansion) `!VAR!` inside `"..."` and has no safe interactive inline escape for `"`, `%`, or `!`, if the existing `<absolute handoff path>` contains `"`, `%`, or `!`, do not inline `<resume prompt>` into a `cmd.exe` double-quoted argument: instead use the `.resume-prompt.txt` fallback by printing `claude -n <chain>-<n+1> --model <model>` and instructing the owner to paste the prompt from `~/.claude/handoffs/<same slug>.resume-prompt.txt` (or run the PowerShell single-quoted command in PowerShell).

Unless the owner has said which shell they paste into, assume `cmd.exe` on a Windows host and a POSIX shell elsewhere. Print the command in a fenced block under a short lead-in naming the working directory and receiving shell to run it from. Also write the filled prompt to `~/.claude/handoffs/<same slug>.resume-prompt.txt`, beside the handoff, for the owner to paste from if the one-line form is awkward or when `cmd.exe` uses the prompt-file fallback. Record `launch: owner-started` with `session_id: null` and the `not_started_reason` in the handoff header.

### New terminal window

The prompt is read from the prompt file above, because Windows Terminal splits its command line at every semicolon and the prompt contains them. On Windows with Windows Terminal, from the PowerShell tool:

```text
wt.exe -w new -d "<this session's working directory>" pwsh -NoExit -File "<wrap skill directory>\scripts\launch-chain-successor.ps1" -Name "<chain>-<n+1>" -Model <successor model> -PermissionMode <successor mode> -PromptFile "<absolute prompt file path>"
```

`scripts/launch-chain-successor.ps1` removes the variables the window inherits from the tool call (`NO_COLOR`, `CLAUDECODE`, `CLAUDE_PID`, every `CLAUDE_CODE_*`) and then runs `claude -n <name> --model <model> --permission-mode <mode> <prompt>`. Never start `claude` in the new window without that scrub.

On another desktop, open the host's terminal emulator in this session's working directory running `bash "<wrap skill directory>/scripts/launch-chain-successor.sh" "<chain>-<n+1>" <successor model> <successor mode> "<absolute prompt file path>"`, which does the same scrub. Use a terminal command only when it is known to work on that host; otherwise use tmux.

### tmux session

From the Bash tool:

```text
tmux new-session -d -s "<chain>-<n+1>" -c "<this session's working directory>" bash "<wrap skill directory>/scripts/launch-chain-successor.sh" "<chain>-<n+1>" <successor model> <successor mode> "<absolute prompt file path>"
```

The session is detached, so the owner has to be told how to reach it. Print exactly one command in Phase 4, and no launch command:

- `tmux attach -t <chain>-<n+1>` when this session is not inside tmux.
- `tmux switch-client -t <chain>-<n+1>` when this session is inside tmux (`TMUX` set), because tmux refuses a nested attach.

### Confirmation and identity

List the running sessions with `claude agents --json` before the launch and again after it. The successor is the entry with kind `interactive` that was not there before and whose name is exactly `<chain>-<n+1>`: confirmation is by exact name. A new interactive session under a different name is not the successor, even when it is the only new entry: the owner may have opened an unrelated session at the same moment, and the intended launch may be stalled or absent. For tmux, `tmux has-session -t "<chain>-<n+1>"` proves only that the container exists, never which Claude session runs inside it. Record `session_id` from a differently named entry only when this launch independently tied that id to the successor (for example the launcher reported the id of the session it started); without that correlation, report an unconfirmed launch. Once confirmed, record `launch: window` or `launch: tmux` and the full session id in the handoff header. If the launcher fails to start, or no exactly named interactive session appears within 20 seconds (for example, the launcher script failed on a missing or empty prompt file), treat the launch as failed: do not record an unconfirmed successor, set `launch: owner-started` with `session_id: null` and reason `launch failed`, say so plainly, and print the copy-pasteable command as the fallback.

This session's own full id (for the handoff's `session_id` field) is in the `CLAUDE_CODE_SESSION_ID` environment variable of any Bash or PowerShell tool call.

Observed on Windows (host chonkers, 2026-10-06): a window opened with `wt.exe -w new ... pwsh -NoExit -Command "claude ..."` and no scrub rendered without colors, because `NO_COLOR=1` was inherited. The same window opened through `launch-chain-successor.ps1` rendered in color, and `claude agents --json` listed it within 20 seconds with kind `interactive`, its name and its own full session id.

**Other harnesses (codex, opencode).** Neither has a detached interactive launcher, so the successor is a headless re-invocation that receives the resume prompt. Print one line in the same shape as the Claude Code line, with `<quoted resume prompt>` built exactly as above and run from this session's working directory:

```text
codex exec <quoted resume prompt>
codex exec resume <session id> <quoted resume prompt>
opencode run <quoted resume prompt>
```

- `codex exec` starts a fresh successor session. `codex exec resume <session id>` sends the prompt into an existing session instead (`<session id>` is a UUID or thread name); use it only when continuing a specific recorded session rather than starting link n+1 fresh.
- `opencode run` takes the prompt as its message argument and starts a new session.
- When the quoted form is awkward, `codex exec -` reads the prompt from stdin from the `.resume-prompt.txt` written above, as `codex exec - < <quoted prompt file>`, with the file path quoted for the receiving shell by the rules above. That `<` redirection is for a POSIX shell or `cmd.exe` only: PowerShell reserves the `<` operator and rejects the line before codex starts, so in PowerShell use the quoted-argument form in the block above rather than stdin.
- These adapters do not forward a name, a model or a permission mode, and the run is non-interactive, so there is no owner to answer a prompt: record the handoff as `launch: owner-started` with `session_id: null`, and treat the successor as running without an owner at its first permission prompt (set `attendance: unattended` only on the grounds in Attendance).
- Verified against `codex exec --help`, `codex exec resume --help` and `opencode run --help` on host chonkers (2026-11-06). Other flags exist; this reference names only the forms above.

A printed command leaves nothing running, so Phase 2b has nothing to exclude. A confirmed window or tmux successor is the intended continuation: Phase 2b leaves it running.

## Final lines and failure behaviour

The last lines of Phase 4 say, without ambiguity, whether the successor is already running or the owner has to start it. Phase 4 carries exactly one of these, immediately before the sentinel, and never two:

- **Window launch:** the successor's name and "open in a new terminal window". No command of any kind.
- **tmux launch:** the successor's name and the one attach or switch command. No launch command.
- **Not started:** the line `Not auto-started: <reason>` and the launch command in a fenced block.

Then emit the matching chained sentinel verbatim as the last line, with `<n>` the current link number and `<chain>-<n+1>` the successor's session name (for example `settle-and-cure-6`). Both come from the handoff this link just wrote, so a link that re-scoped writes `Link 1` and `<new chain>-2`.

After a confirmed window launch:

> `That was a chained /wrap. Link <n> is closed; <chain>-<n+1> is already running in a new terminal window. Do not paste anything.`

After a confirmed tmux launch:

> `That was a chained /wrap. Link <n> is closed; <chain>-<n+1> is already running in tmux. Open it with the command above; do not start another.`

After a printed command, whatever the reason (link budget, manual mode, quota, no launcher, a failed or denied launch):

> `That was a chained /wrap. Link <n> is closed; <chain>-<n+1> has NOT been started. Paste the command above to continue.`

A chained sentinel is emitted only for a `continue` handoff. A wrap that stops (status `blocked` or `done`) has no successor and ends with the completed sentinel, preceded by one line that states the chain's condition: `Chain <chain> is complete at link <n>.` for `done`, or `Chain <chain> is waiting on the owner at link <n>; nothing is running.` for `blocked`.

> That's a /wrap. Go ahead and close the session.

If an automatic launch fails or startup cannot be confirmed, keep the handoff, say plainly that the launch failed or was unconfirmed, set `launch: owner-started` with `session_id: null`, and print the exact copy-pasteable fallback command as above. Do not invent successor ids. A launch problem does not undo the completed wrap; the printed fallback command ends with the not-started form of the chained sentinel. If the wrap itself was interrupted, use Phase 4's interrupted sentinel instead.
