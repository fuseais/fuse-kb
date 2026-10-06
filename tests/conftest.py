"""A small synthetic KB, built to the published file format, for every test."""
import hashlib
import math
import re
import sqlite3

import pytest
import sqlite_vec

from fuse_kb import Embedder, LLM, Reranker

DIMS = 16

SCHEMA = f"""
CREATE TABLE chunks (
    chunk_id INTEGER PRIMARY KEY, document_id TEXT NOT NULL, document_name TEXT,
    source TEXT, mime_type TEXT, page_number INTEGER, total_pages INTEGER,
    chunk_offset INTEGER, word_count INTEGER, chunk_text TEXT NOT NULL,
    content_hash TEXT, ingest_timestamp TEXT,
    classification_category TEXT, classification_confidence REAL,
    document_domain TEXT, jurisdiction_country TEXT, jurisdiction_subdivision TEXT
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_text, document_name, content='chunks', content_rowid='chunk_id',
    tokenize='porter unicode61');
CREATE VIRTUAL TABLE chunks_vec USING vec0(chunk_id INTEGER PRIMARY KEY,
                                           embedding float[{DIMS}]);
CREATE TABLE entities (chunk_id INTEGER, entity_type TEXT, entity_value TEXT,
                       confidence REAL);
CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT);
"""

# (document_id, name, page, text, category, country)
CHUNKS = [
    ("d1", "Employee Handbook.pdf", 1,
     "Parental leave: employees receive sixteen weeks of paid parental leave "
     "after one year of service.", "HR Policy", "US"),
    ("d1", "Employee Handbook.pdf", 2,
     "Vacation accrues at 1.5 days per month. Unused vacation carries over "
     "up to ten days.", "HR Policy", "US"),
    ("d1", "Employee Handbook.pdf", 3,
     "| Plan | Monthly premium |\n|---|---|\n| Gold | $630 |\n| Silver | $611 |",
     "HR Policy", "US"),
    ("d2", "Form W-4 Instructions.pdf", 1,
     "Form W-4 tells your employer how much federal income tax to withhold "
     "from your paycheck.", "Tax Form", "US"),
    ("d2", "Form W-4 Instructions.pdf", 2,
     "Step 3 claims dependents. Multiply qualifying children under age 17 by "
     "$2,000.", "Tax Form", "US"),
    ("d3", "Guía de Beneficios.pdf", 1,
     "El período de espera es de 30 días antes del primer pago del "
     "beneficio.", "Benefits Guide", "ES"),
]


def toy_vector(text: str) -> list[float]:
    """Deterministic bag-of-words hashing embedding (stand-in for a model)."""
    vec = [0.0] * DIMS
    for tok in re.findall(r"\w+", text.lower()):
        vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIMS] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class ToyEmbedder(Embedder):
    spec = "toy"
    dims = DIMS

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [toy_vector(t) for t in texts]


class ReverseReranker(Reranker):
    """Ranks candidates in exactly reverse order, to make fusion visible."""
    spec = "reverse"

    def rerank(self, query, documents, top_n):
        n = len(documents)
        return [(i, 1.0 - (n - 1 - i) / n) for i in reversed(range(n))][:top_n]


class EchoLLM(LLM):
    spec = "echo"

    def __init__(self, reply="The answer is in [1]."):
        self.reply, self.prompts = reply, []

    def complete(self, system, user, max_tokens=2048):
        self.prompts.append((system, user))
        return self.reply


def build_kb(path, meta=None, with_vectors=True):
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.executescript(SCHEMA)
    for i, (doc_id, name, page, text, cat, country) in enumerate(CHUNKS, 1):
        conn.execute(
            "INSERT INTO chunks (chunk_id, document_id, document_name, source, "
            "page_number, total_pages, chunk_offset, chunk_text, "
            "classification_category, document_domain, jurisdiction_country) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (i, doc_id, name, f"filename:{name}", page, 3, 0, text, cat,
             "hr" if doc_id != "d3" else "benefits", country))
        if with_vectors:
            conn.execute("INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                         (i, sqlite_vec.serialize_float32(toy_vector(text))))
    conn.execute("INSERT INTO entities VALUES (4, 'FORM', 'W-4', 0.9)")
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    meta = {"embed_spec": "ollama:toy-model", "embed_dims": str(DIMS),
            "description": "Synthetic test KB", **(meta or {})}
    conn.executemany("INSERT INTO _meta VALUES (?, ?)", meta.items())
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def kb_path(tmp_path):
    return str(build_kb(tmp_path / "handbook.sqlite"))


@pytest.fixture
def kb_dir(tmp_path):
    d = tmp_path / "kbs"
    d.mkdir()
    build_kb(d / "handbook.sqlite")
    build_kb(d / "benefits.sqlite", meta={"description": "Second KB"})
    (d / "notes.txt").write_text("not a kb")
    return str(d)
