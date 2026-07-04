# AI-Browser-Assistant

This project is developed under **Summer of Code 2026**.

A progressive 6-assignment project that builds an AI-powered browser agent, evolving from basic async I/O to a full LLM-driven automation agent with a web API and React frontend.

**Repository:** [https://github.com/Ath-07/AI-Browser-Assistant](https://github.com/Ath-07/AI-Browser-Assistant)

## Assignment 1 — Async Data Loader
- Loads user profile from a JSON file using asynchronous Python (`asyncio`)
- Demonstrates basic async file I/O with `json.load()` wrapped in a coroutine
- Prints structured user memory (name, email, phone, address) to the console

## Assignment 2 — Playwright Browser Automation
- Launches a Chromium browser and runs three automation scripts sequentially
- **Navigator** scrapes top 5 Hacker News headlines; **Form Filler** fills a practice form and captures a screenshot; **Tab Manager** opens 5 sites in parallel, logs titles, and cleans up tabs
- Uses Playwright's async API with robust error handling for timeouts and missing elements

## Assignment 3 — LLM Intent Parsing
- Converts natural language commands into structured JSON actions using Google Gemini (`gemini-2.5-flash`)
- Defines a strict Pydantic schema with allowed actions (`fill_form`, `navigate`, `email`, `summarize`, `click`)
- Handles ambiguity gracefully by setting `clarification_needed` flags instead of guessing

## Assignment 4 — LangChain Browser Agent
- Combines Playwright + Gemini via `langchain_google_genai` into a full tool-calling agent
- Exposes 5 tools: `navigate_to`, `click_element`, `type_text`, `get_user_profile`, and `open_my_resume`
- Maintains conversation history in list-based memory, enabling context-aware multi-step interactions

## Assignment 5 — FastAPI Web Server with WebSocket Log Streaming
- Wraps the LangChain agent into a FastAPI REST API with endpoints: `POST /command`, `GET /status/{task_id}`, user profile CRUD
- Provides real-time log streaming via `WebSocket /ws/status/{task_id}`
- Uses SQLite (`aiosqlite`) for persistent user profile storage
- Runs the agent in the background with task polling and status tracking

## Assignment 6 — Full-Stack Application with React Frontend
- Extends Assignment 5 with a **React 18 + Vite + Tailwind CSS** frontend
- Adds a local **intent parser** (regex-based) that resolves commands for 5 actions (`navigate`, `fill_form`, `email`, `summarize`, `click`) before falling back to the LLM
- Real-time activity log via WebSocket with auto-scroll and status badges
- Profile settings form for viewing/editing user profile from the UI
- Includes a formal architecture specification (`ARCHITECTURE.md`)

---

**Author:** Atharva
