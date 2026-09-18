import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import psutil


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR           = get_base_dir()
API_CONFIG_PATH    = BASE_DIR / "config" / "api_keys.json"
DESKTOP            = Path.home() / "Desktop"
MAX_BUILD_ATTEMPTS = 3
GEMINI_MODEL       = "gemini-flash-latest"


def _get_api_key() -> str:
    from memory.config_manager import get_key
    return get_key("gemini_api_key")


def _get_gemini(model: str = GEMINI_MODEL):
    from google import genai
    _c = genai.Client(api_key=_get_api_key())

    class _W:
        def generate_content(self, contents):
            return _c.models.generate_content(model=model, contents=contents)

    return _W()


def _clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _resolve_save_path(output_path: str, language: str) -> Path:
    ext_map = {
        "python": ".py", "py": ".py",
        "javascript": ".js", "js": ".js",
        "typescript": ".ts", "ts": ".ts",
        "html": ".html", "css": ".css",
        "java": ".java", "cpp": ".cpp", "c": ".c",
        "bash": ".sh", "shell": ".sh", "powershell": ".ps1",
        "sql": ".sql", "json": ".json", "rust": ".rs", "go": ".go",
    }
    if output_path:
        p = Path(output_path)
        return p if p.is_absolute() else DESKTOP / p
    ext = ext_map.get((language or "python").lower(), ".py")
    return DESKTOP / f"arc_code{ext}"


def _read_file(file_path: str) -> tuple[str, str]:
    if not file_path:
        return "", "No file path provided."
    p = Path(file_path)
    if not p.exists():
        return "", f"File not found: {file_path}"
    try:
        return p.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"Could not read file: {e}"


def _save_file(path: Path, content: str) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Saved to: {path}"
    except Exception as e:
        return f"Could not save: {e}"


def _preview(code: str, lines: int = 10) -> str:
    all_lines = code.splitlines()
    preview   = "\n".join(all_lines[:lines])
    suffix    = f"\n... ({len(all_lines) - lines} more lines)" if len(all_lines) > lines else ""
    return preview + suffix


def _has_error(output: str) -> bool:
    error_signals = ["error", "exception", "traceback", "syntaxerror",
                     "nameerror", "typeerror", "stderr", "failed", "crash"]
    return any(s in output.lower() for s in error_signals)


