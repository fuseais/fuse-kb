import sqlite3

import pytest

from fuse_kb import (EmbedderUnavailable, FuseKBError, KBFormatError,
                     KnowledgeBase, ProviderError)
from fuse_kb import search as S
from fuse_kb.providers import spec_from_meta
from fuse_kb.providers.embedders import resolve_embedder

from conftest import EchoLLM, ReverseReranker, ToyEmbedder, build_kb


def test_lexical_handles_punctuation_and_ranks_relevant_first(kb_path):
    with KnowledgeBase(kb_path, embedder=None) as kb:
        r = kb.search("¿cuál es el período de espera?", mode="lexical", k=3)
        assert r.hits[0].document_name == "Guía de Beneficios.pdf"
        assert r.hits[0].score_lexical is not None


def test_lexical_phrase(kb_path):
    with KnowledgeBase(kb_path, embedder=None) as kb:
        assert kb.search("paid parental leave", mode="lexical", phrase=True).hits
        assert not kb.search("leave parental paid", mode="lexical", phrase=True).hits


def test_filters_scalar_list_range_and_rejects_unknown_columns(kb_path):
    with KnowledgeBase(kb_path, embedder=None) as kb:
        hits = kb.search(mode="filter", filters={"jurisdiction_country": "ES"}).hits
        assert {h.document_id for h in hits} == {"d3"}
        hits = kb.search(mode="filter", filters={"document_id": ["d1", "d3"]}, k=50).hits
        assert {h.document_id for h in hits} == {"d1", "d3"}
        hits = kb.search(mode="filter", k=50,
                         filters={"document_id": "d1", "page_number": [2, 3]}).hits
        assert [h.page_number for h in hits] == [2, 3]
        with pytest.raises(ValueError, match="Can't filter"):
            kb.search("x", mode="lexical", filters={"chunk_text; DROP TABLE chunks": 1})


def test_dense_and_hybrid_with_an_explicit_embedder(kb_path):
    emb = ToyEmbedder()
    with KnowledgeBase(kb_path, embedder=emb) as kb:
        dense = kb.search("Form W-4 federal income tax withhold", mode="dense", k=2)
        assert dense.hits[0].document_id == "d2"
        hybrid = kb.search("W-4 withholding", k=3)
        assert hybrid.hits[0].document_id == "d2"
        assert all(h.rank_rrf is not None for h in hybrid.hits)
        assert not hybrid.notes


def test_hybrid_degrades_to_keywords_when_embedder_unavailable(kb_path):
    # The file names ollama:toy-model; nothing serves it, so the call fails.
    import os
    os.environ["OLLAMA_HOST"] = "http://127.0.0.1:9"
    try:
        with KnowledgeBase(kb_path) as kb:
            r = kb.search("parental leave")
            assert r.hits and r.hits[0].document_id == "d1"
            assert r.notes and r.notes[0].startswith("Keyword search only")
            with pytest.raises(EmbedderUnavailable):
                kb.search("parental leave", mode="dense")
    finally:
        del os.environ["OLLAMA_HOST"]


def test_dimension_mismatch_is_explained(kb_path):
    class Wide(ToyEmbedder):
        def embed(self, texts):
            return [[0.1] * 32 for _ in texts]
    with KnowledgeBase(kb_path, embedder=Wide()) as kb:
        with pytest.raises(EmbedderUnavailable, match="32-dim"):
            kb.search("anything", mode="dense")
        assert "Keyword search only" in kb.search("vacation").notes[0]


def test_fusion_modes_with_a_reranker(kb_path):
    with KnowledgeBase(kb_path, embedder=ToyEmbedder(),
                       reranker=ReverseReranker()) as kb:
        by_rerank = kb.search("vacation days carry over", k=3, fusion="rerank")
        by_rrf = kb.search("vacation days carry over", k=3, fusion="rrf")
        # The reverse reranker demotes the best keyword+vector match...
        assert by_rerank.hits[0].rank_rrf != 0
        # ...but RRF fusion keeps agreement between the lists in play.
        assert by_rrf.hits[0].rank_rrf == 0
        assert by_rrf.settings["fusion"] == "rrf"
        h = by_rerank.hits[0]
        assert h.score_final == h.score_rerank and h.rank_rerank == 0


def test_reranker_failure_falls_back_to_rrf_order(kb_path):
    class Broken(ReverseReranker):
        def rerank(self, *a, **kw):
            raise RuntimeError("service down")
    with KnowledgeBase(kb_path, embedder=ToyEmbedder(), reranker=Broken()) as kb:
        r = kb.search("vacation", k=2)
        assert len(r.hits) == 2 and "Reranking skipped" in r.notes[0]


