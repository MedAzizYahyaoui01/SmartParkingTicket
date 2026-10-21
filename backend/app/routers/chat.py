from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_assistant, optional_identity
from app.security import TokenClaims
from app.services.assistant.service import AssistantService
from app.services.assistant.tools import Caller

router = APIRouter(prefix="/chat", tags=["assistant"])


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = Field(default=None, max_length=64)
    # Where the anonymous user is; a token decides it otherwise
    channel: Literal["app", "kiosk"] = "app"


class ChatOut(BaseModel):
    conversation_id: str
    reply: str
    language: Literal["en", "fr", "ar"]
    engine: Literal["claude", "rules"]
    actions: list[dict[str, Any]]


@router.post("", response_model=ChatOut)
async def chat(
    body: ChatIn,
    assistant: Annotated[AssistantService, Depends(get_assistant)],
    claims: Annotated[TokenClaims | None, Depends(optional_identity)],
) -> ChatOut:
    """Talk to the parking assistant in English, French or Arabic (text, or voice already
    transcribed by the browser). Without a token it only answers general questions.
    `actions` lists what happened (barrier opening, reservation...) for the UI."""
    if claims is None:
        caller = Caller(uid=None, channel=body.channel)
    else:
        caller = Caller(uid=claims.uid, channel="kiosk" if claims.scope == "kiosk" else "app")
    result = await assistant.chat(caller, body.message.strip(), body.conversation_id)
    return ChatOut(
        conversation_id=result.conversation_id,
        reply=result.reply,
        language=result.language,
        engine=result.engine,
        actions=result.actions,
    )


@router.get("/info")
async def info(assistant: Annotated[AssistantService, Depends(get_assistant)]) -> dict:
    """Which engine answers: "claude" (API key set) or "rules" (offline keywords)."""
    return {"engine": assistant.engine_name, "languages": ["en", "fr", "ar"]}
