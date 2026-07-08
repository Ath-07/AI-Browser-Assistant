# Profile/Resume storage management
"""
Lightweight JSON-backed user profile store.

Used for durable key/value facts about the user (preferences, deadlines,
recurring settings, etc.) that agent nodes need to read/write across
sessions, distinct from the semantic vector memory in vector_store.py.
"""

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_PROFILE_PATH = Path("data/profile.json")


class ProfileManagerError(Exception):
    """Raised on unrecoverable read/write failures against the profile store."""


class ProfileManager:
    """
    Reads and writes a flat JSON profile file at `data/profile.json`.

    Thread-safe for use within a single process (guarded by a lock);
    writes are atomic (write-to-temp + os.replace) to avoid corrupting
    the file if the process is interrupted mid-write.
    """

    def __init__(self, profile_path: Path | str = _DEFAULT_PROFILE_PATH) -> None:
        self._path = Path(profile_path)
        self._lock = threading.Lock()
        self._ensure_file_exists()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _ensure_file_exists(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict[str, Any]:
        try:
            with self._path.open("r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            logger.error("Profile file at %s is corrupted: %s", self._path, exc)
            raise ProfileManagerError(
                f"Profile file at '{self._path}' contains invalid JSON."
            ) from exc

    def _write(self, data: dict[str, Any]) -> None:
        """
        Atomically write `data` to the profile path: write to a temp file
        in the same directory, then os.replace() it into place. Avoids
        leaving a half-written/corrupt profile.json if interrupted.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except OSError as exc:
            logger.error("Failed to write profile to %s: %s", self._path, exc)
            raise ProfileManagerError(f"Failed to write profile: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_value(self, key: str, default: Optional[Any] = None) -> Any:
        """
        Return the value stored under `key`, or `default` if not present.
        Supports dotted-path keys (e.g. "preferences.timezone") for
        nested lookups.
        """
        with self._lock:
            data = self._read()
        return self._resolve_dotted(data, key, default)

    def update_value(self, key: str, value: Any) -> None:
        """
        Set `key` to `value` and persist immediately. Supports dotted-path
        keys, creating intermediate dicts as needed.
        """
        with self._lock:
            data = self._read()
            self._set_dotted(data, key, value)
            self._write(data)

    def get_full_profile(self) -> dict[str, Any]:
        """Return a copy of the entire profile as a dict."""
        with self._lock:
            return self._read()

    def delete_value(self, key: str) -> bool:
        """
        Remove `key` from the profile if present. Returns True if a value
        was deleted, False if the key didn't exist.
        """
        with self._lock:
            data = self._read()
            parts = key.split(".")
            node = data
            for part in parts[:-1]:
                if not isinstance(node, dict) or part not in node:
                    return False
                node = node[part]
            if isinstance(node, dict) and parts[-1] in node:
                del node[parts[-1]]
                self._write(data)
                return True
            return False

    # ------------------------------------------------------------------ #
    # Dotted-path helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_dotted(data: dict[str, Any], key: str, default: Any) -> Any:
        node: Any = data
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    @staticmethod
    def _set_dotted(data: dict[str, Any], key: str, value: Any) -> None:
        parts = key.split(".")
        node = data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value