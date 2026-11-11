#!/usr/bin/env python3
"""A/B runner: OLD skill text versus NEW skill text, same neutral prompt, same fixture.

Each run copies the fixture into a fresh directory under <workspace>, appends the skill text
under test (plus a sandbox notice) to the system prompt, runs `claude -p --model sonnet` with
a hard timeout, saves the stream-json trace, then grades tool traces and resulting state.

Automatic execution credit is conservative: exact standalone report commands, the
inline NODE_THEME_CHECK command, or a headless browser dump of the project file URI.
Custom scripts, alternative quoting and compound commands require manual trace
adjudication. A non-passing automatic score is not proof the agent did not exercise
the target. The Node checker is not injected into evaluated agents' context.

  python ab_runner.py --scenarios scenarios.json --worktree <repo root> --workspace <dir> \
      --only A,B --configs old,new --runs 3 [--jobs 3]
"""

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

UTF8 = "utf-8"
REPLACE_ERRORS = "replace"
TIMEOUT_SECONDS = 600
TOOLS = "Bash,Read,Write,Edit,Glob,Grep"
CLAUDE_FLAGS = (
    "-p --model sonnet --output-format stream-json --verbose "
    "--permission-mode bypassPermissions --tools "
    f"{TOOLS} --disable-slash-commands --setting-sources project "
    "--strict-mcp-config --no-session-persistence --append-system-prompt-file"
).split()
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
EXPECTED_A_ROWS = (
    ("Alder", "north", 120.5),
    ("Birch", "south", None),
    ("Cedar", "east", 75.0),
    ("Dogwood", "west", 310.25),
)
# Blank CSV amount policy: a missing numeric cell may serialize as numeric 0/0.0 or JSON null (None).
BLANK_AMOUNT_POLICY = "0_or_null"
ERROR_OUTPUT_PATTERN = re.compile(
    r"Traceback \(most recent call last\):|\b(ValueError|TypeError|SyntaxError|ReferenceError|AssertionError)\b"
    r"|^\s*error\b|\bcommand failed\b|(?:\bexit(?:ed with)?(?:\s+code)?|\breturncode)\s*[:=]?\s*[1-9]\d*",
    re.IGNORECASE | re.MULTILINE,
)
OUTSIDE_PATTERN = re.compile(
    r"https?://(?!localhost|127\.0\.0\.1)|curl |wget |Invoke-WebRequest|gitea|\.claude|\.gitea|~/|C:\\Users",
    re.IGNORECASE,
)
HANDOFF_PATTERN = re.compile(
    r"(please|you (can|could|should|may|might|will want to)|go ahead and|feel free to|worth)[^.\n]{0,80}"
    r"(open|check|verify|test|try|reload|refresh|confirm)|in (your|a|the) browser|manual(ly)? (test|check|verif)"
    r"|couldn'?t (test|verify|check)|could not (test|verify|check)|let me know if",
    re.IGNORECASE,
)
NODE_THEME_CHECK = r"""const fs = require('fs'), vm = require('vm'), html = fs.readFileSync(process.argv[1], 'utf8').replace(/<!--[\s\S]*?-->/g, ''), scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]); if (!scripts.length) process.exit(1);
const mkStore = () => { const s = new Map(), a = { getItem: k => (s.has(String(k)) ? s.get(String(k)) : null), setItem: (k, v) => s.set(String(k), String(v)), removeItem: k => s.delete(String(k)), clear: () => s.clear() }; return new Proxy(a, { get: (t, p) => (p in t ? t[p] : (s.has(String(p)) ? s.get(String(p)) : undefined)), set: (_, p, v) => (s.set(String(p), String(v)), true), deleteProperty: (_, p) => (s.delete(String(p)), true) }); }, localStorage = mkStore(), sessionStorage = mkStore(), cookies = new Map();
const mkEl = (tag, id = '') => { const cls = new Set(), at = new Map(), ls = new Map(), dataset = {}; const el = { tagName: tag.toUpperCase(), id, dataset, style: {}, textContent: '', innerText: '', onclick: null, classList: { add: (...ns) => ns.forEach(n => n && cls.add(String(n))), remove: (...ns) => ns.forEach(n => cls.delete(String(n))), contains: n => cls.has(String(n)), toggle: (n, f) => { const k = String(n), on = f === undefined ? !cls.has(k) : Boolean(f); on ? cls.add(k) : cls.delete(k); return on; } }, get className() { return [...cls].join(' '); }, set className(v) { cls.clear(); String(v || '').split(/\s+/).filter(Boolean).forEach(c => cls.add(c)); }, getAttribute: n => (n === 'class' ? el.className || null : n && n.startsWith('data-') && n.slice(5) in dataset ? dataset[n.slice(5)] : at.has(n) ? at.get(n) : null), setAttribute(n, v) { const s = String(v); if (n === 'class') { el.className = s; return; } if (n && n.startsWith('data-')) dataset[n.slice(5)] = s; at.set(n, s); }, removeAttribute(n) { if (n === 'class') cls.clear(); if (n && n.startsWith('data-')) delete dataset[n.slice(5)]; at.delete(n); }, hasAttribute: n => el.getAttribute(n) !== null, addEventListener: (t, fn) => { if (!ls.has(t)) ls.set(t, []); ls.get(t).push(fn); }, removeEventListener: (t, fn) => ls.has(t) && ls.set(t, ls.get(t).filter(f => f !== fn)), dispatchEvent(e) { const ev = Object.assign({ target: el, currentTarget: el, preventDefault() {}, stopPropagation() {} }, e); (ls.get(ev.type) || []).forEach(fn => fn.call(el, ev)); if (ev.type === 'click' && typeof el.onclick === 'function') el.onclick.call(el, ev); }, click: () => el.dispatchEvent({ type: 'click' }) }; return el; }, loadPage = () => { const body = mkEl('body'), documentElement = mkEl('html'), btn = mkEl('button', 'theme-toggle'), dLs = new Map(), wLs = new Map(); if (/<body\b[^>]*\bclass\s*=\s*["'][^"']*\bdark\b/i.test(html)) body.classList.add('dark'); if (/<html\b[^>]*\bclass\s*=\s*["'][^"']*\bdark\b/i.test(html)) documentElement.classList.add('dark'); const document = { body, documentElement, readyState: 'complete', getElementById: id => (id === 'theme-toggle' ? btn : null), querySelector: s => (s === '#theme-toggle' || s === 'button' || s === 'button#theme-toggle' ? btn : s === 'body' ? body : s === 'html' || s === ':root' ? documentElement : null), querySelectorAll: s => { const m = document.querySelector(s); return m ? [m] : []; }, addEventListener: (t, fn) => { if (!dLs.has(t)) dLs.set(t, []); dLs.get(t).push(fn); }, get cookie() { return [...cookies.entries()].map(([k, v]) => `${k}=${v}`).join('; '); }, set cookie(str) { const [nv, ...r] = String(str).split(';').map(s => s.trim()); if (!nv || !nv.includes('=')) return; const eq = nv.indexOf('='), k = nv.slice(0, eq).trim(), v = nv.slice(eq + 1).trim(); r.some(a => /^max-age\s*=\s*0$/i.test(a)) || !v ? cookies.delete(k) : cookies.set(k, v); } }; const win = { document, localStorage, sessionStorage, onload: null, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }), addEventListener: (t, fn) => { if (!wLs.has(t)) wLs.set(t, []); wLs.get(t).push(fn); }, setTimeout: fn => (typeof fn === 'function' && fn(), 0), clearTimeout() {} }; win.window = win.globalThis = win.self = win; const ctx = vm.createContext(win); scripts.forEach(c => vm.runInContext(c, ctx, { timeout: 2000 })); (dLs.get('DOMContentLoaded') || []).forEach(fn => fn.call(document, { type: 'DOMContentLoaded' })); (wLs.get('DOMContentLoaded') || []).forEach(fn => fn.call(win, { type: 'DOMContentLoaded' })); (wLs.get('load') || []).forEach(fn => fn.call(win, { type: 'load' })); if (typeof win.onload === 'function') win.onload.call(win, { type: 'load' }); const isDark = () => body.classList.contains('dark') || documentElement.classList.contains('dark') || body.dataset.theme === 'dark' || documentElement.dataset.theme === 'dark'; return { btn, isDark }; };
const p1 = loadPage(), init = p1.isDark(); p1.btn.click(); if (p1.isDark() === init) process.exit(1); const p2 = loadPage(); if (p2.isDark() !== p1.isDark()) process.exit(1); p2.btn.click(); if (p2.isDark() !== init || loadPage().isDark() !== init) process.exit(1);"""


