# Beginner's guide to installing and configuring the client

This document is for users who do not write code and just want to download the client and use it. The goal is simple: download the client, enter a model service key, enter some stock codes, and generate your first analysis report.

> This project produces supporting analysis reports; it is not investment advice. Judge the risk of any real trade yourself.

## Before you start

1. A Windows or macOS computer.
2. A model service key. Either of these is a good choice:
   - [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC): supports the major global models, and a single key works for both the model and news search, which makes the first setup the least work.
   - [AIHubMix](https://inferera.com/?aff=CfMq): supports the major global models, and suits users who want to switch between several models on one platform.
3. The stock codes you want to analyze, for example `AAPL,MSFT,RY.TO`.

## 1. Download the client

Open the releases page:

<https://github.com/your-org/your-repo/releases/latest>

Download from `Assets` at the bottom of the page:

| Computer | Which file |
| --- | --- |
| Windows | `daily-stock-analysis-windows-installer-<version>.exe` |
| Windows, without installing | `daily-stock-analysis-windows-noinstall-<version>.zip` |
| macOS Apple silicon | `daily-stock-analysis-macos-arm64-<version>.dmg` |
| macOS Intel | `daily-stock-analysis-macos-x64-<version>.dmg` |

You do not need `latest.yml` or `*.blockmap`; they are not client installers.

If you are not sure which chip your Mac has: click the Apple icon in the top-left corner -> About This Mac. M1/M2/M3/M4 means `arm64`, and Intel means `x64`.

## 2. Install and open it

- Windows installer: double-click the `.exe` and follow the prompts; the default installation directory is fine.
- Windows portable package: extract the `.zip` and double-click `Daily Stock Analysis.exe`.
- macOS: double-click the `.dmg` and drag the app into `Applications`. The current DMG is not signed or notarized with an Apple Developer certificate, so Gatekeeper may still block it. Only allow it through Privacy & Security for official GitHub Releases attachments; see `docs/desktop-package.md` for the full limitations and troubleshooting.

macOS users should export a configuration backup from the client settings before upgrading.

## 3. Configure the AI model

Open the client and go to:

`System Settings -> AI model`

Pick just one of the options below.

> Important: click the save button on the page after every change. Wait for the save-succeeded message before switching pages or going back to the home page.

### Option A: Anspire Open

1. Open [Anspire Open](https://open.anspire.cn/?share_code=QFBC0FYC), register or sign in, and create an API key.
2. Back in the client, choose `Anspire Open` under quick channel setup.
3. Paste the API key.
4. Choose a model that is enabled in your console; if you are unsure, start with the console's recommended or lightweight model.
5. Click save, and once you see the save-succeeded message, click test connection.

### Option B: AIHubMix

1. Open [AIHubMix](https://inferera.com/?aff=CfMq), register or sign in, and create an API key.
2. Back in the client, choose `AIHubmix (aggregator platform)` under quick channel setup.
3. Paste the API key.
4. Choose a model that is enabled in your console; if you are unsure, start with the console's recommended model.
5. Click save, and once you see the save-succeeded message, click test connection.

Once the test succeeds, move on to the next step.

## 4. Enter your watchlist

Go to:

`System Settings -> Basic settings`

Find `Watchlist` and enter:

`AAPL,MSFT,RY.TO`

Separate multiple stocks with a comma. Common formats:

- A-shares: `600519`, `300750`, `000001`
- Canada: `RY.TO`, `SHOP.TO` (Hong Kong is not currently supported)
- US: `AAPL`, `TSLA`, `NVDA`

Click save, and go back to the home page once you see the save-succeeded message.

## 5. Configuring a news source is recommended

A news source is optional but recommended. It feeds recent news, announcements, event-driven signals, hot themes, and risk warnings.

Go to:

`System Settings -> Data sources`

Choose according to your model service:

1. Using Anspire Open: find `Anspire API Keys` and enter the same Anspire key; you are done once it saves successfully.
2. Using AIHubMix: getting a [SerpAPI](https://serpapi.com/github-daily-stock-analysis) or [Tavily](https://tavily.com/) key as well is recommended. Enter it under `SerpAPI API Keys` or `Tavily API Keys`; you are done once it saves successfully.

You can skip the news source if you just want to try things out - the client still produces a basic analysis.

## 6. Run an analysis

Back on the home page:

1. Enter a stock code, for example `600519`.
2. Click analyze.
3. Wait for the task to move from queued to analyzing to complete.
4. View the report under history.

## Troubleshooting

### There are a lot of files on the download page; which one do I need?

Ordinary Windows users download the `.exe` installer. Do not download `latest.yml` or `*.blockmap`.

### I entered an API key but it still does not work

Check these:

1. Whether the key was copied in full, with no stray spaces.
2. Whether the platform account has credit or quota left.
3. Whether the current model is enabled.
4. Whether the connection test reports a missing model, insufficient permissions, or insufficient balance.

### What if my configuration gets into a mess?

Export a configuration backup from the client settings. When something goes wrong you can import an earlier backup, or keep just these three and reconfigure: the AI model, the watchlist, and the news source.
