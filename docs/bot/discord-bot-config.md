# Discord Bot Configuration

## The Discord bot
Receiving messages with a Discord bot requires a bot application created in the Discord Developer Portal:
https://discord.com/developers/applications

The Discord bot supports two ways of sending messages:
1. **Webhook mode**: simple to configure and low-privilege, suited to sending messages only
2. **Bot API mode**: higher privilege, supports receiving commands, and needs a bot token and channel ID

## Creating the Discord bot

### 1. Sign in to the Discord Developer Portal
Go to https://discord.com/developers/applications and sign in with your Discord account

### 2. Create the application
Click "New Application", enter an application name (for example, AI Stock Analysis Bot), then click "Create"

### 3. Configure the bot
Click "Bot" in the left navigation, then click "Add Bot" and confirm

### 4. Get the bot token
On the Bot page, click "Reset Token" and copy the generated token (this is your `DISCORD_BOT_TOKEN`)

### 5. Configure the permissions
In the "Privileged Gateway Intents" section of the Bot page, enable:
- Presence Intent
- Server Members Intent
- Message Content Intent

### 6. Add it to a server
1. Click "OAuth2" > "URL Generator" in the left navigation
2. Under "Scopes", select:
   - `bot`
   - `applications.commands`
3. Under "Bot Permissions", select:
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Use Slash Commands
4. Copy the generated URL, open it in a browser, and pick the server to add the bot to

### 7. Get the channel ID
1. In the Discord client, enable developer mode: Settings > Advanced > Developer Mode
2. Right-click the channel you want the bot to post in and choose "Copy ID" (this is your `DISCORD_MAIN_CHANNEL_ID`)

## Configuring the environment variables

Add the following to your `.env` file:

```env
# Discord bot configuration
DISCORD_BOT_TOKEN=your-discord-bot-token
DISCORD_MAIN_CHANNEL_ID=your-channel-id
DISCORD_WEBHOOK_URL=your-webhook-url (optional)
DISCORD_INTERACTIONS_PUBLIC_KEY=your-public-key (needed only for inbound Interaction/Webhook callbacks)
DISCORD_BOT_STATUS=A股智能分析 | /help
```

If you configure inbound Discord Interaction / webhook callbacks, copy the public key from `General Information -> Public Key` in the Discord Developer Portal into `DISCORD_INTERACTIONS_PUBLIC_KEY`. The system verifies the Ed25519 signature of every inbound request with that key and rejects the request outright when verification fails.

## Webhook mode (optional)

If you only want to send messages through a webhook and need no bot token, configure it like this:

1. Right-click the channel and choose "Edit Channel"
2. Click "Integrations" > "Webhooks" > "New Webhook"
3. Set the webhook name and avatar
4. Copy the webhook URL (this is your `DISCORD_WEBHOOK_URL`)

## Supported commands

The Discord bot supports these slash commands:

1. `/analyze <target> [full_report]` - analyze a stock, a registered index, or a stock name
   - `target`: what to analyze — a stock code (such as `600519`), a registered index (such as `sh000016`, `930955.CSI`, or `上证50`), or a stock name (such as `贵州茅台`)
   - `full_report`: optional; whether to generate the full report (including the market)

2. `/market_review` - get the market review report

3. `/help` - show the help message

> Boundary: `/analyze` accepts registered indices and stock names (a stock name reuses the existing name resolver and submits the legacy code); `/ask` and `/batch` do not accept an index yet.

## Testing the bot

1. Make sure the bot was added to your server successfully
2. Type `/help` in a channel and the bot replies with the help message
3. Type `/analyze 600519` to test stock analysis (a registered index such as `/analyze sh000016` and a stock name such as `/analyze 贵州茅台` work too)
4. Type `/market_review` to test the market review

## Notes

1. Make sure the bot has enough permission to send messages and use slash commands in the channel
2. Rotate your bot token regularly to keep it secure
3. Never share your bot token with anyone
4. If the bot does not respond, check:
   - Whether the bot token is correct
   - Whether the channel ID is correct
   - Whether the bot is online
   - Whether the bot has permission to send messages

## Troubleshooting

- **The bot does not respond to commands**: check that the bot token and channel ID are correct, and that the bot was added to the server
- **Slash commands do not appear**: wait a while (Discord needs to sync the commands), or re-add the bot
- **Sending a message fails**: check the channel permissions and make sure the bot can send messages

## Related links

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Bot Documentation](https://discordpy.readthedocs.io/en/stable/)
- [Discord Slash Commands](https://discord.com/developers/docs/interactions/application-commands)
