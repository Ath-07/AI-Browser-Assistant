import os
from pathlib import Path

# Define the directory structure
structure = {
    "agentic-browser-assistant": [
        "data/",
        "src/agents/",
        "src/tools/",
        "src/memory/",
        "src/ui/",
        "src/utils/",
        "tests/",
    ]
}

# Define files to create
files = {
    "src/agents/orchestrator.py": "# Orchestrator logic for task chaining",
    "src/agents/base_agent.py": "# Base agent system prompts",
    "src/tools/browser_tools.py": "# Playwright integration for DOM interaction",
    "src/tools/email_tools.py": "# Gmail/SMTP API tools",
    "src/tools/calendar_tools.py": "# Google Calendar API tools",
    "src/memory/vector_store.py": "# ChromaDB/RAG setup",
    "src/memory/profile_mgr.py": "# Profile/Resume storage management",
    "src/utils/llm_client.py": "# LLM API client wrapper",
    "src/utils/config.py": "# Environment and config management",
    "main.py": "# Entry point for the assistant",
    "requirements.txt": "langgraph\nlangchain-openai\nplaywright\nchromadb\npython-dotenv",
    ".env": "OPENAI_API_KEY=\nGOOGLE_CALENDAR_TOKEN=",
    ".gitignore": "__pycache__/\n*.pyc\n.env\ndata/\n.venv/"
}

def create_scaffold():
    root = Path(".")
    
    # Create directories
    for base, dirs in structure.items():
        for d in dirs:
            path = root / base / d
            path.mkdir(parents=True, exist_ok=True)
            print(f"Created directory: {path}")

    # Create files
    for filepath, content in files.items():
        path = root / "agentic-browser-assistant" / filepath
        with open(path, "w") as f:
            f.write(content)
        print(f"Created file: {path}")

if __name__ == "__main__":
    create_scaffold()
    print("\nScaffold complete! Navigate into 'agentic-browser-assistant' to begin.")