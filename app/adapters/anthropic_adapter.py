import json
from typing import AsyncIterator

import httpx

from app.adapters.base import ChatChunk, ChatResult, ModelAdapter
from app.config import get_models_config
from app.services.token_counter import count_message_tokens, count_tokens


class AnthropicAdapter(ModelAdapter):
    API_VERSION = "2023-06-01"

    async def chat(
        self,
        messages: list[dict],
        stream: bool = False,
        **kwargs,
    ) -> ChatResult | AsyncIterator[ChatChunk]:
        if stream:
            return self._stream(messages, **kwargs)
        return await self._non_stream(messages, **kwargs)

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        system_prompt = None
        converted = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            elif msg["role"] in ("user", "assistant"):
                converted.append({"role": msg["role"], "content": msg["content"]})
        return system_prompt, converted

    async def _non_stream(self, messages: list[dict], **kwargs) -> ChatResult:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/v1/messages"
        system_prompt, converted = self._convert_messages(messages)
        headers = {
            "x-api-key": self._get_api_key(),
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        max_tokens = kwargs.get("max_tokens", 4096)
        body = {
            "model": self.model_config.name,
            "messages": converted,
            "max_tokens": max_tokens,
            **{k: v for k, v in kwargs.items() if k != "max_tokens"},
        }
        if system_prompt:
            body["system"] = system_prompt
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=body, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        content_blocks = data.get("content", [])
        text_content = next((b["text"] for b in content_blocks if b.get("type") == "text"), "")
        content = text_content or content_blocks[0].get("text", "") if content_blocks else ""
        usage = data.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        if not prompt_tokens:
            prompt_tokens = count_message_tokens(messages, self.model_config.name)
        if not completion_tokens:
            completion_tokens = count_tokens(content, self.model_config.name)
        return ChatResult(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=self.model_config.name,
            finish_reason=data.get("stop_reason", "end_turn"),
        )

    async def _stream(self, messages: list[dict], **kwargs) -> AsyncIterator[ChatChunk]:
        provider_cfg = get_models_config()["providers"][self.model_config.provider]
        url = f"{provider_cfg['base_url']}/v1/messages"
        system_prompt, converted = self._convert_messages(messages)
        headers = {
            "x-api-key": self._get_api_key(),
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model_config.name,
            "messages": converted,
            "max_tokens": kwargs.pop("max_tokens", 4096),
            "stream": True,
            **kwargs,
        }
        if system_prompt:
            body["system"] = system_prompt
        accumulated: list[str] = []
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, json=body, timeout=60) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    event_type = data.get("type", "")
                    if event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            accumulated.append(text)
                            yield ChatChunk(content=text)
                    elif event_type == "message_delta":
                        stop_reason = data.get("delta", {}).get("stop_reason")
                        usage = data.get("usage", {})
                        prompt_tokens = usage.get("input_tokens", 0)
                        completion_tokens = usage.get("output_tokens", 0)
                        if stop_reason:
                            if not prompt_tokens:
                                prompt_tokens = count_message_tokens(messages, self.model_config.name)
                            if not completion_tokens:
                                completion_tokens = count_tokens("".join(accumulated), self.model_config.name)
                            yield ChatChunk(
                                content="",
                                finish_reason=stop_reason,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                total_tokens=prompt_tokens + completion_tokens,
                            )
