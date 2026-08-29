"""Semantic retrieval against real pgvector, and its isolation guarantees.

These run against PostgreSQL with the `vector` extension — the whole point is the
`<=>` cosine operator and the ownership join, neither of which a mock would test.
Embeddings come from the deterministic fake so no paid call is made; ranking is
still meaningful because the fake places texts that share vocabulary closer.
"""

import io

from fastapi.testclient import TestClient

from app.tests.conftest import auth
from app.tests.factories import make_text_pdf

TRANSPORT_NOTES = (
    b"TCP provides reliable delivery using sequence numbers and acknowledgements. "
    b"When packet loss is detected the congestion window is halved, which drains "
    b"the bottleneck queue. Additive increase then probes for capacity again."
)
DNS_NOTES = (
    b"DNS resolves human readable domain names into IP addresses. Resolvers query "
    b"root servers, then top level domain servers, then authoritative servers."
)
SECURITY_NOTES = (
    b"A buffer overflow occurs when a program writes past the end of an allocated "
    b"region. Stack canaries and ASLR make exploitation harder."
)


def upload(client: TestClient, token: str, course_id: str, name: str, data: bytes) -> str:
    response = client.post(
        f"/api/v1/courses/{course_id}/documents",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def search(client: TestClient, token: str, course_id: str, query: str, top_k: int = 5):
    return client.post(
        f"/api/v1/courses/{course_id}/search",
        json={"query": query, "top_k": top_k},
        headers=auth(token),
    )


def make_course(client: TestClient, token: str, title: str, code: str) -> str:
    response = client.post(
        "/api/v1/courses", json={"title": title, "code": code}, headers=auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestSemanticSearch:
    def test_returns_the_relevant_document(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        upload(client, token, course_id, "dns.txt", DNS_NOTES)

        response = search(client, token, course_id, "congestion window halved on loss")

        assert response.status_code == 200
        results = response.json()["results"]
        assert results
        assert results[0]["document_name"] == "transport.txt"

    def test_results_are_ranked_by_similarity(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        upload(client, token, course_id, "dns.txt", DNS_NOTES)

        results = search(
            client, token, course_id, "acknowledgements and sequence numbers"
        ).json()["results"]

        scores = [result["similarity"] for result in results]
        assert scores == sorted(scores, reverse=True)
        assert all(
            result["distance"] == round(1 - result["similarity"], 6) for result in results
        )

    def test_results_carry_citation_metadata(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        document_id = upload(
            client,
            token,
            course_id,
            "lecture.pdf",
            make_text_pdf(
                [
                    "Page one covers addressing and subnetting.",
                    "TCP halves the congestion window after packet loss occurs.",
                ]
            ),
        )

        results = search(
            client, token, course_id, "congestion window packet loss"
        ).json()["results"]

        top = results[0]
        assert top["document_id"] == document_id
        assert top["document_name"] == "lecture.pdf"
        # Page number comes from the stored chunk, and points at the right page.
        assert top["page_number"] == 2
        assert isinstance(top["chunk_index"], int)

    def test_top_k_limits_the_result_count(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        upload(client, token, course_id, "dns.txt", DNS_NOTES)
        upload(client, token, course_id, "security.txt", SECURITY_NOTES)

        assert (
            len(search(client, token, course_id, "networks", top_k=1).json()["results"])
            == 1
        )
        assert (
            len(search(client, token, course_id, "networks", top_k=2).json()["results"])
            <= 2
        )

    def test_top_k_is_bounded(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        assert search(client, token, course_id, "anything", top_k=0).status_code == 422
        assert search(client, token, course_id, "anything", top_k=999).status_code == 422

    def test_blank_query_is_rejected(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        assert search(client, token, course_id, "   ").status_code == 422

    def test_overlong_query_is_rejected(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        assert search(client, token, course_id, "x" * 5000).status_code == 422

    def test_empty_course_returns_no_results(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        response = search(client, token, course_id, "congestion control")

        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_only_ready_documents_are_searched(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        """A failed document's text must never surface in results."""
        from app.tests.factories import make_image_only_pdf

        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)
        failed_id = upload(client, token, course_id, "scan.pdf", make_image_only_pdf())

        assert (
            client.get(f"/api/v1/documents/{failed_id}", headers=auth(token)).json()[
                "processing_status"
            ]
            == "failed"
        )

        results = search(client, token, course_id, "congestion window").json()["results"]
        assert all(result["document_id"] != failed_id for result in results)

    def test_search_requires_authentication(
        self, client: TestClient, course_id: str
    ) -> None:
        response = client.post(
            f"/api/v1/courses/{course_id}/search", json={"query": "anything"}
        )
        assert response.status_code == 401


class TestIsolation:
    def test_cannot_search_another_users_course(
        self, client: TestClient, token: str, other_token: str, course_id: str
    ) -> None:
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        response = search(client, other_token, course_id, "congestion window")

        assert response.status_code == 404

    def test_another_users_chunks_never_appear_in_results(
        self, client: TestClient, token: str, other_token: str, course_id: str
    ) -> None:
        """The decisive test: identical material in both accounts, and each user's
        search must return only their own chunks."""
        upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        other_course = make_course(client, other_token, "Their Networks", "CS999")
        other_document = upload(
            client, other_token, other_course, "transport.txt", TRANSPORT_NOTES
        )

        mine = search(client, token, course_id, "congestion window halved").json()[
            "results"
        ]
        theirs = search(
            client, other_token, other_course, "congestion window halved"
        ).json()["results"]

        assert mine and theirs
        assert all(result["document_id"] != other_document for result in mine)
        assert all(result["document_id"] == other_document for result in theirs)

    def test_course_a_cannot_retrieve_course_b_chunks(
        self, client: TestClient, token: str, course_id: str
    ) -> None:
        """Same user, two courses. Cross-course retrieval is not a Phase 3 feature."""
        transport_id = upload(client, token, course_id, "transport.txt", TRANSPORT_NOTES)

        security_course = make_course(client, token, "Software Security", "SEC420")
        security_id = upload(
            client, token, security_course, "security.txt", SECURITY_NOTES
        )

        # Ask the security course about a networks topic.
        results = search(
            client, token, security_course, "congestion window halved on loss"
        ).json()["results"]

        assert all(result["document_id"] != transport_id for result in results)
        assert all(result["document_id"] == security_id for result in results)
