"""Wallet top-ups through the simulated card gateway."""

import pytest

from tests.conftest import register

CHECKOUT = "/api/v1/payments/checkout"
VISA_OK = "4242 4242 4242 4242"


def card(number: str = VISA_OK, **overrides) -> dict:
    return {
        "number": number,
        "exp_month": 12,
        "exp_year": 2099,
        "cvc": "123",
        "holder": "Amine",
    } | overrides


@pytest.fixture
def user(client):
    return register(client)


def pay(client, user, amount: int, card_body: dict) -> dict:
    payment = client.post(CHECKOUT, json={"amount": amount}, headers=user).json()
    assert payment["status"] == "requires_payment"
    response = client.post(
        f"/api/v1/payments/{payment['id']}/confirm", json=card_body, headers=user
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_successful_top_up_credits_the_wallet(client, user):
    result = pay(client, user, 20000, card())

    assert result["status"] == "succeeded"
    assert (result["card_brand"], result["card_last4"]) == ("Visa", "4242")
    assert result["receipt_no"].startswith("R-")
    assert result["balance_after"] == 20000
    me = client.get("/api/v1/me", headers=user).json()
    assert (me["balance"], me["status"]) == (20000, "ok")
    tx = client.get("/api/v1/me/transactions", headers=user).json()
    assert [(t["kind"], t["amount"]) for t in tx] == [("topup", 20000)]


def test_mastercard_is_recognised(client, user):
    assert pay(client, user, 5000, card("5555555555554444"))["card_brand"] == "Mastercard"


@pytest.mark.parametrize(
    ("number", "overrides", "reason"),
    [
        ("4000 0000 0000 0002", {}, "card_declined"),
        ("4000 0000 0000 9995", {}, "insufficient_funds"),
        ("4000 0000 0000 0069", {}, "expired_card"),
        ("4242 4242 4242 4241", {}, "invalid_number"),  # fails the Luhn check
        (VISA_OK, {"exp_year": 2001}, "expired_card"),
    ],
)
def test_failed_payment_leaves_the_wallet_unchanged(client, user, number, overrides, reason):
    result = pay(client, user, 10000, card(number, **overrides))

    assert (result["status"], result["failure_reason"]) == ("failed", reason)
    assert client.get("/api/v1/me", headers=user).json()["balance"] == 0
    assert client.get("/api/v1/me/transactions", headers=user).json() == []


def test_a_payment_is_processed_only_once(client, user):
    payment = client.post(CHECKOUT, json={"amount": 10000}, headers=user).json()
    url = f"/api/v1/payments/{payment['id']}/confirm"

    assert client.post(url, json=card(), headers=user).status_code == 200
    assert client.post(url, json=card(), headers=user).status_code == 409
    assert client.get("/api/v1/me", headers=user).json()["balance"] == 10000


def test_cannot_pay_someone_elses_checkout(client, user):
    payment = client.post(CHECKOUT, json={"amount": 10000}, headers=user).json()
    other = register(client, "sara@example.com", "Sara")

    response = client.post(f"/api/v1/payments/{payment['id']}/confirm", json=card(), headers=other)
    assert response.status_code == 404


@pytest.mark.parametrize("amount", [100, 4999, 500_001])
def test_amount_must_be_within_bounds(client, user, amount):
    assert client.post(CHECKOUT, json={"amount": amount}, headers=user).status_code == 422


def test_card_number_and_cvc_are_never_stored(client, user, account_repo):
    pay(client, user, 10000, card())
    stored = str(account_repo.payments) + str(account_repo.transactions)
    assert "4242424242424242" not in stored and "4242 4242 4242 4242" not in stored
    assert "'cvc'" not in stored


def test_payment_history(client, user):
    pay(client, user, 10000, card())
    pay(client, user, 5000, card("4000000000000002"))

    history = client.get("/api/v1/payments", headers=user).json()
    assert {p["status"] for p in history} == {"succeeded", "failed"}
