import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
AUDIT_PS1 = SCRIPTS_DIR / "audit.ps1"
CLEANUP_PS1 = SCRIPTS_DIR / "cleanup.ps1"
AUDIT_SH = SCRIPTS_DIR / "audit.sh"
CLEANUP_SH = SCRIPTS_DIR / "cleanup.sh"

REQUIRED_FINDING_KEYS = {
    "kind",
    "what",
    "path",
    "evidence",
    "recommendation",
    "confidence",
    "rationale",
    "action_on_approval",
    "section",
    "os",
    "classification",
    "reclaim_bytes",
    "precondition",
    "action",
}

REQUIRED_REPORT_HEADINGS = (
    "## Summary",
    "## Findings",
    "## Checked and clean",
    "## Blocked or skipped",
)


def _find_pwsh() -> str:
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    pytest.skip("Neither pwsh nor powershell found on PATH")


def _find_bash() -> str:
    if sys.platform == "win32":
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        if git_bash.is_file():
            return str(git_bash)
    resolved = shutil.which("bash")
    if resolved:
        return resolved
    pytest.skip("bash not found on PATH")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell audit test")
def test_windows_audit_env_and_harness(tmp_path: Path) -> None:
    pwsh = _find_pwsh()
    out_dir = tmp_path / "audit-out"
    cmd = [
        pwsh,
        "-NoProfile",
        "-File",
        str(AUDIT_PS1),
        "-Sections",
        "env,harness",
        "-OutputDir",
        str(out_dir),
        "-SkipElevated",
    ]
    completed = subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=180
    )
    assert completed.returncode == 0, (
        f"audit.ps1 failed: {completed.stderr}\n{completed.stdout}"
    )

    findings_path = out_dir / "findings.json"
    report_path = out_dir / "report.md"
    assert findings_path.is_file(), "findings.json was not created"
    assert report_path.is_file(), "report.md was not created"
    assert (out_dir / "raw" / "env.json").is_file(), "raw/env.json was not created"
    assert (out_dir / "raw" / "harness.json").is_file(), (
        "raw/harness.json was not created"
    )

    findings = json.loads(findings_path.read_text(encoding="utf-8-sig"))
    assert isinstance(findings, list)
    for finding in findings:
        missing = REQUIRED_FINDING_KEYS - set(finding.keys())
        assert not missing, f"Finding missing required keys {missing}: {finding}"
        assert finding["section"] in {"env", "harness"}
        assert finding["os"] == "windows"
        assert finding["classification"] in {
            "safe-mechanical",
            "needs-judgment",
            "needs-elevation",
        }

    report_text = report_path.read_text(encoding="utf-8-sig")
    for heading in REQUIRED_REPORT_HEADINGS:
        assert heading in report_text, f"Missing heading '{heading}' in report.md"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell cleanup test")
