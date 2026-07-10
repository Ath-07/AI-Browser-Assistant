# Agentic Browser Assistant

An AI-powered browser automation assistant with a chat interface. Uses natural language to navigate web pages, fill forms, take screenshots, manage Gmail, and handle Google Calendar events.

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Set your Gemini API key in .env
echo "GEMINI_API_KEY=your_key_here" > .env

# Run the server
python api_server.py
```

Open http://localhost:8000 in your browser.

## Usage

### Web UI

The chat interface lets you give natural language instructions like:

- "Navigate to example.com and take a screenshot"
- "Fill out the registration form with my details"
- "Check my unread emails"
- "Add a meeting to my calendar tomorrow at 2pm"
- "Apply to this job posting and add it to my calendar"

Actions like form submissions and sending emails require your approval before executing.

### CLI

```bash
python main.py --task "Navigate to example.com and take a screenshot"
python main.py --task "Check my unread emails" --thread-id my-session
```

### Settings

Open the sidebar and click **Settings** to configure your Gemini API key. The key can also be set via the `GEMINI_API_KEY` environment variable in a `.env` file.

## Project structure

```
├── api_server.py            FastAPI server (serves frontend + API)
├── main.py                  CLI entry point
├── frontend/
│   ├── index.html           Chat UI
│   ├── app.js               Frontend logic & API calls
│   └── styles.css           Styling
├── src/
│   ├── agents/
│   │   ├── base_agent.py    System prompt & persona
│   │   └── orchestrator.py  LangGraph planner + executor
│   ├── tools/
│   │   ├── browser_tools.py Playwright automation
│   │   ├── calendar_tools.py Google Calendar
│   │   ├── email_tools.py   Gmail integration
│   │   └── content_tools.py Page summarization
│   ├── memory/
│   │   ├── profile_mgr.py   JSON profile storage
│   │   └── vector_store.py  ChromaDB semantic memory
│   └── utils/
│       ├── config.py        Pydantic settings
│       └── llm_client.py    Gemini LLM client
└── data/
    ├── screenshots/         Saved screenshots
    └── profile.json         Conversation history
```

## How it works

The app uses a **natural language → AI planner → tools** pipeline:

1. **Frontend** (`frontend/index.html`, `app.js`, `styles.css`) — A vanilla JS chat UI. User messages are sent as JSON POST requests to the FastAPI backend.
2. **API Server** (`api_server.py`) — FastAPI handles sessions (each gets its own `Orchestrator` instance), serves the frontend statically, and exposes endpoints for sending messages, approving/rejecting irreversible actions, and managing settings.
3. **Orchestrator** (`src/agents/orchestrator.py`) — A LangGraph `StateGraph` with two alternating nodes:
   - `planner` — Sends the user message + system prompt + prior tool results to the Gemini LLM. The LLM decides which tool(s) to call next.
   - `tool_executor` — Runs the requested tools and feeds results back to the planner. This loop repeats until the LLM produces a final answer.
4. **Base agent** (`src/agents/base_agent.py`) — Defines the system prompt persona that governs how the LLM behaves (concise, proactive, security-conscious).
5. **Tools** (`src/tools/`) — Individual capabilities the LLM can invoke:
   - `browser_tools.py` — Playwright-based browser automation (navigate, fill forms, screenshots, etc.)
   - `email_tools.py` — Gmail integration (read, draft, send)
   - `calendar_tools.py` — Google Calendar integration (list, create events)
   - `content_tools.py` — Page summarization
6. **Memory** (`src/memory/`) — `profile_mgr.py` stores conversation history and user profile in JSON; `vector_store.py` uses ChromaDB for semantic memory retrieval.
7. **CLI** (`main.py`) — Alternative entry point that wires up the same tools and orchestrator but prompts for approval via stdin.

### Safety gates

Irreversible actions (`submit_form`, `send_email`, `send_message`) require user approval. In the web UI a modal appears with the proposed tool calls; in the CLI the user is prompted for `y/n`. The graph pauses until the user responds.

### File linking summary

```
app.js  ──HTTP──►  api_server.py  ──►  orchestrator.py
                    │                      ├── base_agent.py (system prompt)
                    │                      ├── browser_tools.py
                    │                      ├── email_tools.py
                    │                      ├── calendar_tools.py
                    │                      └── content_tools.py
                    │
                    ├── main.py (CLI alternative, uses same tools)
                    └── frontend/ (static files served by FastAPI)
```

## Tech stack

- **Backend:** FastAPI, LangGraph, LangChain
- **AI:** Google Gemini 2.5 Flash
- **Browser:** Playwright (Chromium)
- **Frontend:** Vanilla HTML/CSS/JS
- **Integrations:** Gmail API, Google Calendar API
- **Memory:** ChromaDB, JSON file
