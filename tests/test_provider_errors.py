import httpx

from app.services.provider_errors import normalize_provider_error


def _http_error(
    status_code: int,
    url: str = "https://api.deepseek.com/v1/chat/completions",
    body: dict | None = None,
):
    request = httpx.Request("POST", url)
    response = httpx.Response(status_code, json=body, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_402_maps_to_payment_required():
    error = normalize_provider_error(
        _http_error(402),
        provider="deepseek",
        model="deepseek-chat",
    )
    assert error.code == "provider_payment_required"
    assert error.status_code == 402
    assert error.provider == "deepseek"
    assert error.model == "deepseek-chat"


def test_403_maps_to_forbidden():
    error = normalize_provider_error(
        _http_error(403),
        provider="lingya",
        model="qwen3.6-plus",
    )
    assert error.code == "provider_forbidden"


def test_401_maps_to_unauthorized():
    error = normalize_provider_error(
        _http_error(
            401,
            body={
                "error": {
                    "message": "Invalid Authentication",
                    "type": "invalid_authentication_error",
                }
            },
        ),
        provider="kimi",
        model="kimi-k2.5",
    )

    assert error.code == "provider_unauthorized"
    assert error.status_code == 401
    assert "Invalid Authentication" in (error.details or "")


def test_429_maps_to_rate_limited():
    error = normalize_provider_error(
        _http_error(429),
        provider="deepseek",
        model="deepseek-chat",
    )
    assert error.code == "provider_rate_limited"


def test_400_maps_to_bad_request():
    error = normalize_provider_error(
        _http_error(400),
        provider="kimi",
        model="kimi-k2.5",
    )
    assert error.code == "provider_bad_request"


def test_http_error_details_include_response_body():
    error = normalize_provider_error(
        _http_error(
            400,
            body={
                "error": {
                    "message": "invalid request: thinking parameter is required",
                    "type": "invalid_request_error",
                }
            },
        ),
        provider="kimi",
        model="kimi-k2.5",
    )

    assert "thinking parameter is required" in (error.details or "")
