import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from src.agents.orchestrator import Orchestrator, PENDING_APPROVAL_TOOL_NAMES
from src.memory.profile_mgr import ProfileManager
from src.tools.browser_tools import BrowserTool
from src.tools.calendar_tools import CalendarTools
from src.tools.email_tools import EmailTool
from src.utils.config import settings

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- Models -----------------------------------------------------------------

class InitRequest(BaseModel):
    session_id: str

class InitResponse(BaseModel):
    session_id: str
    thread_id: str
    api_key_configured: bool
    history: list[dict]
    messages: list[dict]
    error: str | None = None

class SendMessageRequest(BaseModel):
    session_id: str
    text: str

class ChatResponse(BaseModel):
    messages: list[dict]
    is_thinking: bool
    pending_approval: bool
    pending_calls: list[dict]
    thread_id: str
    history: list[dict]
    error: str | None = None

class ApproveRequest(BaseModel):
    session_id: str

class RejectRequest(BaseModel):
    session_id: str

class ClearRequest(BaseModel):
    session_id: str

class LoadConversationRequest(BaseModel):
    session_id: str
    thread_id: str
    label: str = ""

class SaveApiKeyRequest(BaseModel):
    session_id: str
    api_key: str

# --- Session Management ----------------------------------------------------

_SESSION_TIMEOUT = 1800  # 30 minutes

class Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.orchestrator: Orchestrator | None = None
        self.browser_tool: BrowserTool | None = None
        self.profile_manager: ProfileManager | None = None
        self.messages: list[dict[str, Any]] = []
        self.thread_id: str = ""
        self.is_thinking: bool = False
        self.pending_approval: bool = False
        self.pending_calls: list[dict[str, Any]] = []
        self.api_key: str = ""
        self.show_settings: bool = False
        self.history: list[dict[str, Any]] = []
        self.error_message: str = ""
        self.initialized: bool = False
        self.last_active: float = 0.0

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc).timestamp()

sessions: dict[str, Session] = {}

def get_session(session_id: str) -> Session:
    s = sessions.get(session_id)
    if not s:
        s = Session(session_id)
        sessions[session_id] = s
    s.touch()
    return s

def _stale_sessions() -> list[str]:
    now = datetime.now(timezone.utc).timestamp()
    return [sid for sid, s in sessions.items() if now - s.last_active > _SESSION_TIMEOUT]

async def _cleanup_stale_sessions() -> None:
    stale = _stale_sessions()
    for sid in stale:
        s = sessions.pop(sid, None)
        if s and s.browser_tool:
            try:
                await s.browser_tool.close()
            except Exception:
                pass

# --- Tool builders (mirrored from main.py / state.py) ----------------------

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
        page = browser_tool._require_page()
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

# --- Helpers ---------------------------------------------------------------

def _extract_pending_calls(result_messages: list) -> list[dict[str, Any]]:
    for msg in reversed(result_messages):
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            pending = [
                call for call in tool_calls
                if call["name"] in PENDING_APPROVAL_TOOL_NAMES
            ]
            if pending:
                return pending
    return []

def _extract_assistant_response(result_messages: list) -> str | None:
    for msg in reversed(result_messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = str(msg.content).strip()
            if content:
                return content
    return None

def _load_history_for_session(session: Session) -> list[dict]:
    pm = session.profile_manager
    if not pm:
        return []
    try:
        profile = pm.get_full_profile()
        cmds = profile.get("history", {}).get("commands", {})
        items = []
        for tid, commands in cmds.items():
            for cmd in commands:
                user_input = cmd.get("user_input", "")
                ts = cmd.get("timestamp", "")
                time_str = ""
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts)
                        time_str = dt.strftime("%b %d, %H:%M")
                    except (ValueError, TypeError):
                        time_str = ""
                items.append({
                    "thread_id": tid,
                    "input": user_input,
                    "label": user_input[:60] + "..." if len(user_input) > 60 else user_input,
                    "timestamp": ts,
                    "time_str": time_str,
                    "summary": str(cmd.get("final_summary", "")),
                })
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:50]
    except Exception:
        return []

