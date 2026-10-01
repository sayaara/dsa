# Documentation Index

This is the entry point for project documentation. The README covers the project overview and quick start; detailed setup, configuration, deployment, feature usage, and troubleshooting docs are linked below.

## Choose By Goal

| I want to | Start with | Then read |
| --- | --- | --- |
| Understand what the project does | [README](../README.md) | [Full Guide (EN)](full-guide.md) |
| Run the project for the first time | [README](../README.md) | [Full Guide (EN)](full-guide.md) |
| Configure model providers | [LLM Config Guide (EN)](LLM_CONFIG_GUIDE.md) | [Provider Configuration Guide](llm-providers.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> |
| Configure notifications | [Notification Baseline](notifications.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | [Full Guide (EN)](full-guide.md) |
| Deploy to a server or cloud platform | [Deploy Guide (EN)](DEPLOY.md) | [Cloud WebUI Deployment](deploy-webui-cloud.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>, [Zeabur Deployment](docker/zeabur-deployment.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) |
| Use Bot / IM integrations | [Bot Commands (EN)](bot-command.md) | [Bot Platform Docs](bot/) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) |
| Troubleshoot runtime issues | [FAQ (EN)](FAQ.md) | [Changelog](CHANGELOG.md) |
| Troubleshoot data-source failures | [Data-source stability diagrams](data-source-stability.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | [FAQ (EN)](FAQ.md) |
| Contribute code or docs | [Contributing Guide](CONTRIBUTING.md) | [API Spec](architecture/api_spec.json) |

## Getting Started

| Document | Contents |
| --- | --- |
| [README](../README.md) | Project overview, key features, quick start, sample output |
| [Full Guide (EN)](full-guide.md) | Environment setup, run modes, configuration, deployment paths, and common issues |
| [FAQ (EN)](FAQ.md) | Common configuration, model, notification, deployment, and runtime issues |
| [Data-source stability diagrams](data-source-stability.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | Existing-source routing, fallback chains, and recommended configuration profiles |
| [Changelog](CHANGELOG.md) | Release notes, capability changes, and migration notes |

## Configuration

| Document | Contents |
| --- | --- |
| [LLM Config Guide (EN)](LLM_CONFIG_GUIDE.md) | Model providers, three-tier configuration, Web settings, and common model setup |
| [Provider Configuration Guide](llm-providers.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | Provider presets, GitHub Actions mapping, error categories, and diagnostics |
| [LiteLLM YAML Example](examples/litellm_config.example.yaml) | Example LiteLLM multi-provider configuration |
| [Notification Baseline](notifications.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | Telegram, Discord, Slack, Email, and other notification channels |

## Usage Topics

| Document | Contents |
| --- | --- |
| [Bot Commands (EN)](bot-command.md) | Bot commands, webhooks, platform integration, and callback behavior |
| [Bot Platform Docs](bot/) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Discord and related Bot configuration screenshots and notes |
| [Real-Time Alert Center](alerts.md) <sub><sub>![P4 Badge](https://img.shields.io/badge/P4-yellow?style=flat)</sub></sub> | EventMonitor baseline, Web rule management, notification attempts, cooldown state, and phase boundaries |
| [Stock Profile API](stock-profile-api.md) <sub><sub>![P1 Badge](https://img.shields.io/badge/P1-yellow?style=flat)</sub></sub> | Single stock-profile contract, per-block quality status, code normalization, and Web phase boundaries |
| [DecisionSignal Topic](decision-signals.md) <sub><sub>![P7 Badge](https://img.shields.io/badge/P7-orange?style=flat)</sub></sub> | AI signal fields, API, Web display, alert/notification/portfolio-risk linkage, outcome evaluation, redaction, migration, and rollback |
| [ResearchArtifact Contract](research-artifact.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | Structured thesis, evidence, invalidation conditions, deterministic fallback identity, and the boundary before persistence/API integration |
| [Analysis Context Pack Contract, Runtime Consumption, And Visibility](analysis-context-pack.md) <sub><sub>![P6 Badge](https://img.shields.io/badge/P6-orange?style=flat)</sub></sub> | AnalysisContextPack first-scope boundaries, field quality states, P1/P2 internal contracts, P3 prompt-summary consumption, P4 history/API/Web low-sensitivity visibility, P5 data-quality scoring, and P6 migration/rollback notes, plus source anchors; the full guide adds #1386 market-phase analysis, migration, and rollback entry points |
| [Image Extraction Prompt](image-extract-prompt.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | Prompt and boundaries for extracting stock information from images |
| [OpenClaw Skill Integration](openclaw-skill-integration.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | OpenClaw / Skill external integration notes |
| [Grok Bot Integration](grok-bot-integration.md) <sub><sub>![P0 Badge](https://img.shields.io/badge/P0-green?style=flat)</sub></sub> | 2026-08-11 Grok Bot (AI teammate) vs LiteLLM `xai/` provider; HTTP / Skill / DecisionSignal consumption |

## Deployment And Packaging

| Document | Contents |
| --- | --- |
| [Deploy Guide (EN)](DEPLOY.md) | Server deployment, Docker, systemd, Supervisor, and related options |
| [Cloud WebUI Deployment](deploy-webui-cloud.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | Cloud server WebUI access and deployment notes |
| [Zeabur Deployment](docker/zeabur-deployment.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> (Chinese-only) | Zeabur platform deployment |
| [Desktop Packaging](desktop-package.md) <sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub> | Electron desktop app and Web artifact packaging |

## Reference And Development

| Document | Contents |
| --- | --- |
| [API Spec](architecture/api_spec.json) | FastAPI OpenAPI artifact |
| [Contributing Guide](CONTRIBUTING.md) | Issues, pull requests, tests, documentation sync, and collaboration expectations |
| [Agent Trajectory Eval](agent-trajectory-eval.md) | Offline-scored agent tool-call trajectories against golden samples |
| [Prompt-Language Eval](prompt-language-eval.md) | Compare analyzer prompt variants on frozen inputs before changing prompts |

## China-Market Glossary

| Term | Meaning |
| --- | --- |
| **A-shares** | Stocks listed on the Shanghai or Shenzhen stock exchanges, denominated in CNY |
| **Northbound capital flow** | Net buy/sell flow from foreign investors through Stock Connect programs |
| **Dragon-Tiger List** | Daily SSE/SZSE disclosure of heavily traded stocks and top trading seats |
| **Chip distribution** | Cost-basis distribution of outstanding shares, often used to estimate support and resistance |