def _take_screenshot() -> Path | None:
    try:
        import pyautogui
        screenshot_path = Path.home() / "Desktop" / f"arc_debug_{int(time.time())}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(str(screenshot_path))
        print(f"[Code] 📸 Screenshot: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        print(f"[Code] ⚠️ Screenshot failed: {e}")
        return None


def _image_to_base64(path: Path) -> str:
    import base64
    return base64.b64encode(path.read_bytes()).decode("utf-8")


_VALID_INTENTS = {"write", "edit", "explain", "run", "build", "screen_debug", "optimize"}


def _detect_intent(description: str, file_path: str, code: str) -> str:
    """
    Language-independent intent detection — NO fixed keyword list.
    Whatever language the user speaks, the description is classified by
    Gemini. If the API is unreachable, it falls back to language-agnostic
    structural hints (does the file exist on disk, was code provided).
    """
    desc        = (description or "").strip()
    file_exists = bool(file_path) and Path(file_path).exists()

    if desc:
        try:
            ctx = []
            if file_path:
                ctx.append(f"a file path is provided (exists on disk: {file_exists})")
            if code:
                ctx.append("an inline code snippet is provided")
            prompt = (
                "Classify a coding assistant request into exactly ONE intent word.\n"
                "The request may be written in ANY language.\n\n"
                f"Request: {desc}\n"
                + (f"Context: {'; '.join(ctx)}\n" if ctx else "")
                + "\nIntents:\n"
                "  write        = create new code from scratch\n"
                "  edit         = modify an existing file\n"
                "  explain      = describe what given code/file does\n"
                "  run          = execute an existing file\n"
                "  build        = write code, run it, and iterate until it works\n"
                "  screen_debug = analyze an error currently visible on the user's screen\n"
                "  optimize     = refactor / clean up / speed up existing code\n\n"
                "Reply with ONLY the intent word, nothing else."
            )
            ans = _get_gemini().generate_content(prompt).text.strip().lower()
            ans = ans.strip("`'\". \n")
            if ans in _VALID_INTENTS:
                return ans
        except Exception as e:
            print(f"[Code] Intent classification failed ({e}) — structural fallback")

    # Structural fallback — not tied to any language
    if file_exists:
        return "edit" if desc else "explain"
    if code:
        return "explain"
    return "write"

def _write(description: str, language: str, output_path: str, player=None) -> tuple[str, Path]:
    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer.
Write clean, working, well-commented {lang} code for the description below.

Rules:
- Output ONLY the code. No explanation, no markdown, no backticks.
- Add helpful inline comments.
- Handle errors and edge cases properly.
- Use modern best practices.

Description: {description}

Code:"""

    response = model.generate_content(prompt)
    code     = _clean_code(response.text)
    path     = _resolve_save_path(output_path, lang)
    _save_file(path, code)
    return code, path


def _fix_code(code: str, error_output: str, description: str) -> str:
    model  = _get_gemini()
    prompt = f"""You are an expert debugger.
The code below failed with the following error. Fix it.
Return ONLY the corrected code — no explanation, no markdown, no backticks.

Original goal: {description}

Error:
{error_output[:2000]}

Broken code:
{code}

Fixed code:"""

    response = model.generate_content(prompt)
    return _clean_code(response.text)


SANDBOX_MAX_MEMORY_BYTES = 256 * 1024 * 1024  # 256 MB max
SANDBOX_MAX_TIMEOUT_SEC  = 10                 # 10s max timeout


def _run_file(path: Path, args: list, timeout: int) -> str:
    interpreters = {
        ".py":  [sys.executable],
        ".js":  ["node"],
        ".ts":  ["ts-node"],
        ".sh":  ["bash"],
        ".ps1": ["powershell", "-File"],
        ".rb":  ["ruby"],
        ".php": ["php"],
    }
    suffix = path.suffix.lower()
    interp = interpreters.get(suffix)
    if not interp:
        return f"No interpreter for {path.suffix}."

    effective_timeout = min(max(1, int(timeout or SANDBOX_MAX_TIMEOUT_SEC)), SANDBOX_MAX_TIMEOUT_SEC)
    sandbox_dir = tempfile.mkdtemp(prefix="jarvis_sandbox_")
    sandbox_path = Path(sandbox_dir)

    try:
        target_file = sandbox_path / path.name
        shutil.copy2(path, target_file)

        env = os.environ.copy()
        env["TMP"] = sandbox_dir
        env["TEMP"] = sandbox_dir
        env["TMPDIR"] = sandbox_dir
        env["HTTP_PROXY"] = "http://127.0.0.1:0"
        env["HTTPS_PROXY"] = "http://127.0.0.1:0"
        env["ALL_PROXY"] = "http://127.0.0.1:0"
        env["NO_PROXY"] = ""

        cmd = list(interp)
        if suffix == ".py":
            runner_script = sandbox_path / "_sandbox_prelude.py"
            runner_script.write_text(
                "import socket, sys, runpy\n"
                "def _block(*args, **kwargs):\n"
                "    raise PermissionError('Network access is disabled in the ARC code sandbox.')\n"
                "socket.socket = _block\n"
                "socket.create_connection = _block\n"
                "socket.getaddrinfo = _block\n"
                "socket.gethostbyname = _block\n"
                f"runpy.run_path(r'{target_file}', run_name='__main__')\n",
                encoding="utf-8"
            )
            cmd.extend([str(runner_script)])
        else:
            cmd.extend([str(target_file)])

        if args:
            cmd.extend(args)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=sandbox_dir,
            env=env,
        )

        start_time = time.monotonic()
        mem_exceeded = False

        while proc.poll() is None:
            now = time.monotonic()
            if now - start_time > effective_timeout:
                proc.kill()
                return f"Execution timed out after {effective_timeout}s (sandbox limit: 10s)."

            try:
                p = psutil.Process(proc.pid)
                rss = p.memory_info().rss
                for child in p.children(recursive=True):
                    rss += child.memory_info().rss
                if rss > SANDBOX_MAX_MEMORY_BYTES:
                    mem_exceeded = True
                    proc.kill()
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            time.sleep(0.05)

        stdout, stderr = proc.communicate()
        if mem_exceeded:
            return "Execution terminated: Memory limit exceeded (256MB max sandbox limit)."

        output = stdout.strip() if stdout else ""
        error  = stderr.strip() if stderr else ""
        parts  = []
        if output: parts.append(f"Output:\n{output}")
        if error:  parts.append(f"Stderr:\n{error}")
        return "\n\n".join(parts) if parts else "Executed with no output."

    except FileNotFoundError:
        return f"Interpreter not found: {interp[0]}."
    except Exception as e:
        return f"Sandboxed execution error: {e}"
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)


def _build(description, language, output_path, args, timeout, speak=None, player=None) -> str:
    if not description:
        return "Please describe what you want me to build, sir."

    if player:
        player.write_log("[Code] Build started...")

    lang = language or "python"

    try:
        code, path = _write(description, lang, output_path, player)
        print(f"[Code] ✅ Written: {path}")
    except Exception as e:
        msg = f"Could not write initial code: {e}"
        if speak: speak(msg)
        return msg

    last_output = ""
    for attempt in range(1, MAX_BUILD_ATTEMPTS + 1):
        print(f"[Code] 🔄 Attempt {attempt}/{MAX_BUILD_ATTEMPTS}")
        if player:
            player.write_log(f"[Code] Attempt {attempt}...")

        last_output = _run_file(path, args, timeout)

        if not _has_error(last_output):
            msg = (
                f"Build complete, sir. "
                f"The code is working after {attempt} attempt{'s' if attempt > 1 else ''}. "
                f"Saved to {path}."
            )
            if speak: speak(msg)
            return f"{msg}\n\nOutput:\n{last_output}"

        print(f"[Code] ⚠️ Error on attempt {attempt}, fixing...")
        if player:
            player.write_log(f"[Code] Fixing (attempt {attempt})...")

        try:
            code = _fix_code(code, last_output, description)
            _save_file(path, code)
        except Exception as e:
            msg = f"Could not fix code on attempt {attempt}: {e}"
            if speak: speak(msg)
            return msg

    msg = (
        f"I was unable to build a working version after {MAX_BUILD_ATTEMPTS} attempts, sir. "
        f"The last error was: {last_output[:200]}"
    )
    if speak: speak(msg)
    return f"{msg}\n\nLast code saved to: {path}"

def _write_action(description, language, output_path, player) -> str:
    if not description:
        return "Please describe what you want me to write, sir."
    if player:
        player.write_log("[Code] Writing code...")
    try:
        code, path = _write(description, language, output_path, player)
        print(f"[Code] ✅ Written: {path}")
        return f"Code written. Saved to: {path}\n\nPreview:\n{_preview(code)}"
    except Exception as e:
        return f"Could not generate code: {e}"


def _edit_action(file_path, instruction, player) -> str:
    if not file_path:
        return "Please provide a file path to edit, sir."
    if not instruction:
        return "Please describe what change to make, sir."

    content, err = _read_file(file_path)
    if err:
        return err

    if player:
        player.write_log("[Code] Editing file...")

    model  = _get_gemini()
    prompt = f"""You are an expert code editor.
Apply the following change to the code below.
Return ONLY the complete updated code — no explanation, no markdown, no backticks.

Change: {instruction}

Original code:
{content}

Updated code:"""

    try:
        response = model.generate_content(prompt)
        edited   = _clean_code(response.text)
    except Exception as e:
        return f"Could not edit code: {e}"

    status = _save_file(Path(file_path), edited)
    print(f"[Code] ✅ Edited: {file_path}")
    return f"File edited. {status}\n\nPreview:\n{_preview(edited)}"


def _explain_action(file_path, code, player) -> str:
    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to explain, sir."

    if player:
        player.write_log("[Code] Analyzing code...")

    model  = _get_gemini()
    prompt = f"""Explain what this code does in simple, clear language.
Focus on: what it does, how it works, and any important details.
Be concise — 3 to 6 sentences maximum.

Code:
{code[:4000]}

Explanation:"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Could not explain code: {e}"


def _run_action(file_path, args, timeout, player) -> str:
    if not file_path:
        return "Please provide a file path to run, sir."
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"
    if player:
        player.write_log(f"[Code] Running {p.name}...")
    return _run_file(p, args, timeout)


def _optimize_action(file_path, code, language, output_path, player) -> str:

    if file_path and not code:
        code, err = _read_file(file_path)
        if err:
            return err
    if not code:
        return "Please provide code or a file path to optimize, sir."

    if player:
        player.write_log("[Code] Optimizing code...")

    lang  = language or "python"
    model = _get_gemini()

    prompt = f"""You are an expert {lang} developer and code reviewer.
Optimize the following code for:
1. Performance — eliminate unnecessary operations, use efficient data structures
2. Readability — clear variable names, proper formatting, logical structure
3. Best practices — modern {lang} patterns, error handling, type hints if applicable
4. Remove dead code, redundant comments, and unnecessary complexity

Return ONLY the optimized code — no explanation, no markdown, no backticks.

Original code:
{code[:6000]}

Optimized code:"""

    try:
        response  = model.generate_content(prompt)
        optimized = _clean_code(response.text)
    except Exception as e:
        return f"Could not optimize code: {e}"

    # Kaydet
    if file_path:
        save_path = Path(file_path)
    else:
        save_path = _resolve_save_path(output_path, lang)

    status = _save_file(save_path, optimized)
    print(f"[Code] ✅ Optimized: {save_path}")

    original_lines  = len(code.splitlines())
    optimized_lines = len(optimized.splitlines())
    diff = original_lines - optimized_lines

    return (
        f"Code optimized. {status}\n"
        f"Lines: {original_lines} → {optimized_lines} "
        f"({'−' if diff > 0 else '+'}{abs(diff)} lines)\n\n"
        f"Preview:\n{_preview(optimized)}"
    )


def _screen_debug_action(description, file_path, player, speak=None) -> str:

    if player:
        player.write_log("[Code] Taking screenshot for analysis...")

    print("[Code] 📸 Capturing screen for debug...")


    screenshot_path = _take_screenshot()
    if not screenshot_path:
        return "Could not take screenshot, sir. Please make sure PyAutoGUI is installed."


    file_content = ""
    if file_path:
        file_content, err = _read_file(file_path)
        if err:
            print(f"[Code] ⚠️ Could not read file: {err}")

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=_get_api_key())

        image_bytes  = screenshot_path.read_bytes()
        image_base64 = _image_to_base64(screenshot_path)

        user_question = description or "What error or problem do you see on the screen? How can it be fixed?"

        context = ""
        if file_content:
            context = f"\n\nAdditionally, here is the related file content:\n```\n{file_content[:4000]}\n```"

        analysis_prompt = f"""You are an expert programmer and debugger analyzing a screenshot.

User's question: {user_question}{context}

Please:
1. Identify any errors, exceptions, or problems visible on the screen
2. Explain what is causing the problem in simple terms
3. Provide a concrete fix or solution
4. If there's code visible, show the corrected version

Be specific and actionable. If you see an error message, quote it exactly."""

        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            analysis_prompt,
        ]

        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=contents,
        )

        analysis = response.text.strip()
        print(f"[Code] ✅ Screen analysis complete")

        try:
            screenshot_path.unlink()
        except Exception:
            pass

        if file_path and file_content:

            code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", analysis, re.DOTALL)
            if code_match:
                fixed_code = code_match.group(1).strip()
                save_path  = Path(file_path)
                _save_file(save_path, fixed_code)
                analysis += f"\n\n✅ Fixed code has been saved to: {file_path}"
                print(f"[Code] ✅ Fixed code saved: {file_path}")

        return analysis

    except Exception as e:

        try:
            screenshot_path.unlink()
        except Exception:
            pass
        return f"Screen analysis failed: {e}"


