from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None


class ToolRef(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    messages: list[Message]
    stream: bool = False
    model: str | None = None  # Direct model specification
    tier: str | None = None  # Alias for model_tier
    model_tier: str = Field(default="auto", pattern="^(auto|cheap|expensive)$")
    preferred_model: str | None = None
    fallback_model: str | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, gt=0, le=128000)
    tools: list[ToolRef] = Field(default_factory=list)


class IntentResult(BaseModel):
    tier: str = Field(pattern="^(cheap|expensive)$")
    task_type: str
    fallback_model: str | None = None
