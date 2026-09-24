# Zeabur Deployment Guide

This guide walks through deploying the AI stock analysis system on Zeabur, including the WebUI and the Discord bot.

## Contents

- [1. Before you deploy](#1-before-you-deploy)
- [2. Deploying on Zeabur](#2-deploying-on-zeabur)
- [3. Configuring the start command](#3-configuring-the-start-command)
- [4. Deploying the Discord bot](#4-deploying-the-discord-bot)
- [5. Environment variable configuration](#5-environment-variable-configuration)
- [6. Volume mounts](#6-volume-mounts)
- [7. Health checks](#7-health-checks)
- [8. FAQ](#8-faq)

## 1. Before you deploy

### 1.1 Requirements

- A Zeabur account
- A GitHub account (to connect the repository)
- A Discord developer account (if you are deploying the bot)
- The relevant API keys (a Gemini API key, search service API keys, and so on)

### 1.2 Repository preparation

Make sure your repository contains:

- `.github/workflows/docker-publish.yml` (created automatically)
- `docker/Dockerfile` (already present)
- The complete project code

## 2. Deploying on Zeabur

### 2.1 Connect the GitHub repository

1. Sign in to the Zeabur console
2. Click "New Project"
3. Choose "Import from GitHub"
4. Select your repository and branch (`main` is recommended)
5. Click "Import"

### 2.2 Configure the build rule

Zeabur detects `.github/workflows/docker-publish.yml` automatically and builds the image with GitHub Actions.

If it is not detected, configure it by hand:

1. On the project page, click "Build Rules"
2. Choose "Dockerfile"
3. Set the Dockerfile path to `docker/Dockerfile`
4. Click "Save"

### 2.3 Start the service

1. Wait for the image build to finish
2. Click "Start Service"
3. Once it is running, the access URL is on the "Networking" tab

### 2.4 Frontend build and static assets

FastAPI serves the frontend assets under `static/` automatically. The frontend build output location is decided by
`apps/dsa-web/vite.config.ts` and defaults to `static/` in the project root.

The Dockerfile uses a multi-stage build, so the frontend is bundled during the image build.
To override the default static assets, build them on the host and mount them at `/app/static` inside the container.

### 2.5 Resource sizing

Start a Zeabur service at `1G` of memory. `512M` suits only a lightweight Web/API, single-stock, low-concurrency setup, and `MAX_WORKERS=1` is recommended there.

- Bare minimum: `512M`, with no two heavy tasks running at once.
- Recommended: `1G`, for regular single-service analysis.
- High load: `2G+`, for running the Web/API alongside scheduled analysis, many stocks, market review, news enrichment, image reports, or screening.

If `512M` is all you have, avoid deploying a multi-service combination equivalent to `server + analyzer`, and turn off the market review, news enrichment, and image report features you do not need.

## 3. Configuring the start command

### 3.1 Supported start modes

The system supports several start modes, so you can configure the start command you need:

| Mode | Start command | Description |
|------|----------|------|
| Scheduled mode (default) | `python main.py --schedule` | Runs stock analysis on a schedule |
| FastAPI mode | `python main.py --serve` | Starts FastAPI and runs an analysis |
| FastAPI-only mode | `python main.py --serve-only` | Starts FastAPI without running an analysis |
| Market review only | `python main.py --market-review` | Runs the market review analysis only |

### 3.2 Setting the start command

1. In the Zeabur console, open the service page
2. Click "Settings"
3. Find the "Start Command" option
4. Enter the start command you need, for example:
    - Start FastAPI: `python main.py --serve`
    - Start FastAPI only: `python main.py --serve-only --host 0.0.0.0 --port 8000`
    - Start the scheduler: `python main.py --schedule`
5. Click "Save"
6. Restart the service

## 4. Deploying the Discord bot

### 4.1 Preparation

1. Create a Discord application and bot
   - Go to the [Discord developer portal](https://discord.com/developers/applications)
   - Click "New Application" to create an application
   - On the "Bot" tab, click "Add Bot" to create the bot
   - Copy the bot token

2. Configure the bot permissions
   - On the "Bot" tab, scroll down to "Privileged Gateway Intents"
   - Enable "Server Members Intent" and "Message Content Intent"
   - Under "OAuth2" -> "URL Generator", select the "bot" scope
   - Select the permissions you need (such as "Send Messages" and "Read Messages/View Channels")
   - Copy the generated invite link and add the bot to your server

### 4.2 Configure the environment variables

Under "Environment Variables" in the Zeabur console, add:

| Variable | Description | Example |
|--------|------|--------|
| `DISCORD_BOT_TOKEN` | The Discord bot token | `MTAxMjM0NTY3ODkwMTEyMzQ1Ng.GhIjKl.MnOpQrStUvWxYz1234567890` |
| `DISCORD_MAIN_CHANNEL_ID` | The main channel ID | `123456789012345678` |
| `DISCORD_WEBHOOK_URL` | The Discord webhook URL (optional) | `https://discord.com/api/webhooks/...` |

### 4.3 Start the bot

The bot is enabled by configuration and needs no special start command. Make sure your configuration file contains the bot settings, or set them through environment variables.

## 5. Environment variable configuration

### 5.1 Basic environment variables

| Variable | Description | Default |
|--------|------|--------|
| `PYTHONUNBUFFERED` | Enables unbuffered Python output | `1` |
| `LOG_DIR` | The log directory | `/app/logs` |
| `DATABASE_PATH` | The database path | `/app/data/stock_analysis.db` |

### 5.2 API service configuration

| Variable | Description | Default |
|--------|------|--------|
| `API_HOST` | The API service listen address | `0.0.0.0` |
| `API_PORT` | The API service port | `8000` |

> The legacy `WEBUI_HOST`/`WEBUI_PORT`/`WEBUI_ENABLED` environment variables are still supported and are forwarded to the API service automatically.

### 5.3 Analysis configuration

| Variable | Description |
|--------|------|
| `ANSPIRE_API_KEYS` | The Anspire Open API key (shared by the LLM and search; recommended) |
| `AIHUBMIX_KEY` | The AIHubMix API key (one key, many models; recommended) |
| `GEMINI_API_KEY` | The Gemini API key |
| `OPENAI_API_KEY` | An OpenAI-compatible API key |
| `SERPAPI_API_KEYS` | The SerpAPI key (recommended) |
| `TAVILY_API_KEYS` | Tavily API keys (comma-separated) |
| `BOCHA_API_KEYS` | Bocha API keys (comma-separated) |
| `BRAVE_API_KEYS` | Brave Search API keys (comma-separated) |
| `MINIMAX_API_KEYS` | MiniMax API keys (comma-separated) |
| `SEARXNG_BASE_URLS` | SearXNG instance URLs (comma-separated, no quota fallback, and `format: json` must be enabled in settings.yml). When empty, `searx.space` is used only after public-instance discovery is enabled explicitly |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | Whether to fetch public instances from `searx.space` when `SEARXNG_BASE_URLS` is empty (defaults to `false`) |

### 5.4 How to configure them

In the Zeabur console:

1. Open the service page
2. Click "Environment Variables"
3. Click "Add Environment Variable"
4. Enter the name and value
5. Click "Save"
6. Restart the service

## 6. Volume mounts

### 6.1 Supported mount directories

| Directory | Description |
|------|------|
| `/app/data` | The database and data files |
| `/app/logs` | Log files |
| `/app/reports` | Analysis reports |

### 6.2 Configuring a mount

1. In the Zeabur console, open the service page
2. Click "Storage"
3. Click "Add Volume"
4. Choose "Persistent Storage"
5. Configure the mount path:
   - Volume path: `/app/data`
   - Container path: `/app/data`
6. Click "Save"
7. Repeat for the other directories you want mounted

### 6.3 Notes

- Once mounted, data persists and is not lost when the container restarts
- Mounting at least `/app/data` is recommended, so the database survives

## 7. Health checks

The system has a built-in health check that by default checks:

- WebUI mode: the `http://localhost:8000/health` endpoint
- FastAPI mode: the `http://localhost:8000/api/health` endpoint
- Non-service mode: always reports healthy

The health check is configured as:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || curl -f http://localhost:8000/health \
    || python -c "import sys; sys.exit(0)"
```

## 8. FAQ

### 8.1 The API service is unreachable

- Check that the start command includes `--serve` or `--serve-only`
- Check that a domain is configured on the "Networking" tab
- Check the firewall settings

### 8.2 The bot does not respond

- Check that the Discord bot token is correct
- Check that the bot was added to the server
- Check that the bot has enough permissions
- Check the log files for errors

### 8.3 Analysis jobs do not run

- Check that the schedule configuration is correct
- Check that the API keys are valid
- Check the log files for errors

### 8.4 Data loss

- Make sure `/app/data` is mounted
- Check that the volume configuration is correct

## 9. Advanced configuration

### 9.1 Multi-instance deployment

You can deploy several instances on Zeabur for different jobs:

1. One instance for the API service (`python main.py --serve-only`)
2. One instance for the scheduler (`python main.py --schedule`)
3. One instance for the bot (`python main.py --discord-bot`)

Make sure they share the same `/app/data` volume so they share the database.

### 9.2 Custom domain

On the "Networking" tab of the Zeabur console you can:

1. Use the automatically generated domain
2. Bind a custom domain
3. Configure HTTPS

## 10. Updating a deployment

### 10.1 Automatic updates

When you push new code to the repository:

1. GitHub Actions builds a new image automatically
2. Zeabur detects the new image
3. You can choose "Auto Deploy" or trigger a deployment by hand

### 10.2 Manual updates

1. In the Zeabur console, open the service page
2. Click "Deployment History"
3. Choose "Redeploy"
4. Or click "Update Image"

## 11. Monitoring and logs

### 11.1 Viewing logs

In the Zeabur console, open the service page and click the "Logs" tab to see live and historical logs.

### 11.2 Metrics

Zeabur provides basic metrics:

- CPU usage
- Memory usage
- Network traffic
- Disk usage

See the "Monitoring" tab for details.

## 12. Troubleshooting

### 12.1 Reading the detailed log

```bash
# Enter the container
zeabur exec <service-name> bash

# Read the log file
cat /app/logs/stock_analysis_20260125.log
```

### 12.2 Checking the configuration

```bash
# Enter the container
zeabur exec <service-name> bash

# Check the environment variables
printenv | grep -i discord
printenv | grep -i webui
```

### 12.3 Testing connectivity

```bash
# Test the network connection
zeabur exec <service-name> curl -I https://api.discord.com

# Test the API connection
zeabur exec <service-name> python -c "import requests; print(requests.get('https://api.discord.com').status_code)"
```

## 13. Best practices

1. **Use persistent storage**: always mount `/app/data`, so the database survives
2. **Configure a sensible health check**: tune the health check parameters to your setup
3. **Keep secrets in environment variables**: never hard-code an API key into the source
4. **Back up regularly**: download the contents of `/app/data` for backup on a regular basis
5. **Pick the right start mode**: choose the start command that matches your needs
6. **Monitor the service**: check the service status and logs regularly
7. **Size the memory to the load**: start at `1G` for a full analysis; set `MAX_WORKERS=1` on a `512M` low-spec environment, and use `2G+` under high load

## 14. Contact

If you have a question, contact the project maintainers or ask in GitHub Issues.
