"""MCP server: expose a folder of KBs to Claude Desktop, Claude Code, and any
other Model Context Protocol client.

    fuse-kb mcp --path ./kbs                  # stdio, for desktop clients
    fuse-kb mcp --path ./kbs --transport streamable-http --port 8765
"""

import inspect
from typing import Any, Literal, Optional

from .errors import FuseKBError
from .library import KBLibrary
from .tools import Toolkit

INSTRUCTIONS = """Searchable knowledge bases built from document collections.
Start with kb_list if you don't know which knowledge base to use, then
kb_research for questions. Cite passages by their ref number, document name,
and page. Use kb_read_pages only when a passage is cut off mid-table,
mid-list, or mid-code. If results include notes, they explain fallbacks
(for example, vector search being unavailable)."""


def build_server(library: KBLibrary, *, max_text_chars: Optional[int] = None):
    try:
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server
        except ImportError as exc:
            raise FuseKBError(
                "The MCP server needs the 'mcp' package: "
                "pip install 'fuse-kb[mcp]'") from exc

    toolkit = Toolkit(library, max_text_chars=max_text_chars)
    server = Server("fuse-kb", instructions=INSTRUCTIONS)
    specs = {t["name"]: t for t in toolkit.definitions()}

    def register(fn):
        """Register ``fn`` with a signature trimmed to the tool definition,
        so MCP clients see the same options as the Python toolkit."""
        spec = specs.get(fn.__name__)
        if spec is None:
            return
        allowed = set(spec["input_schema"].get("properties", {}))
        sig = inspect.signature(fn)
        params = []
        for p in sig.parameters.values():
            if p.name not in allowed:
                continue
            if p.name == "kb" and library.names:
                p = p.replace(annotation=Optional[Literal[tuple(library.names)]])
            params.append(p)
        fn.__signature__ = sig.replace(parameters=params)
        server.tool(name=spec["name"], description=spec["description"])(fn)

    # Explicit signatures so MCP clients get a typed input schema.
    def kb_list() -> dict:
        return toolkit.call("kb_list", {})

    def kb_research(question: str, kb: Optional[str] = None, k: int = 10,
                    filters: Optional[dict[str, Any]] = None,
                    fusion: Optional[str] = None,
                    rrf_k: Optional[int] = None) -> dict:
        return toolkit.call("kb_research", dict(
            question=question, kb=kb, k=k, filters=filters, fusion=fusion,
            rrf_k=rrf_k))

    def kb_search(mode: str, query: str = "", kb: Optional[str] = None,
                  k: int = 10, filters: Optional[dict[str, Any]] = None,
                  phrase: bool = False, fusion: Optional[str] = None,
                  rrf_k: Optional[int] = None, hyde: bool = False) -> dict:
        return toolkit.call("kb_search", dict(
            mode=mode, query=query, kb=kb, k=k, filters=filters, phrase=phrase,
            fusion=fusion, rrf_k=rrf_k, hyde=hyde))

    def kb_read_pages(document_id: str, page_start: int,
                      page_end: Optional[int] = None,
                      kb: Optional[str] = None) -> dict:
        return toolkit.call("kb_read_pages", dict(
            document_id=document_id, page_start=page_start, page_end=page_end,
            kb=kb))

    def kb_documents(kb: Optional[str] = None,
                     name_contains: Optional[str] = None) -> dict:
        return toolkit.call("kb_documents", dict(kb=kb, name_contains=name_contains))

    def kb_answer(question: str, kb: Optional[str] = None,
                  filters: Optional[dict[str, Any]] = None) -> dict:
        return toolkit.call("kb_answer", dict(question=question, kb=kb,
                                              filters=filters))

    for fn in (kb_list, kb_research, kb_search, kb_read_pages, kb_documents,
               kb_answer):
        register(fn)
    return server


def serve(library: KBLibrary, transport: str = "stdio",
          host: str = "127.0.0.1", port: int = 8765, **kwargs) -> None:
    server = build_server(library, **kwargs)
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=transport, host=host, port=port)
