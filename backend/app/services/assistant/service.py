"""Conversations with the assistant.

Conversations live in memory (they are short: a driver at the gate) and expire after 30
minutes of silence. Each one keeps the full message list sent to Claude, append-only.
When the person behind a conversation changes (they scan their QR code at the kiosk, or
sign out), a system message says so, instead of rewriting the earlier turns.
"""

import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.services.accounts import AccountService, KeyedLocks
from app.services.assistant.claude import ClaudeEngine
from app.services.assistant.language import detect_language
from app.services.assistant.rules import RulesEngine
from app.services.assistant.tools import Caller, ToolBox
from app.services.gate import GateService
from app.services.parking import ParkingService
from app.services.stats import StatsService

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_S = 30 * 60
MAX_MESSAGES = 80  # a longer conversation starts afresh
MAX_CONVERSATIONS = 500


@dataclass
class Conversation:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    context: str | None = None  # who the last turn was from
    updated_at: float = 0.0


@dataclass
class ChatResult:
    conversation_id: str
    reply: str
    language: str
    engine: str
    actions: list[dict[str, Any]]


class AssistantService:
    def __init__(
        self,
        parking: ParkingService,
        accounts: AccountService,
        gate: GateService,
        stats: StatsService,
        claude: ClaudeEngine | None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.parking = parking
        self.accounts = accounts
        self.gate = gate
        self.stats = stats
        self.claude = claude
        self.rules = RulesEngine()
        self.clock = clock
        self.conversations: dict[str, Conversation] = {}
        self.locks = KeyedLocks()

    @property
    def engine_name(self) -> str:
        return "claude" if self.claude else "rules"

    async def chat(
        self, caller: Caller, message: str, conversation_id: str | None = None
    ) -> ChatResult:
        conv = self._conversation(conversation_id)
        async with self.locks(conv.id):
            tools = ToolBox(caller, self.parking, self.accounts, self.gate, self.stats)
            lang = detect_language(message, default=await self._preferred_language(caller))

            turn: list[dict[str, Any]] = [{"role": "user", "content": message}]
            context = await self._context_note(caller)
            if context != conv.context:
                turn.append({"role": "system", "content": context})

            reply, engine = None, "rules"
            if self.claude:
                try:
                    reply, added = await self.claude.reply(conv.messages + turn, tools, lang)
                    conv.messages += turn + added
                    engine = "claude"
                    lang = detect_language(reply, default=lang)
                except anthropic.APIError:
                    logger.exception("Claude API call failed; answering with the offline rules")
                    if tools.actions:
                        # A tool already acted (barrier, reservation...): running the request
                        # again would do it twice, so only say what was done.
                        reply = self.rules.describe(tools.actions, lang)

            if reply is None:
                reply, lang = await self.rules.reply(message, tools, lang)
            if engine == "rules":
                conv.messages += turn + [{"role": "assistant", "content": reply}]

            conv.context = context
            conv.updated_at = self.clock()
            return ChatResult(conv.id, reply, lang, engine, tools.actions)

    def _conversation(self, conversation_id: str | None) -> Conversation:
        now = self.clock()
        for cid, c in list(self.conversations.items()):
            if now - c.updated_at > IDLE_TIMEOUT_S:
                del self.conversations[cid]
        conv = self.conversations.get(conversation_id or "")
        if conv is None or len(conv.messages) > MAX_MESSAGES:
            if len(self.conversations) >= MAX_CONVERSATIONS:
                oldest = min(self.conversations.values(), key=lambda c: c.updated_at)
                del self.conversations[oldest.id]
            conv = Conversation(id=secrets.token_urlsafe(16), updated_at=now)
            self.conversations[conv.id] = conv
        return conv

    async def _preferred_language(self, caller: Caller) -> str:
        if caller.uid:
            try:
                return (await self.accounts.get_user(caller.uid)).get("language", "en")
            except Exception:
                pass
        return "en"

    async def _context_note(self, caller: Caller) -> str:
        where = "the gate kiosk" if caller.channel == "kiosk" else "the mobile app"
        if not caller.uid:
            return f"Context: the user is on {where} and is not identified."
        try:
            user = await self.accounts.get_user(caller.uid)
        except Exception:
            return f"Context: the user is on {where} and is not identified."
        return (
            f"Context: the user is on {where}, signed in as {user['name']} "
            f"(account UID {caller.uid}). Only act for this account."
        )
