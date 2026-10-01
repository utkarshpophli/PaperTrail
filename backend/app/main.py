"""FastAPI application entrypoint."""

import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.auth.router import router as auth_router
from app.coderesearch.router import router as coderesearch_router
from app.collections.router import router as collections_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.discovery.router import router as discovery_router
from app.evidence.router import router as evidence_router
from app.graph.router import router as graph_router
from app.papers.router import router as papers_router
from app.providers.router import router as providers_router

settings = get_settings()
logger = get_logger(__name__)

app = FastAPI(title="Paper Trail API")
if settings.local_mode:
    logger.warning(
        "local_mode=on: no login, every request acts as one local user. "
        "Keep the API bound to 127.0.0.1; never expose it to a network."
    )
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_mode_loopback_only(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Local mode has no login, so the only thing keeping papers and API keys
    private is that the API is reachable from this machine alone. Enforce that
    here instead of trusting how uvicorn was started (``--host 0.0.0.0`` would
    otherwise hand every paper and every key-bearing request to the network)."""
    if get_settings().local_mode and not _is_loopback(request.client.host if request.client else None):
        logger.warning("local_mode_rejected_non_loopback_client")
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "local_mode_loopback_only",
                    "message": "Local mode only accepts requests from this machine.",
                    "detail": None,
                }
            },
        )
    return await call_next(request)


def _is_loopback(host: str | None) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("request_failed code=%s path=%s", exc.code, request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "detail": {"errors": jsonable_encoder(exc.errors())},
            }
        },
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "rate_limited", "message": "Too many requests, please try again later."}},
    )


app.include_router(auth_router)
app.include_router(papers_router)
app.include_router(providers_router)
app.include_router(evidence_router)
app.include_router(discovery_router)
app.include_router(collections_router)
app.include_router(graph_router)
app.include_router(coderesearch_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
