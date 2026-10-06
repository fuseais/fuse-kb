# fuse-kb

Search the knowledge bases you build in [Fuse](https://fuseais.com) from your own
agents and apps. A Fuse knowledge base downloads as a single `.sqlite` file
that holds your documents' passages, a keyword index, vector embeddings, and
metadata. Drop the file into a folder, point fuse-kb at it, and your agent can
search it with cited, page-level results. It works offline, with no server to
run.

```bash
pip install "fuse-kb[mcp]"
mkdir kbs && mv ~/Downloads/handbook.sqlite kbs/
fuse-kb research handbook "how much parental leave do we offer?"
```

The same tools also work with hosted Fuse backends. An agent built against a
downloaded file can move to a hosted knowledge base without code changes.

## Contents

**New to Fuse knowledge bases?** Start with the
[getting started guide](docs/getting-started.md). If your documents include
employee information, read [Handling KB files safely](docs/handling-kb-files.md)
before downloading. Something not working? See [Troubleshooting](docs/troubleshooting.md).

- [Use it from Python](#use-it-from-python)
- [Give it to an agent](#give-it-to-an-agent): Claude, OpenAI, MCP, agent skill
- [Choosing providers](#choosing-providers): vector search, reranking, LLMs
- [How search works](#how-search-works)
- [Command line](#command-line)
- [Security](#security)
- [File format](docs/FORMAT.md)
- Guides: [Getting started](docs/getting-started.md), [Handling KB files safely](docs/handling-kb-files.md), [Troubleshooting](docs/troubleshooting.md)

## Use it from Python

```python
from fuse_kb import KnowledgeBase

with KnowledgeBase("kbs/handbook.sqlite") as kb:
    result = kb.research("how much parental leave do we offer?")
    for hit in result.hits:
        print(f"[{hit.label}] {hit.chunk_text[:200]}")
    print(result.notes)   # explains any fallback, e.g. vector search unavailable
```

`research()` tries several strategies and keeps the first convincing one.
For one specific method, use `search()`:

```python
kb.search("Form W-4", mode="lexical", phrase=True)          # exact phrase
kb.search("time off after having a baby", mode="dense")     # by meaning
kb.search(mode="filter", filters={"document_name": "Employee Handbook.pdf",
                                  "page_number": [3, 5]})   # metadata only
kb.pages(document_id=hit.document_id, page_start=4, page_end=5)
kb.documents()                                              # what's inside
```

For a folder of KBs, use `KBLibrary`. It addresses KBs by name (the file name
without `.sqlite`) and reads `$FUSE_KB_PATH`, or `./kbs` by default:

```python
from fuse_kb import KBLibrary

library = KBLibrary("kbs/")
library.names                    # ['benefits', 'handbook']
library.get("handbook").research("dental coverage")
```

## Give it to an agent

### Claude (Anthropic API)

`Toolkit` turns a library into tool definitions and runs the calls.

```python
import anthropic
from fuse_kb import KBLibrary, Toolkit

toolkit = Toolkit(KBLibrary("kbs/"))
client = anthropic.Anthropic()
messages = [{"role": "user", "content": "How much parental leave do we offer?"}]

while True:
    response = client.beta.messages.create(
        model="claude-opus-5-5",
        max_tokens=16000,
        tools=toolkit.anthropic_tools(),
        messages=messages,
        # On a policy decline, retry on a fallback model within the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    messages.append({"role": "assistant", "content": response.content})
    if response.stop_reason != "tool_use":
        break
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": block.id,
         "content": toolkit.call_json(block.name, block.input)}
        for block in response.content if block.type == "tool_use"
    ]})

print("".join(b.text for b in response.content if b.type == "text"))
```

### OpenAI and compatible APIs

```python
tools = toolkit.openai_tools()
# for each tool call: toolkit.call_json(call.function.name, json.loads(call.function.arguments))
```

### Tools the agent gets

| Tool | What it does |
|---|---|
| `kb_list` | Lists the KBs with descriptions, so the agent can pick one. |
| `kb_research` | The default: hybrid search with automatic fallbacks. |
| `kb_search` | One method: `hybrid`, `lexical` (exact terms), `dense` (meaning), or `filter` (metadata). |
| `kb_read_pages` | Reads up to 6 consecutive pages of a document, for tables or lists cut off at a passage edge. |
| `kb_documents` | Lists the documents in a KB. |
| `kb_answer` | Writes a grounded answer with citations. Appears only when an LLM is configured. |

Tool definitions match your setup. KB names become an enum, and reranking and
HyDE options appear only when a reranker or LLM is configured, so the agent is
never offered options that can't work. Errors come back as `{"error": "..."}`
for the agent to read.

### MCP: Claude Desktop, Claude Code, and other clients

```bash
claude mcp add fuse-kb -- fuse-kb mcp --path /absolute/path/to/kbs
```

Or in a client's MCP config file:

```json
{
  "mcpServers": {
    "fuse-kb": {
      "command": "fuse-kb",
      "args": ["mcp", "--path", "/absolute/path/to/kbs"]
    }
  }
}
```

Use `--transport streamable-http --port 8765` to serve over HTTP instead of stdio.

### Agent skill

`fuse-kb skill` prints a `SKILL.md` that teaches an agent the search workflow:
which tool to use when, how to read scores, and how to cite. To install it
for Claude Code:

```bash
fuse-kb skill --install ~/.claude/skills
```

## Choosing providers

Keyword search works out of the box, with no setup and no network calls.
Vector search, reranking, and LLM features each need a provider. Every
provider is optional and chosen explicitly. Nothing calls a cloud service
unless you configure one, or the KB was embedded with a cloud model and you
run a vector search.

### Vector search: the KB decides

A KB can only be searched by vector with the model that embedded it, so each
file records its embedder and fuse-kb picks it automatically. Run
`fuse-kb info <kb>` to see which one your file needs:

| `embedder` shown | Install | Needs |
|---|---|---|
| `bedrock` | `pip install "fuse-kb[bedrock]"` | AWS credentials with Bedrock access |
| `ollama:<model>` | nothing extra | [Ollama](https://ollama.com) running, with `ollama pull <model>` |
| `sentence-transformers:<model>` | `pip install "fuse-kb[local]"` | Downloads the model on first use |
| `openai:<model>` | `pip install "fuse-kb[openai]"` | `OPENAI_API_KEY` |

If the embedder isn't available, hybrid search still works on keywords alone
and says so in `notes`. Fully offline use needs a KB built with a local
embedder (Ollama or sentence-transformers).

### Reranking: optional, improves ordering

```python
KnowledgeBase(path, reranker="cohere")                          # Cohere v3.5 on AWS Bedrock
KnowledgeBase(path, reranker="cross-encoder:BAAI/bge-reranker-v2-m3")  # local, fuse-kb[local]
```

### LLM: for HyDE and grounded answers

```python
KnowledgeBase(path, llm="anthropic")              # Claude (fuse-kb[anthropic])
KnowledgeBase(path, llm="ollama:qwen3:8b")        # local
KnowledgeBase(path, llm="bedrock:<model-id>")     # any Bedrock chat model
KnowledgeBase(path, llm="openai:<model>")         # OpenAI or compatible (OPENAI_BASE_URL)
```

Environment variables set the same options for the CLI, MCP server, and
`KBLibrary`: `FUSE_KB_PATH`, `FUSE_KB_EMBEDDER`, `FUSE_KB_RERANKER`,
`FUSE_KB_LLM`, `AWS_REGION`, `OLLAMA_HOST`, `OPENAI_BASE_URL`.

You can also pass your own provider object: subclass `fuse_kb.Embedder`,
`fuse_kb.Reranker`, or `fuse_kb.LLM` and implement one method.

## How search works

```
question ─┬─ keyword search (SQLite FTS5, BM25) ─┐
          └─ vector search (sqlite-vec)         ─┴─ Reciprocal Rank Fusion ─ rerank (optional) ─ results
```

1. **Keyword and vector search** each find up to 50 candidates. Metadata
   filters apply inside both.
2. **Reciprocal Rank Fusion (RRF)** merges the two rankings. Each passage
   scores 1 ÷ (k + rank) in each list it appears in, and the scores add up,
   so passages near the top of both lists win.
3. **Reranking** (if configured) reads the top 20 against the question.
   `fusion="rerank"` makes the reranker's order final. `fusion="rrf"` folds
   its ranking in as a third RRF list, so a strong exact match isn't dropped
   on one judgment. Prefer `rrf` for codes, form numbers, and amounts.

`rrf_k` (default 60) sets how much the very top positions matter. For
example, passage A is 1st for keywords but 25th for vectors, and passage B is
8th in both:

| `rrf_k` | A | B | Winner |
|---|---|---|---|
| 10 | 0.129 | 0.118 | A: one standout ranking counts for a lot |
| 60 | 0.029 | 0.030 | B: agreement between rankings counts more |

**HyDE** (`hyde=True`, needs an LLM) has the LLM write a hypothetical answer
and searches vectors with that instead of the question. It helps when the
question's wording differs from the documents'.

**`research()`** tries hybrid + HyDE (with an LLM), then plain hybrid, then
keyword-only, and keeps the first result whose best rerank score reaches 0.3.
Without a reranker, the first strategy that finds anything wins.

## Command line

```bash
fuse-kb list                                   # KBs in ./kbs or $FUSE_KB_PATH
fuse-kb info handbook                          # contents and required embedder
fuse-kb docs handbook --contains benefits
fuse-kb research handbook "dental coverage"
fuse-kb search handbook "W-4" --mode lexical --phrase
fuse-kb search handbook --mode filter --filter page_number=3-5 --filter document_id=abc123
fuse-kb search handbook "plan premiums" --reranker cohere --fusion rrf --rrf-k 30
fuse-kb pages handbook --document-id abc123 --pages 4-5
fuse-kb answer handbook "dental coverage" --llm anthropic
fuse-kb mcp --path ./kbs
```

Every command accepts `--json`, and a KB argument can be a name or a path to
a `.sqlite` file.

## Security

- **Files open read-only.** fuse-kb never writes to a KB file.
- **A KB file can't run code.** The embedder a file records is used only if
  it's one of the built-in kinds. Custom provider classes load only from your
  own code, flags, or environment.
- **Agents can't reach other files.** Tools address KBs by name, and only
  names discovered on the configured path resolve.
- **Filters can't inject SQL.** Filter columns come from a fixed list and
  values are always bound parameters.
- **A KB file contains your documents' text.** Treat it with the same care as
  the documents themselves. See [Handling KB files safely](docs/handling-kb-files.md).
- **Encrypted files are optional.** A PGP-encrypted download
  (`handbook.sqlite.gpg`) opens like any other KB: fuse-kb decrypts it in
  memory with your GnuPG keyring, or with a key from `FUSE_KB_PGP_KEY` /
  `FUSE_KB_PGP_KEY_FILE` and `FUSE_KB_PGP_PASSPHRASE` for servers and agents.
  No readable copy is written to disk. Needs GnuPG and Python 3.11+.

## License

MIT
