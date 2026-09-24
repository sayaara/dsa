# Maintaining the settings-page configuration help

The settings-page configuration help puts the key explanation of each option inside the WebUI, so users do not keep switching between the settings page and the documentation. The page keeps a short description, and the detailed explanation opens from the help icon next to the option's title.

This document only describes the maintenance rules for the help system; it does not replace the full configuration documentation. Configuration semantics, defaults, runtime precedence, and troubleshooting details remain sourced from `.env.example`, `docs/full-guide.md`, and the matching topic documents.

## Data structures

The backend configuration registry in `src/core/config_registry.py` attaches help metadata to a field:

- `help_key`: the stable key for the frontend's localized help text.
- `examples`: configuration samples that can be displayed directly. Sensitive fields may use placeholders only, such as `sk-xxxx` or `your_token`.
- `docs`: links to related documentation, preferring an existing topic document or the full guide in this repository.
- `warning_codes`: stable hint codes for the frontend or for later validation extensions.

The long-form frontend text lives in `apps/dsa-web/src/locales/settingsHelp.ts`:

- Chinese text is shown by default.
- The English text keeps the same structure, which makes a later language switch straightforward.
- The text should explain the purpose, the accepted values, the blast radius, the caveats, and the related documentation. It should not duplicate an entire topic document.

## WebUI language (not a configuration option)

The WebUI interface (static page text, navigation, and common control labels) is English-only. This is decoupled from `REPORT_LANGUAGE` and does not change report-language semantics.

- There is no in-app UI language toggle; a legacy `dsa.uiLanguage` value left in `localStorage` by older builds is ignored.
- The UI language is not an `.env` configuration field and does not appear in the configurable field list of `system/config`.
- The interface sets `document.documentElement.lang` to `en`, which helps accessibility semantics.

## Coverage

PR1 covered the infrastructure and a first representative set of options:

- `STOCK_LIST`
- `LITELLM_MODEL`
- `LLM_CHANNELS`
- `FEISHU_WEBHOOK_URL`
- `WEBUI_HOST`

PR2 continued with the high-frequency options that are easy to get wrong:

- AI model runtime: the Agent primary model, fallback models, advanced YAML routing, temperature, provider API keys, and the OpenAI-compatible base URL.
- Fields inside the LLM Channels editor: channel name, protocol, base URL, API key, model list, runtime capability detection, primary model, Agent primary model, fallback, vision, and temperature.
- Data sources and search: Tushare, the stock-index remote update toggle, real-time quote priority, real-time technical indicators, search API keys, SearXNG, chip distribution, and the news window.
- Notifications: webhooks, Telegram, email, chat platforms such as Discord and Slack, report output, and webhook SSL verification.
- WebUI / auth / schedule / proxy: host, port, login protection, trusted reverse proxy, scheduled jobs, the trading-day check, and the network proxy.

PR3 is the registered-field slice, completing help for the fields actually displayed or configurable in the Web settings page, including the fields currently visible on the general configuration card and the conditionally visible AI legacy fields:

- Agent configuration (22 fields): ask-stock generation mode, Agent mode, maximum reasoning steps, strategy list, strategy directory, natural-language routing, architecture, orchestrator mode, timeout, risk veto, Deep Research budget and timeout, memory, automatic strategy weighting, strategy routing, visible chat context compression for ask-stock, the event-monitoring toggle and interval, and the alert-rule JSON. Ordinary users see only the new `AGENT_BACKEND` selector; the old `AGENT_GENERATION_BACKEND` is kept for configuration compatibility only.
- Backtest configuration (5 fields): the backtest toggle, evaluation window, minimum record age, engine version, and neutral return band.
- Report configuration (9 fields): summary-only push, showing the model name, the template directory, the rendering engine, completeness validation and retry, historical signal comparison, per-stock push, and combined email.
- Notification routing configuration (9 fields): report/alert/system-error channel routing, de-duplication and cooldown, quiet hours and timezone, minimum severity, and the daily digest (reserved).
- System runtime (7 fields): log level, debug mode, maximum concurrency, analysis interval, and the market-analysis toggle, market, and colour scheme.
- AI legacy and Anspire configuration: provider-specific multi-key fields, model name, temperature, vision model, max tokens, and the Anspire LLM gateway fields.
- Data sources and search: TickFlow, SerpAPI, Brave, Bocha, MiniMax, SearXNG public instances, the BIAS threshold, and the Pytdx server fields.
- Advanced notification fields: Feishu advanced security and application fields, Telegram topic, Discord/Slack advanced fields, Pushover, ntfy, Gotify, PushPlus, ServerChan3, AstrBot, and the custom-webhook advanced template and authentication fields.

