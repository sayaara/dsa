# -*- coding: utf-8 -*-
"""Register the bot's slash commands with Discord.

Discord only shows slash commands that were registered for the application. This
script builds one command per visible bot command (``bot.commands.ALL_COMMANDS``),
each with a single free-text ``args`` option that the Discord adapter turns back
into ``/<name> <args>``, and replaces the application's command list.

Usage::

    # Print the payload without calling Discord
    python scripts/register_discord_commands.py --dry-run

    # Register globally (can take up to an hour to appear) or for one server (instant)
    DISCORD_APPLICATION_ID=... DISCORD_BOT_TOKEN=... python scripts/register_discord_commands.py
    python scripts/register_discord_commands.py --guild-id 123456789012345678

Commands are registered with ``default_member_permissions="0"``: only server
administrators see them until an administrator grants them to roles or members in
Server Settings -> Integrations. Every command can start paid LLM work, so widen
access deliberately.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DISCORD_API_BASE = "https://discord.com/api/v10"
_NAME_RE = re.compile(r"^[-_a-z0-9]{1,32}$")
_MAX_DESCRIPTION = 100


def _clip(text: str, limit: int = _MAX_DESCRIPTION) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def build_command_payload() -> List[Dict[str, Any]]:
    """Return the Discord application-command definitions for the visible bot commands."""

    from bot.commands import ALL_COMMANDS

    payload: List[Dict[str, Any]] = []
    for command_cls in ALL_COMMANDS:
        command = command_cls()
        if command.hidden:
            continue
        name = command.name.strip().lower()
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"bot command name {command.name!r} is not a valid Discord command name")
        payload.append(
            {
                "name": name,
                "type": 1,  # CHAT_INPUT (slash command)
                "description": _clip(command.description) or name,
                "options": [
                    {
                        "type": 3,  # STRING
                        "name": "args",
                        "description": _clip(f"Arguments, as in {command.usage}"),
                        "required": False,
                    }
                ],
                "default_member_permissions": "0",
                "dm_permission": False,
            }
        )
    return payload


def register(application_id: str, bot_token: str, guild_id: Optional[str], payload: List[Dict[str, Any]]) -> int:
    import requests

    if guild_id:
        url = f"{DISCORD_API_BASE}/applications/{application_id}/guilds/{guild_id}/commands"
    else:
        url = f"{DISCORD_API_BASE}/applications/{application_id}/commands"
    response = requests.put(
        url,
        headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=20,
    )
    if response.status_code >= 300:
        print(f"Discord rejected the commands: HTTP {response.status_code} {response.text[:500]}", file=sys.stderr)
        return 1
    names = ", ".join(f"/{item['name']}" for item in response.json())
    scope = f"server {guild_id}" if guild_id else "all servers (global)"
    print(f"Registered {len(payload)} commands for {scope}: {names}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Register the bot's slash commands with Discord.")
    parser.add_argument("--application-id", default=os.getenv("DISCORD_APPLICATION_ID", ""))
    parser.add_argument("--guild-id", default=os.getenv("DISCORD_GUILD_ID", ""), help="register for one server only")
    parser.add_argument("--dry-run", action="store_true", help="print the payload and do not call Discord")
    args = parser.parse_args(argv)

    payload = build_command_payload()
    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    bot_token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    application_id = (args.application_id or "").strip()
    if not application_id or not bot_token:
        print("Set DISCORD_APPLICATION_ID (or --application-id) and DISCORD_BOT_TOKEN.", file=sys.stderr)
        return 2
    return register(application_id, bot_token, (args.guild_id or "").strip() or None, payload)


if __name__ == "__main__":
    raise SystemExit(main())