async def _init_services(session: Session) -> None:
    try:
        bt = session.browser_tool
        if bt is not None:
            try:
                await bt.close()
            except Exception:
                pass

        pm = ProfileManager()
        session.profile_manager = pm

        bt = BrowserTool(headless=settings.BROWSER_HEADLESS)
        await bt.start()
        session.browser_tool = bt

        all_tools = []
        all_tools += build_browser_tools(bt)
        ct = CalendarTools()
        all_tools += build_calendar_tools(ct)
        et = EmailTool()
        all_tools += build_email_tools(et)

        session.orchestrator = Orchestrator(
            tools=all_tools,
            browser_tool=bt,
            profile_manager=pm,
        )
    except Exception as e:
        session.error_message = f"Service init failed: {e}"
        logger.exception("Service init failed")

# --- App setup -------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    for s in sessions.values():
        if s.browser_tool:
            try:
                await s.browser_tool.close()
            except Exception:
                pass

app = FastAPI(lifespan=lifespan, title="Agentic Browser Assistant API")

# --- API routes ------------------------------------------------------------

@app.post("/api/init")
async def api_init(req: InitRequest) -> InitResponse:
    session = get_session(req.session_id)
    if session.initialized and session.thread_id:
        return InitResponse(
            session_id=session.session_id,
            thread_id=session.thread_id,
            api_key_configured=bool(session.api_key),
            history=_load_history_for_session(session),
            messages=session.messages,
        )

    session.thread_id = f"ui-{uuid.uuid4().hex[:12]}"
    try:
        session.api_key = settings.GEMINI_API_KEY or ""
    except Exception:
        session.api_key = ""

    await _init_services(session)
    session.history = _load_history_for_session(session)
    session.initialized = True

    return InitResponse(
        session_id=session.session_id,
        thread_id=session.thread_id,
        api_key_configured=bool(session.api_key),
        history=session.history,
        messages=session.messages,
    )

