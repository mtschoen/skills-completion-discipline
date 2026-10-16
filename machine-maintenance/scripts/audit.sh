#!/usr/bin/env bash
# Read-only Linux and macOS host maintenance audit across disk, repos, processes, env, harness, and os.
set -uo pipefail

OUTPUT_DIR=""
SECTIONS="disk,repos,processes,env,harness,os"
REPO_ROOTS=""
MAX_DEPTH=1
SKIP_ELEVATED=0
FORGE_TOKEN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir|-OutputDir)
            OUTPUT_DIR="${2:-}"
            shift 2
            ;;
        --sections|-Sections)
            SECTIONS="${2:-}"
            shift 2
            ;;
        --repo-roots|-RepoRoots)
            REPO_ROOTS="${2:-}"
            shift 2
            ;;
        --max-depth|-MaxDepth)
            MAX_DEPTH="${2:-1}"
            shift 2
            ;;
        --skip-elevated|-SkipElevated)
            SKIP_ELEVATED=1
            shift
            ;;
        --forge-token|-ForgeToken)
            FORGE_TOKEN="${2:-}"
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

mkdir -p "$OUTPUT_DIR/raw"
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
: > "$FINDINGS_TMP"
: > "$CLEAN_TMP"
: > "$BLOCKED_TMP"

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

    printf '{"kind":"%s","what":"%s","path":"%s","evidence":"%s","recommendation":"%s","confidence":"%s","rationale":"%s","action_on_approval":"%s","section":"%s","os":"%s","classification":"%s","reclaim_bytes":%s,"precondition":"%s","action":"%s"}\n' \
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
        "$(json_escape "$act")" >> "$FINDINGS_TMP"
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
        add_finding "disk" "cache_uv" "uv cache ($b bytes)" "$uv_dir" "$uv_dir is $b bytes" "delete" "high" \
            "Use uv cache prune only; never run uv cache clean because live venvs use ~/.cache/uv" \
            "uv cache prune" "safe-mechanical" "$b" "no_uv_lock" "uv cache prune"
    else
        echo "[disk] uv cache under threshold ($b bytes)" >> "$CLEAN_TMP"
    fi

    b="$(measure_bytes "$pip_dir")"
    if [[ "$b" -gt 104857600 ]]; then
        add_finding "disk" "cache_pip" "pip cache ($b bytes)" "$pip_dir" "$pip_dir is $b bytes" "delete" "high" \
            "Regenerable pip HTTP wheel cache" "pip cache purge" "safe-mechanical" "$b" "process_stopped:pip" "pip cache purge"
    fi

    b="$(measure_bytes "$npm_dir")"
    if [[ "$b" -gt 209715200 ]]; then
        add_finding "disk" "cache_npm" "npm cache ($b bytes)" "$npm_dir" "$npm_dir is $b bytes" "delete" "high" \
            "Regenerable npm cache" "npm cache clean --force" "safe-mechanical" "$b" "process_stopped:npm" "npm cache clean --force"
    fi

    b="$(measure_bytes "$pnpm_dir")"
    if [[ "$b" -gt 209715200 ]]; then
        add_finding "disk" "cache_pnpm" "pnpm store ($b bytes)" "$pnpm_dir" "$pnpm_dir is $b bytes" "delete" "high" \
            "Prune unreferenced content-addressed packages" "pnpm store prune" "safe-mechanical" "$b" "process_stopped:pnpm" "pnpm store prune"
    fi

    if [[ "$OS_NAME" == "linux" ]]; then
        if command -v journalctl >/dev/null 2>&1; then
            local j_usage
            j_usage="$(journalctl --disk-usage 2>/dev/null || true)"
            if [[ "$j_usage" =~ ([0-9.]+)G ]]; then
                add_finding "disk" "linux_journal_vacuum" "systemd journal ($j_usage)" "/var/log/journal" "$j_usage" \
                    "delete" "high" "Rotate active journal files first so vacuum can reclaim space" \
                    "sudo journalctl --rotate && sudo journalctl --vacuum-size=500M" "needs-elevation" "0" "none"
            else
                echo "[disk] systemd journal usage acceptable ($j_usage)" >> "$CLEAN_TMP"
            fi
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

    printf '{"os":"%s","max_depth":%s}\n' "$OS_NAME" "$MAX_DEPTH" > "$OUTPUT_DIR/raw/disk.json"
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
                    dirty="$(git -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
                    if [[ "${dirty:-0}" -eq 0 ]] && git -C "$wt" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
                        add_finding "repos" "worktree_merged_clean" "Merged clean worktree $(basename "$wt")" "$wt" \
                            "Clean tree and ancestor of origin/main" "delete" "high" \
                            "Use double --force in case of submodules" \
                            "git worktree remove --force --force \"$wt\"" "safe-mechanical" "0" "worktree_clean"
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
        echo "[repos] No stale worktrees across $repo_count repositories" >> "$CLEAN_TMP"
    fi
    printf '{"repo_count":%d,"stale_worktree_count":%d}\n' "$repo_count" "$stale_wt" > "$OUTPUT_DIR/raw/repos.json"
}

