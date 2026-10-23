"""
Content-addressed case cache.

The server is *soft*-stateful: a case's text lives in RAM (LRU 20, 2 h TTL, never on disk) keyed by the sha256 of the
text the client holds, and every derived artifact (profile, precedents, graph, outcome, document index) is cached under
a deterministic key. Everything here is recomputable from the text, so a Space restart only costs a re-PUT (the client
handles the 409 `case_unknown` transparently).
"""

import asyncio
import hashlib
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, TypeVar

from services.agent import doc_index
from utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
MAX_CASES = 20
TTL_SECONDS = 2 * 60 * 60


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def artifact_key(*parts: Any) -> str:
    """Deterministic short key for an artifact from the things it depends on."""
    return hashlib.sha1("\x1f".join(repr(p) for p in parts).encode("utf-8")).hexdigest()[:16]


class CaseWorkspace:
    def __init__(self, sha: str, text: str, title: Optional[str], filename: Optional[str]) -> None:
        self.sha = sha
        self.text = text
        self.title = title or ""
        self.filename = filename
        self.touched = time.monotonic()
        self._artifacts: Dict[str, Any] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def get_or_compute(self, key: str, compute: Callable[[], Awaitable[T]]) -> Tuple[T, bool]:
        """Singleflight: concurrent callers for one key share a single computation. Returns (value, was_cached)."""
        if key in self._artifacts:
            return self._artifacts[key], True
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._artifacts:
                return self._artifacts[key], True
            value = await compute()
            self._artifacts[key] = value
            return value, False

    def peek(self, key: str) -> Any:
        return self._artifacts.get(key)

    async def ensure_doc_index(self) -> doc_index.DocIndex:
        value, _ = await self.get_or_compute("doc_index", lambda: doc_index.build_index(self.text))
        return value


class WorkspaceStore:
    def __init__(self) -> None:
        self._cases: "OrderedDict[str, CaseWorkspace]" = OrderedDict()

    def _evict(self) -> None:
        now = time.monotonic()
        for sha in [s for s, w in self._cases.items() if now - w.touched > TTL_SECONDS]:
            self._cases.pop(sha, None)
        while len(self._cases) > MAX_CASES:
            self._cases.popitem(last=False)

    def put(self, text: str, title: Optional[str] = None, filename: Optional[str] = None) -> CaseWorkspace:
        sha = sha256_text(text)
        ws = self._cases.get(sha)
        if ws is None:
            ws = CaseWorkspace(sha, text, title, filename)
            self._cases[sha] = ws
        else:
            ws.title = title or ws.title
            ws.filename = filename or ws.filename
        ws.touched = time.monotonic()
        self._cases.move_to_end(sha)
        self._evict()
        return ws

    def get(self, sha: str) -> Optional[CaseWorkspace]:
        self._evict()
        ws = self._cases.get(sha)
        if ws is not None:
            ws.touched = time.monotonic()
            self._cases.move_to_end(sha)
        return ws

    def clear(self) -> None:
        self._cases.clear()


workspaces = WorkspaceStore()
