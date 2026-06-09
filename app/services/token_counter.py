import tiktoken

_DEFAULT_ENCODING = "cl100k_base"

# Mapping from common model names to tiktoken encoding names.
# When a model is not listed we fall back to the default encoding.
_MODEL_ENCODINGS: dict[str, str] = {
    "gpt-4": "cl100k_base",
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "text-embedding-3-small": "cl100k_base",
    "text-embedding-3-large": "cl100k_base",
}


def _encoding_for_model(model_name: str) -> tiktoken.Encoding:
    """Return a tiktoken encoding for *model_name* (best-effort)."""
    enc_name = None
    for prefix, name in _MODEL_ENCODINGS.items():
        if model_name.startswith(prefix):
            enc_name = name
            break
    if enc_name is None:
        enc_name = _DEFAULT_ENCODING
    try:
        return tiktoken.get_encoding(enc_name)
    except Exception:
        return tiktoken.get_encoding(_DEFAULT_ENCODING)


def count_tokens(text: str, model_name: str = "gpt-4") -> int:
    """Estimate the number of tokens in *text* for *model_name*."""
    if not text:
        return 0
    try:
        enc = _encoding_for_model(model_name)
        return len(enc.encode(text))
    except Exception:
        # Fallback: ~4 English chars per token, ~1.5 CJK chars per token.
        # We use a simple heuristic weighted toward CJK content.
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return max(1, ascii_chars // 4 + non_ascii_chars // 2)


def count_message_tokens(messages: list[dict], model_name: str = "gpt-4") -> int:
    """Estimate tokens for a list of chat messages (including overhead)."""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get("text", ""))
            content = "".join(parts)
        total += count_tokens(content, model_name)
        # Per-message overhead (~4 tokens for role/name delimiters)
        total += 4
    # Conversation format overhead
    total += 2
    return total
