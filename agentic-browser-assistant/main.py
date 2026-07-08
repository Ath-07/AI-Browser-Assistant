# Entry point for the assistant
"""
CLI entry point for the browser/study assistant.

Usage:
    python main.py --task "Apply to this form"
    python main.py --task "Summarize this page" --thread-id my-session
"""

import argparse
import asyncio
import logging
import sys
import uuid
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from src.agents.orchestrator import Orchestrator, PENDING_APPROVAL_TOOL_NAMES
from src.tools.browser_tools import BrowserTool
from src.tools.calendar_tools import CalendarTools
from src.tools.email_tools import EmailTool
from src.utils.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------- #
# Tool wiring
# ---------------------------------------------------------------------- #
# Thin @tool wrappers around a single shared BrowserTool instance, so the
# planner LLM can call them by name. "submit_form" is registered under
# PENDING_APPROVAL_TOOL_NAMES in the orchestrator, so any call to it will
# pause the graph for user approval rather than executing immediately.

def build_browser_tools(browser_tool: BrowserTool) -> list:
    @tool
    async def navigate(url: str) -> str:
        """Navigate the browser to the given URL and wait for it to load."""
        await browser_tool.navigate(url)
        return f"Navigated to {url}"

    @tool
    async def get_dom_tree() -> str:
        """Return the current page's cleaned HTML (scripts/styles/svg stripped)."""
        return await browser_tool.get_dom_tree()

    @tool
    async def fill_form(mapping: dict[str, str]) -> str:
        """Fill form fields given a {css_selector: value} mapping. Does not submit."""
        await browser_tool.fill_form(mapping)
        return f"Filled {len(mapping)} field(s): {list(mapping.keys())}"

    @tool
    async def take_screenshot() -> str:
        """Capture a base64-encoded PNG screenshot of the current viewport."""
        return await browser_tool.take_screenshot()

    @tool
    async def submit_form(selector: str) -> str:
        """
        Click the given selector to submit a form (e.g. a submit button).
        This is an irreversible action and requires explicit user approval
        before it will actually be executed.
        """
        await browser_tool.fill_form({})  # no-op placeholder if mapping unused
        page = browser_tool._require_page()  # noqa: SLF001 - internal, acceptable within same package boundary
        await page.click(selector)
        return f"Submitted form via selector '{selector}'"

    return [navigate, get_dom_tree, fill_form, take_screenshot, submit_form]


def build_calendar_tools(calendar_tool: CalendarTools) -> list:
    @tool
    def list_events(time_min: str, time_max: str, max_results: int = 50) -> str:
        """List calendar events between time_min and time_max (ISO 8601 or natural language like 'today', 'tomorrow', 'next Monday')."""
        events = calendar_tool.list_events(time_min, time_max, max_results)
        if not events:
            return "No events found in that time range."
        lines = []
        for e in events:
            lines.append(f"- {e['summary']}: {e['start']} -> {e['end']}")
        return "\n".join(lines)

    @tool
    def add_event(summary: str, start: str, end: str, description: str = "") -> str:
        """Create a new calendar event."""
        created = calendar_tool.add_event(summary, start, end, description)
        return f"Created event '{created.get('summary')}' (id={created.get('id')})"

    return [list_events, add_event]


def build_email_tools(email_tool: EmailTool) -> list:
    @tool
    def list_unread_emails(max_results: int = 5) -> str:
        """List the most recent unread emails in your Gmail inbox."""
        emails = email_tool.list_unread_emails(max_results)
        if not emails:
            return "No unread emails."
        lines = []
        for e in emails:
            lines.append(f"- From: {e['sender']} | Subject: {e['subject']} | {e['snippet']}")
        return "\n".join(lines)

    @tool
    def summarize_thread(thread_id: str) -> str:
        """Fetch and summarize an email thread by its thread_id."""
        return email_tool.summarize_thread(thread_id)

    @tool
    def draft_email(to: str, intent: str) -> str:
        """Draft an email to a recipient based on a natural-language intent. Does NOT send."""
        draft = email_tool.draft_email(to, intent)
        return f"To: {draft['to']}\nSubject: {draft['subject']}\nBody:\n{draft['body']}"

    @tool
    def send_email(to: str, subject: str, body: str, confirm: bool = False) -> str:
        """Send an email via Gmail. Requires confirm=True to actually send; without it returns a preview."""
        result = email_tool.send_email(to, subject, body, confirm)
        if result["status"] == "preview":
            return f"PREVIEW — To: {to}\nSubject: {subject}\nBody:\n{body}"
        return f"Email sent to {to} (message_id={result.get('message_id', '')})"

    return [list_unread_emails, summarize_thread, draft_email, send_email]


