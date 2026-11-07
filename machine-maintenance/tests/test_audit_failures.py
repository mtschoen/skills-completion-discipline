# Unix behavior matrix shares controlled command fixtures in one module.
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
AUDIT_SH = SKILL_DIR / "scripts" / "audit.sh"
PROCESS_TIMEOUT = int(os.environ.get("MACHINE_MAINTENANCE_TEST_TIMEOUT", "120"))
BASE_COMMANDS = ("awk", "du", "head", "mkdir", "rm", "sed", "tr", "wc")

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Unix audit execution runs on Linux/macOS"
)


def _command_directory(root: Path) -> Path:
    command_dir = root / "commands"
    command_dir.mkdir()
    for name in BASE_COMMANDS:
        source = shutil.which(name)
        assert source is not None, f"Required test utility is unavailable: {name}"
        (command_dir / name).symlink_to(source)
    (command_dir / "python3").symlink_to(sys.executable)
    _write_command(command_dir, "id", "printf '%s\\n' 1000")
    _write_command(command_dir, "uname", "printf '%s\\n' Linux")
    _write_command(command_dir, "ps", "exit 0")
    return command_dir


def _write_command(command_dir: Path, name: str, body: str) -> None:
    command_path = command_dir / name
    command_path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    command_path.chmod(0o755)


