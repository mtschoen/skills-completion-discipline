#!/usr/bin/env bash
# Read-only Linux and macOS host maintenance audit across disk, repos, processes, env, harness, and os.
set -uo pipefail

OUTPUT_DIR=""
SECTIONS="disk,repos,processes,env,harness,os"
REPO_ROOTS=""
MAX_DEPTH=1
SKIP_ELEVATED=0
FORGE_TOKEN=""

require_value() {
    if [[ $# -lt 2 || -z "$2" ]]; then
        echo "Error: $1 requires a value." >&2
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir|-OutputDir)
            require_value "$1" "${2:-}"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --sections|-Sections)
            require_value "$1" "${2:-}"
            SECTIONS="$2"
            shift 2
            ;;
        --repo-roots|-RepoRoots)
            require_value "$1" "${2:-}"
            REPO_ROOTS="$2"
            shift 2
            ;;
        --max-depth|-MaxDepth)
            require_value "$1" "${2:-}"
            MAX_DEPTH="$2"
            shift 2
            ;;
        --skip-elevated|-SkipElevated)
            SKIP_ELEVATED=1
            shift
            ;;
        --forge-token|-ForgeToken)
            require_value "$1" "${2:-}"
            FORGE_TOKEN="$2"
            shift 2
            ;;
        --json|-Json)
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$OUTPUT_DIR" ]]; then
    echo "Error: --output-dir / -OutputDir is required." >&2
    exit 1
fi

PUBLISH_FAILED=0
publish_error() {
    printf 'Error: %s\n' "$1" >&2
    PUBLISH_FAILED=1
}

if ! mkdir -p "$OUTPUT_DIR/raw"; then
    publish_error "Could not create audit output directory: $OUTPUT_DIR"
    exit 1
fi
UNAME_S="$(uname -s)"
if [[ "$UNAME_S" == "Darwin" ]]; then
    OS_NAME="macos"
else
    OS_NAME="linux"
fi

IS_ROOT=0
if [[ "$(id -u)" -eq 0 ]]; then
    IS_ROOT=1
fi

if [[ -z "$REPO_ROOTS" ]]; then
    REPO_ROOTS="$HOME"
fi

FINDINGS_TMP="$OUTPUT_DIR/.findings.jsonl"
CLEAN_TMP="$OUTPUT_DIR/.clean.txt"
BLOCKED_TMP="$OUTPUT_DIR/.blocked.txt"
if ! { : > "$FINDINGS_TMP" && : > "$CLEAN_TMP" && : > "$BLOCKED_TMP"; }; then
    publish_error "Could not initialize audit temporary files in $OUTPUT_DIR"
    exit 1
fi

json_escape() {
    local s="${1:-}"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/ }"
    s="${s//$'\r'/}"
    s="${s//$'\t'/ }"
    printf '%s' "$s"
}

