# -*- coding: utf-8 -*-
"""Inbound bot webhooks.

Discord posts slash-command interactions here. Set the application's
"Interactions Endpoint URL" in the Discord Developer Portal to
``https://<your-host>/api/v1/bot/discord/interactions``. Every request is checked
against ``DISCORD_INTERACTIONS_PUBLIC_KEY`` (Ed25519) before anything runs, so the
route is exempt from the Web login session (Discord cannot log in).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bot.handler import handle_webhook_async

logger = logging.getLogger(__name__)

router = APIRouter()

DISCORD_INTERACTIONS_PATH = "/api/v1/bot/discord/interactions"


@router.post(
    "/discord/interactions",
    summary="Discord interactions webhook",
    description=(
        "Receives Discord slash-command interactions. Requests must carry a valid "
        "X-Signature-Ed25519 / X-Signature-Timestamp pair for DISCORD_INTERACTIONS_PUBLIC_KEY; "
        "anything else gets 401. PING (type 1) is answered with PONG, and commands are "
        "acknowledged at once (type 5) and answered by a follow-up message."
    ),
    include_in_schema=False,
)
async def discord_interactions(request: Request) -> JSONResponse:
    body = await request.body()
    headers = {key: value for key, value in request.headers.items()}
    result = await handle_webhook_async("discord", headers, body)
    return JSONResponse(status_code=result.status_code, content=result.body, headers=result.headers or None)
