# LLM API client wrapper
"""
Centralized LLM client wrapper around LangChain's ChatGoogleGenerativeAI.
"""

from functools import lru_cache
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from src.utils.config import settings


class LLMClient:
    """
    Thin wrapper that owns LLM instantiation so agent/graph code doesn't
    need to know provider-specific construction details.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        temperature: float = 0,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._client: ChatGoogleGenerativeAI = ChatGoogleGenerativeAI(
            model=self._model,
            temperature=self._temperature,
            google_api_key=settings.GEMINI_API_KEY,
        )

    def get_client(self) -> Any:
        """
        Return the configured chat model instance.

        The returned object supports LangChain's `.bind_tools(...) /
        tool-calling interface directly, so it can be passed straight
        into LangGraph nodes or agent executors that expect a
        tool-calling-capable chat model.
        """
        return self._client


@lru_cache(maxsize=1)
def get_default_llm_client() -> LLMClient:
    """
    Cached factory so repeated imports across the codebase (e.g. multiple
    LangGraph nodes) share a single underlying chat model instance instead
    of re-instantiating on every call.
    """
    return LLMClient()