# Playwright integration for DOM interaction
"""
Playwright-based browser automation tools for agent use.

Exposes navigation, DOM extraction, form filling, and screenshot
capabilities as async methods on a single BrowserTool instance so it can
be wrapped as LangChain/LangGraph tools (e.g. via @tool decorators) in
the calling code.
"""

import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)

logger = logging.getLogger(__name__)

# Tags whose content contributes nothing useful to an LLM reading the DOM
# and burns tokens disproportionately.
_STRIP_TAG_PATTERN = re.compile(
    r"<(script|style|svg)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
# Catches self-closing/void variants (e.g. inline <svg/>) the pair-based
# pattern above would miss.
_STRIP_SELF_CLOSING_PATTERN = re.compile(
    r"<(script|style|svg)\b[^>]*/>",
    re.IGNORECASE,
)


class BrowserToolError(Exception):
    """Base exception for browser tool failures."""


class NavigationTimeoutError(BrowserToolError):
    """Raised when a page fails to load within the configured timeout."""


class SelectorNotFoundError(BrowserToolError):
    """Raised when a target selector cannot be located on the page."""


class BrowserTool:
    """
    Wraps a single Playwright browser/page lifecycle for agent-driven
    browser automation.

    Usage:
        tool = BrowserTool(headless=True)
        await tool.start()
        await tool.navigate("https://example.com")
        html = await tool.get_dom_tree()
        await tool.fill_form({"#email": "a@b.com"})
        screenshot_b64 = await tool.take_screenshot()
        await tool.close()

    Or as an async context manager:
        async with BrowserTool(headless=True) as tool:
            await tool.navigate(...)
    """

    def __init__(
        self,
        headless: bool = True,
        default_timeout_ms: int = 30_000,
        browser_type: str = "chromium",
    ) -> None:
        self._headless = headless
        self._default_timeout_ms = default_timeout_ms
        self._browser_type = browser_type

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Boot Playwright, launch the browser, and open a fresh page."""
        if self._page is not None:
            return  # already started

        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self._browser_type)
        self._browser = await launcher.launch(headless=self._headless)
        self._context = await self._browser.new_context()
        self._context.set_default_timeout(self._default_timeout_ms)
        self._page = await self._context.new_page()

    async def close(self) -> None:
        """Tear down the page/context/browser/playwright instance."""
        try:
            if self._context is not None:
                await self._context.close()
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    async def __aenter__(self) -> "BrowserTool":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _require_page(self) -> Page:
        if self._page is None:
            raise BrowserToolError(
                "Browser not started. Call `await tool.start()` first "
                "(or use `async with BrowserTool(...) as tool`)."
            )
        return self._page

    # ------------------------------------------------------------------ #
    # 1. navigate
    # ------------------------------------------------------------------ #

    async def navigate(self, url: str, wait_until: str = "load") -> None:
        """
        Navigate the current page to `url` and wait for the page to
        finish loading.

        Args:
            url: Target URL.
            wait_until: Playwright load-state to wait for
                ("load", "domcontentloaded", "networkidle", "commit").

        Raises:
            NavigationTimeoutError: If the page doesn't load in time.
            BrowserToolError: For other navigation failures.
        """
        page = self._require_page()
        try:
            await page.goto(
                url,
                wait_until=wait_until,
                timeout=self._default_timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            logger.warning("Navigation to %s timed out: %s", url, exc)
            raise NavigationTimeoutError(
                f"Timed out navigating to '{url}' after "
                f"{self._default_timeout_ms}ms."
            ) from exc
        except PlaywrightError as exc:
            logger.error("Navigation to %s failed: %s", url, exc)
            raise BrowserToolError(f"Failed to navigate to '{url}': {exc}") from exc

    # ------------------------------------------------------------------ #
    # 2. get_dom_tree
    # ------------------------------------------------------------------ #

    async def get_dom_tree(self) -> str:
        """
        Return the page's current HTML with <script>, <style>, and <svg>
        tags stripped out to reduce token usage when passed to an LLM.

        Raises:
            BrowserToolError: If content extraction fails.
        """
        page = self._require_page()
        try:
            html = await page.content()
        except PlaywrightError as exc:
            logger.error("Failed to extract DOM content: %s", exc)
            raise BrowserToolError(f"Failed to extract DOM content: {exc}") from exc

        cleaned = _STRIP_TAG_PATTERN.sub("", html)
        cleaned = _STRIP_SELF_CLOSING_PATTERN.sub("", cleaned)
        # Collapse excessive whitespace left behind by stripping large blocks.
        cleaned = re.sub(r"\n\s*\n+", "\n", cleaned).strip()
        return cleaned

    # ------------------------------------------------------------------ #
    # 3. fill_form
    # ------------------------------------------------------------------ #

    async def fill_form(self, mapping: dict[str, str]) -> None:
        """
        Fill form fields given a {selector: value} mapping.

        Each selector is waited on individually before being filled, so
        one missing field doesn't silently no-op the rest — it raises
        immediately with the offending selector identified.

        Args:
            mapping: Dict of CSS/text selector -> value to fill.

        Raises:
            SelectorNotFoundError: If a selector can't be located/filled.
        """
        page = self._require_page()

        for selector, value in mapping.items():
            try:
                await page.wait_for_selector(
                    selector,
                    state="visible",
                    timeout=self._default_timeout_ms,
                )
                await page.fill(selector, value)
            except PlaywrightTimeoutError as exc:
                logger.warning("Selector '%s' not found in time: %s", selector, exc)
                raise SelectorNotFoundError(
                    f"Could not locate selector '{selector}' within "
                    f"{self._default_timeout_ms}ms."
                ) from exc
            except PlaywrightError as exc:
                logger.error("Failed to fill selector '%s': %s", selector, exc)
                raise SelectorNotFoundError(
                    f"Failed to fill selector '{selector}': {exc}"
                ) from exc

    # ------------------------------------------------------------------ #
    # 4. take_screenshot
    # ------------------------------------------------------------------ #

    async def take_screenshot(self, full_page: bool = False) -> str:
        """
        Capture a screenshot of the current viewport (or full page) and
        return it as a base64-encoded PNG string. The image is also saved
        to ``data/screenshots/`` on disk with a timestamped filename.

        Args:
            full_page: If True, capture the entire scrollable page
                instead of just the visible viewport.

        Raises:
            BrowserToolError: If the screenshot fails.
        """
        page = self._require_page()
        try:
            image_bytes = await page.screenshot(
                type="png",
                full_page=full_page,
            )
        except PlaywrightError as exc:
            logger.error("Screenshot failed: %s", exc)
            raise BrowserToolError(f"Failed to capture screenshot: {exc}") from exc

        screenshot_dir = Path("data/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = screenshot_dir / f"screenshot_{timestamp}.png"
        filepath.write_bytes(image_bytes)
        logger.info("Screenshot saved to %s", filepath)

        return base64.b64encode(image_bytes).decode("utf-8")