# LLM Provider Configuration Guide

This page is written for first-time configuration. It explains how to choose an LLM configuration mode, how the web settings page's AI model configuration presets map to `.env` and GitHub Actions, and how to handle common detection errors.

> This page introduces no new external provider, model name, or Base URL compatibility behavior. It only collects configuration references and official sources; actual compatibility is still determined by the repository's current runtime dependencies and test results.

> - Runtime baseline: `requirements.txt` currently pins `litellm>=1.80.10,!=1.82.7,!=1.82.8,<1.99.0`, and compatibility semantics follow the implementation under that constraint.
> - Verification loop: the system-configuration path regression lives in `tests/test_system_config_service.py` and `tests/test_system_config_api.py`; the `Web` settings-page interaction regression is covered by the existing component tests.
> - Rollback path: old variables are kept with no automatic migration. Roll back through a Web/desktop export backup followed by `POST /api/v1/system/config/import`, or restore the historical `LLM_*` / `LITELLM_*` / `AGENT_*` / `VISION_MODEL` configuration by hand.

The models, quotas, regional restrictions, and prices that are actually available are whatever each provider's console says. If the model list cannot be fetched, type the model name into the web UI by hand. The provider capability tags, official source links, and configuration notes shown on the web settings page come from a static provider template. They are a configuration reference only and do not mean the runtime capability has been verified.

## Choose a configuration mode first

| Mode | Who it suits | Main variables | Notes |
| --- | --- | --- | --- |
| Minimal legacy | Users who just want one model working quickly | `LITELLM_MODEL` plus the matching provider key | The fewest variables, good for getting started locally; not suited to complex fallbacks. |
| Channels | Users who need several providers, several keys, or fallbacks | `LLM_CHANNELS` plus `LLM_<CHANNEL>_*` | The recommended default path; this is also the layer the web settings page writes. |
| YAML | Users familiar with LiteLLM routing, load balancing, and enterprise gateways | `LITELLM_CONFIG` / `LITELLM_CONFIG_YAML` | The highest priority; once it takes effect, Channels and legacy no longer take part in that request. |

The precedence is unchanged: `LITELLM_CONFIG` / `LITELLM_CONFIG_YAML` > `LLM_CHANNELS` > legacy provider keys. P4 only adds documentation; it does not migrate, clear, or silently rewrite an existing configuration.

