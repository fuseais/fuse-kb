"""KBLibrary: a folder (or list) of KB files, addressed by name."""
from __future__ import annotations

import os
from typing import Iterable, Optional

from .encrypted import is_encrypted, kb_name
from .errors import FuseKBError
from .kb import KnowledgeBase, ProviderArg, _provider
from .providers import resolve_llm, resolve_reranker

ENV_PATH = "FUSE_KB_PATH"
DEFAULT_PATH = "kbs"


class KBLibrary:
    """Every ``.sqlite`` KB in the given folders or files, by name.

    A KB's name is its file name without ``.sqlite`` (or ``.sqlite.gpg``
    for a PGP-encrypted file, which is decrypted into memory on first use). Only discovered names
    can be opened, so a name supplied by an agent or user can't reach other
    files on disk.

    ``paths`` defaults to ``$FUSE_KB_PATH`` (folders or files separated by
    ``os.pathsep``), else ``./kbs``. Provider arguments are shared by every
    KB opened from the library; see :class:`KnowledgeBase`.
    """

    def __init__(self, paths: str | os.PathLike | Iterable[str | os.PathLike] | None = None,
                 *, embedder: ProviderArg = "auto", reranker: ProviderArg = None,
                 llm: ProviderArg = None, region: Optional[str] = None,
                 pgp_key: Optional[str] = None, pgp_key_file: Optional[str] = None,
                 pgp_passphrase: Optional[str] = None):
        if paths is None:
            paths = os.environ.get(ENV_PATH) or DEFAULT_PATH
        if isinstance(paths, (str, os.PathLike)):
            paths = [p for p in os.fspath(paths).split(os.pathsep) if p]
        self._files: dict[str, str] = {}
        for p in paths:
            p = os.path.abspath(os.path.expanduser(os.fspath(p)))
            if os.path.isdir(p):
                for entry in sorted(os.listdir(p)):
                    if entry.endswith(".sqlite") or is_encrypted(entry):
                        self._files.setdefault(kb_name(entry), os.path.join(p, entry))
            elif os.path.isfile(p):
                self._files.setdefault(kb_name(os.path.basename(p)), p)
        self._provider_args = dict(embedder=embedder, reranker=reranker,
                                   llm=llm, region=region)
        self._pgp = dict(pgp_key=pgp_key, pgp_key_file=pgp_key_file,
                         pgp_passphrase=pgp_passphrase)
        self._open: dict[str, KnowledgeBase] = {}
        self._backends: dict = {}
        self._shared: dict = {}

    def add(self, name: str, backend) -> None:
        """Register any :class:`fuse_kb.backend.KBBackend` under ``name``,
        for example a hosted or enterprise search backend. It then appears in
        :meth:`list` and in every agent tool alongside the local files."""
        if name in self._files or name in self._backends:
            raise FuseKBError(f"A knowledge base named {name!r} already exists")
        self._backends[name] = backend

    @property
    def names(self) -> list[str]:
        return sorted({*self._files, *self._backends})

    def __contains__(self, name: str) -> bool:
        return name in self._files or name in self._backends

    def __len__(self) -> int:
        return len(self._files) + len(self._backends)

    def get(self, name: Optional[str] = None):
        """Open a KB by name. With exactly one KB, the name may be omitted."""
        if name is None:
            if len(self) == 1:
                name = self.names[0]
            elif len(self):
                raise FuseKBError("Several knowledge bases are available; name "
                                  "one of: " + ", ".join(self.names))
            else:
                raise FuseKBError("No knowledge bases found. Put .sqlite files "
                                  f"in ./{DEFAULT_PATH} or set {ENV_PATH}.")
        if name in self._backends:
            return self._backends[name]
        if name not in self._files:
            raise FuseKBError(
                f"No knowledge base named {name!r}. Available: "
                + (", ".join(self.names) or "none"))
        if name not in self._open:
            self._open[name] = KnowledgeBase(self._files[name], name=name,
                                             **self._shared_providers(), **self._pgp)
        return self._open[name]

    def _shared_providers(self) -> dict:
        """Provider args with reranker and LLM built once for all KBs."""
        if not self._shared:
            args = dict(self._provider_args)
            args["reranker"] = _provider(args["reranker"], resolve_reranker,
                                         args["region"])
            args["llm"] = _provider(args["llm"], resolve_llm, args["region"])
            self._shared = args
        return self._shared

    @property
    def has_llm(self) -> bool:
        return self._provider_args["llm"] is not None

    @property
    def has_reranker(self) -> bool:
        return self._provider_args["reranker"] is not None

    def list(self) -> list[dict]:
        """Name, description, size, and embedder of every KB."""
        out = []
        for name in self.names:
            try:
                info = self.get(name).info()
                out.append({k: info[k] for k in (
                    "name", "description", "documents", "chunks", "embedder", "built")})
            except FuseKBError as exc:
                out.append({"name": name, "error": str(exc)})
        return out

    def close(self) -> None:
        for kb in [*self._open.values(), *self._backends.values()]:
            kb.close()
        self._open.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
