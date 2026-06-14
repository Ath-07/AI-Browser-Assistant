from playwright.async_api import async_playwright

async def launch_browser():
    playwright = await async_playwright().start()

    browser = await playwright.chromium.launch(
        headless=False
    )

    return playwright, browser