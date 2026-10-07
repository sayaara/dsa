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
DISCORD_INTERACTIONS_PUBLIC_KEY=your-public-key (needed only for inbound slash commands)
DISCORD_APPLICATION_ID=your-application-id (needed only to register the slash commands)
```

`DISCORD_BOT_TOKEN`, `DISCORD_MAIN_CHANNEL_ID` and `DISCORD_WEBHOOK_URL` are for **outbound** notifications (reports posted to a channel). The two keys below them are for **inbound** slash commands.

## Webhook mode (optional)

If you only want to send messages through a webhook and need no bot token, configure it like this:

1. Right-click the channel and choose "Edit Channel"
2. Click "Integrations" > "Webhooks" > "New Webhook"
3. Set the webhook name and avatar
4. Copy the webhook URL (this is your `DISCORD_WEBHOOK_URL`)

## Inbound slash commands

Slash commands let people in your server run the bot's commands (`/analyze AAPL`, `/market`, `/ask`, and so on). Discord sends each command to your DSA server, so the server must be reachable over public HTTPS.

1. **Public key.** Copy `General Information -> Public Key` from the Discord Developer Portal into `DISCORD_INTERACTIONS_PUBLIC_KEY` and restart DSA. Every inbound request is checked against this key (Ed25519); requests that fail are rejected with 401 before anything runs.
2. **Interactions endpoint.** In `General Information -> Interactions Endpoint URL`, enter `https://<your-host>/api/v1/bot/discord/interactions` and save. Discord sends a signed PING to verify the URL; DSA answers it, so saving succeeds only when the public key matches. The route does not need the Web login (Discord cannot log in); the signature check replaces it.
3. **Register the commands.** Discord only shows registered commands. With `DISCORD_APPLICATION_ID` (`General Information -> Application ID`) and `DISCORD_BOT_TOKEN` set, run:

   ```bash
   python scripts/register_discord_commands.py --guild-id <your-server-id>
   ```

   `--guild-id` registers for one server and shows the commands at once; without it the commands are global and can take up to an hour to appear. `--dry-run` prints the payload without calling Discord. Run it again after commands change.
4. **Grant access.** Commands are registered as administrator-only (`default_member_permissions = "0"`) because each one can start paid LLM work. To let others use them, open `Server Settings -> Integrations -> <your app>` and allow the roles or members you choose. Per-user rate limits (`BOT_RATE_LIMIT_REQUESTS` per `BOT_RATE_LIMIT_WINDOW` seconds) still apply.

## Supported commands

Each command takes one free-text `args` option, written the same way as the text command:

| Command | Example `args` | What it does |
|---|---|---|
| `/analyze` | `AAPL`, `RY.TO full` | Analyze a US or Canadian stock (`full` adds the market context) |
| `/market` | (none) | Market review |
| `/ask` | `AAPL bull_trend` | Analyze stocks with an Agent skill |
| `/chat` | `What moved NVDA today?` | Free chat with the assistant (Agent mode) |
| `/research` | `AAPL services margin` | Deep research on a stock or topic |
| `/batch` | `5` | Analyze the first N watchlist stocks |
| `/strategies` | `active` | List the trading strategies |
| `/history` | `clear` | Agent chat history |
| `/status` | (none) | System status |
| `/help` | `analyze` | Help |

Hong Kong and mainland China codes are rejected as unsupported.

## Testing the bot

1. Make sure the bot was added to your server and the commands are registered
2. Run `/help`; the bot answers with the help text
3. Run `/analyze` with `args` = `AAPL`; Discord shows "thinking..." and the result replaces it when the analysis finishes
4. Run `/market` to test the market review

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
- **Slash commands do not appear**: run `scripts/register_discord_commands.py` (with `--guild-id` they appear at once; global commands can take up to an hour), and check that your role was granted the commands in Server Settings -> Integrations
- **Saving the Interactions Endpoint URL fails**: DSA must be reachable over public HTTPS and `DISCORD_INTERACTIONS_PUBLIC_KEY` must match the application's public key
- **Sending a message fails**: check the channel permissions and make sure the bot can send messages

## Related links

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Bot Documentation](https://discordpy.readthedocs.io/en/stable/)
- [Discord Slash Commands](https://discord.com/developers/docs/interactions/application-commands)
