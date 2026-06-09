from dataclasses import dataclass

import httpx


@dataclass
class ProviderError:
    code: str
    message: str
    provider: str
    model: str
    status_code: int | None = None
    details: str | None = None


def _http_error_details(exc: httpx.HTTPStatusError) -> str:
    response_text = exc.response.text.strip()
    if not response_text:
        return str(exc)
    return f"{exc}\nProvider response body: {response_text}"


def normalize_provider_error(exc: Exception, provider: str, model: str) -> ProviderError:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        details = _http_error_details(exc)
        if status_code == 401:
            return ProviderError(
                code="provider_unauthorized",
                message="Provider unauthorized",
                provider=provider,
                model=model,
                status_code=status_code,
                details=details,
            )
        if status_code == 402:
            return ProviderError(
                code="provider_payment_required",
                message="Provider payment required",
                provider=provider,
                model=model,
                status_code=status_code,
                details=details,
            )
        if status_code == 403:
            return ProviderError(
                code="provider_forbidden",
                message="Provider forbidden",
                provider=provider,
                model=model,
                status_code=status_code,
                details=details,
            )
        if status_code == 429:
            return ProviderError(
                code="provider_rate_limited",
                message="Provider rate limited",
                provider=provider,
                model=model,
                status_code=status_code,
                details=details,
            )
        if status_code == 400:
            return ProviderError(
                code="provider_bad_request",
                message="Provider bad request",
                provider=provider,
                model=model,
                status_code=status_code,
                details=details,
            )
        return ProviderError(
            code="provider_error",
            message="Provider error",
            provider=provider,
            model=model,
            status_code=status_code,
            details=details,
        )
    if isinstance(exc, TimeoutError):
        return ProviderError(
            code="provider_timeout",
            message="Provider timeout",
            provider=provider,
            model=model,
            details=str(exc),
        )
    return ProviderError(
        code="provider_error",
        message="Provider error",
        provider=provider,
        model=model,
        details=str(exc),
    )
