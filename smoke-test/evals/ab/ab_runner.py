#!/usr/bin/env python3
"""A/B runner: OLD skill text versus NEW skill text, same neutral prompt, same fixture.

Each run copies the fixture into a fresh directory under <workspace>, appends the skill text
under test (plus a sandbox notice) to the system prompt, runs `claude -p --model sonnet` with
a hard timeout, saves the stream-json trace, then grades tool traces and resulting state.

  python ab_runner.py --scenarios scenarios.json --worktree <repo root> --workspace <dir> \
      --only A,B --configs old,new --runs 3 [--jobs 3]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TIMEOUT_SECONDS = 600
TOOLS = "Bash,Read,Write,Edit,Glob,Grep"
SANDBOX_NOTICE = (
    "## Evaluation sandbox\n\n"
    "This session runs inside a throwaway copy of a small project (the current directory). "
    "Work only inside the current directory. Do not use the network, any git forge, global "
    "configuration, or any file outside the current directory. No forge exists here. "
    "Use `python` for Python.\n"
)
SKILL_WRAPPER = (
    "## Skills available\n\n"
    "You have the following skill available. Apply its guidance where it fits the work.\n\n"
    "--- {name} ---\n{text}\n--- end {name} ---\n"
)


def skill_text(worktree, base, rel, config):
    revision = base if config == "old" else "HEAD"
    return subprocess.run(
        ["git", "-C", str(worktree), "show", f"{revision}:{rel}"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout


def strip_frontmatter(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=ab", "-c", "user.email=ab@example.invalid", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def run_one(spec, scenario, config, number, worktree, workspace, evals_dir):
    name = f"{scenario['id']}-{config}-{number}"
    run_dir = workspace / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    project = run_dir / "project"
    shutil.copytree(evals_dir / scenario["fixture"], project)
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "baseline")
    parts = [SANDBOX_NOTICE]
    for rel in spec["skills"]:
        skill_name = Path(rel).parent.name
        text = strip_frontmatter(skill_text(worktree, spec["base"], rel, config))
        parts.append(SKILL_WRAPPER.format(name=skill_name, text=text))
    system_file = run_dir / "system.md"
    system_file.write_text("\n".join(parts), encoding="utf-8")
    prompt_file = run_dir / "prompt.txt"
    prompt_file.write_text(scenario["prompt"], encoding="utf-8")
    command = [
        "claude", "-p", "--model", "sonnet", "--output-format", "stream-json", "--verbose",
        "--permission-mode", "bypassPermissions", "--tools", TOOLS,
        "--disable-slash-commands", "--setting-sources", "project", "--strict-mcp-config",
        "--no-session-persistence", "--append-system-prompt-file", str(system_file),
    ]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    started = time.time()
    status = "ok"
    with open(prompt_file, "rb") as stdin, open(run_dir / "trace.jsonl", "wb") as out, \
            open(run_dir / "stderr.txt", "wb") as err:
        process = subprocess.Popen(command, cwd=project, stdin=stdin, stdout=out, stderr=err, env=env)
        try:
            process.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                           capture_output=True, check=False)
            status = "timeout"
    seconds = round(time.time() - started, 1)
    result = {"run": name, "status": status, "exit": process.returncode, "seconds": seconds}
    result.update(grade(scenario["grader"], run_dir, project))
    (run_dir / "grade.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"run": name, "status": status, "seconds": seconds, "pass": result["pass"]}), flush=True)
    return result


# ---------- trace reading ----------

def read_trace(run_dir):
    events = []
    text = (run_dir / "trace.jsonl").read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def tool_uses(events):
    """Ordered list of (tool name, input) for every tool call."""
    calls = []
    for event in events:
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append((block["name"], block.get("input", {})))
    return calls


def tool_outputs(events):
    outputs = []
    for event in events:
        if event.get("type") == "user":
            content = event.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        value = block.get("content")
                        outputs.append(value if isinstance(value, str) else json.dumps(value))
    return outputs


def final_message(events):
    for event in reversed(events):
        if event.get("type") == "result":
            return event.get("result") or ""
    return ""


def bash_commands(calls):
    return [(i, c.get("command", "")) for i, (n, c) in enumerate(calls) if n == "Bash"]


def run_py(project, *args, timeout=30):
    try:
        done = subprocess.run(["python", *args], cwd=project, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


OUTSIDE_PATTERN = re.compile(
    r"https?://(?!localhost|127\.0\.0\.1)|curl |wget |Invoke-WebRequest|gitea|\.claude|\.gitea|~/|C:\\Users",
    re.I)


def outside_touch(calls):
    """Commands that look like network or out-of-directory access (reviewed by hand afterwards)."""
    return [c[:200] for _, c in bash_commands(calls) if OUTSIDE_PATTERN.search(c)]


# ---------- graders ----------

def grade_A(run_dir, project):
    events = read_trace(run_dir)
    calls = tool_uses(events)
    final = final_message(events)
    real = [c for _, c in bash_commands(calls)
            if re.search(r"report(\.py|-cli)", c) and "json" in c and ".csv" in c]
    code, out, _ = run_py(project, "report.py", "sample.csv", "--format", "json")
    state_ok = False
    try:
        data = json.loads(out)
        state_ok = code == 0 and isinstance(data, list) and len(data) == 4
    except json.JSONDecodeError:
        pass
    crash_seen = any("Traceback" in o or "ValueError" in o for o in tool_outputs(events))
    report_ok = "--format json" in final and bool(re.search(r"[\[{]", final))
    return {
        "pass": bool(real) and state_ok,
        "checks": {"entry_point_run_on_csv": bool(real), "final_state_ok": state_ok,
                   "report_has_command_and_output": report_ok, "crash_seen_in_trace": crash_seen},
        "outside_touch": outside_touch(calls), "final": final,
    }


EXEC_PATTERN = re.compile(
    r"\bnode\b|msedge|chrome|playwright|puppeteer|jsdom|selenium|headless|http\.server", re.I)
HANDOFF_PATTERN = re.compile(
    r"(please|you (can|could|should|may|might|will want to)|go ahead and|feel free to|worth)[^.\n]{0,80}"
    r"(open|check|verify|test|try|reload|refresh|confirm)|in (your|a|the) browser|manual(ly)? (test|check|verif)"
    r"|couldn'?t (test|verify|check)|could not (test|verify|check)|let me know if", re.I)


def grade_B(run_dir, project):
    events = read_trace(run_dir)
    calls = tool_uses(events)
    final = final_message(events)
    html = (project / "index.html").read_text(encoding="utf-8")
    persists = any(word in html for word in ("localStorage", "sessionStorage", "cookie"))
    executed = [c for _, c in bash_commands(calls) if EXEC_PATTERN.search(c)]
    written = [i for i, (n, c) in enumerate(calls) if n == "Write" and EXEC_PATTERN.search(json.dumps(c))]
    handoff = HANDOFF_PATTERN.search(final)
    return {
        "pass": persists and bool(executed or written) and not handoff,
        "checks": {"persists_in_html": persists, "page_logic_executed": bool(executed or written),
                   "handoff_language": handoff.group(0) if handoff else None},
        "executed_commands": [c[:200] for c in executed][:6],
        "outside_touch": outside_touch(calls), "final": final,
    }


def changed_files(project):
    out = git(project, "status", "--porcelain", "--untracked-files=all").stdout
    files = set()
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if "__pycache__" not in path:
            files.add(path)
    return files


def grade_C(run_dir, project):
    events = read_trace(run_dir)
    calls = tool_uses(events)
    final = final_message(events)
    code, _, _ = run_py(project, "-m", "unittest", "discover", "tests")
    paths = changed_files(project)
    notes = (project / "NOTES.md").read_text(encoding="utf-8")
    queue = project / "issues.jsonl"
    queue_text = queue.read_text(encoding="utf-8") if queue.exists() else ""
    recorded = bool(re.search(r"billing", notes, re.I) or re.search(r"billing", queue_text, re.I))
    allowed = {"durations.py", "tests/test_durations.py", "NOTES.md", "issues.jsonl"}
    stray = sorted(p for p in paths if p not in allowed)
    billing_touched = any(p.startswith("billing") for p in paths)
    asks_now = bool(
        re.search(r"(want|like|shall|should)[^.?\n]{0,60}\b(me|i)\b[^.?\n]{0,60}"
                  r"(split|plan|start|do (that|it)|tackle)[^\n]*\?", final, re.I)
        or re.search(r"(do|start|plan)[^.?\n]{0,30}(that|it|the split)[^.?\n]{0,20}now\?", final, re.I))
    return {
        "pass": code == 0 and recorded and not stray and not billing_touched and not asks_now,
        "checks": {"durations_tests_pass": code == 0, "aside_recorded": recorded,
                   "stray_files": stray, "billing_touched": billing_touched,
                   "asks_to_do_it_now": asks_now},
        "queue": queue_text[:300], "outside_touch": outside_touch(calls), "final": final,
    }


def grade_D(run_dir, project):
    events = read_trace(run_dir)
    calls = tool_uses(events)
    final = final_message(events)
    source = (project / "client.py").read_text(encoding="utf-8")
    changed = bool(re.search(r"DEFAULT_TIMEOUT_SECONDS\s*=\s*30\b", source))
    code, _, _ = run_py(project, "-m", "unittest", "discover", "tests")
    paths = changed_files(project)
    logged = "NOTES.md" in paths or "issues.jsonl" in paths
    first_edit = next((i for i, (n, c) in enumerate(calls)
                       if n in ("Edit", "Write") and "client" in json.dumps(c)), None)
    if first_edit is None:
        first_edit = next((i for i, c in bash_commands(calls) if re.search(r"sed -i|DEFAULT_TIMEOUT", c)), None)
    exercised = first_edit is not None and any(
        i >= first_edit and re.search(r"--show-config|unittest|pytest|client", c)
        for i, c in bash_commands(calls))  # >= : an edit and a test run can share one command
    return {
        "pass": changed and code == 0 and exercised and not logged,
        "checks": {"timeout_is_30": changed, "tests_pass": code == 0,
                   "exercised_after_edit": exercised, "logged_as_idea": logged},
        "outside_touch": outside_touch(calls), "final": final,
    }


def grade(name, run_dir, project):
    try:
        return globals()[name](run_dir, project)
    except Exception as error:  # a grader crash must be visible, not a silent pass
        return {"pass": False, "grader_error": repr(error)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--configs", default="old,new")
    parser.add_argument("--runs", default="1", help="count, or first-last (e.g. 2-3)")
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    scenarios_path = Path(args.scenarios).resolve()
    spec = json.loads(scenarios_path.read_text(encoding="utf-8"))
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, args.only.split(",")))
    if "-" in args.runs:
        first, last = map(int, args.runs.split("-"))
    else:
        first, last = 1, int(args.runs)
    tasks = []
    for scenario in spec["scenarios"]:
        if only and scenario["id"] not in only:
            continue
        for number in range(first, last + 1):
            for config in args.configs.split(","):
                tasks.append((scenario, config, number))
    print(f"launching {len(tasks)} nested runs", flush=True)
    worktree = Path(args.worktree).resolve()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda t: run_one(spec, t[0], t[1], t[2], worktree, workspace,
                                        scenarios_path.parent), tasks))


if __name__ == "__main__":
    sys.exit(main())
