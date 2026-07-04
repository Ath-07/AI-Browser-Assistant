import asyncio
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import aiosqlite

from database import init_db, get_db, get_profile, upsert_profile
from models import CommandRequest, UserProfile
from agent_runner import task_store, run_agent, _generate_task_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Assignment 6", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/command")
async def create_command(
    body: CommandRequest,
    background_tasks: BackgroundTasks,
):
    task_id = _generate_task_id()
    task_store[task_id] = {
        "status": "pending",
        "result": None,
        "logs": [],
    }
    background_tasks.add_task(run_agent, task_id, body.text_command)
    return JSONResponse(content={"task_id": task_id}, status_code=202)


@app.get("/status/{task_id}")
async def get_status(task_id: str):
    entry = task_store.get(task_id)
    if entry is None:
        return JSONResponse(content={"error": "task not found"}, status_code=404)
    return {
        "task_id": task_id,
        "status": entry["status"],
        "result": entry["result"],
        "logs": entry["logs"],
    }


@app.get("/user/profile")
async def get_user_profile(db: aiosqlite.Connection = Depends(get_db)):
    profile = await get_profile(db)
    if profile is None:
        return JSONResponse(content={"error": "no profile found"}, status_code=404)
    return {
        "name": profile["name"],
        "email": profile["email"],
        "phone": profile["phone"],
        "address": profile["address"],
        "resume_text": profile["resume_text"],
    }


@app.post("/user/profile")
async def update_user_profile(
    body: UserProfile,
    db: aiosqlite.Connection = Depends(get_db),
):
    await upsert_profile(db, body.model_dump())
    return {"message": "profile updated", **body.model_dump()}


@app.websocket("/ws/status/{task_id}")
async def ws_status(websocket: WebSocket, task_id: str):
    await websocket.accept()
    entry = task_store.get(task_id)
    if entry is None:
        await websocket.send_json({"error": "task not found"})
        await websocket.close()
        return

    last_log_count = 0
    try:
        while True:
            current = task_store.get(task_id)
            if current is None:
                break

            logs = current.get("logs", [])
            while last_log_count < len(logs):
                await websocket.send_text(logs[last_log_count])
                last_log_count += 1

            if current["status"] in ("completed", "failed"):
                await websocket.send_json({
                    "type": "done",
                    "status": current["status"],
                    "result": current["result"],
                })
                await websocket.close()
                break

            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    uvicorn.run(app, host="0.0.0.0", port=8000)
