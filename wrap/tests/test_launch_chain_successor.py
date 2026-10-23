"""End-to-end launcher script and multi-shell printed-command round-trip tests (exceeds 500 lines to keep POSIX, PowerShell, and cmd.exe subprocess harnesses in one module)."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


def find_powershell_executable() -> str | None:
    powershell_on_path = shutil.which("pwsh") or shutil.which("powershell")
    if powershell_on_path:
        return str(Path(powershell_on_path).resolve())
    for executable_name in ("pwsh.exe", "pwsh"):
        dotnet_powershell = Path.home() / ".dotnet" / "tools" / executable_name
        if dotnet_powershell.is_file() and os.access(dotnet_powershell, os.X_OK):
            return str(dotnet_powershell.resolve())
    return None


def get_safe_child_path_directories(powershell_executable: str) -> list[str]:
    candidate_directories: list[Path] = [
        Path(powershell_executable).parent,
    ]

    if os.name == "nt":
        system_root_value = (
            os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        )
        system_root_directory = Path(system_root_value)
        candidate_directories.extend(
            [
                system_root_directory / "System32",
                system_root_directory,
                system_root_directory / "System32" / "WindowsPowerShell" / "v1.0",
            ]
        )
    else:
        candidate_directories.extend(
            [
                Path("/usr/bin"),
                Path("/bin"),
            ]
        )

    claude_executable_names = (
        {"claude.exe", "claude.cmd", "claude.bat", "claude.ps1", "claude.com"}
        if os.name == "nt"
        else {"claude"}
    )

    safe_directories: list[str] = []
    for candidate in candidate_directories:
        if not candidate.is_dir():
            continue
        resolved_candidate = candidate.resolve()
        contains_installed_claude = any(
            (resolved_candidate / executable_name).is_file()
            for executable_name in claude_executable_names
        )
        if contains_installed_claude:
            continue
        candidate_string = str(resolved_candidate)
        if candidate_string not in safe_directories:
            safe_directories.append(candidate_string)

    return safe_directories


@pytest.mark.parametrize(
    (
        "case_identifier",
        "directory_name",
        "file_content",
        "file_exists",
        "expect_success",
    ),
    [
        (
            "finding-1-literal-path-square-brackets",
            "handoffs[1]",
            "Resume continuation prompt in bracketed directory",
            True,
            True,
        ),
        (
            "finding-2-missing-prompt-file",
            "handoffs",
            None,
            False,
            False,
        ),
        (
            "finding-2-empty-prompt-file",
            "handoffs",
            "",
            True,
            False,
        ),
        (
            "finding-2-whitespace-only-prompt-file",
            "handoffs",
            "   \n\t  \r\n  ",
            True,
            False,
        ),
        (
            "baseline-standard-prompt-file",
            "handoffs",
            "Standard continuation prompt text",
            True,
            True,
        ),
    ],
    ids=[
        "finding-1-literal-path-square-brackets",
        "finding-2-missing-prompt-file",
        "finding-2-empty-prompt-file",
        "finding-2-whitespace-only-prompt-file",
        "baseline-standard-prompt-file",
    ],
)
def test_launch_chain_successor_prompt_file_handling(
    case_identifier: str,
    directory_name: str,
    file_content: str | None,
    file_exists: bool,
    expect_success: bool,
) -> None:
    powershell_executable = find_powershell_executable()
    if not powershell_executable:
        pytest.skip("PowerShell executable (pwsh) not found on system")

    powershell_path = Path(powershell_executable).resolve()
    assert powershell_path.is_file(), (
        f"PowerShell executable does not exist at {powershell_path}"
    )
    assert powershell_path.is_absolute(), (
        f"PowerShell executable path is not absolute: {powershell_path}"
    )

    script_path = (
        Path(__file__).parents[1] / "scripts" / "launch-chain-successor.ps1"
    ).resolve()
    assert script_path.is_file(), f"Launcher script does not exist at {script_path}"

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        mock_binary_directory = temporary_root / "bin"
        mock_binary_directory.mkdir()

        invocation_log = temporary_root / "invoked_arguments.txt"
        write_mock_claude_executable(mock_binary_directory, invocation_log)

        safe_directories = get_safe_child_path_directories(powershell_executable)
        safe_system_path = os.pathsep.join(safe_directories)

        # Ensure installed Claude locations cannot be searched.
        assert shutil.which("claude", path=safe_system_path) is None, (
            f"Installed Claude executable unexpectedly searchable in safe system path: {safe_system_path}"
        )

        child_path = os.pathsep.join([str(mock_binary_directory), safe_system_path])
        environment = os.environ.copy()
        environment["PATH"] = child_path

        resolved_mock_claude = shutil.which("claude", path=child_path)
        assert resolved_mock_claude is not None, (
            f"Mock claude executable could not be resolved in child PATH: {child_path}"
        )
        assert (
            Path(resolved_mock_claude).parent.resolve()
            == mock_binary_directory.resolve()
        ), (
            f"Resolved claude ({resolved_mock_claude}) did not resolve from mock directory ({mock_binary_directory})"
        )

        prompt_directory = temporary_root / directory_name
        prompt_directory.mkdir(parents=True, exist_ok=True)
        prompt_file = prompt_directory / "resume-prompt.txt"

        if file_exists:
            assert file_content is not None
            prompt_file.write_text(file_content, encoding="utf-8")

        completed_process = subprocess.run(
            [
                powershell_executable,
                "-NoProfile",
                "-File",
                str(script_path),
                "-Name",
                "chain-successor-test",
                "-PermissionMode",
                "auto",
                "-PromptFile",
                str(prompt_file),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        if expect_success:
            assert completed_process.returncode == 0, (
                f"Expected success for {case_identifier}, but received returncode {completed_process.returncode}.\n"
                f"Standard output:\n{completed_process.stdout}\n"
                f"Standard error:\n{completed_process.stderr}"
            )
            assert invocation_log.is_file(), (
                f"Expected claude to be invoked for {case_identifier}, but {invocation_log} does not exist"
            )
            invoked_lines = invocation_log.read_text(encoding="utf-8").splitlines()
            expected_lines = [
                "-n",
                "chain-successor-test",
                "--permission-mode",
                "auto",
                file_content,
            ]
            assert invoked_lines == expected_lines
        else:
            assert completed_process.returncode != 0, (
                f"Expected non-zero returncode for {case_identifier}, but command succeeded.\n"
                f"Standard output:\n{completed_process.stdout}\n"
                f"Standard error:\n{completed_process.stderr}"
            )
            assert not invocation_log.exists(), (
                f"Claude CLI must not be invoked for {case_identifier}, but {invocation_log} was written"
            )


RESUME_PROMPT_TEMPLATE = (
    "You are link {next_link} of session chain {chain_name}. Before anything else, read the "
    "handoff {handoff_path} in full, then continue from its section Next steps, "
    "in order. After writing your own complete handoff, delete that handoff and its "
    ".resume-prompt.txt (defer deletion under --fast and report the deferred cleanup in the summary). "
    "Honor every ruling under Inherited owner rulings without reopening any of them, "
    "including those made in earlier links. Keep the standing "
    "routing rules: dispatch subagents for well-specified lanes and route "
    "sustained volume to external harnesses (codex, opencode, agy, kimi, local "
    "qwen) as the handoff section How to run the lanes describes; the orchestrator "
    "seat does triage, briefs, review and delicate steps only. Ask owner questions "
    "one per turn through the question widget. When the wrap nudge fires and you "
    "reach a natural stopping point, or the owner asks, wrap and continue the chain "
    "as link {future_link}."
)


def write_mock_claude_executable(
    mock_binary_directory: Path,
    invocation_log: Path,
) -> None:
    if os.name == "nt":
        mock_claude_command_script = mock_binary_directory / "claude.cmd"
        mock_claude_command_script.write_text(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "setlocal DisableDelayedExpansion\r\n"
            ":loop\r\n"
            'if "%~1"=="" goto done\r\n'
            'set "ARGUMENT=%~1"\r\n'
            "setlocal EnableDelayedExpansion\r\n"
            f'>>"{invocation_log}" echo(!ARGUMENT!\r\n'
            "endlocal\r\n"
            "shift\r\n"
            "goto loop\r\n"
            ":done\r\n",
            encoding="utf-8",
        )
        mock_claude_batch_script = mock_binary_directory / "claude.bat"
        mock_claude_batch_script.write_text(
            mock_claude_command_script.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    else:
        mock_claude_shell_script = mock_binary_directory / "claude"
        mock_claude_shell_script.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$@" > "{invocation_log}"\n',
            encoding="utf-8",
        )
        mock_claude_shell_script.chmod(0o755)


def quote_posix_argument(argument: str) -> str:
    """Quotes an argument for POSIX shells using literal single-quoting."""
    return "'" + argument.replace("'", "'\\''") + "'"


def quote_powershell_argument(argument: str) -> str:
    """Quotes an argument for PowerShell using literal single-quoting."""
    return "'" + argument.replace("'", "''") + "'"


def quote_cmd_argument(argument: str) -> str:
    """Quotes an argument for cmd.exe with one pair of double quotes."""
    if any(character in argument for character in ('"', "%", "!")):
        raise ValueError(
            "A cmd.exe double-quoted argument must not contain '\"', '%', or '!'; "
            "use the .resume-prompt.txt prompt-file fallback instead"
        )
    if argument.endswith("\\"):
        raise ValueError("A cmd.exe argument must not end in a backslash")
    return '"' + argument + '"'


RECEIVING_SHELL_QUOTERS = {
    "posix": quote_posix_argument,
    "powershell": quote_powershell_argument,
    "cmd": quote_cmd_argument,
}


def format_printed_launch_command(
    chain_name: str,
    next_link: int,
    model: str,
    handoff_path: str,
    receiving_shell: str = "posix",
) -> tuple[str, str]:
    """Formats the collapsed resume prompt and the launch command for the receiving shell."""
    if receiving_shell not in RECEIVING_SHELL_QUOTERS:
        raise ValueError(f"Unsupported receiving shell: {receiving_shell!r}")
    quote_argument = RECEIVING_SHELL_QUOTERS[receiving_shell]
    prompt = RESUME_PROMPT_TEMPLATE.format(
        chain_name=chain_name,
        next_link=next_link,
        handoff_path=handoff_path,
        future_link=next_link + 1,
    )
    collapsed_prompt = " ".join(prompt.split())
    quoted_prompt = quote_argument(collapsed_prompt)
    command = f"claude -n {chain_name}-{next_link} --model {model} {quoted_prompt}"
    return collapsed_prompt, command


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


@pytest.mark.parametrize(
    ("case_identifier", "handoff_path_component"),
    [
        (
            "finding-1-command-substitution-dollar-parentheses",
            "$(printf INJECTED >&2)",
        ),
        (
            "finding-1-command-substitution-backticks",
            "`printf INJECTED >&2`",
        ),
        (
            "finding-1-variable-expansion-dollar-sign",
            "$REVIEW_SUFFIX",
        ),
        (
            "finding-1-doubled-backslash-path",
            "double\\\\backslash",
        ),
        (
            "finding-1-apostrophe-single-quote",
            "O'Brien/owner's-handoff",
        ),
    ],
    ids=[
        "finding-1-command-substitution-dollar-parentheses",
        "finding-1-command-substitution-backticks",
        "finding-1-variable-expansion-dollar-sign",
        "finding-1-doubled-backslash-path",
        "finding-1-apostrophe-single-quote",
    ],
)
def test_printed_command_posix_quoting_round_trip(
    case_identifier: str,
    handoff_path_component: str,
) -> None:
    shell_executable = find_posix_shell_executable()
    if not shell_executable:
        pytest.skip("POSIX shell executable (sh or bash) not found on system")

    handoff_path = f"/home/user/.claude/handoffs/2026-10-14-{handoff_path_component}.md"
    collapsed_prompt, printed_command = format_printed_launch_command(
        chain_name="settle-and-cure",
        next_link=2,
        model="opus",
        handoff_path=handoff_path,
        receiving_shell="posix",
    )
    if "'" in collapsed_prompt:
        assert "'\\''" in printed_command

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        mock_binary_directory = temporary_root / "bin"
        mock_binary_directory.mkdir()

        invocation_log = temporary_root / "invoked_arguments.txt"

        mock_claude_script = mock_binary_directory / "claude"
        mock_claude_script.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$@" > "{invocation_log}"\n',
            encoding="utf-8",
        )
        mock_claude_script.chmod(0o755)

        environment = os.environ.copy()
        current_path = environment.get("PATH", "")
        environment["PATH"] = (
            f"{mock_binary_directory}{os.pathsep}{current_path}"
            if current_path
            else str(mock_binary_directory)
        )
        environment["REVIEW_SUFFIX"] = "INJECTED_ENV_VALUE"

        completed_process = subprocess.run(
            [shell_executable, "-c", printed_command],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed_process.returncode == 0, (
            f"Expected shell execution to succeed for {case_identifier}, but received returncode "
            f"{completed_process.returncode}.\n"
            f"Standard output:\n{completed_process.stdout}\n"
            f"Standard error:\n{completed_process.stderr}"
        )
        assert completed_process.stderr == "", (
            f"Expected empty standard error (no command substitution or injection) for {case_identifier}, "
            f"but received:\n{completed_process.stderr}"
        )
        assert invocation_log.is_file(), (
            f"Expected mock claude script to be invoked for {case_identifier}, but {invocation_log} was not created"
        )

        invoked_arguments = invocation_log.read_text(encoding="utf-8").splitlines()
        expected_arguments = [
            "-n",
            "settle-and-cure-2",
            "--model",
            "opus",
            collapsed_prompt,
        ]
        assert invoked_arguments == expected_arguments, (
            f"Argument mismatch for {case_identifier}.\n"
            f"Expected:\n{expected_arguments}\n"
            f"Received:\n{invoked_arguments}"
        )


CHAIN_REFERENCE_PATH = Path(__file__).resolve().parents[1] / "references" / "chain.md"
CHAIN_PLACEHOLDERS = {
    "<n+1>": "{next_link}",
    "<n+2>": "{future_link}",
    "<chain>": "{chain_name}",
    "<absolute handoff path>": "{handoff_path}",
}


def read_resume_prompt_template_from_reference() -> str:
    """Returns the fenced text block directly under the Resume prompt heading."""
    reference_text = CHAIN_REFERENCE_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^## Resume prompt[^\n]*\n.*?^```text\r?\n(.*?)^```",
        reference_text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "Resume prompt fenced block not found in chain.md"
    return match.group(1)


def test_resume_prompt_template_has_no_quote_characters() -> None:
    reference_text = CHAIN_REFERENCE_PATH.read_text(encoding="utf-8")
    reference_template = read_resume_prompt_template_from_reference()
    for forbidden_character in ('"', "'", "`"):
        assert forbidden_character not in reference_template, (
            f"chain.md resume prompt contains {forbidden_character!r}"
        )
    assert not reference_template.rstrip().endswith("\\")

    normalised_reference = " ".join(reference_template.split())
    for placeholder, replacement in CHAIN_PLACEHOLDERS.items():
        normalised_reference = normalised_reference.replace(placeholder, replacement)
    assert normalised_reference == " ".join(RESUME_PROMPT_TEMPLATE.split())

    assert "receiving shell" in reference_text
    assert "'\\''" in reference_text
    assert "''" in reference_text
    assert "nothing inside the prompt is escaped" not in reference_text

    for unsafe_cmd_fragment in (
        'quote"character',
        "%USERPROFILE%",
        "!DELAYED!",
        "trailing\\",
    ):
        with pytest.raises(ValueError):
            quote_cmd_argument(unsafe_cmd_fragment)


@pytest.mark.parametrize(
    ("receiving_shell", "handoff_path_component"),
    [
        ("powershell", "plain"),
        ("powershell", r"O'Brien\owner's-handoff"),
        ("powershell", r"double\\backslash"),
        (
            "powershell",
            "$(New-Item -ItemType File -Path CHAIN_INJECTION_MARKER)",
        ),
        ("powershell", "$HOME-$env:REVIEW_SUFFIX"),
        ("cmd", "plain"),
        ("cmd", r"O'Brien\owner's-handoff"),
        ("cmd", r"double\\backslash"),
        (
            "cmd",
            "$(New-Item -ItemType File -Path CHAIN_INJECTION_MARKER)",
        ),
        ("cmd", "$HOME-$env:REVIEW_SUFFIX"),
    ],
    ids=[
        "powershell-plain",
        "finding-2-powershell-apostrophe",
        "powershell-doubled-backslash",
        "finding-1-powershell-subexpression-injection",
        "finding-1-powershell-variable-expansion",
        "cmd-plain",
        "finding-2-cmd-apostrophe",
        "cmd-doubled-backslash",
        "cmd-subexpression-literal",
        "cmd-dollar-variable-literal",
    ],
)
def test_printed_command_windows_quoting_round_trip(
    receiving_shell: str,
    handoff_path_component: str,
) -> None:
    handoff_path = (
        rf"C:\Users\owner\.claude\handoffs\2026-10-14-{handoff_path_component}.md"
    )
    collapsed_prompt, printed_command = format_printed_launch_command(
        chain_name="settle-and-cure",
        next_link=2,
        model="opus",
        handoff_path=handoff_path,
        receiving_shell=receiving_shell,
    )

    if receiving_shell == "powershell":
        assert printed_command.endswith("'")
        if "'" in collapsed_prompt:
            assert "''" in printed_command
            assert "'\\''" not in printed_command
        powershell_executable = find_powershell_executable()
        if not powershell_executable:
            pytest.skip("PowerShell executable (pwsh) not found on system")
    else:
        assert printed_command.endswith(f'"{collapsed_prompt}"')
        command_interpreter = shutil.which("cmd.exe") if os.name == "nt" else None
        if not command_interpreter:
            pytest.skip("cmd.exe not available on this system")

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        mock_binary_directory = temporary_root / "bin"
        mock_binary_directory.mkdir()
        invocation_log = temporary_root / "invoked_arguments.txt"
        write_mock_claude_executable(mock_binary_directory, invocation_log)

        environment = os.environ.copy()
        environment["REVIEW_SUFFIX"] = "INJECTED_ENV_VALUE"

        if receiving_shell == "powershell":
            safe_directories = get_safe_child_path_directories(powershell_executable)
            environment["PATH"] = os.pathsep.join(
                [str(mock_binary_directory), *safe_directories]
            )
            completed_process = subprocess.run(
                [
                    powershell_executable,
                    "-NoProfile",
                    "-Command",
                    printed_command,
                ],
                cwd=temporary_root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            environment["PATH"] = (
                f"{mock_binary_directory}{os.pathsep}{environment.get('PATH', '')}"
            )
            completed_process = subprocess.run(
                f'"{command_interpreter}" /d /s /c "{printed_command}"',
                cwd=temporary_root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        assert completed_process.returncode == 0, (
            f"{receiving_shell} failed ({completed_process.returncode}):\n"
            f"Standard output:\n{completed_process.stdout}\n"
            f"Standard error:\n{completed_process.stderr}"
        )
        assert completed_process.stderr == ""
        assert not (temporary_root / "CHAIN_INJECTION_MARKER").exists(), (
            f"{receiving_shell} evaluated subexpression and created CHAIN_INJECTION_MARKER"
        )
        assert invocation_log.is_file(), (
            f"Expected mock claude executable to be invoked by {receiving_shell}"
        )
        invoked_arguments = invocation_log.read_text(encoding="utf-8").splitlines()
        assert invoked_arguments == [
            "-n",
            "settle-and-cure-2",
            "--model",
            "opus",
            collapsed_prompt,
        ]