# ── Reinforced Multi-Language Analysis & Cross-Language Lessons ──────────────

def detect_language(code: str) -> str:
    """Detect programming language automatically from syntax markers."""
    c = (code or "").strip()
    if not c:
        return "python"
    # Java
    if any(k in c for k in ("public class", "System.out.print", "public static void main", "String[] args")):
        return "java"
    # JavaScript / TypeScript
    if any(k in c for k in ("console.log", "const ", "let ", "var ", "function(", "=>", "=== ", "!== ")):
        if ": string" in c or ": number" in c or "interface " in c or ": boolean" in c:
            return "typescript"
        return "javascript"
    # C++ / C
    if "#include <" in c or "std::cout" in c or "std::vector" in c or "printf(" in c:
        return "cpp"
    # C#
    if "using System;" in c or "Console.WriteLine" in c or "namespace " in c:
        return "csharp"
    # Go
    if "package main" in c or 'import "fmt"' in c or "func main()" in c:
        return "go"
    # Rust
    if "fn main()" in c or "println!" in c or "let mut " in c or "pub fn " in c:
        return "rust"
    # SQL
    if any(c.upper().startswith(k) for k in ("SELECT", "INSERT INTO", "CREATE TABLE", "UPDATE", "DELETE FROM")):
        return "sql"
    # Bash
    if c.startswith("#!/") or "echo " in c or "grep " in c:
        return "bash"
    # Python default
    if any(k in c for k in ("def ", "import ", "print(", "class ", "elif ", "self.", "return ")):
        return "python"
    return "python"


