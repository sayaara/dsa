# -*- coding: utf-8 -*-
"""
===================================
API v1 package initialization
===================================

Responsibilities:
1. Export the v1 API router lazily, so importing a schema does not pull in the entire endpoint import tree
"""

from typing import Any

__all__ = ["api_v1_router"]


def __getattr__(name: str) -> Any:
    if name != "api_v1_router":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from api.v1.router import router

    return router
