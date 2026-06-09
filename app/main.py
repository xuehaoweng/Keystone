import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_record["request_id"] = record.request_id
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from app.utils.context import get_request_id
        record.request_id = get_request_id()
        return True


# Configure root logger to output structured JSON
_handler = logging.StreamHandler()
_handler.setFormatter(JSONFormatter())
_handler.addFilter(RequestIdFilter())
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)

from app.api.admin import router as admin_router  # noqa: E402
from app.api.anthropic_compatible import router as anthropic_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.openai_compatible import router as openai_router  # noqa: E402
from app.api.runs import router as runs_router  # noqa: E402
from app.db.redis import get_redis  # noqa: E402
from app.db.redis import close_redis  # noqa: E402
from app.db.sqlite import close_db  # noqa: E402
from app.db.sqlite import get_db  # noqa: E402
from app.db.sqlite import init_db  # noqa: E402
from app.services.health_probe import start_health_probe, stop_health_probe  # noqa: E402
from app.services.prometheus_metrics import generate_metrics  # noqa: E402
from app.services.retention import start_retention_cleanup, stop_retention_cleanup  # noqa: E402
from app.services.metrics import get_metrics  # noqa: E402
from app.utils.context import request_id_var  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    if not os.getenv("GATEWAY_KEY_ENCRYPTION_SECRET"):
        raise RuntimeError(
            "GATEWAY_KEY_ENCRYPTION_SECRET is not set. "
            "This environment variable is required for API key encryption. "
            "Please add it to your .env file before starting the gateway."
        )
    await init_db()
    get_metrics().start_flush_loop()
    start_health_probe()
    start_retention_cleanup()
    yield
    await get_metrics().force_flush()
    await stop_health_probe()
    await stop_retention_cleanup()
    await close_redis()
    await close_db()


app = FastAPI(title="LLM Gateway", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    request.state.request_id = request_id
    request_id_var.set(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(runs_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(openai_router)
app.include_router(anthropic_router)

_web_dir = Path(__file__).parent / "web"
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
app.mount("/admin/assets", StaticFiles(directory=_web_dir), name="admin-assets")
if (_frontend_dist / "assets").exists():
    app.mount(
        "/llm_gateway_admin/assets",
        StaticFiles(directory=_frontend_dist / "assets"),
        name="llm-gateway-admin-assets",
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(generate_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/ready")
async def ready():
    checks = {"db": False, "redis": False}
    async with get_db() as db:
        await db.execute("SELECT 1")
        checks["db"] = True
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False
    return {
        "status": "ready" if all(checks.values()) else "degraded",
        "checks": checks,
    }


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/login")


@app.get("/login", include_in_schema=False)
async def login_page():
    return _admin_index()


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return _admin_index()


@app.get("/llm_gateway_admin", include_in_schema=False)
async def llm_gateway_admin_page():
    return _admin_index()


@app.get("/llm_gateway_admin/favicon.svg", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    return _favicon_file()


def _admin_index():
    react_index = _frontend_dist / "index.html"
    if react_index.exists():
        html = react_index.read_text(encoding="utf-8")
        return Response(
            content=html,
            media_type="text/html",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return Response(
        content=_web_dir.joinpath("admin.html").read_text(encoding="utf-8"),
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _favicon_file():
    react_favicon = _frontend_dist / "favicon.svg"
    if react_favicon.exists():
        return FileResponse(react_favicon, media_type="image/svg+xml")
    return FileResponse(
        Path(__file__).parent.parent / "frontend" / "public" / "favicon.svg",
        media_type="image/svg+xml",
    )