def _run_audit(
    output_dir: Path,
    sections: str,
    command_dir: Path,
    home: Path,
    *,
    path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": str(command_dir) if path is None else path,
    }
    return subprocess.run(
        [
            shutil.which("bash") or "/bin/bash",
            str(AUDIT_SH),
            "--sections",
            sections,
            "--output-dir",
            str(output_dir),
            "--skip-elevated",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
        env=environment,
        cwd=home,
    )


def _report_categories(output_dir: Path) -> tuple[str, str, list[dict]]:
    report = (output_dir / "report.md").read_text(encoding="utf-8")
    clean = report.split("## Checked and clean\n", 1)[1].split(
        "## Blocked or skipped", 1
    )[0]
    blocked = report.split("## Blocked or skipped\n", 1)[1]
    findings = json.loads((output_dir / "findings.json").read_text(encoding="utf-8"))
    return clean, blocked, findings


def _assert_check_category(
    output_dir: Path,
    category: str,
    needle: str,
    clean_scope: str,
    finding_kind: str,
) -> None:
    clean, blocked, findings = _report_categories(output_dir)
    matching_findings = [item for item in findings if item["kind"] == finding_kind]
    if category == "clean":
        assert needle in clean
        assert clean_scope not in blocked
        assert not matching_findings
    elif category == "blocked":
        assert needle in blocked
        assert clean_scope not in clean
        assert not matching_findings
    else:
        assert category == "finding"
        assert any(item["kind"] == needle for item in matching_findings)
        assert clean_scope not in clean
        assert clean_scope not in blocked


@pytest.mark.parametrize(
    ("command_body", "category", "needle"),
    [
        pytest.param("exit 2", "blocked", "systemctl --failed", id="failure-issue-27"),
        pytest.param("exit 0", "clean", "0 failed units", id="empty-success"),
        pytest.param(
            "printf '%s\\n' 'failed.service loaded failed failed Example service'",
            "finding",
            "systemd_failed_units",
            id="failed-unit",
        ),
    ],
)
def test_systemd_failed_query_requires_successful_evidence(
    tmp_path: Path, command_body: str, category: str, needle: str
) -> None:
    command_dir = _command_directory(tmp_path)
    _write_command(
        command_dir,
        "systemctl",
        f'if [ "$1" = --failed ]; then\n{command_body}\nelse\nexit 0\nfi',
    )

    result = _run_audit(tmp_path / "out", "processes", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    _assert_check_category(
        tmp_path / "out",
        category,
        needle,
        "[processes] systemctl --failed",
        "systemd_failed_units",
    )


@pytest.mark.parametrize(
    ("command_body", "category", "needle"),
    [
        pytest.param(
            "exit 2", "blocked", "journalctl --disk-usage", id="failure-issue-27"
        ),
        pytest.param(
            "printf '%s\\n' 'unexpected output'",
            "blocked",
            "journalctl --disk-usage",
            id="unrecognized-issue-27",
        ),
        pytest.param(
            "printf '%s\\n' 'Archived and active journals take up 24.0M in the file system.'",
            "clean",
            "systemd journal usage acceptable",
            id="recognized-small-usage",
        ),
        pytest.param(
            "printf '%s\\n' 'Archived and active journals take up 1.2G in the file system.'",
            "finding",
            "linux_journal_vacuum",
            id="recognized-large-usage",
        ),
        pytest.param(
            "printf '%s\n' 'Archived and active journals take up 1.2T in the file system.'",
            "finding",
            "linux_journal_vacuum",
            id="recognized-terabyte-usage",
        ),
    ],
)
def test_journal_usage_requires_recognized_successful_output(
    tmp_path: Path, command_body: str, category: str, needle: str
) -> None:
    command_dir = _command_directory(tmp_path)
    _write_command(command_dir, "journalctl", command_body)

    result = _run_audit(tmp_path / "out", "disk", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    _assert_check_category(
        tmp_path / "out",
        category,
        needle,
        "[disk] systemd journal",
        "linux_journal_vacuum",
    )


@pytest.mark.parametrize(
    ("du_body", "category"),
    [
        pytest.param("exit 2", "blocked", id="failure-issue-40"),
        pytest.param("exit 0", "blocked", id="empty-output-issue-40"),
        pytest.param("printf '%s\t%s\n' 4 \"$3\"", "clean", id="success-control"),
    ],
)
def test_failed_du_probe_is_blocked_instead_of_zero_bytes(
    tmp_path: Path, du_body: str, category: str
) -> None:
    command_dir = _command_directory(tmp_path)
    (command_dir / "du").unlink()
    _write_command(command_dir, "du", du_body)
    (tmp_path / ".cache" / "uv").mkdir(parents=True)

    result = _run_audit(tmp_path / "out", "disk", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    clean, blocked, _findings = _report_categories(tmp_path / "out")
    if category == "blocked":
        assert "du -sk" in blocked
        assert "uv cache" not in clean
    else:
        assert "uv cache under threshold (4096 bytes)" in clean
        assert "du -sk" not in blocked


@pytest.mark.parametrize(
    ("ps_body", "category"),
    [
        pytest.param("exit 2", "blocked", id="failure-issue-40"),
        pytest.param("exit 0", "clean", id="success-control"),
    ],
)
def test_failed_ps_probe_is_blocked_instead_of_no_orphans(
    tmp_path: Path, ps_body: str, category: str
) -> None:
    command_dir = _command_directory(tmp_path)
    _write_command(command_dir, "ps", ps_body)

    result = _run_audit(tmp_path / "out", "processes", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    clean, blocked, findings = _report_categories(tmp_path / "out")
    assert not [item for item in findings if item["kind"] == "orphan_processes"]
    if category == "blocked":
        assert "ps -eo" in blocked
        assert "No orphaned" not in clean
    else:
        assert "No orphaned" in clean
        assert "ps -eo" not in blocked


@pytest.mark.parametrize(
    ("config_text", "category", "expected_count"),
    [
        pytest.param("[user]\n\temail = test@example.com\n", "clean", 0, id="no-value"),
        pytest.param(
            "[safe]\n\tdirectory = /one\n\tdirectory = /two\n", "clean", 2, id="entries"
        ),
        pytest.param("[safe\n", "blocked", None, id="fatal-error-issue-27"),
    ],
)
def test_git_safe_directory_distinguishes_no_value_from_fatal_error(
    tmp_path: Path, config_text: str, category: str, expected_count: int | None
) -> None:
    command_dir = _command_directory(tmp_path)
    (command_dir / "git").symlink_to(shutil.which("git"))
    (tmp_path / ".gitconfig").write_text(config_text, encoding="utf-8")

    result = _run_audit(tmp_path / "out", "env", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    _assert_check_category(
        tmp_path / "out",
        category,
        "git config --global --get-all safe.directory"
        if category == "blocked"
        else "safe.directory count is clean",
        "[env] Global gitconfig safe.directory",
        "gitconfig_safe_directory_bloat",
    )
    raw = json.loads(
        (tmp_path / "out" / "raw" / "env.json").read_text(encoding="utf-8")
    )
    assert raw["safe_directory_count"] == expected_count


def test_missing_unix_commands_are_blocked_instead_of_clean(tmp_path: Path) -> None:
    command_dir = _command_directory(tmp_path)

    result = _run_audit(tmp_path / "out", "processes,disk,env", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    clean, blocked, findings = _report_categories(tmp_path / "out")
    assert "systemctl --failed" in blocked
    assert "journalctl --disk-usage" in blocked
    assert "git config --global --get-all safe.directory" in blocked
    assert "systemctl --failed is clean" not in clean
    assert "systemd journal usage acceptable" not in clean
    assert "safe.directory count is clean" not in clean
    assert not [
        item
        for item in findings
        if item["kind"]
        in {
            "systemd_failed_units",
            "linux_journal_vacuum",
            "gitconfig_safe_directory_bloat",
        }
    ]
    raw = json.loads(
        (tmp_path / "out" / "raw" / "env.json").read_text(encoding="utf-8")
    )
    assert raw["safe_directory_count"] is None


@pytest.mark.parametrize(
    ("path_template", "category", "expected_counts"),
    [
        pytest.param(
            ":{commands}", "finding", (1, 0, 0, 0), id="leading-colon-issue-27"
        ),
        pytest.param(
            "{commands}::{other}",
            "finding",
            (1, 0, 0, 0),
            id="doubled-colon-issue-27",
        ),
        pytest.param(
            "{commands}:", "finding", (1, 0, 0, 0), id="trailing-colon-issue-27"
        ),
        pytest.param("{commands}:.", "finding", (0, 1, 0, 0), id="dot-entry-issue-27"),
        pytest.param(
            "{commands}:relative-bin",
            "finding",
            (0, 1, 0, 0),
            id="existing-relative-entry-issue-27",
        ),
        pytest.param("{commands}", "clean", (0, 0, 0, 0), id="valid-absolute-path"),
        pytest.param(
            "{commands}:{commands}",
            "finding",
            (0, 0, 0, 1),
            id="duplicate-entry",
        ),
        pytest.param(
            "{commands}:{missing}",
            "finding",
            (0, 0, 1, 0),
            id="dead-entry",
        ),
    ],
)
def test_path_hygiene_preserves_empty_and_relative_entries(
    tmp_path: Path,
    path_template: str,
    category: str,
    expected_counts: tuple[int, int, int, int],
) -> None:
    command_dir = _command_directory(tmp_path)
    other_dir = tmp_path / "other-bin"
    other_dir.mkdir()
    (tmp_path / "relative-bin").mkdir()
    path = path_template.format(
        commands=command_dir,
        other=other_dir,
        missing=tmp_path / "missing-bin",
    )

    result = _run_audit(tmp_path / "out", "env", command_dir, tmp_path, path=path)

    assert result.returncode == 0, result.stderr
    _assert_check_category(
        tmp_path / "out",
        category,
        "All PATH directories exist" if category == "clean" else "path_hygiene",
        "[env] All PATH directories",
        "path_hygiene",
    )
    raw = json.loads(
        (tmp_path / "out" / "raw" / "env.json").read_text(encoding="utf-8")
    )
    empty_count, relative_count, dead_count, duplicate_count = expected_counts
    assert raw["empty_path_entries"] == empty_count
    assert raw["relative_path_entries"] == relative_count
    assert raw["dead_path_entries"] == dead_count
    assert raw["dupe_path_entries"] == duplicate_count


@pytest.mark.parametrize(
    ("config_text", "grep_status", "category", "needle"),
    [
        pytest.param(
            None,
            1,
            "blocked",
            "No supported harness model config files",
            id="no-configs-issue-27",
        ),
        pytest.param(
            '{"model":"sonnet"}\n',
            1,
            "clean",
            "No retired model IDs",
            id="inspected-clean-config",
        ),
        pytest.param(
            '{"model":"terra"}\n',
            0,
            "finding",
            "harness_retired_model_ids",
            id="retired-model",
        ),
        pytest.param(
            '{"model":"sonnet"}\n',
            2,
            "blocked",
            "Failed to inspect model IDs",
            id="failed-read-issue-27",
        ),
    ],
)
def test_harness_reports_scan_scope_and_unevaluated_checks(
    tmp_path: Path,
    config_text: str | None,
    grep_status: int,
    category: str,
    needle: str,
) -> None:
    command_dir = _command_directory(tmp_path)
    (command_dir / "basename").symlink_to(shutil.which("basename"))
    _write_command(command_dir, "grep", f"exit {grep_status}")
    config_path = tmp_path / ".config" / "opencode" / "opencode.json"
    if config_text is not None:
        config_path.parent.mkdir(parents=True)
        config_path.write_text(config_text, encoding="utf-8")

    result = _run_audit(tmp_path / "out", "harness", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    _assert_check_category(
        tmp_path / "out",
        category,
        needle,
        "[harness] No retired model IDs",
        "harness_retired_model_ids",
    )
    clean, blocked, _ = _report_categories(tmp_path / "out")
    if category == "clean":
        assert str(config_path) in clean
    assert "Unix hook validation is not implemented" in blocked
    assert "Unix MCP command resolution is not implemented" in blocked
    assert "Unix stale-project evaluation is not implemented" in blocked


def test_macos_process_probes_do_not_claim_unimplemented_health(
    tmp_path: Path,
) -> None:
    command_dir = _command_directory(tmp_path)
    _write_command(command_dir, "uname", "printf '%s\\n' Darwin")
    _write_command(command_dir, "launchctl", "exit 0")
    _write_command(command_dir, "lsof", "exit 0")

    result = _run_audit(tmp_path / "out", "processes", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    clean, blocked, findings = _report_categories(tmp_path / "out")
    assert "launch-agent health is not evaluated" in blocked
    assert "listener health is not evaluated" in blocked
    assert "Checked launchctl list" not in clean
    assert not findings


@pytest.mark.parametrize("operating_system", ["Linux", "Darwin"])
def test_unix_smart_and_clock_health_are_explicitly_unimplemented(
    tmp_path: Path, operating_system: str
) -> None:
    command_dir = _command_directory(tmp_path)
    _write_command(command_dir, "uname", f"printf '%s\\n' {operating_system}")

    result = _run_audit(tmp_path / "out", "os", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    clean, blocked, findings = _report_categories(tmp_path / "out")
    assert "SMART health evaluation is not implemented" in blocked
    assert "Clock health evaluation is not implemented" in blocked
    assert "Checked diskutil info" not in clean
    assert "network time sync" not in clean
    if operating_system == "Linux":
        reboot_findings = [
            item for item in findings if item["kind"] == "os_pending_reboot"
        ]
        assert bool(reboot_findings) != (
            "[os] No /var/run/reboot-required flag present" in clean
        )
    else:
        assert not findings


@pytest.mark.parametrize(
    "destination",
    [
        "output-file",
        ".findings.jsonl",
        "findings.json",
        "report.md",
        "raw/env.json",
    ],
)
def test_audit_publication_failures_return_nonzero_without_success_message(
    tmp_path: Path, destination: str
) -> None:
    command_dir = _command_directory(tmp_path)
    output_dir = tmp_path / "out"
    if destination == "output-file":
        output_dir.write_text("not a directory", encoding="utf-8")
    else:
        obstructed_path = output_dir / destination
        obstructed_path.parent.mkdir(parents=True, exist_ok=True)
        obstructed_path.mkdir()

    result = _run_audit(output_dir, "env", command_dir, tmp_path)

    assert result.returncode != 0
    assert "Audit complete" not in result.stdout
    assert result.stderr


def test_audit_renderer_failure_is_not_masked_by_later_report_writes(
    tmp_path: Path,
) -> None:
    command_dir = _command_directory(tmp_path)
    (command_dir / "python3").unlink()
    _write_command(
        command_dir,
        "python3",
        f'if [ "$1" = - ]; then\n'
        f"printf '%s\\n' 'simulated renderer failure' >&2\n"
        f"exit 1\n"
        f"fi\n"
        f'exec "{sys.executable}" "$@"',
    )

    result = _run_audit(
        tmp_path / "out",
        "env",
        command_dir,
        tmp_path,
        path=f"{command_dir}:{tmp_path / 'missing-bin'}",
    )

    assert result.returncode != 0
    assert "Audit complete" not in result.stdout
    assert "simulated renderer failure" in result.stderr


def test_audit_successful_publication_control(tmp_path: Path) -> None:
    command_dir = _command_directory(tmp_path)

    result = _run_audit(tmp_path / "out", "env", command_dir, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Audit complete" in result.stdout
    assert isinstance(
        json.loads((tmp_path / "out" / "findings.json").read_text(encoding="utf-8")),
        list,
    )


def _cleanup_item(kind: str, path: Path, action: str) -> dict:
    return {
        "kind": kind,
        "what": kind,
        "path": str(path),
        "action": action,
        "classification": "safe-mechanical",
        "precondition": "none",
    }


def _run_cleanup(
    manifest: Path, command_dir: Path, home: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            shutil.which("bash") or "/bin/bash",
            str(SKILL_DIR / "scripts" / "cleanup.sh"),
            "--manifest",
            str(manifest),
            "--execute",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
        env={**os.environ, "PATH": str(command_dir), "HOME": str(home)},
        cwd=home,
    )


def _cleanup_records(manifest: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (manifest.parent / "cleanup-log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]


def test_cleanup_command_failure_is_retained_and_fails_overall_status(
    tmp_path: Path,
) -> None:
    command_dir = _command_directory(tmp_path)
    (command_dir / "dirname").symlink_to(shutil.which("dirname"))
    _write_command(
        command_dir,
        "git",
        "printf '%s\\n' 'simulated prune failure' >&2\nexit 1",
    )
    repository = tmp_path / "repo"
    repository.mkdir()
    scratch_file = tmp_path / "scratch.tmp"
    scratch_file.write_text("scratch", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                _cleanup_item("worktree_prunable", repository, "git worktree prune"),
                _cleanup_item("temp_file", scratch_file, str(scratch_file)),
            ]
        ),
        encoding="utf-8",
    )

    result = _run_cleanup(manifest, command_dir, tmp_path)

    assert result.returncode != 0
    assert not scratch_file.exists()
    records = _cleanup_records(manifest)
    assert records[0]["outcome"] == "failed"
    assert "simulated prune failure" in records[0]["stderr"]
    assert records[1]["outcome"] == "executed"
    assert records[-1]["kind"] == "volume_free_space"


def test_cleanup_launch_failure_preserves_evidence_and_later_actions(
    tmp_path: Path,
) -> None:
    command_dir = _command_directory(tmp_path)
    (command_dir / "dirname").symlink_to(shutil.which("dirname"))
    scratch_file = tmp_path / "scratch.tmp"
    scratch_file.write_text("scratch", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                _cleanup_item(
                    "macos_brew_cleanup", tmp_path / "missing", "brew cleanup"
                ),
                _cleanup_item("temp_file", scratch_file, str(scratch_file)),
            ]
        ),
        encoding="utf-8",
    )

    result = _run_cleanup(manifest, command_dir, tmp_path)

    assert result.returncode != 0
    assert not scratch_file.exists()
    records = _cleanup_records(manifest)
    assert records[0]["outcome"] == "failed"
    assert records[0]["stderr"]
    assert records[1]["outcome"] == "executed"
    assert records[-1]["kind"] == "volume_free_space"