After Issue #1512 closed, the Web settings page shows only the formal fields in the backend configuration registry. An unregistered `.env` key is no longer displayed as an ordinary editable setting, which keeps raw keys, `Auto-inferred field metadata.`, and options with no help button out of the interface. Those keys can still be kept and maintained through the `.env` file or the import/export capability.

Exception: the dynamic channel detail keys declared by `LLM_CHANNELS` (such as `LLM_DEEPSEEK_API_KEY` and `LLM_MY_PROXY_MODELS`) remain in the configuration endpoint's response, so the AI model integration editor can read and save them. They are not shown as ordinary configuration cards and do not reuse the operational hiding semantics of `WEB_SETTINGS_HIDDEN_FROM_UI`.

Low-frequency and operational `.env` variables not yet surfaced in the Web settings page include `DATABASE_PATH`, `SQLITE_*`, `USE_PROXY`, `PROXY_HOST`, and `PROXY_PORT`. To make one of them editable in the Web later, register it formally in `src/core/config_registry.py` with complete help metadata rather than relying on automatic inference.

### Coverage boundary

- The `settings.llm_channel.*` series in `settingsHelp.ts` describes fields internal to the LLM channel editor. It is used for frontend rendering only and does not correspond to individual `.env` options; this is a deliberate built-in extension from PR2 that improves the editor's usability.
- Every other help entry should map from some field's `help_key` in `src/core/config_registry.py` back to the backend registry metadata, so it can be maintained together with the documentation source and `warning_codes`.

## Source-of-truth precedence

When adding or changing help text, verify against these in order:

1. `.env.example`: configuration key names, defaults, sample formats, and sensitive placeholders.
2. `docs/full-guide.md`: the main configuration explanation, runtime entry points, and deployment context.
3. `docs/LLM_CONFIG_GUIDE.md` and `docs/llm-providers.md`: LLM precedence, channels, provider/model, compatibility boundaries, and troubleshooting.
4. Topic documents: for example `docs/bot/feishu-bot-config.md`, `docs/deploy-webui-cloud.md`, and `docs/desktop-package.md`.
5. The implementation and its tests: when documentation and code disagree, trust the executable implementation first and fix the documentation in the same change.

## Maintenance boundary

- Help text must not change configuration saving, validation, runtime precedence, `.env` write-back, or environment-variable override semantics.
- Never display a real secret, account, token, complete webhook value, or local absolute path.
- If an LLM example names a specific provider prefix, model, or base URL, it must be traceable to current repository documentation or an official source; otherwise use a placeholder or link to the source of truth.
- Settings help must not make its own promises about third-party model/API availability, the LiteLLM compatibility window, or provider fallback rules. Any change there requires updating the topic document and the PR compatibility notes as well.
- The Chinese and English text should cover the same semantic scope. If only one language is updated, state why in the delivery notes.
- Keep the first-screen short description concise and put the detail in the help dialog, which avoids duplicating a hover tooltip and a permanently visible short description.

## Restart semantics

Saving on the settings page normally only writes `.env` and triggers a configuration refresh that can be reloaded at runtime. Help text and `warning_codes` must distinguish these cases explicitly:

- `WEBUI_HOST`, `WEBUI_PORT`: the listen address and port bind only at process start, so after saving you must restart the current process, Docker container, or service manager for the change to take effect.
- `RUN_IMMEDIATELY`: a startup-only single-run setting for non-schedule mode. Saving it does not make an already-running WebUI/API process trigger an analysis.
- The Web settings page does not expose internal keys such as `SCHEDULE_TIME`, `SCHEDULE_TIMES`, or `SCHEDULE_RUN_IMMEDIATELY` directly; users manage the enabled state, multiple execution times, and a one-off run through the scheduled-job card.
- `SCHEDULE_ENABLED`: long-running WebUI/API/Desktop processes (including `python main.py --serve --schedule`) start or stop the runtime scheduler according to the new value after saving. Restarting `--serve-only` or the Desktop process also restores enabled daily jobs, but does not itself run an analysis immediately. Pure CLI schedule mode (`python main.py --schedule`) still runs from the arguments and configuration given at startup.
- `SCHEDULE_TIME`, `SCHEDULE_TIMES`: not restart-dependent. When `SCHEDULE_TIMES` is empty, `SCHEDULE_TIME` is used, and a running scheduler rebuilds its daily jobs at the new times.
- `SCHEDULE_RUN_IMMEDIATELY`: startup behaviour for schedule mode. Saving it does not make the current process run an analysis immediately; use the runtime scheduler's run-now API for a manual run.
- The runtime scheduler's run-now API only accepts a request when no analysis task is running. If one is already running it returns a busy status, and the Web settings page suggests retrying later.
