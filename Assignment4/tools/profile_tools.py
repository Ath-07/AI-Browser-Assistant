from langchain_core.tools import tool # type: ignore
import json


@tool
def get_user_profile() -> str:
    """Return the stored user profile."""
    
    with open("data/user_profile.json") as f:
        return json.dumps(json.load(f), indent=2)