import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ProviderError:
    code: str
    message: str
    provider: str
    model: str
    status_code: int | None = None
    details: str | None = None


def _safe_message(exc: httpx.HTTPStatusError) -> str:
    """Return a short, safe message without the full response body."""
    return f"HTTP {exc.response.status_code} from {exc.request.url}"


def normalize_provider_error(exc: Exception, provider: str, model: str) -> ProviderError:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        safe_msg = _safe_message(exc)
        # Log the full response body server-side only
        logger.warning(
            "Provider error: %s %s status=%s body=%s",
            provider,
            model,
            status_code,
            exc.response.text[:500],
        )
        if status_code == 401:
            return ProviderError(
                code="provider_unauthorized",
                message="Provider unauthorized",
                provider=provider,
                model=model,
                status_code=status_code,
                details=safe_msg,
            )
        if status_code == 402:
            return ProviderError(
                code="provider_payment_required",
                message="Provider payment required",
                provider=provider,
                model=model,
                status_code=status_code,
                details=safe_msg,
            )
        if status_code == 403:
            return ProviderError(
                code="provider_forbidden",
                message="Provider forbidden",
                provider=provider,
                model=model,
                status_code=status_code,
                details=safe_msg,
            )
        if status_code == 429:
            return ProviderError(
                code="provider_rate_limited",
                message="Provider rate limited",
                provider=provider,
                model=model,
                status_code=status_code,
                details=safe_msg,
            )
        if status_code == 400:
            return ProviderError(
                code="provider_bad_request",
                message="Provider bad request",
                provider=provider,
                model=model,
                status_code=status_code,
                details=safe_msg,
            )
        return ProviderError(
            code="provider_error",
            message="Provider error",
            provider=provider,
            model=model,
            status_code=status_code,
            details=safe_msg,
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
