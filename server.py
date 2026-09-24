# -*- coding: utf-8 -*-
"""
===================================
Daily Stock Analysis - FastAPI backend service entry point
===================================

Responsibilities:
1. Serve the RESTful API
2. Configure CORS
3. Expose the health-check endpoint
4. Host the frontend static files (production mode)

Startup:
    uvicorn server:app --reload --host 0.0.0.0 --port 8000
    
    or through main.py:
    python main.py --serve-only      # start the API service only
    python main.py --serve           # API service plus the analysis run
"""

import logging

from src.config import setup_env, get_config
from src.logging_config import setup_logging

# Initialise the environment variables and logging
setup_env()

config = get_config()
level_name = (config.log_level or "INFO").upper()
level = getattr(logging, level_name, logging.INFO)

setup_logging(
    log_prefix="api_server",
    console_level=level,
    extra_quiet_loggers=['uvicorn', 'fastapi'],
)

# Import the application instance from api.app
from api.app import app  # noqa: E402

# Export app for uvicorn
__all__ = ['app']


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
