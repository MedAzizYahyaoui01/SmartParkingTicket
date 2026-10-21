"""Assistant powered by Claude, with the parking tools.

The conversation is append-only: the system prompt and the tool list never change, and
each turn only adds messages (who is speaking is told with a mid-conversation system
message, never by editing earlier turns). That keeps the prompt cache warm and the thinking
blocks Claude sends back valid on the next turn.
"""

import json
import logging
from typing import Any

import anthropic

from app.services.assistant.tools import TOOL_DEFINITIONS, ToolBox

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """\
You are the voice and chat assistant of a small smart parking lot (4 spots, P1 to P4, \
one entry/exit barrier). People talk to you on the kiosk at the gate, often by voice from \
their car, or in the mobile app.

Language: always answer in the language of the user's latest message: English, French or \
Arabic. If they write Tunisian Darija (in Arabic letters or in Latin letters with digits \
like 3, 7, 9), answer in simple Tunisian Arabic written in Arabic letters.

Style: your answers may be read aloud by speech synthesis, so keep them to one to three \
short sentences of plain text: no markdown, no lists, no emoji. Amounts are in Tunisian \
dinars (TND); say them as the tools give them.

Facts and actions: use the tools for every fact about spots, prices, the user's account \
and for every action; never guess a number or claim an action you did not perform with a \
tool. Only open the barrier when the user asks to open it, enter or leave. If a tool says \
the user is not identified, tell them to sign in to the app or show the QR code from the \
app's Account page to the kiosk camera. If a payment is needed, call top_up, which opens a \
secure card checkout; never ask for or accept card numbers in the chat. You act only for \
the signed-in user; politely refuse requests about other people's accounts. If the request \
is unrelated to parking, say briefly that you can only help with the parking."""

TOOLS = [{**tool, "strict": True} for tool in TOOL_DEFINITIONS]

REFUSAL_REPLY = {
    "en": "Sorry, I can't help with that. I can help with parking spots, the gate, "
    "reservations and your wallet.",
    "fr": "Désolé, je ne peux pas aider pour cela. Je peux vous aider pour les places, la "
    "barrière, les réservations et votre solde.",
    "ar": "سامحني، ما نجمش نعاون في هاذا. نجم نعاونك في البلايص، الباب، الحجز والرصيد.",
}


class ClaudeEngine:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str) -> None:
        self.client = client
        self.model = model

    async def reply(
        self, history: list[dict[str, Any]], tools: ToolBox, lang: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """Runs one user turn. `history` already ends with the new user message.
        Returns (reply text, messages to append to the conversation). Raises
        anthropic.APIError if the API fails; nothing is to be appended then."""
        added: list[dict[str, Any]] = []
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=history + added,
                # Short spoken answers: low effort keeps the gate responsive
                output_config={"effort": "low"},
                cache_control={"type": "ephemeral"},
                # If a safety classifier declines, the API retries on a fallback model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )

            if response.stop_reason == "refusal":
                text = REFUSAL_REPLY.get(lang, REFUSAL_REPLY["en"])
                added.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
                return text, added

            content = _replayable(response.content)
            added.append({"role": "assistant", "content": content})
            calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                text = " ".join(b.text for b in response.content if b.type == "text").strip()
                if not text:
                    text = "…"
                    added[-1] = {"role": "assistant", "content": [{"type": "text", "text": text}]}
                return text, added

            results = []
            for call in calls:  # one after another: they change the parking state
                try:
                    result = await tools.run(call.name, dict(call.input))
                    is_error = False
                except Exception as e:  # a tool bug must not break the conversation
                    logger.exception("Assistant tool %s failed", call.name)
                    result, is_error = {"ok": False, "error": str(e)}, True
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                        "is_error": is_error,
                    }
                )
            added.append({"role": "user", "content": results})

        # Too many tool rounds: close the turn with a plain answer
        text = REFUSAL_REPLY.get(lang, REFUSAL_REPLY["en"])
        added.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        return text, added


def _replayable(blocks: list[Any]) -> list[dict[str, Any]]:
    """The assistant content as it must be sent back next time. After a mid-output
    fallback, the thinking / tool_use blocks before the last `fallback` marker are dropped
    (they belong to the model that declined); everything else is kept unchanged."""
    dumped = [b.model_dump(mode="json", exclude_none=True) for b in blocks]
    last_fallback = max((i for i, b in enumerate(dumped) if b["type"] == "fallback"), default=-1)
    if last_fallback < 0:
        return dumped
    keep_types = {"text"}
    before = [b for b in dumped[:last_fallback] if b["type"] in keep_types]
    return before + dumped[last_fallback + 1 :]