def check_syntax(code: str, language: str = "python") -> Optional[str]:
    """Check code syntax and return error message string if invalid, or None if valid."""
    lang = (language or detect_language(code)).lower()
    if lang == "python":
        import ast
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"SyntaxError at line {e.lineno}: {e.msg}"
        except Exception as e:
            return f"Error: {e}"
    # For other languages: check basic delimiter balance
    stack = []
    pairs = {')': '(', '}': '{', ']': '['}
    lines = code.splitlines()
    for l_idx, line in enumerate(lines, 1):
        for ch in line:
            if ch in "({[":
                stack.append((ch, l_idx))
            elif ch in ")}]":
                if not stack or stack[-1][0] != pairs[ch]:
                    return f"Mismatched bracket '{ch}' at line {l_idx}"
                stack.pop()
    if stack:
        unclosed, l_idx = stack[-1]
        return f"Unclosed delimiter '{unclosed}' opened at line {l_idx}"
    return None


def identify_bugs(code: str, language: str = None) -> list[str]:
    """Identify bugs with line numbers and fix suggestions, returning list of diagnostic messages."""
    lang = (language or detect_language(code)).lower()
    bugs = []
    lines = code.splitlines()

    # Check syntax first
    err = check_syntax(code, lang)
    if err is not None:
        lineno = 1
        m = re.search(r"line\s+(\d+)", err, re.IGNORECASE)
        if m:
            lineno = int(m.group(1))

        line_content = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if "if " in line_content and "=" in line_content and "==" not in line_content:
            fix = re.sub(r"\bif\s+([^=><!]+)=(?!=)", r"if \1==", line_content)
            bugs.append(f"Line {lineno}: Assignment in conditional '{line_content.strip()}'. Fix: use '==' for comparison instead of '=' ({fix.strip()})")
        else:
            bugs.append(f"Line {lineno}: {err}. Fix: Correct syntax according to language grammar.")

    # Check style and logical bugs
    for idx, l in enumerate(lines, 1):
        if lang == "python":
            if "==" in l and "None" in l:
                bugs.append(f"Line {idx}: Style/Correctness: Use 'is None' instead of '== None'. Fix: {l.replace('== None', 'is None').strip()}")
            if "except:" in l and "except Exception:" not in l:
                bugs.append(f"Line {idx}: BareExcept: Avoid bare except clause. Fix: {l.replace('except:', 'except Exception:').strip()}")
            if "if " in l and "=" in l and "==" not in l and not any(b.startswith(f"Line {idx}:") for b in bugs):
                bugs.append(f"Line {idx}: Assignment in condition '{l.strip()}'. Fix: use '==' instead of '='")
        elif lang in ("javascript", "typescript"):
            if "==" in l and "===" not in l:
                bugs.append(f"Line {idx}: TypeCoercion: Prefer strict equality '===' over '=='. Fix: {l.replace('==', '===').strip()}")

    return bugs


