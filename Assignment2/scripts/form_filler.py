import json
from playwright.async_api import TimeoutError

async def form_filler(browser):

    page = await browser.new_page()

    try:
        with open("data/form_data.json") as f:
            data = json.load(f)

        await page.goto(
            "https://demoqa.com/automation-practice-form",
            timeout=15000
        )

        # Remove ads/footer that can intercept clicks
        await page.evaluate("""
            document.querySelector('#fixedban')?.remove();
            document.querySelector('footer')?.remove();
            document.querySelectorAll('iframe').forEach(e => e.remove());
        """)

        await page.fill("#firstName", data["first_name"])
        await page.fill("#lastName", data["last_name"])
        await page.fill("#userEmail", data["email"])

        # Gender
        gender_map = {
            "Male": "gender-radio-1",
            "Female": "gender-radio-2",
            "Other": "gender-radio-3"
        }

        await page.locator(
            f"label[for='{gender_map[data['gender']]}']"
        ).click(force=True)

        await page.fill("#userNumber", data["mobile"])

        # Subjects
        subject_input = page.locator("#subjectsInput")

        for subject in data["subjects"]:
            await subject_input.fill(subject)
            await subject_input.press("Enter")

        # Hobbies
        hobby_map = {
            "Sports": "hobbies-checkbox-1",
            "Reading": "hobbies-checkbox-2",
            "Music": "hobbies-checkbox-3"
        }

        for hobby in data["hobbies"]:
            locator = page.locator(
                f"label[for='{hobby_map[hobby]}']"
            )

            await locator.scroll_into_view_if_needed()
            await locator.click(force=True)

        await page.fill(
            "#currentAddress",
            data["address"]
        )

        # Screenshot before submission
        await page.screenshot(
            path="screenshots/form_before_submit.png",
            full_page=True
        )

        print("Screenshot saved successfully.")

        # Optional: submit
        # await page.click("#submit")

    except TimeoutError:
        print("Page load timeout.")

    except Exception as e:
        print(f"Form filling failed: {e}")

    finally:
        await page.close()