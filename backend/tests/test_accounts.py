"""Accounts: sign-up, sign-in, tokens, profile, pricing and the wallet statement."""

import pytest

from app.security import (
    InvalidTokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.accounts import InvalidAccessCodeError
from tests.conftest import register

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"


def test_password_hash_round_trip():
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)
    assert hash_password("correct horse") != stored  # random salt


def test_token_round_trip_and_expiry():
    token = create_token("SP-ABCDEFGH", "kiosk", 60, "secret", now=1_000)
    with pytest.raises(InvalidTokenError):
        decode_token(token, "secret")  # expired long ago
    fresh = create_token("SP-ABCDEFGH", "kiosk", 60, "secret")
    claims = decode_token(fresh, "secret")
    assert (claims.uid, claims.scope) == ("SP-ABCDEFGH", "kiosk")
    with pytest.raises(InvalidTokenError):
        decode_token(fresh, "other-secret")


def test_register_creates_an_account_with_a_uid_and_an_empty_wallet(client):
    response = client.post(
        REGISTER,
        json={
            "name": "Amine",
            "email": "Amine@Example.com",
            "password": "secret-pass",
            "plate": "123 TU 4567",
            "language": "fr",
        },
    )

    assert response.status_code == 201
    user = response.json()["user"]
    assert user["uid"].startswith("SP-") and len(user["uid"]) == 11
    assert user["email"] == "amine@example.com"
    assert (user["balance"], user["currency"], user["status"]) == (0, "TND", "low")
    assert user["language"] == "fr"
    assert "password" not in str(response.json())


def test_email_can_only_be_used_once(client):
    register(client)
    response = client.post(
        REGISTER, json={"name": "B", "email": "amine@example.com", "password": "secret-pass"}
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"name": "A", "email": "not-an-email", "password": "secret-pass"},
        {"name": "A", "email": "a@example.com", "password": "short"},
        {"name": "", "email": "a@example.com", "password": "secret-pass"},
        {"name": "A", "email": "a@example.com", "password": "secret-pass", "language": "de"},
    ],
)
def test_invalid_registration_returns_422(client, body):
    assert client.post(REGISTER, json=body).status_code == 422


def test_login(client):
    register(client)

    ok = client.post(LOGIN, json={"email": "AMINE@example.com", "password": "secret-pass"})
    assert ok.status_code == 200
    assert ok.json()["user"]["name"] == "Amine"

    bad = client.post(LOGIN, json={"email": "amine@example.com", "password": "nope"})
    unknown = client.post(LOGIN, json={"email": "who@example.com", "password": "secret-pass"})
    assert bad.status_code == unknown.status_code == 401


def test_me_needs_a_valid_token(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_profile_update(client):
    user = register(client)
    response = client.patch("/api/v1/me", json={"plate": "99 TU 1", "language": "ar"}, headers=user)

    assert response.status_code == 200
    assert (response.json()["plate"], response.json()["language"]) == ("99 TU 1", "ar")
    assert response.json()["name"] == "Amine"


def test_pricing_is_public(client, settings):
    body = client.get("/api/v1/pricing").json()
    assert body["hourly_rate"] == settings.hourly_rate
    assert body["currency"] == "TND"


def test_parking_fee_rules(client):
    accounts = client.app.state.accounts
    assert accounts.parking_fee(10) == 0  # free minutes
    assert accounts.parking_fee(15) == 0
    assert accounts.parking_fee(16) == 500  # one started 15-min block at 2 TND/h
    assert accounts.parking_fee(30) == 500
    assert accounts.parking_fee(31) == 1000
    assert accounts.parking_fee(75) == 2000


def test_access_code_is_single_use(client):
    user = register(client)
    code = client.post("/api/v1/me/access-code", headers=user).json()
    assert len(code["code"]) == 6 and code["qr_payload"] == f"SPGATE:{code['code']}"

    first = client.post("/api/v1/gate/identify", json={"code": code["qr_payload"]})
    assert first.status_code == 200
    assert first.json()["user"]["name"] == "Amine"
    again = client.post("/api/v1/gate/identify", json={"code": code["code"]})
    assert again.status_code == 401


def test_a_new_access_code_replaces_the_previous_one(client):
    user = register(client)
    old = client.post("/api/v1/me/access-code", headers=user).json()["code"]
    new = client.post("/api/v1/me/access-code", headers=user).json()["code"]

    assert client.post("/api/v1/gate/identify", json={"code": old}).status_code == 401
    assert client.post("/api/v1/gate/identify", json={"code": new}).status_code == 200


def test_access_code_expires(client, settings):
    accounts = client.app.state.accounts
    code = accounts.new_access_code("SP-TESTUSER").code
    now = accounts.clock
    accounts.clock = lambda: now() + settings.access_code_ttl_s + 1
    with pytest.raises(InvalidAccessCodeError):
        accounts.redeem_access_code(code, "kiosk-1")


def test_wrong_codes_are_rate_limited(client):
    for _ in range(5):
        assert client.post("/api/v1/gate/identify", json={"code": "000000"}).status_code == 401
    assert client.post("/api/v1/gate/identify", json={"code": "000000"}).status_code == 429


def test_kiosk_session_cannot_pay_or_change_the_profile(client):
    user = register(client)
    code = client.post("/api/v1/me/access-code", headers=user).json()["code"]
    token = client.post("/api/v1/gate/identify", json={"code": code}).json()["token"]
    kiosk = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/me", headers=kiosk).status_code == 200
    assert client.patch("/api/v1/me", json={"name": "X"}, headers=kiosk).status_code == 403
    assert (
        client.post("/api/v1/payments/checkout", json={"amount": 10000}, headers=kiosk).status_code
        == 403
    )
    assert client.post("/api/v1/me/access-code", headers=kiosk).status_code == 403
