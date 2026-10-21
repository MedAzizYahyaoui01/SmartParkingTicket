"""The assistant: offline rules in 3 languages, and the Claude tool loop (with a fake client)."""

from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.assistant.claude import SYSTEM_PROMPT
from tests.conftest import API_KEY, credit, make_reading, register

CHAT = "/api/v1/chat"
READING = "/api/v1/sensors/reading"
SENSORS = {"X-API-Key": API_KEY}


# --- fake Claude ---------------------------------------------------------------


def message(stop_reason: str, *content: dict[str, Any]) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": list(content),
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }
    )


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def tool_use(name: str, args: dict, call_id: str = "toolu_1") -> dict:
    return {"type": "tool_use", "id": call_id, "name": name, "input": args}


class FakeMessages:
    """Replays scripted responses and records every request."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> BetaMessage:
        # Copy: the engine keeps appending to the same lists
        self.requests.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClaude:
    def __init__(self, script: list[Any]) -> None:
        self.beta = type("Beta", (), {})()
        self.beta.messages = FakeMessages(script)


def api_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))


def make_client(store, history, account_repo, claude=None, **settings_kw):
    settings = Settings(
        _env_file=None,
        api_key=API_KEY,
        gate_mode="account",
        chat_engine="claude" if claude else "rules",
        **settings_kw,
    )
    app = create_app(
        settings,
        store=store,
        history=history,
        account_repo=account_repo,
        claude_client=claude,
        background_tasks=False,
    )
    return TestClient(app)


@pytest.fixture
def rules_api(store, history, account_repo):
    with make_client(store, history, account_repo) as c:
        c.post(READING, json=make_reading(occupied=(True, False, False, False)), headers=SENSORS)
        yield c


@pytest.fixture
def user(rules_api, account_repo):
    headers = register(rules_api)
    credit(account_repo, headers, rules_api, 5000)
    return headers


def say(client, message: str, headers: dict | None = None, conversation_id=None) -> dict:
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = client.post(CHAT, json=body, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


# --- offline rules ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "lang", "expected"),
    [
        ("Is there a free spot?", "en", "3 of 4 spots are free"),
        ("Il y a une place libre ?", "fr", "3 place(s) libre(s) sur 4"),
        ("فما بلاصة فارغة؟", "ar", "فما 3 بلايص فارغة من 4"),
    ],
)
def test_rules_answer_in_the_users_language(rules_api, message, lang, expected):
    reply = say(rules_api, message)
    assert reply["engine"] == "rules"
    assert reply["language"] == lang
    assert expected in reply["reply"]


def test_rules_ask_anonymous_users_to_identify(rules_api):
    reply = say(rules_api, "open the gate please")
    assert reply["actions"] == [{"type": "login_required"}]
    assert "QR code" in reply["reply"]


def test_rules_open_the_gate_by_voice_in_darija(rules_api, user):
    reply = say(rules_api, "عسلامة، حل الباب", user)
    assert reply["language"] == "ar"
    assert {"type": "barrier_opening", "direction": "entry"} in reply["actions"]
    command = rules_api.post(READING, json=make_reading(gate=True), headers=SENSORS).json()
    assert command["barrier_command"] == "open"


def test_rules_reserve_in_french_with_a_duration(rules_api, user):
    reply = say(rules_api, "Je voudrais réserver la place P3 pour 30 min", user)
    assert "P3" in reply["reply"] and "30 min" in reply["reply"]
    assert reply["actions"][0]["type"] == "reservation_created"
    me = rules_api.get("/api/v1/me", headers=user).json()
    assert me["reservation"]["spot_id"] == "P3"


def test_rules_balance_and_leaving(rules_api, user):
    assert "5.000 TND" in say(rules_api, "what's my balance?", user)["reply"]
    say(rules_api, "open", user)
    reply = say(rules_api, "I'm leaving", user)
    assert "Goodbye Amine" in reply["reply"]
    assert {"type": "barrier_opening", "direction": "exit"} in reply["actions"]


def test_rules_top_up_opens_the_checkout_in_the_app_only(rules_api, user):
    reply = say(rules_api, "I want to top up 20", user)
    assert reply["actions"] == [{"type": "open_top_up", "amount": 20000}]

    code = rules_api.post("/api/v1/me/access-code", headers=user).json()["code"]
    token = rules_api.post("/api/v1/gate/identify", json={"code": code}).json()["token"]
    kiosk = say(rules_api, "recharger mon compte", {"Authorization": f"Bearer {token}"})
    assert kiosk["actions"] == []
    assert "application" in kiosk["reply"]


def test_rules_explain_low_credit_at_the_gate(rules_api):
    broke = register(rules_api, "broke@example.com", "Sara")
    reply = say(rules_api, "ouvrez la barrière svp", broke)
    assert "Rechargez" in reply["reply"]
    assert reply["actions"] == [{"type": "open_top_up", "amount": None}]


def test_unknown_request_gets_help(rules_api):
    reply = say(rules_api, "blah blah")
    assert "Try:" in reply["reply"]


def test_chat_info_reports_the_engine(rules_api):
    assert rules_api.get("/api/v1/chat/info").json()["engine"] == "rules"


# --- Claude tool loop ------------------------------------------------------------


def test_claude_runs_tools_and_answers(store, history, account_repo):
    fake = FakeClaude(
        [
            message("tool_use", text("Je regarde."), tool_use("parking_status", {})),
            message("end_turn", text("Il reste 3 places libres : P2, P3 et P4.")),
        ]
    )
    with make_client(store, history, account_repo, claude=fake) as c:
        c.post(READING, json=make_reading(occupied=(True, False, False, False)), headers=SENSORS)
        reply = say(c, "Bonjour, il reste de la place ?")

    assert reply["engine"] == "claude"
    assert reply["language"] == "fr"
    assert reply["reply"] == "Il reste 3 places libres : P2, P3 et P4."

    first, second = fake.beta.messages.requests
    assert first["model"] == "claude-opus-5-5"
    assert first["system"] == SYSTEM_PROMPT
    assert all(t["strict"] for t in first["tools"])
    assert first["fallbacks"] == "default"
    # Turn = user message + who is speaking (a system message, never an edit)
    assert [m["role"] for m in first["messages"]] == ["user", "system"]
    assert "not identified" in first["messages"][1]["content"]
    # The tool result went back to Claude with the live state
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and '"free": 3' in result["content"]


def test_claude_conversation_is_append_only(store, history, account_repo):
    fake = FakeClaude(
        [message("end_turn", text("Hello!")), message("end_turn", text("You have 0.000 TND."))]
    )
    with make_client(store, history, account_repo, claude=fake) as c:
        cid = say(c, "hi")["conversation_id"]
        user = register(c)
        say(c, "my balance?", user, conversation_id=cid)

    first, second = fake.beta.messages.requests
    # Everything sent the first time is sent again unchanged, in the same order
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["system"] == first["system"] and second["tools"] == first["tools"]
    # The sign-in is told with a new system message after the new user message
    new = second["messages"][len(first["messages"]) + 1 :]
    assert [m["role"] for m in new] == ["user", "system"]
    assert "signed in as Amine" in new[1]["content"]


def test_claude_acts_only_for_the_signed_in_user(store, history, account_repo):
    fake = FakeClaude(
        [
            message("tool_use", tool_use("open_gate", {"direction": "auto"})),
            message("end_turn", text("Welcome, the barrier is opening.")),
        ]
    )
    with make_client(store, history, account_repo, claude=fake) as c:
        c.post(READING, json=make_reading(), headers=SENSORS)
        user = register(c)
        credit(account_repo, user, c, 5000)
        reply = say(c, "open the gate", user)

    assert {"type": "barrier_opening", "direction": "entry"} in reply["actions"]


def test_claude_api_failure_falls_back_to_the_rules(store, history, account_repo):
    fake = FakeClaude([api_error()])
    with make_client(store, history, account_repo, claude=fake) as c:
        c.post(READING, json=make_reading(), headers=SENSORS)
        reply = say(c, "any free spot?")

    assert reply["engine"] == "rules"
    assert "4 of 4 spots are free" in reply["reply"]


def test_claude_failure_after_an_action_does_not_repeat_it(store, history, account_repo):
    fake = FakeClaude(
        [message("tool_use", tool_use("open_gate", {"direction": "auto"})), api_error()]
    )
    with make_client(store, history, account_repo, claude=fake) as c:
        c.post(READING, json=make_reading(), headers=SENSORS)
        user = register(c)
        credit(account_repo, user, c, 5000)
        reply = say(c, "open the gate", user)
        me = c.get("/api/v1/me", headers=user).json()

    assert reply["reply"] == "The barrier is opening."
    assert me["stay"] is not None  # entered once, not entered-then-charged-on-exit
    assert [a["type"] for a in reply["actions"]] == ["barrier_opening"]


def test_claude_refusal_gets_a_polite_reply(store, history, account_repo):
    fake = FakeClaude([message("refusal")])
    with make_client(store, history, account_repo, claude=fake) as c:
        reply = say(c, "something off topic")
    assert reply["engine"] == "claude"
    assert reply["reply"].startswith("Sorry")