def _run_cmd(args, cwd=None, timeout=None, check=False):
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding=UTF8,
        errors=REPLACE_ERRORS,
        timeout=timeout,
        check=check,
    )


def skill_text(worktree, base, rel, config):
    rev = base if config == "old" else "HEAD"
    return _run_cmd(
        ["git", "-C", str(worktree), "show", f"{rev}:{rel}"], check=True
    ).stdout


def strip_frontmatter(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


def git(cwd, *args):
    return _run_cmd(
        ["git", "-c", "user.name=ab", "-c", "user.email=ab@example.invalid", *args],
        cwd=cwd,
    )


def terminate_process_tree(process):
    """Terminate only this run's process tree and always wait/reap the child."""
    pid = getattr(process, "pid", None)
    if os.name == "nt" and pid is not None:
        with contextlib.suppress(FileNotFoundError, OSError):
            _run_cmd(["taskkill", "/F", "/T", "/PID", str(pid)])
    elif pid is not None and hasattr(os, "killpg"):
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pid, signal.SIGKILL)
    if hasattr(process, "kill"):
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            process.kill()
    process.wait()


def run_one(spec, scenario, config, number, worktree, workspace, *extra):
    default_dir = spec.get("evals_dir", Path(__file__).resolve().parent)
    evals_dir = Path(extra[0]) if extra else Path(default_dir)
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
        text = strip_frontmatter(skill_text(worktree, spec["base"], rel, config))
        parts.append(SKILL_WRAPPER.format(name=Path(rel).parent.name, text=text))
    (run_dir / "system.md").write_text("\n".join(parts), encoding=UTF8)
    (run_dir / "prompt.txt").write_text(scenario["prompt"], encoding=UTF8)
    cmd = ["claude", *CLAUDE_FLAGS, str(run_dir / "system.md")]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    kw = {"start_new_session": True} if os.name != "nt" else {}
    started = time.time()
    status = "ok"
    with (
        open(run_dir / "prompt.txt", "rb") as s_in,
        open(run_dir / "trace.jsonl", "wb") as s_out,
        open(run_dir / "stderr.txt", "wb") as s_err,
    ):
        proc = subprocess.Popen(
            cmd, cwd=project, stdin=s_in, stdout=s_out, stderr=s_err, env=env, **kw
        )
        try:
            proc.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            terminate_process_tree(proc)
            status = "timeout"
    if status == "ok" and proc.returncode not in (0, None):
        status = "error"
    secs = round(time.time() - started, 1)
    res = {"run": name, "status": status, "exit": proc.returncode, "seconds": secs}
    res.update(grade(scenario["grader"], run_dir, project))
    if status != "ok" or proc.returncode != 0:
        res["pass"] = False
    (run_dir / "grade.json").write_text(json.dumps(res, indent=1), encoding=UTF8)
    summary = {"run": name, "status": status, "seconds": secs, "pass": res["pass"]}
    print(json.dumps(summary), flush=True)
    return res


