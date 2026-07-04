import json
import asyncio

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from main import app
from agent_runner import task_store


class TestUserProfile:
    @pytest.mark.asyncio
    async def test_create_and_retrieve(self, async_client: AsyncClient):
        payload = {
            "name": "Alice",
            "email": "alice@example.com",
            "phone": "123-456-7890",
            "address": "123 Main St",
            "resume_text": "Python developer",
        }
        resp = await async_client.post("/user/profile", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Alice"
        assert data["email"] == "alice@example.com"
        assert data["phone"] == "123-456-7890"

        resp = await async_client.get("/user/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Alice"
        assert data["email"] == "alice@example.com"
        assert data["phone"] == "123-456-7890"
        assert data["address"] == "123 Main St"
        assert data["resume_text"] == "Python developer"

    @pytest.mark.asyncio
    async def test_persistence_between_requests(self, async_client: AsyncClient):
        await async_client.post("/user/profile", json={
            "name": "Bob",
            "email": "bob@test.com",
        })
        resp = await async_client.get("/user/profile")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Bob"
        assert resp.json()["email"] == "bob@test.com"

    @pytest.mark.asyncio
    async def test_get_when_no_profile(self, async_client: AsyncClient):
        resp = await async_client.get("/user/profile")
        assert resp.status_code == 404
        assert resp.json()["error"] == "no profile found"


class TestCommand:
    @pytest.mark.asyncio
    async def test_command_returns_valid_task_id(self, async_client: AsyncClient):
        resp = await async_client.post("/command", json={"text_command": "hello"})
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]
        assert isinstance(task_id, str) and len(task_id) > 0

    @pytest.mark.asyncio
    async def test_task_lifecycle(self, async_client: AsyncClient):
        resp = await async_client.post("/command", json={"text_command": "test"})
        task_id = resp.json()["task_id"]

        states_seen = []
        for _ in range(30):
            resp = await async_client.get(f"/status/{task_id}")
            data = resp.json()
            states_seen.append(data["status"])
            if data["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        assert states_seen[-1] == "completed"
        assert data["result"] is not None
        assert len(data["logs"]) > 0

    @pytest.mark.asyncio
    async def test_status_not_found(self, async_client: AsyncClient):
        resp = await async_client.get("/status/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["error"] == "task not found"


class TestWebSocket:
    def test_receives_log_messages_and_done(self):
        client = TestClient(app)
        resp = client.post("/command", json={"text_command": "hello"})
        task_id = resp.json()["task_id"]

        with client.websocket_connect(f"/ws/status/{task_id}") as ws:
            messages = []
            from starlette.websockets import WebSocketDisconnect
            try:
                while True:
                    messages.append(ws.receive_text())
            except WebSocketDisconnect:
                pass

            assert len(messages) >= 3
            assert messages[0] == "Started"
            assert "Finished" in messages

            done_msgs = [m for m in messages if '"type":"done"' in m]
            assert len(done_msgs) == 1
            done = json.loads(done_msgs[0])
            assert done["status"] == "completed"

    def test_websocket_task_not_found(self):
        client = TestClient(app)
        with client.websocket_connect("/ws/status/invalid_id") as ws:
            msg = ws.receive_json()
            assert msg["error"] == "task not found"


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_missing_text_command(self, async_client: AsyncClient):
        resp = await async_client.post("/command", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_command_input_type(self, async_client: AsyncClient):
        resp = await async_client.post("/command", json={"text_command": 12345})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_profile_missing_name(self, async_client: AsyncClient):
        resp = await async_client.post("/user/profile", json={"email": "a@b.com"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_profile_missing_email(self, async_client: AsyncClient):
        resp = await async_client.post("/user/profile", json={"name": "Test"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_profile_body(self, async_client: AsyncClient):
        resp = await async_client.post("/user/profile", json={})
        assert resp.status_code == 422
