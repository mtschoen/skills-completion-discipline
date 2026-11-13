import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from test_launch_chain_successor import (
    CHAIN_REFERENCE_PATH,
    find_posix_shell_executable,
    format_printed_launch_command,
)

SKILL_PATH = (Path(__file__).parents[1] / "SKILL.md").resolve()

SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "launch-chain-successor.sh"
).resolve()

# Prepends the mock directory inside the shell so the path form matches the
# shell's own (Git Bash on Windows converts it; a POSIX host uses it as is).
HARNESS = 'PATH="$(cd "$1" && pwd):$PATH"\nexport PATH\nshift\nexec bash "$@"\n'

MOCK_CLAUDE = (
    "#!/bin/sh\n"
    'printf "%s\\n" "$@" > "$MOCK_ARGUMENT_LOG"\n'
    'env | grep -E "^(NO_COLOR|FORCE_COLOR|CLAUDECODE|CLAUDE_PID|CLAUDE_CODE_)" '
    '> "$MOCK_ENVIRONMENT_LOG" || true\n'
)

INHERITED_ENVIRONMENT = {
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "CLAUDECODE": "1",
    "CLAUDE_PID": "4242",
    "CLAUDE_CODE_SESSION_ID": "parent-session-identifier",
    "CLAUDE_CODE_CHILD_SESSION": "1",
}


