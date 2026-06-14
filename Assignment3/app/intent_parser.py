import json
import google.generativeai as genai
from dotenv import load_dotenv
import os

from app.prompts import SYSTEM_PROMPT

load_dotenv()

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash"
)


def parse_intent(user_command: str) -> dict:
    """
    Convert natural language into browser actions.
    """

    prompt = f"""
{SYSTEM_PROMPT}

User Command:
{user_command}

JSON Output:
"""

    response = model.generate_content(prompt)

    try:
        text = response.text.strip()

        if text.startswith("```json"):
            text = text.replace("```json", "")
            text = text.replace("```", "")

        return json.loads(text)

    except Exception:
        return {
            "action": "unknown",
            "target_url": None,
            "data": {},
            "steps": [],
            "clarification_needed": True,
            "question": "I could not understand the command."
        }