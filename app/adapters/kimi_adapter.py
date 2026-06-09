from app.adapters.openai_adapter import OpenAIAdapter


class KimiAdapter(OpenAIAdapter):
    """Kimi (Moonshot) uses OpenAI-compatible API."""

    _K2_5_FIXED_PARAMETER_FIELDS = {
        "temperature",
        "top_p",
        "n",
        "presence_penalty",
        "frequency_penalty",
    }

    def _build_request_body(self, messages: list[dict], stream: bool, **kwargs) -> dict:
        body = super()._build_request_body(messages, stream, **kwargs)
        if self.model_config.name == "kimi-k2.5":
            for field in self._K2_5_FIXED_PARAMETER_FIELDS:
                body.pop(field, None)
            body.setdefault("thinking", {"type": "disabled"})
        return body
