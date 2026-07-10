# Orchestrator logic for task chaining
"""
Top-level LangGraph orchestrator for the browser/study assistant.

Wires together a ``planner`` node (LLM decides which tool(s) to call) and a
``tool_executor`` node (actually runs those tools) into a loop, with a
human-in-the-loop pause whenever a tool performs an irreversible action
(submitting a form, sending an email/message) — the graph halts and
returns control to the caller instead of proceeding automatically.

New capabilities added on top of the original loop:

1. **Multi-tool chaining** – tool results are accumulated into
   ``context["_tool_results_chain"]`` so the planner can feed the output of
   one tool into the next call.

2. **Compound command parsing** – user input that contains multiple
   instructions separated by ``AND`` | ``, then`` | ``;`` is broken into a
   serialised plan stored in ``context["_plan_steps"]``.  The planner sees
   the current step (and remaining steps) in its context note and can work
   through them one at a time.

3. **History logging** – every completed task is recorded in the
   ``ProfileManager`` (flat command log under ``history.commands``) and the
   ``VectorStore`` (semantic memory) for future retrieval.
"""

import datetime
import json
import logging
import re
import uuid
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from src.agents.base_agent import SYSTEM_PROMPT, get_system_message
from src.memory.profile_mgr import ProfileManager
from src.memory.vector_store import VectorStore
from src.tools.browser_tools import BrowserTool
from src.utils.llm_client import get_default_llm_client

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# SYSTEM_PROMPT is imported from src.agents.base_agent.

# Tool names whose execution should pause the graph for human approval.
PENDING_APPROVAL_TOOL_NAMES: set[str] = {
    "submit_form",
    "send_email",
    "send_message",
}

