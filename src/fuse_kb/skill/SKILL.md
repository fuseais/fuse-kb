---
name: fuse-kb
description: Answer questions from Fuse knowledge bases (document collections indexed for search) using the kb_* tools, the fuse-kb CLI, or the fuse_kb Python library. Use when a question should be answered from a company's documents, policies, contracts, manuals, or other files loaded as a knowledge base, and when the user wants cited, page-level sources.
---

# Searching Fuse knowledge bases

A knowledge base (KB) is a document collection split into passages. Each
passage carries its document name, page number, source, and metadata such as
category and jurisdiction. Search combines keyword matching with meaning-based
(vector) matching, and can rerank results with a model that reads each passage
against the question.

The same tools work whether a KB is a local `.sqlite` file or a hosted Fuse
backend. Nothing in this workflow depends on which one you are using.

## How to access the tools

Use whichever of these is available, in this order:

1. **MCP or agent tools** named `kb_list`, `kb_research`, `kb_search`,
   `kb_read_pages`, `kb_documents`, and possibly `kb_answer`.
2. **The CLI**: `fuse-kb research <kb> "<question>"`, `fuse-kb search`,
   `fuse-kb pages`, `fuse-kb docs`, `fuse-kb list`. Add `--json` for
   machine-readable output.
3. **Python**: `from fuse_kb import KBLibrary` then
   `KBLibrary().get("<kb>").research("<question>")`.

## Workflow

1. **Pick the KB.** If you don't know which KB covers the question, call
   `kb_list` and choose by description. If there is only one, you can omit
   the name.
2. **Research.** Call `kb_research` with the question in natural language. It
   runs hybrid search and falls back to other strategies until it finds
   convincing passages. Its `strategy` and `attempts` fields say what worked.
3. **Read the notes.** If a result has `notes`, read them. They explain
   fallbacks, for example "Keyword search only" when vector search isn't set up
   on this machine. Keyword-only results are still valid; phrase follow-up
   searches with the exact terms the documents are likely to use.
4. **Follow up when needed.**
   - Exact terms, names, codes, form numbers, IDs: `kb_search` with
     `mode: "lexical"`. Add `phrase: true` for an exact phrase.
   - A passage's table, list, or code is visibly cut off, or it says "see the
     table below": `kb_read_pages` with its `document_id` and the page before
     or after. Don't do this for ordinary prose that runs past a passage edge.
   - "What documents do you have about X": `kb_documents`, or `kb_search` with
     `mode: "filter"` and metadata filters.
   - Several angles of one question: run two or three searches with different
     wordings (one natural, one keyword-dense) and merge the results by
     `chunk_id`.
5. **Answer with citations.** Use only what the passages say. Cite each claim
   as [ref], and end with a sources list: document name, page, and the source
   or document_id. If the passages don't answer the question, say the KB
   doesn't cover it. Don't fill gaps from general knowledge.

## Ranking options

These appear only when a reranker is configured.

- `fusion: "rerank"` (default): the reranker's order is final. Best for
  conversational questions where relevance is a judgment call.
- `fusion: "rrf"`: the reranker's ranking is combined with the keyword and
  vector rankings, so a passage that matches an exact term strongly isn't
  dropped on one reranker judgment. Prefer it for codes, form numbers,
  policy or statute references, and amounts, or to retry when "rerank"
  results look off-topic.
- `rrf_k` (default 60): around 10 lets one standout match in a single ranking
  win; 60 or higher favors passages both rankings agree on. Leave it unset
  unless you are deliberately tuning.

## Reading scores

- `score_final`: the score that set the order. Compare within one result
  list only, never across searches or modes.
- `score_rerank`: relevance from 0 to 1. Above about 0.3 is usually a real
  match; below about 0.1 usually isn't.
- `score_lexical` is more negative for stronger keyword matches;
  `score_dense` is a distance, so lower is closer.
- `rank_rrf` and `rank_rerank` show how far reranking moved a passage.

## Filters

Filter keys: `document_id`, `document_name`, `source`, `mime_type`,
`page_number`, `total_pages`, `classification_category`, `document_domain`,
`jurisdiction_country`, `jurisdiction_subdivision`, `content_hash`. A value
matches exactly, a list matches any item, and `page_number: [first, last]`
is a page range. Get exact values from earlier results or `kb_documents`
rather than guessing; values are case-sensitive.