add_finding() {
    local section="$1"
    local kind="$2"
    local what="$3"
    local path="$4"
    local evidence="$5"
    local rec="$6"
    local conf="$7"
    local rationale="$8"
    local action_app="$9"
    local class="${10}"
    local bytes="${11:-0}"
    local pre="${12:-none}"
    local act="${13:-$action_app}"
    local tip_sha="${14:-}"

    if command -v python3 >/dev/null 2>&1; then
        python3 -c '
import json
import sys

keys = ["kind", "what", "path", "evidence", "recommendation", "confidence", "rationale",
        "action_on_approval", "section", "os", "classification", "reclaim_bytes",
        "precondition", "action", "tip_sha"]
record = dict(zip(keys, sys.argv[1:16]))
record["reclaim_bytes"] = int(record["reclaim_bytes"] or 0)
print(json.dumps(record, ensure_ascii=False))
' "$kind" "$what" "$path" "$evidence" "$rec" "$conf" "$rationale" "$action_app" "$section" "$OS_NAME" "$class" "$bytes" "$pre" "$act" "$tip_sha" >> "$FINDINGS_TMP" || publish_error "Could not append to $FINDINGS_TMP"
        return
    fi

    if [[ "$path" == *$'\n'* || "$path" == *$'\r'* || "$path" == *$'\t'* ]]; then
        echo "[audit] Skipped finding '$kind': path contains control characters and python3 is unavailable for safe JSON encoding" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
        return
    fi

    printf '{"kind":"%s","what":"%s","path":"%s","evidence":"%s","recommendation":"%s","confidence":"%s","rationale":"%s","action_on_approval":"%s","section":"%s","os":"%s","classification":"%s","reclaim_bytes":%s,"precondition":"%s","action":"%s","tip_sha":"%s"}\n' \
        "$(json_escape "$kind")" \
        "$(json_escape "$what")" \
        "$(json_escape "$path")" \
        "$(json_escape "$evidence")" \
        "$(json_escape "$rec")" \
        "$(json_escape "$conf")" \
        "$(json_escape "$rationale")" \
        "$(json_escape "$action_app")" \
        "$(json_escape "$section")" \
        "$(json_escape "$OS_NAME")" \
        "$(json_escape "$class")" \
        "$bytes" \
        "$(json_escape "$pre")" \
        "$(json_escape "$act")" \
        "$(json_escape "$tip_sha")" >> "$FINDINGS_TMP" || publish_error "Could not append to $FINDINGS_TMP"
}

measure_bytes() {
    local target="$1"
    if [[ ! -e "$target" ]]; then
        echo 0
        return
    fi
    local kb
    kb="$(du -sk "$target" 2>/dev/null | awk '{print $1}' | head -n 1)"
    if [[ -z "$kb" ]]; then
        echo 0
    else
        echo $(( kb * 1024 ))
    fi
}

