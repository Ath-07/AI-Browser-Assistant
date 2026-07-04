# Assignment 6 — Architecture Specification

## System Diagram

```mermaid
flowchart LR
    subgraph Frontend ["React UI (Vite + Tailwind)"]
        CB[CommandBar]
        AL[ActivityLog]
        PS[ProfileSettings]
        H[useAgentStream Hook]
    end

    subgraph Backend ["FastAPI Server (Port 8000)"]
        API[HTTP / REST Endpoints]
        WS[WebSocket /ws/status/{task_id}]
    end

    subgraph AgentLayer ["Agent Executor"]
        IP[Intent Parser]
        LLM[Gemini 2.5 Flash]
        M[Memory / Context]
        T[Tool Registry]
    end

    subgraph External ["External Systems"]
        WEB[Browser / Playwright]
        DB[(SQLite DB)]
        API_EXT[Third-party APIs]
    end

    CB -->|POST /command| API
    H -->|WS connect| WS
    PS -->|GET/POST /user/profile| API

    API -->|background task| IP
    IP -->|structured action| T
    T -->|tool call| WEB
    T -->|query| DB
    T -->|request| API_EXT
    LLM -->|plan| T
    M -->|history| LLM

    AL -->|renders logs| WS
```

## Data Flow

1. **User types a command** in the `CommandBar` → sends `POST /command` with `{"text_command": "..."}`.
2. **FastAPI** creates a task (status: `pending`) and returns a `task_id`.
3. **React** opens a WebSocket to `/ws/status/{task_id}` via `useAgentStream` hook.
4. **Agent Executor** runs the command through the Intent Parser → resolves to an `AgentAction`.
5. **Tool Registry** executes the appropriate tool (navigate, click, type, etc.).
6. **Logs stream** back through the WebSocket → `ActivityLog` renders them live.
7. On completion, a `{"type": "done", "status": …}` message closes the socket.

## Layer Responsibilities

| Layer | Responsibility |
|---|---|
| **React UI** | User input, real-time log display, profile management. Communicates over HTTP + WebSocket. |
| **FastAPI** | REST endpoints for commands and profile; WebSocket for log streaming; CORS-enabled for cross-origin requests. |
| **Agent Executor** | Orchestrates the LLM, tools, and memory. Converts raw text into structured actions via the Intent Parser. |
| **Intent Parser** | Pure function that translates natural-language commands into typed `AgentAction` objects (navigate, fill_form, email, summarize, click). |
| **LLM (Gemini)** | Generates tool-call JSON for complex or ambiguous commands. |
| **Tools** | `navigate_to`, `click_element`, `type_text`, `get_user_profile`, `open_my_resume` — each is a callable unit accessing Playwright, SQLite, or external APIs. |
| **Memory** | In-memory list of previous command/result pairs for conversational context. |
| **External APIs** | Browser automation (Playwright), SQLite database for profile persistence. |

## Data Contracts

- `UserProfile` — full user profile (name, email, phone, address, resume_text).
- `Task` — task metadata (id, status, command, result, logs).
- `AgentAction` — parsed intent (action type + flexible parameter dict).
