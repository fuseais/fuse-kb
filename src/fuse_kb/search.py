"""Connection-level search functions.

These operate on an open ``sqlite3.Connection`` and take providers as
objects, so they have no configuration of their own. Most callers want the
higher-level :class:`fuse_kb.KnowledgeBase`, which picks providers, handles
missing ones gracefully, and returns structured results.

Retrieval levels, all in one file:
  lexical  FTS5 BM25 over chunk text and document names
  dense    sqlite-vec KNN over chunk embeddings
  filter   plain SQL WHERE over metadata columns
  hybrid   lexical + dense fused with Reciprocal Rank Fusion (RRF),
           optionally reranked, with the final order set by ``fusion``
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Iterable, Optional, Sequence

import sqlite_vec

from .errors import FuseKBError, KBFormatError
from .hit import Hit

DEFAULT_RRF_K = 60
FUSION_MODES = ("rerank", "rrf")

FILTER_COLUMNS = frozenset({
    "document_id",
    "document_name",
    "source",
    "mime_type",
    "page_number",
    "total_pages",
    "classification_category",
    "document_domain",
    "jurisdiction_country",
    "jurisdiction_subdivision",
    "content_hash",
})

_HIT_COLUMNS = (
    "chunks.chunk_id, chunks.document_id, chunks.document_name, "
    "chunks.page_number, chunks.chunk_text, chunks.source, chunks.chunk_offset, "
    "chunks.classification_category, chunks.document_domain, "
    "chunks.jurisdiction_country, chunks.jurisdiction_subdivision"
)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def open_db(path: str | os.PathLike) -> sqlite3.Connection:
    """Open a KB file read-only and load sqlite-vec.

    ``immutable=1`` tells SQLite the file never changes: no journal, no
    locks, safe for many processes to share one copy.
    """
    path = os.path.abspath(os.fspath(path))
    if not os.path.isfile(path):
        raise FuseKBError(f"KB file not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except AttributeError as exc:
        conn.close()
        raise FuseKBError(
            "This Python's sqlite3 module can't load extensions, which "
            "sqlite-vec needs. Use a Python build with extension loading "
            "(python.org installers, uv, pyenv, Homebrew, or conda)."
        ) from exc
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise KBFormatError(f"{path} is not a SQLite database: {exc}") from exc
    missing = {"chunks", "chunks_fts"} - names
    if missing:
        conn.close()
        raise KBFormatError(
            f"{path} is not a fuse-kb knowledge base "
            f"(missing tables: {', '.join(sorted(missing))})")
    return conn


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def fts5_query(text: str, phrase: bool = False) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Free text is reduced to word tokens, each quoted so FTS5 treats it
    literally (apostrophes, colons, and hyphens are FTS5 operators). Tokens
    are OR-ed implicitly by BM25 ranking. ``phrase=True`` matches the whole
    text as one exact phrase instead.
    """
    if phrase:
        inner = " ".join(_TOKEN_RE.findall(text or ""))
        return f'"{inner}"' if inner else '""'
    tokens = _TOKEN_RE.findall(text or "")
    return " OR ".join(f'"{t}"' for t in tokens) if tokens else '""'


def filters_to_where(filters: Optional[dict]) -> tuple[str, list]:
    """Translate a filter dict into a parameterized WHERE fragment.

    Values: scalar -> ``=``, list -> ``IN``, 2-tuple -> ``BETWEEN``. A
    2-element list of numbers on ``page_number``/``total_pages`` is also
    read as a range, since JSON has no tuples. Column names are checked
    against :data:`FILTER_COLUMNS`; values are always bound parameters.
    """
    if not filters:
        return "", []
    parts: list[str] = []
    params: list = []
    for col, val in filters.items():
        if col not in FILTER_COLUMNS:
            raise ValueError(
                f"Can't filter on {col!r}. Filterable columns: "
                f"{', '.join(sorted(FILTER_COLUMNS))}")
        is_range = isinstance(val, tuple) and len(val) == 2
        if (isinstance(val, list) and len(val) == 2
                and col in ("page_number", "total_pages")
                and all(isinstance(v, (int, float)) for v in val)):
            is_range = True
        if is_range:
            parts.append(f"chunks.{col} BETWEEN ? AND ?")
            params.extend(val)
        elif isinstance(val, list):
            if not val:
                raise ValueError(f"Empty list for filter {col!r}")
            parts.append(f"chunks.{col} IN ({','.join('?' for _ in val)})")
            params.extend(val)
        else:
            parts.append(f"chunks.{col} = ?")
            params.append(val)
    return " AND ".join(parts), params


