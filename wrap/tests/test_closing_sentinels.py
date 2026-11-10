import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_launch_chain_successor

WRAP_DIRECTORY = Path(__file__).resolve().parent.parent
RUN_AUDIT_SCRIPT = WRAP_DIRECTORY / "tests" / "run-audit.sh"
SKILL_TEXT = (WRAP_DIRECTORY / "SKILL.md").read_text(encoding="utf-8")
CHAIN_TEXT = (WRAP_DIRECTORY / "references" / "chain.md").read_text(encoding="utf-8")

COMPLETED_SENTINEL = "That's a /wrap. Go ahead and close the session."
INTERRUPTED_SENTINEL = (
    "That was an interrupted /wrap. The session is NOT in a clean wrap state - "
    "some items may still be dirty, uncommitted, or unsaved."
)
CHAINED_WINDOW_SENTINEL = (
    "That was a chained /wrap. Link <n> is closed; "
    "<chain>-<n+1> is already running in a new terminal window. "
    "Do not paste anything."
)
CHAINED_TMUX_SENTINEL = (
    "That was a chained /wrap. Link <n> is closed; "
    "<chain>-<n+1> is already running in tmux. "
    "Open it with the command above; do not start another."
)
CHAINED_NOT_STARTED_SENTINEL = (
    "That was a chained /wrap. Link <n> is closed; "
    "<chain>-<n+1> has NOT been started. Paste the command above to continue."
)
CHAINED_SENTINELS = (
    CHAINED_WINDOW_SENTINEL,
    CHAINED_TMUX_SENTINEL,
    CHAINED_NOT_STARTED_SENTINEL,
)
FILLED_CHAINED_SENTINEL = (
    "That was a chained /wrap. Link 1 is closed; "
    "settle-and-cure-2 has NOT been started. Paste the command above to continue."
)


def find_posix_shell_executable() -> str | None:
    # Native Git Bash must precede WSL launchers for Windows-generated harness paths.
    if os.name == "nt":
        for candidate_path in (
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
            Path(r"C:\Program Files\Git\bin\sh.exe"),
        ):
            if candidate_path.is_file():
                return str(candidate_path.resolve())
    shell_on_path = shutil.which("bash") or shutil.which("sh")
    if shell_on_path:
        return str(Path(shell_on_path).resolve())
    return None


@pytest.mark.parametrize(
    "shell_module",
    [
        pytest.param(sys.modules[__name__], id="closing-sentinels"),
        pytest.param(test_launch_chain_successor, id="launch-chain-successor"),
    ],
)
@pytest.mark.parametrize(
    (
        "platform_name",
        "bash_on_path",
        "sh_on_path",
        "native_candidates_exist",
        "expected_shell",
    ),
    [
        pytest.param(
            "nt",
            "wsl",
            False,
            True,
            "native",
            id="windowsapps-native-issue-49",
        ),
        pytest.param(
            "nt",
            "compatible",
            False,
            False,
            "compatible",
            id="windows-path-fallback",
        ),
        pytest.param(
            "posix",
            "compatible",
            False,
            True,
            "compatible",
            id="non-windows-path-first",
        ),
        pytest.param(
            "posix",
            None,
            True,
            False,
            "sh",
            id="non-windows-sh-fallback",
        ),
        pytest.param(
            "nt",
            None,
            False,
            False,
            None,
            id="no-shell",
        ),
    ],
)
def test_find_posix_shell_executable(
    shell_module,
    platform_name: str,
    bash_on_path: str | None,
    sh_on_path: bool,
    native_candidates_exist: bool,
    expected_shell: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_path = Path
    native_candidates = {
        r"C:\Program Files\Git\bin\bash.exe": tmp_path / "native" / "bin-bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe": tmp_path
        / "native"
        / "usr-bin-bash.exe",
        r"C:\Program Files\Git\bin\sh.exe": tmp_path / "native" / "bin-sh.exe",
    }
    if native_candidates_exist:
        for candidate in native_candidates.values():
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.touch()

    wsl_bash = tmp_path / "Microsoft" / "WindowsApps" / "bash.exe"
    compatible_bash = tmp_path / "compatible" / "bash.exe"
    compatible_sh = tmp_path / "compatible" / "sh"
    path_shells = {
        "bash": {"wsl": wsl_bash, "compatible": compatible_bash}.get(bash_on_path),
        "sh": compatible_sh if sh_on_path else None,
    }
    for shell in path_shells.values():
        if shell is not None:
            shell.parent.mkdir(parents=True, exist_ok=True)
            shell.touch()
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(str(shell.parent) for shell in path_shells.values() if shell),
    )

    def synthetic_path(value: str | Path) -> Path:
        return native_candidates.get(str(value), real_path(value))

    monkeypatch.setattr(shell_module, "os", SimpleNamespace(name=platform_name))
    monkeypatch.setattr(shell_module, "Path", synthetic_path)
    monkeypatch.setattr(
        shell_module,
        "shutil",
        SimpleNamespace(
            which=lambda name: str(path_shells[name]) if path_shells[name] else None
        ),
    )

    expected_path = {
        "native": native_candidates[r"C:\Program Files\Git\bin\bash.exe"],
        "compatible": compatible_bash,
        "sh": compatible_sh,
        None: None,
    }[expected_shell]
    assert shell_module.find_posix_shell_executable() == (
        str(expected_path.resolve()) if expected_path is not None else None
    )


