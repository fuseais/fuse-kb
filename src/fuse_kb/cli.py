"""fuse-kb command line."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from importlib import resources

from . import __version__
from .encrypted import is_encrypted
from .errors import FuseKBError
from .kb import MODES, KnowledgeBase
from .library import ENV_PATH, KBLibrary


def _providers(args) -> dict:
    return dict(
        embedder=args.embedder or "auto",
        reranker=args.reranker or os.environ.get("FUSE_KB_RERANKER") or None,
        llm=args.llm or os.environ.get("FUSE_KB_LLM") or None,
        region=args.region,
        pgp_key_file=getattr(args, "pgp_key_file", None),
    )


def _open(args) -> KnowledgeBase:
    """KB argument: a path to a .sqlite file, or a name found on --path."""
    target = args.kb
    if target and (target.endswith(".sqlite") or is_encrypted(target)
                   or os.path.isfile(target)):
        return KnowledgeBase(target, **_providers(args))
    return KBLibrary(args.path, **_providers(args)).get(target)


def _filters(items) -> dict:
    out: dict = {}
    for item in items or []:
        col, sep, val = item.partition("=")
        if not sep:
            raise SystemExit(f"--filter must look like column=value, got {item!r}")
        if col in ("page_number", "total_pages") and "-" in val:
            lo, hi = val.split("-", 1)
            out[col] = (int(lo), int(hi))
        elif "," in val:
            out[col] = val.split(",")
        else:
            out[col] = int(val) if col in ("page_number", "total_pages") else val
    return out


def _print_result(result: dict, show_text: bool) -> None:
    for note in result.get("notes", []):
        print(f"note: {note}")
    if result.get("strategy"):
        print(f"strategy: {result['strategy']}")
    print(f"{len(result['hits'])} hits · {result['elapsed_ms']:.0f} ms\n")
    for h in result["hits"]:
        page = f" p.{h['page_number']}" if h.get("page_number") is not None else ""
        print(f"[{h['ref']}] {h.get('document_name', '?')}{page}")
        scores = [f"{key}={h[key]:.4g}" for key in (
            "score_final", "score_rerank", "score_rrf", "score_dense",
            "score_lexical") if h.get(key) is not None]
        if h.get("rank_rrf") is not None and h.get("rank_rerank") is not None:
            scores.append(f"rrf #{h['rank_rrf'] + 1} → rerank #{h['rank_rerank'] + 1}")
        if scores:
            print("    " + "  ".join(scores))
        text = " ".join((h.get("chunk_text") or "").split())
        print("    " + (text if show_text else text[:240] + ("…" if len(text) > 240 else "")))
        print()


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--path", default=None,
                        help=f"Folders or files holding KBs (default: ${ENV_PATH} or ./kbs)")
    common.add_argument("--embedder", help="Override the query embedder spec")
    common.add_argument("--reranker", help="cohere | cross-encoder:<model> (env FUSE_KB_RERANKER)")
    common.add_argument("--llm", help="anthropic[:<model>] | bedrock:<id> | ollama:<model> | openai:<model> (env FUSE_KB_LLM)")
    common.add_argument("--region", help="AWS region for Bedrock providers")
    common.add_argument("--pgp-key-file", help="Private key for encrypted .sqlite.gpg "
                        "files (env FUSE_KB_PGP_KEY_FILE). Passphrase: env "
                        "FUSE_KB_PGP_PASSPHRASE. Default: your GnuPG keyring.")
    common.add_argument("--json", action="store_true", help="Print JSON")

    p = argparse.ArgumentParser(prog="fuse-kb", description="Search Fuse knowledge-base files.")
    p.add_argument("--version", action="version", version=f"fuse-kb {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", parents=[common], help="List KBs on --path")

    s = sub.add_parser("info", parents=[common], help="Show what a KB contains and needs")
    s.add_argument("kb", help="KB name or .sqlite path")

    s = sub.add_parser("docs", parents=[common], help="List a KB's documents")
    s.add_argument("kb")
    s.add_argument("--contains", help="Only documents whose name contains this")

    for name, help_text in (("search", "Search with one method"),
                            ("research", "Search with automatic fallbacks")):
        s = sub.add_parser(name, parents=[common], help=help_text)
        s.add_argument("kb")
        s.add_argument("query", nargs="?", default="")
        s.add_argument("-k", type=int, default=10)
        s.add_argument("--filter", action="append", metavar="COL=VALUE",
                       help="Repeatable. Lists with commas, pages as 3-7.")
        s.add_argument("--fusion", choices=["rerank", "rrf"], default="rerank")
        s.add_argument("--rrf-k", type=int, default=60)
        s.add_argument("--show-text", action="store_true")
        if name == "search":
            s.add_argument("--mode", choices=MODES, default="hybrid")
            s.add_argument("--no-rerank", action="store_true")
            s.add_argument("--hyde", action="store_true", help="Needs --llm")
            s.add_argument("--phrase", action="store_true",
                           help="Lexical: match the query as an exact phrase")

    s = sub.add_parser("answer", parents=[common], help="Answer from the KB (needs --llm)")
    s.add_argument("kb")
    s.add_argument("question")

    s = sub.add_parser("pages", parents=[common], help="Read pages of one document")
    s.add_argument("kb")
    s.add_argument("--document-id", required=True)
    s.add_argument("--pages", required=True, metavar="N or N-M")
    s.add_argument("--show-text", action="store_true")

    s = sub.add_parser("mcp", parents=[common], help="Run the MCP server")
    s.add_argument("--transport", choices=["stdio", "streamable-http", "sse"],
                   default="stdio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--max-text-chars", type=int)

    s = sub.add_parser("skill", help="Print or install the agent skill (SKILL.md)")
    s.add_argument("--install", metavar="DIR",
                   help="Copy into DIR/fuse-kb/, e.g. ~/.claude/skills")

    args = p.parse_args(argv)
    try:
        return _run(args)
    except (FuseKBError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(args) -> int:
    out = lambda obj: print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))  # noqa: E731

    if args.cmd == "skill":
        src = resources.files("fuse_kb").joinpath("skill/SKILL.md")
        if args.install:
            dest = os.path.join(os.path.expanduser(args.install), "fuse-kb")
            os.makedirs(dest, exist_ok=True)
            with resources.as_file(src) as f:
                shutil.copy(f, os.path.join(dest, "SKILL.md"))
            print(f"Installed {os.path.join(dest, 'SKILL.md')}")
        else:
            print(src.read_text(encoding="utf-8"))
        return 0

    if args.cmd == "list":
        rows = KBLibrary(args.path, **_providers(args)).list()
        if args.json:
            out(rows)
        elif not rows:
            print(f"No KBs found. Put .sqlite files in ./kbs or set ${ENV_PATH}.")
        for r in rows if not args.json else []:
            desc = f" — {r['description']}" if r.get("description") else ""
            print(f"{r['name']}: {r.get('documents')} documents, "
                  f"{r.get('chunks')} chunks, embedder {r.get('embedder')}{desc}")
        return 0

    if args.cmd == "mcp":
        from .mcp_server import serve
        serve(KBLibrary(args.path, **_providers(args)), transport=args.transport,
              host=args.host, port=args.port, max_text_chars=args.max_text_chars)
        return 0

    kb = _open(args)
    if args.cmd == "info":
        info = kb.info()
        if args.json:
            out(info)
        else:
            for key, value in info.items():
                if value is not None:
                    print(f"{key:12} {value}")
        return 0
    if args.cmd == "docs":
        docs = kb.documents(name_contains=args.contains)
        if args.json:
            out(docs)
        for d in docs if not args.json else []:
            print(f"{d['document_id']}  {d['document_name']}  "
                  f"({d['total_pages']} pages, {d['chunks']} chunks)")
        return 0
    if args.cmd == "answer":
        result = kb.answer(args.question)
        if args.json:
            out(result)
        else:
            print(result["answer"])
            for h in result["hits"]:
                page = f" p.{h['page_number']}" if h.get("page_number") is not None else ""
                print(f"  [{h['ref']}] {h.get('document_name')}{page}")
        return 0
    if args.cmd == "pages":
        first, _, last = args.pages.partition("-")
        result = kb.pages(document_id=args.document_id, page_start=int(first),
                          page_end=int(last or first)).to_dict()
    elif args.cmd == "research":
        result = kb.research(args.query, k=args.k, filters=_filters(args.filter),
                             fusion=args.fusion, rrf_k=args.rrf_k).to_dict()
    else:
        result = kb.search(args.query, mode=args.mode, k=args.k,
                           filters=_filters(args.filter), rerank=not args.no_rerank,
                           fusion=args.fusion, rrf_k=args.rrf_k, hyde=args.hyde,
                           phrase=args.phrase).to_dict()
    if args.json:
        out(result)
    else:
        _print_result(result, args.show_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
