from typing import Optional, Dict, List
from pydantic import BaseModel


class IntentSchema(BaseModel):
    action: str
    target_url: Optional[str] = None
    data: Dict = {}
    steps: List[str] = []
    clarification_needed: bool = False
    question: Optional[str] = None