def _row_to_hit(row: sqlite3.Row, **scores) -> Hit:
    return Hit(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        document_name=row["document_name"],
        page_number=row["page_number"],
        chunk_text=row["chunk_text"],
        source=row["source"],
        chunk_offset=row["chunk_offset"],
        classification_category=row["classification_category"],
        document_domain=row["document_domain"],
        jurisdiction_country=row["jurisdiction_country"],
        jurisdiction_subdivision=row["jurisdiction_subdivision"],
        **scores,
    )


# ---------------------------------------------------------------------------
# Single-level searches
# ---------------------------------------------------------------------------

def lexical_search(conn: sqlite3.Connection, query: str, k: int = 20,
                   filters: Optional[dict] = None, raw_match: bool = False,
                   phrase: bool = False) -> list[Hit]:
    """FTS5 BM25 search. ``raw_match=True`` passes ``query`` to MATCH verbatim."""
    match = query if raw_match else fts5_query(query, phrase=phrase)
    where, params = filters_to_where(filters)
    sql = f"""
        SELECT {_HIT_COLUMNS}, bm25(chunks_fts) AS bm25_score
          FROM chunks_fts JOIN chunks ON chunks.chunk_id = chunks_fts.rowid
         WHERE chunks_fts MATCH ? {"AND " + where if where else ""}
         ORDER BY bm25_score LIMIT ?
    """
    rows = conn.execute(sql, [match, *params, k]).fetchall()
    return [_row_to_hit(r, score_lexical=r["bm25_score"]) for r in rows]


def vector_search(conn: sqlite3.Connection, vector: Sequence[float],
                  k: int = 20, filters: Optional[dict] = None) -> list[Hit]:
    """sqlite-vec KNN for a query vector. Distance: lower is closer."""
    where, params = filters_to_where(filters)
    # vec0 picks the k nearest before the metadata filter applies, so
    # over-fetch when filtering and trim afterwards.
    fetch = k * 4 if where else k
    sql = f"""
        SELECT {_HIT_COLUMNS}, chunks_vec.distance AS vec_distance
          FROM chunks_vec JOIN chunks ON chunks.chunk_id = chunks_vec.chunk_id
         WHERE chunks_vec.embedding MATCH ? AND k = ?
               {"AND " + where if where else ""}
         ORDER BY vec_distance
    """
    blob = sqlite_vec.serialize_float32(list(vector))
    rows = conn.execute(sql, [blob, fetch, *params]).fetchall()[:k]
    return [_row_to_hit(r, score_dense=r["vec_distance"]) for r in rows]


def dense_search(conn: sqlite3.Connection, query: str, embedder,
                 k: int = 20, filters: Optional[dict] = None) -> list[Hit]:
    """Embed ``query`` with ``embedder`` and run :func:`vector_search`."""
    return vector_search(conn, embedder.embed([query])[0], k=k, filters=filters)


def filter_search(conn: sqlite3.Connection, filters: dict,
                  k: int = 20) -> list[Hit]:
    """Metadata-only lookup in document and page order. No relevance ranking."""
    where, params = filters_to_where(filters)
    if not where:
        raise ValueError("Filter search needs at least one filter")
    sql = f"""
        SELECT {_HIT_COLUMNS} FROM chunks WHERE {where}
         ORDER BY chunks.document_name, chunks.page_number, chunks.chunk_offset
         LIMIT ?
    """
    return [_row_to_hit(r) for r in conn.execute(sql, [*params, k]).fetchall()]


# ---------------------------------------------------------------------------
# Rerank and hybrid
# ---------------------------------------------------------------------------

def rerank_hits(query: str, hits: list[Hit], reranker) -> list[Hit]:
    """Score each hit against the query; return them in reranked order."""
    if not hits:
        return hits
    scored = reranker.rerank(query, [h.chunk_text for h in hits], top_n=len(hits))
    ordered: list[Hit] = []
    for rank, (idx, score) in enumerate(scored):
        h = hits[idx]
        h.score_rerank = float(score)
        h.rank_rerank = rank
        ordered.append(h)
    return ordered


