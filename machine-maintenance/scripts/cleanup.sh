#!/usr/bin/env bash
# Manifest-driven Linux and macOS cleanup runner. Executes only safe-mechanical items whose preconditions pass.
set -uo pipefail

MANIFEST=""
OUTPUT_DIR=""
EXECUTE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest|-Manifest)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: $1 requires a value." >&2
                exit 1
            fi
            MANIFEST="$2"
            shift 2
            ;;
        --output-dir|-OutputDir)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: $1 requires a value." >&2
                exit 1
            fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --dry-run|-DryRun)
            EXECUTE=0
            shift
            ;;
        --execute|-Execute)
            EXECUTE=1
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$MANIFEST" || ! -f "$MANIFEST" ]]; then
    echo "Error: valid --manifest / -Manifest file is required." >&2
    exit 1
fi

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$(dirname "$MANIFEST")"
fi
mkdir -p "$OUTPUT_DIR"
LOG_PATH="$OUTPUT_DIR/cleanup-log.jsonl"

PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Error: python3 or python is required to parse the JSON manifest." >&2
    exit 1
fi

 "$PYTHON_BIN" - "$MANIFEST" "$LOG_PATH" "$EXECUTE" <<'PYEOF'
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest_path = Path(sys.argv[1])
log_path = Path(sys.argv[2])
execute = sys.argv[3] == "1"

EXACT_DELETE_DIR_KINDS = {"cache_xcode_deriveddata"}

items = json.loads(manifest_path.read_text(encoding="utf-8"))
if isinstance(items, dict):
    items = [items]

def measure_path_bytes(p: str) -> int:
    if not p or not os.path.exists(p):
        return 0
    path_obj = Path(p)
    if path_obj.is_file():
        return path_obj.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path_obj, followlinks=False):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total

def worktree_locked(target_path: str) -> bool:
    res = subprocess.run(["git", "-C", target_path, "rev-parse", "--absolute-git-dir"], capture_output=True, text=True)
    if res.returncode != 0:
        return True
    return os.path.isfile(os.path.join(res.stdout.strip(), "locked"))

