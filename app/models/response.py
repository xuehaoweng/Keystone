from pydantic import BaseModel


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RouteInfo(BaseModel):
    source: str = "unknown"
    rule_name: str | None = None
    requested_tier: str = "auto"
    resolved_tier: str
    attempted_models: list[str] = []
    fallback_used: bool = False
    cache_hit: bool = False


class ChatResponse(BaseModel):
    id: str
    model: str
    tier: str
    content: str
    usage: UsageInfo
    finish_reason: str = "stop"
    route: RouteInfo | None = None


class ChunkResponse(BaseModel):
    id: str
    model: str
    content: str = ""
    finish_reason: str | None = None
    usage: UsageInfo | None = None


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: str | None = None
