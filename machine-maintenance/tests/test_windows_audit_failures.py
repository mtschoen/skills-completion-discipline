# Native Windows integration matrix shares process fixtures in one module.
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
AUDIT_PS1 = SCRIPTS_DIR / "audit.ps1"
PROCESS_TIMEOUT = int(os.environ.get("MACHINE_MAINTENANCE_TEST_TIMEOUT", "180"))

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows audit execution requires Windows"
)


def _pwsh() -> str:
    resolved = shutil.which("pwsh")
    assert resolved is not None, "Windows regression tests require PowerShell 7 (pwsh)"
    return resolved


def _git_environment(home: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def _run_git(home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("git") or "git", *arguments],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_TIMEOUT,
        env=_git_environment(home),
    )


def _create_merged_worktree(home: Path, root: Path, name: str) -> tuple[Path, Path]:
    repository = root / name
    _run_git(home, "init", "-b", "main", str(repository))
    _run_git(
        home,
        "-C",
        str(repository),
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-m",
        "initial",
    )
    _run_git(
        home, "-C", str(repository), "update-ref", "refs/remotes/origin/main", "HEAD"
    )
    worktree_parent = root / f"{name}-worktrees"
    worktree_parent.mkdir()
    worktree = worktree_parent / "merged"
    _run_git(home, "-C", str(repository), "worktree", "add", "--detach", str(worktree))
    return worktree, worktree_parent


# `pwsh -File` passes every trailing token to the script as a literal string, so
# it cannot bind several tokens to audit.ps1's [string[]] parameters. This
# wrapper decodes them from JSON and invokes the real script with typed arrays.
AUDIT_WRAPPER = r"""
Set-StrictMode -Version Latest
$parameters = @{ OutputDir = $env:MM_OUTPUT_DIR }
if ($env:MM_SECTIONS_JSON) {
    $parameters.Sections = [string[]]@($env:MM_SECTIONS_JSON | ConvertFrom-Json)
}
if ($env:MM_REPO_ROOTS_JSON) {
    $parameters.RepoRoots = [string[]]@($env:MM_REPO_ROOTS_JSON | ConvertFrom-Json)
}
& $env:MM_AUDIT_PS1 @parameters
if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }
exit 0
"""


def _run_audit(
    output_dir: Path,
    home: Path,
    local_app_data: Path,
    *,
    sections: Sequence[str] = (),
    repo_roots: Sequence[str] = (),
) -> subprocess.CompletedProcess[str]:
    wrapper = output_dir.parent / "audit-wrapper.ps1"
    wrapper.write_text(AUDIT_WRAPPER, encoding="utf-8")
    return subprocess.run(
        [_pwsh(), "-NoProfile", "-File", str(wrapper)],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
        env={
            **_git_environment(home),
            "LOCALAPPDATA": str(local_app_data),
            "MM_AUDIT_PS1": str(AUDIT_PS1),
            "MM_OUTPUT_DIR": str(output_dir),
            "MM_SECTIONS_JSON": json.dumps(list(sections)) if sections else "",
            "MM_REPO_ROOTS_JSON": json.dumps(list(repo_roots)) if repo_roots else "",
        },
    )


def _merged_worktree_findings(output_dir: Path) -> list[dict]:
    findings = json.loads(
        (output_dir / "findings.json").read_text(encoding="utf-8-sig")
    )
    return [item for item in findings if item["kind"] == "worktree_merged_clean"]


def test_repo_roots_drive_worktree_discovery_and_parent_paths(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first_root = tmp_path / "roots" / "first"
    second_root = tmp_path / "roots" / "second"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)
    first_worktree, _ = _create_merged_worktree(home, first_root, "first-repo")
    second_worktree, _ = _create_merged_worktree(home, second_root, "second-repo")

    result = _run_audit(
        tmp_path / "out",
        home,
        tmp_path / "local",
        sections=("repos",),
        repo_roots=(str(first_root), str(second_root), str(first_root)),
    )

    assert result.returncode == 0, result.stderr
    findings = _merged_worktree_findings(tmp_path / "out")
    assert [item["path"] for item in findings].count(str(first_worktree)) == 1
    assert [item["path"] for item in findings].count(str(second_worktree)) == 1
    assert len(findings) == 2
    raw = json.loads(
        (tmp_path / "out" / "raw" / "repos.json").read_text(encoding="utf-8-sig")
    )
    summaries = {item["path"]: item for item in raw["worktrees"]}
    assert summaries[str(first_worktree)]["parent_repo"] == str(
        first_root / "first-repo"
    )
    assert summaries[str(second_worktree)]["parent_repo"] == str(
        second_root / "second-repo"
    )


