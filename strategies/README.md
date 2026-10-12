# Trading Strategies

This directory holds **natural-language trading strategy files** (YAML). Every `.yaml` file here is loaded automatically at startup.

For users and documentation we keep calling these capabilities "strategies"; in the code, the configuration, and the API fields they are uniformly named `skill`, which you can read as "a reusable strategy capability pack".

## Writing a custom strategy (strategy skill)

Create a `.yaml` file and describe your trading strategy in natural language. **No code is needed.** Keep `display_name`, `description` and `aliases` in English: the Web UI shows them and `/ask` matches the aliases.

### Minimal template

```yaml
name: my_strategy          # Unique identifier (English, underscore-separated)
display_name: My Strategy   # Display name (shown in the Web UI and the agent prompt)
description: A short description of what the strategy is for

instructions: |
  Your strategy description...
  Write out the judgment criteria, entry conditions, exit conditions, and so on in natural language.
  You can name tools (such as get_daily_history or analyze_trend) to steer which data the AI uses.
```

### Full template

```yaml
name: my_strategy
display_name: My Strategy
description: A short description of the market conditions this strategy suits

# Strategy category: trend, pattern, reversal, framework
category: trend

# Related core trading principle numbers (1-7), optional
core_rules: [1, 2]

# The tools the strategy needs, optional
# Available tools (tests/test_strategy_required_tools.py checks them against the registry):
#   get_daily_history, get_realtime_quote, analyze_trend, analyze_pattern,
#   get_volume_analysis, get_market_indices, get_stock_info, search_stock_news,
#   search_comprehensive_intel
required_tools:
  - get_daily_history
  - analyze_trend

# Optional aliases (used by natural-language skill selection such as /ask; matched case-insensitively)
aliases: [my strategy, my model]

# The metadata below drives default behavior (optional)
# default_active: whether the skill is in the default active set
# default_router: whether the skill is in the router fallback set
# default_priority: the default display/sort priority; lower sorts first
# market_regimes: the market-state tags this skill suits best
default_active: true
default_router: false
default_priority: 100
market_regimes: [trending_up]

# The detailed strategy description (natural language, Markdown supported)
instructions: |
  **Your strategy name**

  Judgment criteria:

  1. **Condition one**:
     - Use `analyze_trend` to check the moving-average alignment.
     - Describe the trend characteristics you expect to see...

  2. **Condition two**:
     - Describe the volume requirement...

  Score adjustment:
  - The sentiment_score adjustment to suggest when the conditions are met
  - Name the strategy in `buy_reason`
```

### Core trading principles reference

| No. | Principle |
|------|------|
| 1 | Strict entry: only consider entering when the deviation rate is < 5% |
| 2 | Trend trading: a bullish MA5 > MA10 > MA20 alignment |
| 3 | Efficiency first: volume confirms that the trend is valid |
| 4 | Entry preference: prefer a pullback to moving-average support |
| 5 | Risk screening: bad news is an outright veto |
| 6 | Price-volume agreement: volume validates the price move |
| 7 | Relaxed for strong trends: leading stocks may have the criteria relaxed |

## A custom strategy directory

Besides this directory (the built-in strategies), an environment variable can point at an extra custom strategy directory:

```env
AGENT_SKILL_DIR=./my_skills
```

Both the built-in and the custom strategies are loaded. On a name conflict, the custom strategy overrides the built-in one.

The environment variable is still named `AGENT_SKILL_DIR`, which is the configuration entrypoint after the internal naming was unified; in product terms it still means "the custom strategy directory".
