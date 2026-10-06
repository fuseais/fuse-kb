import json

import pytest

from fuse_kb import FuseKBError, KBLibrary, Toolkit
from fuse_kb.cli import main

from conftest import EchoLLM, ReverseReranker, ToyEmbedder


def test_library_discovers_kbs_and_blocks_other_paths(kb_dir):
    lib = KBLibrary(kb_dir, embedder=None)
    assert lib.names == ["benefits", "handbook"]
    with pytest.raises(FuseKBError, match="No knowledge base named"):
        lib.get("../handbook")
    with pytest.raises(FuseKBError, match="Several"):
        lib.get()
    assert {r["name"] for r in lib.list()} == {"benefits", "handbook"}


def test_library_registers_other_backends(kb_dir):
    lib = KBLibrary(kb_dir, embedder=None)
    remote = lib.get("handbook")          # any object with the backend methods
    lib.add("enterprise", remote)
    assert "enterprise" in lib.names
    out = Toolkit(lib).call("kb_research", {"kb": "enterprise", "question": "vacation"})
    assert out["hits"]


def test_tool_definitions_follow_configuration(kb_dir):
    plain = Toolkit(KBLibrary(kb_dir, embedder=None)).definitions()
    names = [t["name"] for t in plain]
    assert "kb_answer" not in names
    search = next(t for t in plain if t["name"] == "kb_search")["input_schema"]
    assert "fusion" not in search["properties"] and "hyde" not in search["properties"]
    assert search["properties"]["kb"]["enum"] == ["benefits", "handbook"]

    full = Toolkit(KBLibrary(kb_dir, embedder=ToyEmbedder(),
                             reranker=ReverseReranker(), llm=EchoLLM())).definitions()
    names = [t["name"] for t in full]
    assert "kb_answer" in names
    search = next(t for t in full if t["name"] == "kb_search")["input_schema"]
    assert {"fusion", "rrf_k", "hyde"} <= set(search["properties"])


def test_single_kb_makes_name_optional(kb_path):
    tk = Toolkit(KBLibrary(kb_path, embedder=None))
    research = next(t for t in tk.definitions() if t["name"] == "kb_research")
    assert research["input_schema"]["required"] == ["question"]
    assert tk.call("kb_research", {"question": "parental leave"})["hits"]


def test_dispatch_results_are_json_and_errors_are_returned(kb_dir):
    tk = Toolkit(KBLibrary(kb_dir, embedder=None), max_text_chars=20)
    out = json.loads(tk.call_json("kb_search", {"kb": "handbook", "mode": "lexical",
                                                "query": "W-4 withholding"}))
    assert out["hits"][0]["ref"] == 1 and out["hits"][0]["chunk_text"].endswith("…")
    assert "error" in tk.call("kb_search", {"kb": "nope", "mode": "lexical", "query": "x"})
    assert "error" in tk.call("kb_read_pages", {"kb": "handbook", "document_id": "d1",
                                                "page_start": 1, "page_end": 9})
    assert "error" in tk.call("not_a_tool", {})
    docs = tk.call("kb_documents", {"kb": "handbook"})["documents"]
    assert len(docs) == 3
    openai = tk.openai_tools()
    assert openai[0]["type"] == "function" and "parameters" in openai[0]["function"]


def test_mcp_server_registers_tools(kb_dir):
    pytest.importorskip("mcp")
    import asyncio
    from fuse_kb.mcp_server import build_server
    server = build_server(KBLibrary(kb_dir, embedder=None))
    tools = asyncio.run(server.list_tools())
    tools = tools.tools if hasattr(tools, "tools") else tools
    names = {t.name for t in tools}
    assert {"kb_list", "kb_research", "kb_search", "kb_read_pages", "kb_documents"} <= names
    assert "kb_answer" not in names
    research = next(t for t in tools if t.name == "kb_research")
    schema = getattr(research, "input_schema", None) or research.inputSchema
    assert "fusion" not in schema["properties"]          # no reranker configured
    assert "benefits" in json.dumps(schema["properties"]["kb"])   # names offered

    full = build_server(KBLibrary(kb_dir, embedder=None, reranker=ReverseReranker()))
    tools = asyncio.run(full.list_tools())
    research = next(t for t in (tools.tools if hasattr(tools, "tools") else tools)
                    if t.name == "kb_research")
    schema = getattr(research, "input_schema", None) or research.inputSchema
    assert "fusion" in schema["properties"]


def test_cli(kb_dir, capsys):
    assert main(["list", "--path", kb_dir]) == 0
    assert "handbook: 3 documents" in capsys.readouterr().out
    assert main(["search", "handbook", "W-4", "--path", kb_dir, "--mode", "lexical",
                 "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["hits"][0]["document_id"] == "d2"
    assert main(["search", "handbook", "--path", kb_dir, "--mode", "filter",
                 "--filter", "page_number=2-3", "--filter", "document_id=d1"]) == 0
    assert "2 hits" in capsys.readouterr().out
    assert main(["info", "nope", "--path", kb_dir]) == 1
    assert main(["skill"]) == 0
    assert "name: fuse-kb" in capsys.readouterr().out