def test_repo_roots_default_to_home_only_when_not_supplied(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    worktree, _ = _create_merged_worktree(home, home, "home-repo")

    result = _run_audit(
        tmp_path / "out",
        home,
        tmp_path / "local",
        sections=("repos",),
    )

    assert result.returncode == 0, result.stderr
    findings = _merged_worktree_findings(tmp_path / "out")
    assert [item["path"] for item in findings] == [str(worktree)]


HELPER_PROBE = r"""
Set-StrictMode -Version Latest
. $env:MM_HELPERS
$arguments = @($env:MM_ARGUMENTS_JSON | ConvertFrom-Json)
$result = Invoke-CommandWithTimeout -FilePath $env:MM_TARGET -ArgumentList $arguments -WorkingDirectory $env:MM_WORKING_DIRECTORY -TimeoutSeconds ([int]$env:MM_TIMEOUT_SECONDS)
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $env:MM_RESULT -Encoding utf8
"""


def _invoke_helper(
    tmp_path: Path,
    target: str,
    arguments: list[str],
    *,
    working_directory: Path | None = None,
    timeout_seconds: int = 15,
) -> dict:
    probe = tmp_path / "helper-probe.ps1"
    probe.write_text(HELPER_PROBE, encoding="utf-8")
    result_path = tmp_path / "helper-result.json"
    completed = subprocess.run(
        [_pwsh(), "-NoProfile", "-File", str(probe)],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
        env={
            **os.environ,
            "MM_HELPERS": str(SCRIPTS_DIR / "common" / "windows-helpers.ps1"),
            "MM_TARGET": target,
            "MM_ARGUMENTS_JSON": json.dumps(arguments),
            "MM_WORKING_DIRECTORY": str(working_directory or ""),
            "MM_TIMEOUT_SECONDS": str(timeout_seconds),
            "MM_RESULT": str(result_path),
        },
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(result_path.read_text(encoding="utf-8-sig"))


def test_powershell_shim_preserves_arguments_working_directory_and_exit_code(
    tmp_path: Path,
) -> None:
    shim = tmp_path / "shim space.ps1"
    shim.write_text(
        "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Values)\n"
        "[Console]::Write((@{values=$values;cwd=(Get-Location).Path} | ConvertTo-Json -Compress))\n"
        "exit 7\n",
        encoding="utf-8",
    )
    arguments = [
        "plain",
        "space value",
        "-literal",
        "; & echo injected > injected.txt &",
    ]

    result = _invoke_helper(tmp_path, str(shim), arguments, working_directory=tmp_path)

    assert result["exit_code"] == 7
    assert result["error"] is None
    payload = json.loads(result["stdout"])
    assert payload["values"] == arguments
    assert payload["cwd"] == str(tmp_path)
    assert not (tmp_path / "injected.txt").exists()


def test_command_shim_preserves_arguments_without_command_injection(
    tmp_path: Path,
) -> None:
    shim = tmp_path / "shim space.cmd"
    shim.write_text(
        "@echo off\n"
        "setlocal DisableDelayedExpansion\n"
        "echo ARG1=%1\n"
        "echo ARG2=%2\n"
        "echo ARG3=%3\n"
        "echo ARG4=%4\n"
        "echo ARG5=%5\n"
        "echo ARG6=%6\n"
        "echo ARG7=%7\n"
        "echo ARG8=%8\n"
        "echo ARG9=%9\n"
        "echo CWD=%CD%\n"
        "exit /b 7\n",
        encoding="utf-8",
    )
    arguments = [
        "space value",
        "& echo injected > injected.txt &",
        "%PATH%",
        "^|<>!",
        "(paren) | pipe | < redir > out.txt",
        'say "hi" & echo injected2 > injected2.txt',
        'a" & echo injected3 > injected3.txt',
        "!!bang!!",
        "a^^b",
    ]

    result = _invoke_helper(tmp_path, str(shim), arguments, working_directory=tmp_path)

    assert result["exit_code"] == 7
    assert result["error"] is None
    output_lines = result["stdout"].splitlines()
    assert 'ARG1="space value"' in output_lines
    assert 'ARG2="& echo injected > injected.txt &"' in output_lines
    assert 'ARG3="%PATH%"' in output_lines
    assert 'ARG4="^|<>!"' in output_lines
    assert 'ARG5="(paren) | pipe | < redir > out.txt"' in output_lines
    # A literal quote reaches the batch doubled: cmd.exe splits batch parameters
    # on quote state, so "" keeps the value inside one quoted token, and a shim
    # forwarding %* to a program hands that program a single quote back.
    assert 'ARG6="say ""hi"" & echo injected2 > injected2.txt"' in output_lines
    assert 'ARG7="a"" & echo injected3 > injected3.txt"' in output_lines
    assert 'ARG8="!!bang!!"' in output_lines
    assert 'ARG9="a^^b"' in output_lines
    assert f"CWD={tmp_path}" in output_lines
    assert not (tmp_path / "injected.txt").exists()
    assert not (tmp_path / "injected2.txt").exists()
    assert not (tmp_path / "injected3.txt").exists()
    assert not (tmp_path / "out.txt").exists()


def test_direct_executable_invocation_is_unchanged(tmp_path: Path) -> None:
    result = _invoke_helper(
        tmp_path,
        _pwsh(),
        ["-NoProfile", "-Command", "[Console]::Write('direct-ok')"],
    )

    assert result["exit_code"] == 0
    assert result["stdout"] == "direct-ok"
    assert result["error"] is None


def test_unavailable_command_returns_error_evidence(tmp_path: Path) -> None:
    result = _invoke_helper(tmp_path, str(tmp_path / "missing-npm"), [])

    assert result["exit_code"] == -1
    assert result["error"]


def test_helper_returns_timeout_result_for_long_running_shim(tmp_path: Path) -> None:
    shim = tmp_path / "slow.ps1"
    shim.write_text("Start-Sleep -Seconds 60\n", encoding="utf-8")

    result = _invoke_helper(tmp_path, str(shim), [], timeout_seconds=1)

    assert result["timed_out"] is True
    assert result["exit_code"] == -1
    assert "Timed out" in result["error"]


SECTION_PROBE = r"""
Set-StrictMode -Version Latest
. (Join-Path $env:MM_COMMON 'windows-helpers.ps1')
. (Join-Path $env:MM_COMMON $env:MM_MODULE)
function Invoke-CommandWithTimeout {
    param([string]$FilePath, [string[]]$ArgumentList = @(), [int]$TimeoutSeconds = 15, [string]$WorkingDirectory = '')
    $fixtureName = [System.IO.Path]::GetFileName($FilePath) + '.json'
    $fixturePath = Join-Path $env:MM_FIXTURES $fixtureName
    if (-not (Test-Path -LiteralPath $fixturePath)) { throw "No command fixture for $FilePath" }
    return Get-Content -LiteralPath $fixturePath -Raw -Encoding utf8 | ConvertFrom-Json
}
function Get-PnpDevice {
    [CmdletBinding()]param()
    if ($env:MM_PNP_ERROR -eq '1') { throw 'simulated PnP query failure' }
    $fixturePath = Join-Path $env:MM_FIXTURES 'pnp.json'
    if (Test-Path -LiteralPath $fixturePath) {
        foreach ($device in @(Get-Content -LiteralPath $fixturePath -Raw -Encoding utf8 | ConvertFrom-Json)) {
            Write-Output $device
        }
    }
}
function Get-Service {
    [CmdletBinding()]param([string]$Name)
    if ($env:MM_SERVICE_STATUS) {
        return [PSCustomObject]@{ Status = $env:MM_SERVICE_STATUS; StartType = 'Manual' }
    }
    return $null
}
$result = switch ($env:MM_SECTION) {
    'harness' { Invoke-HarnessAudit -HomeDir $env:MM_HOME }
    'disk' { Invoke-DiskAudit -HomeDir $env:MM_HOME -LocalAppData $env:MM_LOCAL -MaxDepth 1 -IsElevated $true -SkipElevated $false }
    'os' { Invoke-OsAudit -IsElevated $true -SkipElevated $false }
    'processes' { Invoke-ProcessesAudit -HomeDir $env:MM_HOME }
    default { throw "Unknown section fixture: $env:MM_SECTION" }
}
[PSCustomObject]@{
    findings = @($result.findings)
    clean = @($result.clean | ForEach-Object { [string]$_ })
    blocked = @($result.blocked | ForEach-Object { [string]$_ })
    raw = $result.raw
} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $env:MM_RESULT -Encoding utf8
"""


def _command_result(
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    error: str | None = None,
) -> dict:
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "error": error,
    }


def _run_section(
    tmp_path: Path,
    module_name: str,
    section: str,
    *,
    command_results: dict[str, dict] | None = None,
    pnp_devices: list[dict] | None = None,
    pnp_error: bool = False,
    service_status: str = "",
) -> dict:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    local = tmp_path / "local"
    local.mkdir()
    for command, result in (command_results or {}).items():
        (fixtures / f"{command}.json").write_text(json.dumps(result), encoding="utf-8")
    if pnp_devices is not None:
        (fixtures / "pnp.json").write_text(json.dumps(pnp_devices), encoding="utf-8")
    probe = tmp_path / "section-probe.ps1"
    probe.write_text(SECTION_PROBE, encoding="utf-8")
    result_path = tmp_path / "section-result.json"
    completed = subprocess.run(
        [_pwsh(), "-NoProfile", "-File", str(probe)],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
        env={
            **os.environ,
            "MM_COMMON": str(SCRIPTS_DIR / "common"),
            "MM_MODULE": module_name,
            "MM_SECTION": section,
            "MM_FIXTURES": str(fixtures),
            "MM_HOME": str(home),
            "MM_LOCAL": str(local),
            "MM_RESULT": str(result_path),
            "MM_PNP_ERROR": "1" if pnp_error else "0",
            "MM_SERVICE_STATUS": service_status,
        },
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(result_path.read_text(encoding="utf-8-sig"))


def _assert_section_category(
    result: dict,
    category: str,
    needle: str,
    clean_scope: str,
    finding_kind: str,
) -> None:
    clean = "\n".join(result["clean"])
    blocked = "\n".join(result["blocked"])
    findings = [item for item in result["findings"] if item["kind"] == finding_kind]
    if category == "clean":
        assert needle in clean
        assert clean_scope not in blocked
        assert not findings
    elif category == "blocked":
        assert needle in blocked
        assert clean_scope not in clean
        assert not findings
    else:
        assert category == "finding"
        assert any(item["kind"] == needle for item in findings)
        assert clean_scope not in clean
        assert clean_scope not in blocked


@pytest.mark.parametrize(
    ("command_result", "category", "needle"),
    [
        pytest.param(
            _command_result(stdout="{}"),
            "clean",
            "npm reported no outdated global packages",
            id="empty-map",
        ),
        pytest.param(
            _command_result(
                exit_code=1,
                stdout='{"left-pad":{"current":"1.0.0","wanted":"1.1.0","latest":"2.0.0"}}',
            ),
            "finding",
            "npm_global_outdated",
            id="outdated-map",
        ),
        pytest.param(
            _command_result(exit_code=2, stdout="{}", stderr="registry failed"),
            "blocked",
            "npm outdated -g",
            id="command-error-issue-27",
        ),
        pytest.param(
            _command_result(
                exit_code=-1, stdout="{}", timed_out=True, error="Timed out"
            ),
            "blocked",
            "npm outdated -g",
            id="timeout-issue-27",
        ),
        pytest.param(
            _command_result(stdout="not-json"),
            "blocked",
            "npm outdated -g",
            id="malformed-json-issue-27",
        ),
        pytest.param(
            _command_result(stdout='{"error":{"code":"EREGISTRY"}}'),
            "blocked",
            "npm outdated -g",
            id="json-error-object-issue-27",
        ),
        pytest.param(
            _command_result(
                stdout='{"left-pad":{"current":"1.0.0","wanted":"1.1.0","latest":"2.0.0"}}'
            ),
            "blocked",
            "npm outdated -g",
            id="inconsistent-success-map-issue-27",
        ),
    ],
)
def test_npm_outdated_requires_recognized_command_and_json_results(
    tmp_path: Path, command_result: dict, category: str, needle: str
) -> None:
    result = _run_section(
        tmp_path,
        "windows-harness.ps1",
        "harness",
        command_results={"npm": command_result},
    )

    _assert_section_category(result, category, needle, "npm", "npm_global_outdated")
    if category == "blocked":
        assert result["raw"]["npm_global_outdated"] is None
    elif category == "clean":
        assert result["raw"]["npm_global_outdated"] == {}
    else:
        assert result["raw"]["npm_global_outdated"]["left-pad"]["latest"] == "2.0.0"


@pytest.mark.parametrize(
    ("command_result", "category", "needle", "expected_recommendation"),
    [
        pytest.param(
            _command_result(stdout="Component Store Cleanup Recommended : No"),
            "clean",
            "WinSxS component store analyze clean",
            False,
            id="recognized-no",
        ),
        pytest.param(
            _command_result(stdout="Component Store Cleanup Recommended : Yes"),
            "finding",
            "dism_component_store",
            True,
            id="recognized-yes",
        ),
        pytest.param(
            _command_result(
                exit_code=1,
                stdout="Component Store Cleanup Recommended : No",
                stderr="DISM failed",
            ),
            "blocked",
            "DISM AnalyzeComponentStore",
            None,
            id="failure-issue-27",
        ),
        pytest.param(
            _command_result(
                exit_code=-1,
                stdout="Component Store Cleanup Recommended : No",
                timed_out=True,
                error="Timed out",
            ),
            "blocked",
            "DISM AnalyzeComponentStore",
            None,
            id="timeout-issue-27",
        ),
        pytest.param(
            _command_result(stdout=""),
            "blocked",
            "DISM AnalyzeComponentStore",
            None,
            id="empty-issue-27",
        ),
        pytest.param(
            _command_result(stdout="Bereinigung empfohlen: Nein"),
            "blocked",
            "DISM AnalyzeComponentStore",
            None,
            id="unrecognized-localized-issue-27",
        ),
    ],
)
def test_dism_requires_successful_recognized_analysis(
    tmp_path: Path,
    command_result: dict,
    category: str,
    needle: str,
    expected_recommendation: bool | None,
) -> None:
    result = _run_section(
        tmp_path,
        "windows-disk.ps1",
        "disk",
        command_results={"dism.exe": command_result},
    )

    _assert_section_category(
        result, category, needle, "WinSxS component store", "dism_component_store"
    )
    assert result["raw"]["dism_cleanup_recommended"] == expected_recommendation


@pytest.mark.parametrize(
    (
        "command_result",
        "service_status",
        "category",
        "needle",
        "expected_synced",
        "expected_source",
    ),
    [
        pytest.param(
            _command_result(stdout="Source: time.windows.com\r\n"),
            "",
            "clean",
            "Windows Time synced",
            True,
            "time.windows.com",
            id="usable-source",
        ),
        pytest.param(
            _command_result(stdout="Source: Local CMOS Clock\r\n"),
            "",
            "finding",
            "w32tm_unsynced",
            False,
            "Local CMOS Clock",
            id="local-clock",
        ),
        pytest.param(
            _command_result(stdout="Source: Free-running System Clock\r\n"),
            "",
            "finding",
            "w32tm_unsynced",
            False,
            "Free-running System Clock",
            id="free-running-clock",
        ),
        pytest.param(
            _command_result(exit_code=1, stderr="service stopped"),
            "Stopped",
            "blocked",
            "w32tm /query /status",
            None,
            "Service Stopped (Manual)",
            id="failed-query-stopped-service-issue-27",
        ),
        pytest.param(
            _command_result(stdout="Leap Indicator: 3"),
            "",
            "blocked",
            "w32tm /query /status",
            None,
            "Unavailable",
            id="unparseable-issue-27",
        ),
        pytest.param(
            _command_result(stdout=""),
            "",
            "blocked",
            "w32tm /query /status",
            None,
            "Unavailable",
            id="empty-issue-27",
        ),
        pytest.param(
            _command_result(exit_code=-1, timed_out=True, error="Timed out"),
            "",
            "blocked",
            "w32tm /query /status",
            None,
            "Unavailable",
            id="timeout-unavailable-service-issue-27",
        ),
        pytest.param(
            _command_result(stdout="Source: Unknown\r\n"),
            "",
            "blocked",
            "w32tm /query /status",
            None,
            "Unavailable",
            id="unknown-source-issue-27",
        ),
    ],
)
def test_clock_sync_requires_a_usable_source(
    tmp_path: Path,
    command_result: dict,
    service_status: str,
    category: str,
    needle: str,
    expected_synced: bool | None,
    expected_source: str,
) -> None:
    result = _run_section(
        tmp_path,
        "windows-os.ps1",
        "os",
        command_results={"w32tm.exe": command_result},
        service_status=service_status,
    )

    _assert_section_category(result, category, needle, "Windows Time", "w32tm_unsynced")
    assert result["raw"]["w32tm_synced"] == expected_synced
    assert result["raw"]["w32tm_source"] == expected_source


@pytest.mark.parametrize(
    (
        "devices",
        "pnp_error",
        "category",
        "needle",
        "expected_count",
        "expected_known",
        "expected_problems",
    ),
    [
        pytest.param(
            None,
            True,
            "blocked",
            "Get-PnpDevice",
            None,
            0,
            0,
            id="query-failure-issue-27",
        ),
        pytest.param(
            [
                {
                    "Status": "OK",
                    "Class": "Net",
                    "FriendlyName": "Adapter",
                    "InstanceId": "PCI\\1",
                }
            ],
            False,
            "clean",
            "PnP devices report Status OK",
            1,
            1,
            0,
            id="observed-ok-device",
        ),
        pytest.param(
            [],
            False,
            "blocked",
            "Get-PnpDevice",
            0,
            0,
            0,
            id="empty-device-set-issue-27",
        ),
        pytest.param(
            [
                {
                    "Status": "Unknown",
                    "Class": "Net",
                    "FriendlyName": "Ghost",
                    "InstanceId": "PCI\\2",
                }
            ],
            False,
            "blocked",
            "Get-PnpDevice",
            1,
            0,
            0,
            id="unknown-only-issue-27",
        ),
        pytest.param(
            [
                {
                    "Status": "OK",
                    "Class": "Net",
                    "FriendlyName": "Adapter",
                    "InstanceId": "PCI\\1",
                },
                {
                    "Status": "Unknown",
                    "Class": "Net",
                    "FriendlyName": "Ghost",
                    "InstanceId": "PCI\\2",
                },
                {
                    "Status": "Error",
                    "Class": "USB",
                    "FriendlyName": "Device",
                    "InstanceId": "USB\\3",
                },
            ],
            False,
            "finding",
            "pnp_problem_devices",
            3,
            2,
            1,
            id="observed-problem-device",
        ),
    ],
)
def test_pnp_clean_claim_requires_observed_known_devices(
    tmp_path: Path,
    devices: list[dict] | None,
    pnp_error: bool,
    category: str,
    needle: str,
    expected_count: int | None,
    expected_known: int,
    expected_problems: int,
) -> None:
    result = _run_section(
        tmp_path,
        "windows-os.ps1",
        "os",
        command_results={
            "w32tm.exe": _command_result(stdout="Source: time.windows.com")
        },
        pnp_devices=devices,
        pnp_error=pnp_error,
    )

    _assert_section_category(
        result, category, needle, "PnP devices", "pnp_problem_devices"
    )
    assert result["raw"]["pnp_device_count"] == expected_count
    assert result["raw"]["pnp_known_device_count"] == expected_known
    assert result["raw"]["pnp_query_failed"] == pnp_error
    assert len(result["raw"]["pnp_problems"]) == expected_problems


def test_wsl_reclaim_advice_uses_experimental_section(tmp_path: Path) -> None:
    result = _run_section(tmp_path, "windows-processes.ps1", "processes")

    finding = next(
        item for item in result["findings"] if item["kind"] == "wslconfig_missing"
    )
    assert "[experimental] autoMemoryReclaim=gradual" in finding["action_on_approval"]
    assert "[wsl2] autoMemoryReclaim" not in finding["action_on_approval"]


def test_final_clock_summary_renders_unknown_as_unknown(tmp_path: Path) -> None:
    copied_scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPTS_DIR, copied_scripts)
    (copied_scripts / "common" / "windows-os.ps1").write_text(
        "function Invoke-OsAudit {\n"
        "    param([bool]$IsElevated = $false, [bool]$SkipElevated = $false)\n"
        "    return [PSCustomObject]@{\n"
        "        findings = [System.Collections.Generic.List[object]]::new()\n"
        "        clean = [System.Collections.Generic.List[string]]::new()\n"
        "        blocked = [System.Collections.Generic.List[string]]::new()\n"
        "        raw = [PSCustomObject]@{ w32tm_synced = $null; w32tm_source = 'Unknown' }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    output_dir = tmp_path / "out"
    completed = subprocess.run(
        [
            _pwsh(),
            "-NoProfile",
            "-File",
            str(copied_scripts / "audit.ps1"),
            "-Sections",
            "os",
            "-OutputDir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
        env={
            **_git_environment(home),
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
    )

    assert completed.returncode == 0, completed.stderr
    report = (output_dir / "report.md").read_text(encoding="utf-8-sig")
    assert "w32tm sync state: unknown (Source: Unknown)" in report
    raw = json.loads((output_dir / "raw" / "os.json").read_text(encoding="utf-8-sig"))
    assert raw["w32tm_synced"] is None


def test_windows_audit_output_failure_is_visible(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    output_file = tmp_path / "out"
    output_file.write_text("not a directory", encoding="utf-8")

    result = _run_audit(
        output_file,
        home,
        tmp_path / "local",
        sections=("env",),
    )

    assert result.returncode != 0
    assert "Audit complete" not in result.stdout


def _run_cleanup_with_command_mode(
    tmp_path: Path, mode: str
) -> tuple[subprocess.CompletedProcess[str], list[dict], Path]:
    copied_scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPTS_DIR, copied_scripts)
    helper_path = copied_scripts / "common" / "windows-helpers.ps1"
    with helper_path.open("a", encoding="utf-8") as helper:
        helper.write(
            "\nfunction Invoke-CommandWithTimeout {\n"
            "    param([string]$FilePath, [string[]]$ArgumentList = @(), [int]$TimeoutSeconds = 15, [string]$WorkingDirectory = '')\n"
            "    if ($env:MM_COMMAND_MODE -eq 'throw') { throw 'simulated launch failure' }\n"
            "    if ($env:MM_COMMAND_MODE -eq 'timeout') {\n"
            "        return [PSCustomObject]@{ exit_code = -1; stdout = ''; stderr = ''; timed_out = $true; error = 'Timed out after 30s' }\n"
            "    }\n"
            "    return [PSCustomObject]@{ exit_code = 1; stdout = ''; stderr = 'simulated prune failure'; timed_out = $false; error = $null }\n"
            "}\n"
        )
    repository = tmp_path / "repo"
    repository.mkdir()
    scratch_file = tmp_path / "scratch.tmp"
    scratch_file.write_text("scratch", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "kind": "worktree_prunable",
                    "what": "Prunable worktree",
                    "path": str(repository),
                    "action": "git worktree prune",
                    "classification": "safe-mechanical",
                    "precondition": "none",
                },
                {
                    "kind": "temp_file",
                    "what": "Scratch file",
                    "path": str(scratch_file),
                    "action": str(scratch_file),
                    "classification": "safe-mechanical",
                    "precondition": "none",
                },
            ]
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            _pwsh(),
            "-NoProfile",
            "-File",
            str(copied_scripts / "cleanup.ps1"),
            "-Manifest",
            str(manifest),
            "-Execute",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROCESS_TIMEOUT,
        env={**os.environ, "MM_COMMAND_MODE": mode},
    )
    records = [
        json.loads(line)
        for line in (tmp_path / "cleanup-log.jsonl")
        .read_text(encoding="utf-8-sig")
        .splitlines()
        if line
    ]
    return completed, records, scratch_file


@pytest.mark.parametrize(
    ("mode", "expected_evidence"),
    [
        ("failure", "simulated prune failure"),
        ("throw", "simulated launch failure"),
        ("timeout", "Timed out after 30s"),
    ],
)
def test_windows_cleanup_failure_is_logged_and_fails_overall_status(
    tmp_path: Path, mode: str, expected_evidence: str
) -> None:
    result, records, scratch_file = _run_cleanup_with_command_mode(tmp_path, mode)

    assert result.returncode != 0
    assert not scratch_file.exists()
    assert records[0]["outcome"] == "failed"
    assert expected_evidence in records[0]["stderr"]
    assert records[1]["outcome"] == "executed"
    assert records[-1]["kind"] == "volume_free_space"
