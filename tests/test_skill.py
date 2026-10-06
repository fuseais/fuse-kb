"""The agent skill must document exactly the parameters the tools accept."""
import re
from importlib import resources

from fuse_kb import KBLibrary, Toolkit

from conftest import EchoLLM, ReverseReranker, ToyEmbedder


def _skill_params() -> dict[str, set[str]]:
    text = resources.files("fuse_kb").joinpath("skill/SKILL.md").read_text()
    params, tool = {}, None
    for line in text.splitlines():
        heading = re.match(r"### `(kb_\w+)`", line)
        if heading:
            tool = heading.group(1)
            params[tool] = set()
        elif tool and line.startswith("| `"):
            params[tool].add(re.match(r"\| `(\w+)`", line).group(1))
        elif line.startswith("## "):
            tool = None
    return params


def test_skill_documents_every_tool_parameter(kb_dir):
    full = Toolkit(KBLibrary(kb_dir, embedder=ToyEmbedder(),
                             reranker=ReverseReranker(), llm=EchoLLM()))
    documented = _skill_params()
    for tool in full.definitions():
        actual = set(tool["input_schema"].get("properties", {}))
        assert documented.get(tool["name"], set()) == actual, tool["name"]
