"""The search result record."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class Hit:
    """One retrieved chunk, with its provenance and every score that ranked it.

    Scores read in different directions:
      score_lexical  BM25; lower (more negative) is a stronger match
      score_dense    vector distance; lower is closer
      score_rerank   reranker relevance; higher is better
      score_rrf      Reciprocal Rank Fusion of the lexical and dense rankings
      score_final    whatever set the final order (rerank, RRF, or the above)

    Ranks are 0-based positions within each list. ``rank_rrf`` and
    ``rank_rerank`` together show how far the reranker moved a hit.
    """

    chunk_id: int
    document_id: Optional[str]
    document_name: Optional[str]
    page_number: Optional[int]
    chunk_text: str
    source: Optional[str] = None
    chunk_offset: Optional[int] = None
    classification_category: Optional[str] = None
    document_domain: Optional[str] = None
    jurisdiction_country: Optional[str] = None
    jurisdiction_subdivision: Optional[str] = None
    score_lexical: Optional[float] = None
    score_dense: Optional[float] = None
    score_rerank: Optional[float] = None
    score_rrf: Optional[float] = None
    score_final: Optional[float] = None
    rank_lexical: Optional[int] = None
    rank_dense: Optional[int] = None
    rank_rrf: Optional[int] = None
    rank_rerank: Optional[int] = None

    @property
    def label(self) -> str:
        page = f"p.{self.page_number}" if self.page_number is not None else ""
        return f"{self.document_name or '?'} {page}".strip()

    def to_dict(self, compact: bool = False) -> dict:
        """Plain dict for JSON. ``compact=True`` drops fields that are None."""
        d = asdict(self)
        if compact:
            d = {k: v for k, v in d.items() if v is not None}
        return d

    def to_citation(self, snippet_chars: int = 240) -> dict:
        """Footnote-ready citation. ``url`` is set only for http(s)/s3 sources."""
        src = self.source or ""
        url = src if src.startswith(("http://", "https://", "s3://")) else None
        snippet = " ".join((self.chunk_text or "").split())
        if len(snippet) > snippet_chars:
            snippet = snippet[:snippet_chars].rsplit(" ", 1)[0] + "…"
        return {
            "label": self.label,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page_number": self.page_number,
            "chunk_id": self.chunk_id,
            "chunk_offset": self.chunk_offset,
            "source": self.source,
            "url": url,
            "snippet": snippet,
        }
