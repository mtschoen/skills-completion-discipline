import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock, patch


def load_runner_module():
    module_path = Path(__file__).parents[1] / "evals" / "run.py"
    specification = importlib.util.spec_from_file_location("eval_runner", module_path)
    module = importlib.util.module_from_spec(specification)
    assert specification.loader is not None
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


runner = load_runner_module()


class FakeWindowsPath:
    def __init__(self, value, available_files=frozenset()):
        self.path = PureWindowsPath(value)
        self.available_files = available_files

    def __truediv__(self, child):
        return FakeWindowsPath(self.path / child, self.available_files)

    def exists(self):
        return True

    def is_file(self):
        return self.path in self.available_files

    def as_posix(self):
        return self.path.as_posix()

    def __str__(self):
        return str(self.path)


class RunnerTests(unittest.TestCase):
    def test_loaders_and_prompt_variants(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            evals_path = root / "evals.json"
            evals_path.write_text('{"evals": [{"id": 1}]}', encoding="utf-8")
            scenario_directory = root / "scenario"
            scenario_directory.mkdir()
            (scenario_directory / "brief.md").write_text(
                "Inspect the repo.", encoding="utf-8"
            )

            self.assertEqual(runner.load_evals(evals_path), [{"id": 1}])
            self.assertEqual(runner.load_brief(scenario_directory), "Inspect the repo.")
            with_skill = runner.build_prompt(
                "Inspect the repo.", "with_skill", "skill body"
            )
            without_skill = runner.build_prompt(
                "Inspect the repo.", "without_skill", "skill body"
            )

        self.assertIn("skill body", with_skill)
        self.assertIn("Inspect the repo.", with_skill)
        self.assertNotIn("skill body", without_skill)

    def test_materialize_workspace_from_seed_replaces_existing_workspace(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scenario_directory = root / "scenario"
            seed_directory = scenario_directory / "seed"
            seed_directory.mkdir(parents=True)
            (seed_directory / "seed.txt").write_text("seed", encoding="utf-8")
            workspace_directory = root / "workspace"
            workspace_directory.mkdir()
            (workspace_directory / "old.txt").write_text("old", encoding="utf-8")

            runner.materialize_workspace(scenario_directory, workspace_directory)

            self.assertEqual((workspace_directory / "seed.txt").read_text(), "seed")
            self.assertFalse((workspace_directory / "old.txt").exists())

    def test_materialize_workspace_without_seed_creates_empty_workspace(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scenario_directory = root / "scenario"
            scenario_directory.mkdir()
            workspace_directory = root / "workspace"

            runner.materialize_workspace(scenario_directory, workspace_directory)

            self.assertTrue(workspace_directory.is_dir())
            self.assertEqual(list(workspace_directory.iterdir()), [])

    def test_run_scenario_script_handles_missing_success_failure_and_timeout(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scenario_directory = root / "scenario with spaces"
            run_directory = root / "run with spaces"
            scenario_directory.mkdir()
            run_directory.mkdir()

            with (
                patch.object(runner, "_find_bash_executable", create=True) as find_bash,
                patch.object(runner.subprocess, "run") as run_process,
            ):
                self.assertEqual(
                    runner.run_scenario_script(
                        scenario_directory, run_directory, "missing.sh"
                    ),
                    (True, ""),
                )
            find_bash.assert_not_called()
            run_process.assert_not_called()

            script = scenario_directory / "setup.sh"
            script.write_text("printf 'ready'\n", encoding="utf-8")
            self.assertEqual(
                runner.run_scenario_script(
                    scenario_directory, run_directory, "setup.sh"
                ),
                (True, "ready"),
            )

            failed_process = Mock(returncode=7, stdout="", stderr="broken")
            with patch.object(runner.subprocess, "run", return_value=failed_process):
                successful, output = runner.run_scenario_script(
                    scenario_directory, run_directory, "setup.sh"
                )
            self.assertFalse(successful)
            self.assertIn("exit 7: broken", output)

            with patch.object(
                runner.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["bash"], 5),
            ):
                successful, output = runner.run_scenario_script(
                    scenario_directory, run_directory, "setup.sh", timeout=5
                )
            self.assertFalse(successful)
            self.assertEqual(output, "setup.sh timeout after 5s")

    def test_run_scenario_script_prefers_native_git_bash_and_forward_slashes(self):
        program_files = PureWindowsPath(r"C:\Program Files")
        native_bin = program_files / "Git/bin/bash.exe"
        native_usr = program_files / "Git/usr/bin/bash.exe"
        scenario_directory = FakeWindowsPath(r"C:\work\scenario with spaces")

        for script_name in ("setup.sh", "probe.sh"):
            with self.subTest(script_name=script_name):
                with (
                    patch.object(
                        runner,
                        "os",
                        SimpleNamespace(
                            name="nt",
                            environ={"ProgramFiles": str(program_files)},
                        ),
                    ),
                    patch.object(
                        runner,
                        "Path",
                        lambda root: FakeWindowsPath(root, {native_bin, native_usr}),
                    ),
                    patch.object(
                        runner.shutil,
                        "which",
                        return_value=(
                            r"C:\Users\test\AppData\Local\Microsoft"
                            r"\WindowsApps\bash.EXE"
                        ),
                    ),
                    patch.object(
                        runner.subprocess,
                        "run",
                        return_value=Mock(returncode=0, stdout="ready", stderr=""),
                    ) as run_process,
                ):
                    self.assertEqual(
                        runner.run_scenario_script(
                            scenario_directory,
                            PureWindowsPath(r"C:\work\run"),
                            script_name,
                        ),
                        (True, "ready"),
                    )

                self.assertEqual(
                    run_process.call_args.args[0],
                    [
                        r"C:\Program Files\Git\bin\bash.exe",
                        f"C:/work/scenario with spaces/{script_name}",
                    ],
                )

    def test_run_scenario_script_shell_selection_fallbacks(self):
        program_files = PureWindowsPath(r"C:\Program Files")
        native_bin = program_files / "Git/bin/bash.exe"
        native_usr = program_files / "Git/usr/bin/bash.exe"
        path_bash = r"C:\Users\test\AppData\Local\Microsoft\WindowsApps\bash.EXE"
        cases = [
            (
                "second native candidate",
                "nt",
                {"ProgramFiles": str(program_files)},
                {native_usr},
                path_bash,
                r"C:\Program Files\Git\usr\bin\bash.exe",
            ),
            (
                "PATH without native candidates",
                "nt",
                {"ProgramFiles": str(program_files)},
                set(),
                path_bash,
                path_bash,
            ),
            (
                "PATH without ProgramFiles",
                "nt",
                {},
                {native_bin},
                path_bash,
                path_bash,
            ),
            (
                "PATH on non-Windows",
                "posix",
                {"ProgramFiles": str(program_files)},
                {native_bin, native_usr},
                path_bash,
                path_bash,
            ),
            (
                "literal bash when PATH lookup misses",
                "nt",
                {},
                set(),
                None,
                "bash",
            ),
        ]

        for name, os_name, environment, available, path_result, expected in cases:
            with self.subTest(name=name):
                with (
                    patch.object(
                        runner,
                        "os",
                        SimpleNamespace(name=os_name, environ=environment),
                    ),
                    patch.object(
                        runner,
                        "Path",
                        lambda root, available=available: FakeWindowsPath(
                            root, available
                        ),
                    ),
                    patch.object(runner.shutil, "which", return_value=path_result),
                    patch.object(
                        runner.subprocess,
                        "run",
                        return_value=Mock(returncode=0, stdout="ready", stderr=""),
                    ) as run_process,
                ):
                    self.assertEqual(
                        runner.run_scenario_script(
                            FakeWindowsPath(r"C:\scenario"),
                            PureWindowsPath(r"C:\run"),
                            "setup.sh",
                        ),
                        (True, "ready"),
                    )

                self.assertEqual(
                    run_process.call_args.args[0],
                    [expected, "C:/scenario/setup.sh"],
                )

    def test_invoke_agent_success_builds_command_environment_and_timing(self):
        process = Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "result": "  response text  ",
                    "usage": {"input_tokens": 4, "output_tokens": 6},
                    "duration_ms": 123,
                    "total_cost_usd": 0.25,
                    "stop_reason": "end_turn",
                    "num_turns": 2,
                }
            ),
            stderr="",
        )
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.dict(os.environ, {"CLAUDECODE": "nested", "KEPT": "yes"}, clear=True),
            patch.object(runner.subprocess, "run", return_value=process) as run_process,
            patch.object(runner.time, "time", side_effect=[10.0, 11.5]),
        ):
            response, timing = runner.invoke_agent(
                "prompt", Path(temporary_directory), "test-model", 30
            )

        self.assertEqual(response, "response text")
        self.assertEqual(timing["total_tokens"], 10)
        self.assertEqual(timing["duration_ms"], 123)
        self.assertEqual(timing["total_duration_seconds"], 1.5)
        command = run_process.call_args.args[0]
        self.assertEqual(command[-2:], ["--model", "test-model"])
        self.assertNotIn("CLAUDECODE", run_process.call_args.kwargs["env"])
        self.assertEqual(run_process.call_args.kwargs["env"]["KEPT"], "yes")

    def test_invoke_agent_uses_elapsed_duration_when_wrapper_omits_fields(self):
        process = Mock(returncode=0, stdout='{"result": null}', stderr="")
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(runner.subprocess, "run", return_value=process) as run_process,
            patch.object(runner.time, "time", side_effect=[2.0, 2.75]),
        ):
            response, timing = runner.invoke_agent(
                "prompt", Path(temporary_directory), None, 10
            )

        self.assertEqual(response, "")
        self.assertEqual(timing["total_tokens"], 0)
        self.assertEqual(timing["duration_ms"], 750)
        self.assertNotIn("--model", run_process.call_args.args[0])

    def test_invoke_agent_reports_timeout_nonzero_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            with patch.object(
                runner.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["claude"], 9),
            ):
                self.assertEqual(
                    runner.invoke_agent("prompt", workspace, None, 9),
                    ("", {"_error": "agent timeout after 9s"}),
                )

            with patch.object(
                runner.subprocess,
                "run",
                return_value=Mock(returncode=3, stderr="failure", stdout=""),
            ):
                response, timing = runner.invoke_agent("prompt", workspace, None, 9)
            self.assertEqual(response, "")
            self.assertIn("agent exit 3: failure", timing["_error"])

            with patch.object(
                runner.subprocess,
                "run",
                return_value=Mock(returncode=0, stderr="", stdout="not-json"),
            ):
                response, timing = runner.invoke_agent("prompt", workspace, None, 9)
            self.assertEqual(response, "")
            self.assertIn("agent stdout not JSON", timing["_error"])

    def test_write_run_and_eval_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_directory = Path(temporary_directory) / "run"
            runner.write_run(run_directory, "answer", {"duration": 1})
            runner.write_eval_metadata(run_directory, {"id": 4, "name": "case"})

            self.assertEqual(
                (run_directory / "outputs" / "response.md").read_text(), "answer"
            )
            self.assertEqual(
                json.loads((run_directory / "timing.json").read_text()), {"duration": 1}
            )
            self.assertEqual(
                json.loads((run_directory / "eval_metadata.json").read_text())["id"], 4
            )

    def test_run_single_reports_workspace_and_setup_failures(self):
        eval_entry = {"scenario_dir": "scenarios/example"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            run_directory = root / "run"
            scenarios_root = root / "scenarios"
            with patch.object(
                runner,
                "materialize_workspace",
                side_effect=FileNotFoundError("missing seed"),
            ):
                outcome = runner.run_single(
                    eval_entry,
                    "with_skill",
                    run_directory,
                    scenarios_root,
                    "skill",
                    None,
                    5,
                )
            self.assertEqual(outcome["status"], "error")
            self.assertIn("missing seed", outcome["error"])

            with (
                patch.object(runner, "materialize_workspace"),
                patch.object(
                    runner, "run_scenario_script", return_value=(False, "setup broke")
                ),
            ):
                outcome = runner.run_single(
                    eval_entry,
                    "with_skill",
                    run_directory,
                    scenarios_root,
                    "skill",
                    None,
                    5,
                )
            self.assertEqual(outcome, {"status": "error", "error": "setup broke"})

    def test_run_single_writes_probe_and_returns_agent_outcomes(self):
        eval_entry = {"scenario_dir": "scenarios/example"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scenario_directory = root / "scenarios" / "example"
            scenario_directory.mkdir(parents=True)
            (scenario_directory / "brief.md").write_text("brief", encoding="utf-8")
            scenarios_root = root / "scenarios"

            error_run = root / "error-run"
            with (
                patch.object(
                    runner,
                    "run_scenario_script",
                    side_effect=[(True, ""), (False, "probe broke")],
                ),
                patch.object(
                    runner,
                    "invoke_agent",
                    return_value=("", {"_error": "agent broke"}),
                ),
            ):
                outcome = runner.run_single(
                    eval_entry,
                    "with_skill",
                    error_run,
                    scenarios_root,
                    "skill",
                    None,
                    5,
                )
            self.assertEqual(outcome, {"status": "error", "error": "agent broke"})
            self.assertEqual(
                (error_run / "outputs" / "post-state.txt").read_text(),
                "(probe failed) probe broke",
            )

            successful_run = root / "successful-run"
            with (
                patch.object(
                    runner,
                    "run_scenario_script",
                    side_effect=[(True, ""), (True, "state=yes")],
                ),
                patch.object(
                    runner,
                    "invoke_agent",
                    return_value=("answer", {"total_duration_seconds": 2.5}),
                ),
            ):
                outcome = runner.run_single(
                    eval_entry,
                    "without_skill",
                    successful_run,
                    scenarios_root,
                    "skill",
                    None,
                    5,
                )
            self.assertEqual(outcome, {"status": "ok", "duration": 2.5})
            self.assertEqual(
                (successful_run / "outputs" / "post-state.txt").read_text(), "state=yes"
            )

    def test_main_dry_run_filters_evals_and_lists_work(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            evals_path = root / "evals.json"
            evals_path.write_text(
                json.dumps(
                    {
                        "evals": [
                            {
                                "id": 1,
                                "name": "first",
                                "scenario_dir": "scenarios/first",
                            },
                            {
                                "id": 2,
                                "name": "second",
                                "scenario_dir": "scenarios/second",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            skill_path = root / "SKILL.md"
            skill_path.write_text("skill", encoding="utf-8")
            output_directory = root / "output"
            arguments = [
                "run.py",
                "--evals",
                str(evals_path),
                "--skill-md",
                str(skill_path),
                "--output-dir",
                str(output_directory),
                "--runs-per-config",
                "2",
                "--configs",
                "with_skill",
                "--only-eval",
                "2",
                "--dry-run",
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch("sys.stderr") as standard_error,
            ):
                runner.main()

            rendered = "".join(
                call.args[0] for call in standard_error.write.call_args_list
            )
            self.assertIn("Discovered 2 work units", rendered)
            self.assertIn("second / with_skill / run-2", rendered)
            self.assertNotIn("first /", rendered)

    def test_main_runs_work_and_reports_worker_exceptions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            evals_path = root / "evals.json"
            evals_path.write_text(
                json.dumps(
                    {
                        "evals": [
                            {
                                "id": 1,
                                "name": "example",
                                "scenario_dir": "scenarios/example",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            skill_path = root / "SKILL.md"
            skill_path.write_text("skill", encoding="utf-8")
            arguments = [
                "run.py",
                "--evals",
                str(evals_path),
                "--skill-md",
                str(skill_path),
                "--output-dir",
                str(root / "output"),
                "--runs-per-config",
                "1",
                "--configs",
                "with_skill",
                "--parallel",
                "1",
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch.object(
                    runner, "run_single", side_effect=RuntimeError("worker broke")
                ),
                patch("sys.stderr") as standard_error,
            ):
                runner.main()

            rendered = "".join(
                call.args[0] for call in standard_error.write.call_args_list
            )
            self.assertIn("[ERROR] example/with_skill/run-1", rendered)
            self.assertIn("_do raised: worker broke", rendered)
            self.assertIn("Done.", rendered)


if __name__ == "__main__":
    unittest.main()
