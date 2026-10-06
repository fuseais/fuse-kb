"""LLMs used for HyDE (a hypothetical answer to embed) and grounded answers."""
from __future__ import annotations

from ..errors import ProviderError
from ._common import aws_region, load_custom, ollama_url, post_json, require

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
# Models that accept server-side refusal fallbacks on the Claude API.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                    "claude-sonnet-5-5"}


class LLM:
    """Base class. :meth:`complete` returns the model's text reply."""

    spec: str = "custom"

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        raise NotImplementedError


class AnthropicLLM(LLM):
    """Claude through the Anthropic API (``ANTHROPIC_API_KEY`` or an
    ``ant auth login`` profile)."""

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL, effort: str = "low"):
        anthropic = require("anthropic", "anthropic")
        self.model, self.effort = model, effort
        self.spec = f"anthropic:{model}"
        self._client = anthropic.Anthropic()

    def complete(self, system, user, max_tokens=2048):
        kwargs = dict(
            model=self.model,
            max_tokens=max(max_tokens, 4096),
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
        )
        if self.model in _FALLBACK_MODELS:
            # On a policy decline, the API retries on a fallback model in the
            # same call instead of returning an empty refusal.
            resp = self._client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                **kwargs)
        else:
            resp = self._client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            raise ProviderError(f"{self.model} declined the request")
        return "".join(b.text for b in resp.content if b.type == "text").strip()


class BedrockLLM(LLM):
    """Any Bedrock chat model through the model-agnostic Converse API."""

    def __init__(self, model_id: str, region: str | None = None):
        boto3 = require("boto3", "bedrock")
        self.model_id, self.spec = model_id, f"bedrock:{model_id}"
        self._client = boto3.client("bedrock-runtime", region_name=aws_region(region))

    def complete(self, system, user, max_tokens=2048):
        try:
            resp = self._client.converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1})
        except Exception as exc:
            raise ProviderError(f"Bedrock {self.model_id} failed: {exc}") from exc
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts).strip()


class OllamaLLM(LLM):
    def __init__(self, model: str, base_url: str | None = None):
        self.model, self.spec = model, f"ollama:{model}"
        self._url = (base_url or ollama_url()).rstrip("/")

    def complete(self, system, user, max_tokens=2048):
        data = post_json(f"{self._url}/api/chat", {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {"temperature": 0.1, "num_predict": max_tokens},
        }, timeout=600)
        text = data.get("message", {}).get("content", "")
        # Reasoning models served by older Ollama versions inline their
        # thinking; keep only the answer.
        if "</think>" in text:
            text = text.rsplit("</think>", 1)[1]
        return text.strip()


class OpenAILLM(LLM):
    """OpenAI or any OpenAI-compatible chat API (``OPENAI_BASE_URL``):
    vLLM, llama.cpp, LM Studio, and others."""

    def __init__(self, model: str):
        openai = require("openai", "openai")
        self.model, self.spec = model, f"openai:{model}"
        self._client = openai.OpenAI()

    def complete(self, system, user, max_tokens=2048):
        resp = self._client.chat.completions.create(
            model=self.model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        return (resp.choices[0].message.content or "").strip()


def resolve_llm(spec: str, *, region: str | None = None,
                trusted: bool = True) -> LLM:
    kind, _, arg = spec.partition(":")
    if kind == "anthropic":
        return AnthropicLLM(arg or DEFAULT_ANTHROPIC_MODEL)
    if kind == "bedrock" and arg:
        return BedrockLLM(arg, region=region)
    if kind == "ollama" and arg:
        return OllamaLLM(arg)
    if kind == "openai" and arg:
        return OpenAILLM(arg)
    if "." in spec and ":" not in spec:
        return load_custom(spec, "LLM", trusted)
    raise ProviderError(
        f"Unknown LLM {spec!r}. Use anthropic[:<model>], bedrock:<model-id>, "
        f"ollama:<model>, or openai:<model>.")
