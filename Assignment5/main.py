import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

import aiosqlite

from database import init_db, get_db, get_profile, upsert_profile
from models import CommandRequest, UserProfile, TaskStatus
from agent_runner import task_store, run_agent, _generate_task_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Assignment 5", lifespan=lifespan)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


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


@app.get("/status/{task_id}", response_model=TaskStatus)
async def get_status(task_id: str):
    entry = task_store.get(task_id)
    if entry is None:
        return JSONResponse(content={"error": "task not found"}, status_code=404)
    return TaskStatus(
        task_id=task_id,
        status=entry["status"],
        result=entry["result"],
        logs=entry["logs"],
    )


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

            await asyncio.sleep(0.1)

            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