run_disk_audit() {
    local uv_dir="$HOME/.cache/uv"
    local pip_dir="$HOME/.cache/pip"
    local npm_dir="$HOME/.npm"
    local pnpm_dir="$HOME/.local/share/pnpm/store"
    if [[ "$OS_NAME" == "macos" ]]; then
        uv_dir="$HOME/Library/Caches/uv"
        pip_dir="$HOME/Library/Caches/pip"
        pnpm_dir="$HOME/Library/pnpm/store"
    fi

    local b
    b="$(measure_bytes "$uv_dir")"
    if [[ "$b" -gt 104857600 ]]; then
        add_finding "disk" "cache_uv" "uv cache ($b bytes)" "$uv_dir" "$uv_dir is $b bytes" "needs_human_judgment" "high" \
            "Use uv cache prune only; never run uv cache clean because live venvs use ~/.cache/uv" \
            "uv cache prune" "needs-judgment" "$b" "no_uv_lock" "uv cache prune"
    else
        echo "[disk] uv cache under threshold ($b bytes)" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
    fi

    b="$(measure_bytes "$pip_dir")"
    if [[ "$b" -gt 104857600 ]]; then
        add_finding "disk" "cache_pip" "pip cache ($b bytes)" "$pip_dir" "$pip_dir is $b bytes" "needs_human_judgment" "high" \
            "Regenerable pip HTTP wheel cache; purge targets the configured cache, which may differ from the measured path" "pip cache purge" "needs-judgment" "$b" "process_stopped:pip" "pip cache purge"
    fi

    b="$(measure_bytes "$npm_dir")"
    if [[ "$b" -gt 209715200 ]]; then
        add_finding "disk" "cache_npm" "npm cache ($b bytes)" "$npm_dir" "$npm_dir is $b bytes" "needs_human_judgment" "high" \
            "Regenerable npm cache; clean targets the configured cache, which may differ from the measured path" "npm cache clean --force" "needs-judgment" "$b" "process_stopped:npm" "npm cache clean --force"
    fi

    b="$(measure_bytes "$pnpm_dir")"
    if [[ "$b" -gt 209715200 ]]; then
        add_finding "disk" "cache_pnpm" "pnpm store ($b bytes)" "$pnpm_dir" "$pnpm_dir is $b bytes" "needs_human_judgment" "high" \
            "Prune unreferenced content-addressed packages; prune targets the configured store, which may differ from the measured path" "pnpm store prune" "needs-judgment" "$b" "process_stopped:pnpm" "pnpm store prune"
    fi

    if [[ "$OS_NAME" == "linux" ]]; then
        if command -v journalctl >/dev/null 2>&1; then
            local j_usage
            local j_status
            j_usage="$(journalctl --disk-usage 2>&1)"
            j_status=$?
            if [[ "$j_status" -ne 0 ]]; then
                j_usage="${j_usage//$'\n'/; }"
                printf '[disk] journalctl --disk-usage failed (exit %d): %s\n' "$j_status" "${j_usage:-no output}" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
            elif [[ "$j_usage" =~ ^Archived[[:space:]]and[[:space:]]active[[:space:]]journals[[:space:]]take[[:space:]]up[[:space:]]([0-9]+([.][0-9]+)?)([KMGTP]?)B?[[:space:]]in[[:space:]]the[[:space:]]file[[:space:]]system\.?$ ]]; then
                if [[ "${BASH_REMATCH[3]}" =~ ^[GTP]$ ]]; then
                    add_finding "disk" "linux_journal_vacuum" "systemd journal ($j_usage)" "/var/log/journal" "$j_usage" \
                        "delete" "high" "Rotate active journal files first so vacuum can reclaim space" \
                        "sudo journalctl --rotate && sudo journalctl --vacuum-size=500M" "needs-elevation" "0" "none"
                else
                    echo "[disk] systemd journal usage acceptable ($j_usage)" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
                fi
            else
                j_usage="${j_usage//$'\n'/; }"
                printf '[disk] journalctl --disk-usage returned unrecognized output: %s\n' "${j_usage:-empty output}" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
            fi
        else
            echo "[disk] journalctl --disk-usage unavailable; skipped systemd journal usage check" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
        fi
        for pkg_cache in /var/cache/apt/archives /var/cache/dnf /var/cache/pacman/pkg; do
            if [[ -d "$pkg_cache" ]]; then
                b="$(measure_bytes "$pkg_cache")"
                if [[ "$b" -gt 524288000 ]]; then
                    add_finding "disk" "linux_pkg_cache" "Package cache $pkg_cache ($b bytes)" "$pkg_cache" "$pkg_cache: $b bytes" \
                        "delete" "high" "OS package manager archive cache" "sudo paccache -rk1 || sudo apt-get autoclean" "needs-elevation" "$b" "none"
                fi
            fi
        done
    else
        # macOS specific disk checks
        if command -v brew >/dev/null 2>&1; then
            local brew_dry
            brew_dry="$(brew cleanup -n 2>/dev/null | tail -n 1 || true)"
            if [[ -n "$brew_dry" ]]; then
                add_finding "disk" "macos_brew_cleanup" "Homebrew cache cleanup available" "$HOME/Library/Caches/Homebrew" "$brew_dry" \
                    "delete" "high" "Stale Homebrew downloads and formula versions" "brew cleanup" "safe-mechanical" "0" "none" "brew cleanup"
            fi
        fi
        local xcode_dd="$HOME/Library/Developer/Xcode/DerivedData"
        if [[ -d "$xcode_dd" ]]; then
            b="$(measure_bytes "$xcode_dd")"
            if [[ "$b" -gt 524288000 ]]; then
                add_finding "disk" "cache_xcode_deriveddata" "Xcode DerivedData ($b bytes)" "$xcode_dd" "$xcode_dd is $b bytes" \
                    "delete" "high" "Regenerable Xcode build artifacts" "rm -rf \"$xcode_dd\"/*" "safe-mechanical" "$b" "process_stopped:Xcode"
            fi
        fi
        if command -v tmutil >/dev/null 2>&1; then
            local snaps
            snaps="$(tmutil listlocalsnapshots / 2>/dev/null | grep -c 'com.apple.TimeMachine' || true)"
            if [[ "${snaps:-0}" -gt 5 ]]; then
                add_finding "disk" "macos_tm_snapshots" "$snaps Time Machine local snapshots on /" "/" "tmutil listlocalsnapshots / returned $snaps snapshots" \
                    "needs_human_judgment" "medium" "Local snapshots can be thinned if free space is tight" \
                    "sudo tmutil thinlocalsnapshots / 10000000000 4" "needs-elevation" "0" "none"
            fi
        fi
    fi

    printf '{"os":"%s","max_depth":%s}\n' "$OS_NAME" "$MAX_DEPTH" > "$OUTPUT_DIR/raw/disk.json" || publish_error "Could not write $OUTPUT_DIR/raw/disk.json"
}