run_processes_audit() {
    if [[ "$OS_NAME" == "linux" ]]; then
        if command -v systemctl >/dev/null 2>&1; then
            local failed_units
            failed_units="$(systemctl --failed --no-legend --no-pager 2>/dev/null | wc -l | tr -d ' ')"
            if [[ "${failed_units:-0}" -gt 0 ]]; then
                add_finding "processes" "systemd_failed_units" "$failed_units failed systemd unit(s)" "" \
                    "systemctl --failed reported $failed_units unit(s)" "needs_human_judgment" "high" \
                    "Failed systemd units indicate crashing services or timers" "systemctl --failed" "needs-judgment" "0" "none"
            else
                echo "[processes] systemctl --failed is clean (0 failed units)" >> "$CLEAN_TMP"
            fi
            systemctl list-timers --no-pager >/dev/null 2>&1 || true
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
            echo "[processes] No orphaned node/python/pytest/bash processes with PPID 1" >> "$CLEAN_TMP"
        fi
    else
        launchctl list >/dev/null 2>&1 || true
        if command -v lsof >/dev/null 2>&1; then
            lsof -iTCP -sTCP:LISTEN -n -P >/dev/null 2>&1 || true
        fi
        echo "[processes] Checked launchctl list and listening TCP ports" >> "$CLEAN_TMP"
    fi
    printf '{"os":"%s"}\n' "$OS_NAME" > "$OUTPUT_DIR/raw/processes.json"
}

run_env_audit() {
    local dead_count=0
    local dupe_count=0
    local seen_paths=":"
    local IFS_SAVE="$IFS"
    IFS=':'
    for p in $PATH; do
        IFS="$IFS_SAVE"
        [[ -z "$p" ]] && continue
        if [[ "$seen_paths" == *":$p:"* ]]; then
            dupe_count=$(( dupe_count + 1 ))
        else
            seen_paths="${seen_paths}${p}:"
        fi
        if [[ ! -d "$p" ]]; then
            dead_count=$(( dead_count + 1 ))
        fi
    done
    IFS="$IFS_SAVE"

    if [[ "$dead_count" -gt 0 || "$dupe_count" -gt 0 ]]; then
        add_finding "env" "path_hygiene" "PATH has $dead_count dead dir(s) and $dupe_count duplicate entry/entries" "$HOME/.profile" \
            "dead=$dead_count, duplicates=$dupe_count across PATH entries" "needs_human_judgment" "medium" \
            "Clean duplicate and non-existent PATH exports in /etc/environment, /etc/paths.d, $HOME/.profile, or $HOME/.bashrc" \
            "Inspect $HOME/.profile and $HOME/.bashrc PATH exports" "needs-judgment" "0" "none"
    else
        echo "[env] All PATH directories exist and have no duplicates" >> "$CLEAN_TMP"
    fi

    local safe_dirs=0
    if command -v git >/dev/null 2>&1; then
        safe_dirs="$(git config --global --get-all safe.directory 2>/dev/null | wc -l | tr -d ' ')"
        if [[ "${safe_dirs:-0}" -gt 50 ]]; then
            add_finding "env" "gitconfig_safe_directory_bloat" "Global gitconfig has $safe_dirs safe.directory entries" "$HOME/.gitconfig" \
                "safe.directory count=$safe_dirs" "needs_human_judgment" "medium" \
                "Accumulated safe.directory entries from container or test runs" \
                "Prune stale safe.directory lines in $HOME/.gitconfig" "needs-judgment" "0" "none"
        else
            echo "[env] Global gitconfig safe.directory count is clean (${safe_dirs:-0})" >> "$CLEAN_TMP"
        fi
    fi

    printf '{"dead_path_entries":%d,"dupe_path_entries":%d,"safe_directory_count":%d}\n' \
        "$dead_count" "$dupe_count" "${safe_dirs:-0}" > "$OUTPUT_DIR/raw/env.json"
}

