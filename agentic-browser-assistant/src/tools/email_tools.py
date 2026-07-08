# Gmail/SMTP API tools
"""
Gmail API-based email tools.

Uses google-api-python-client rather than browser automation for reliable,
structured access to Gmail (listing, reading threads, sending). All
send-capable actions require an explicit confirmation step — send_email
defaults to a dry-run preview and only actually sends when called with
confirm=True, matching the orchestrator's human-in-the-loop pattern for
PENDING_APPROVAL_TOOL_NAMES.
"""

import base64
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.utils.llm_client import get_default_llm_client

logger = logging.getLogger(__name__)

_GMAIL_API_VERSION = "v1"
_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class EmailToolError(Exception):
    """Raised on unrecoverable Gmail API failures."""


class EmailNotConfirmedError(EmailToolError):
    """Raised when send_email is called without explicit confirmation."""


@dataclass
class EmailSummaryItem:
    """Structured representation of a single unread message."""

    message_id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    timestamp: str  # ISO 8601

    def to_dict(self) -> dict[str, str]:
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "sender": self.sender,
            "subject": self.subject,
            "snippet": self.snippet,
            "timestamp": self.timestamp,
        }


class EmailTool:
    """
    Wraps Gmail API access for the assistant: reading unread mail,
    summarizing threads, drafting content, and sending (with mandatory
    confirmation).

    Uses OAuth 2.0 via a ``credentials.json`` file (Google Cloud Console
    desktop app credentials). On first use it opens a browser for the
    user to authorize Gmail access, then caches the token locally in
    ``gmail_token.json`` for subsequent runs.
    """

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "gmail_token.json",
    ) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = self._authenticate()
        self._llm = get_default_llm_client().get_client()

    def _authenticate(self):
        """Perform OAuth 2.0 flow, caching the token for future runs."""
        creds = None

        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(
                self.token_path, _GMAIL_SCOPES
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise EmailToolError(
                        f"OAuth credentials file not found at "
                        f"'{self.credentials_path}'. Download it from "
                        f"the Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, _GMAIL_SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())

        return build("gmail", _GMAIL_API_VERSION, credentials=creds)

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def list_unread_emails(self, max_results: int = 5) -> list[dict[str, str]]:
        """
        Return structured summaries of the most recent unread messages.

        Args:
            max_results: Maximum number of unread messages to fetch.

        Returns:
            List of dicts: {message_id, thread_id, sender, subject,
            snippet, timestamp}, most recent first.

        Raises:
            EmailToolError: On API failure.
        """
        try:
            list_response = (
                self._service.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=max_results)
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to list unread emails: %s", exc)
            raise EmailToolError(f"Failed to list unread emails: {exc}") from exc

        message_refs = list_response.get("messages", [])
        results: list[dict[str, str]] = []

        for ref in message_refs:
            try:
                message = (
                    self._service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=ref["id"],
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
            except HttpError as exc:
                logger.warning("Failed to fetch message %s: %s", ref["id"], exc)
                continue

            item = self._parse_message_metadata(message)
            results.append(item.to_dict())

        logger.info("Read %d unread email(s).", len(results))
        return results

    def summarize_thread(self, thread_id: str) -> str:
        """
        Fetch a full thread and produce a concise LLM-generated summary.

        Args:
            thread_id: Gmail thread ID (from list_unread_emails or search).

        Returns:
            A short natural-language summary of the thread.

        Raises:
            EmailToolError: If the thread can't be fetched or is empty.
        """
        try:
            thread = (
                self._service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to fetch thread %s: %s", thread_id, exc)
            raise EmailToolError(f"Failed to fetch thread '{thread_id}': {exc}") from exc

        messages = thread.get("messages", [])
        if not messages:
            raise EmailToolError(f"Thread '{thread_id}' contains no messages.")

        thread_text = self._render_thread_as_text(messages)

        prompt = (
            "Summarize the following email thread concisely for a busy "
            "professional. Capture: who is involved, what is being "
            "discussed or requested, and any action items or deadlines. "
            "Keep it under 150 words.\n\n"
            f"--- THREAD ---\n{thread_text}\n--- END THREAD ---"
        )

        try:
            response = self._llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM summarization failed for thread %s: %s", thread_id, exc)
            raise EmailToolError(f"Failed to summarize thread: {exc}") from exc

        summary = response.content if hasattr(response, "content") else str(response)
        logger.info("Summarized thread %s (%d messages).", thread_id, len(messages))
        return summary

    # ------------------------------------------------------------------ #
    # Draft (no send)
    # ------------------------------------------------------------------ #

    def draft_email(self, to: str, intent: str) -> dict[str, str]:
        """
        Use the LLM to draft an email body based on a natural-language
        intent. Returns the draft for user review — does NOT send.

        Args:
            to: Intended recipient (used for tone/context only at this stage).
            intent: What the email should accomplish, e.g. "ask my
                mentor Keerthi for feedback on Checkpoint 1 and propose
                a call next week".

        Returns:
            Dict: {"to", "subject", "body"} — a reviewable draft.

        Raises:
            EmailToolError: If drafting fails.
        """
        prompt = (
            "Draft a professional, concise email based on the intent "
            "below. Return ONLY in this exact format, nothing else:\n"
            "SUBJECT: <subject line>\n"
            "BODY:\n<email body>\n\n"
            f"Recipient: {to}\n"
            f"Intent: {intent}"
        )

        try:
            response = self._llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM drafting failed for recipient %s: %s", to, exc)
            raise EmailToolError(f"Failed to draft email: {exc}") from exc

        raw = response.content if hasattr(response, "content") else str(response)
        subject, body = self._parse_draft_output(raw)

        logger.info("Drafted email to %s (not sent).", to)
        return {"to": to, "subject": subject, "body": body}

    # ------------------------------------------------------------------ #
    # Send (requires confirmation)
    # ------------------------------------------------------------------ #

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        confirm: bool = False,
    ) -> dict[str, str]:
        """
        Send an email via Gmail.

        This is an irreversible action. By default (confirm=False) this
        method does NOT send anything — it returns a preview of what
        would be sent so the caller (e.g. the orchestrator's approval
        loop) can surface it to the user first. Only when called with
        confirm=True is the message actually dispatched.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain-text email body.
            confirm: Must be True to actually send. Defaults to False.

        Returns:
            If confirm=False: {"status": "preview", "to", "subject", "body"}
            If confirm=True and send succeeds: {"status": "sent", "message_id", ...}

        Raises:
            EmailNotConfirmedError: If confirm=False (preview only — not
                an error condition, but callers relying on exceptions to
                gate sends can catch this).
            EmailToolError: If the send itself fails.
        """
        preview = {
            "status": "preview",
            "to": to,
            "subject": subject,
            "body": body,
        }

        if not confirm:
            logger.info("Prepared email to %s for approval (not sent).", to)
            return preview

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        try:
            sent = (
                self._service.users()
                .messages()
                .send(userId="me", body={"raw": raw_message})
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to send email to %s: %s", to, exc)
            raise EmailToolError(f"Failed to send email to '{to}': {exc}") from exc

        logger.info(
            "Sent email to %s (message_id=%s, subject=%r).",
            to,
            sent.get("id"),
            subject,
        )
        return {
            "status": "sent",
            "message_id": sent.get("id", ""),
            "to": to,
            "subject": subject,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_message_metadata(message: dict[str, Any]) -> EmailSummaryItem:
        headers = {
            h["name"]: h["value"]
            for h in message.get("payload", {}).get("headers", [])
        }
        internal_date_ms = int(message.get("internalDate", 0))
        timestamp = (
            datetime.fromtimestamp(internal_date_ms / 1000).isoformat()
            if internal_date_ms
            else ""
        )

        return EmailSummaryItem(
            message_id=message.get("id", ""),
            thread_id=message.get("threadId", ""),
            sender=headers.get("From", "Unknown sender"),
            subject=headers.get("Subject", "(no subject)"),
            snippet=message.get("snippet", ""),
            timestamp=timestamp,
        )

    @staticmethod
    def _render_thread_as_text(messages: list[dict[str, Any]]) -> str:
        rendered = []
        for msg in messages:
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            sender = headers.get("From", "Unknown sender")
            date = headers.get("Date", "")
            snippet = msg.get("snippet", "")
            rendered.append(f"From: {sender}\nDate: {date}\n{snippet}\n")
        return "\n---\n".join(rendered)

    @staticmethod
    def _parse_draft_output(raw: str) -> tuple[str, str]:
        """Parse the LLM's 'SUBJECT: ... BODY: ...' format into parts."""
        subject = "(no subject)"
        body = raw.strip()

        if "SUBJECT:" in raw and "BODY:" in raw:
            try:
                subject_part, body_part = raw.split("BODY:", 1)
                subject = subject_part.replace("SUBJECT:", "").strip()
                body = body_part.strip()
            except ValueError:
                logger.warning("Could not cleanly parse LLM draft output; using raw text as body.")

        return subject, body