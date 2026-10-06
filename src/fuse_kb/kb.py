"""KnowledgeBase: open one KB file and search it."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from . import search as S
from .encrypted import decrypt, is_encrypted, kb_name
from .errors import EmbedderUnavailable, FuseKBError, ProviderError
from .hit import Hit
from .providers import (Embedder, LLM, Reranker, resolve_embedder, resolve_llm,
                        resolve_reranker, spec_from_meta)
from .providers.embedders import env_embedder_spec

MODES = ("hybrid", "lexical", "dense", "filter")
NO_ANSWER = "I cannot find that information in the knowledge base."
MAX_PAGE_SPAN = 6
DEFAULT_STRONG_SCORE = 0.30

_HYDE_SYSTEM = (
    "Write a concise hypothetical paragraph that would answer the following "
    "question, as if it were a passage from authoritative documentation on "
    "this topic. Use natural domain vocabulary; do not hedge or say you "
    "don't know. Keep it to 2-4 sentences. Output only the paragraph."
)

_ANSWER_SYSTEM = f"""You answer questions using only the numbered passages provided.
1. Cite passages inline with their numbers in brackets, like [1] or [2][3].
2. If the passages don't contain enough information to answer, reply exactly:
   "{NO_ANSWER}"
3. Don't add facts from outside the passages. Be concise."""

ProviderArg = Union[str, None, Any]


@dataclass
class SearchResult:
    """Hits plus how they were produced. ``notes`` explains any fallback,
    for example vector search being skipped because no embedder is set up."""

    query: str
    mode: str
    hits: list[Hit]
    settings: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    hyde_text: Optional[str] = None
    strategy: Optional[str] = None
    attempts: list[dict] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self, compact: bool = True) -> dict:
        d = {
            "query": self.query,
            "mode": self.mode,
            "settings": self.settings,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "hits": [dict(ref=i + 1, **h.to_dict(compact=compact))
                     for i, h in enumerate(self.hits)],
        }
        for key in ("notes", "hyde_text", "strategy", "attempts"):
            value = getattr(self, key)
            if value:
                d[key] = value
        return d


