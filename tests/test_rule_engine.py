from app.services.rule_engine import evaluate_rules


def test_tool_match_db_query():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "run query"}],
        tools=["execute_sql"],
    )
    assert result.matched is True
    assert result.rule_name == "db_query"
    assert result.tier == "cheap"


def test_tool_match_mcp():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "call mcp"}],
        tools=["mcp_search"],
    )
    assert result.matched is True
    assert result.tier == "cheap"


def test_keyword_match_network_traffic_query():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "查村合肥B3的211.91.71.106的流量"}],
    )
    assert result.matched is True
    assert result.rule_name == "network_traffic_query"
    assert result.tier == "cheap"


def test_keyword_match_alert():
    # alert_analysis rule requires min_content_tokens: 1000
    # Build a message with >1000 words that contains "告警"
    long_body = "system reported high cpu usage on node " * 200
    result = evaluate_rules(
        messages=[{"role": "user", "content": f"分析这个告警：{long_body}"}],
    )
    assert result.matched is True
    assert result.rule_name == "alert_analysis"
    assert result.tier == "expensive"


def test_no_tool_no_keyword_short_text():
    result = evaluate_rules(
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result.matched is True
    assert result.tier == "cheap"


def test_unmatched_when_no_rules_apply(monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", "/tmp/test_no_rules")
    import os
    import yaml
    os.makedirs("/tmp/test_no_rules", exist_ok=True)
    with open("/tmp/test_no_rules/gateway.yaml", "w") as f:
        yaml.dump({"server": {"host": "0.0.0.0", "port": 8000}}, f)
    with open("/tmp/test_no_rules/models.yaml", "w") as f:
        yaml.dump({"models": [], "providers": {}}, f)
    from app.config import reload_config
    reload_config()
    result = evaluate_rules(messages=[{"role": "user", "content": "test"}])
    assert result.matched is False
