"""fuse-kb: search Fuse knowledge-base files from your own agents and apps.

    from fuse_kb import KnowledgeBase

    with KnowledgeBase("kbs/handbook.sqlite") as kb:
        for hit in kb.search("parental leave policy").hits:
            print(hit.label, hit.chunk_text[:200])
"""
__version__ = "0.1.0"

from .errors import EmbedderUnavailable, FuseKBError, KBFormatError, ProviderError
from .hit import Hit
from .kb import NO_ANSWER, KnowledgeBase, SearchResult
from .library import KBLibrary
from .providers import Embedder, LLM, Reranker
from .tools import Toolkit
from .backend import KBBackend

__all__ = [
    "KnowledgeBase", "KBLibrary", "KBBackend", "SearchResult", "Hit", "Toolkit",
    "Embedder", "Reranker", "LLM",
    "FuseKBError", "KBFormatError", "ProviderError", "EmbedderUnavailable",
    "NO_ANSWER", "__version__",
]