def test_rrf_k_changes_scores_and_is_validated(kb_path):
    with KnowledgeBase(kb_path, embedder=ToyEmbedder()) as kb:
        lo = kb.search("vacation", rrf_k=10).hits[0].score_rrf
        hi = kb.search("vacation", rrf_k=100).hits[0].score_rrf
        assert lo > hi
        with pytest.raises(ValueError):
            kb.search("vacation", rrf_k=0)


def test_research_falls_through_and_reports_attempts(kb_path):
    llm = EchoLLM("A hypothetical paragraph about vacation accrual.")
    with KnowledgeBase(kb_path, embedder=ToyEmbedder(), llm=llm) as kb:
        r = kb.research("how much vacation do I get")
        assert r.strategy == "hybrid+hyde"
        assert r.hyde_text and r.hits
        assert [a["strategy"] for a in r.attempts] == ["hybrid+hyde"]


def test_pages_are_ordered_and_capped(kb_path):
    with KnowledgeBase(kb_path, embedder=None) as kb:
        r = kb.pages(document_id="d1", page_start=1, page_end=3)
        assert [h.page_number for h in r.hits] == [1, 2, 3]
        with pytest.raises(ValueError, match="at most 6"):
            kb.pages(document_id="d1", page_start=1, page_end=7)


def test_answer_cites_passages_and_detects_no_answer(kb_path):
    llm = EchoLLM()
    with KnowledgeBase(kb_path, embedder=None, llm=llm) as kb:
        a = kb.answer("parental leave length")
        assert a["answer"] == "The answer is in [1]." and not a["no_answer"]
        assert a["hits"][0]["ref"] == 1
        assert "[1] Employee Handbook.pdf p.1" in llm.prompts[-1][1]
    with KnowledgeBase(kb_path, embedder=None,
                       llm=EchoLLM("I cannot find that information in the knowledge base.")) as kb:
        assert kb.answer("moon landing")["no_answer"]
    with KnowledgeBase(kb_path, embedder=None) as kb:
        with pytest.raises(ProviderError, match="needs an LLM"):
            kb.answer("anything")


def test_info_and_documents(kb_path):
    with KnowledgeBase(kb_path, embedder=None) as kb:
        info = kb.info()
        assert (info["chunks"], info["documents"], info["dims"]) == (6, 3, 16)
        assert info["embedder"] == "ollama:toy-model"
        docs = kb.documents(name_contains="w-4")
        assert [d["document_id"] for d in docs] == ["d2"]


def test_file_is_opened_read_only(kb_path):
    with KnowledgeBase(kb_path, embedder=None) as kb:
        with pytest.raises(sqlite3.OperationalError):
            kb._conn.execute("DELETE FROM chunks")


def test_rejects_non_kb_files(tmp_path):
    plain = tmp_path / "plain.sqlite"
    sqlite3.connect(plain).execute("CREATE TABLE t (x)").connection.commit()
    with pytest.raises(KBFormatError):
        KnowledgeBase(plain)
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a database at all" * 100)
    with pytest.raises(KBFormatError):
        KnowledgeBase(junk)
    with pytest.raises(FuseKBError, match="not found"):
        KnowledgeBase(tmp_path / "missing.sqlite")


def test_spec_detection_never_trusts_custom_classes_from_files():
    assert spec_from_meta({"embed_spec": "ollama:mxbai-embed-large"}) == "ollama:mxbai-embed-large"
    assert spec_from_meta({"embed_model": "BedrockProvider"}) == "bedrock"
    assert spec_from_meta({"embed_spec": "os.system"}) is None
    with pytest.raises(ProviderError, match="Refusing"):
        resolve_embedder("os.getcwd", trusted=False)


def test_kb_file_cannot_select_a_custom_embedder(tmp_path):
    path = build_kb(tmp_path / "evil.sqlite", meta={"embed_spec": "os.getcwd"})
    with KnowledgeBase(path) as kb:
        assert kb.embed_spec is None
        r = kb.search("vacation")
        assert "doesn't record which model" in r.notes[0]


def test_fts5_query_escaping():
    assert S.fts5_query('say "hi" (now)') == '"say" OR "hi" OR "now"'
    assert S.fts5_query("") == '""'
    assert S.fts5_query("exact words", phrase=True) == '"exact words"'