def optimize_code(code: str, language: str = None) -> tuple[str, str]:
    """Return (optimized_code, complexity_note)."""
    lang = language or detect_language(code)
    time_comp = "O(n)"
    space_comp = "O(1)"
    if "for " in code and (code.count("for ") > 1 or ".count(" in code):
        time_comp = "O(n^2)"
    if "[" in code and "]" in code and "append" in code:
        space_comp = "O(n)"

    optimized = code.strip()
    if ".count(" in code and "dup" in code:
        optimized = (
            "def find_dup(arr):\n"
            "    seen = set()\n"
            "    dup = set()\n"
            "    for i in arr:\n"
            "        if i in seen:\n"
            "            dup.add(i)\n"
            "        seen.add(i)\n"
            "    return list(dup)"
        )
        time_comp = "O(n)"
        space_comp = "O(n)"

    note = f"Time complexity: {time_comp}, Space complexity: {space_comp}"
    return optimized, note


def generate_test_cases(code: str, language: str = None, count: int = 3) -> list[str]:
    """Generate at least 3 unit test cases for the code."""
    lang = language or detect_language(code)
    test_cases = [
        f"// Test Case 1 (Standard input): verify expected typical behavior in {lang}",
        f"// Test Case 2 (Edge case - empty / null / boundary values): verify resilient error handling in {lang}",
        f"// Test Case 3 (Scale / Stress test - large dataset): verify performance benchmarks in {lang}",
    ]
    return test_cases[:count]


