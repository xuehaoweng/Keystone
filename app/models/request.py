import os
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

_MAX_MESSAGES = int(os.getenv("GATEWAY_MAX_MESSAGES", "100"))
_MAX_CONTENT_LENGTH = int(os.getenv("GATEWAY_MAX_CONTENT_LENGTH", "100000"))
_MAX_TOKENS_GATEWAY = int(os.getenv("GATEWAY_MAX_TOKENS", "32768"))


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

    @model_validator(mode="after")
    def check_limits(self):
        if len(self.messages) > _MAX_MESSAGES:
            raise ValueError(f"Too many messages: maximum {_MAX_MESSAGES}")
        total_content = 0
        for msg in self.messages:
            total_content += len(msg.content)
            if len(msg.content) > _MAX_CONTENT_LENGTH:
                raise ValueError(f"Message content too long: maximum {_MAX_CONTENT_LENGTH} characters")
        if self.max_tokens > _MAX_TOKENS_GATEWAY:
            raise ValueError(f"max_tokens exceeds gateway limit: maximum {_MAX_TOKENS_GATEWAY}")
        return self


class IntentResult(BaseModel):
    tier: str = Field(pattern="^(cheap|expensive)$")
    task_type: str
    fallback_model: str | None = None
