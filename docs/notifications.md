# Notification Capability Baseline

This document records the P0-P7 end state of the notification capability: channels, configuration keys, the GitHub Actions mapping, web settings metadata, the CLI diagnostic contract, the web one-click test, custom webhook body-template semantics, notification routing policy, the noise-suppression mechanism, aggregate-report failure isolation, ntfy / Gotify as first-class channels, the WebPush / Apprise evaluation, and scenario-specific configuration notes for local, Docker, GitHub Actions, and desktop. P0 covered the baseline and read-only diagnostics only; P1 added a real single-channel test in the web UI; P2 productized the existing body template; P3 added report / alert / system_error routing; P4 added in-process noise suppression; P5 strengthened test diagnostics and per-channel failure isolation for aggregate reports; P6-A added ntfy; P6-C added Gotify; P6-D only evaluated WebPush / Apprise; P7 closed out the documentation and automated the Actions env comparison table, adding no runtime dependency, configuration entrypoint, per-URL template, cross-process persistence, real daily digest, or retry loop.

## Channel baseline

| Channel | Type | Minimal key | Advanced key | Notes |
| --- | --- | --- | --- | --- |
| Telegram | Static configuration | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `TELEGRAM_MESSAGE_THREAD_ID` | The token and chat ID must both be present |
| Email | Static configuration | `EMAIL_SENDER`, `EMAIL_PASSWORD` | `EMAIL_RECEIVERS`, `EMAIL_SENDER_NAME` | An empty `EMAIL_RECEIVERS` sends to yourself |
| Pushover | Static configuration | `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN` | - | Both keys must be present |
| ntfy | Static configuration | `NTFY_URL` | `NTFY_TOKEN`, `WEBHOOK_VERIFY_SSL` | `NTFY_URL` must include the topic path, for example `https://ntfy.sh/my-topic` |
| Gotify | Static configuration | `GOTIFY_URL`, `GOTIFY_TOKEN` | `WEBHOOK_VERIFY_SSL` | `GOTIFY_URL` is the server base URL and excludes `/message`; the token is sent in the `X-Gotify-Key` header |
| Custom webhook | Static configuration | `CUSTOM_WEBHOOK_URLS` | `CUSTOM_WEBHOOK_BEARER_TOKEN`, `CUSTOM_WEBHOOK_BODY_TEMPLATE`, `WEBHOOK_VERIFY_SSL` | Supports several comma-separated URLs |
| Discord | Static configuration | `DISCORD_WEBHOOK_URL`, or `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` | `DISCORD_INTERACTIONS_PUBLIC_KEY` | Either the webhook or the bot can enable sending |
| Slack | Static configuration | `SLACK_WEBHOOK_URL`, or `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | - | The bot is preferred for sending text and images to the same channel |
| AstrBot | Static configuration | `ASTRBOT_URL` | `ASTRBOT_TOKEN`, `WEBHOOK_VERIFY_SSL` | `ASTRBOT_TOKEN` is optional |
| `UNKNOWN` | Fallback enumeration | - | - | A fallback for unknown channels only; never enabled by a static environment variable |
| Telegram conversation | Runtime context | - | - | Extracted from the source message context; an interactive command's result goes back only to the source conversation |

Sending a long Discord report reuses the existing chunking path: one `content` never exceeds Discord's 2000-character limit at runtime, and both the webhook and the Bot API send chunk by chunk with a short wait between chunks. On a 429 they retry a bounded number of times using the `retry_after` or `Retry-After` Discord returns, so a mid-run rate limit cannot leave the recipient with only the first half of the report.

## The Minimal / Advanced split

- A minimal key is the smallest configuration that enables one notification channel.
- An advanced key affects only authentication, security, formatting, threading, grouping, certificate verification, or presentation, and cannot enable a channel on its own.
- P3's `NOTIFICATION_*_CHANNELS` are advanced keys: they only narrow the already-enabled channels and never enable one.
- P4's `NOTIFICATION_DEDUP_TTL_SECONDS`, `NOTIFICATION_COOLDOWN_SECONDS`, `NOTIFICATION_QUIET_HOURS`, `NOTIFICATION_TIMEZONE`, `NOTIFICATION_MIN_SEVERITY`, and `NOTIFICATION_DAILY_DIGEST_ENABLED` are advanced keys: they affect only the send policy of already-enabled static channels and never enable one.
- `REPORT_SHOW_LLM_MODEL` is a report-presentation toggle: at its default `true` the LLM model used for the analysis appears at the bottom of the notification report, and `false` hides it. It affects report rendering only and never changes the runtime provider/model/Base URL, LiteLLM routing, model persistence, migration, or cleanup logic; to roll back, set it to `true` again or remove the variable.
- `WEBHOOK_VERIFY_SSL` is the shared certificate-verification toggle for the webhook-style HTTPS notification requests that read it.
- WebPush, Apprise, finer-grained routing, cross-process noise suppression, and a real daily digest are not in the runtime implementation yet. If those configurations are introduced later, this document, `.env.example`, the web metadata, and the regression tests should be updated first.
- Bark stays on the custom webhook baseline; no first-class `BARK_*` configuration is added.

## Report rendering and chunking

The entrypoint, content source, and overall layout of the reports pushed today are unchanged. This stage converges only the technical route of notification rendering: a channel capability profile, a pre-send message structure, and structure-aware chunking, so that later per-channel extensions do not keep stacking parallel logic inside each sender.

The default send path keeps the existing sender behavior and wires in no new renderer: Telegram keeps its existing compatibility conversion, and Slack keeps its existing chunking, so the report layout visible in production does not change. The new channel capability profile, PreparedMessage, renderer presets, and structure-aware chunking are groundwork for later extension only. Enabling a channel-specific renderer for Telegram, Slack, and so on should proceed gradually, through explicit configuration, real send verification, and regression tests.

Compatibility exclusions:
- This round did not change the send paths in `src/notification_sender/slack_sender.py` or `src/notification_sender/telegram_sender.py`.
- `model_used` appears only at the end of report rendering and takes no part in runtime provider/model/base_url selection, persistence, cleanup, or migration. If a CI scan matches a "provider/API compatibility migration" keyword, the match should be traced back to the `model_used` example in the test fixtures and the report snapshot fixtures (`tests/fixtures/notification_reports/*.md`), and to the display-only `report_show_llm_model` toggle logic in `src/notification.py`.
- `REPORT_SHOW_LLM_MODEL` and `report_renderer_enabled` are both presentation/degradation toggles: turning them off changes only the visible report structure and triggers no configuration migration or runtime parameter rollback. To roll back, restore `true` (or remove the entry) or restore the default configuration.

Related-board rendering stays in the report-body generation stage. With no industry or concept gainer/loser signal, the pushed report keeps the original single-line style, for example `通信线缆及配套 / 通信设备 / 通信 / 江苏板块 / 科技风格`, and shows no extra type column. Only when a leading-gainer or leading-loser signal in `fundamental_context.boards.data` / `sector_rankings` or `fundamental_context.concept_boards.data` / `concept_rankings` matches does it use a table of board / type / board performance / board change, where the type column marks the board as "行业板块" or "概念板块". This logic affects report presentation only and changes no provider/model/Base URL, LiteLLM routing, model persistence, migration, or cleanup logic.

## GitHub Actions mapping

The bundled `.github/workflows/00-daily-analysis.yml` imports only a fixed set of variable names explicitly. P0/P3/P4/P6 already brought notification keys such as the body template, security entries, routing, noise suppression, ntfy, and Gotify into the default workflow. The table below is generated by `scripts/generate_notification_actions_env_table.py` from the workflow's `env:` block and the notification diagnostic metadata, so a hand-written comparison table cannot keep drifting away from the real Actions mapping.

<!-- notification-actions-env-table:start -->

| Key | Tier | Channel / feature | Actions source | Default |
| --- | --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | minimal | telegram | Secret | - |
| `TELEGRAM_CHAT_ID` | minimal | telegram | Secret | - |
| `TELEGRAM_MESSAGE_THREAD_ID` | advanced | telegram | Secret | - |
| `EMAIL_SENDER` | minimal | email | Variable or Secret | - |
| `EMAIL_PASSWORD` | minimal | email | Secret | - |
| `EMAIL_RECEIVERS` | advanced | email | Variable or Secret | - |
| `EMAIL_SENDER_NAME` | advanced | email | Variable or Secret | `Stock Analysis Assistant` |
| `PUSHOVER_USER_KEY` | minimal | pushover | Secret | - |
| `PUSHOVER_API_TOKEN` | minimal | pushover | Secret | - |
| `NTFY_URL` | minimal | ntfy | Secret | - |
| `NTFY_TOKEN` | advanced | ntfy | Secret | - |
| `GOTIFY_URL` | minimal | gotify | Secret | - |
| `GOTIFY_TOKEN` | minimal | gotify | Secret | - |
| `CUSTOM_WEBHOOK_URLS` | minimal | custom | Secret | - |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | advanced | custom | Secret | - |
| `CUSTOM_WEBHOOK_BODY_TEMPLATE` | advanced | custom | Variable or Secret | - |
| `WEBHOOK_VERIFY_SSL` | advanced | ntfy, gotify, custom, astrbot | Variable or Secret | `true` |
| `DISCORD_WEBHOOK_URL` | minimal | discord | Secret | - |
| `DISCORD_BOT_TOKEN` | minimal | discord | Secret | - |
| `DISCORD_MAIN_CHANNEL_ID` | minimal | discord | Secret | - |
| `ASTRBOT_URL` | minimal | astrbot | Secret | - |
| `ASTRBOT_TOKEN` | advanced | astrbot | Secret | - |
| `SLACK_WEBHOOK_URL` | minimal | slack | Secret | - |
| `SLACK_BOT_TOKEN` | minimal | slack | Secret | - |
| `SLACK_CHANNEL_ID` | minimal | slack | Secret | - |
| `NOTIFICATION_REPORT_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_ALERT_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | advanced | routing | Variable or Secret | - |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | advanced | noise | Variable or Secret | `0` |
| `NOTIFICATION_COOLDOWN_SECONDS` | advanced | noise | Variable or Secret | `0` |
| `NOTIFICATION_QUIET_HOURS` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_TIMEZONE` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_MIN_SEVERITY` | advanced | noise | Variable or Secret | - |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | advanced | noise | Variable or Secret | `false` |

<!-- notification-actions-env-table:end -->

The default workflow still does not map `MARKDOWN_TO_IMAGE_CHANNELS` or `MERGE_EMAIL_NOTIFICATION`. They are send-form or aggregation toggles rather than channel credentials, and having Actions start reading an identically named secret/variable automatically would introduce extra behavior changes.

## Image report sharing template

With `MARKDOWN_TO_IMAGE_CHANNELS` configured, single-stock analysis, aggregate reports, and market reviews follow the existing notification routing and apply a 1080px-wide branded sharing template at the image-conversion stage. A single stock produces a decision card laid out as conclusion, price levels, technicals, risks, and holdings; the market review produces a review card laid out as signal, indices, breadth, strong/weak sectors, capital watch, key follow-ups, strategy, and risks; a multi-stock report keeps the aggregate layout. The footer shows the GitHub repository address, an optional Xiaohongshu account area, and the "仅供研究交流，不构成投资建议" risk disclaimer.

- The Xiaohongshu URL, display name, and QR-code path can be overridden through `SHARE_IMAGE_XIAOHONGSHU_*`; only the display name appears below the QR code, never a numeric ID. When all of them are empty, no social account is shown. The QR code is embedded in the HTML at conversion time and depends on no external image service or runtime network access.
- The template shows only the 0-100 score, the eight-state action, and the `battle_plan.sniper_points` levels the report already has. The ideal and secondary entry points, the stop loss, and the target use a dedicated high-contrast trading card; no extra score or long/short ratio is generated.
- For the structured fields, missing-value behavior, single-stock/market mapping, and a local preview example, see [the sharing image template and data filling](share-images.md).
- `wkhtmltoimage`, `markdown-to-file`, and `playwright` share one poster HTML; the existing `MD2IMG_ENGINE` and `MARKDOWN_TO_IMAGE_MAX_CHARS` behavior, and the text fallback after a failed conversion, are unchanged. Playwright mode requires the web dependencies plus `npx playwright install chromium`.
- The template produces a tall image sized to the body length and never truncates a report to fit a fixed frame. Content over `MARKDOWN_TO_IMAGE_MAX_CHARS` still skips image conversion.
- GitHub Actions still does not map `MARKDOWN_TO_IMAGE_CHANNELS` by default; to enable it in a forked workflow, add the environment-variable mapping explicitly and install the chosen conversion tool.

## CLI diagnostics

```bash
python main.py --check-notify
```

The command reads the configuration only: it sends no notification and writes no `.env`. It runs immediately after configuration loading and log initialization, then exits without entering the web, scheduler, market-review, or default analysis flow.

- Exit code `0`: no error-level diagnostic.
- Exit code `1`: an error is present — for example, zero static notification channels are configured, or only half of a paired key is set.

## The web one-click test

The notification channels category on the web settings page provides a single-channel test entrypoint. The test builds a temporary configuration from the current page draft and sends one real test notification, but it neither saves `.env` nor modifies the runtime global configuration.

- Test scope: the 14 static notification channels, excluding `UNKNOWN` and the runtime-context channels.
- Ordinary channels: returns one send result, its duration, and a generic error code.
- Custom webhook: returns attempts in URL order, showing each URL's success or failure, HTTP status, duration, and error code. When several URLs partially succeed, the top-level message reports the success count out of the total.
- The returned result redacts tokens, secrets, passwords, Bearer values, the full webhook query, and anything that looks like a path token.
- Missing configuration or a failed send returns `success=false` and affects neither the saved configuration nor the default analysis flow.

## The custom webhook body template

`CUSTOM_WEBHOOK_BODY_TEMPLATE` is the global JSON body template for custom webhooks. Once configured it takes effect ahead of URL auto-detection, so it overrides the automatic Bark, Slack, and Discord payloads. With no template configured, the original URL auto-detection still applies. When the rendered result is not a valid JSON object, an error is logged and the default payload is used instead, without interrupting the main notification flow.

Available placeholders:

- `$content_json`: the JSON-escaped notification body, and the recommended default.
- `$title_json`: the JSON-escaped notification title, and the recommended default.
- `$content` / `$title`: the raw strings, without JSON escaping. A body containing a double quote, backslash, or newline may produce invalid JSON and trigger the fallback.

In a Docker Compose deployment, saving this template to `.env` from the web settings page automatically writes the application placeholders as `$$content_json`, `$$title_json`, `$$content`, and `$$title`, so Compose does not treat them as host environment variables and expand them to nothing; the application restores a single `$` placeholder at runtime. When editing Docker's `.env` by hand, save them in the `$$content_json` form as well.

This feature affects notification body rendering only and has nothing to do with saving, migrating, or cleaning up the LLM `provider` / `model` / `base URL` / LiteLLM routing. If a structured scan matches provider/API compatibility semantics, the match belongs to this file's separation between report model presentation and notification configuration, not to the webhook fix path itself.

A generic webhook example:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"content":$content_json}
```

To use Bark through a custom webhook, put the Bark endpoint straight into `CUSTOM_WEBHOOK_URLS`; no extra `BARK_*` configuration is needed. With no global template configured, the system generates `title` / `body` / `group` automatically for `api.day.app`; with a global template configured, write the Bark body yourself:

```env
CUSTOM_WEBHOOK_URLS=https://api.day.app/YOUR_BARK_KEY
```

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"body":$content_json,"group":"stock"}
```

AstrBot is already a first-class notification channel, so prefer `ASTRBOT_URL` and the optional `ASTRBOT_TOKEN`. Use a custom webhook template only when an AstrBot-compatible endpoint has to go into `CUSTOM_WEBHOOK_URLS`, for example:

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$content_json}
```

ntfy is already a first-class notification channel, so prefer `NTFY_URL` and the optional `NTFY_TOKEN`. `NTFY_URL` is the complete topic endpoint, for example `https://ntfy.sh/my-topic` or `https://self-hosted:port/my-topic`; the system parses the last path segment as the topic and sends a JSON publish to the server root:

```env
NTFY_URL=https://ntfy.sh/my-topic
NTFY_TOKEN=
```

Gotify is already a first-class notification channel, so prefer `GOTIFY_URL` and `GOTIFY_TOKEN`. `GOTIFY_URL` is the Gotify server base URL and may include a reverse-proxy path prefix, but excludes `/message`; the system appends the fixed `/message` API when sending and passes the application token in the `X-Gotify-Key` header. `NTFY_URL` being a complete topic endpoint while `GOTIFY_URL` is a server base URL is a deliberate choice forced by the two services' API designs:

```env
GOTIFY_URL=https://gotify.example
GOTIFY_TOKEN=app-token
```

```env
# Reverse-proxy path prefix example; the real request goes to https://example.com/gotify/message
GOTIFY_URL=https://example.com/gotify
GOTIFY_TOKEN=app-token
```

The NapCat / OneBot HTTP API has to be adjusted to your actual endpoint and target type. The following are only common body shapes: `user_id`, `group_id`, the URL path, and the authentication method should all follow your own NapCat configuration:

```env
# Direct message: CUSTOM_WEBHOOK_URLS=http://127.0.0.1:3000/send_private_msg
CUSTOM_WEBHOOK_BODY_TEMPLATE={"user_id":123456,"message":$content_json}
```

```env
# Group message: CUSTOM_WEBHOOK_URLS=http://127.0.0.1:3000/send_group_msg
CUSTOM_WEBHOOK_BODY_TEMPLATE={"group_id":123456789,"message":$content_json}
```

## Notification routing policy

P3 added three kinds of notification routing configuration:

| Route type | Configuration key | Current producers |
| --- | --- | --- |
| `report` | `NOTIFICATION_REPORT_CHANNELS` | Single-stock push, the aggregate daily report, the market review, and merged pushes |
| `alert` | `NOTIFICATION_ALERT_CHANNELS` | EventMonitor trigger notifications |
| `system_error` | `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | A reserved capability; no automatic system-error producer is added yet |

The value is a comma-separated channel enumeration: `telegram,email,pushover,ntfy,gotify,custom,discord,slack,astrbot`.

- Empty or unset: the old behavior is kept, sending to every configured static channel.
- Non-empty: sends only to the intersection of the route list and the configured channels; an empty intersection does not fall back to all channels.
- `send_to_context()` is not subject to routing, so a bot conversation context still receives the reply for the task it triggered.
- When an interactive command (a Telegram conversation) carries a source context, static notification channels such as `DISCORD_WEBHOOK_URL` are skipped; `SCHEDULE`, CLI, API, and tasks with no source context still send over the report route.
- Route filtering happens before Markdown-to-image conversion, so `MARKDOWN_TO_IMAGE_CHANNELS` applies only to the post-routing channel subset.
- `MERGE_EMAIL_NOTIFICATION` needs no extra configuration; as long as `email` survives the report route, the existing merged-email behavior is unchanged.
- `--check-notify` reports an unknown channel value as an error, and a valid but disabled route target as a warning.

## Aggregate-report failure isolation

P5 strengthened the failure boundary on the aggregate-report notification path: after report-route filtering, `_send_notifications()` sends to each static notification channel separately. A channel that raises is logged and counted as that channel's failure, but it neither skips the remaining channels nor interrupts the main analysis flow.

- Email is isolated per receiver group; when one recipient group fails, the remaining groups still send.
- When any static channel succeeds, the P4 noise-suppression reservation is committed to a formal record; when every static channel fails or raises, the reservation is released.
- `send_to_context()` remains independent of static-channel routing and noise-suppression records, and is used to reply to the bot conversation context that triggered the task.

The decision-signal summary from #1390 P6 follows the same failure-isolation boundary: analysis-report notifications and alert notifications append only the low-sensitivity `decision_signal_summary` (action, horizon, reason, watch conditions, risks, and the source report) and never emit a signal's `metadata`, `evidence`, raw diagnostics, or a webhook/token. A failed alert notification records only the notification attempt or a dispatch fallback; it never rolls back an already-written trigger or DecisionSignal.

For the DecisionSignal notification summary fields, the sensitive-information boundary, and migration and rollback notes, see [the DecisionSignal topic](decision-signals.md).

## The notification noise-suppression mechanism

P4 added in-process noise suppression. It affects statically configured channels only, and never the bot-triggered conversation receipt from `send_to_context()`. Every option is off by default, so unset configuration keeps the old behavior.

| Configuration key | Default | Notes |
| --- | --- | --- |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | `0` | One stable dedup key sends only once within the TTL; `0` disables it |
| `NOTIFICATION_COOLDOWN_SECONDS` | `0` | One cooldown key is rate-limited within the window; `0` disables it |
| `NOTIFICATION_QUIET_HOURS` | empty | Quiet hours in `HH:MM-HH:MM` form, spanning midnight if needed |
| `NOTIFICATION_TIMEZONE` | empty | The quiet-hours time zone, such as `America/New_York`; empty uses the Python runtime's local time zone (usually decided by the process `TZ` or the system time zone) |
| `NOTIFICATION_MIN_SEVERITY` | empty | `info`, `warning`, `error`, `critical`; empty means no filtering |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | `false` | A reserved option; no daily digest is sent and no digest content is persisted yet |

Default severity levels:

- `report`: `info`
- `alert`: `warning`
- `system_error`: `error`
- An unknown or unset route: `info`

Implementation boundaries:

- Dedup and cooldown state is a dict inside the current Python process, which suits single-process `main.py` and a single-worker `--serve`.
- Under `uvicorn --workers N`, multiple containers, or multiple machines, the state is not shared, so noise suppression degrades to a per-worker approximation.
- The pipeline's single-stock and aggregate-report paths use stable keys so a changing generation timestamp inside the report cannot defeat deduplication; other report notifications with no explicit `dedup_key` deduplicate on a content hash.
- A call with no explicit `cooldown_key` shares the default cooldown slot for its route and severity, so ordinary report / info notifications share one slot.
- Concurrent sends with the same key inside one process first take a short-lived in-flight slot, which prevents a burst of duplicates; when every static channel fails, the slot is released and no formal dedup or cooldown state is written.
- Noise-suppression evaluation fails open: an exception is logged and the static channels are still sent.
- With `NOTIFICATION_TIMEZONE` empty, the runtime local time zone resolved by `datetime.now().astimezone()` is used; in Actions and Docker, configuring `NOTIFICATION_TIMEZONE` explicitly avoids time-zone ambiguity.

## The WebPush / Apprise evaluation

P6-D is a design evaluation only and adds no dependency, `.env` option, or runtime notification path. The conclusion is that neither belongs in a channel-implementation PR this round.

If WebPush is implemented later, the subscription lifecycle and security boundary need a separate design first:

- It needs a service worker registered by the web frontend. A service worker and `PushManager.subscribe()` depend on a secure context, so production normally requires HTTPS, while local development can use localhost.
- It needs a VAPID key pair: the public key has to be delivered at subscription time, and the server has to hold the private key and protect the key-rotation policy.
- It needs a browser permission interaction: a subscription must be triggered by a user gesture and cannot be enabled silently in the background.
- A `PushSubscription` contains an endpoint and encryption keys. The endpoint is a capability URL and should be treated as a secret and redacted when displayed.
- It needs persisted subscriptions plus handling for expired subscriptions and device unbinding; the current `.env` / single-process configuration model is a poor fit for storing many user or device subscriptions.
- The APIs to submit, delete, and update a subscription need authentication and CSRF protection, not just a hidden frontend entrypoint.

If Apprise is introduced later, it should be evaluated as an optional dependency rather than a default one:

- Apprise is a general-purpose notification library with wide coverage, but it overlaps the first-class Telegram, Discord, Slack, ntfy, Gotify, and Pushover channels already present.
- The dependency size, install-failure paths, Docker image growth, GitHub Actions dependency caching, and an optional-extras strategy all need evaluating.
- Secret passing must not expose a complete Apprise URL; redaction, masking of the web test target, and error-log filtering all need to be unified.
- A send failure must stay isolated within the Apprise channel and must not affect the existing channels' failure-isolation semantics.
- If Apprise is adopted, add a separate experimental channel or a CLI-only spike first, then decide whether it belongs on the web settings page and in the Actions env.

## Local configuration

A local run prefers the `.env` in the project root. Copy `.env.example` and fill in at least one minimal key to enable the matching static notification channel; an advanced key only changes authentication, security, formatting, routing, or noise-suppression behavior and never enables a channel on its own.

```bash
python main.py --check-notify
```

`--check-notify` is a read-only diagnostic: it sends no notification, writes no `.env`, and does not enter the analysis flow. Once the WebUI is configured, the single-channel test on the system settings page can send a real test message; that test uses the page draft as a temporary configuration only and does not save `.env`.

## Docker

In Docker, notification environment variables can be injected through `--env-file .env` or the Compose `env_file`. Do not bind-mount the host's `.env` as a single file over the container's `/app/.env`: Docker mount-point restrictions can then break the atomic replace or the permissions when the web settings page saves configuration. When the active `.env` is missing some keys, the current web settings page falls back to showing the identically named environment variables injected at startup. To keep notification configuration saved through the WebUI across a container rebuild, point `ENV_FILE` at a writable volume file such as `/app/data/runtime.env`, and update or remove the identically named stale value in the startup environment so a restart cannot override it.

For quiet hours, configuring `NOTIFICATION_TIMEZONE` explicitly avoids a container default time zone that differs from expectations. A self-signed internal webhook can use `WEBHOOK_VERIFY_SSL=false` temporarily, but never disable certificate verification on a public-internet path.

## GitHub Actions

The default `00-daily-analysis.yml` reads only the secrets and variables mapped explicitly in the table. After adding a repository secret or variable, it reaches the run process only if its name already appears in the workflow's `env:` block; arbitrarily numbered variables such as `STOCK_GROUP_N` and `EMAIL_GROUP_N` are not imported automatically.

Secrets suit sensitive entries such as tokens, passwords, and webhook URLs; variables suit non-sensitive behavior configuration such as `EMAIL_SENDER_NAME`, routing, noise-suppression windows, and the time zone. `MARKDOWN_TO_IMAGE_CHANNELS` and `MERGE_EMAIL_NOTIFICATION` are unmapped by default; to use them in your own fork, modify the workflow explicitly and add the matching tests.

## Desktop

The desktop app reuses the web settings page's notification configuration and single-channel test entrypoint. A notification test sends a real test message but uses only the current page draft and saves nothing automatically; saving the configuration still requires clicking save.

The desktop app can restore `.env` through configuration export and import. To roll back one notification channel, clear that channel's minimal key and save; a leftover advanced key does not enable the channel on its own, but clearing it too reduces noise during later troubleshooting.

## Rollback

- Local / Docker: restore the old `.env`, or delete the channel's minimal key and restart the process.
- GitHub Actions: clear or delete the corresponding secret / variable; an unmapped key never reaches the workflow run process.
- Desktop: import the old `.env` from a configuration backup, or clear the channel's configuration on the settings page and save.
- Version rollback: the `NTFY_*`, `GOTIFY_*`, routing, and noise-suppression keys added in P6/P7 are ignored by older versions; to avoid confusion, remove them from `.env` or the Actions configuration at the same time.