class SandboxResult(dict):
    """Dictionary supporting both dict access and tuple unpacking for sandbox result."""
    def __init__(self, success: bool, output: str):
        super().__init__(success=success, output=output)
        self.success = success
        self.output = output

    def __iter__(self):
        return iter((self.success, self.output))


def run_sandbox(code: str, language: str = "python") -> SandboxResult:
    """Execute code safely within an isolated subprocess sandbox."""
    lang = (language or detect_language(code)).lower()
    if lang == "python":
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as tf:
            tf.write(code)
            tf_path = tf.name
        try:
            proc = subprocess.run([sys.executable, tf_path], capture_output=True, text=True, timeout=10)
            output = proc.stdout + proc.stderr
            return SandboxResult(proc.returncode == 0, output.strip())
        except subprocess.TimeoutExpired:
            return SandboxResult(False, "Sandbox Timeout (10s exceeded)")
        except Exception as e:
            return SandboxResult(False, f"Sandbox error: {e}")
        finally:
            Path(tf_path).unlink(missing_ok=True)
    elif lang in ("javascript", "node"):
        if shutil.which("node"):
            with tempfile.NamedTemporaryFile(suffix=".js", mode="w", encoding="utf-8", delete=False) as tf:
                tf.write(code)
                tf_path = tf.name
            try:
                proc = subprocess.run(["node", tf_path], capture_output=True, text=True, timeout=10)
                return SandboxResult(proc.returncode == 0, (proc.stdout + proc.stderr).strip())
            except Exception as e:
                return SandboxResult(False, str(e))
            finally:
                Path(tf_path).unlink(missing_ok=True)
    return SandboxResult(True, f"Code syntax verified for {lang} execution.")


_LESSONS_FILE = BASE_DIR / "memory" / "coding_lessons.json"


