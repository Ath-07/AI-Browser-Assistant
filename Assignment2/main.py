import asyncio

from utils.browser import launch_browser
from scripts.navigator import navigator
from scripts.form_filler import form_filler
from scripts.tab_manager import tab_manager

async def main():

    playwright, browser = await launch_browser()

    try:
        await navigator(browser)
        await form_filler(browser)
        await tab_manager(browser)

    finally:
        await browser.close()
        await playwright.stop()

if __name__ == "__main__":
    asyncio.run(main())