def run_launcher(
    temporary_root: Path,
    arguments: list[str],
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    shell_executable = find_posix_shell_executable()
    if not shell_executable:
        pytest.skip("POSIX shell executable (sh or bash) not found on system")

    mock_binary_directory = temporary_root / "bin"
    mock_binary_directory.mkdir()
    mock_claude = mock_binary_directory / "claude"
    mock_claude.write_text(MOCK_CLAUDE, encoding="utf-8", newline="\n")
    mock_claude.chmod(0o755)

    argument_log = temporary_root / "arguments.txt"
    environment_log = temporary_root / "environment.txt"

    environment = os.environ.copy()
    environment.update(INHERITED_ENVIRONMENT)
    environment["MOCK_ARGUMENT_LOG"] = argument_log.as_posix()
    environment["MOCK_ENVIRONMENT_LOG"] = environment_log.as_posix()

    completed_process = subprocess.run(
        [
            shell_executable,
            "-c",
            HARNESS,
            "_",
            mock_binary_directory.as_posix(),
            SCRIPT_PATH.as_posix(),
            *arguments,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed_process, argument_log, environment_log


def test_shell_launcher_starts_claude_with_model_mode_and_prompt(
    tmp_path: Path,
) -> None:
    prompt_file = tmp_path / "resume-prompt.txt"
    prompt_text = "You are link 3 of session chain settle-and-cure; read the handoff."
    prompt_file.write_text(prompt_text + "\n", encoding="utf-8", newline="\n")

    completed_process, argument_log, _ = run_launcher(
        tmp_path,
        ["settle-and-cure-3", "opus", "auto", prompt_file.as_posix()],
    )

    assert completed_process.returncode == 0, completed_process.stderr
    assert argument_log.read_text(encoding="utf-8").splitlines() == [
        "-n",
        "settle-and-cure-3",
        "--model",
        "opus",
        "--permission-mode",
        "auto",
        prompt_text,
    ]


def test_shell_launcher_scrubs_inherited_session_variables(tmp_path: Path) -> None:
    prompt_file = tmp_path / "resume-prompt.txt"
    prompt_file.write_text("continue the chain\n", encoding="utf-8", newline="\n")

    completed_process, _, environment_log = run_launcher(
        tmp_path,
        ["settle-and-cure-3", "opus", "auto", prompt_file.as_posix()],
    )

    assert completed_process.returncode == 0, completed_process.stderr
    assert environment_log.read_text(encoding="utf-8").strip() == ""


@pytest.mark.parametrize(
    ("case_identifier", "file_content"),
    [
        ("missing-prompt-file", None),
        ("empty-prompt-file", ""),
        ("whitespace-only-prompt-file", " \n\t\n"),
    ],
    ids=["missing-prompt-file", "empty-prompt-file", "whitespace-only-prompt-file"],
)
def test_shell_launcher_refuses_unusable_prompt_file(
    case_identifier: str,
    file_content: str | None,
    tmp_path: Path,
) -> None:
    prompt_file = tmp_path / "resume-prompt.txt"
    if file_content is not None:
        prompt_file.write_text(file_content, encoding="utf-8", newline="\n")

    completed_process, argument_log, _ = run_launcher(
        tmp_path,
        ["settle-and-cure-3", "opus", "auto", prompt_file.as_posix()],
    )

    assert completed_process.returncode != 0, case_identifier
    assert not argument_log.exists(), (
        f"claude must not be invoked for {case_identifier}"
    )


def test_shell_launcher_requires_all_four_arguments(tmp_path: Path) -> None:
    completed_process, argument_log, _ = run_launcher(
        tmp_path,
        ["settle-and-cure-3", "auto"],
    )

    assert completed_process.returncode == 2
    assert not argument_log.exists()


def read_bash_transcript_mode_query_from_reference() -> str:
    reference_text = CHAIN_REFERENCE_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^### Successor permission mode[^\n]*\n.*?From the Bash tool:\s*```text\r?\n(.*?)^\s*```",
        reference_text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "Bash transcript permission-mode query not found in chain.md"
    return match.group(1).strip()


def read_printed_command_template_from_reference() -> str:
    reference_text = CHAIN_REFERENCE_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^### Printed command[^\n]*\n.*?^```text\r?\n(.*?)^```",
        reference_text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "Printed command fenced block not found in chain.md"
    return match.group(1).strip()


@pytest.mark.parametrize(
    ("attendance", "transcript_modes", "expected_mode"),
    [
        ("attended", ("default", "acceptEdits", "plan"), "acceptEdits"),
        ("unattended", ("default", "acceptEdits", "plan"), "auto"),
    ],
    ids=["attended-acceptEdits", "unattended-auto"],
)
def test_printed_command_carries_resolved_successor_permission_mode(
    attendance: str,
    transcript_modes: tuple[str, ...],
    expected_mode: str,
    tmp_path: Path,
) -> None:
    shell_executable = find_posix_shell_executable()
    if not shell_executable:
        pytest.skip("POSIX shell executable (sh or bash) not found on system")

    reference_text = CHAIN_REFERENCE_PATH.read_text(encoding="utf-8")
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    assert read_printed_command_template_from_reference() == (
        "claude -n <chain>-<n+1> --model <model> "
        "--permission-mode <successor mode> <quoted resume prompt>"
    )
    assert (
        "printing `claude -n <chain>-<n+1> --model <model> --permission-mode <successor mode>`"
        in reference_text
    )
    assert (
        "`claude -n <chain>-<n+1> --model <model> --permission-mode <successor mode> <quoted resume prompt>`"
        in skill_text
    )
    assert (
        "exact filled `claude -n ... --model ... --permission-mode ...` command"
        in skill_text
    )

    session_id = "00000000-0000-4000-8000-000000000042"
    claude_config_dir = tmp_path / ".claude"
    project_dir = claude_config_dir / "projects" / "demo-project"
    project_dir.mkdir(parents=True)
    transcript_file = project_dir / f"{session_id}.jsonl"
    transcript_file.write_text(
        "".join(
            json.dumps(
                {
                    "type": "permission-mode",
                    "permissionMode": mode,
                    "sessionId": session_id,
                }
            )
            + "\n"
            for mode in transcript_modes
        ),
        encoding="utf-8",
        newline="\n",
    )

    if attendance == "unattended":
        successor_mode = "auto"
    else:
        query = read_bash_transcript_mode_query_from_reference()
        query_env = os.environ.copy()
        query_env["CLAUDE_CONFIG_DIR"] = claude_config_dir.as_posix()
        query_env["CLAUDE_CODE_SESSION_ID"] = session_id
        query_result = subprocess.run(
            [shell_executable, "-c", query],
            env=query_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert query_result.returncode == 0, query_result.stderr
        successor_mode = query_result.stdout.strip() or "default"

    assert successor_mode == expected_mode

    handoff_path = (
        tmp_path / "handoffs" / "2026-11-11-settle-and-cure-2.md"
    ).as_posix()
    collapsed_prompt, printed_command = format_printed_launch_command(
        chain_name="settle-and-cure",
        next_link=3,
        model="opus",
        handoff_path=handoff_path,
        receiving_shell="posix",
        permission_mode=successor_mode,
    )
    assert f"--permission-mode {expected_mode}" in printed_command

    mock_binary_directory = tmp_path / "bin"
    mock_binary_directory.mkdir()
    mock_claude = mock_binary_directory / "claude"
    mock_claude.write_text(MOCK_CLAUDE, encoding="utf-8", newline="\n")
    mock_claude.chmod(0o755)
    argument_log = tmp_path / "arguments.txt"
    environment_log = tmp_path / "environment.txt"

    exec_env = os.environ.copy()
    exec_env["PATH"] = (
        f"{mock_binary_directory.as_posix()}{os.pathsep}{exec_env.get('PATH', '')}"
    )
    exec_env["MOCK_ARGUMENT_LOG"] = argument_log.as_posix()
    exec_env["MOCK_ENVIRONMENT_LOG"] = environment_log.as_posix()

    completed_process = subprocess.run(
        [shell_executable, "-s"],
        input=printed_command,
        env=exec_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed_process.returncode == 0, completed_process.stderr
    assert argument_log.read_text(encoding="utf-8").splitlines() == [
        "-n",
        "settle-and-cure-3",
        "--model",
        "opus",
        "--permission-mode",
        expected_mode,
        collapsed_prompt,
    ]
