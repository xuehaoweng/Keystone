import fnmatch
from dataclasses import dataclass


@dataclass
class RuleMatch:
    matched: bool
    rule_name: str = ""
    tier: str = ""


def _content_text(messages: list[dict]) -> str:
    return " ".join(m.get("content", "") for m in messages)


def _tools_match(rule_tools: list[str], request_tools: list[str]) -> bool:
    for rt in request_tools:
        tool_name = rt if isinstance(rt, str) else (rt.get("name", "") if isinstance(rt, dict) else "")
        for pattern in rule_tools:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
    return False


def _keywords_match(rule_keywords: list[str], text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in rule_keywords)


def evaluate_rules(messages: list[dict], tools: list[str] | None = None) -> RuleMatch:
    from app.config import get_gateway_config

    rules = get_gateway_config().get("rules", [])
    if not rules:
        return RuleMatch(matched=False)

    text = _content_text(messages)

    for rule in rules:
        match_cfg = rule.get("match", {})

        if "tools" in match_cfg:
            if not tools or not _tools_match(match_cfg["tools"], tools):
                continue

        if "keywords" in match_cfg:
            if not _keywords_match(match_cfg["keywords"], text):
                continue

        word_count = len(text.split())
        if "max_content_tokens" in match_cfg and word_count > match_cfg["max_content_tokens"]:
            continue
        if "min_content_tokens" in match_cfg and word_count < match_cfg["min_content_tokens"]:
            continue

        return RuleMatch(matched=True, rule_name=rule["name"], tier=rule["tier"])

    return RuleMatch(matched=False)