def test_windows_cleanup_dry_run_execute_and_refusal(tmp_path: Path) -> None:
    pwsh = _find_pwsh()
    target_file = tmp_path / "reclaim-me.tmp"
    target_file.write_text("scratch data", encoding="utf-8")

    safe_manifest = tmp_path / "safe-manifest.json"
    safe_item = [
        {
            "kind": "temp_file",
            "what": "Temporary test file",
            "path": str(target_file),
            "evidence": "test file",
            "recommendation": "delete",
            "confidence": "high",
            "rationale": "unit test",
            "action_on_approval": f"Remove-Item -LiteralPath '{target_file}' -Force",
            "section": "disk",
            "os": "windows",
            "classification": "safe-mechanical",
            "reclaim_bytes": 12,
            "precondition": "none",
            "action": str(target_file),
        }
    ]
    safe_manifest.write_text(json.dumps(safe_item), encoding="utf-8")

    # 1. Dry-run must leave the file intact
    dry = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(CLEANUP_PS1),
            "-Manifest",
            str(safe_manifest),
            "-DryRun",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert dry.returncode == 0, f"cleanup.ps1 -DryRun failed: {dry.stderr}"
    assert target_file.exists(), "Dry-run must not delete the target file"

    # 2. Execute must remove the file and log the execution line
    exe = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(CLEANUP_PS1),
            "-Manifest",
            str(safe_manifest),
            "-Execute",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert exe.returncode == 0, f"cleanup.ps1 -Execute failed: {exe.stderr}"
    assert not target_file.exists(), "Execute should have deleted the target file"

    log_path = tmp_path / "cleanup-log.jsonl"
    assert log_path.is_file(), "cleanup-log.jsonl was not written"
    log_records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    assert any(
        r.get("kind") == "temp_file" and r.get("outcome") == "executed"
        for r in log_records
    )

    # 3. needs-judgment item must be refused and not deleted
    protected_file = tmp_path / "keep-me.tmp"
    protected_file.write_text("important WIP", encoding="utf-8")
    judgment_manifest = tmp_path / "judgment-manifest.json"
    judgment_item = [
        {
            **safe_item[0],
            "kind": "unmerged_wip",
            "what": "Protected item needing judgment",
            "path": str(protected_file),
            "classification": "needs-judgment",
            "action": str(protected_file),
        }
    ]
    judgment_manifest.write_text(json.dumps(judgment_item), encoding="utf-8")

    refused = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(CLEANUP_PS1),
            "-Manifest",
            str(judgment_manifest),
            "-Execute",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert refused.returncode != 0, (
        "cleanup.ps1 should return non-zero when refusing needs-judgment"
    )
    assert protected_file.exists(), "needs-judgment item must never be deleted"
    updated_records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    assert any(
        r.get("kind") == "unmerged_wip" and r.get("outcome") == "refused"
        for r in updated_records
    )

    # 4. A stale manifest naming a browser User Data root must be refused (F5)
    user_data = tmp_path / "User Data"
    profile = user_data / "Default"
    cache_dir = profile / "Cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "data.bin").write_text("cached", encoding="utf-8")
    cookies = profile / "Cookies"
    cookies.write_text("credentials", encoding="utf-8")

    root_manifest = tmp_path / "browser-root-manifest.json"
    root_item = [
        {
            **safe_item[0],
            "kind": "cache_browser_chrome",
            "what": "Stale finding naming the browser User Data root",
            "path": str(user_data),
            "action": str(user_data),
        }
    ]
    root_manifest.write_text(json.dumps(root_item), encoding="utf-8")
    refused_root = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(CLEANUP_PS1),
            "-Manifest",
            str(root_manifest),
            "-Execute",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert refused_root.returncode != 0, (
        "cleanup.ps1 should refuse a kind with no explicit handler"
    )
    assert cookies.exists(), "Browser profile data must survive a refused item"

    # 5. browser_cache_subdir deletes only recognized cache leaves
    bad_leaf_manifest = tmp_path / "browser-bad-leaf-manifest.json"
    bad_leaf_item = [
        {
            **safe_item[0],
            "kind": "browser_cache_subdir",
            "what": "Profile directory masquerading as a cache leaf",
            "path": str(profile),
            "action": str(profile),
        }
    ]
    bad_leaf_manifest.write_text(json.dumps(bad_leaf_item), encoding="utf-8")
    refused_leaf = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(CLEANUP_PS1),
            "-Manifest",
            str(bad_leaf_manifest),
            "-Execute",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert refused_leaf.returncode != 0
    assert profile.exists(), "Non-cache leaf must not be deleted"

    leaf_manifest = tmp_path / "browser-leaf-manifest.json"
    leaf_item = [
        {
            **safe_item[0],
            "kind": "browser_cache_subdir",
            "what": "Browser Cache subdirectory",
            "path": str(cache_dir),
            "action": str(cache_dir),
        }
    ]
    leaf_manifest.write_text(json.dumps(leaf_item), encoding="utf-8")
    cleared = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(CLEANUP_PS1),
            "-Manifest",
            str(leaf_manifest),
            "-Execute",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert cleared.returncode == 0, f"cache leaf cleanup failed: {cleared.stderr}"
    assert not cache_dir.exists(), "Recognized Cache leaf should be deleted"
    assert cookies.exists(), "Profile data outside the cache leaf must survive"


