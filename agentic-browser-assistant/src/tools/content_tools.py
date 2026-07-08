# Content summarization and analysis tools
"""
SummarizationTool for summarizing web pages / raw text and analyzing job
descriptions using the configured LLM.
"""

import json
import logging
import re

from src.tools.browser_tools import BrowserTool
from src.utils.llm_client import get_default_llm_client

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise ImportError(
        "Missing 'beautifulsoup4'. Install it with:\n"
        "    pip install beautifulsoup4"
    ) from exc

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


class SummarizationTool:
    """
    Provides LLM-powered content summarization and job-description analysis
    for the browser assistant.

    Usage:
        tool = SummarizationTool(browser_tool=my_browser_tool)
        summary = await tool.summarize_page("https://example.com/job")
        skills = tool.analyze_job_description(summary["tldr"])
    """

    def __init__(
        self,
        browser_tool: BrowserTool | None = None,
    ) -> None:
        self._browser_tool = browser_tool
        self._llm = get_default_llm_client().get_client()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def summarize_page(self, url_or_text: str) -> dict:
        """
        Summarize the content at a URL or raw text.

        If ``url_or_text`` starts with ``http://`` or ``https://``, the
        method navigates the browser to that URL, fetches the rendered DOM,
        and extracts readable text via BeautifulSoup before sending it to
        the LLM.

        Args:
            url_or_text: A URL to visit, or plain text to summarize.

        Returns:
            dict with keys:
                "tldr"         - 3-sentence plain-text summary
                "key_points"   - list of bullet-point takeaways
                "action_items" - list of suggested next steps

        Raises:
            ValueError: If a URL is given but no BrowserTool was provided.
        """
        text = await self._fetch_text(url_or_text)

        prompt = (
            "Summarize the following content. Return ONLY valid JSON "
            "with exactly these three keys -- no markdown, no explanation:\n"
            '"tldr": a 3-sentence plain-text summary,\n'
            '"key_points": a list of bullet-point key takeaways,\n'
            '"action_items": a list of suggested action items.\n\n'
            f"--- CONTENT ---\n{text}\n--- END CONTENT ---"
        )

        response = self._llm.invoke(prompt)
        return self._parse_json_response(response)

    def analyze_job_description(self, text: str) -> dict:
        """
        Extract skill requirements from a job description.

        Args:
            text: The full job description text.

        Returns:
            dict with keys:
                "required_skills"     - list of explicitly required skills
                "nice_to_have_skills" - list of preferred/optional skills
        """
        prompt = (
            "Analyze the following job description and extract structured "
            "skill information. Return ONLY valid JSON with exactly these "
            "two keys -- no markdown, no explanation:\n"
            '"required_skills": a list of skills explicitly listed as '
            "required / essential / must-have,\n"
            '"nice_to_have_skills": a list of skills listed as preferred / '
            "optional / bonus / nice-to-have.\n\n"
            f"--- JOB DESCRIPTION ---\n{text}\n--- END JOB DESCRIPTION ---"
        )

        response = self._llm.invoke(prompt)
        return self._parse_json_response(response)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _fetch_text(self, url_or_text: str) -> str:
        """Resolve a URL-or-text input into plain text for the LLM."""
        if not _URL_PATTERN.match(url_or_text):
            return url_or_text

        if self._browser_tool is None:
            raise ValueError(
                "A BrowserTool is required to summarize a URL. Pass one "
                "to SummarizationTool(browser_tool=...) or provide raw text."
            )

        await self._browser_tool.navigate(url_or_text)
        raw_html = await self._browser_tool.get_dom_tree()
        return self._clean_html(raw_html)

    @staticmethod
    def _clean_html(html: str) -> str:
        """
        Strip HTML tags and return visible text using BeautifulSoup.
        Removes script, style, svg, nav, footer, header, noscript, iframe,
        form, and button elements as non-content noise.
        """
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(
            [
                "script", "style", "svg", "nav", "footer", "header",
                "noscript", "iframe", "form", "button",
            ]
        ):
            tag.decompose()

        text = soup.get_text(separator="\n")
        return re.sub(r"\n\s*\n+", "\n", text).strip()

    @staticmethod
    def _parse_json_response(response) -> dict:
        """
        Extract a JSON dict from an LLM response, handling markdown code
        fences and surrounding text gracefully.
        """
        content = response.content if hasattr(response, "content") else str(response)

        match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL
        )
        if match:
            content = match.group(1)

        brace_match = re.search(r"\{.*\}", content, re.DOTALL)
        if brace_match:
            content = brace_match.group(0)

        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse LLM JSON response: %s", exc)
            logger.debug("Raw response: %s", content)
            return {"error": f"Failed to parse LLM response: {exc}", "raw": content}
