"""Grounded answering: context construction, citations and the no-answer path."""

import io

from fastapi.testclient import TestClient

from app.tests.conftest import auth
from app.tests.factories import make_text_pdf
from app.tests.fakes import FakeLLMProvider

TRANSPORT_NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"When packet loss is detected the congestion window is halved, which drains "
    b"the bottleneck queue. Additive increase then probes for capacity again."
)


def upload(client: TestClient, token: str, course_id: str, name: str, data: bytes) -> str:
    response = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask(client: TestClient, token: str, course_id: str, question: str):
    return client.post(
        f"/api/v1/courses/{course_id}/ask",
        json={"question": question},
        headers=auth(token),
    )


class TestGroundedAnswers:
    def test_returns_the_generated_answer(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        llm.answer = "The window is halved to drain the bottleneck queue."

        response = ask(client, token, course_id, "congestion window halved packet loss")

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "The window is halved to drain the bottleneck queue."
        assert body["is_grounded"] is True

    def test_retrieved_context_is_passed_to_the_model(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        ask(client, token, course_id, "congestion window halved packet loss")

        assert llm.call_count == 1
        prompt = llm.last_user_content
        # The excerpt itself, and the question, both reach the model.
        assert "congestion window is halved" in prompt
        assert "congestion window halved packet loss" in prompt

    def test_the_system_prompt_forbids_outside_knowledge(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        ask(client, token, course_id, "congestion window halved packet loss")

        system = llm.calls[0][0]
        assert system.role == "system"
        assert "ONLY" in system.content
        assert "Do not use outside knowledge" in system.content
        assert "not invent document names, page numbers" in system.content


class TestCitations:
    def test_citations_come_from_stored_chunks(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        document_id = upload(
            client,
            token,
            course_id,
            "lecture.pdf",
            make_text_pdf(
                [
                    "Page one introduces addressing and subnetting concepts.",
                    "TCP halves the congestion window after packet loss is detected.",
                ]
            ),
        )
        # The model returns text with no citation in it whatsoever.
        llm.answer = "Some answer text with no citation anywhere in it."

        body = ask(
            client, token, course_id, "congestion window halved packet loss"
        ).json()

        assert body["citations"]
        citation = body["citations"][0]
        assert citation["document_id"] == document_id
        assert citation["document_name"] == "lecture.pdf"
        # Page number is real, taken from the chunk row, not written by the model.
        assert citation["page_number"] == 2
        assert citation["chunk_id"]
        assert citation["excerpt"]

    def test_citation_excerpts_match_the_source_text(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        body = ask(
            client, token, course_id, "congestion window halved packet loss"
        ).json()

        source = TRANSPORT_NOTES.decode()
        for citation in body["citations"]:
            fragment = citation["excerpt"].rstrip("…").strip()
            assert fragment[:60] in " ".join(source.split())

    def test_a_hallucinated_page_number_cannot_reach_the_response(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        llm.answer = "See Imaginary Textbook.pdf page 999 for details."

        body = ask(
            client, token, course_id, "congestion window halved packet loss"
        ).json()

        # Provenance comes from our rows, never from the model's prose.
        assert all(c["document_name"] == "transport.txt" for c in body["citations"])
        # None rather than 999 — and none rather than 1, which this previously
        # asserted. A TXT file has no pages, so any number here would be invented,
        # whether the model made it up or the column defaulted to it.
        assert all(c["page_number"] is None for c in body["citations"])


class TestNoAnswerFallback:
    def test_no_relevant_context_skips_the_model(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        """Below the relevance threshold, no paid call is made at all."""
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        body = ask(
            client,
            token,
            course_id,
            "sourdough baking hydration levels overnight proving",
        ).json()

        assert llm.call_count == 0
        assert body["is_grounded"] is False
        assert body["citations"] == []
        assert "couldn't find enough information" in body["answer"]

    def test_empty_course_skips_the_model(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        body = ask(client, token, course_id, "anything at all").json()

        assert llm.call_count == 0
        assert body["is_grounded"] is False
        assert body["citations"] == []


class TestValidationAndIsolation:
    def test_blank_question_is_rejected(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        assert ask(client, token, course_id, "   ").status_code == 422

    def test_overlong_question_is_rejected(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        assert ask(client, token, course_id, "x" * 5000).status_code == 422
        assert llm.call_count == 0

    def test_ask_requires_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/ask", json={"question": "hi"}
        )
        assert response.status_code == 401

    def test_cannot_ask_over_another_users_course(
        self,
        client: TestClient,
        token: str,
        other_token: str,
        course_id: str,
        llm: FakeLLMProvider,
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        response = ask(client, other_token, course_id, "congestion window halved")

        assert response.status_code == 404
        assert llm.call_count == 0

    def test_answers_never_draw_on_another_courses_material(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        other = client.post(
            "/api/v1/courses",
            json={"title": "Software Security", "code": "SEC420"},
            headers=auth(token),
        ).json()["id"]
        upload(
            client,
            token,
            other,
            "security.txt",
            b"A buffer overflow writes past an allocated region. Canaries help.",
        )

        body = ask(client, token, other, "congestion window halved packet loss").json()

        assert all(c["document_name"] != "transport.txt" for c in body["citations"])
        if llm.call_count:
            assert "congestion window is halved" not in llm.last_user_content


class TestWeakMatchFiltering:
    """A chunk that merely cleared the absolute floor must not become a citation."""

    def test_chunks_far_below_the_best_match_are_dropped(self) -> None:
        import uuid

        from app.services.rag.rag_service import _drop_weak_matches
        from app.services.rag.retrieval import RetrievedChunk

        def chunk(similarity: float) -> RetrievedChunk:
            return RetrievedChunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                document_name="d.pdf",
                page_number=1,
                chunk_index=0,
                content="x",
                similarity=similarity,
            )

        # Observed live: a DNS question against a congestion-control lecture.
        kept = _drop_weak_matches([chunk(s) for s in (0.7275, 0.5494, 0.5447)], 0.15)

        assert [round(c.similarity, 4) for c in kept] == [0.7275]

    def test_close_matches_are_all_kept(self) -> None:
        import uuid

        from app.services.rag.rag_service import _drop_weak_matches
        from app.services.rag.retrieval import RetrievedChunk

        def chunk(similarity: float) -> RetrievedChunk:
            return RetrievedChunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                document_name="d.pdf",
                page_number=1,
                chunk_index=0,
                content="x",
                similarity=similarity,
            )

        kept = _drop_weak_matches([chunk(s) for s in (0.77, 0.69, 0.65)], 0.15)

        assert len(kept) == 3

    def test_empty_input_is_handled(self) -> None:
        from app.services.rag.rag_service import _drop_weak_matches

        assert _drop_weak_matches([], 0.15) == []

    def test_citations_only_cover_chunks_close_to_the_best_match(
        self, client, token: str, course_id: str, llm
    ) -> None:
        """End-to-end: an off-topic document in the same course must not be cited."""
        import io

        from app.tests.conftest import auth

        for name, body in (
            (
                "transport.txt",
                b"TCP halves the congestion window when packet loss occurs.",
            ),
            ("baking.txt", b"Sourdough proofing temperature and hydration percentages."),
        ):
            client.post(
                f"/api/v1/courses/{course_id}/documents",
                files={"file": (name, io.BytesIO(body), "text/plain")},
                headers=auth(token),
            )

        body = client.post(
            f"/api/v1/courses/{course_id}/ask",
            json={"question": "congestion window halved packet loss"},
            headers=auth(token),
        ).json()

        assert body["citations"]
        assert all(c["document_name"] == "transport.txt" for c in body["citations"])


class TestCitationPageNumbers:
    """A citation must never claim a page the source does not have.

    TXT and Markdown chunks are stored as page 1 because a chunk needs *some*
    value. Reporting that as "page 1" is invented precision, and the README says
    it is omitted. The quiz, flashcard, knowledge-map and study-guide surfaces
    already did this through `page_number_for`; `/ask` and `/search` passed the
    raw column and showed "p1" for a text file. Both directions are pinned here
    so the two paths cannot drift apart again.
    """

    def test_a_txt_citation_reports_no_page(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        llm.answer = "The window is halved."

        citations = ask(
            client, token, course_id, "congestion window halved packet loss"
        ).json()["citations"]

        assert citations, "expected at least one citation"
        for citation in citations:
            assert citation["document_name"].endswith(".txt")
            assert citation["page_number"] is None, (
                "a TXT file has no pages; 1 would be fabricated"
            )

    def test_a_markdown_citation_reports_no_page(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        upload(client, token, course_id, "transport.md", TRANSPORT_NOTES)
        llm.answer = "The window is halved."

        citations = ask(
            client, token, course_id, "congestion window halved packet loss"
        ).json()["citations"]
        assert citations
        assert all(c["page_number"] is None for c in citations)

    def test_a_pdf_citation_keeps_its_real_page(
        self, client: TestClient, token: str, course_id: str, llm: FakeLLMProvider
    ) -> None:
        """The fix must not throw away genuine page numbers."""
        pdf = make_text_pdf(
            [
                "Introduction to reliable transport and acknowledgements.",
                "When packet loss is detected the congestion window is halved, "
                "which drains the bottleneck queue.",
            ]
        )
        upload(client, token, course_id, "lecture.pdf", pdf)
        llm.answer = "The window is halved."

        citations = ask(
            client, token, course_id, "congestion window halved packet loss"
        ).json()["citations"]
        assert citations
        for citation in citations:
            assert citation["document_name"].endswith(".pdf")
            assert isinstance(citation["page_number"], int)
            assert citation["page_number"] >= 1

    def test_search_results_follow_the_same_rule(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        """`/search` builds its own result shape and had the same bug."""
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        response = client.post(
            f"/api/v1/courses/{course_id}/search",
            json={"query": "congestion window halved", "top_k": 3},
            headers=auth(token),
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert results
        assert all(r["page_number"] is None for r in results)

    def test_search_keeps_pdf_pages(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        pdf = make_text_pdf(
            [
                "Reliable transport and acknowledgements.",
                "The congestion window is halved when loss is detected.",
            ]
        )
        upload(client, token, course_id, "lecture.pdf", pdf)

        results = client.post(
            f"/api/v1/courses/{course_id}/search",
            json={"query": "congestion window halved", "top_k": 3},
            headers=auth(token),
        ).json()["results"]
        assert results
        assert all(isinstance(r["page_number"], int) for r in results)

    def test_the_retrieved_chunk_carries_the_file_type(
        self, client: TestClient, token: str, course_id: str, session
    ) -> None:
        """`page_number_for` needs the format. Taking it from the retrieval join
        avoids a second query per citation."""
        import uuid as _uuid

        from app.services.rag.retrieval import RetrievalService
        from app.tests.fakes import FakeEmbeddingProvider

        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        user_id = _uuid.UUID(
            client.get("/api/v1/auth/me", headers=auth(token)).json()["id"]
        )

        chunks = RetrievalService(session).search(
            user_id,
            _uuid.UUID(course_id),
            FakeEmbeddingProvider().embed_query("congestion window"),
            top_k=3,
        )
        assert chunks
        assert all(chunk.file_type == "txt" for chunk in chunks)
