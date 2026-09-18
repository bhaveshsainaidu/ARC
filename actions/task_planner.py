"""
actions/task_planner.py — Multi-Step Sequential Task Planning Action.

Allows ARC to orchestrate multi-step tasks where output from step N
can feed into step N+1.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any
from core.task_planner import AsyncTaskQueue


def task_planner(parameters: dict, player=None, speak=None, **context) -> str:
    """Execute a multi-step task plan."""
    plan_name = parameters.get("plan_name", "Multi-step plan")
    steps = parameters.get("steps", [])
    if not steps or not isinstance(steps, list):
        return "No steps provided to execute."

    action_reg = context.get("action_registry")
    plugin_reg = context.get("plugin_registry")

    queue = AsyncTaskQueue(
        action_registry=action_reg,
        plugin_registry=plugin_reg,
        player=player,
        speak_fn=speak,
    )

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                res = pool.submit(lambda: asyncio.run(queue.run_plan(plan_name, steps))).result()
        else:
            res = asyncio.run(queue.run_plan(plan_name, steps))
    except Exception as e:
        return f"Task planning failed with error: {e}"

    status = res.get("status", "unknown")
    steps_exec = res.get("steps_executed", 0)
    total = res.get("total_steps", 0)
    final_out = res.get("final_output", "")

    summary_lines = [
        f"Plan '{plan_name}': {status.upper()} ({steps_exec}/{total} steps executed)."
    ]
    for s in res.get("step_history", []):
        mark = "[OK]" if s.get("success") else "[FAIL]"
        summary_lines.append(f"  {mark} Step {s.get('step')} ({s.get('tool')}): {str(s.get('output'))[:60]}")

    if final_out:
        summary_lines.append(f"Final output: {final_out}")

    return "\n".join(summary_lines)


TOOL = {
    "name": "task_planner",
    "description": (
        "Execute multi-step task workflows sequentially. Pass outputs between steps using "
        "{prev_result} or {step_N_output}. Handles step errors and retries."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "plan_name": {
                "type": "STRING",
                "description": "Short name or goal of the plan",
            },
            "steps": {
                "type": "ARRAY",
                "description": "Sequential steps to execute. Each item is {tool: string, args: object, on_error?: 'abort'|'skip', max_retries?: number}",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "tool": {"type": "STRING", "description": "Action or plugin name"},
                        "args": {"type": "OBJECT", "description": "Arguments for the tool"},
                        "output_var": {"type": "STRING", "description": "Optional variable name to store result"},
                        "on_error": {"type": "STRING", "description": "Failure behavior: 'abort' or 'skip'"},
                    },
                    "required": ["tool"],
                },
            },
        },
        "required": ["steps"],
    },
    "handler": task_planner,
}
