# -*- coding: utf-8 -*-
"""
===================================
API middleware package initialization
===================================

Responsibilities:
1. Export all middlewares
"""

from api.middlewares.error_handler import add_error_handlers

__all__ = ["add_error_handlers"]
