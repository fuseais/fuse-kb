# Getting started with Fuse knowledge bases

This guide takes you from a knowledge base in Fuse to asking it questions on
your own computer, in Claude, or in an agent you build. It takes about 15
minutes.

## What you're working with

A **knowledge base (KB)** is a set of documents you've loaded into Fuse,
prepared so they can be searched by meaning, not just by keyword. Fuse splits
each document into passages, tags them (document type, topics, names, dates,
amounts), and indexes them.

You can use a KB in two ways:

- **Online in Fuse**, where you can test searches as you build the KB.
- **As a downloaded file**, a single `.sqlite` file you can search offline,
  on your own machine, with no Fuse account needed at query time. This guide
  covers the downloaded file.

The file contains the text of your documents. Before you download one, read
[Handling KB files safely](handling-kb-files.md), especially if your documents
include employee information.

## 1. Download your knowledge base

In Fuse, open the knowledge base and download it. You'll get either:

- `handbook.sqlite`, a standard file, ready to use. Best for testing and for
  documents that aren't sensitive.
- `handbook.sqlite.gpg`, an encrypted file, if your organization chose
  encrypted downloads. See [Encrypted downloads](handling-kb-files.md#encrypted-downloads)
  for the one-time setup.

The file name (without `.sqlite`) becomes the knowledge base's name.

## 2. Install fuse-kb

fuse-kb needs Python 3.10 or newer (3.11 or newer for encrypted files).
Install it as a command-line tool:

```bash
pipx install "fuse-kb[mcp]"
```

`uv tool install "fuse-kb[mcp]"` works too. If you're adding fuse-kb to a
Python project instead, use `pip install "fuse-kb[mcp]"` in that project's
environment.

Then make a folder for your knowledge bases and move the file there:

```bash
mkdir ~/kbs
mv ~/Downloads/handbook.sqlite ~/kbs/
```

## 3. Ask your first question

```bash
fuse-kb research handbook "how many weeks of parental leave do we offer?" --path ~/kbs
```

You'll get the most relevant passages, each with its document name and page:

```
strategy: hybrid
3 hits · 31 ms

[1] Employee Handbook.pdf p.12
    score_final=0.03252  score_rrf=0.03252  score_lexical=-6.214
    Parental leave: employees receive sixteen weeks of paid parental leave after…
```

Higher `score_final` means a better match within one result list.

To skip typing `--path` every time, set it once in your shell profile:

```bash
export FUSE_KB_PATH=~/kbs
```

Other useful commands:

```bash
fuse-kb list                          # every KB in your folder
fuse-kb info handbook                 # what's inside, and what search needs
fuse-kb docs handbook                 # the documents in a KB
```

If you see a line starting with `note:`, read it. The most common one is
"Keyword search only", which means meaning-based search isn't set up yet on
this computer. Keyword results are still useful; step 5 explains how to turn
on the rest.

## 4. Connect it to Claude

fuse-kb includes an MCP server, which lets Claude search your knowledge bases
directly and cite the pages it used.

**Claude Code:**

```bash
claude mcp add fuse-kb -- fuse-kb mcp --path ~/kbs
```

**Claude Desktop:** open Settings, then Developer, then Edit Config, and add:

```json
{
  "mcpServers": {
    "fuse-kb": {
      "command": "/full/path/to/fuse-kb",
      "args": ["mcp", "--path", "/full/path/to/kbs"]
    }
  }
}
```

Use full paths: run `which fuse-kb` (macOS and Linux) or `where fuse-kb`
(Windows) to find the command's location. Restart Claude Desktop, then ask
something like "What does our handbook say about parental leave?" Claude will
search the KB and cite the documents and pages it used.

To teach Claude how to search well (which tool to use when, how to cite), also
install the fuse-kb skill:

```bash
fuse-kb skill --install ~/.claude/skills
```

**Your own agent or app:** see [Give it to an agent](../README.md#give-it-to-an-agent)
in the README for Python examples with the Claude and OpenAI APIs.

## 5. Get the best results

Out of the box, fuse-kb searches by keyword. Two optional additions improve
results noticeably.

**Search by meaning.** This finds passages that answer a question even when
they use different words ("time off after having a baby" finds "parental
leave"). It needs the same model that indexed your KB. Run `fuse-kb info
handbook` and look at the `embedder` line:

| `embedder` | What to do |
|---|---|
| `bedrock` | `pipx inject fuse-kb boto3`, and have AWS credentials with Bedrock access. Your question text is sent to AWS to be converted; your documents are not. |
| `ollama:<model>` | Install [Ollama](https://ollama.com) and run `ollama pull <model>`. Everything stays on your computer. |
| `sentence-transformers:<model>` | `pipx inject fuse-kb sentence-transformers`. The model downloads once, then runs on your computer. |

**Reranking.** A reranker reads the top passages against your question and
puts the best ones first:

```bash
fuse-kb research handbook "dental coverage for dependents" --reranker cohere
```

`cohere` runs on AWS Bedrock and sends your question plus the top 20 passages
to AWS. For a reranker that runs on your computer, use
`--reranker cross-encoder:BAAI/bge-reranker-v2-m3` (after
`pipx inject fuse-kb sentence-transformers`).

## Next steps

- [Handling KB files safely](handling-kb-files.md): what's in a file, encrypted
  downloads, and what data leaves your computer with each feature.
- [Troubleshooting](troubleshooting.md): what each message means and how to fix it.
- [README](../README.md): the full Python API, agent tools, and search options.