def check_precondition(pre: str, target_path: str) -> tuple[bool, str]:
    if not pre or pre == "none":
        return True, ""
    if pre.startswith("process_stopped:"):
        names = [n.strip() for n in pre.split(":", 1)[1].split(",") if n.strip()]
        for name in names:
            res = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True)
            if res.returncode == 0:
                return False, f"Process '{name}' is running"
            if res.returncode != 1:
                return False, f"pgrep -x {name} failed (exit {res.returncode}): {res.stderr.strip()}"
        return True, ""
    if pre == "no_uv_lock":
        res = subprocess.run(["pgrep", "-x", "uv"], capture_output=True, text=True)
        if res.returncode == 0:
            return False, "uv process is currently running"
        if res.returncode != 1:
            return False, f"pgrep -x uv failed (exit {res.returncode}): {res.stderr.strip()}"
        return True, ""
    if pre == "worktree_clean":
        if not target_path or not os.path.isdir(target_path):
            return False, f"Worktree path missing: {target_path}"
        res = subprocess.run(["git", "-C", target_path, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"], capture_output=True, text=True)
        if res.returncode != 0 or res.stdout.strip():
            return False, "Worktree is dirty or unreadable"
        return True, ""
    if pre == "dir_empty":
        if not target_path or not os.path.isdir(target_path):
            return False, f"Directory missing: {target_path}"
        if any(Path(target_path).iterdir()):
            return False, "Directory is not empty"
        return True, ""
    return False, f"Unknown precondition: {pre}"

def append_log(record: dict) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

free_before = shutil.disk_usage(str(output_dir := log_path.parent)).free
had_refusal = False

for item in items:
    kind = str(item.get("kind", "unknown"))
    what = str(item.get("what", kind))
    classification = str(item.get("classification", ""))
    target_path = str(item.get("path", ""))
    action = str(item.get("action") or item.get("action_on_approval") or target_path)
    precondition = str(item.get("precondition", "none"))
    now = datetime.now(timezone.utc).isoformat()

    if classification != "safe-mechanical":
        msg = f"REFUSED: '{what}' ({kind}) has classification '{classification}'; only 'safe-mechanical' is allowed. Suggested command to run manually if approved: {action}"
        sys.stderr.write(msg + "\n")
        append_log({
            "timestamp": now,
            "item": what,
            "kind": kind,
            "path": target_path,
            "action": action,
            "bytes_before": 0,
            "bytes_after": 0,
            "outcome": "refused",
            "stderr": msg,
        })
        had_refusal = True
        continue

    if "uv cache clean" in action:
        msg = f"REFUSED: '{what}' ({kind}) attempted 'uv cache clean'; only 'uv cache prune' is permitted."
        sys.stderr.write(msg + "\n")
        append_log({
            "timestamp": now,
            "item": what,
            "kind": kind,
            "path": target_path,
            "action": action,
            "bytes_before": 0,
            "bytes_after": 0,
            "outcome": "refused",
            "stderr": msg,
        })
        had_refusal = True
        continue

    ok, reason = check_precondition(precondition, target_path)
    if not ok:
        append_log({
            "timestamp": now,
            "item": what,
            "kind": kind,
            "path": target_path,
            "action": action,
            "bytes_before": 0,
            "bytes_after": 0,
            "outcome": "skipped_precondition",
            "stderr": reason,
        })
        continue

    bytes_before = measure_path_bytes(target_path)
    if not execute:
        append_log({
            "timestamp": now,
            "item": what,
            "kind": kind,
            "path": target_path,
            "action": action,
            "bytes_before": bytes_before,
            "bytes_after": bytes_before,
            "outcome": "dry_run",
            "stderr": "",
        })
        continue

    outcome = "executed"
    stderr_str = ""
    try:
        if kind == "macos_brew_cleanup":
            r = subprocess.run(["brew", "cleanup"], capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                outcome, stderr_str = "failed", r.stderr.strip()
        elif kind == "worktree_prunable":
            r = subprocess.run(["git", "-C", target_path, "worktree", "prune"], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                outcome, stderr_str = "failed", r.stderr.strip()
        elif kind == "worktree_merged_clean":
            audited_tip = str(item.get("tip_sha", "")).strip()
            tip_res = subprocess.run(["git", "-C", target_path, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
            current_tip = tip_res.stdout.strip() if tip_res.returncode == 0 else ""
            if not audited_tip or current_tip != audited_tip:
                outcome, stderr_str = "refused", "Worktree tip changed since audit; re-run the audit before removal"
                had_refusal = True
            elif worktree_locked(target_path):
                outcome, stderr_str = "refused", "Worktree is locked; refusing double-force removal"
                had_refusal = True
            else:
                r = subprocess.run(["git", "-C", target_path, "worktree", "remove", "--force", "--force", target_path], capture_output=True, text=True, timeout=30)
                if r.returncode != 0:
                    outcome, stderr_str = "failed", r.stderr.strip()
        elif kind == "temp_file":
            p = Path(target_path)
            if p.is_symlink() or p.is_file():
                p.unlink()
            elif not p.exists():
                outcome = "skipped_missing"
            else:
                outcome, stderr_str = "refused", "temp_file target is a directory; refusing recursive delete"
                had_refusal = True
        elif kind in EXACT_DELETE_DIR_KINDS:
            if target_path and os.path.exists(target_path):
                p = Path(target_path)
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink()
            else:
                outcome = "skipped_missing"
        else:
            outcome = "refused"
            stderr_str = f"No explicit cleanup handler for kind '{kind}'; not touching '{target_path}'"
            had_refusal = True
    except Exception as exc:
        outcome = "failed"
        stderr_str = str(exc)

    bytes_after = measure_path_bytes(target_path)
    append_log({
        "timestamp": now,
        "item": what,
        "kind": kind,
        "path": target_path,
        "action": action,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
        "outcome": outcome,
        "stderr": stderr_str,
    })

free_after = shutil.disk_usage(str(output_dir)).free
append_log({
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "kind": "volume_free_space",
    "dry_run": not execute,
    "free_before": free_before,
    "free_after": free_after,
})

sys.exit(2 if had_refusal else 0)
PYEOF
