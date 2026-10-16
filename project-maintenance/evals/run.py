#!/usr/bin/env python3
"""Run project-maintenance eval scenarios (researched repo-cleanup pass).

Per scenario, per config, per run:
  1. Copy scenarios/<name>/seed/ (if present) into a fresh per-run workspace,
     then execute scenarios/<name>/setup.sh (bash, cwd = the run dir) to build
     the git state a checked-in seed cannot carry: commits, branches, bare
     remotes under remotes/, empty directories.
  2. Invoke `claude -p` with cwd at workspace/, tools = Read,Grep,Glob,Edit,Write,Bash.
     The dispatch prompt includes the brief from scenarios/<name>/brief.md
     and (for `with_skill`) the SKILL.md content.
  3. Execute scenarios/<name>/probe.sh (bash, cwd = the run dir) and capture
     its stdout to outputs/post-state.txt -- key=value lines describing the
     post-run git state for the grader.
  4. Capture chat output (response.md) and timing.json.

The grader (grade.py) reads workspace/, outputs/response.md, and
outputs/post-state.txt, applies scenarios/<name>/rubric.json, and buckets the
run as actioned | surfaced | missed | over_actioned | no_op.

Output layout:
  <output-dir>/
    eval-<id>-<name>/
      eval_metadata.json
      with_skill/  OR  without_skill/
        run-<N>/
          workspace/<post-state files>
          remotes/<bare repos, if the scenario creates any>
          outputs/response.md
          outputs/post-state.txt
          timing.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

AGENT_PROMPT_TEMPLATE = """{skill_section}You are a subagent in a fleet maintenance sweep run by an orchestrator. You have been dispatched to run a maintenance pass on the repository at your current directory. You have full filesystem access here via Read, Grep, Glob, Edit, Write, and Bash.

## Brief from the orchestrator

{brief}

## How to proceed

This workspace is a real git repository; any remotes configured on it are reachable local mirrors - treat them as the project's actual remotes. The project-tracker MCP server and the wrap skill are not available in this environment, so perform the maintenance checks manually with git and the filesystem. There is no interactive user to approve actions: present each finding with evidence, a recommendation, and the exact action you would take on approval, and execute only the actions that are unambiguously safe. Finish with a summary of your findings and any actions you took.
"""


SKILL_SECTION_WRAPPER = """## Skill available: project-maintenance

You have the project-maintenance skill available. Apply it to this maintenance pass. The skill content:

---
{skill_md}
---

