"""The interface every knowledge-base backend implements.

The agent tools, MCP server, and CLI talk only to this interface. A local
``.sqlite`` file (:class:`fuse_kb.KnowledgeBase`) is one backend; a hosted
or enterprise search service can be another. Register any object with these
methods in a :class:`fuse_kb.KBLibrary` and the same tools work against it,
so agents move from a downloaded file to a hosted backend without changes.

Results use the same :class:`fuse_kb.Hit` and :class:`fuse_kb.SearchResult`
shapes whatever the backend, so citations and scores read the same way.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from .kb import SearchResult


@runtime_checkable
class KBBackend(Protocol):
    name: str

    def info(self) -> dict: ...

    def documents(self, limit: int = 500,
                  name_contains: Optional[str] = None) -> list[dict]: ...

    def search(self, query: str = "", *, mode: str = "hybrid", k: int = 10,
               filters: Optional[dict] = None, rerank: bool = True,
               fusion: str = "rerank", rrf_k: int = 60, hyde: bool = False,
               phrase: bool = False, raw_match: bool = False) -> SearchResult: ...

    def research(self, question: str, *, k: int = 10,
                 filters: Optional[dict] = None, fusion: str = "rerank",
                 rrf_k: int = 60) -> SearchResult: ...

    def pages(self, *, page_start: int, page_end: Optional[int] = None,
              document_id: Optional[str] = None,
              document_name: Optional[str] = None) -> SearchResult: ...

    def answer(self, question: str, *, k: int = 8,
               filters: Optional[dict] = None) -> dict: ...

    def close(self) -> None: ...
