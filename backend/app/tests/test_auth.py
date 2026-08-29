"""Authentication: registration, login, session identity and isolation."""

import uuid

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.tests.conftest import auth, register, unique_email


def test_register_returns_a_usable_token(client: TestClient) -> None:
    email = unique_email()
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Ghaida Ahmed", "email": email, "password": "correct-horse-9"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0

    me = client.get("/api/v1/auth/me", headers=auth(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_register_never_returns_the_password(client: TestClient) -> None:
    email = unique_email()
    token = register(client, email, "correct-horse-9")
    body = client.get("/api/v1/auth/me", headers=auth(token)).json()

    assert "password" not in body
    assert "hashed_password" not in body


def test_password_is_hashed_not_stored_raw(client: TestClient, session: Session) -> None:
    email = unique_email()
    register(client, email, "correct-horse-9")

    user = session.scalar(select(User).where(User.email == email))
    assert user is not None
    assert user.hashed_password != "correct-horse-9"
    assert user.hashed_password.startswith("$2b$")


def test_duplicate_registration_is_rejected(client: TestClient) -> None:
    email = unique_email()
    register(client, email)

    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Impostor", "email": email, "password": "another-pass-1"},
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_duplicate_registration_is_case_insensitive(client: TestClient) -> None:
    email = unique_email()
    register(client, email)

    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Impostor", "email": email.upper(), "password": "another-pass-1"},
    )

    assert response.status_code == 409


def test_login_with_valid_credentials(client: TestClient) -> None:
    email = unique_email()
    register(client, email, "correct-horse-9")

    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "correct-horse-9"}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_with_wrong_password_is_rejected(client: TestClient) -> None:
    email = unique_email()
    register(client, email, "correct-horse-9")

    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password."


def test_login_for_unknown_email_gives_the_same_message(client: TestClient) -> None:
    """Identical wording, so the endpoint cannot be used to enumerate accounts."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email("ghost"), "password": "correct-horse-9"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password."


def test_short_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Test", "email": unique_email(), "password": "short"},
    )
    assert response.status_code == 422


def test_protected_endpoint_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_protected_endpoint_rejects_a_garbage_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers=auth("not-a-real-jwt"))
    assert response.status_code == 401


def test_protected_endpoint_rejects_a_token_signed_with_another_key(
    client: TestClient,
) -> None:
    forged = jwt.encode({"sub": str(uuid.uuid4())}, "a" * 40)
    response = client.get("/api/v1/auth/me", headers=auth(forged))
    assert response.status_code == 401


def test_two_users_see_their_own_identity(client: TestClient) -> None:
    first_email, second_email = unique_email("a"), unique_email("b")
    first = register(client, first_email)
    second = register(client, second_email)

    assert (
        client.get("/api/v1/auth/me", headers=auth(first)).json()["email"] == first_email
    )
    assert (
        client.get("/api/v1/auth/me", headers=auth(second)).json()["email"]
        == second_email
    )


class TestSecretKeyValidation:
    """A blank signing key makes every session token forgeable.

    `.env.example` ships `SECRET_KEY=` empty, so copying it to `.env` overrides the
    default with "" — and PyJWT signs and verifies happily with an empty key.
    """

    def test_blank_key_falls_back_in_development(self) -> None:
        from app.core.config import Settings

        settings = Settings(SECRET_KEY="   ", ENVIRONMENT="development")

        assert settings.SECRET_KEY.strip()

    def test_blank_key_is_fatal_outside_development(self) -> None:
        import pytest as _pytest

        from app.core.config import Settings

        with _pytest.raises(ValueError, match="SECRET_KEY is empty"):
            Settings(SECRET_KEY="", ENVIRONMENT="production")

    def test_dev_default_is_fatal_outside_development(self) -> None:
        import pytest as _pytest

        from app.core.config import Settings

        with _pytest.raises(ValueError, match="real value"):
            Settings(
                SECRET_KEY="dev-only-insecure-secret-change-me",
                ENVIRONMENT="production",
            )

    def test_short_key_is_fatal_outside_development(self) -> None:
        import pytest as _pytest

        from app.core.config import Settings

        with _pytest.raises(ValueError, match="at least"):
            Settings(SECRET_KEY="too-short", ENVIRONMENT="production")

    def test_a_token_signed_with_an_empty_key_is_rejected(self) -> None:
        """The concrete attack the validation prevents."""
        import uuid as _uuid

        import jwt as _jwt

        from app.core.security import decode_access_token

        forged = _jwt.encode({"sub": str(_uuid.uuid4())}, "")

        assert decode_access_token(forged) is None
