import json
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
            "kind": "temp_scratch_file",
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
        r.get("kind") == "temp_scratch_file" and r.get("outcome") == "executed"
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
                    "kind": "temp_scratch",
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
