import asyncio
from playwright.async_api import TimeoutError

async def tab_manager(browser):

    context = await browser.new_context()

    urls = [
        "https://www.google.com",
        "https://news.ycombinator.com",
        "https://github.com",
        "https://openai.com",
        "https://www.wikipedia.org"
    ]

    pages = []

    try:

        async def open_tab(url):
            page = await context.new_page()

            try:
                await page.goto(url, timeout=10000)
                title = await page.title()

                print(f"{url} -> {title}")

                return page

            except TimeoutError:
                print(f"Timeout: {url}")
                await page.close()
                return None

        pages = await asyncio.gather(
            *[open_tab(url) for url in urls]
        )

        pages = [p for p in pages if p]

        for page in pages[1:]:
            await page.close()

        print("Closed all tabs except first.")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        await context.close()