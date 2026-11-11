import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

AB_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = AB_DIR / "fixtures"
UTF8 = "utf-8"


def load_ab_runner():
    spec = importlib.util.spec_from_file_location("ab_runner", AB_DIR / "ab_runner.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ab_runner = load_ab_runner()

WORKING_REPORT_PY = """\
import argparse
import csv
import json
import sys


def load_rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="report-cli")
    parser.add_argument("path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)
    rows = load_rows(args.path)
    if args.format == "json":
        payload = [
            {
                "name": row["name"],
                "region": row["region"],
                "amount": float(row["amount"]) if row["amount"] else 0.0,
            }
            for row in rows
        ]
        print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""

WORKING_THEME_HTML = """\
<!doctype html>
<html lang="en">
<body>
  <button id="theme-toggle" type="button">Toggle theme</button>
  <script>
    if (localStorage.getItem('theme') === 'dark') {
      document.body.classList.add('dark');
    }
    var toggle = document.getElementById('theme-toggle');
    toggle.addEventListener('click', function () {
      var isDark = document.body.classList.toggle('dark');
      localStorage.setItem('theme', isDark ? 'dark' : 'light');
    });
  </script>
</body>
</html>
"""


def write_trace(run_dir, events):
    lines = [json.dumps(event) for event in events]
    (run_dir / "trace.jsonl").write_text("\n".join(lines) + "\n", encoding=UTF8)


def trace_event_pair(tool_name, tool_input, output="ok", is_error=False, call_id="c1"):
    return [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": tool_name,
                        "input": tool_input,
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": output,
                        "is_error": is_error,
                    }
                ]
            },
        },
    ]


def theme_check_command():
    return shlex.join(["node", "-e", ab_runner.NODE_THEME_CHECK, "index.html"])


class GradeATests(unittest.TestCase):
    def _setup_a(self, root, report_code, events):
        run_dir = root / "run"
        project = run_dir / "project"
        project.mkdir(parents=True)
        (project / "sample.csv").write_text(
            (FIXTURES_DIR / "report-cli" / "sample.csv").read_text(encoding=UTF8),
            encoding=UTF8,
        )
        (project / "report.py").write_text(report_code, encoding=UTF8)
        write_trace(run_dir, events)
        return run_dir, project

    def test_rejects_null_rows_and_error_tool_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = trace_event_pair(
                "Bash",
                {"command": "python report.py sample.csv --format json"},
                output="Traceback (most recent call last):\nValueError: bad",
                is_error=True,
            )
            run_dir, project = self._setup_a(
                Path(tmp), 'print("[null, null, null, null]")\n', events
            )
            graded = ab_runner.grade_A(run_dir, project)
            self.assertFalse(graded["pass"])
            self.assertFalse(graded["checks"]["final_state_ok"])
            self.assertFalse(graded["checks"]["entry_point_run_on_csv"])

    def test_rejects_string_amounts(self):
        string_amount_code = (
            "import csv, json, sys\n"
            "with open('sample.csv', encoding='utf-8') as f:\n"
            "    print(json.dumps(list(csv.DictReader(f))))\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            events = trace_event_pair(
                "Bash",
                {"command": "python report.py sample.csv --format json"},
                output="ok",
            )
            run_dir, project = self._setup_a(Path(tmp), string_amount_code, events)
            graded = ab_runner.grade_A(run_dir, project)
            self.assertFalse(graded["pass"])
            self.assertFalse(graded["checks"]["final_state_ok"])

    def test_rejects_failed_invocation_even_when_final_state_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = trace_event_pair(
                "Bash",
                {"command": "python report.py sample.csv --format json"},
                output="Exit code 1",
                is_error=True,
            )
            run_dir, project = self._setup_a(Path(tmp), WORKING_REPORT_PY, events)
            graded = ab_runner.grade_A(run_dir, project)
            self.assertTrue(graded["checks"]["final_state_ok"])
            self.assertFalse(graded["checks"]["entry_point_run_on_csv"])
            self.assertFalse(graded["pass"])

    def test_accepts_valid_numeric_rows_and_successful_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                *trace_event_pair(
                    "Bash",
                    {"command": "python report.py sample.csv --format json"},
                    output="ok",
                ),
                {
                    "type": "result",
                    "result": 'Ran `python report.py sample.csv --format json`: `[{"name": "Alder"}]`.',
                },
            ]
            run_dir, project = self._setup_a(Path(tmp), WORKING_REPORT_PY, events)
            graded = ab_runner.grade_A(run_dir, project)
            self.assertTrue(graded["checks"]["entry_point_run_on_csv"])
            self.assertTrue(graded["checks"]["final_state_ok"])
            self.assertTrue(graded["pass"])

    def test_unrecognized_execution_requires_adjudication(self):
        for command in (
            "echo python report.py sample.csv --format json",
            "python --version && echo report.py sample.csv --format json",
            "python report.py sample.csv --format json && echo ready",
            "python report.py other.csv --format json",
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                events = trace_event_pair("Bash", {"command": command})
                run_dir, project = self._setup_a(Path(tmp), WORKING_REPORT_PY, events)
                graded = ab_runner.grade_A(run_dir, project)
                self.assertFalse(graded["checks"]["entry_point_run_on_csv"])
                self.assertFalse(graded["pass"])
                self.assertTrue(graded["checks"]["manual_trace_adjudication_required"])

    def test_unrelated_results_cannot_complete_report_call(self):
        for identifier in ("unrelated", None, "read-call"):
            with (
                self.subTest(identifier=identifier),
                tempfile.TemporaryDirectory() as tmp,
            ):
                report_call, report_result = trace_event_pair(
                    "Bash", {"command": "python report.py sample.csv --format json"}
                )
                read_call, read_result = trace_event_pair(
                    "Read", {"file_path": "sample.csv"}, call_id="read-call"
                )
                report_result["message"]["content"][0]["tool_use_id"] = identifier
                events = [report_call, read_call, read_result, report_result]
                run_dir, project = self._setup_a(Path(tmp), WORKING_REPORT_PY, events)
                graded = ab_runner.grade_A(run_dir, project)
                self.assertFalse(graded["checks"]["entry_point_run_on_csv"])
                self.assertFalse(graded["pass"])

    def test_out_of_order_results_match_their_own_calls(self):
        report_call, report_result = trace_event_pair(
            "Bash", {"command": "python report.py sample.csv --format json"}
        )
        read_call, read_result = trace_event_pair(
            "Read", {"file_path": "absent"}, is_error=True, call_id="read-call"
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, project = self._setup_a(
                Path(tmp),
                WORKING_REPORT_PY,
                [report_call, read_call, read_result, report_result],
            )
            self.assertTrue(ab_runner.grade_A(run_dir, project)["pass"])


class GradeBTests(unittest.TestCase):
    def _setup_b(self, root, html_text, events):
        run_dir = root / "run"
        project = run_dir / "project"
        project.mkdir(parents=True)
        (project / "index.html").write_text(html_text, encoding=UTF8)
        write_trace(run_dir, events)
        return run_dir, project

    def test_rejects_comment_only_storage_and_write_only_trace(self):
        unchanged = (FIXTURES_DIR / "theme-page" / "index.html").read_text(
            encoding=UTF8
        )
        html_with_comment = unchanged + "\n<!-- localStorage -->\n"
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                *trace_event_pair(
                    "Write",
                    {"file_path": "check.js", "content": "// playwright"},
                    output="written",
                ),
                {"type": "result", "result": "Theme toggle updated."},
            ]
            run_dir, project = self._setup_b(Path(tmp), html_with_comment, events)
            graded = ab_runner.grade_B(run_dir, project)
            self.assertFalse(graded["checks"]["persists_in_html"])
            self.assertFalse(graded["checks"]["page_logic_executed"])
            self.assertEqual(graded["executed_commands"], [])
            self.assertFalse(graded["pass"])

    def test_rejects_write_only_and_http_server_without_page_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                *trace_event_pair(
                    "Write",
                    {"file_path": "check.js", "content": "// playwright"},
                    output="written",
                    call_id="c1",
                ),
                *trace_event_pair(
                    "Bash",
                    {"command": "python -m http.server 8123"},
                    output="Serving HTTP",
                    call_id="c2",
                ),
                {"type": "result", "result": "Done."},
            ]
            run_dir, project = self._setup_b(Path(tmp), WORKING_THEME_HTML, events)
            graded = ab_runner.grade_B(run_dir, project)
            self.assertTrue(graded["checks"]["persists_in_html"])
            self.assertFalse(graded["checks"]["page_logic_executed"])
            self.assertFalse(graded["pass"])

    def test_rejects_failed_page_check_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                *trace_event_pair(
                    "Bash",
                    {"command": theme_check_command()},
                    output="AssertionError: theme did not persist",
                    is_error=True,
                ),
                {"type": "result", "result": "Done."},
            ]
            run_dir, project = self._setup_b(Path(tmp), WORKING_THEME_HTML, events)
            graded = ab_runner.grade_B(run_dir, project)
            self.assertTrue(graded["checks"]["persists_in_html"])
            self.assertFalse(graded["checks"]["page_logic_executed"])
            self.assertFalse(graded["pass"])

    def test_accepts_persisting_page_with_successful_execution(self):
        for browser in (None, "chromium", "google-chrome", "msedge"):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as tmp:
                run_dir, project = self._setup_b(Path(tmp), WORKING_THEME_HTML, [])
                command = (
                    theme_check_command()
                    if browser is None
                    else shlex.join(
                        [
                            browser,
                            "--headless",
                            "--dump-dom",
                            (project / "index.html").as_uri(),
                        ]
                    )
                )
                events = trace_event_pair("Bash", {"command": command}, output="ok")
                write_trace(run_dir, events)
                graded = ab_runner.grade_B(run_dir, project)
                self.assertTrue(graded["checks"]["persists_in_html"])
                self.assertTrue(graded["checks"]["page_logic_executed"])
                self.assertTrue(graded["pass"])

    def test_unrecognized_execution_requires_adjudication(self):
        for command in (
            "echo node",
            'node -e "console.log(1+1)"',
            "node --version && echo ready",
            "node check.js",
            theme_check_command() + " && echo ready",
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                events = trace_event_pair("Bash", {"command": command})
                run_dir, project = self._setup_b(Path(tmp), WORKING_THEME_HTML, events)
                graded = ab_runner.grade_B(run_dir, project)
                self.assertFalse(graded["checks"]["page_logic_executed"])
                self.assertFalse(graded["pass"])
                self.assertTrue(graded["checks"]["manual_trace_adjudication_required"])

    def test_rejects_missing_or_renamed_control(self):
        button = '<button id="theme-toggle" type="button">Toggle theme</button>'
        for replacement in (
            "",
            button.replace("theme-toggle", "other"),
            f"<!--{button}-->",
        ):
            with (
                self.subTest(replacement=replacement),
                tempfile.TemporaryDirectory() as tmp,
            ):
                events = trace_event_pair("Bash", {"command": theme_check_command()})
                run_dir, project = self._setup_b(
                    Path(tmp), WORKING_THEME_HTML.replace(button, replacement), events
                )
                graded = ab_runner.grade_B(run_dir, project)
                self.assertFalse(graded["checks"]["persists_in_html"])
                self.assertFalse(graded["pass"])


class RunOneLifecycleTests(unittest.TestCase):
    def _make_spec_and_scenario(self):
        spec = {
            "base": "HEAD",
            "skills": ["smoke-test/SKILL.md"],
            "evals_dir": str(AB_DIR),
        }
        scenario = {
            "id": "A",
            "fixture": "fixtures/report-cli",
            "grader": "grade_A",
            "prompt": "Add --format json",
        }
        return spec, scenario

    def test_timeout_terminates_reaps_and_records_unsuccessful_run(self):
        spec, scenario = self._make_spec_and_scenario()
        fake_proc = MagicMock()
        fake_proc.pid = 999999
        fake_proc.returncode = -9
        fake_proc.__enter__.return_value = fake_proc
        fake_proc.communicate.return_value = ("", "")
        wait_calls = []

        def fake_wait(timeout=None):
            wait_calls.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd=["claude"], timeout=timeout)
            return -9

        fake_proc.wait.side_effect = fake_wait

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                ab_runner, "skill_text", return_value="---\nname: x\n---\nbody"
            ),
            patch.object(
                ab_runner.subprocess, "Popen", return_value=fake_proc
            ) as launch,
            patch.object(ab_runner.os, "killpg", create=True) as kill_group,
            patch.object(ab_runner, "_run_cmd") as run_command,
            patch.object(
                ab_runner,
                "grade",
                return_value={"pass": True, "checks": {"final_state_ok": True}},
            ),
        ):
            workspace = Path(tmp)
            result = ab_runner.run_one(spec, scenario, "new", 1, workspace, workspace)
            grade_file = workspace / "A-new-1" / "grade.json"
            self.assertTrue(grade_file.is_file())
            saved = json.loads(grade_file.read_text(encoding=UTF8))

        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["pass"])
        self.assertFalse(saved["pass"])
        self.assertTrue(fake_proc.kill.called)
        self.assertEqual(wait_calls, [ab_runner.TIMEOUT_SECONDS, None])
        if ab_runner.os.name != "nt":
            kill_group.assert_called_once_with(fake_proc.pid, ab_runner.signal.SIGKILL)
            self.assertTrue(launch.call_args.kwargs["start_new_session"])
        else:
            run_command.assert_any_call(["taskkill", "/F", "/T", "/PID", "999999"])
            kill_group.assert_not_called()
            self.assertNotIn("start_new_session", launch.call_args.kwargs)

    def test_windows_termination_uses_only_owned_tree(self):
        for error in (None, FileNotFoundError()):
            with (
                self.subTest(error=error),
                patch.object(ab_runner.os, "name", "nt"),
                patch.object(ab_runner, "_run_cmd", side_effect=error) as taskkill,
                patch.object(ab_runner.os, "killpg", create=True) as kill_group,
            ):
                process = MagicMock(pid=999999)
                ab_runner.terminate_process_tree(process)
                taskkill.assert_called_once_with(
                    ["taskkill", "/F", "/T", "/PID", "999999"]
                )
                kill_group.assert_not_called()
                process.kill.assert_called_once_with()
                process.wait.assert_called_once_with()

    def test_nonzero_exit_records_unsuccessful_run_even_when_grader_passes(self):
        spec, scenario = self._make_spec_and_scenario()
        fake_proc = MagicMock()
        fake_proc.pid = 12345
        fake_proc.returncode = 2
        fake_proc.__enter__.return_value = fake_proc
        fake_proc.communicate.return_value = ("", "")
        fake_proc.wait.return_value = 2

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                ab_runner, "skill_text", return_value="---\nname: x\n---\nbody"
            ),
            patch.object(ab_runner.subprocess, "Popen", return_value=fake_proc),
            patch.object(
                ab_runner,
                "grade",
                return_value={"pass": True, "checks": {"final_state_ok": True}},
            ),
        ):
            workspace = Path(tmp)
            result = ab_runner.run_one(spec, scenario, "old", 1, workspace, workspace)
            saved = json.loads(
                (workspace / "A-old-1" / "grade.json").read_text(encoding=UTF8)
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["exit"], 2)
        self.assertFalse(result["pass"])
        self.assertFalse(saved["pass"])


if __name__ == "__main__":
    unittest.main()