def test_shell_scripts_syntax_and_shellcheck() -> None:
    bash = _find_bash()
    for script in (AUDIT_SH, CLEANUP_SH):
        # Ensure LF line endings so bash -n and shellcheck succeed across platforms
        raw = script.read_bytes()
        assert b"\r\n" not in raw, f"{script.name} contains CRLF line endings"
        res = subprocess.run(
            [bash, "-n", script.name],
            cwd=str(SCRIPTS_DIR),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert res.returncode == 0, f"bash -n {script.name} failed: {res.stderr}"

    shellcheck = shutil.which("shellcheck")
    if shellcheck:
        sc = subprocess.run(
            [shellcheck, str(AUDIT_SH), str(CLEANUP_SH)],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert sc.returncode == 0, f"shellcheck failed:\n{sc.stdout}\n{sc.stderr}"


@pytest.mark.skipif(
    sys.platform == "win32", reason="Unix audit/cleanup execution runs on Linux/macOS"
)
def test_unix_audit_and_cleanup(tmp_path: Path) -> None:
    bash = _find_bash()
    out_dir = tmp_path / "unix-audit"
    res = subprocess.run(
        [
            bash,
            str(AUDIT_SH),
            "--sections",
            "env,harness",
            "--output-dir",
            str(out_dir),
            "--skip-elevated",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert res.returncode == 0, f"audit.sh failed: {res.stderr}"
    findings = json.loads((out_dir / "findings.json").read_text(encoding="utf-8"))
    assert isinstance(findings, list)
    for finding in findings:
        assert not (REQUIRED_FINDING_KEYS - set(finding.keys()))

    report_text = (out_dir / "report.md").read_text(encoding="utf-8")
    for heading in REQUIRED_REPORT_HEADINGS:
        assert heading in report_text

    target_file = tmp_path / "unix-reclaim.tmp"
    target_file.write_text("scratch", encoding="utf-8")
    manifest = tmp_path / "unix-manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "kind": "temp_file",
                    "what": "Unix scratch file",
                    "path": str(target_file),
                    "evidence": "test",
                    "recommendation": "delete",
                    "confidence": "high",
                    "rationale": "test",
                    "action_on_approval": f"rm -f {target_file}",
                    "section": "disk",
                    "os": "linux",
                    "classification": "safe-mechanical",
                    "reclaim_bytes": 7,
                    "precondition": "none",
                    "action": str(target_file),
                }
            ]
        ),
        encoding="utf-8",
    )

    dry = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(manifest), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert dry.returncode == 0
    assert target_file.exists()

    exe = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(manifest), "--execute"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert exe.returncode == 0
    assert not target_file.exists()

    # Missing option operands must be rejected instead of looping forever (F14/F31)
    for script, option in (
        (CLEANUP_SH, "--manifest"),
        (CLEANUP_SH, "--output-dir"),
        (AUDIT_SH, "--output-dir"),
        (AUDIT_SH, "--sections"),
        (AUDIT_SH, "--repo-roots"),
        (AUDIT_SH, "--max-depth"),
        (AUDIT_SH, "--forge-token"),
    ):
        bad = subprocess.run(
            [bash, str(script), option],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert bad.returncode != 0, f"{script.name} {option} without operand must fail"

    # needs-judgment package caches are refused and the suggested command is printed (F24)
    pip_dir = tmp_path / "pip-cache"
    pip_dir.mkdir()
    (pip_dir / "wheel.whl").write_text("cached", encoding="utf-8")
    pkg_manifest = tmp_path / "pkg-manifest.json"
    pkg_manifest.write_text(
        json.dumps(
            [
                {
                    "kind": "cache_pip",
                    "what": "pip cache",
                    "path": str(pip_dir),
                    "evidence": "test",
                    "recommendation": "needs_human_judgment",
                    "confidence": "high",
                    "rationale": "test",
                    "action_on_approval": "pip cache purge",
                    "section": "disk",
                    "os": "linux",
                    "classification": "needs-judgment",
                    "reclaim_bytes": 6,
                    "precondition": "none",
                    "action": "pip cache purge",
                }
            ]
        ),
        encoding="utf-8",
    )
    refused_pkg = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(pkg_manifest), "--execute"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert refused_pkg.returncode == 2
    assert (pip_dir / "wheel.whl").exists(), "needs-judgment cache must not be purged"
    pkg_log = (tmp_path / "cleanup-log.jsonl").read_text(encoding="utf-8")
    assert "pip cache purge" in pkg_log, "Refusal should print the suggested command"

    # A safe-mechanical item whose kind has no explicit handler must be refused (F5-F8 fallback)
    mystery_dir = tmp_path / "mystery-cache"
    mystery_dir.mkdir()
    (mystery_dir / "data.bin").write_text("keep", encoding="utf-8")
    mystery_manifest = tmp_path / "mystery-manifest.json"
    mystery_manifest.write_text(
        json.dumps(
            [
                {
                    "kind": "cache_browser_chrome",
                    "what": "Stale finding naming a broad directory",
                    "path": str(mystery_dir),
                    "evidence": "test",
                    "recommendation": "delete",
                    "confidence": "high",
                    "rationale": "test",
                    "action_on_approval": str(mystery_dir),
                    "section": "disk",
                    "os": "linux",
                    "classification": "safe-mechanical",
                    "reclaim_bytes": 4,
                    "precondition": "none",
                    "action": str(mystery_dir),
                }
            ]
        ),
        encoding="utf-8",
    )
    refused_kind = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(mystery_manifest), "--execute"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert refused_kind.returncode == 2
    assert (mystery_dir / "data.bin").exists(), "Unhandled kind must not be deleted"

    # A failed pgrep must not authorize deletion (F29)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_pgrep = fake_bin / "pgrep"
    fake_pgrep.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    fake_pgrep.chmod(0o755)
    guarded_file = tmp_path / "guarded.tmp"
    guarded_file.write_text("scratch", encoding="utf-8")
    guard_manifest = tmp_path / "guard-manifest.json"
    guard_manifest.write_text(
        json.dumps(
            [
                {
                    "kind": "temp_file",
                    "what": "Guarded scratch file",
                    "path": str(guarded_file),
                    "evidence": "test",
                    "recommendation": "delete",
                    "confidence": "high",
                    "rationale": "test",
                    "action_on_approval": str(guarded_file),
                    "section": "disk",
                    "os": "linux",
                    "classification": "safe-mechanical",
                    "reclaim_bytes": 7,
                    "precondition": "process_stopped:definitely-not-running",
                    "action": str(guarded_file),
                }
            ]
        ),
        encoding="utf-8",
    )
    guard_env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    guarded = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(guard_manifest), "--execute"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=guard_env,
    )
    assert guarded.returncode == 0
    assert guarded_file.exists(), "pgrep error must block deletion"
    guard_log = (tmp_path / "cleanup-log.jsonl").read_text(encoding="utf-8")
    assert "skipped_precondition" in guard_log

    _run_worktree_guard_cases(bash, tmp_path)


