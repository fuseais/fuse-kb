"""Rerankers: score each (question, passage) pair for relevance."""
from __future__ import annotations

import math
import time

from ..errors import ProviderError
from ._common import aws_region, load_custom, require

COHERE_RERANK_V35 = "cohere.rerank-v3-5:0"


class Reranker:
    """Base class. :meth:`rerank` returns ``[(index, score), ...]`` best first,
    with scores in 0..1 so a single relevance threshold works across rerankers."""

    spec: str = "custom"

    def rerank(self, query: str, documents: list[str],
               top_n: int) -> list[tuple[int, float]]:
        raise NotImplementedError


class CohereBedrockReranker(Reranker):
    """Cohere Rerank v3.5 through the AWS Bedrock Rerank API."""

    def __init__(self, region: str | None = None, model_id: str = COHERE_RERANK_V35):
        boto3 = require("boto3", "bedrock")
        self.spec = "cohere"
        self._region = aws_region(region)
        self._model_arn = (
            f"arn:aws:bedrock:{self._region}::foundation-model/{model_id}")
        self._client = boto3.client("bedrock-agent-runtime",
                                    region_name=self._region)

    def rerank(self, query, documents, top_n):
        sources = [{
            "type": "INLINE",
            "inlineDocumentSource": {
                "type": "TEXT",
                "textDocument": {"text": ((d or "").strip() or "(empty)")[:4096]},
            },
        } for d in documents]
        for attempt in range(3):
            try:
                resp = self._client.rerank(
                    queries=[{"type": "TEXT", "textQuery": {"text": query}}],
                    sources=sources,
                    rerankingConfiguration={
                        "type": "BEDROCK_RERANKING_MODEL",
                        "bedrockRerankingConfiguration": {
                            "modelConfiguration": {"modelArn": self._model_arn},
                            "numberOfResults": min(top_n, len(documents)),
                        },
                    })
                return [(r["index"], float(r["relevanceScore"]))
                        for r in resp.get("results", [])]
            except Exception as exc:  # botocore raises per-service classes
                if "Throttling" in str(exc) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise ProviderError(f"Cohere rerank on Bedrock failed: {exc}") from exc
        return []


class CrossEncoderReranker(Reranker):
    """Local sentence-transformers cross-encoder, e.g. BAAI/bge-reranker-v2-m3."""

    def __init__(self, model: str, device: str | None = None):
        st = require("sentence_transformers", "local")
        self.spec = f"cross-encoder:{model}"
        self._model = st.CrossEncoder(model, device=device)

    def rerank(self, query, documents, top_n):
        logits = self._model.predict([(query, d or "(empty)") for d in documents])
        # Cross-encoders emit logits; a sigmoid maps them to 0..1 relevance.
        scored = [(i, 1.0 / (1.0 + math.exp(-float(s)))) for i, s in enumerate(logits)]
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[:top_n]


def resolve_reranker(spec: str, *, region: str | None = None,
                     trusted: bool = True) -> Reranker:
    kind, _, arg = spec.partition(":")
    if kind in ("cohere", "cohere-bedrock") and not arg:
        return CohereBedrockReranker(region=region)
    if kind == "cross-encoder" and arg:
        return CrossEncoderReranker(arg)
    if "." in spec and ":" not in spec:
        return load_custom(spec, "reranker", trusted)
    raise ProviderError(
        f"Unknown reranker {spec!r}. Use cohere (Cohere v3.5 on AWS Bedrock) "
        f"or cross-encoder:<model> (local).")
