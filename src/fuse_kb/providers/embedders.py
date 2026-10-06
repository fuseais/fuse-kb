"""Query embedders.

A KB can only be searched by vector with the same model that embedded it,
so the KB records its embedder (``_meta.embed_spec``) and fuse-kb picks the
matching one automatically.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from ..errors import ProviderError
from ._common import aws_region, load_custom, ollama_url, post_json, require

TITAN_V2 = "amazon.titan-embed-text-v2:0"
_BUILTIN_PREFIXES = ("bedrock", "ollama:", "sentence-transformers:", "openai:")


class Embedder:
    """Base class. Subclasses set ``spec`` and implement :meth:`embed`."""

    spec: str = "custom"
    dims: Optional[int] = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class BedrockTitanEmbedder(Embedder):
    def __init__(self, model_id: str = TITAN_V2, region: str | None = None,
                 dims: int = 1024):
        boto3 = require("boto3", "bedrock")
        self.model_id, self.dims = model_id, dims
        self.spec = "bedrock" if model_id == TITAN_V2 else f"bedrock:{model_id}"
        self._client = boto3.client("bedrock-runtime", region_name=aws_region(region))

    def embed(self, texts):
        out = []
        for text in texts:
            # Titan v2 accepts ~8k tokens; same truncation the builder uses.
            resp = self._client.invoke_model(
                modelId=self.model_id,
                body=json.dumps({"inputText": text[:8000], "dimensions": self.dims}))
            out.append(json.loads(resp["body"].read())["embedding"])
        return out


class OllamaEmbedder(Embedder):
    def __init__(self, model: str, base_url: str | None = None):
        self.model, self.spec = model, f"ollama:{model}"
        self._url = (base_url or ollama_url()).rstrip("/")

    def embed(self, texts):
        # /api/embed with truncate=True clips inputs past the model's context
        # instead of failing (the legacy /api/embeddings endpoint 500s).
        data = post_json(f"{self._url}/api/embed",
                         {"model": self.model, "input": list(texts), "truncate": True})
        vecs = data["embeddings"]
        if vecs:
            self.dims = len(vecs[0])
        return vecs


class SentenceTransformersEmbedder(Embedder):
    def __init__(self, model: str, device: str | None = None):
        st = require("sentence_transformers", "local")
        self.spec = f"sentence-transformers:{model}"
        self._model = st.SentenceTransformer(model, device=device)
        self.dims = self._model.get_sentence_embedding_dimension()

    def embed(self, texts):
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return [v.tolist() for v in vecs]


class OpenAIEmbedder(Embedder):
    """OpenAI or any OpenAI-compatible embeddings API (``OPENAI_BASE_URL``)."""

    def __init__(self, model: str, dims: int | None = None):
        openai = require("openai", "openai")
        self.model, self.dims, self.spec = model, dims, f"openai:{model}"
        self._client = openai.OpenAI()

    def embed(self, texts):
        kwargs = {"dimensions": self.dims} if self.dims else {}
        resp = self._client.embeddings.create(model=self.model, input=list(texts),
                                              **kwargs)
        return [d.embedding for d in resp.data]


def is_builtin_spec(spec: str) -> bool:
    return spec == "bedrock" or spec.startswith(_BUILTIN_PREFIXES)


def resolve_embedder(spec: str, *, region: str | None = None,
                     dims: int | None = None, trusted: bool = True) -> Embedder:
    """Build an embedder from a spec string. See :mod:`fuse_kb.providers`."""
    kind, _, arg = spec.partition(":")
    if kind == "bedrock":
        return BedrockTitanEmbedder(arg or TITAN_V2, region=region, dims=dims or 1024)
    if kind == "ollama" and arg:
        return OllamaEmbedder(arg)
    if kind == "sentence-transformers" and arg:
        return SentenceTransformersEmbedder(arg)
    if kind == "openai" and arg:
        return OpenAIEmbedder(arg, dims=dims)
    if "." in spec and ":" not in spec:
        return load_custom(spec, "embedder", trusted)
    raise ProviderError(
        f"Unknown embedder {spec!r}. Use bedrock, bedrock:<model-id>, "
        f"ollama:<model>, sentence-transformers:<model>, or openai:<model>.")


def spec_from_meta(meta: dict) -> Optional[str]:
    """The embedder spec a KB was built with, or None if it can't be told.

    KBs built before ``embed_spec`` was recorded were always embedded with
    Bedrock Titan v2, which they record as ``embed_model``.
    """
    spec = (meta.get("embed_spec") or "").strip()
    if spec:
        return spec if is_builtin_spec(spec) else None
    model = (meta.get("embed_model") or "").lower()
    if "bedrock" in model or "titan" in model:
        return "bedrock"
    return None


def env_embedder_spec() -> Optional[str]:
    return os.environ.get("FUSE_KB_EMBEDDER") or None
