"""Course CRUD and ownership isolation."""

import uuid

from fastapi.testclient import TestClient

from app.tests.conftest import auth


def test_create_course(client: TestClient, token: str) -> None:
    response = client.post(
        "/api/v1/courses",
        json={
            "title": "Software Security",
            "code": "SEC420",
            "description": "Threat modelling.",
        },
        headers=auth(token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Software Security"
    assert body["code"] == "SEC420"
    assert body["document_count"] == 0
    assert body["created_at"] and body["updated_at"]


def test_create_course_requires_a_title(client: TestClient, token: str) -> None:
    response = client.post("/api/v1/courses", json={"title": "   "}, headers=auth(token))
    assert response.status_code == 422


def test_create_course_allows_an_omitted_code(client: TestClient, token: str) -> None:
    response = client.post(
        "/api/v1/courses", json={"title": "Reading Group"}, headers=auth(token)
    )

    assert response.status_code == 201
    assert response.json()["code"] == ""


def test_duplicate_course_code_is_rejected(client: TestClient, token: str) -> None:
    client.post(
        "/api/v1/courses", json={"title": "First", "code": "CS340"}, headers=auth(token)
    )
    response = client.post(
        "/api/v1/courses", json={"title": "Second", "code": "CS340"}, headers=auth(token)
    )

    assert response.status_code == 409


def test_two_users_may_share_a_course_code(
    client: TestClient, token: str, other_token: str
) -> None:
    """The uniqueness constraint is per user, not global."""
    first = client.post(
        "/api/v1/courses",
        json={"title": "Networks", "code": "CS340"},
        headers=auth(token),
    )
    second = client.post(
        "/api/v1/courses",
        json={"title": "Networks", "code": "CS340"},
        headers=auth(other_token),
    )

    assert first.status_code == 201
    assert second.status_code == 201


def test_list_courses_returns_only_your_own(
    client: TestClient, token: str, other_token: str
) -> None:
    client.post("/api/v1/courses", json={"title": "Mine"}, headers=auth(token))
    client.post("/api/v1/courses", json={"title": "Theirs"}, headers=auth(other_token))

    mine = client.get("/api/v1/courses", headers=auth(token)).json()
    theirs = client.get("/api/v1/courses", headers=auth(other_token)).json()

    assert [course["title"] for course in mine] == ["Mine"]
    assert [course["title"] for course in theirs] == ["Theirs"]


def test_read_one_course(client: TestClient, token: str, course_id: str) -> None:
    response = client.get(f"/api/v1/courses/{course_id}", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["id"] == course_id


def test_update_course(client: TestClient, token: str, course_id: str) -> None:
    response = client.patch(
        f"/api/v1/courses/{course_id}",
        json={"title": "Computer Networks II"},
        headers=auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Computer Networks II"
    # Untouched fields survive a partial update.
    assert body["code"] == "CS340"


def test_delete_course(client: TestClient, token: str, course_id: str) -> None:
    assert (
        client.delete(f"/api/v1/courses/{course_id}", headers=auth(token)).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/courses/{course_id}", headers=auth(token)).status_code == 404
    )


def test_unknown_course_is_404(client: TestClient, token: str) -> None:
    response = client.get(f"/api/v1/courses/{uuid.uuid4()}", headers=auth(token))
    assert response.status_code == 404


def test_course_endpoints_require_authentication(
    client: TestClient, course_id: str
) -> None:
    assert client.get("/api/v1/courses").status_code == 401
    assert client.post("/api/v1/courses", json={"title": "X"}).status_code == 401
    assert client.get(f"/api/v1/courses/{course_id}").status_code == 401
    assert (
        client.patch(f"/api/v1/courses/{course_id}", json={"title": "X"}).status_code
        == 401
    )
    assert client.delete(f"/api/v1/courses/{course_id}").status_code == 401


def test_cannot_read_another_users_course(
    client: TestClient, other_token: str, course_id: str
) -> None:
    """404, not 403 — another user's course is indistinguishable from a missing one."""
    response = client.get(f"/api/v1/courses/{course_id}", headers=auth(other_token))
    assert response.status_code == 404


def test_cannot_update_another_users_course(
    client: TestClient, token: str, other_token: str, course_id: str
) -> None:
    response = client.patch(
        f"/api/v1/courses/{course_id}",
        json={"title": "Hijacked"},
        headers=auth(other_token),
    )
    assert response.status_code == 404

    unchanged = client.get(f"/api/v1/courses/{course_id}", headers=auth(token)).json()
    assert unchanged["title"] == "Computer Networks"


def test_cannot_delete_another_users_course(
    client: TestClient, token: str, other_token: str, course_id: str
) -> None:
    assert (
        client.delete(
            f"/api/v1/courses/{course_id}", headers=auth(other_token)
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/courses/{course_id}", headers=auth(token)).status_code == 200
    )
