# ChromaDB/RAG setup
"""
Persistent semantic memory store backed by ChromaDB.

Stores free-text interaction summaries (with metadata) and supports
similarity search over them, so agent nodes can retrieve relevant past
context (e.g. "what deadlines has the user mentioned before?") rather
than relying solely on the flat key/value ProfileManager.
"""

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

import chromadb
from chromadb.errors import ChromaError

logger = logging.getLogger(__name__)

_DEFAULT_PERSIST_DIR = Path("data/chroma")
_COLLECTION_NAME = "user_history"


class VectorStoreError(Exception):
    """Raised on unrecoverable vector store failures."""


class VectorStore:
    """
    Thin wrapper around a persistent ChromaDB collection ("user_history")
    for storing and semantically retrieving past interaction memories.
    """

    def __init__(
        self,
        persist_dir: Path | str = _DEFAULT_PERSIST_DIR,
        collection_name: str = _COLLECTION_NAME,
    ) -> None:
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._collection_name = collection_name

        try:
            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"description": "Semantic memory of user interactions"},
            )
        except ChromaError as exc:
            logger.error("Failed to initialize ChromaDB at %s: %s", persist_dir, exc)
            raise VectorStoreError(f"Failed to initialize vector store: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    def add_memory(
        self,
        text: str,
        metadata: Optional[dict[str, Any]] = None,
        memory_id: Optional[str] = None,
    ) -> str:
        """
        Embed and store `text` in the "user_history" collection.

        Args:
            text: The interaction/memory content to store.
            metadata: Arbitrary metadata (e.g. {"source": "chat",
                "timestamp": "...", "session_id": "..."}). Chroma requires
                metadata values to be str/int/float/bool, so non-primitive
                values are coerced to strings.
            memory_id: Optional explicit ID; a UUID4 is generated if omitted.

        Returns:
            The ID under which the memory was stored.

        Raises:
            VectorStoreError: If the text is empty or the write fails.
        """
        if not text or not text.strip():
            raise VectorStoreError("Cannot store an empty memory text.")

        doc_id = memory_id or str(uuid.uuid4())
        safe_metadata = self._sanitize_metadata(metadata or {})

        try:
            self._collection.add(
                ids=[doc_id],
                documents=[text],
                metadatas=[safe_metadata],
            )
        except ChromaError as exc:
            logger.error("Failed to add memory to vector store: %s", exc)
            raise VectorStoreError(f"Failed to add memory: {exc}") from exc

        return doc_id

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def query_memory(
        self,
        query: str,
        n_results: int = 3,
        where: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve the `n_results` most semantically similar memories to
        `query`.

        Args:
            query: Natural-language query text.
            n_results: Max number of results to return.
            where: Optional Chroma metadata filter, e.g. {"source": "chat"}.

        Returns:
            A list of dicts, each: {"id", "text", "metadata", "distance"},
            ordered from most to least similar. Empty list if the
            collection has no documents yet.

        Raises:
            VectorStoreError: If the query fails or `query` is empty.
        """
        if not query or not query.strip():
            raise VectorStoreError("Query text cannot be empty.")

        try:
            count = self._collection.count()
        except ChromaError as exc:
            logger.error("Failed to count vector store collection: %s", exc)
            raise VectorStoreError(f"Failed to query vector store: {exc}") from exc

        if count == 0:
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results, count),
                where=where,
            )
        except ChromaError as exc:
            logger.error("Failed to query vector store: %s", exc)
            raise VectorStoreError(f"Failed to query vector store: {exc}") from exc

        return self._format_results(results)

    # ------------------------------------------------------------------ #
    # Maintenance
    # ------------------------------------------------------------------ #

    def delete_memory(self, memory_id: str) -> None:
        """Delete a single memory by its ID."""
        try:
            self._collection.delete(ids=[memory_id])
        except ChromaError as exc:
            logger.error("Failed to delete memory %s: %s", memory_id, exc)
            raise VectorStoreError(f"Failed to delete memory '{memory_id}': {exc}") from exc

    def count(self) -> int:
        """Return the number of memories currently stored."""
        try:
            return self._collection.count()
        except ChromaError as exc:
            raise VectorStoreError(f"Failed to count memories: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        """Coerce metadata values to Chroma-supported primitive types."""
        clean: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean[key] = value if value is not None else ""
            else:
                clean[key] = str(value)
        return clean

    @staticmethod
    def _format_results(results: dict[str, Any]) -> list[dict[str, Any]]:
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        return [
            {
                "id": ids[i],
                "text": documents[i],
                "metadata": metadatas[i],
                "distance": distances[i],
            }
            for i in range(len(ids))
        ]