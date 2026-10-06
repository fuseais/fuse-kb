# Troubleshooting

Find the message you're seeing, then follow the fix. Messages that start with
`note:` aren't errors: the search still ran, with a fallback.

## Search notes

### "Keyword search only."

Meaning-based search was skipped, so results come from keyword matching
alone. The rest of the note says why:

| The note continues with | Fix |
|---|---|
| "This KB was embedded with bedrock … needs the 'boto3' package" | `pipx inject fuse-kb boto3` (or `pip install "fuse-kb[bedrock]"`). |
| "Embedding the query with bedrock failed: Unable to locate credentials" | Configure AWS credentials (`aws configure`, or your organization's SSO) with Bedrock access. |
| "Embedding the query with ollama:… failed: Can't reach http://localhost:11434…" | Start Ollama, or set `OLLAMA_HOST` if it runs elsewhere. |
| "…returned HTTP 404: model … not found" | Run `ollama pull <model>` with the model named in the note. |
| "This KB doesn't record which model embedded it" | Set `FUSE_KB_EMBEDDER` to the model the KB was built with, or ask your Fuse admin for a fresh download. |
| "…makes 768-dim vectors, but this KB stores 1024-dim vectors" | A different model is configured than the one that built the KB. Remove `FUSE_KB_EMBEDDER` or `--embedder` and let fuse-kb pick the KB's own model. |
| "Vector search is turned off (embedder=None)" | Your code or configuration disabled it on purpose. |
| "This KB has no vector index." | The KB was built for keyword search only. |

### "Reranking skipped, showing RRF order"

The reranker failed, so results use the order from combining keyword and
meaning search. With `cohere`, check AWS credentials and Bedrock access in
your region (`AWS_REGION`). With `cross-encoder:…`, install
`sentence-transformers`.

### "HyDE skipped"

HyDE needs an LLM. Configure one with `--llm` or `FUSE_KB_LLM`, or turn HyDE off.

## Finding knowledge bases

### "No knowledge bases found"

fuse-kb found no `.sqlite` or `.sqlite.gpg` files. Check the folder: pass
`--path /path/to/kbs` or set `FUSE_KB_PATH`. The default is a `kbs` folder in
the current directory.

### "Several knowledge bases are available; name one of: …"

Name the KB you want, for example `fuse-kb research handbook "…"`. Agents
pick one with the `kb` argument.

### "No knowledge base named '…'"

The name is the file name without `.sqlite` (or `.sqlite.gpg`). Run
`fuse-kb list` to see the exact names.

### "… is not a fuse-kb knowledge base" or "… is not a SQLite database"

The file isn't a Fuse KB, or the download was incomplete. Download it again.

## Encrypted files

### "… is encrypted. Install GnuPG"

Install GnuPG: `brew install gnupg` on macOS, Gpg4win on Windows, or your
Linux package manager.

### "Couldn't decrypt …: this file was encrypted for a key that isn't available here"

The file was encrypted for a different key than the one available. Check
that the private key matches the public key uploaded to Fuse. On servers,
check `FUSE_KB_PGP_KEY` or `FUSE_KB_PGP_KEY_FILE`. If the key was rotated,
download the KB again.

### "the passphrase is wrong"

Check `FUSE_KB_PGP_PASSPHRASE`, or retype the passphrase when GnuPG asks for it.

### "Opening encrypted KB files needs Python 3.11 or newer"

Encrypted files are decrypted in memory, which needs Python 3.11 or newer.
Reinstall fuse-kb with a newer Python, for example
`pipx install --python python3.12 "fuse-kb[mcp]"`.

## Installation

### "This Python's sqlite3 module can't load extensions"

Some Python builds, notably the one bundled with macOS, can't load SQLite
extensions. Install Python from python.org, Homebrew, uv, pyenv, or conda,
and reinstall fuse-kb with it.

### "This provider needs the '…' package"

Install the extra named in the message, for example
`pip install "fuse-kb[bedrock]"`, or with pipx, `pipx inject fuse-kb boto3`.

## Claude and other assistants

### The fuse-kb tools don't appear in Claude Desktop

- Use full paths for both `command` and `--path` in the config file. Claude
  Desktop doesn't use your shell's `PATH`. Find the command with
  `which fuse-kb` (or `where fuse-kb` on Windows).
- Restart Claude Desktop after editing the config.
- Run the command from the config in a terminal. If it prints an error,
  that's what Claude Desktop hit too.

### Claude cites the wrong passages, or misses an obvious one

- For exact terms, names, form numbers, and codes, ask Claude to search for
  the exact phrase. The `kb_search` tool has a `phrase` option for this.
- With a reranker configured, try `fusion: "rrf"`, which keeps strong
  keyword matches near the top.
- Make sure meaning-based search is working: look for a "Keyword search only"
  note in `fuse-kb research` output.
- If a passage is cut off mid-table, Claude can read the neighboring page
  with `kb_read_pages`.

## Still stuck?

Run the failing command with `--json` and include its output, plus the output
of `fuse-kb info <kb>`, when you contact Fuse support. Remove any document
text you can't share first.
