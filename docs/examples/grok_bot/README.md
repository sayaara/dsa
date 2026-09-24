# Grok Bot Skill Example

A minimal skill package for the 2026-08-11 [Grok Bot](https://x.ai/bot). It calls DSA's existing REST endpoints only and introduces no new API, environment variable, or MCP server.

Copy [`SKILL.md`](SKILL.md) into the bot's Skills directory, set `DSA_BASE_URL` (for example `http://127.0.0.1:8000`), and keep DSA running first with `python main.py --serve-only` or in Docker.

For the complete boundary, the DecisionSignal routine, and the authentication limits, see [Grok Bot integration](../../grok-bot-integration.md). openclaw users should read the [openclaw skill](../../openclaw-skill-integration.md), which follows the same contract.
