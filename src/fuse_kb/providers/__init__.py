"""Pluggable embedders, rerankers, and LLMs.

Every provider is chosen with a short spec string, or passed as an object
you construct yourself:

  embedders   bedrock | bedrock:<model-id> | ollama:<model>
              sentence-transformers:<model> | openai:<model>
  rerankers   cohere | cohere-bedrock | cross-encoder:<model>
  LLMs        anthropic[:<model>] | bedrock:<model-id> | ollama:<model>
              openai:<model>

Specs that come from your own code, CLI flags, or environment variables may
also be a dotted path to a class (``mypackage.module.ClassName``). Specs read
from a KB file never are: a downloaded file can only select a built-in
provider, so opening a file can't import arbitrary code.
"""
from .embedders import Embedder, resolve_embedder, spec_from_meta
from .llms import LLM, resolve_llm
from .rerankers import Reranker, resolve_reranker

__all__ = [
    "Embedder", "Reranker", "LLM",
    "resolve_embedder", "resolve_reranker", "resolve_llm", "spec_from_meta",
]