worktree_is_locked() {
    local git_dir
    git_dir="$(git -C "$1" rev-parse --absolute-git-dir 2>/dev/null)" || return 1
    [[ -f "$git_dir/locked" ]]
}

run_repos_audit() {
    local repo_count=0
    local stale_wt=0
    local IFS_SAVE="$IFS"
    IFS=','
    for root in $REPO_ROOTS; do
        IFS="$IFS_SAVE"
        [[ -d "$root" ]] || continue
        for d in "$root"/*; do
            [[ -d "$d" ]] || continue
            if [[ "$d" == *-worktrees ]]; then
                for wt in "$d"/*; do
                    [[ -d "$wt" ]] || continue
                    stale_wt=$(( stale_wt + 1 ))
                    local dirty
                    dirty="$(git -C "$wt" status --porcelain --untracked-files=all --ignore-submodules=none 2>/dev/null | wc -l | tr -d ' ')"
                    local wt_tip
                    wt_tip="$(git -C "$wt" rev-parse HEAD 2>/dev/null)"
                    if worktree_is_locked "$wt"; then
                        add_finding "repos" "worktree_needs_review" "Locked worktree $(basename "$wt")" "$wt" \
                            "git worktree lock is set on $wt" "needs_human_judgment" "medium" \
                            "Locked worktrees are reserved by an operator; double --force removal would override the lock" \
                            "Inspect the lock reason with git -C \"$wt\" worktree list --porcelain" "needs-judgment" "0" "none"
                    elif [[ "${dirty:-0}" -eq 0 ]] && git -C "$wt" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
                        add_finding "repos" "worktree_merged_clean" "Merged clean worktree $(basename "$wt")" "$wt" \
                            "Clean tree and ancestor of origin/main at tip $wt_tip" "delete" "high" \
                            "Use double --force in case of submodules" \
                            "git worktree remove --force --force \"$wt\"" "safe-mechanical" "0" "worktree_clean" \
                            "git worktree remove --force --force \"$wt\"" "$wt_tip"
                    else
                        add_finding "repos" "worktree_needs_review" "Worktree $(basename "$wt") (dirty=$dirty)" "$wt" \
                            "dirty=$dirty, forge_token_set=$([[ -n "$FORGE_TOKEN" ]] && echo yes || echo no)" "needs_human_judgment" "medium" \
                            "Check squash-merge state or diff against origin/main before removing" \
                            "git -C \"$wt\" status -sb && git -C \"$wt\" diff origin/main..HEAD --stat" "needs-judgment" "0" "none"
                    fi
                done
                continue
            fi
            if [[ -e "$d/.git" ]]; then
                repo_count=$(( repo_count + 1 ))
                local prunable
                prunable="$(git -C "$d" worktree list --porcelain 2>/dev/null | grep -c '^prunable ' || true)"
                if [[ "${prunable:-0}" -gt 0 ]]; then
                    stale_wt=$(( stale_wt + prunable ))
                    add_finding "repos" "worktree_prunable" "$prunable prunable worktree(s) in $(basename "$d")" "$d" \
                        "git worktree list --porcelain reported $prunable prunable entries" "delete" "high" \
                        "Worktree directory already absent on disk" "git -C \"$d\" worktree prune" "safe-mechanical" "0" "none"
                fi
            fi
        done
    done
    IFS="$IFS_SAVE"
    if [[ "$stale_wt" -eq 0 ]]; then
        echo "[repos] No stale worktrees across $repo_count repositories" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
    fi
    printf '{"repo_count":%d,"stale_worktree_count":%d}\n' "$repo_count" "$stale_wt" > "$OUTPUT_DIR/raw/repos.json" || publish_error "Could not write $OUTPUT_DIR/raw/repos.json"
}

run_processes_audit() {
    if [[ "$OS_NAME" == "linux" ]]; then
        if command -v systemctl >/dev/null 2>&1; then
            local failed_units_output
            local failed_units_status
            failed_units_output="$(systemctl --failed --no-legend --no-pager 2>&1)"
            failed_units_status=$?
            if [[ "$failed_units_status" -ne 0 ]]; then
                failed_units_output="${failed_units_output//$'\n'/; }"
                printf '[processes] systemctl --failed failed (exit %d): %s\n' "$failed_units_status" "${failed_units_output:-no output}" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
            elif [[ -z "${failed_units_output//[[:space:]]/}" ]]; then
                echo "[processes] systemctl --failed is clean (0 failed units)" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
            else
                local failed_units
                failed_units="$(printf '%s\n' "$failed_units_output" | wc -l | tr -d ' ')"
                add_finding "processes" "systemd_failed_units" "$failed_units failed systemd unit(s)" "" \
                    "systemctl --failed reported $failed_units unit(s)" "needs_human_judgment" "high" \
                    "Failed systemd units indicate crashing services or timers" "systemctl --failed" "needs-judgment" "0" "none"
            fi
            systemctl list-timers --no-pager >/dev/null 2>&1 || true
        else
            echo "[processes] systemctl --failed unavailable; skipped failed-unit check" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
        fi
        if command -v ss >/dev/null 2>&1; then
            ss -tlnp >/dev/null 2>&1 || true
        fi
        # Orphan processes with PPID 1 and no controlling TTY
        local orphans
        orphans="$(ps -eo pid=,ppid=,tty=,comm= 2>/dev/null | awk '$2 == 1 && $3 == "?" && ($4 ~ /^(node|python|pytest|pwsh|bash)$/) {print $1}' | tr '\n' ' ')"
        if [[ -n "${orphans// /}" ]]; then
            add_finding "processes" "orphan_processes" "Orphaned background process(es) with PPID 1" "" \
                "Orphan PIDs: $orphans" "needs_human_judgment" "medium" \
                "Processes reparented to PID 1 without a TTY may be leaked test or agent subprocesses" \
                "ps -fp $orphans" "needs-judgment" "0" "none"
        else
            echo "[processes] No orphaned node/python/pytest/bash processes with PPID 1" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
        fi
    else
        echo "[processes] macOS launch-agent health is not evaluated; launchctl inspection is unimplemented" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
        echo "[processes] macOS listener health is not evaluated; listening-port inspection is unimplemented" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
    fi
    printf '{"os":"%s"}\n' "$OS_NAME" > "$OUTPUT_DIR/raw/processes.json" || publish_error "Could not write $OUTPUT_DIR/raw/processes.json"
}

run_env_audit() {
    local dead_count=0
    local dupe_count=0
    local empty_count=0
    local relative_count=0
    local seen_paths=":"
    local remaining_path="$PATH"
    local path_entries=()
    while [[ "$remaining_path" == *:* ]]; do
        path_entries+=("${remaining_path%%:*}")
        remaining_path="${remaining_path#*:}"
    done
    path_entries+=("$remaining_path")
    for p in "${path_entries[@]}"; do
        if [[ -z "$p" ]]; then
            empty_count=$(( empty_count + 1 ))
            continue
        fi
        if [[ "$p" != /* ]]; then
            relative_count=$(( relative_count + 1 ))
        fi
        if [[ "$seen_paths" == *":$p:"* ]]; then
            dupe_count=$(( dupe_count + 1 ))
        else
            seen_paths="${seen_paths}${p}:"
        fi
        if [[ ! -d "$p" ]]; then
            dead_count=$(( dead_count + 1 ))
        fi
    done

    if [[ "$dead_count" -gt 0 || "$dupe_count" -gt 0 || "$empty_count" -gt 0 || "$relative_count" -gt 0 ]]; then
        add_finding "env" "path_hygiene" "PATH has $empty_count empty, $relative_count relative, $dead_count dead, and $dupe_count duplicate entry/entries" "$HOME/.profile" \
            "empty=$empty_count, relative=$relative_count, dead=$dead_count, duplicates=$dupe_count across PATH entries" "needs_human_judgment" "medium" \
            "Clean empty, relative, duplicate, and non-existent PATH exports in /etc/environment, /etc/paths.d, $HOME/.profile, or $HOME/.bashrc" \
            "Inspect $HOME/.profile and $HOME/.bashrc PATH exports" "needs-judgment" "0" "none"
    else
        echo "[env] All PATH directories exist, are absolute and non-empty, and have no duplicates" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
    fi

    local safe_dirs=0
    local safe_dirs_json="null"
    if command -v git >/dev/null 2>&1; then
        local safe_output
        local safe_status
        safe_output="$(git config --global --get-all safe.directory 2>&1)"
        safe_status=$?
        if [[ "$safe_status" -eq 0 || "$safe_status" -eq 1 ]]; then
            if [[ "$safe_status" -eq 0 && -n "$safe_output" ]]; then
                safe_dirs="$(printf '%s\n' "$safe_output" | wc -l | tr -d ' ')"
            fi
            safe_dirs_json="$safe_dirs"
            if [[ "$safe_dirs" -gt 50 ]]; then
                add_finding "env" "gitconfig_safe_directory_bloat" "Global gitconfig has $safe_dirs safe.directory entries" "$HOME/.gitconfig" \
                    "safe.directory count=$safe_dirs" "needs_human_judgment" "medium" \
                    "Accumulated safe.directory entries from container or test runs" \
                    "Prune stale safe.directory lines in $HOME/.gitconfig" "needs-judgment" "0" "none"
            else
                echo "[env] Global gitconfig safe.directory count is clean ($safe_dirs)" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
            fi
        else
            safe_output="${safe_output//$'\n'/; }"
            printf '[env] git config --global --get-all safe.directory failed (exit %d): %s\n' "$safe_status" "${safe_output:-no output}" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
        fi
    else
        echo "[env] git config --global --get-all safe.directory unavailable; skipped safe.directory count" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
    fi

    printf '{"dead_path_entries":%d,"dupe_path_entries":%d,"empty_path_entries":%d,"relative_path_entries":%d,"safe_directory_count":%s}\n' \
        "$dead_count" "$dupe_count" "$empty_count" "$relative_count" "$safe_dirs_json" > "$OUTPUT_DIR/raw/env.json" || publish_error "Could not write $OUTPUT_DIR/raw/env.json"
}

run_harness_audit() {
    local retired_hits=0
    local config_files=0
    local inspected_count=0
    local inspected_configs=""
    for cf in "$HOME/.config/opencode/opencode.json" "$HOME/.qwen/settings.json" "$HOME/.codex/config.toml" "$HOME/.pr-crew/config.toml"; do
        if [[ -f "$cf" ]]; then
            config_files=$(( config_files + 1 ))
            local model_status
            grep -Eqi 'gpt-5\.6|terra|[a-z0-9.]+-fast\b' "$cf" 2>/dev/null
            model_status=$?
            case "$model_status" in
                0)
                    retired_hits=$(( retired_hits + 1 ))
                    inspected_count=$(( inspected_count + 1 ))
                    add_finding "harness" "harness_retired_model_ids" "Retired or -fast model ID in ${cf##*/}" "$cf" \
                        "Matched gpt-5.6, terra, or -fast in $cf" "needs_human_judgment" "high" \
                        "gpt-5.6, terra, and -fast model variants are retired by policy" \
                        "Update model pins in $cf" "needs-judgment" "0" "none"
                    ;;
                1)
                    inspected_count=$(( inspected_count + 1 ))
                    inspected_configs="${inspected_configs}${inspected_configs:+, }$cf"
                    ;;
                *)
                    printf '[harness] Failed to inspect model IDs in %s (grep exit %d)\n' "$cf" "$model_status" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
                    ;;
            esac
        fi
    done
    if [[ "$retired_hits" -eq 0 && "$inspected_count" -gt 0 ]]; then
        printf '[harness] No retired model IDs (gpt-5.6, terra, -fast) found in inspected harness configs: %s\n' "$inspected_configs" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
    elif [[ "$config_files" -eq 0 ]]; then
        echo "[harness] No supported harness model config files were found; model-ID check not evaluated" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
    fi
    {
        echo "[harness] Unix hook validation is not implemented; skipped hook health check"
        echo "[harness] Unix MCP command resolution is not implemented; skipped MCP health check"
        echo "[harness] Unix stale-project evaluation is not implemented; skipped project health check"
    } >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
    printf '{"retired_model_hits":%d,"inspected_config_count":%d}\n' "$retired_hits" "$inspected_count" > "$OUTPUT_DIR/raw/harness.json" || publish_error "Could not write $OUTPUT_DIR/raw/harness.json"
}