def rrf_score(rrf_k: int, ranks: Iterable[Optional[int]]) -> float:
    """Reciprocal Rank Fusion: sum of 1 / (rrf_k + rank) over lists, 0-based ranks."""
    return sum(1.0 / (rrf_k + r) for r in ranks if r is not None)


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    *,
    embedder=None,
    reranker=None,
    k: int = 10,
    filters: Optional[dict] = None,
    candidate_k: int = 50,
    rerank_top: int = 20,
    dense_query: Optional[str] = None,
    fusion: str = "rerank",
    rrf_k: int = DEFAULT_RRF_K,
) -> list[Hit]:
    """Lexical + dense candidates fused by RRF, then optionally reranked.

    ``embedder=None`` skips the dense leg (keyword-only RRF);
    ``reranker=None`` skips reranking and returns the RRF order.

    ``fusion`` sets the final order when a reranker runs:
      "rerank"  the reranker's order is final
      "rrf"     the reranker's ranking joins the lexical and dense rankings
                as a third RRF list, so a strong exact match isn't dropped
                on one reranker judgment

    ``dense_query`` replaces the text embedded for the dense leg (HyDE);
    the lexical leg and the reranker still use ``query``.
    """
    if fusion not in FUSION_MODES:
        raise ValueError(f"fusion must be one of {FUSION_MODES}, got {fusion!r}")
    if rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")

    by_id: dict[int, Hit] = {}
    for rank, h in enumerate(lexical_search(conn, query, k=candidate_k,
                                            filters=filters)):
        h.rank_lexical = rank
        by_id[h.chunk_id] = h
    if embedder is not None:
        for rank, h in enumerate(dense_search(conn, dense_query or query,
                                              embedder, k=candidate_k,
                                              filters=filters)):
            existing = by_id.get(h.chunk_id)
            if existing is None:
                h.rank_dense = rank
                by_id[h.chunk_id] = h
            else:
                existing.rank_dense = rank
                existing.score_dense = h.score_dense

    fused = list(by_id.values())
    for h in fused:
        h.score_rrf = rrf_score(rrf_k, (h.rank_lexical, h.rank_dense))
        h.score_final = h.score_rrf
    fused.sort(key=lambda h: h.score_rrf, reverse=True)
    for rank, h in enumerate(fused):
        h.rank_rrf = rank

    if reranker is None:
        return fused[:k]
    return apply_rerank(query, fused, reranker, k=k, rerank_top=rerank_top,
                        fusion=fusion, rrf_k=rrf_k)


def apply_rerank(query: str, fused: list[Hit], reranker, *, k: int = 10,
                 rerank_top: int = 20, fusion: str = "rerank",
                 rrf_k: int = DEFAULT_RRF_K) -> list[Hit]:
    """Rerank the top of an RRF-ordered list and set the final order."""
    top = rerank_hits(query, fused[:rerank_top], reranker)
    if fusion == "rrf":
        for h in top:
            h.score_final = rrf_score(
                rrf_k, (h.rank_lexical, h.rank_dense, h.rank_rerank))
        top.sort(key=lambda h: h.score_final, reverse=True)
    else:
        for h in top:
            h.score_final = h.score_rerank
    return top[:k]


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------

def page_chunks(conn: sqlite3.Connection, *, document_id: Optional[str] = None,
                document_name: Optional[str] = None, page_start: int,
                page_end: int, limit: int = 200) -> list[Hit]:
    """Every chunk on a page range of one document, in reading order."""
    if not (document_id or document_name):
        raise ValueError("Pass document_id or document_name")
    col, val = ("document_id", document_id) if document_id else (
        "document_name", document_name)
    sql = f"""
        SELECT {_HIT_COLUMNS} FROM chunks
         WHERE chunks.{col} = ? AND chunks.page_number BETWEEN ? AND ?
         ORDER BY chunks.page_number, chunks.chunk_offset, chunks.chunk_id
         LIMIT ?
    """
    rows = conn.execute(sql, [val, page_start, page_end, limit]).fetchall()
    return [_row_to_hit(r) for r in rows]


def list_documents(conn: sqlite3.Connection, limit: int = 500,
                   name_contains: Optional[str] = None) -> list[dict]:
    """One row per document: id, name, source, pages, chunks, category."""
    where, params = "", []
    if name_contains:
        where, params = "WHERE document_name LIKE ? ESCAPE '\\'", [
            "%" + name_contains.replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_") + "%"]
    sql = f"""
        SELECT document_id, document_name, MIN(source) AS source,
               MAX(total_pages) AS total_pages, COUNT(*) AS chunks,
               MIN(classification_category) AS classification_category,
               MIN(document_domain) AS document_domain
          FROM chunks {where}
         GROUP BY document_id ORDER BY document_name LIMIT ?
    """
    return [dict(r) for r in conn.execute(sql, [*params, limit]).fetchall()]


def read_meta(conn: sqlite3.Connection) -> dict:
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT key, value FROM _meta")}
    except sqlite3.OperationalError:
        return {}


def vector_dims(conn: sqlite3.Connection) -> Optional[int]:
    """The embedding width declared by the chunks_vec table, if any."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'chunks_vec'").fetchone()
    if not row or not row[0]:
        return None
    m = re.search(r"float\[(\d+)\]", row[0])
    return int(m.group(1)) if m else None
