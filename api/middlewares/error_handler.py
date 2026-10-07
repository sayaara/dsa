# -*- coding: utf-8 -*-
"""
===================================
Global exception handlers
===================================

Responsibilities:
1. Catch unhandled exceptions
2. Normalize the error response format
3. Write error logs

``add_error_handlers`` registers the FastAPI exception handlers that ``api/app.py`` installs.
"""

import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def add_error_handlers(app) -> None:
    """
    Register the global exception handlers
    
    Attaches handlers for the various exception types to the FastAPI app
    
    Args:
        app: the FastAPI application instance
    """
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Handle HTTP exceptions"""
        # If detail is already a dict in ErrorResponse shape, use it as is
        if isinstance(exc.detail, dict) and "error" in exc.detail and "message" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail
            )
        # Otherwise wrap detail into the ErrorResponse shape
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": str(exc.detail) if exc.detail else "HTTP Error",
                "detail": None
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle request validation exceptions"""
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "Request parameter validation failed",
                "detail": exc.errors()
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle uncategorized exceptions"""
        logger.error(
            f"Unhandled exception: {exc}\n"
            f"Request path: {request.url.path}\n"
            f"Traceback: {traceback.format_exc()}"
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Internal server error",
                "detail": None
            }
        )
