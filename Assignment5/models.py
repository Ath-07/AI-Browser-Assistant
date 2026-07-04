from pydantic import BaseModel
from typing import Optional


class CommandRequest(BaseModel):
    text_command: str


class UserProfile(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    address: Optional[str] = ""
    resume_text: Optional[str] = ""


class TaskStatus(BaseModel):
    task_id: str
    status: str
    result: Optional[str] = None
    logs: list[str] = []