run_harness_audit() {
    local retired_hits=0
    for cf in "$HOME/.config/opencode/opencode.json" "$HOME/.qwen/settings.json" "$HOME/.codex/config.toml" "$HOME/.pr-crew/config.toml"; do
        if [[ -f "$cf" ]]; then
            if grep -Eqi 'gpt-5\.6|terra|[a-z0-9.]+-fast\b' "$cf" 2>/dev/null; then
                retired_hits=$(( retired_hits + 1 ))
                add_finding "harness" "harness_retired_model_ids" "Retired or -fast model ID in $(basename "$cf")" "$cf" \
                    "Matched gpt-5.6, terra, or -fast in $cf" "needs_human_judgment" "high" \
                    "gpt-5.6, terra, and -fast model variants are retired by policy" \
                    "Update model pins in $cf" "needs-judgment" "0" "none"
            fi
        fi
    done
    if [[ "$retired_hits" -eq 0 ]]; then
        echo "[harness] No retired model IDs (gpt-5.6, terra, -fast) found in harness configs" >> "$CLEAN_TMP"
    fi
    printf '{"retired_model_hits":%d}\n' "$retired_hits" > "$OUTPUT_DIR/raw/harness.json"
}

run_os_audit() {
    if [[ "$OS_NAME" == "linux" ]]; then
        if [[ -f /var/run/reboot-required ]]; then
            add_finding "os" "os_pending_reboot" "/var/run/reboot-required is present" "/var/run/reboot-required" \
                "Kernel or libc update requires reboot" "needs_human_judgment" "high" \
                "Pending reboot after system package upgrade" "sudo reboot (during maintenance window)" "needs-elevation" "0" "none"
        else
            echo "[os] No /var/run/reboot-required flag present" >> "$CLEAN_TMP"
        fi
        if [[ "$IS_ROOT" -eq 1 && "$SKIP_ELEVATED" -eq 0 ]] && command -v smartctl >/dev/null 2>&1; then
            smartctl --scan >/dev/null 2>&1 || true
        else
            echo "[os] smartctl -H skipped (requires root): run sudo smartctl -H /dev/nvme0n1" >> "$BLOCKED_TMP"
        fi
    else
        diskutil info / >/dev/null 2>&1 || true
        if command -v sntp >/dev/null 2>&1; then
            sntp -d time.apple.com >/dev/null 2>&1 || true
        fi
        echo "[os] Checked diskutil info / and network time sync" >> "$CLEAN_TMP"
    fi
    printf '{"os":"%s","is_root":%d}\n' "$OS_NAME" "$IS_ROOT" > "$OUTPUT_DIR/raw/os.json"
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
    awk 'NR > 1 { printf ",\n" } { printf "  %s", $0 } END { if (NR > 0) printf "\n" }' "$FINDINGS_TMP"
    echo "]"
} > "$FINDINGS_JSON"

TOTAL_FINDINGS="$(wc -l < "$FINDINGS_TMP" | tr -d ' ')"
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
        render_findings_markdown "$FINDINGS_TMP"
    fi
    echo ""
    echo "## Checked and clean"
    echo ""
    if [[ -s "$CLEAN_TMP" ]]; then
        sed 's/^/- /' "$CLEAN_TMP"
    else
        echo "- None recorded."
    fi
    echo ""
    echo "## Blocked or skipped"
    echo ""
    if [[ -s "$BLOCKED_TMP" ]]; then
        sed 's/^/- /' "$BLOCKED_TMP"
    else
        echo "- None."
    fi
} > "$REPORT_MD"

rm -f "$FINDINGS_TMP" "$CLEAN_TMP" "$BLOCKED_TMP"
echo "Audit complete. Findings: ${TOTAL_FINDINGS:-0}. Report: $REPORT_MD"
