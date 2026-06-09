import json
from typing import AsyncIterator

import httpx

from app.adapters.base import ChatChunk, ChatResult, ModelAdapter
from app.config import get_models_config


class OpenAIAdapter(ModelAdapter):
    def _build_request_body(self, messages: list[dict], stream: bool, **kwargs) -> dict:
        return {
            "model": self.model_config.name,
            "messages": messages,
            "stream": stream,
            **kwargs,
        }

    async def chat(
        self,
        messages: list[dict],
        stream: bool = False,
        **kwargs,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        if stream:
            return self._stream(messages, **kwargs)
        return await self._non_stream(messages, **kwargs)

    async def _non_stream(self, messages: list[dict], **kwargs) -> ChatResult:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        body = self._build_request_body(messages, stream=False, **kwargs)
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=body, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        if not data.get("choices"):
            raise ValueError(f"Empty choices from {self.model_config.name}")
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return ChatResult(
            content=choice["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            model=data.get("model", self.model_config.name),
            finish_reason=choice.get("finish_reason", "stop"),
        )

    async def _stream(self, messages: list[dict], **kwargs) -> AsyncIterator[ChatChunk]:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }
        body = self._build_request_body(messages, stream=True, **kwargs)
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, json=body, timeout=60) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    content = delta.get("content", "") or ""
                    finish_reason = choice.get("finish_reason")
                    if content or finish_reason:
                        yield ChatChunk(content=content, finish_reason=finish_reason)
