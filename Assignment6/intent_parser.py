import re
from typing import Optional

from models import AgentAction


def parse_intent(text: str) -> Optional[AgentAction]:
    """Translate raw natural-language text into a structured AgentAction.

    Supports: navigate, fill_form, email, summarize, click.

    Returns None when no intent can be determined.
    """
    text = text.strip().lower()

    # ── navigate ──
    m = re.search(
        r"(?:go\s+to|navigate\s+to|open)\s+(.+?)$",
        text,
    )
    if m:
        url = m.group(1).strip()
        if not url.startswith("http"):
            url = "https://" + url
        return AgentAction(action="navigate", parameters={"url": url})

    # ── fill_form ──
    m = re.search(
        r"(?:fill\s+(?:the\s+)?(?:form|input)\s+with\s+|\b(?:enter|type)\s+)\"?(.+?)\"?\s+in\s+(?:the\s+)?\"?(.+?)\"?\s*(?:field|box|input)?\s*$",
        text,
    )
    if m:
        return AgentAction(
            action="fill_form",
            parameters={"field_id": m.group(2).strip(), "value": m.group(1).strip()},
        )

    # ── email ──
    m = re.search(
        r"(?:send\s+)?email\s+(?:to\s+)?(\S+@\S+)",
        text,
    )
    if m:
        return AgentAction(
            action="email",
            parameters={"recipient": m.group(1).strip()},
        )

    # ── summarize ──
    if re.search(r"\bsummarize\b", text):
        return AgentAction(action="summarize", parameters={})

    # ── click ──
    m = re.search(
        r"click\s+(?:on\s+)?(?:the\s+)?(.+?)$",
        text,
    )
    if m:
        return AgentAction(
            action="click",
            parameters={"selector": m.group(1).strip()},
        )

    return None