run_os_audit() {
    if [[ "$OS_NAME" == "linux" ]]; then
        if [[ -f /var/run/reboot-required ]]; then
            add_finding "os" "os_pending_reboot" "/var/run/reboot-required is present" "/var/run/reboot-required" \
                "Kernel or libc update requires reboot" "needs_human_judgment" "high" \
                "Pending reboot after system package upgrade" "sudo reboot (during maintenance window)" "needs-elevation" "0" "none"
        else
            echo "[os] No /var/run/reboot-required flag present" >> "$CLEAN_TMP" || publish_error "Could not append to $CLEAN_TMP"
        fi
    fi
    printf '[os] SMART health evaluation is not implemented on %s; run the platform SMART health check manually\n' "$OS_NAME" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
    printf '[os] Clock health evaluation is not implemented on %s; inspect clock synchronization manually\n' "$OS_NAME" >> "$BLOCKED_TMP" || publish_error "Could not append to $BLOCKED_TMP"
    printf '{"os":"%s","is_root":%d,"skip_elevated":%d}\n' "$OS_NAME" "$IS_ROOT" "$SKIP_ELEVATED" > "$OUTPUT_DIR/raw/os.json" || publish_error "Could not write $OUTPUT_DIR/raw/os.json"
}

IFS_SAVE="$IFS"
IFS=','
for sec in $SECTIONS; do
    IFS="$IFS_SAVE"
    sec="$(echo "$sec" | tr '[:upper:]' '[:lower:]' | tr -d ' ')"
    case "$sec" in
        all)
            run_disk_audit
            run_repos_audit
            run_processes_audit
            run_env_audit
            run_harness_audit
            run_os_audit
            ;;
        disk) run_disk_audit ;;
        repos) run_repos_audit ;;
        processes) run_processes_audit ;;
        env) run_env_audit ;;
        harness) run_harness_audit ;;
        os) run_os_audit ;;
        *)
            echo "Unknown section: $sec" >&2
            exit 1
            ;;
    esac