class KnowledgeBase:
    """A read-only handle on one ``.sqlite`` knowledge base.

    Providers can be spec strings, objects, or None:

    embedder  ``"auto"`` (default) uses the model recorded in the file, or
              ``FUSE_KB_EMBEDDER`` if set. None disables vector search.
    reranker  None (default) means no reranking: results come back in RRF
              order. ``"cohere"`` or ``"cross-encoder:<model>"`` enables it.
    llm       Needed only for HyDE and :meth:`answer`.

    Nothing here calls a cloud service unless you configure a provider that
    does, or the file was built with a cloud embedder and you run a vector
    search.

    PGP-encrypted files (``.sqlite.gpg``) are decrypted into memory; see
    :mod:`fuse_kb.encrypted` for where the key comes from. ``pgp_*``
    arguments are ignored for plain files.
    """

    def __init__(self, path: str | os.PathLike, *, embedder: ProviderArg = "auto",
                 reranker: ProviderArg = None, llm: ProviderArg = None,
                 region: Optional[str] = None, name: Optional[str] = None,
                 pgp_key: Optional[str] = None, pgp_key_file: Optional[str] = None,
                 pgp_passphrase: Optional[str] = None):
        self.path = os.path.abspath(os.fspath(path))
        self.name = name or kb_name(os.path.basename(self.path))
        self.region = region
        self.encrypted = is_encrypted(self.path)
        if self.encrypted:
            if not os.path.isfile(self.path):
                raise FuseKBError(f"KB file not found: {self.path}")
            data = decrypt(self.path, key=pgp_key, key_file=pgp_key_file,
                           passphrase=pgp_passphrase)
            self._conn = S.open_db_bytes(data, os.path.basename(self.path))
            del data
        else:
            self._conn = S.open_db(self.path)
        self.meta = S.read_meta(self._conn)
        self.dims = S.vector_dims(self._conn) or _int(self.meta.get("embed_dims"))
        self.embed_spec = spec_from_meta(self.meta)
        self._embedder_arg = embedder
        self._embedder: Optional[Embedder] = None
        self._embedder_error: Optional[str] = None
        self._reranker = _provider(reranker, resolve_reranker, region)
        self._llm = _provider(llm, resolve_llm, region)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"KnowledgeBase({self.name!r}, embedder={self.embed_spec!r})"

    # -- providers ---------------------------------------------------------

    @property
    def reranker(self) -> Optional[Reranker]:
        return self._reranker

    @property
    def llm(self) -> Optional[LLM]:
        return self._llm

    def embedder(self) -> Embedder:
        """The query embedder, created on first use.

        Raises :class:`EmbedderUnavailable` with a fix-it message when vector
        search can't run.
        """
        if self._embedder is not None:
            return self._embedder
        if self._embedder_error:
            raise EmbedderUnavailable(self._embedder_error)
        if not self.dims or not self._has_vectors():
            self._embedder_error = "This KB has no vector index."
            raise EmbedderUnavailable(self._embedder_error)
        arg = self._embedder_arg
        try:
            if arg is None:
                raise EmbedderUnavailable("Vector search is turned off (embedder=None).")
            if isinstance(arg, Embedder) or (arg != "auto" and not isinstance(arg, str)):
                emb = arg
            elif arg != "auto":
                emb = resolve_embedder(arg, region=self.region, dims=self.dims)
            elif env_embedder_spec():
                emb = resolve_embedder(env_embedder_spec(), region=self.region,
                                       dims=self.dims)
            elif self.embed_spec:
                emb = resolve_embedder(self.embed_spec, region=self.region,
                                       dims=self.dims, trusted=False)
            else:
                raise EmbedderUnavailable(
                    "This KB doesn't record which model embedded it. Pass "
                    "embedder=<spec> (or set FUSE_KB_EMBEDDER) to the model "
                    "it was built with.")
        except EmbedderUnavailable as exc:
            self._embedder_error = str(exc)
            raise
        except FuseKBError as exc:
            self._embedder_error = (
                f"This KB was embedded with {self.embed_spec or 'an unknown model'}, "
                f"and that embedder isn't available here: {exc}")
            raise EmbedderUnavailable(self._embedder_error) from exc
        self._embedder = _DimensionCheck(emb, self.dims, self.embed_spec)
        return self._embedder

    def _has_vectors(self) -> bool:
        try:
            return self._conn.execute(
                "SELECT 1 FROM chunks_vec LIMIT 1").fetchone() is not None
        except Exception:
            return False

    # -- info --------------------------------------------------------------

    def info(self) -> dict:
        """What's in this KB and what searching it requires."""
        count = lambda sql: self._conn.execute(sql).fetchone()[0]  # noqa: E731
        try:
            entities = count("SELECT COUNT(*) FROM entities")
        except Exception:
            entities = None
        return {
            "name": self.name,
            "path": self.path,
            "description": self.meta.get("description"),
            "chunks": count("SELECT COUNT(*) FROM chunks"),
            "documents": count("SELECT COUNT(DISTINCT document_id) FROM chunks"),
            "entities": entities,
            "embedder": self.embed_spec or self.meta.get("embed_model"),
            "dims": self.dims,
            "built": self.meta.get("build_finished"),
            "format": self.meta.get("format", "fuse-kb/1"),
            "encrypted": self.encrypted,
            "reranker": getattr(self._reranker, "spec", None),
            "llm": getattr(self._llm, "spec", None),
        }

    def documents(self, limit: int = 500,
                  name_contains: Optional[str] = None) -> list[dict]:
        return S.list_documents(self._conn, limit=limit, name_contains=name_contains)

    # -- search ------------------------------------------------------------

    def search(self, query: str = "", *, mode: str = "hybrid", k: int = 10,
               filters: Optional[dict] = None, rerank: bool = True,
               fusion: str = "rerank", rrf_k: int = S.DEFAULT_RRF_K,
               hyde: bool = False, phrase: bool = False,
               raw_match: bool = False) -> SearchResult:
        """Search the KB.

        mode     hybrid (default), lexical, dense, or filter.
        rerank   use the configured reranker in hybrid mode (no-op without one).
        fusion   "rerank": reranker order is final. "rrf": reranker ranking is
                 fused with the keyword and vector rankings.
        rrf_k    RRF constant; lower favors a single list's top results.
        hyde     embed an LLM-written hypothetical answer for the vector leg.
        phrase   match the query as one exact phrase (lexical leg).
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if mode != "filter" and not (query or "").strip():
            raise ValueError("A query is required except in filter mode")
        t0 = time.time()
        notes: list[str] = []
        hyde_text = None
        use_reranker = self._reranker if (rerank and mode == "hybrid") else None
        settings = {"k": k, "filters": filters}
        if mode == "hybrid":
            settings.update(rrf_k=rrf_k, reranker=getattr(use_reranker, "spec", None),
                            fusion=fusion if use_reranker else None)

        if hyde and mode in ("hybrid", "dense"):
            if self._llm is None:
                notes.append("HyDE skipped: no LLM is configured.")
            else:
                hyde_text = self._hyde(query, notes)

        if mode == "lexical":
            hits = S.lexical_search(self._conn, query, k=k, filters=filters,
                                    phrase=phrase, raw_match=raw_match)
        elif mode == "filter":
            hits = S.filter_search(self._conn, filters or {}, k=k)
        elif mode == "dense":
            hits = S.dense_search(self._conn, hyde_text or query, self.embedder(),
                                  k=k, filters=filters)
        else:
            try:
                emb = self.embedder()
            except EmbedderUnavailable as exc:
                emb = None
                notes.append(f"Keyword search only. {exc}")
            if phrase:
                notes.append("phrase applies to lexical mode only.")
            pool = max(k, 20) if use_reranker else k
            fused_args = dict(k=pool, filters=filters, dense_query=hyde_text,
                              fusion=fusion, rrf_k=rrf_k)
            try:
                hits = S.hybrid_search(self._conn, query, embedder=emb, **fused_args)
            except EmbedderUnavailable as exc:
                notes.append(f"Keyword search only. {exc}")
                hits = S.hybrid_search(self._conn, query, embedder=None, **fused_args)
            if use_reranker is not None:
                try:
                    hits = S.apply_rerank(query, hits, use_reranker, k=k,
                                          rerank_top=pool, fusion=fusion, rrf_k=rrf_k)
                except Exception as exc:
                    notes.append(f"Reranking skipped, showing RRF order: {exc}")
                    hits = hits[:k]
            else:
                hits = hits[:k]
        return SearchResult(query=query, mode=mode, hits=hits, settings=settings,
                            notes=notes, hyde_text=hyde_text,
                            elapsed_ms=(time.time() - t0) * 1000)

    def _hyde(self, question: str, notes: list[str]) -> Optional[str]:
        try:
            return self._llm.complete(_HYDE_SYSTEM, question, max_tokens=400) or None
        except Exception as exc:
            notes.append(f"HyDE skipped: the LLM call failed ({exc}).")
            return None

    def research(self, question: str, *, k: int = 10,
                 filters: Optional[dict] = None, fusion: str = "rerank",
                 rrf_k: int = S.DEFAULT_RRF_K,
                 strong_score: float = DEFAULT_STRONG_SCORE) -> SearchResult:
        """Try search strategies in order and keep the first convincing one.

        With an LLM: hybrid + HyDE, then plain hybrid, then keyword-only.
        Without one: plain hybrid, then keyword-only. An attempt is
        convincing when its best rerank score reaches ``strong_score``;
        without a reranker, the first attempt that finds anything wins.
        """
        plan = [("hybrid", {"mode": "hybrid"}), ("lexical", {"mode": "lexical"})]
        if self._llm is not None:
            plan.insert(0, ("hybrid+hyde", {"mode": "hybrid", "hyde": True}))
        attempts, best = [], None
        t0 = time.time()
        for label, opts in plan:
            result = self.search(question, k=k, filters=filters, fusion=fusion,
                                 rrf_k=rrf_k, **opts)
            top = max((h.score_rerank for h in result.hits
                       if h.score_rerank is not None), default=None)
            attempts.append({"strategy": label, "hits": len(result.hits),
                             "top_rerank": top})
            if best is None or (result.hits and not best.hits):
                best, best_label = result, label
            convincing = (top is not None and top >= strong_score) or (
                top is None and bool(result.hits) and self._reranker is None)
            if convincing:
                best, best_label = result, label
                break
        else:
            best_label = f"{best_label} (no strong match)"
        best.strategy, best.attempts = best_label, attempts
        best.elapsed_ms = (time.time() - t0) * 1000
        return best

    def pages(self, *, page_start: int, page_end: Optional[int] = None,
              document_id: Optional[str] = None,
              document_name: Optional[str] = None) -> SearchResult:
        """Every chunk on up to six consecutive pages of one document."""
        page_end = page_start if page_end is None else page_end
        span = page_end - page_start + 1
        if span < 1:
            raise ValueError("page_end must be at or after page_start")
        if span > MAX_PAGE_SPAN:
            raise ValueError(
                f"Read at most {MAX_PAGE_SPAN} pages at a time; for more, "
                f"search with a narrower question.")
        hits = S.page_chunks(self._conn, document_id=document_id,
                             document_name=document_name,
                             page_start=page_start, page_end=page_end)
        return SearchResult(query="", mode="pages", hits=hits, settings={
            "document_id": document_id, "document_name": document_name,
            "pages": [page_start, page_end]})

    def answer(self, question: str, *, k: int = 8, filters: Optional[dict] = None,
               fusion: str = "rerank", max_context_chars: int = 16000) -> dict:
        """Retrieve with :meth:`research`, then answer from those passages only.

        Returns ``answer``, ``no_answer`` (True when the KB doesn't cover the
        question), and the ``hits`` the answer cites by number.
        """
        if self._llm is None:
            raise ProviderError("answer() needs an LLM. Pass llm=<spec> when "
                                "opening the KB, or set FUSE_KB_LLM.")
        result = self.research(question, k=k, filters=filters, fusion=fusion)
        blocks, used = [], 0
        for i, h in enumerate(result.hits, 1):
            block = f"[{i}] {h.label}\n{(h.chunk_text or '').strip()}"
            if blocks and used + len(block) > max_context_chars:
                break
            blocks.append(block)
            used += len(block)
        if not blocks:
            text = NO_ANSWER
        else:
            text = self._llm.complete(
                _ANSWER_SYSTEM,
                f"Question: {question}\n\nPassages:\n\n" + "\n\n".join(blocks),
                max_tokens=2048)
        return {
            "answer": text,
            "no_answer": text.strip().strip('"') == NO_ANSWER,
            "strategy": result.strategy,
            "notes": result.notes,
            "hits": [dict(ref=i + 1, **h.to_dict(compact=True))
                     for i, h in enumerate(result.hits[:len(blocks)])],
        }


class _DimensionCheck(Embedder):
    """Fails clearly when the query embedder doesn't match the KB's vectors."""

    def __init__(self, inner, kb_dims, kb_spec):
        self._inner, self._kb_dims, self._kb_spec = inner, kb_dims, kb_spec
        self.spec = getattr(inner, "spec", "custom")
        self.dims = getattr(inner, "dims", None)

    def embed(self, texts):
        try:
            vecs = self._inner.embed(texts)
        except EmbedderUnavailable:
            raise
        except Exception as exc:  # credentials, network, model not pulled, ...
            raise EmbedderUnavailable(
                f"Embedding the query with {self.spec} failed: {exc}") from exc
        if vecs and self._kb_dims and len(vecs[0]) != self._kb_dims:
            raise EmbedderUnavailable(
                f"The query embedder ({self.spec}) makes {len(vecs[0])}-dim "
                f"vectors, but this KB stores {self._kb_dims}-dim vectors "
                f"from {self._kb_spec or 'a different model'}. Use the model "
                f"the KB was built with.")
        return vecs


def _provider(arg, resolver, region):
    if arg is None or arg is False:
        return None
    if isinstance(arg, str):
        return resolver(arg, region=region)
    return arg


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