"""


def load_evals(evals_path: Path) -> list:
    data = json.loads(evals_path.read_text(encoding="utf-8"))
    return data["evals"]


def load_brief(scenario_dir: Path) -> str:
    return (scenario_dir / "brief.md").read_text(encoding="utf-8")


def build_prompt(brief: str, config: str, skill_md: str) -> str:
    skill_section = (
        SKILL_SECTION_WRAPPER.format(skill_md=skill_md)
        if config == "with_skill"
        else ""
    )
    return AGENT_PROMPT_TEMPLATE.format(skill_section=skill_section, brief=brief)


def materialize_workspace(scenario_dir: Path, workspace_dir: Path) -> None:
    """Copy scenarios/<name>/seed/* into workspace_dir if a seed exists, else start empty.

    Most scenarios have no seed/ at all: git state (commits, branches, remotes,
    empty dirs) cannot live in a checked-in seed, so setup.sh builds everything.
    """
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    seed_dir = scenario_dir / "seed"
    if seed_dir.exists():
        shutil.copytree(seed_dir, workspace_dir)
    else:
        workspace_dir.mkdir(parents=True)


def run_scenario_script(
    scenario_dir: Path, run_dir: Path, script_name: str, timeout: int = 120
) -> tuple[bool, str]:
    """Run scenarios/<name>/<script_name> via bash with cwd at the run dir.

    The script sees workspace/ (and may create remotes/) relative to its cwd.
    Returns (ok, stdout-or-error). A missing script is fine: (True, "").
    """
    script = scenario_dir / script_name
    if not script.exists():
        return True, ""
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(run_dir),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"{script_name} timeout after {timeout}s"
    if result.returncode != 0:
        return False, f"{script_name} exit {result.returncode}: {result.stderr[:500]}"
    return True, result.stdout


def invoke_agent(
    prompt: str, workspace_dir: Path, model: str | None, timeout: int
) -> tuple[str, dict]:
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "bypassPermissions",
        "--tools",
        "Read,Grep,Glob,Edit,Write,Bash",
        "--disable-slash-commands",
    ]
    if model:
        cmd.extend(["--model", model])
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=str(workspace_dir),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", {"_error": f"agent timeout after {timeout}s"}
    duration = time.time() - start
    if result.returncode != 0:
        return "", {"_error": f"agent exit {result.returncode}: {result.stderr[:500]}"}
    try:
        wrapper = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return "", {"_error": f"agent stdout not JSON: {e}; raw={result.stdout[:500]}"}
    response_text = (wrapper.get("result") or "").strip()
    usage = wrapper.get("usage") or {}
    timing = {
        "total_tokens": (usage.get("input_tokens") or 0)
        + (usage.get("output_tokens") or 0),
        "duration_ms": wrapper.get("duration_ms", int(duration * 1000)),
        "total_duration_seconds": round(duration, 2),
        "total_cost_usd": wrapper.get("total_cost_usd"),
        "stop_reason": wrapper.get("stop_reason"),
        "num_turns": wrapper.get("num_turns"),
    }
    return response_text, timing


def write_run(run_dir: Path, response_text: str, timing: dict) -> None:
    (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "outputs" / "response.md").write_text(response_text, encoding="utf-8")
    (run_dir / "timing.json").write_text(json.dumps(timing, indent=2), encoding="utf-8")


def run_single(
    eval_entry: dict,
    config: str,
    run_dir: Path,
    scenarios_root: Path,
    skill_md: str,
    model: str | None,
    timeout: int,
) -> dict:
    scenario_dir = scenarios_root.parent / eval_entry["scenario_dir"]
    workspace_dir = run_dir / "workspace"
    try:
        materialize_workspace(scenario_dir, workspace_dir)
    except FileNotFoundError as e:
        return {"status": "error", "error": str(e)}

    ok, setup_output = run_scenario_script(scenario_dir, run_dir, "setup.sh")
    if not ok:
        return {"status": "error", "error": setup_output}

    brief = load_brief(scenario_dir)
    prompt = build_prompt(brief, config, skill_md)
    response, timing = invoke_agent(prompt, workspace_dir, model, timeout)
    write_run(run_dir, response, timing)

    ok, probe_output = run_scenario_script(scenario_dir, run_dir, "probe.sh")
    post_state = probe_output if ok else f"(probe failed) {probe_output}"
    (run_dir / "outputs" / "post-state.txt").write_text(post_state, encoding="utf-8")

    if "_error" in timing:
        return {"status": "error", "error": timing["_error"]}
    return {"status": "ok", "duration": timing["total_duration_seconds"]}


def write_eval_metadata(eval_dir: Path, eval_entry: dict) -> None:
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "eval_metadata.json").write_text(
        json.dumps(eval_entry, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description="Run project-maintenance evals")
    parser.add_argument("--evals", required=True, help="Path to evals.json")
    parser.add_argument(
        "--skill-md", required=True, help="Path to SKILL.md (used for with_skill)"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Where to write run artifacts"
    )
    parser.add_argument("--runs-per-config", type=int, default=3)
    parser.add_argument(
        "--configs",
        nargs="+",
        default=["with_skill", "without_skill"],
        choices=["with_skill", "without_skill"],
    )
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--only-eval", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    evals_path = Path(args.evals).resolve()
    scenarios_root = evals_path.parent / "scenarios"
    skill_md = Path(args.skill_md).resolve().read_text(encoding="utf-8")
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    evals = load_evals(evals_path)

    work_units = []
    for eval_entry in evals:
        if args.only_eval is not None and eval_entry["id"] != args.only_eval:
            continue
        eval_dir = output_dir / f"eval-{eval_entry['id']}-{eval_entry['name']}"
        write_eval_metadata(eval_dir, eval_entry)
        for config in args.configs:
            for run_n in range(1, args.runs_per_config + 1):
                run_dir = eval_dir / config / f"run-{run_n}"
                run_dir.mkdir(parents=True, exist_ok=True)
                work_units.append((eval_entry, config, run_dir))

    print(f"Discovered {len(work_units)} work units", file=sys.stderr)
    if args.dry_run:
        for eval_entry, config, run_dir in work_units:
            print(
                f"  {eval_entry['name']} / {config} / {run_dir.name}", file=sys.stderr
            )
        return

    def _do(unit):
        eval_entry, config, run_dir = unit
        return unit, run_single(
            eval_entry,
            config,
            run_dir,
            scenarios_root,
            skill_md,
            args.model,
            args.timeout,
        )

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(_do, u): u for u in work_units}
        for future in as_completed(futures):
            try:
                unit, outcome = future.result()
            except Exception as e:  # noqa: BLE001 - boundary catch-all, failure is reported not raised
                unit = futures[future]
                outcome = {"status": "error", "error": f"_do raised: {e}"}
            eval_entry, config, run_dir = unit
            status = outcome.get("status", "?").upper()
            extra = ""
            if outcome.get("error"):
                extra = f" - {outcome['error'][:120]}"
            print(
                f"  [{status}] {eval_entry['name']}/{config}/{run_dir.name}{extra}",
                file=sys.stderr,
            )

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