def read_trace(run_dir):
    events = []
    trace_file = run_dir / "trace.jsonl"
    if not trace_file.exists():
        return events
    for line in trace_file.read_text(encoding=UTF8, errors=REPLACE_ERRORS).splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            events.append(json.loads(line))
    return events


def _message_blocks(event):
    msg = event.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return content if isinstance(content, list) else []


def _attach_tool_result(records, block):
    val = block.get("content")
    text = val if isinstance(val, str) else json.dumps(val)
    uid = block.get("tool_use_id")
    unmatched = [r for r in records if r["output"] is None]
    by_id = [r for r in unmatched if uid is not None and r["id"] == uid]
    target = by_id[0] if by_id else None
    if target is not None:
        target["output"] = text
        target["is_error"] = bool(block.get("is_error"))


def tool_calls_with_results(events):
    """Ordered list of dicts correlating each tool_use with its tool_result."""
    records = []
    for event in events:
        etype = event.get("type")
        for block in _message_blocks(event):
            if not isinstance(block, dict):
                continue
            if etype == "assistant" and block.get("type") == "tool_use":
                inp = block.get("input")
                clean_in = inp if isinstance(inp, dict) else {}
                rec = {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": clean_in,
                }
                rec.update({"output": None, "is_error": False})
                records.append(rec)
            elif etype == "user" and block.get("type") == "tool_result":
                _attach_tool_result(records, block)
    return records