The generation backend configuration is an outer runtime selection contract. Phase 4 supports `GENERATION_BACKEND=litellm|codex_cli|claude_code_cli|opencode_cli`, but a local CLI backend is not a LiteLLM provider: do not configure `LITELLM_MODEL=codex_cli/...`, `LITELLM_MODEL=claude_code_cli/...`, or `LITELLM_MODEL=opencode_cli/...`. The `codex_cli` preset uses `codex --ask-for-approval never exec --sandbox read-only --output-last-message <temp-file> -`, which fixes an unattended approval policy and keeps a read-only boundary. The `claude_code_cli` preset uses `claude --safe-mode --tools "" --disallowedTools "mcp__*" --strict-mcp-config --no-session-persistence --output-format json -p <static instruction>`, passes the full DSA prompt over stdin, and extracts the final text only from the `result/success` field of the JSON envelope; the arguments follow the [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference). The `opencode_cli` preset uses `opencode --pure run --format json [--model <OPENCODE_CLI_MODEL>] <static instruction> --file <temp prompt file>`, appends `--model` only when `OPENCODE_CLI_MODEL` is configured explicitly, passes the full DSA prompt through a permission-controlled temporary file, and extracts the final text only from JSON event text output that carries no tool events; the arguments follow the [OpenCode CLI reference](https://opencode.ai/docs/cli), and the configuration merge semantics follow the [OpenCode config reference](https://opencode.ai/docs/config). Diagnostic stdout/stderr is subject to the `GENERATION_BACKEND_MAX_OUTPUT_BYTES` total cap together with the final response, and exceeding it returns a structured `output_too_large`. An empty `GENERATION_FALLBACK_BACKEND=` disables backend-level fallback in a local `.env`; when the variable is unset the default falls back to `litellm`. The default GitHub Actions workflow uses `litellm` explicitly when the variable is not configured, so to disable fallback set it to the primary backend and let it become a self no-op. Agent tool calling still uses LiteLLM: the web settings page exposes only `AGENT_GENERATION_BACKEND=auto|litellm`, and hand-writing `codex_cli|claude_code_cli|opencode_cli` does not enable a text-only Agent mode — it returns an explicit unsupported tool-calling diagnostic.

The generation-backend status endpoint and the web panel present the lightweight check and the smoke test separately. The quick check only reads the saved `.env`, the runtime fallback values, and the current draft: it writes no configuration, reloads no runtime, and issues no real model request. Only the JSON smoke test issues a real request, using a fixed JSON prompt and schema. `health_status` and `last_error_code/message` are the result of the current computation, not the last historical error. `supports_tools=false` on a local CLI preset means only that the DSA Agent tool-calling path is unsupported; ordinary text generation may still work.

The Phase 6a Tool Surface is AgentBackend's single internal tool surface: a unified DSA tool schema, public descriptor, MCP-compatible descriptor, scope guard, structured errors, audit summary, and redacted diagnostics. A stock-scoped tool call must pass `ToolAccessContext.stock_scope` explicitly; a tool that takes a `stock_code` parameter without declaring a stock scope fails closed. The Phase 6 Codex App Server adapter executes tools only through that Tool Surface: it does not treat the `codex_cli` generation backend, an MCP server, an SDK, or a final-text fallback as Agent tool success.

## Codex App Server ask-stock boundary

`AGENT_BACKEND=codex_app_server` is an experimental way to run the existing ask-stock chat. It is not a new provider model channel and it does not change `GENERATION_BACKEND`. After selecting it in the web UI under Settings -> Agent settings -> Ask-stock method, you must use `AGENT_ARCH=single` and an overall time limit greater than 0. The settings page only checks whether the configuration, the Codex command, and the required App Server protocol permit an attempt; after saving, the user can ask a question directly, and the first question is the first real execution. `auto` (recommended) and `litellm` always keep the original LiteLLM ask-stock path.

- DSA uses [Codex App Server v2](https://developers.openai.com/codex/app-server/) JSONL stdio, ephemeral threads, and experimental dynamic tools, and handles chat cancellation through `turn/interrupt`. The version accepted on 2026-07-15 was `codex-cli 0.144.3`; no minimum version is hard-coded from that.
- Codex must be installed and signed in on the machine running the DSA backend. DSA neither reads nor stores Codex credentials. PATH and sign-in state are independent across Docker, a remote server, and the desktop app.
- The Phase 6 Codex App Server Agent currently supports macOS, Linux, and a DSA backend running entirely inside WSL; native Windows is not yet supported. This does not affect Windows support for the Phase 2 `codex_cli` GenerationBackend.
- Codex currently gets read-only access to saved analysis context, the global backtest summary, and strategy backtest summaries only. This round verifies the separate-process, stop, timeout, and reclaim loop for those three tools only. Real-time quotes, news, market hotspots, technical-indicator recomputation, per-stock backtest detail, and portfolio tools are not covered this round and are therefore not exposed to Codex; choose the default model when you need them. A stock scope is established only for the historical analysis-context tool that is already open, and only from an explicit stock code or a unique web match — ambiguity such as an identical name across markets is never guessed.
- LLM compression of ask-stock history applies to the default model only. Codex always uses the most recent 20 user-visible messages and never calls `AGENT_LITELLM_MODEL` to produce a summary; a user's saved compression configuration is kept and applies again after switching back to the default model.
- Only single-agent chat is supported at present; Codex Multi Agent and Codex Deep Research are not. The existing LiteLLM Multi Agent and Deep Research are unaffected.
- The cheap status check issues no model request. It checks only the App Server schema capabilities the production path depends on, and binds to no arbitrary minimum version. `scripts/codex_app_server_gate_a.py` in the repository is a maintainer feasibility check, not a settings-page button or a production API; for an ordinary user the first real question is the first real execution.
- When the user stops a Codex ask-stock run, the web UI first shows a stopping state. The backend interrupts the Codex turn and terminates and reaps the tool processes started independently for that turn. Only once both Codex and the tool processes have exited does the original SSE request return its final stopped state. Timeouts and client disconnects follow the same cleanup boundary, so a task still running in the background is never reported as finished. The default LiteLLM Agent behavior is unchanged.
- The basic status only says "this machine can attempt it". It checks neither sign-in, nor the model, nor a real tool loop, and it caches no evidence of success. A real chat has the server choose the actual backend: a single `accepted` event is emitted once context preparation and user-message persistence are complete, and only then is the model started. Before `accepted` the web client keeps the input, stock scope, follow-up context, and skill selection, and uses `accepted.backend` to decide how to stop. Codex's cumulative output, events, and tool calls are all bounded by the whole-turn budget, and the tool-call count follows `AGENT_MAX_STEPS`.
- Codex is not an offline model: stock codes, news, portfolio context, and redacted tool results may be processed by the services Codex itself is configured with.

The versions smoke-tested for this PR are `claude 2.1.177 (Claude Code)` and `opencode 1.17.11`; no broader minimum version is claimed. If the CLI a user has installed does not support these fixed preset arguments or the non-interactive output contract, DSA returns a structured `capability_unsupported`, `cli_contract_unsupported`, `invalid_json`, `schema_validation_failed`, or the matching backend error, and falls back to `litellm` when a backend fallback is configured.

A local CLI backend is not the same as an offline model. Docker, cloud servers, and CI do not automatically carry a local CLI sign-in. On macOS, launching the desktop app from Finder or the Dock does not inherit the shell PATH; the packaged desktop app adds the common Homebrew paths when it starts the backend, and if the settings check still reports that the CLI executable cannot be found, quit DSA completely and reopen it. DSA does not read Codex/Claude/OpenCode credential files, and it neither generates nor relays a provider API key for OpenCode. A subprocess may use the machine's sign-in state or configuration through the CLI's own mechanisms, so stock codes, news, portfolio context, analysis prompts, and report drafts may be processed by the service behind that CLI. DSA inherits a minimal runtime environment by default and refuses wildcard inheritance of `CLAUDE_*`, `ANTHROPIC_*`, `OPENCODE_*`, provider API key/token/base-url/model environment variables, and webhook tokens, which reduces the risk of leaking parent-process configuration; `CODEX_HOME` is kept as an exact-name exception for compatibility with the existing Codex CLI sign-in directory.

`opencode_cli` is an experimental, limited generation backend. It does not support OpenCode serve / web / ACP / MCP / attach or `--dangerously-skip-permissions`. DSA uses the local OpenCode default model by default; `OPENCODE_CLI_MODEL` is an optional model override that is passed to OpenCode as `--model` only when configured. DSA writes a minimal project `opencode.json` into a temporary cwd, but OpenCode's resolved config may still include the user's machine-wide global configuration. The runtime security boundary depends jointly on `--pure`, the environment denylist, the prompt-file permissions, and the fail-closed event extractor.

## The web settings page path

Configuring Channels through the web settings page is the recommended route:

1. Open AI model configuration on the settings page.
2. Pick a provider preset under quick channel setup.
3. Enter the API key and, if needed, fetch the model list.
4. Choose the primary model, the Agent primary model, the fallback models, and the vision model, then save.
5. Run the connection test to confirm that authentication, the model name, the quota, and the response format are all working.
6. To confirm JSON / tools / stream / vision capability, tick runtime capability detection explicitly and then trigger it. That detection issues real LLM requests, its result is a single best-effort probe of the current account, model, and endpoint only, it is not written back to `.env`, and it does not block saving.

## Channel examples

### The official DeepSeek channel

```env
LLM_CHANNELS=deepseek
LLM_DEEPSEEK_PROTOCOL=deepseek
LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_DEEPSEEK_API_KEY=sk-xxx
LLM_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro
LITELLM_MODEL=deepseek/deepseek-v4-flash
```

### An OpenAI-compatible aggregator or custom gateway

```env
LLM_CHANNELS=my_proxy
LLM_MY_PROXY_PROTOCOL=openai
LLM_MY_PROXY_API_SURFACE=chat_completions
LLM_MY_PROXY_BASE_URL=https://your-proxy.example.com/v1
LLM_MY_PROXY_API_KEY=sk-xxx
LLM_MY_PROXY_MODELS=gpt-5.5,claude-sonnet-4-6
```

An OpenAI-compatible Base URL goes only as far as the provider's compatibility entrypoint; do not append `/chat/completions` yourself. A local `.env`, Docker, and self-hosted scripts can use a custom channel directly; GitHub Actions requires the workflow to pass the identically named `LLM_MY_PROXY_*` variables through explicitly.
The Xiaomi MiMo example works the same way: it applies to a local `.env`, Docker, or a self-hosted script. To use `LLM_CHANNELS=mimo` in GitHub Actions, add the `LLM_MIMO_*` mapping to the workflow by hand first.

### Anspire Responses API (the GPT-5.6 names are observed samples)

Anspire's official onboarding page documents the `https://open-gateway.anspire.cn/v6/responses` call shape: <https://open.anspire.cn/model?link=sample&tab=models>. If the live `/models` response, the provider documentation, and a connection test all confirm that the target model uses Responses, put those models in one channel and set the API surface to `responses` explicitly. The `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` names below are samples observed on the current gateway, not a commitment to a long-term model list:

```env
LLM_CHANNELS=anspire
LLM_ANSPIRE_PROTOCOL=openai
LLM_ANSPIRE_API_SURFACE=responses
LLM_ANSPIRE_BASE_URL=https://open-gateway.anspire.cn/v6
LLM_ANSPIRE_API_KEY=sk-xxx
LLM_ANSPIRE_MODELS=gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna
LITELLM_MODEL=openai/gpt-5.6-sol
LITELLM_FALLBACK_MODELS=openai/gpt-5.6-terra,openai/gpt-5.6-luna
```

This capability does not depend on the `gpt-5.6-*` naming: any model a provider declares Responses-only can use the same configuration shape. Model lists and account permissions change, so treat the provider's `/models` response, its official documentation, and a real connection test as the authority. One channel can use only one API surface. To use Anspire's Chat Completions models at the same time, create a second OpenAI-compatible channel for them rather than mixing both kinds in one channel. The web settings page's connection test uses the currently selected surface, and the runtime never silently switches to the other endpoint after a failure.

## Common provider presets

| Provider | Channel name | Protocol | Base URL | Example models |
| --- | --- | --- | --- | --- |
| AIHubmix | `aihubmix` | `openai` | `https://aihubmix.com/v1` | `gpt-5.5,claude-sonnet-4-6,gemini-3.1-pro-preview` |
| Anspire Open | `anspire` | `openai` | `https://open-gateway.anspire.cn/v6` (example) | `Doubao-Seed-2.0-lite,Doubao-Seed-2.0-pro,qwen3.5-flash,MiniMax-M2.7` (examples) |
| OpenAI | `openai` | `openai` | `https://api.openai.com/v1` | `gpt-5.5,gpt-5.4-mini` |
| DeepSeek | `deepseek` | `deepseek` | `https://api.deepseek.com` | `deepseek-v4-flash,deepseek-v4-pro` |
| Gemini | `gemini` | `gemini` | leave empty | `gemini-3.1-pro-preview,gemini-3-flash-preview` |
| Anthropic Claude | `anthropic` | `anthropic` | leave empty | `claude-sonnet-4-6,claude-opus-4-7` |
| Kimi / Moonshot | `moonshot` | `openai` | `https://api.moonshot.cn/v1` | `kimi-k2.6,kimi-k2.5` |
| Qwen / DashScope | `dashscope` | `openai` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3.6-plus,qwen3.6-flash` |
| Zhipu GLM | `zhipu` | `openai` | `https://open.bigmodel.cn/api/paas/v4` | `glm-5.1,glm-4.7-flash` |
| MiniMax | `minimax` | `openai` | `https://api.minimax.io/v1` | `MiniMax-M3,MiniMax-M2.7,MiniMax-M2.7-highspeed` |
| Xiaomi MiMo | `mimo` | `openai` | from the official console (not mapped in Actions by default) | see the official documentation / console |
| Volcengine Ark / Doubao | `volcengine` | `openai` | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-seed-1-6-251015,doubao-seed-1-6-thinking-251015` |
| SiliconFlow | `siliconflow` | `openai` | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3.2,Qwen/Qwen3-235B-A22B-Thinking-2507` |
| OpenRouter | `openrouter` | `openai` | `https://openrouter.ai/api/v1` | `~anthropic/claude-sonnet-latest,~openai/gpt-latest` |
| Ollama | `ollama` | `ollama` | `http://127.0.0.1:11434` | `llama3.2,qwen2.5` |

## Official sources and compatibility

| Provider | Official source | Compatibility notes |
| --- | --- | --- |
| Anspire Open | [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC) | `ANSPIRE_API_KEYS` can serve both the LLM gateway and search when no higher-priority OpenAI-compatible source is configured. The page and `.env` defaults use `openai/Doubao-Seed-2.0-lite` plus `https://open-gateway.anspire.cn/v6`; whether that works depends on the console and model permissions. |
| OpenAI | [Model list](https://platform.openai.com/docs/models) | The official model page suggests starting from `gpt-5.5`, and using `gpt-5.4-mini` or `gpt-5.4-nano` for low-latency or low-cost cases. |
| DeepSeek | [Quick start](https://api-docs.deepseek.com/) | The official OpenAI Base URL is `https://api.deepseek.com`. `deepseek-chat` and `deepseek-reasoner` are deprecated as of 2026-07-24, so the current template uses `deepseek-v4-flash` / `deepseek-v4-pro` directly. |
| Gemini | [Model list](https://ai.google.dev/gemini-api/docs/models) | Gemini 3.1 Pro and Gemini 3 Flash are still preview; for production stability, switch back to the stable 2.5 models in the console. |
| Anthropic Claude | [Model overview](https://docs.anthropic.com/en/docs/about-claude/models/all-models) | Claude's current API IDs include `claude-sonnet-4-6` and `claude-opus-4-7`; Sonnet is the better default for price/performance. |
| Kimi / Moonshot | [Kimi K2.6 quick start](https://platform.kimi.com/docs/guide/kimi-k2-6-quickstart), [model list](https://platform.kimi.com/docs/models) | `kimi-k2.6` is the official recommendation. The `kimi-k2` series is retired on 2026-05-25, and the older `moonshot-v1-*` models remain only as a stable choice for existing workloads. |
| Qwen / DashScope | [Text generation](https://help.aliyun.com/zh/model-studio/text-generation-model/) | Model Studio recommends `qwen3.6-plus`; once the results look right, `qwen3.6-flash` lowers the cost. |
| Zhipu GLM | [Model overview](https://docs.bigmodel.cn/cn/guide/start/model-overview), [GLM-5.1](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.1) | `glm-5.1` is the current flagship; `glm-4.7-flash` is the lightweight / free example. |
| MiniMax | [OpenAI API compatibility](https://platform.minimax.io/docs/api-reference/text-chat), [list models](https://platform.minimax.io/docs/api-reference/models/openai/list-models), [pricing](https://platform.minimax.io/docs/guides/pricing-paygo) | The official OpenAI-compatible Base URL is `https://api.minimax.io/v1`, listing `MiniMax-M3` (the default, with image input, officially supporting up to 1M input context, priced in two tiers for `<=512K` and `>512K` input), `MiniMax-M2.7`, `MiniMax-M2.7-highspeed`, plus the legacy `MiniMax-M2.5`. This repository's fallback cost estimate conservatively registers M3 at the `<=512K` tier and keeps M2.5 legacy pricing for compatibility with existing user configurations. Coding-tool scenarios in mainland China may use the `.com` or Anthropic-specific entrypoint; check the console. |
| Xiaomi MiMo | official documentation / console | Currently integrated as OpenAI-compatible. The Base URL, model names, and permissions follow MiMo's official documentation and console. The `mimo` channel is not mapped explicitly in the repository's default workflow, so for Actions add a custom mapping as described under "GitHub Actions configuration" below. |
| Volcengine Ark / Doubao | [online inference (standard)](https://www.volcengine.com/docs/82379/2121998), [model list](https://www.volcengine.com/docs/82379/1949118) | The official example uses `https://ark.cn-beijing.volces.com/api/v3` with `doubao-seed-1-6-251015`. On a Coding Plan, use its dedicated Base URL and model names instead of this table's online-inference template. |
| SiliconFlow | [model list](https://docs.siliconflow.cn/quickstart/models), [list-models API](https://docs.siliconflow.cn/cn/api-reference/models/get-model-list) | Platform models change constantly and `/models` requires an API key. The template gives only common new models as examples, so fetch the model list from the web settings page before saving to confirm what the account can see. |
| OpenRouter | [Models API](https://openrouter.ai/docs/api/api-reference/models/get-models) | OpenRouter supports latest-router aliases such as `~anthropic/claude-sonnet-latest` and `~openai/gpt-latest`. A manual live smoke test on 2026-05-03 passed with Claude Sonnet latest as the default example, and GPT latest is kept as an alternative to switch to depending on account permissions. |
| LiteLLM | [OpenAI-Compatible Endpoints](https://docs.litellm.ai/docs/providers/openai_compatible) | An OpenAI-compatible endpoint requires the runtime model to be written as `openai/<model>`, and the Base URL goes only as far as the provider's compatibility entrypoint, with no `/chat/completions` appended. |

The presets on this page guarantee only that the configuration shape matches the OpenAI-compatible routing rules of the current dependency. Real connectivity still depends on the provider account's permissions, region, quota, and model enablement. The current LiteLLM version constraint is `litellm>=1.80.10,!=1.82.7,!=1.82.8,<1.99.0` (see `requirements.txt`), which keeps the historical minimum version, excludes the broken PyPI releases explicitly, and caps the upper bound at the verified `<1.99.0` so that a future major version cannot enter automatically.

## OpenAI-compatible and LiteLLM rules

- An OpenAI-compatible provider's channel `protocol` is usually `openai`.
- `LLM_<CHANNEL>_API_SURFACE` defaults to `chat_completions`; set it to `responses` explicitly for a Responses-only model. A Responses channel requires the protocol and every model's actual LiteLLM provider to be `openai`. Direct providers are read from the installed LiteLLM registry and returned by the system configuration API to the web editor as a shared source of truth, so an explicit `anthropic/`, `gemini/`, or `xai/` prefix — and any future conflicting prefix — is recognized consistently at every configuration entrypoint, while a gateway's own slash-bearing model IDs such as `deepseek-ai/...` and `Qwen/...` are normalized to `openai/<model>`. One normalized public alias must not mix Chat and Responses across channels, which would let the Router load-balance between deployments on different surfaces. At runtime the public model alias `openai/<model>` is preserved, and `/responses` is called through LiteLLM's `openai/responses/<model>` bridge.
- This design matches how mainstream projects route explicitly: [LiteLLM](https://github.com/BerriAI/litellm/blob/main/litellm/responses/main.py) provides a Chat-to-Responses bridge, the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/models/) uses separate Responses and Chat model classes, and [LangChain](https://docs.langchain.com/oss/python/integrations/chat/openai) uses `use_responses_api` for an explicit choice and only auto-routes under known conditions. DSA does not guess an endpoint after a request fails, which avoids double requests, double billing, and masking the real server-side error.
- The runtime model name is usually written `openai/<model>`; for example, `gpt-5.5` behind a custom gateway can be routed by LiteLLM as `openai/gpt-5.5`.
- Prefixes such as `Qwen/...` and `deepseek-ai/...` are provider or model-repository organization names, not LiteLLM provider prefixes; do not mistake them for `provider/model` routing just because they contain a slash.
- The Base URL is only the compatibility entrypoint the provider or gateway gives you, usually ending at `/v1`, `/api/v3`, or the path the vendor's documentation specifies; do not append `/chat/completions` by hand.
- In YAML mode, configure it with LiteLLM's native `model_list` / `litellm_params` semantics; while valid, YAML takes precedence over Channels.

## GitHub Actions configuration

The bundled `.github/workflows/00-daily-analysis.yml` passes through only the environment variables the workflow lists explicitly. In channel mode, set `LLM_CHANNELS` in repository variables or secrets first, then add the matching `LLM_<CHANNEL>_*` entries for each channel name.

| Field | Suggested location | Notes |
| --- | --- | --- |
| `LLM_CHANNELS` | Variables or Secrets | Comma-separated channel names, for example `deepseek,minimax,volcengine`. |
| `LLM_<CHANNEL>_PROTOCOL` | Variables or Secrets | Not sensitive; usually `openai`, `deepseek`, `gemini`, `anthropic`, or `ollama`. |
| `LLM_<CHANNEL>_API_SURFACE` | Variables or Secrets | Optional; `chat_completions` (the default) or `responses`. Responses currently supports the `openai` protocol only. |
| `LLM_<CHANNEL>_BASE_URL` | Variables or Secrets | Prefer Variables when it is not sensitive; a private gateway address can go in Secrets. |
| `LLM_<CHANNEL>_MODELS` | Variables or Secrets | A non-sensitive, comma-separated model list. |
| `LLM_<CHANNEL>_ENABLED` | Variables or Secrets | Optional; enabled by default when unset, and `false` skips that channel. |
| `LLM_<CHANNEL>_API_KEY` / `LLM_<CHANNEL>_API_KEYS` | Secrets | Key fields must go in repository secrets; an identically named variable is not read by the workflow. |
| `LLM_<CHANNEL>_EXTRA_HEADERS` | Secrets or Variables | A JSON string; put it in Secrets whenever it carries authentication, tenant, organization, or private gateway information. |
| `LITELLM_CONFIG` | Variables or Secrets | The YAML file path; when used together with `LITELLM_CONFIG_YAML`, the workflow writes to that path. |
| `LITELLM_CONFIG_YAML` | Secrets preferred | The YAML content itself may contain a private gateway or headers, so Secrets is recommended. |
| `LLM_USAGE_HMAC_SECRET` | Secrets | Optional; configure the same high-entropy random secret, for example `openssl rand -hex 32`, only when usage-message HMACs must be compared across deployments. Do not put it in Variables or commit it to version control. |
| `LLM_USAGE_HMAC_KEY_VERSION` | Variables or Secrets | Optional; update the version label together with any rotation of `LLM_USAGE_HMAC_SECRET` so that HMACs generated by different secrets are not compared by mistake. |

The default workflow already maps `primary`, `secondary`, `aihubmix`, `anspire`, `deepseek`, `dashscope`, `zhipu`, `moonshot`, `minimax`, `volcengine`, `siliconflow`, `openrouter`, `gemini`, `anthropic`, `openai`, `ollama`, and `hermes` explicitly; `mimo` is not mapped. To use `mimo` (or any channel name not listed), configure the identically named `LLM_<CHANNEL>_*` entries in Variables/Secrets and add the matching env mapping to the workflow as well. A local `.env`, Docker, and self-hosted scripts are not subject to this restriction.

To roll back the explicit HMAC telemetry configuration, remove `LLM_USAGE_HMAC_SECRET` and restore or delete `LLM_USAGE_HMAC_KEY_VERSION`; once empty, the system returns to its default behavior of generating `.llm_usage_hmac_secret` locally.

Ollama's default Base URL `http://127.0.0.1:11434` targets local machines, Docker, or a self-hosted runner that can reach the service. A GitHub-hosted runner usually has no local Ollama service, so configuring `LLM_CHANNELS=ollama` there will most likely fail to connect.

### Hermes local HTTP generation (Phase 3)

Hermes is a reserved local HTTP generation preset, enabled only through `LLM_CHANNELS=hermes`. The default protocol is `openai`, the default address is `http://127.0.0.1:8642/v1`, and the default model is `hermes-agent`:

```env
LLM_CHANNELS=hermes
LLM_HERMES_PROTOCOL=openai
LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1
LLM_HERMES_API_KEY=sk-local-hermes
LLM_HERMES_MODELS=hermes-agent
LITELLM_MODEL=openai/hermes-agent
```

Phase 3 supports ordinary analysis and JSON generation only — not stream/SSE, tools, vision, Agent tools, remote Hermes, or process lifecycle management. `LLM_HERMES_API_KEY` should come from a local `.env`, the runtime configuration, or GitHub Secrets; do not commit it to the repository. Hermes allows only a loopback `/v1` endpoint, `localhost` is normalized to `127.0.0.1`, and `LLM_HERMES_API_KEYS` and `LLM_HERMES_EXTRA_HEADERS` are unsupported. Saving a reserved Hermes channel from the web settings page clears those two legacy fields and shows a warning; to restore the old values use an `.env` backup, Git history, or a desktop export backup — but a non-empty multi-key or extra-headers value is still rejected by the backend.

In GitHub Actions, `127.0.0.1` on a GitHub-hosted runner is the runner itself, not the user's computer. Only a self-hosted runner or a service on the same machine can reach a local Hermes; otherwise the connection fails.

## Common errors and suggested handling

| `details.reason` / symptom | Common cause | Suggested handling |
| --- | --- | --- |
| `missing_api_key` | The API key is empty, or `API_KEYS` has no non-empty segment after splitting on commas. | Provide at least one valid key; local Ollama and localhost-compatible services are exempt. |
| `api_key_rejected` | The provider returned 401 / 403: the key is invalid, permissions are insufficient, or the project is not enabled. | Copy the key again and check the account project, organization, region, and model permissions. |
| `insufficient_balance` | Insufficient balance, billing not enabled, or the plan quota is used up. | Check the balance, billing status, and model plan in the provider console. |
| `quota_exceeded` | The account or organization quota is exhausted. | Check the plan, project quota, organization quota, and the provider's billing page. |
| `rate_limit` | An RPM / TPM / concurrency limit was hit. | Lower concurrency, switch to a lighter model, or raise the limit in the console. |
| `timeout` | The request timed out — a slow network, a slow provider, or an unresponsive local service. | Check the proxy, firewall, Base URL, model cold start, and timeout settings. |
| `dns_error` | The domain cannot be resolved. | Check the Base URL spelling, DNS, proxy, and the runtime environment's network. |
| `tls_error` | A TLS certificate, proxy, or man-in-the-middle certificate problem. | Check the HTTPS certificate chain, corporate proxy, self-signed certificates, and the system clock. |
| `connection_refused` | Nothing is listening on the target port, or the local service is not running. | Check the Base URL, port, and firewall; for Ollama, confirm the machine or runner can reach the service. |
| `endpoint_not_found` | The `/models` or chat endpoint path does not exist. | Confirm the Base URL stops at the compatibility entrypoint, with no extra or missing vendor-required path segments. |
| `invalid_url` | base_url contains an unsupported form (whitespace/control characters, a backslash, `userinfo@host`, and so on) or parses with unsafe semantics. | Clean up `LLM_<CHANNEL>_BASE_URL` (emptying or deleting the variable first is recommended) and keep the provider's default entrypoint; to pin a gateway, start from the official compatibility example. |
| `model_access_denied` | A best-effort model-availability classification based on observed provider wording: the model may be disabled, not enabled, invisible to the account, or inaccessible to the current key. | Check which model was tested in the test result, and confirm in the provider console that it is enabled. If needed, reorder the models, remove the unavailable one, or fetch the model list to check what the account can see. |
| `provider_blocked` | The provider or relay gateway explicitly blocked the request — account risk control, region, request origin, model permissions, reseller policy, or a content-safety policy. | Check which model was tested in the test result and the provider console logs first; review account/project status, region or origin restrictions, gateway policy, and content-safety rules rather than starting with the Base URL, TLS, or the local network. |
| `provider_prefix_mismatch` | The LiteLLM provider prefix does not match the channel protocol. | An OpenAI-compatible channel usually uses `openai/<model>`; do not mistake `Qwen/...` or `deepseek-ai/...` for a provider prefix. |
| `non_json` | The provider returned something other than JSON, or a proxy returned an HTML / text error page. | Check the Base URL, the gateway path, proxy error pages, and the Chat Completions compatibility entrypoint. |
| `null_response` | LiteLLM returned no parsable response object. | Check whether the provider is Chat Completions compatible, and switch model or endpoint and retry if needed. |
| `null_content` | The chat completion succeeded but `content` was empty. | Switch to a model that supports plain text output, or check whether a tool or vision response is being forced. |
| `malformed_choices` | The response lacks a compatible `choices` structure. | Confirm the endpoint is Chat Completions compatible, not an Embeddings, Responses, or other protocol entrypoint. |
| `capability_unsupported` | The JSON / tools / stream / vision smoke parameters are unsupported by the current model or endpoint. | Switch to a model that supports the capability, or treat the result as one capability probe of the current account, model, and endpoint rather than a global provider limitation. |
| `unknown_error` | The provider or client raised an exception that could not be classified further. | Read the original error in `details.message` or the logs first, then work through the network, authentication, model name, and quota in turn. |

The complete classification logic is whatever the error classifier in `src/services/system_config_service.py` implements.

`model_access_denied` is not an official cross-provider error-code mapping. The reviewable basis for the classification is:

- SiliconFlow's official error-handling documentation asks you to record the HTTP error code and `message` when diagnosing an API error, states that 403 means insufficient balance or insufficient permissions, refers other cases to the error `message`, and suggests trying another model to see whether the problem persists (Chinese: <https://docs.siliconflow.cn/cn/faqs/error-code>; English: <https://docs.siliconflow.cn/en/faqs/error-code>).
- The real redacted sample in issue #1208 came from a SiliconFlow / OpenAI-compatible channel test and returned `litellm.APIError: APIError: OpenAIException - Model disabled.` through LiteLLM.
- Online re-check (2026-05-06T16:21:21Z): under the `litellm>=1.80.10,!=1.82.7,!=1.82.8,<1.99.0` constraint, the local verification environment was Python `3.13.12`, LiteLLM `1.82.3`, Base URL `https://api.siliconflow.cn/v1`, model `Qwen/Qwen3-235B-A22B-Thinking-2507`. Calling SiliconFlow Chat Completions directly returned HTTP `403` with the body `{"code":30003,"message":"Model disabled.","data":null}`; the same model through LiteLLM `completion(model="openai/Qwen/Qwen3-235B-A22B-Thinking-2507")` returned `APIError: OpenAIException - Model disabled.`.

The runtime therefore treats that observed provider `message` as a best-effort model-availability diagnostic rather than declaring it an official cross-provider error code. The implementation enters that diagnostic only when the error text contains both `model` and an explicit permission, disabled, or unavailable signal; provider wording that is not covered, or that means something else, keeps using the existing fallback diagnostic. `provider_blocked` is likewise a best-effort diagnostic based on explicit blocking wording, used to separate a provider or gateway policy block from a local network, TLS, or model-availability problem.

## Runtime capability detection boundary

- The JSON / tools / stream / vision smoke must be triggered explicitly in the web UI.
- Detection issues real LLM requests, which can incur token or image-input cost, RPM/TPM rate limiting, insufficient balance, or a timeout.
- A detection result is one best-effort runtime result for the current account, model, and endpoint.
- Detection results are not written back to `.env` and do not block saving the configuration.
- A failed capability probe does not mean the provider lacks the capability globally; the failure may come from account permissions, a model that is not enabled, the endpoint's region, the balance, the provider's compatibility layer, or LiteLLM's conversion path.
- The current implementation does not run an online smoke test against every real provider. The compatibility basis is `litellm>=1.80.10,!=1.82.7,!=1.82.8,<1.99.0` (see `requirements.txt`), the [LiteLLM Python SDK / OpenAI I/O format](https://docs.litellm.ai/), [LiteLLM OpenAI-compatible routing](https://docs.litellm.ai/docs/providers/openai_compatible), and the OpenAI Chat Completions request shapes for [JSON mode](https://platform.openai.com/docs/guides/structured-outputs?api-mode=chat), [tool calling](https://platform.openai.com/docs/guides/function-calling?api-mode=chat), [streaming](https://platform.openai.com/docs/guides/streaming-responses?api-mode=chat), and [vision input](https://platform.openai.com/docs/guides/images-vision?api-mode=chat).

## Rollback

- Web settings page: delete or disable the channel and select the previous primary model / Agent model / fallbacks again.
- `.env`: restore `LLM_*`, `LITELLM_MODEL`, `AGENT_LITELLM_MODEL`, `VISION_MODEL`, and `LITELLM_FALLBACK_MODELS` from a backup.
- From Channels back to legacy: delete or empty `LLM_CHANNELS`, and keep the legacy provider key and `LITELLM_MODEL`.
- From YAML back to Channels / legacy: remove `LITELLM_CONFIG` / `LITELLM_CONFIG_YAML`, and the lower layer applies again after a restart.
- WebUI / desktop: restore from the configuration backup exported under system settings.
- PR rollback: revert the corresponding docs PR; P4 involves no configuration, data, or code migration.
