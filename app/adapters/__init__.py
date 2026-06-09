from app.adapters.anthropic_adapter import AnthropicAdapter
from app.adapters.base import AdapterRegistry, ModelAdapter, get_adapter
from app.adapters.deepseek_adapter import DeepSeekAdapter
from app.adapters.glm_adapter import GLMAdapter
from app.adapters.kimi_adapter import KimiAdapter
from app.adapters.lingya_adapter import LingyaAdapter
from app.adapters.openai_adapter import OpenAIAdapter
from app.adapters.qwen_adapter import QwenAdapter

# Register all adapters at import time
AdapterRegistry.register("openai", OpenAIAdapter)
AdapterRegistry.register("anthropic", AnthropicAdapter)
AdapterRegistry.register("qwen", QwenAdapter)
AdapterRegistry.register("deepseek", DeepSeekAdapter)
AdapterRegistry.register("kimi", KimiAdapter)
AdapterRegistry.register("kimi_code", KimiAdapter)
AdapterRegistry.register("lingya", LingyaAdapter)
AdapterRegistry.register("glm", GLMAdapter)

__all__ = [
    "ModelAdapter",
    "AdapterRegistry",
    "get_adapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "QwenAdapter",
    "DeepSeekAdapter",
    "KimiAdapter",
    "LingyaAdapter",
    "GLMAdapter",
]