@app.post("/api/chat/send")
async def api_send_message(req: SendMessageRequest) -> ChatResponse:
    session = get_session(req.session_id)
    text = req.text.strip()
    if not text or session.is_thinking:
        return _build_chat_response(session)

    session.messages.append({
        "role": "user",
        "content": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    if not session.orchestrator:
        session.messages.append({
            "role": "assistant",
            "content": "Assistant is not initialized. Check your API key in settings.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return _build_chat_response(session)

    session.is_thinking = True

    try:
        result = await session.orchestrator.ainvoke(
            text, thread_id=session.thread_id,
        )

        if result.get("is_pending_approval"):
            pending = _extract_pending_calls(result["messages"])
            if pending:
                plan_msg = _extract_assistant_response(result["messages"])
                if plan_msg:
                    session.messages.append({
                        "role": "assistant",
                        "content": plan_msg,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                session.pending_calls = pending
                session.pending_approval = True
                session.is_thinking = False
                return _build_chat_response(session)

        response = _extract_assistant_response(result["messages"])
        if response:
            session.messages.append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            session.messages.append({
                "role": "assistant",
                "content": "Task completed.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        session.messages.append({
            "role": "assistant",
            "content": f"Error: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    finally:
        session.is_thinking = False

    session.history = _load_history_for_session(session)
    return _build_chat_response(session)

@app.post("/api/chat/approve")
async def api_approve(req: ApproveRequest) -> ChatResponse:
    session = get_session(req.session_id)
    if not session.pending_calls:
        return _build_chat_response(session)

    calls = session.pending_calls
    session.pending_approval = False
    session.pending_calls = []
    session.is_thinking = True

    try:
        result = await session.orchestrator.ainvoke(
            "The user approved the proposed action. Proceed to execute it now exactly as proposed.",
            thread_id=session.thread_id,
            context={"approved_action": True, "pending_calls": calls},
        )

        if result.get("is_pending_approval"):
            pending = _extract_pending_calls(result["messages"])
            if pending:
                plan_msg = _extract_assistant_response(result["messages"])
                if plan_msg:
                    session.messages.append({
                        "role": "assistant",
                        "content": plan_msg,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                session.pending_calls = pending
                session.pending_approval = True
                session.is_thinking = False
                return _build_chat_response(session)

        response = _extract_assistant_response(result["messages"])
        if response:
            session.messages.append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        session.messages.append({
            "role": "assistant",
            "content": f"Error executing approved action: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    finally:
        session.is_thinking = False

    session.history = _load_history_for_session(session)
    return _build_chat_response(session)

@app.post("/api/chat/reject")
async def api_reject(req: RejectRequest) -> ChatResponse:
    session = get_session(req.session_id)
    calls = session.pending_calls
    session.pending_approval = False
    session.pending_calls = []
    session.is_thinking = True

    try:
        result = await session.orchestrator.ainvoke(
            "The user did not approve the proposed action. Do not perform it. Stop here and summarize the situation for the user.",
            thread_id=session.thread_id,
        )

        response = _extract_assistant_response(result["messages"])
        if response:
            session.messages.append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        session.messages.append({
            "role": "assistant",
            "content": f"Error: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    finally:
        session.is_thinking = False

    session.history = _load_history_for_session(session)
    return _build_chat_response(session)

@app.post("/api/chat/clear")
async def api_clear(req: ClearRequest) -> ChatResponse:
    session = get_session(req.session_id)
    session.messages = []
    session.thread_id = f"ui-{uuid.uuid4().hex[:12]}"
    session.pending_approval = False
    session.pending_calls = []
    return _build_chat_response(session)

@app.post("/api/chat/load")
async def api_load_conversation(req: LoadConversationRequest) -> ChatResponse:
    session = get_session(req.session_id)
    session.messages = []
    session.thread_id = req.thread_id
    session.pending_approval = False
    session.pending_calls = []
    session.messages.append({
        "role": "system",
        "content": f"Continuing session: {req.label[:80]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return _build_chat_response(session)

@app.post("/api/settings/api-key")
async def api_save_api_key(req: SaveApiKeyRequest) -> ChatResponse:
    session = get_session(req.session_id)
    if not req.api_key:
        return _build_chat_response(session)
    try:
        os.environ["GEMINI_API_KEY"] = req.api_key
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.startswith("GEMINI_API_KEY="):
                    lines[i] = f"GEMINI_API_KEY={req.api_key}\n"
                    found = True
                    break
            if not found:
                lines.append(f"GEMINI_API_KEY={req.api_key}\n")
            with open(env_path, "w") as f:
                f.writelines(lines)
        else:
            with open(env_path, "w") as f:
                f.write(f"GEMINI_API_KEY={req.api_key}\n")

        try:
            from src.utils.llm_client import get_default_llm_client
            get_default_llm_client.cache_clear()
        except AttributeError:
            pass

        await _init_services(session)
        session.show_settings = False
    except Exception as e:
        session.error_message = f"Failed to save API key: {e}"

    return _build_chat_response(session)

@app.get("/api/history")
async def api_history(session_id: str) -> list[dict]:
    session = get_session(session_id)
    return _load_history_for_session(session)

# --- Static files (frontend) -----------------------------------------------

frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

# --- Helper ----------------------------------------------------------------

def _build_chat_response(session: Session) -> ChatResponse:
    return ChatResponse(
        messages=session.messages,
        is_thinking=session.is_thinking,
        pending_approval=session.pending_approval,
        pending_calls=session.pending_calls,
        thread_id=session.thread_id,
        history=session.history,
        error=session.error_message or None,
    )

# --- Entry point -----------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000)