def test_skill_carries_all_three_sentinels():
    assert COMPLETED_SENTINEL in SKILL_TEXT
    assert INTERRUPTED_SENTINEL in SKILL_TEXT
    for chained_sentinel in CHAINED_SENTINELS:
        assert chained_sentinel in SKILL_TEXT


def test_chain_reference_carries_every_chained_sentinel_form():
    for chained_sentinel in CHAINED_SENTINELS:
        assert chained_sentinel in CHAIN_TEXT


def test_chained_sentinel_forms_say_whether_the_successor_is_running():
    assert "already running" in CHAINED_WINDOW_SENTINEL
    assert "already running" in CHAINED_TMUX_SENTINEL
    assert "NOT been started" in CHAINED_NOT_STARTED_SENTINEL
    assert len(set(CHAINED_SENTINELS)) == len(CHAINED_SENTINELS)


@pytest.mark.parametrize(
    "expected_substring",
    [
        "Automatic launch is the rule.",
        "auto_through: <link number>",
        "estimated_links_remaining",
        "Not auto-started: <reason>",
        "This session's model is not the default.",
        "Take a fresh reading for the pool the successor's model draws from",
        "tmux attach -t <chain>-<n+1>",
        "tmux switch-client -t <chain>-<n+1>",
        "A display alone does not qualify for a window",
        "a new name for the same goal is not a pivot",
    ],
)
def test_chain_reference_states_the_automatic_launch_contract(
    expected_substring: str,
) -> None:
    assert expected_substring in CHAIN_TEXT


@pytest.mark.parametrize(
    ("case_identifier", "expected_substring"),
    [
        (
            "stopped-chains-completed-sentinel",
            "no successor and ends with the completed sentinel",
        ),
        (
            "finding-1-next-step-carry-count-tracking",
            "[carried: <count + 1>]",
        ),
        (
            "finding-2-fast-mode-defer-predecessor-deletion",
            "Fast mode (`--fast`) defers predecessor deletion",
        ),
    ],
    ids=[
        "stopped-chains-completed-sentinel",
        "finding-1-next-step-carry-count-tracking",
        "finding-2-fast-mode-defer-predecessor-deletion",
    ],
)
def test_chain_reference_keeps_completed_sentinel_for_stopped_chains(
    case_identifier: str,
    expected_substring: str,
) -> None:
    assert COMPLETED_SENTINEL in CHAIN_TEXT
    assert expected_substring in CHAIN_TEXT


