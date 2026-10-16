import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

WRAP_DIRECTORY = Path(__file__).resolve().parent.parent
RUN_AUDIT_SCRIPT = WRAP_DIRECTORY / "tests" / "run-audit.sh"
SKILL_TEXT = (WRAP_DIRECTORY / "SKILL.md").read_text(encoding="utf-8")
CHAIN_TEXT = (WRAP_DIRECTORY / "references" / "chain.md").read_text(encoding="utf-8")

COMPLETED_SENTINEL = "That's a /wrap. Go ahead and close the session."
INTERRUPTED_SENTINEL = (
    "That was an interrupted /wrap. The session is NOT in a clean wrap state - "
    "some items may still be dirty, uncommitted, or unsaved."
)
CHAINED_SENTINEL = (
    "That was a chained /wrap. Link <n> is closed; "
    "start <chain>-<n+1> with the command above."
)
FILLED_CHAINED_SENTINEL = (
    "That was a chained /wrap. Link 1 is closed; "
    "start settle-and-cure-2 with the command above."
)


def find_posix_shell_executable() -> str | None:
    shell_on_path = shutil.which("bash") or shutil.which("sh")
    if shell_on_path:
        return str(Path(shell_on_path).resolve())
    if os.name == "nt":
        for candidate_path in (
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
            Path(r"C:\Program Files\Git\bin\sh.exe"),
        ):
            if candidate_path.is_file():
                return str(candidate_path.resolve())
    return None


def test_skill_carries_all_three_sentinels():
    assert COMPLETED_SENTINEL in SKILL_TEXT
    assert INTERRUPTED_SENTINEL in SKILL_TEXT
    assert CHAINED_SENTINEL in SKILL_TEXT


def test_chain_reference_ends_a_launching_wrap_with_the_chained_sentinel():
    assert CHAINED_SENTINEL in CHAIN_TEXT


def test_chain_reference_keeps_completed_sentinel_for_stopped_chains():
    assert COMPLETED_SENTINEL in CHAIN_TEXT
    assert "no successor and ends with the completed sentinel" in CHAIN_TEXT


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
