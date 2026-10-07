# -*- coding: utf-8 -*-
"""
Auth middleware: protect /api/v1/* when admin auth is enabled.
"""

from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth import COOKIE_NAME, is_auth_enabled, verify_session

logger = logging.getLogger(__name__)

EXEMPT_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/status",
    # Discord cannot hold a login session; the endpoint verifies its Ed25519 signature instead.
    "/api/v1/bot/discord/interactions",
    "/api/health",
    "/api/v1/health",
    "/health",
})

# Interactive API documentation. It discloses the full route surface, so it is
# protected like /api/v1/* when admin auth is enabled. The HTML pages redirect to
# the login page; the JSON schema returns 401 like any other API resource.
PROTECTED_DOC_HTML_PATHS = frozenset({"/docs", "/redoc"})
PROTECTED_DOC_PATHS = PROTECTED_DOC_HTML_PATHS | frozenset({"/openapi.json"})


def _normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _path_exempt(path: str) -> bool:
    """Check if path is exempt from auth."""
    return _normalize_path(path) in EXEMPT_PATHS


def _path_protected(path: str) -> bool:
    """Check if path requires a valid session when auth is enabled."""
    return path.startswith("/api/v1/") or _normalize_path(path) in PROTECTED_DOC_PATHS


class AuthMiddleware(BaseHTTPMiddleware):
    """Require valid session for /api/v1/* when auth is enabled."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        if not is_auth_enabled():
            return await call_next(request)

        path = request.url.path
        if _path_exempt(path):
            return await call_next(request)

        if not _path_protected(path):
            return await call_next(request)

        cookie_val = request.cookies.get(COOKIE_NAME)
        if not cookie_val or not verify_session(cookie_val):
            if _normalize_path(path) in PROTECTED_DOC_HTML_PATHS:
                return RedirectResponse(
                    url=f"/login?redirect={quote(path, safe='/')}",
                    status_code=302,
                )
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": "Login required",
                },
            )

        return await call_next(request)


def add_auth_middleware(app):
    """Add auth middleware to protect API routes.

    The middleware is always registered; whether auth is enforced is determined
    at request time by is_auth_enabled() so the decision stays consistent across
    any runtime configuration reload.
    """
    app.add_middleware(AuthMiddleware)