# ---------------------------------------------------------------------- #
# Approval helpers
# ---------------------------------------------------------------------- #

def _extract_pending_calls(messages: list) -> list[dict[str, Any]]:
    """
    Find the most recent AIMessage with tool_calls, and return only the
    calls that require approval (i.e. match PENDING_APPROVAL_TOOL_NAMES).
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            return [
                call
                for call in message.tool_calls
                if call["name"] in PENDING_APPROVAL_TOOL_NAMES
            ]
    return []


def _print_pending_actions(pending_calls: list[dict[str, Any]]) -> None:
    print("\n--- Action requires your approval ---")
    for call in pending_calls:
        print(f"  Tool:      {call['name']}")
        print(f"  Arguments: {call.get('args', {})}")
    print("--------------------------------------")


def _prompt_approval() -> bool:
    while True:
        try:
            answer = input("Do you approve this action? (y/n): ").strip().lower()
        except EOFError:
            # No interactive stdin available — default to safe rejection.
            logger.warning("No input available; defaulting to rejection.")
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'.")


# ---------------------------------------------------------------------- #
# Main loop
# ---------------------------------------------------------------------- #

async def run_task(task: str, thread_id: str) -> None:
    browser_tool = BrowserTool(headless=settings.BROWSER_HEADLESS)
    await browser_tool.start()

    all_tools = build_browser_tools(browser_tool)

    calendar_tool = CalendarTools()
    all_tools += build_calendar_tools(calendar_tool)

    email_tool = EmailTool()
    all_tools += build_email_tools(email_tool)

    orchestrator = Orchestrator(
        tools=all_tools,
        browser_tool=browser_tool,
    )

    try:
        result = await orchestrator.ainvoke(task, thread_id=thread_id)

        while result.get("is_pending_approval"):
            pending_calls = _extract_pending_calls(result["messages"])

            if not pending_calls:
                # Flag was set but we couldn't find the call — surface
                # what we know and stop rather than looping forever.
                logger.warning(
                    "is_pending_approval is True but no pending tool "
                    "calls were found; aborting."
                )
                break

            _print_pending_actions(pending_calls)
            approved = _prompt_approval()

            if not approved:
                print("Action rejected. Aborting task.")
                result = await orchestrator.ainvoke(
                    "The user did not approve the proposed action. "
                    "Do not perform it. Stop here and summarize the "
                    "situation for the user.",
                    thread_id=thread_id,
                )
                break

            print("Action approved. Proceeding...\n")
            result = await orchestrator.ainvoke(
                "The user approved the proposed action. Proceed to "
                "execute it now exactly as proposed.",
                thread_id=thread_id,
                context={"approved_action": True, "pending_calls": pending_calls},
            )

        final_message = result["messages"][-1] if result.get("messages") else None
        if final_message is not None:
            print("\n--- Assistant ---")
            print(getattr(final_message, "content", final_message))
        else:
            print("Task completed with no final message.")

    finally:
        await browser_tool.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Browser/study assistant CLI — run a task via natural language.",
    )
    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help='The task to perform, e.g. --task "Apply to this form"',
    )
    parser.add_argument(
        "--thread-id",
        type=str,
        default=None,
        help="Conversation/session ID for resuming state. Defaults to a new random ID.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    thread_id = args.thread_id or str(uuid.uuid4())

    try:
        asyncio.run(run_task(args.task, thread_id))
    except KeyboardInterrupt:
        print("\nInterrupted by user. Shutting down gracefully...")
        sys.exit(130)  # conventional exit code for SIGINT
    except Exception as exc:  # noqa: BLE001 - top-level catch-all for CLI UX
        logger.error("Fatal error: %s", exc)
        print(f"\nSomething went wrong: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()