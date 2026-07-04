import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
import aiosqlite
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, str(Path(__file__).resolve().parent))

import database
from main import app
from agent_runner import task_store

TEST_DB_PATH = Path(__file__).resolve().parent / "test_database.db"


@pytest.fixture(autouse=True)
def _override_db_path():
    original = database.DB_PATH
    database.DB_PATH = TEST_DB_PATH
    yield
    database.DB_PATH = original


@pytest_asyncio.fixture(autouse=True)
async def _setup_test_db(_override_db_path):
    from database import init_db
    await init_db()
    yield
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def _clear_task_store():
    task_store.clear()


@pytest.fixture(autouse=True)
def _mock_agent():
    async def mock_run_agent(task_id: str, command: str):
        entry = task_store.get(task_id)
        if entry is None:
            return
        entry["status"] = "in_progress"
        entry["logs"].append("Started")
        await asyncio.sleep(0.05)
        entry["logs"].append("Step 1: Processing...")
        await asyncio.sleep(0.05)
        entry["status"] = "completed"
        entry["result"] = f"Executed: {command}"
        entry["logs"].append("Finished")

    import main as main_module
    import agent_runner as agent_runner_module
    main_module.run_agent = mock_run_agent
    agent_runner_module.run_agent = mock_run_agent


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
