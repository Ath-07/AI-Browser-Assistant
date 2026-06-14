import json
from playwright.async_api import TimeoutError

async def navigator(browser):

    page = await browser.new_page()

    try:
        await page.goto(
            "https://news.ycombinator.com/",
            timeout=10000
        )

        await page.wait_for_selector(".titleline")

        titles = await page.locator(".titleline").all_inner_texts()

        top_five = titles[:5]

        with open("data/news.json", "w") as f:
            json.dump(top_five, f, indent=4)

        print("News saved successfully.")

    except TimeoutError:
        print("Error: Page load timeout.")

    except Exception as e:
        print(f"Error: Element not found or {e}")

    finally:
        await page.close()