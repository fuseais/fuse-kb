from __future__ import annotations

import importlib
import json
import os
import urllib.error
import urllib.request

from ..errors import ProviderError


def aws_region(region: str | None = None) -> str:
    return (region or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")


def ollama_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    return host if host.startswith("http") else f"http://{host}"


def require(module: str, extra: str):
    """Import an optional dependency or explain which extra installs it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ProviderError(
            f"This provider needs the '{module}' package. "
            f"Install it with: pip install 'fuse-kb[{extra}]'") from exc


def load_custom(spec: str, kind: str, trusted: bool):
    """Instantiate ``package.module.ClassName`` when the spec is trusted."""
    if not trusted:
        raise ProviderError(
            f"Refusing to load custom {kind} {spec!r} named inside a KB file. "
            f"Pass the {kind} explicitly from your code instead.")
    module_path, _, class_name = spec.rpartition(".")
    try:
        cls = getattr(importlib.import_module(module_path), class_name)
    except (ImportError, AttributeError) as exc:
        raise ProviderError(f"Can't load custom {kind} {spec!r}: {exc}") from exc
    return cls()


def post_json(url: str, payload: dict, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise ProviderError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"Can't reach {url}: {exc.reason}") from exc
