#!/usr/bin/env bash
# Starts a wrap chain successor as an interactive Claude Code session.
#
# Runs inside the tmux session or terminal window that chain mode opens (see
# references/chain.md). It removes the variables inherited from the launching
# session's tool environment, then starts Claude Code with the resume prompt
# read from a file.
#
# The scrub is required. A tool call's environment carries NO_COLOR=1 (the
# successor would render without colors) and the launching session's
# CLAUDE_CODE_* identity (the successor would not get its own transcript).
#
# Usage: launch-chain-successor.sh <name> <model> <permission-mode> <prompt-file>
set -euo pipefail

if [ "$#" -ne 4 ]; then
	echo "usage: launch-chain-successor.sh <name> <model> <permission-mode> <prompt-file>" >&2
	exit 2
fi

successor_name="$1"
successor_model="$2"
permission_mode="$3"
prompt_file="$4"

for required_value in "$successor_name" "$successor_model" "$permission_mode" "$prompt_file"; do
	if [ -z "$required_value" ]; then
		echo "launch-chain-successor.sh: name, model, permission mode and prompt file must all be non-empty" >&2
		exit 2
	fi
done

if [ ! -f "$prompt_file" ]; then
	echo "Resume prompt file '$prompt_file' does not exist." >&2
	exit 1
fi

prompt="$(cat -- "$prompt_file")"
if [ -z "${prompt//[[:space:]]/}" ]; then
	echo "Resume prompt file '$prompt_file' is empty or contains only whitespace." >&2
	exit 1
fi

while IFS= read -r variable_name; do
	case "$variable_name" in
	CLAUDE_CODE_* | CLAUDECODE | CLAUDE_PID | NO_COLOR | FORCE_COLOR)
		unset "$variable_name"
		;;
	esac
done < <(compgen -e)

exec claude -n "$successor_name" --model "$successor_model" --permission-mode "$permission_mode" "$prompt"
