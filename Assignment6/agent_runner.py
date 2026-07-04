import sys
import json
import uuid
import asyncio
from pathlib import Path

ASSIGNMENT4_DIR = Path(__file__).resolve().parent.parent / "Assignment4"
_assign4_str = str(ASSIGNMENT4_DIR)
if _assign4_str not in sys.path:
    sys.path.append(_assign4_str)

from agent.browser_agent import llm, memory
from tools.browser_tools import (
    navigate_to,
    click_element,
    type_text,
    open_my_resume,
    set_browser as _set_browser,
)
from tools.profile_tools import get_user_profile
from playwright.async_api import async_playwright
from intent_parser import parse_intent

task_store: dict[str, dict] = {}

_playwright_instance = None
_browser_instance = None


async def ensure_browser():
    global _playwright_instance, _browser_instance
    if _browser_instance is None:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            _playwright_instance = await async_playwright().start()
            _browser_instance = await _playwright_instance.chromium.launch(headless=False)
            _set_browser(_browser_instance)
        except NotImplementedError:
            raise RuntimeError(
                "Playwright browser launch failed.\n"
                "On Windows, the asyncio event loop must support subprocesses.\n"
                "Try: python -c \"import asyncio; asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())\"\n"
                f"Current loop type: {type(asyncio.get_running_loop()).__name__}"
            )


async def cleanup_browser():
    global _playwright_instance, _browser_instance
    if _browser_instance:
        await _browser_instance.close()
        _browser_instance = None
    if _playwright_instance:
        await _playwright_instance.stop()
        _playwright_instance = None


def _generate_task_id() -> str:
    return uuid.uuid4().hex


async def _add_log(task_id: str, message: str):
    entry = task_store.get(task_id)
    if entry is not None:
        entry["logs"].append(message)


async def run_agent(task_id: str, command: str):
    entry = task_store.get(task_id)
    if entry is None:
        return

    entry["status"] = "in_progress"
    try:
        await ensure_browser()

        # Try the local intent parser first
        action = parse_intent(command)
        if action is not None:
            await _add_log(
                task_id,
                f"Intent parser resolved: {action.action} → {action.parameters}",
            )
        else:
            await _add_log(task_id, "Falling back to LLM intent parsing…")
            prompt = f"""
You are a browser agent.

Available tools:
1. navigate_to(url)
2. click_element(selector)
3. type_text(selector|||text)
4. get_user_profile()
5. open_my_resume()

Conversation history:
{memory}

User command:
{command}

Return ONLY one JSON:

{{
    "tool": "...",
    "input": "..."
}}
"""
            await _add_log(task_id, "Sending command to LLM (Gemini 2.5 Flash)…")
            response = llm.invoke(prompt)
            content = response.content.strip()
            await _add_log(task_id, f"LLM raw response:\n{content}")

            if content.startswith("```json"):
                content = content.replace("```json", "", 1)
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            data = json.loads(content)
            action = type("_Action", (), {"action": data["tool"], "parameters": {"input": data["input"]}})()

        tool = action.action
        params = action.parameters

        await _add_log(task_id, f"Executing {tool}…")

        TOOL_TIMEOUT = 30.0

        if tool == "navigate":
            coro = navigate_to.coroutine(params["url"])
        elif tool == "fill_form":
            combined = f"{params['field_id']}|||{params['value']}"
            coro = type_text.coroutine(combined)
        elif tool == "email":
            result = f"Email queued to {params['recipient']}"
            coro = None
        elif tool == "summarize":
            result = "Summarization complete (placeholder)"
            coro = None
        elif tool == "click":
            coro = click_element.coroutine(params["selector"])
        elif tool == "navigate_to":
            coro = navigate_to.coroutine(params["input"])
        elif tool == "click_element":
            coro = click_element.coroutine(params["input"])
        elif tool == "type_text":
            coro = type_text.coroutine(params["input"])
        elif tool == "get_user_profile":
            result = get_user_profile.func()
            coro = None
        elif tool == "open_my_resume":
            coro = open_my_resume.coroutine()
        else:
            result = f"Unknown tool: {tool}"
            coro = None

        if coro is not None:
            result = await asyncio.wait_for(coro, timeout=TOOL_TIMEOUT)

        await _add_log(task_id, f"Tool result: {result}")

        memory.append({"command": command, "result": result})

        entry["status"] = "completed"
        entry["result"] = result

    except Exception as exc:
        entry["status"] = "failed"
        entry["result"] = str(exc)
        await _add_log(task_id, f"Error: {exc}")