def tool_uses(events):
    """Ordered list of (tool name, input) for every tool call."""
    return [(r["name"], r["input"]) for r in tool_calls_with_results(events)]


def tool_outputs(events):
    outputs = []
    for event in events:
        if event.get("type") == "user":
            for block in _message_blocks(event):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    val = block.get("content")
                    outputs.append(val if isinstance(val, str) else json.dumps(val))
    return outputs


def bash_call_succeeded(record):
    out = record.get("output")
    if record.get("name") != "Bash" or out is None or record.get("is_error"):
        return False
    return not ERROR_OUTPUT_PATTERN.search(out)


def _cmd(record):
    inp = record.get("input")
    val = inp.get("command") if isinstance(inp, dict) else ""
    return val if isinstance(val, str) else ""


def final_message(events):
    for event in reversed(events):
        if event.get("type") == "result":
            return event.get("result") or ""
    return ""


def bash_commands(calls):
    return [(i, c.get("command", "")) for i, (n, c) in enumerate(calls) if n == "Bash"]


def run_py(project, *args, timeout=30):
    py = shutil.which("python") or sys.executable or "python"
    try:
        done = _run_cmd([py, *args], cwd=project, timeout=timeout)
        return done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def outside_touch(calls):
    """Commands that look like network or out-of-directory access (reviewed by hand afterwards)."""
    return [c[:200] for _, c in bash_commands(calls) if OUTSIDE_PATTERN.search(c)]


def validate_report_json_rows(data):
    if not isinstance(data, list) or len(data) != len(EXPECTED_A_ROWS):
        return False
    for row, (exp_name, exp_region, exp_amount) in zip(
        data, EXPECTED_A_ROWS, strict=True
    ):
        if not isinstance(row, dict) or set(row.keys()) != {"name", "region", "amount"}:
            return False
        if row.get("name") != exp_name or row.get("region") != exp_region:
            return False
        amt = row.get("amount")
        is_num = isinstance(amt, (int, float)) and not isinstance(amt, bool)
        if exp_amount is None:
            if amt is not None and (not is_num or float(amt) != 0.0):
                return False
        elif not is_num or abs(float(amt) - exp_amount) > 1e-9:
            return False
    return True


def _ok_report_a_call(record):
    commands = {
        f"{python} report.py sample.csv --format json"
        for python in ("python", "python3", "python.exe")
    }
    if not (bash_call_succeeded(record) and _cmd(record).strip() in commands):
        return False
    out = (record.get("output") or "").strip()
    if out.startswith("["):
        try:
            return validate_report_json_rows(json.loads(out))
        except json.JSONDecodeError:
            return False
    return True


