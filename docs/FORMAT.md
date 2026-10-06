# Knowledge-base file format (fuse-kb/1)

A fuse-kb knowledge base is one SQLite 3 database file, conventionally named
`<name>.sqlite`. It needs two extensions: FTS5, which ships with SQLite, and
[sqlite-vec](https://github.com/asg017/sqlite-vec) for the vector table.
fuse-kb opens files read-only and never modifies them.

## Tables

### `chunks` (required)

One row per passage.

| Column | Type | Meaning |
|---|---|---|
| `chunk_id` | INTEGER PRIMARY KEY | Passage ID; also the rowid for `chunks_fts` and `chunks_vec`. |
| `document_id` | TEXT NOT NULL | Stable ID of the source document. |
| `document_name` | TEXT | Display name, usually the original file name. |
| `source` | TEXT | Where the document came from: a URL, `s3://` URI, or `filename:<name>`. |
| `mime_type` | TEXT | Source document type. |
| `page_number` | INTEGER | 1-based page within the document. |
| `total_pages` | INTEGER | Page count of the document. |
| `chunk_offset` | INTEGER | Position of the passage within its page, for ordering. |
| `word_count` | INTEGER | Words in `chunk_text`. |
| `chunk_text` | TEXT NOT NULL | The passage text. Tables appear as Markdown. |
| `content_hash` | TEXT | Hash of the source content, for change detection. |
| `ingest_timestamp` | TEXT | ISO 8601 time the passage was produced. |
| `classification_category` | TEXT | Document category, for example `Insurance Policy`. |
| `classification_confidence` | REAL | Confidence in the category, 0 to 1. |
| `document_domain` | TEXT | Broad domain, for example `insurance` or `hr`. |
| `jurisdiction_country` | TEXT | ISO country code the content applies to. |
| `jurisdiction_subdivision` | TEXT | State or region code. |

Metadata columns may be NULL. Readers must not fail on unknown extra columns.

### `chunks_fts` (required)

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_text, document_name,
    content='chunks', content_rowid='chunk_id',
    tokenize='porter unicode61');
```

An external-content FTS5 index over `chunks`. Rebuild it after loading:
`INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')`.

### `chunks_vec` (optional)

```sql
CREATE VIRTUAL TABLE chunks_vec USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding float[1024]);
```

One embedding per passage, keyed by `chunk_id`. The declared width must match
the embedding model's output. A file without this table, or with it empty,
supports keyword and metadata search only.

### `entities` (optional)

```sql
CREATE TABLE entities (chunk_id INTEGER, entity_type TEXT,
                       entity_value TEXT, confidence REAL);
```

Named entities found in each passage (organizations, dates, amounts, and so on).

### `_meta` (recommended)

```sql
CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT);
```

| Key | Meaning |
|---|---|
| `format` | `fuse-kb/1` for this version. Missing means `fuse-kb/1`. |
| `embed_spec` | The embedder that produced `chunks_vec`, as a provider spec (below). |
| `embed_dims` | Embedding width, matching `chunks_vec`. |
| `embed_model` | Free-text model description (informational). |
| `description` | One line saying what the KB covers. Shown to agents by `kb_list`. |
| `build_started`, `build_finished` | ISO 8601 build times. |
| `row_count_chunks`, `row_count_entities`, `row_count_chunks_vec` | Counts at build time. |

Values are informational except `embed_spec` and `embed_dims`, which readers
use to embed queries in the same vector space as the passages. Builders
should not record server file paths, hostnames, or credentials here: the file
is meant to be shared.

## Embedder specs

`embed_spec` must be one of these built-in forms:

| Spec | Model |
|---|---|
| `bedrock` | Amazon Titan Text Embeddings v2 (`amazon.titan-embed-text-v2:0`) |
| `bedrock:<model-id>` | Another Bedrock embedding model |
| `ollama:<model>` | An Ollama embedding model, for example `ollama:mxbai-embed-large` |
| `sentence-transformers:<model>` | A Hugging Face sentence-transformers model, normalized |
| `openai:<model>` | An OpenAI or OpenAI-compatible embedding model |

Readers ignore any other value, so a file can't make a reader load arbitrary
code. Files built before `embed_spec` existed record `embed_model =
BedrockProvider`, which readers treat as `bedrock`.

## Compatibility

Files are forward compatible within `fuse-kb/1`: new optional columns,
tables, or `_meta` keys may be added. A breaking change will use a new
`format` value.
