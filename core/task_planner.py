"""
core/task_planner.py — Multi-Step Task Planner & Sequential Execution Queue.

Provides AsyncTaskQueue to coordinate multi-step workflows across actions and plugins,
passing intermediate results between steps, handling failure states (retry, skip, abort),
and reporting structured results.
"""

from __future__ import annotations

import asyncio
import json
import re
import traceback
from typing import Any, Callable, Optional


class AsyncTaskQueue:
    """
    Sequentially executes multi-step tool plans.
    Substitutes output from prior steps into subsequent step parameters:
      - {prev_result}
      - {step_1_output}, {step_2_output}, etc.
      - Any custom output variable registered via "output_var"
    """

    def __init__(
        self,
        action_registry=None,
        plugin_registry=None,
        player=None,
        speak_fn: Optional[Callable[[str], Any]] = None,
        logger: Optional[Callable[[str], None]] = None,
    ):
        self.action_registry = action_registry
        self.plugin_registry = plugin_registry
        self.player = player
        self.speak_fn = speak_fn
        self.logger = logger or (lambda msg: print(f"[TaskQueue] {msg}"))
        self.variables: dict[str, Any] = {}
        self.history: list[dict] = []

    def _substitute_variables(self, val: Any) -> Any:
        if isinstance(val, str):
            for k, v in self.variables.items():
                pattern = "{" + k + "}"
                if pattern in val:
                    val = val.replace(pattern, str(v))
            return val
        elif isinstance(val, dict):
            return {k: self._substitute_variables(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [self._substitute_variables(item) for item in val]
        return val

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool via action registry, plugin registry, or fallback."""
        args_substituted = self._substitute_variables(args)

        # 1. Action registry
        if self.action_registry and self.action_registry.has(tool_name):
            ctx = {
                "player": self.player,
                "speak": self.speak_fn,
                "response": None,
                "session_memory": None,
            }
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None, lambda: self.action_registry.run(tool_name, args_substituted, ctx)
            )
            return str(res or "Done.")

        # 2. Plugin registry
        if self.plugin_registry and self.plugin_registry.has(tool_name):
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: self.plugin_registry.run(
                    tool_name, args_substituted, player=self.player, session_memory=None
                ),
            )
            return str(res or "Done.")

        raise ValueError(f"Unknown or unavailable tool: '{tool_name}'")

    async def run_step(self, step: dict, step_idx: int) -> tuple[bool, str]:
        """Run an individual step with optional retry."""
        tool_name = step.get("tool", "").strip()
        args = dict(step.get("args", {}))
        output_var = step.get("output_var", "").strip()
        max_retries = int(step.get("max_retries", 1))

        self.logger(f"Running step {step_idx + 1}: {tool_name}")

        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                res = await self.execute_tool(tool_name, args)
                # Register variables
                self.variables["prev_result"] = res
                self.variables[f"step_{step_idx + 1}_output"] = res
                if output_var:
                    self.variables[output_var] = res
                return True, res
            except Exception as e:
                last_error = str(e)
                self.logger(f"Attempt {attempt + 1} failed for step {step_idx + 1} ({tool_name}): {e}")
                if attempt < max_retries:
                    await asyncio.sleep(1.0)

        return False, last_error

    async def run_plan(
        self,
        plan_name: str,
        steps: list[dict],
        stop_on_failure: bool = True,
    ) -> dict:
        """
        Execute a list of steps in sequence.
        Returns execution summary dictionary.
        """
        self.variables.clear()
        self.history.clear()
        all_ok = True

        self.logger(f"Starting plan: '{plan_name}' with {len(steps)} steps.")

        for i, step in enumerate(steps):
            tool = step.get("tool", "")
            on_error = step.get("on_error", "abort" if stop_on_failure else "skip").lower()

            ok, output = await self.run_step(step, i)
            step_record = {
                "step": i + 1,
                "tool": tool,
                "success": ok,
                "output": output,
            }
            self.history.append(step_record)

            if not ok:
                all_ok = False
                if on_error == "abort":
                    self.logger(f"Plan '{plan_name}' aborted at step {i + 1}.")
                    break
                elif on_error == "skip":
                    self.logger(f"Step {i + 1} failed, skipping per configuration.")
                    continue

        status = "completed" if all_ok else ("partial" if any(h["success"] for h in self.history) else "failed")
        final_output = self.variables.get("prev_result", "")
        if not final_output and self.history:
            final_output = self.history[-1]["output"]

        return {
            "plan_name": plan_name,
            "status": status,
            "steps_executed": len(self.history),
            "total_steps": len(steps),
            "final_output": final_output,
            "step_history": self.history,
        }