def grade_A(run_dir, project):
    events = read_trace(run_dir)
    calls = tool_uses(events)
    final = final_message(events)
    real = [_cmd(r) for r in tool_calls_with_results(events) if _ok_report_a_call(r)]
    code, out, _ = run_py(project, "report.py", "sample.csv", "--format", "json")
    state_ok = False
    if code == 0:
        with contextlib.suppress(json.JSONDecodeError):
            state_ok = validate_report_json_rows(json.loads(out))
    outputs = tool_outputs(events)
    crash_seen = any("Traceback" in o or "ValueError" in o for o in outputs)
    report_ok = "--format json" in final and bool(re.search(r"[\[{]", final))
    checks = {
        "entry_point_run_on_csv": bool(real),
        "manual_trace_adjudication_required": not bool(real),
        "final_state_ok": state_ok,
        "report_has_command_and_output": report_ok,
        "crash_seen_in_trace": crash_seen,
    }
    return {
        "pass": bool(real) and state_ok,
        "checks": checks,
        "outside_touch": outside_touch(calls),
        "final": final,
    }


class ThemePageParser(HTMLParser):
    """Check the fixture's required control before supplying the small DOM model."""

    def __init__(self):
        super().__init__()
        self.toggle_controls = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if attributes.get("id") == "theme-toggle":
            self.toggle_controls.append(
                tag == "button" and not {"disabled", "hidden"}.intersection(attributes)
            )


def verify_theme_persistence(project):
    """Run index.html in a DOM+storage harness across toggle and reload to verify persistence."""
    index_path = project / "index.html"
    if not index_path.is_file():
        return False
    page = ThemePageParser()
    page.feed(index_path.read_text(encoding=UTF8))
    if page.toggle_controls != [True]:
        return False
    node_bin = shutil.which("node")
    if not node_bin:
        return False
    try:
        args = [node_bin, "-e", NODE_THEME_CHECK, str(index_path)]
        return _run_cmd(args, cwd=project, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def grade_B(run_dir, project):
    events = read_trace(run_dir)
    calls = tool_uses(events)
    final = final_message(events)
    persists = verify_theme_persistence(project)
    # Exact standalone spellings only; custom checks need manual trace adjudication.
    commands = {shlex.join(["node", "-e", NODE_THEME_CHECK, "index.html"])}
    commands.update(
        shlex.join(
            [
                browser,
                "--headless",
                "--dump-dom",
                (project / "index.html").resolve().as_uri(),
            ]
        )
        for browser in ("chromium", "google-chrome", "msedge")
    )
    executed = [
        _cmd(r)
        for r in tool_calls_with_results(events)
        if bash_call_succeeded(r) and _cmd(r).strip() in commands
    ]
    handoff = HANDOFF_PATTERN.search(final)
    checks = {
        "persists_in_html": persists,
        "page_logic_executed": bool(executed),
        "manual_trace_adjudication_required": not bool(executed),
        "handoff_language": handoff.group(0) if handoff else None,
    }
    return {
        "pass": persists and bool(executed) and not handoff,
        "checks": checks,
        "executed_commands": [c[:200] for c in executed][:6],
        "outside_touch": outside_touch(calls),
        "final": final,
    }


def grade(name, run_dir, project):
    try:
        return globals()[name](run_dir, project)
    except Exception as error:  # noqa: BLE001 - a grader crash must be visible, not a silent pass
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
    spec = json.loads(scenarios_path.read_text(encoding=UTF8))
    spec.setdefault("evals_dir", str(scenarios_path.parent))
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    only = set(filter(None, args.only.split(",")))
    first, last = (
        map(int, args.runs.split("-")) if "-" in args.runs else (1, int(args.runs))
    )
    tasks = [
        (scenario, config, number)
        for scenario in spec["scenarios"]
        if not only or scenario["id"] in only
        for number in range(first, last + 1)
        for config in args.configs.split(",")
    ]
    print(f"launching {len(tasks)} nested runs", flush=True)
    worktree = Path(args.worktree).resolve()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(
            pool.map(
                lambda t: run_one(spec, t[0], t[1], t[2], worktree, workspace), tasks
            )
        )


if __name__ == "__main__":
    sys.exit(main())
