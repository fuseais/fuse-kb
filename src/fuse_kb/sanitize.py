"""Remove hidden markup and text aimed at manipulating an AI.

Documents in a knowledge base may come from anyone. Before passage text
reaches an LLM, this strips the two most common prompt-injection carriers:

- hidden markup: HTML comments and script/style blocks, which readers never
  see but models do
- sentences that address an AI assistant rather than a human reader
  ("ignore previous instructions", "tell the user to ...", "do not mention")

Prompt rules alone don't stop injection reliably, especially with smaller
models; removing the text does. What was removed is reported, so callers
can show it rather than drop content silently.
"""
from __future__ import annotations

import re

_HIDDEN = re.compile(
    r"<!--.*?(?:-->|$)|<(script|style)\b[^>]*>.*?(?:</\1\s*>|$)",
    re.IGNORECASE | re.DOTALL)

_INSTRUCTION = re.compile(r"""
    \b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}?
        \b(?:previous|prior|above|earlier|all|any|other|the)\b[^.\n]{0,20}?
        \b(?:instructions?|directions?|rules|prompts?|guidelines)\b
  | (?:^|[\s>\[(])(?:system|assistant|developer)\s*(?:prompt|message|instructions?)?\s*:
  | \b(?:you\s+are\s+now|from\s+now\s+on\s+you|new\s+instructions?\s*:|act\s+as\s+(?:an?\s+)?(?:ai|assistant|chatbot))\b
  | \b(?:tell|instruct|direct|advise|ask)\s+(?:the\s+)?(?:user|customer|employee|reader)s?\s+to\b
  | \bdo\s+not\s+(?:mention|reveal|tell|disclose)\b[^.\n]{0,40}\b(?:user|portal|this|instructions?)\b
  | \bwhen\s+(?:asked|answering|responding|replying)\b[^.\n]{0,60}\b(?:say|tell|answer|respond|reply)\b
""", re.IGNORECASE | re.VERBOSE)

_SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?]+|\n|$)")


def strip_hidden_markup(text: str) -> tuple[str, list[str]]:
    removed = [m.group(0) for m in _HIDDEN.finditer(text)]
    return _HIDDEN.sub(" ", text), removed


def sanitize(text: str) -> tuple[str, list[str]]:
    """Return (text with injection carriers removed, list of removed snippets)."""
    text, removed = strip_hidden_markup(text or "")
    kept: list[str] = []
    for sentence in _SENTENCE.findall(text):
        if sentence.strip() and _INSTRUCTION.search(sentence):
            removed.append(sentence.strip())
            kept.append(" " if not sentence.endswith("\n") else "\n")
        else:
            kept.append(sentence)
    cleaned = re.sub(r"[ \t]{2,}", " ", "".join(kept))
    return cleaned.strip() if removed else text, [r[:200] for r in removed]


def looks_injected(text: str) -> bool:
    return bool(_HIDDEN.search(text or "") or _INSTRUCTION.search(text or ""))