# Regex patterns used by the compound-command parser.
_COMMAND_SEPARATOR_RE = re.compile(
    r"(?:\s*,\s*and\s+then|"
    r"\s*,\s*AND\s+THEN|"
    r"\s*,\s+and\s+|\s*,\s+AND\s+|"
    r"\s+and\s+then\s+|\s+AND\s+THEN\s+|"
    r"\s+then\s+|\s+THEN\s+|"
    r"\s*;\s*|"
    r"\s*,\s*(?=[A-Z]))",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


class State(TypedDict):
    """Shared graph state threaded through every node."""

    messages: Annotated[list[BaseMessage], add_messages]
    current_url: str
    context: dict[str, Any]
    is_pending_approval: bool


# --------------------------------------------------------------------------- #
# History logger
# --------------------------------------------------------------------------- #


class _HistoryLogger:
    """
    Records completed command sequences for later retrieval.

    Two persistence layers:

    * **ProfileManager** – a flat JSON key/value store.  Commands are stored
      as a list under ``history.commands.<thread_id>``.
    * **VectorStore** – ChromaDB-based semantic memory.  A summary of each
      session is stored so that the agent can later find "what did I do when
      the user asked about X?" via similarity search.
    """

    def __init__(
        self,
        profile_manager: ProfileManager,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._pm = profile_manager
        self._vs = vector_store

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def log_command(
        self,
        thread_id: str,
        user_input: str,
        plan_steps: list[str],
        results_chain: list[dict],
        final_summary: str,
    ) -> None:
        """
        Persist a completed command sequence to both storage backends.
        """
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "thread_id": thread_id,
            "user_input": user_input,
            "plan_steps": plan_steps,
            "results": results_chain,
            "final_summary": final_summary,
        }

        # --- ProfileManager: append to per-thread command list ---
        key = f"history.commands.{thread_id}"
        existing = self._pm.get_value(key, [])
        existing.append(entry)
        self._pm.update_value(key, existing)

        # --- VectorStore: semantic summary for cross-session retrieval ---
        if self._vs is not None:
            steps_text = "; ".join(
                f"[{s}] -> {r.get('tool', '?')}"
                for s, r in zip(plan_steps or [], results_chain or [])
            )
            memory_text = (
                f"Session {thread_id} at {timestamp}: "
                f"User requested: {user_input}. "
                f"Steps executed: {steps_text}. "
                f"Outcome: {final_summary}"
            )
            try:
                self._vs.add_memory(
                    text=memory_text,
                    metadata={
                        "source": "orchestrator",
                        "thread_id": thread_id,
                        "timestamp": timestamp,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to log semantic memory: %s", exc)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


class Orchestrator:
    """
    Builds and owns the compiled LangGraph app for the assistant.

    Usage:
        orchestrator = Orchestrator(tools=[...])
        result = await orchestrator.ainvoke(
            "Fill out the registration form on this page",
            thread_id="session-123",
        )
        if result["is_pending_approval"]:
            # surface the last AI message / tool call to the user for
            # explicit confirmation before resuming
            ...
            # resume after approval:
            result = await orchestrator.ainvoke(
                "approved", thread_id="session-123"
            )
    """

    def __init__(
        self,
        tools: list[BaseTool] | None = None,
        browser_tool: BrowserTool | None = None,
        profile_manager: ProfileManager | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._tools = tools or []
        self._tools_by_name: dict[str, BaseTool] = {t.name: t for t in self._tools}
        self._browser_tool = browser_tool or BrowserTool()

        self._llm = get_default_llm_client().get_client()
        self._llm_with_tools = (
            self._llm.bind_tools(self._tools) if self._tools else self._llm
        )

        self._checkpointer = MemorySaver()
        self._graph = self._build_graph()

        # Memory stores for history logging.
        self._profile_manager = profile_manager or ProfileManager()
        self._vector_store = vector_store
        self._history = _HistoryLogger(self._profile_manager, self._vector_store)

    # ------------------------------------------------------------------ #
    # Graph construction
    # ------------------------------------------------------------------ #

    def _build_graph(self):
        builder = StateGraph(State)

        builder.add_node("planner", self._planner_node)
        builder.add_node("tool_executor", self._tool_executor_node)

        builder.set_entry_point("planner")

        builder.add_conditional_edges(
            "planner",
            self._route_after_planner,
            {
                "tool_executor": "tool_executor",
                "end": END,
            },
        )

        builder.add_conditional_edges(
            "tool_executor",
            self._route_after_tool_executor,
            {
                "await_approval": END,
                "planner": "planner",
            },
        )

        return builder.compile(checkpointer=self._checkpointer)

    # ------------------------------------------------------------------ #
    # Nodes
    # ------------------------------------------------------------------ #

    async def _planner_node(self, state: State) -> dict[str, Any]:
        """
        LLM reasoning step: given the conversation + current page context,
        decide whether to respond directly or call one or more tools.
        """
        messages = state["messages"]

        # Ensure the system prompt leads every planner call, without
        # duplicating it if it is already present from a prior turn.
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [get_system_message(), *messages]

        context_note = self._format_context_note(state)
        planner_input = messages if not context_note else [
            *messages,
            SystemMessage(content=context_note),
        ]

        try:
            response: AIMessage = await self._llm_with_tools.ainvoke(planner_input)
        except Exception as exc:  # noqa: BLE001 - surface as a chat message, don't crash the graph
            logger.error("Planner LLM call failed: %s", exc)
            response = AIMessage(
                content=(
                    "I hit an error while deciding what to do next: "
                    f"{exc}. Could you rephrase or try again?"
                )
            )

        return {"messages": [response]}

    async def _tool_executor_node(self, state: State) -> dict[str, Any]:
        """
        Execute every tool call requested by the last planner message and
        append their results as ToolMessages.  Flags the graph for human
        approval if any executed tool is a "submit"/"send" style action.

        Also accumulates every successful result into ``context`` under
        ``_tool_results_chain`` so the planner can reference earlier outputs
        when chaining multiple tools.
        """
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []

        tool_messages: list[ToolMessage] = []
        pending_approval = False
        updated_context = dict(state.get("context", {}))
        updated_url = state.get("current_url", "")
        chain: list[dict] = updated_context.setdefault("_tool_results_chain", [])

        for call in tool_calls:
            name = call["name"]
            args = call.get("args", {}) or {}
            call_id = call["id"]

            tool = self._tools_by_name.get(name)
            if tool is None:
                logger.warning("Planner requested unknown tool: %s", name)
                tool_messages.append(
                    ToolMessage(
                        content=f"Error: no tool registered with name '{name}'.",
                        tool_call_id=call_id,
                        name=name,
                    )
                )
                continue

            # ---- Pending-approval tools require human approval ----
            if name in PENDING_APPROVAL_TOOL_NAMES:
                ctx = state.get("context", {}) or {}
                if ctx.get("approved_action") and self._is_approved_call(
                    call, ctx.get("pending_calls", [])
                ):
                    # User already approved — execute below.
                    pass
                else:
                    pending_approval = True
                    tool_messages.append(
                        ToolMessage(
                            content=(
                                f"Action '{name}' with args {args} is pending "
                                "user approval and has not been executed."
                            ),
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
                    # Record the intention so the caller can inspect/approve it.
                    chain.append(
                        {
                            "tool": name,
                            "args": args,
                            "result": "(pending approval)",
                            "status": "pending",
                        }
                    )
                    continue

            # ---- Execute the tool ----
            try:
                result = await self._execute_tool(tool, args)
                result_str = str(result)

                tool_messages.append(
                    ToolMessage(content=result_str, tool_call_id=call_id, name=name)
                )

                if name == "navigate" and "url" in args:
                    updated_url = args["url"]

                # Accumulate into the chaining context.
                chain.append(
                    {
                        "tool": name,
                        "args": args,
                        "result": result_str[:500],
                        "status": "ok",
                    }
                )

                logger.debug(
                    "Tool '%s' succeeded (chain length=%d).", name, len(chain)
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Tool '%s' failed: %s", name, exc)
                error_msg = f"Error executing '{name}': {exc}"
                tool_messages.append(
                    ToolMessage(content=error_msg, tool_call_id=call_id, name=name)
                )
                chain.append(
                    {
                        "tool": name,
                        "args": args,
                        "result": error_msg,
                        "status": "error",
                    }
                )

        # ---- Advance plan index when chain grows (a step was completed) ----
        plan_steps = updated_context.get("_plan_steps")
        if plan_steps is not None and any(
            c.get("status") == "ok" for c in chain[-len(tool_calls):]
            if tool_calls
        ):
            plan_index = updated_context.get("_plan_index", 0)
            if plan_index < len(plan_steps):
                updated_context["_plan_index"] = plan_index + 1

        return {
            "messages": tool_messages,
            "context": updated_context,
            "current_url": updated_url,
            "is_pending_approval": pending_approval,
        }

    async def _execute_tool(self, tool: BaseTool, args: dict[str, Any]) -> Any:
        """Invoke a LangChain tool, handling both sync and async tools."""
        if hasattr(tool, "ainvoke"):
            return await tool.ainvoke(args)
        return tool.invoke(args)

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _route_after_planner(state: State) -> str:
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None)
        return "tool_executor" if tool_calls else "end"

    @staticmethod
    def _route_after_tool_executor(state: State) -> str:
        if state.get("is_pending_approval"):
            return "await_approval"
        return "planner"

    # ------------------------------------------------------------------ #
    # Context helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_approved_call(call: dict, pending_calls: list[dict]) -> bool:
        """Return True when *call* matches a previously-approved pending call."""
        name = call["name"]
        for pc in pending_calls:
            if pc["name"] == name:
                return True
        return False

    @staticmethod
    def _format_context_note(state: State) -> str:
        """
        Build a context note that includes:

        * the current page URL,
        * extra ``context`` fields from the caller,
        * the multi-step plan progress (if a compound command was parsed),
        * the accumulated tool-results chain for reference.
        """
        parts = []

        ctx = state.get("context", {}) or {}
        cur_url = state.get("current_url", "")
        if cur_url:
            parts.append(f"Current page URL: {cur_url}")

        # Include user-provided / extra context (but skip internal keys).
        extra_ctx = {k: v for k, v in ctx.items() if not k.startswith("_")}
        if extra_ctx:
            parts.append(f"Additional context: {extra_ctx}")

        # Plan progress.
        plan_steps = ctx.get("_plan_steps")
        plan_index = ctx.get("_plan_index", 0)
        if plan_steps and plan_index < len(plan_steps):
            parts.append(
                f"\nMulti-step plan ({len(plan_steps)} steps total)."
            )
            for i, step in enumerate(plan_steps):
                marker = ">>> CURRENT STEP <<<" if i == plan_index else ""
                parts.append(f"  Step {i + 1}: {step} {marker}".rstrip())
            if plan_index > 0:
                parts.append(
                    f"\nSteps completed: {plan_index}/{len(plan_steps)}"
                )

        # Last few chained results (for reference).
        chain = ctx.get("_tool_results_chain", [])
        if chain:
            last_ok = [c for c in chain if c.get("status") == "ok"][-3:]
            if last_ok:
                lines = []
                for c in last_ok:
                    result_preview = c["result"][:200]
                    lines.append(
                        f"  - {c['tool']}({c['args']}) -> {result_preview}"
                    )
                parts.append("Recent tool results:\n" + "\n".join(lines))

        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Compound-command parser
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_compound_command(user_input: str) -> list[str]:
        """
        Detect and decompose instructions that contain multiple logical
        steps, such as::

            "Apply to https://form.example.com, AND add to calendar, "
            "AND email mentor"

        Returns a list of step descriptions (strings), or an empty list if
        the input appears to be a single command.
        """
        stripped = user_input.strip()
        if not stripped:
            return []

        # Quick heuristic: only bother splitting if there are obvious
        # connectives.
        if not re.search(
            r"\b(?:AND|and\s+then|then)\b", stripped
        ) and stripped.count(",") < 2:
            return []

        candidates = [s.strip() for s in _COMMAND_SEPARATOR_RE.split(stripped) if s.strip()]

        if len(candidates) < 2:
            return []

        return candidates

    # ------------------------------------------------------------------ #
    # History logging
    # ------------------------------------------------------------------ #

    def _log_history(
        self,
        thread_id: str,
        user_input: str,
        context: dict[str, Any],
        messages: list[BaseMessage],
    ) -> None:
        """Persist the completed session to ProfileManager + VectorStore."""
        ctx = context or {}
        plan_steps: list[str] = ctx.get("_plan_steps", [])
        chain: list[dict] = ctx.get("_tool_results_chain", [])

        # Build a brief final summary from the last assistant message.
        final_summary = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                final_summary = msg.content[:500]
                break

        try:
            self._history.log_command(
                thread_id=thread_id,
                user_input=user_input,
                plan_steps=plan_steps,
                results_chain=chain,
                final_summary=final_summary or "(no summary available)",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to log command history: %s", exc)

    # ------------------------------------------------------------------ #
    # Public entrypoints
    # ------------------------------------------------------------------ #

    async def ainvoke(
        self,
        user_input: str,
        thread_id: str,
        current_url: str = "",
        context: dict[str, Any] | None = None,
    ) -> State:
        """
        Run (or resume) the graph for a given conversation thread.

        If the input is a compound command (detected by
        :meth:`_parse_compound_command`), the parsed plan is injected into
        ``context["_plan_steps"]`` so that the planner can work through the
        steps one at a time.

        When the graph finishes, the session is logged to both
        ``ProfileManager`` and ``VectorStore`` via the ``_HistoryLogger``.

        Args:
            user_input: The user's latest message.
            thread_id: Stable identifier for this conversation/session —
                used by the checkpointer to persist and resume state.
            current_url: Current browser URL, if known.
            context: Arbitrary extra context for the planner.

        Returns:
            The resulting graph state, including ``is_pending_approval``
            which the caller should check before treating any
            submit/send action as complete.
        """
        # ---- Parse compound commands into a serialised plan ----
        plan_steps = self._parse_compound_command(user_input)
        if plan_steps:
            logger.info(
                "Parsed compound command into %d step(s): %s",
                len(plan_steps),
                plan_steps,
            )
            ctx = dict(context or {})
            ctx["_plan_steps"] = plan_steps
            ctx["_plan_index"] = 0
            ctx.setdefault("_tool_results_chain", [])
            context = ctx
        else:
            context = context or {}

        # ---- Invoke the graph ----
        config = {"configurable": {"thread_id": thread_id}}

        input_state: dict[str, Any] = {
            "messages": [("user", user_input)],
        }
        if current_url:
            input_state["current_url"] = current_url
        if context:
            input_state["context"] = context

        result = await self._graph.ainvoke(input_state, config=config)

        # ---- Log history (only for new sessions, not resumptions) ----
        if not plan_steps or context.get("_plan_index", 0) == 0:
            self._log_history(
                thread_id=thread_id,
                user_input=user_input,
                context=result.get("context", {}),
                messages=result.get("messages", []),
            )

        return result

    def get_graph(self):
        """Expose the compiled graph (e.g. for visualization or testing)."""
        return self._graph
