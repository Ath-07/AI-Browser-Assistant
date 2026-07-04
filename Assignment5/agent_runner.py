import sys
import json
import uuid
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

task_store: dict[str, dict] = {}

_playwright_instance = None
_browser_instance = None


async def ensure_browser():
    global _playwright_instance, _browser_instance
    if _browser_instance is None:
        _playwright_instance = await async_playwright().start()
        _browser_instance = await _playwright_instance.chromium.launch(headless=True)
        _set_browser(_browser_instance)


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

        await _add_log(task_id, "Constructing prompt for LLM…")
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

        action = json.loads(content)
        tool = action["tool"]
        tool_input = action["input"]

        await _add_log(task_id, f"LLM chose tool: {tool} | input: {tool_input}")
        await _add_log(task_id, f"Executing {tool}…")

        if tool == "navigate_to":
            result = await navigate_to.ainvoke(tool_input)
        elif tool == "click_element":
            result = await click_element.ainvoke(tool_input)
        elif tool == "type_text":
            result = await type_text.ainvoke(tool_input)
        elif tool == "get_user_profile":
            result = get_user_profile.invoke({})
        elif tool == "open_my_resume":
            result = await open_my_resume.ainvoke({})
        else:
            result = "Unknown tool"

        await _add_log(task_id, f"Tool result: {result}")

        memory.append({"command": command, "result": result})

        entry["status"] = "completed"
        entry["result"] = result

    except Exception as exc:
        entry["status"] = "failed"
        entry["result"] = str(exc)
        await _add_log(task_id, f"Error: {exc}")
