"""Exceptions raised by fuse-kb."""


class FuseKBError(Exception):
    """Base class for every error fuse-kb raises."""


class KBFormatError(FuseKBError):
    """The file is not a readable fuse-kb knowledge base."""


class ProviderError(FuseKBError):
    """An embedder, reranker, or LLM could not be created or failed to run."""


class EmbedderUnavailable(ProviderError):
    """Vector search can't run because no compatible query embedder is available."""
