import json
import asyncio
from playwright.async_api import async_playwright # type: ignore
from agent.browser_agent import llm, memory
from tools.browser_tools import (
    navigate_to,
    click_element,
    type_text,
    open_my_resume
)
from tools.profile_tools import get_user_profile
from tools.browser_tools import set_browser


async def execute(command: str):

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

    response = llm.invoke(prompt)

    print("\nLLM Response:")
    print(response.content)

    content = response.content.strip()

    if content.startswith("```json"):
        content = content.replace("```json", "", 1)

    if content.endswith("```"):
        content = content[:-3]

    content = content.strip()
    action = json.loads(content)

    tool = action["tool"]
    tool_input = action["input"]

    if tool == "navigate_to":
        result = await navigate_to.ainvoke(tool_input) # type: ignore
    elif tool == "click_element":
        result = await click_element.ainvoke(tool_input) # type: ignore
    elif tool == "type_text":
        result = await type_text.ainvoke(tool_input) # type: ignore
    elif tool == "get_user_profile":
        result = get_user_profile.invoke({}) # type: ignore
    elif tool == "open_my_resume":
        result = await open_my_resume.ainvoke({}) # type: ignore
    else:
        result = "Unknown tool"

    memory.append(
        {
            "command": command,
            "result": result
        }
    )
    return result


async def main():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    set_browser(browser)

    while True:
        cmd = input("\nUser > ")
        if cmd.lower() == "exit":
            break
        result = await execute(cmd)
        print("\nResult >", result)

    await browser.close()
    await playwright.stop()


asyncio.run(main())