done
IFS="$IFS_SAVE"

# Assemble findings.json array
FINDINGS_JSON="$OUTPUT_DIR/findings.json"
{
    echo "["
    if ! awk 'NR > 1 { printf ",\n" } { printf "  %s", $0 } END { if (NR > 0) printf "\n" }' "$FINDINGS_TMP"; then
        publish_error "Could not assemble findings from $FINDINGS_TMP"
    fi
    echo "]"
} > "$FINDINGS_JSON" || publish_error "Could not write $FINDINGS_JSON"

if ! TOTAL_FINDINGS="$(wc -l < "$FINDINGS_TMP" | tr -d ' ')"; then
    publish_error "Could not read $FINDINGS_TMP"
    TOTAL_FINDINGS=0
fi
REPORT_MD="$OUTPUT_DIR/report.md"

# Render one "#### F<n>: <what>" block per finding, grouped by section, in the
# same shape audit.ps1 writes. python3 is present on every Linux and macOS
# host this skill targets; the raw JSON lines are the fallback when it is not.
render_findings_markdown() {
    local findings_file="$1"
    if ! command -v python3 >/dev/null 2>&1; then
        cat "$findings_file"
        return
    fi
    python3 - "$findings_file" <<'PY'
import json
import sys

findings = []
with open(sys.argv[1], encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if line:
            findings.append(json.loads(line))

def human_bytes(value):
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024

index = 1
for section in ("disk", "repos", "processes", "env", "harness", "os"):
    group = [f for f in findings if f.get("section") == section]
    if not group:
        continue
    print(f"### Section: {section}")
    print()
    for finding in group:
        reclaim = finding.get("reclaim_bytes") or 0
        impact = f"{human_bytes(reclaim)} reclaimable" if reclaim else finding.get("classification", "")
        print(f"#### F{index}: {finding.get('what', '')}")
        print()
        print(f"- **What:** {finding.get('what', '')}")
        print(f"- **Classification:** {finding.get('classification', '')}")
        if finding.get("path"):
            print(f"- **Path:** {finding['path']}")
        print(f"- **Evidence:** {finding.get('evidence', '')}")
        print(f"- **Impact:** {impact}")
        print(f"- **Recommendation:** {finding.get('recommendation', '')}")
        print(f"- **Confidence:** {finding.get('confidence', '')}")
        print(f"- **Precondition:** {finding.get('precondition', 'none')}")
        print(f"- **Action on approval:** `{finding.get('action', '')}`")
        print()
        index += 1
PY
}
{
    echo "# Machine Maintenance Audit Report"
    echo ""
    echo "## Summary"
    echo ""
    echo "- **OS:** $OS_NAME"
    echo "- **Total findings:** ${TOTAL_FINDINGS:-0}"
    echo ""
    echo "## Findings"
    echo ""
    if [[ "${TOTAL_FINDINGS:-0}" -eq 0 ]]; then
        echo "No findings surfaced across the selected sections."
    else
        if ! render_findings_markdown "$FINDINGS_TMP"; then
            publish_error "Could not render findings Markdown from $FINDINGS_TMP"
        fi
    fi
    echo ""
    echo "## Checked and clean"
    echo ""
    if [[ -s "$CLEAN_TMP" ]]; then
        if ! sed 's/^/- /' "$CLEAN_TMP"; then
            publish_error "Could not read $CLEAN_TMP"
        fi
    else
        echo "- None recorded."
    fi
    echo ""
    echo "## Blocked or skipped"
    echo ""
    if [[ -s "$BLOCKED_TMP" ]]; then
        if ! sed 's/^/- /' "$BLOCKED_TMP"; then
            publish_error "Could not read $BLOCKED_TMP"
        fi
    else
        echo "- None."
    fi
} > "$REPORT_MD" || publish_error "Could not write $REPORT_MD"

if [[ "$PUBLISH_FAILED" -ne 0 ]]; then
    echo "Audit failed due to output publication errors." >&2
    exit 1
fi
rm -f "$FINDINGS_TMP" "$CLEAN_TMP" "$BLOCKED_TMP"
echo "Audit complete. Findings: ${TOTAL_FINDINGS:-0}. Report: $REPORT_MD"