@pytest.mark.parametrize(
    ("case_identifier", "sentinel_payload", "expected_turn_count"),
    [
        (
            "completed-control",
            COMPLETED_SENTINEL,
            1,
        ),
        (
            "interrupted-control",
            INTERRUPTED_SENTINEL,
            1,
        ),
        (
            "finding-1-filled-chained-result-stops-driver",
            FILLED_CHAINED_SENTINEL,
            1,
        ),
        (
            "missing-sentinel-control",
            "Wrap progress update without terminal sentinel marker",
            3,
        ),
    ],
    ids=[
        "completed-control",
        "interrupted-control",
        "finding-1-filled-chained-result-stops-driver",
        "missing-sentinel-control",
    ],
)
def test_audit_driver_termination_check(
    case_identifier: str,
    sentinel_payload: str,
    expected_turn_count: int,
) -> None:
    shell_executable = find_posix_shell_executable()
    if not shell_executable:
        pytest.skip("POSIX shell executable (sh or bash) not found on system")

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        binary_directory = temporary_root / "bin"
        binary_directory.mkdir()

        mock_payload_file = temporary_root / "mock_payload.json"
        mock_payload_record = {
            "type": "result",
            "result": sentinel_payload,
            "session_id": "mock-session-identifier",
        }
        mock_payload_file.write_text(
            json.dumps(mock_payload_record, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        mock_claude_script = binary_directory / "claude"
        mock_claude_script.write_text(
            f'#!/bin/sh\ncat "{mock_payload_file}"\n',
            encoding="utf-8",
        )
        mock_claude_script.chmod(0o755)

        driver_harness_script = (
            'source "$1"\n'
            'trace_file="$2/trace.jsonl"\n'
            'error_log="$2/stderr.log"\n'
            "MAX_TURNS=3\n"
            'drive_session "$2" "prompt" "$trace_file" "$error_log"\n'
            'printf "%s" "$TURNS"\n'
        )

        environment = os.environ.copy()
        environment["PATH"] = (
            f"{binary_directory}{os.pathsep}{environment.get('PATH', '')}"
        )

        completed_process = subprocess.run(
            [
                shell_executable,
                "-c",
                driver_harness_script,
                "_",
                str(RUN_AUDIT_SCRIPT),
                str(temporary_root),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed_process.returncode == 0, (
            f"Audit driver failed for {case_identifier}:\n{completed_process.stderr}"
        )
        observed_turn_count = int(completed_process.stdout.strip())
        assert observed_turn_count == expected_turn_count, (
            f"Turn count mismatch for {case_identifier}: "
            f"expected {expected_turn_count}, received {observed_turn_count}"
        )


@pytest.mark.parametrize(
    ("case_identifier", "sentinel_payload", "expected_classification"),
    [
        (
            "completed-control",
            COMPLETED_SENTINEL,
            "PASS sentinel-completed",
        ),
        (
            "interrupted-control",
            INTERRUPTED_SENTINEL,
            "PASS sentinel-interrupted",
        ),
        (
            "finding-2-filled-chained-result-classified-as-chained",
            FILLED_CHAINED_SENTINEL,
            "PASS sentinel-chained",
        ),
        (
            "missing-sentinel-control",
            "Wrap progress update without terminal sentinel marker",
            "FAIL sentinel-missing",
        ),
    ],
    ids=[
        "completed-control",
        "interrupted-control",
        "finding-2-filled-chained-result-classified-as-chained",
        "missing-sentinel-control",
    ],
)
def test_audit_generic_checks_classifier(
    case_identifier: str,
    sentinel_payload: str,
    expected_classification: str,
) -> None:
    shell_executable = find_posix_shell_executable()
    if not shell_executable:
        pytest.skip("POSIX shell executable (sh or bash) not found on system")

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        trace_file = temporary_root / "trace.jsonl"
        trace_record = {
            "type": "result",
            "result": sentinel_payload,
        }
        trace_file.write_text(
            json.dumps(trace_record, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        harness_script = 'source "$1"\ngeneric_checks "$2"\n'

        completed_process = subprocess.run(
            [
                shell_executable,
                "-c",
                harness_script,
                "_",
                str(RUN_AUDIT_SCRIPT),
                str(trace_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed_process.returncode == 0, (
            f"Generic checks execution failed for {case_identifier}:\n"
            f"{completed_process.stderr}"
        )
        output_lines = [
            line.strip()
            for line in completed_process.stdout.splitlines()
            if line.strip()
        ]
        assert expected_classification in output_lines, (
            f"Classification mismatch for {case_identifier}.\n"
            f"Expected: {expected_classification}\n"
            f"Received output lines: {output_lines}"
        )
