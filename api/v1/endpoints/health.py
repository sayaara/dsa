# -*- coding: utf-8 -*-
"""
===================================
Health check endpoint
===================================

Responsibilities:
1. Provide the /api/v1/health health check endpoint
2. Serve load balancers and monitoring systems
"""

from datetime import datetime

from fastapi import APIRouter

from api.v1.schemas.common import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check endpoint
    
    Lets a load balancer or monitoring system check the service status
    
    Returns:
        HealthResponse: contains the service status and a timestamp
    """
    return HealthResponse(
        status="ok",
        timestamp=datetime.now().isoformat()
    )
