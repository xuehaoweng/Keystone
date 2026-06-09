from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_compose() -> dict:
    with (ROOT / "docker-compose.yml").open() as f:
        return yaml.safe_load(f)


def test_compose_runs_ingress_gateway_and_redis_as_one_stack():
    compose = load_compose()
    services = compose["services"]

    assert set(services) == {"ingress", "gateway", "redis", "frontend"}
    assert compose["name"] == "llm-gateway"
    assert "llm_gateway_net" in compose["networks"]

    ingress = services["ingress"]
    assert ingress["image"] == "nginx:1.27-alpine"
    assert ingress["ports"] == ["${GATEWAY_PORT:-8000}:80"]
    assert ingress["depends_on"]["gateway"]["condition"] == "service_healthy"
    assert "./deploy/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" in ingress["volumes"]

    gateway = services["gateway"]
    assert gateway["build"]["context"] == "."
    assert gateway["env_file"] == [".env"]
    assert gateway["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert gateway["depends_on"]["redis"]["condition"] == "service_healthy"
    assert "ports" not in gateway
    assert gateway["expose"] == ["8000"]


def test_compose_keeps_redis_private_to_the_stack():
    redis = load_compose()["services"]["redis"]

    assert "ports" not in redis
    assert redis["expose"] == ["6379"]
    assert redis["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]


def test_nginx_ingress_proxies_to_gateway_and_keeps_streaming_unbuffered():
    nginx_conf = (ROOT / "deploy/nginx/default.conf").read_text()

    assert "upstream llm_gateway_backend" in nginx_conf
    assert "server gateway:8000;" in nginx_conf
    assert "proxy_pass http://llm_gateway_backend;" in nginx_conf
    assert "proxy_buffering off;" in nginx_conf
    assert "limit_req_zone $binary_remote_addr zone=gateway_qps:10m rate=30r/s;" in nginx_conf


def test_dockerignore_keeps_local_state_and_secrets_out_of_build_context():
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()

    assert ".env" in dockerignore
    assert ".venv/" in dockerignore
    assert "frontend/node_modules/" in dockerignore
    assert "frontend/dist/" in dockerignore


def test_gateway_image_contains_test_key_helper_for_first_run():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "COPY scripts/ ./scripts/" in dockerfile