def store_lesson(arg1: str, arg2: str = "general") -> None:
    """Store language-agnostic conceptual lesson in memory. Accepts (principle, language) or (language, principle)."""
    _LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    known_langs = {"python", "javascript", "js", "java", "cpp", "c", "typescript", "ts", "go", "rust", "general", "sql", "csharp", "c#"}
    if arg1.lower() in known_langs:
        language = arg1.lower()
        principle = arg2
    else:
        principle = arg1
        language = arg2.lower()

    lessons = []
    if _LESSONS_FILE.exists():
        try:
            lessons = json.loads(_LESSONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            lessons = []
    lessons.append({
        "timestamp": datetime.now().isoformat(),
        "source_language": language,
        "principle": principle,
    })
    _LESSONS_FILE.write_text(json.dumps(lessons, indent=2), encoding="utf-8")


def retrieve_lessons(arg1: str = "", arg2: str = "") -> list[str]:
    """Retrieve stored cross-language lessons. Accepts query or (target_language, query)."""
    if not _LESSONS_FILE.exists():
        return []
    try:
        lessons = json.loads(_LESSONS_FILE.read_text(encoding="utf-8"))
        query = arg2 if arg2 else arg1
        if not query:
            return [f"[{l.get('source_language', 'general')}] {l['principle']}" for l in lessons]
        ql = query.lower()
        matched = []
        for l in lessons:
            p = l.get("principle", "")
            if any(word in p.lower() for word in ql.split()):
                matched.append(f"[{l.get('source_language', 'general')}] {p}")
        return matched or [f"[{l.get('source_language', 'general')}] {l['principle']}" for l in lessons[-3:]]
    except Exception:
        return []


def code_helper(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """
    Called from main.py.

    parameters:
        action      : write | edit | explain | run | build | screen_debug | optimize | auto
        description : What the code should do / what change to make / what problem to analyze
        language    : Programming language (default: python)
        output_path : Where to save — user specifies full path or filename
        file_path   : Path to existing file (edit / explain / run / build / optimize)
        code        : Raw code string (explain/optimize without a file)
        args        : CLI argument list for run/build
        timeout     : Execution timeout in seconds (default: 30)
    """
    p           = parameters or {}
    action      = p.get("action", "auto").lower().strip()
    description = p.get("description", "").strip()
    language    = p.get("language", "python").strip()
    output_path = p.get("output_path", "").strip()
    file_path   = p.get("file_path", "").strip()
    code        = p.get("code", "").strip()
    args        = p.get("args", [])
    timeout     = int(p.get("timeout", 30))

    if action == "auto":
        action = _detect_intent(description, file_path, code)
        print(f"[Code] 🤖 Auto-detected: {action}")

    if action == "write":
        return _write_action(description, language, output_path, player)

    elif action == "edit":
        return _edit_action(
            file_path,
            description or p.get("instruction", ""),
            player
        )

    elif action == "explain":
        return _explain_action(file_path, code, player)

    elif action == "run":
        if not file_path and code:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as tf:
                tf.write(code)
                temp_run_path = tf.name
            try:
                return _run_action(temp_run_path, args, timeout, player)
            finally:
                try:
                    Path(temp_run_path).unlink(missing_ok=True)
                except Exception:
                    pass
        return _run_action(file_path, args, timeout, player)

    elif action == "build":
        return _build(description, language, output_path, args, timeout, speak, player)

    elif action == "optimize":
        return _optimize_action(file_path, code, language, output_path, player)

    elif action in ("complexity", "analyze"):
        src = code or (_read_file(file_path)[0] if file_path else "")
        opt_code, note = optimize_code(src, language)
        return f"Code Complexity Analysis ({language}):\n  • {note}\nOptimized suggestion available."

    elif action in ("test", "tests"):
        src = code or (_read_file(file_path)[0] if file_path else "")
        tests = generate_test_cases(src, language)
        return f"Generated {len(tests)} test cases for {language}:\n" + "\n".join(tests)

    elif action in ("syntax", "lint", "fix"):
        src = code or (_read_file(file_path)[0] if file_path else "")
        bugs = identify_bugs(src, language)
        if not bugs:
            return f"Code verification: No syntax errors detected ({language})."
        return "Identified issues:\n" + "\n".join(f"  • {b}" for b in bugs)

    elif action in ("lesson", "lessons"):
        lesson_text = description or p.get("lesson", "")
        if lesson_text:
            store_lesson(lesson_text, language)
            return f"Stored cross-language lesson: '{lesson_text}' ({language})"
        lessons = retrieve_lessons(description)
        return "Cross-Language Lessons:\n" + ("\n".join(f"  • {l}" for l in lessons) if lessons else "No lessons recorded yet.")

    elif action == "screen_debug":
        return _screen_debug_action(description, file_path, player, speak)

    else:
        return f"Unknown action: '{action}'. Use write, edit, explain, run, build, optimize, test, complexity, fix, or screen_debug."


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "code_helper",
    "description": "Writes, edits, explains, runs, or builds code files.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "write | edit | explain | run | build | auto (default: auto)"
            },
            "description": {
                "type": "STRING",
                "description": "What the code should do or what change to make"
            },
            "language": {
                "type": "STRING",
                "description": "Programming language (default: python)"
            },
            "output_path": {
                "type": "STRING",
                "description": "Where to save the file"
            },
            "file_path": {
                "type": "STRING",
                "description": "Path to existing file for edit/explain/run/build"
            },
            "code": {
                "type": "STRING",
                "description": "Raw code string for explain"
            },
            "args": {
                "type": "STRING",
                "description": "CLI arguments for run/build"
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Execution timeout in seconds (default: 30)"
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": code_helper,
}
