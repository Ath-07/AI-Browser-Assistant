from pydantic import BaseModel, Field
from typing import Optional


class UserProfile(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    address: Optional[str] = ""
    resume_text: Optional[str] = ""


class Task(BaseModel):
    task_id: str
    status: str = "pending"
    command: str = ""
    result: Optional[str] = None
    logs: list[str] = Field(default_factory=list)


class AgentAction(BaseModel):
    action: str
    parameters: dict = Field(default_factory=dict)


class CommandRequest(BaseModel):
    text_command: str
