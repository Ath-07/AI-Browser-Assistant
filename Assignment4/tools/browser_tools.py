import json
from pathlib import Path
from langchain_core.tools import tool # type: ignore

current_browser = None
current_page = None

def set_browser(browser):
    global current_browser
    current_browser = browser


@tool
async def navigate_to(url: str) -> str:
    """Navigate the browser to the specified URL."""
    global current_page
    if current_page is None:
        current_page = await current_browser.new_page() # type: ignore
    await current_page.goto(url)
    return f"Opened {url}"


@tool
async def click_element(selector: str) -> str:
    """Click an element using a CSS selector."""
    await current_page.click(selector) # type: ignore
    return f"Clicked {selector}"


@tool
async def type_text(input_data: str) -> str:
    """Type text into an element. Format: selector|||text"""
    selector, text = input_data.split("|||")
    await current_page.fill(selector, text) # type: ignore
    return f"Typed '{text}'"


@tool
async def open_my_resume() -> str:
    """Open the user's resume PDF in the browser."""
    global current_page
    if current_page is None:
        current_page = await current_browser.new_page() # type: ignore
    with open("data/user_profile.json") as f:
        profile = json.load(f)
    pdf_path = Path(profile["resume_path"]).resolve()
    await current_page.goto(pdf_path.as_uri())
    return f"Opened {pdf_path.name}"