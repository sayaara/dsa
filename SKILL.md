---
name: "stock_analyzer"
description: "Analyze stocks and the market. Invoke when the user wants to analyze one or more stocks, or run a market review."
---

# Stock Analyzer

This skill exposes the logic in `src/services/analyzer_service.py` to analyze individual stocks and the market as a whole.

## Output structure (`AnalysisResult`)

The analysis functions return an `AnalysisResult` object (or a list of them) with a rich structure. Below is a short overview of its key components, with real output examples:

The `dashboard` attribute holds the core analysis, split into four main sections:
1.  **`core_conclusion`**: one-line summary, signal type, and position recommendation.
2.  **`data_perspective`**: technical data, including trend state, price position, volume analysis, and chip structure.
3.  **`intelligence`**: qualitative information such as news, risk alerts, and positive catalysts.
4.  **`battle_plan`**: actionable strategy, including entry/exit targets, position strategy, and a risk-control checklist.

## Configuration (`Config`)

Every analysis function accepts an optional `config` object. It carries all application configuration, such as API keys, notification settings, and analysis parameters.

If no `config` object is supplied, the function automatically uses the global singleton loaded from the `.env` file.

**Reference:** [`Config`](src/config.py)

## Functions

### 1. Analyze a single stock

**Description:** Analyze one stock and return the analysis result.

**When to use:** When the user asks for analysis of a specific stock.

**Input:**
- `stock_code` (str): the stock code to analyze.
- `config` (Config, optional): configuration object. Defaults to `None`.
- `full_report` (bool, optional): whether to generate a full report. Defaults to `False`.
- `notifier` (NotificationService, optional): notification service object. Defaults to `None`.

**Output:** `Optional[AnalysisResult]`
An `AnalysisResult` object holding the analysis, or `None` if the analysis failed.

**Example:**

```python
from src.services.analyzer_service import analyze_stock

# Analyze a single stock
result = analyze_stock("600989")
if result:
    print(f"Stock: {result.name} ({result.code})")
    print(f"Sentiment score: {result.sentiment_score}")
    print(f"Operation advice: {result.operation_advice}")
```

**Reference:** [`analyze_stock`](src/services/analyzer_service.py)

### 2. Analyze multiple stocks

**Description:** Analyze a list of stocks and return a list of analysis results.

**When to use:** When the user wants several stocks analyzed at once.

**Input:**
- `stock_codes` (List[str]): the list of stock codes to analyze.
- `config` (Config, optional): configuration object. Defaults to `None`.
- `full_report` (bool, optional): whether to generate a full report for each stock. Defaults to `False`.
- `notifier` (NotificationService, optional): notification service object. Defaults to `None`.

**Output:** `List[AnalysisResult]`
A list of `AnalysisResult` objects.

**Example:**

```python
from src.services.analyzer_service import analyze_stocks

# Analyze multiple stocks
results = analyze_stocks(["600989", "000001"])
for result in results:
    print(f"Stock: {result.name}, operation advice: {result.operation_advice}")
```

**Reference:** [`analyze_stocks`](src/services/analyzer_service.py)

### 3. Run a market review

**Description:** Run a review of the overall market and return a report.

**When to use:** When the user asks for a market overview, summary, or review.

**Input:**
- `config` (Config, optional): configuration object. Defaults to `None`.
- `notifier` (NotificationService, optional): notification service object. Defaults to `None`.

**Output:** `Optional[str]`
A string containing the market review report, or `None` on failure.

**Example:**

```python
from src.services.analyzer_service import perform_market_review

# Run a market review
report = perform_market_review()
if report:
    print(report)
```

**Reference:** [`perform_market_review`](src/services/analyzer_service.py)

## Models and external bots

- To use **xAI Grok** as the DSA analysis model: configure `XAI_API_KEY` + `LITELLM_MODEL=xai/<official model ID>` (a direct LiteLLM connection, not a managed channel), and verify with `python scripts/check_env.py --llm`. See [`docs/LLM_CONFIG_GUIDE.md`](docs/LLM_CONFIG_GUIDE.md) for examples.
- The **[Grok Bot](https://x.ai/bot)** launched on 2026-08-11 is a separate path: it is an AI teammate with Skills / Routines / MCP / computer use, and it should call this repository's `analyze_stock` / REST API over HTTP rather than being configured as a LiteLLM provider itself. See [`docs/grok-bot-integration.md`](docs/grok-bot-integration.md) for the integration notes.
