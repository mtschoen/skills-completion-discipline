import os
import subprocess
from pathlib import Path

import pytest
from test_launch_chain_successor import find_posix_shell_executable

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
