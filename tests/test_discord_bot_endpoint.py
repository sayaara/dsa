# -*- coding: utf-8 -*-
"""The Discord interactions webhook is wired end to end.

Requests are signed with a throwaway Ed25519 key, posted to
``/api/v1/bot/discord/interactions`` through the real router, and the deferred
command reaches the dispatcher and the follow-up sender.
"""

import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

import bot.handler as bot_handler
from api.middlewares.auth import EXEMPT_PATHS
from api.v1.endpoints.bot import DISCORD_INTERACTIONS_PATH
from api.v1.router import router as api_v1_router
from bot.models import BotResponse
from bot.platforms import ALL_PLATFORMS
from bot.platforms.discord import DiscordPlatform
from scripts.register_discord_commands import build_command_payload


@pytest.fixture()
def signing_key():
    return SigningKey.generate()


@pytest.fixture()
def client(signing_key):
    config = SimpleNamespace(
        bot_enabled=True,
        discord_interactions_public_key=signing_key.verify_key.encode().hex(),
    )
    app = FastAPI()
    app.include_router(api_v1_router, prefix="/api/v1")
    bot_handler._platform_instances.clear()
    with patch("src.config.get_config", return_value=config), TestClient(app) as test_client:
        yield test_client
    bot_handler._platform_instances.clear()


def _signed(signing_key: SigningKey, payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()
    headers = {
        "X-Signature-Ed25519": signature,
        "X-Signature-Timestamp": timestamp,
        "Content-Type": "application/json",
    }
    return body, headers


def test_discord_is_a_registered_platform_and_its_route_skips_the_web_login() -> None:
    assert ALL_PLATFORMS["discord"] is DiscordPlatform
    assert DISCORD_INTERACTIONS_PATH == "/api/v1/bot/discord/interactions"
    assert DISCORD_INTERACTIONS_PATH in EXEMPT_PATHS


def test_signed_ping_gets_pong(client, signing_key) -> None:
    body, headers = _signed(signing_key, {"type": 1})

    response = client.post(DISCORD_INTERACTIONS_PATH, content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"type": 1}


def test_unsigned_or_forged_requests_are_rejected(client, signing_key) -> None:
    body = json.dumps({"type": 1}).encode("utf-8")
    unsigned = client.post(DISCORD_INTERACTIONS_PATH, content=body, headers={"Content-Type": "application/json"})
    assert unsigned.status_code == 401

    _, headers = _signed(SigningKey.generate(), {"type": 1})
    forged = client.post(DISCORD_INTERACTIONS_PATH, content=body, headers=headers)
    assert forged.status_code == 401


def test_slash_command_is_acknowledged_then_answered_by_follow_up(client, signing_key) -> None:
    payload = {
        "type": 2,
        "id": "interaction-1",
        "application_id": "app-1",
        "token": "token-1",
        "channel_id": "channel-1",
        "guild_id": "guild-1",
        "member": {"user": {"id": "user-1", "username": "trader"}},
        "data": {"name": "analyze", "options": [{"type": 3, "name": "args", "value": "AAPL full"}]},
    }
    body, headers = _signed(signing_key, payload)
    dispatched = []
    followups = []

    class FakeDispatcher:
        async def dispatch_async(self, message):
            dispatched.append(message)
            return BotResponse.text_response("analysis queued")

    with patch.object(bot_handler, "get_dispatcher", return_value=FakeDispatcher()), patch.object(
        DiscordPlatform, "send_followup", lambda self, response, message: followups.append(response.text) or True
    ):
        response = client.post(DISCORD_INTERACTIONS_PATH, content=body, headers=headers)
        deadline = time.time() + 5
        while not followups and time.time() < deadline:
            time.sleep(0.02)

    assert response.status_code == 200
    assert response.json() == {"type": 5}
    assert [message.content for message in dispatched] == ["/analyze AAPL full"]
    assert dispatched[0].user_id == "user-1"
    assert followups == ["analysis queued"]


def test_replies_never_ping_everyone_roles_or_users(signing_key) -> None:
    with patch("src.config.get_config", return_value=SimpleNamespace(discord_interactions_public_key="00" * 32)):
        platform = DiscordPlatform()
    message = SimpleNamespace(raw_data={"type": 2})

    result = platform.format_response(BotResponse.text_response("@everyone buy now"), message)

    assert result.body["data"]["allowed_mentions"] == {"parse": []}


def test_registration_payload_covers_visible_commands_and_is_admin_only_by_default() -> None:
    payload = build_command_payload()
    names = [item["name"] for item in payload]

    assert {"help", "analyze", "market", "ask", "chat", "research"} <= set(names)
    assert len(names) == len(set(names))
    for item in payload:
        assert item["default_member_permissions"] == "0"
        assert item["dm_permission"] is False
        assert 1 <= len(item["description"]) <= 100
        assert [option["name"] for option in item["options"]] == ["args"]