def _run_worktree_guard_cases(bash: str, tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git not found on PATH")
    git_env = {**os.environ, "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"}

    def run_git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [git, *args], check=True, capture_output=True, text=True, env=git_env
        )

    def commit_empty(repo: Path, message: str) -> None:
        run_git(
            "-C",
            str(repo),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-m",
            message,
        )

    repo = tmp_path / "mainrepo"
    run_git("init", "-b", "main", str(repo))
    commit_empty(repo, "init")
    run_git("-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD")

    wt_parent = tmp_path / "mainrepo-worktrees"
    wt_parent.mkdir()
    wt_merged = wt_parent / "merged\nworktree"
    run_git("-C", str(repo), "worktree", "add", "--detach", str(wt_merged))
    wt_unmerged = wt_parent / "space name"
    run_git("-C", str(repo), "worktree", "add", "--detach", str(wt_unmerged))
    commit_empty(wt_unmerged, "wip")

    hidden_repo = tmp_path / "hiderepo"
    run_git("init", "-b", "main", str(hidden_repo))
    commit_empty(hidden_repo, "init")
    run_git("-C", str(hidden_repo), "update-ref", "refs/remotes/origin/main", "HEAD")
    run_git("-C", str(hidden_repo), "config", "status.showUntrackedFiles", "no")
    hidden_parent = tmp_path / "hiderepo-worktrees"
    hidden_parent.mkdir()
    wt_hidden = hidden_parent / "hidden-untracked"
    run_git("-C", str(hidden_repo), "worktree", "add", "--detach", str(wt_hidden))
    (wt_hidden / "untracked.txt").write_text("wip", encoding="utf-8")

    repos_out = tmp_path / "repos-audit"
    audit = subprocess.run(
        [
            bash,
            str(AUDIT_SH),
            "--sections",
            "repos",
            "--repo-roots",
            str(tmp_path),
            "--output-dir",
            str(repos_out),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert audit.returncode == 0, f"audit.sh repos failed: {audit.stderr}"
    findings = json.loads((repos_out / "findings.json").read_text(encoding="utf-8"))
    merged = {f["path"]: f for f in findings if f["kind"] == "worktree_merged_clean"}
    review = {f["path"]: f for f in findings if f["kind"] == "worktree_needs_review"}

    # F23: the manifest path must be byte-identical to the audited path
    assert str(wt_merged) in merged
    assert merged[str(wt_merged)]["tip_sha"], "F26: audited tip must be recorded"
    # F25: an untracked file hidden by status.showUntrackedFiles=no still counts
    assert str(wt_hidden) in review
    assert str(wt_hidden) not in merged
    assert str(wt_unmerged) in review

    # F26: a tip moved after the audit must refuse removal
    stale_manifest = tmp_path / "stale-manifest.json"
    stale_manifest.write_text(json.dumps([merged[str(wt_merged)]]), encoding="utf-8")
    commit_empty(wt_merged, "post-audit")
    stale = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(stale_manifest), "--execute"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert stale.returncode == 2
    assert wt_merged.exists(), "Stale merge evidence must refuse removal"

    # F27: a locked worktree must refuse removal even with a fresh tip
    run_git("-C", str(repo), "worktree", "lock", str(wt_merged))
    tip = subprocess.run(
        [git, "-C", str(wt_merged), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        env=git_env,
    ).stdout.strip()
    locked_item = dict(merged[str(wt_merged)])
    locked_item["tip_sha"] = tip
    locked_manifest = tmp_path / "locked-manifest.json"
    locked_manifest.write_text(json.dumps([locked_item]), encoding="utf-8")
    locked = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(locked_manifest), "--execute"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert locked.returncode == 2
    assert wt_merged.exists(), "Locked worktree must refuse double-force removal"

    # Fresh evidence and unlocked: removal succeeds, collateral worktrees survive
    run_git("-C", str(repo), "worktree", "unlock", str(wt_merged))
    fresh = subprocess.run(
        [bash, str(CLEANUP_SH), "--manifest", str(locked_manifest), "--execute"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert fresh.returncode == 0, f"fresh cleanup failed: {fresh.stderr}"
    assert not wt_merged.exists()
    assert wt_unmerged.exists(), "Unmerged worktree must survive (F23 collateral)"
    assert (wt_hidden / "untracked.txt").exists()
