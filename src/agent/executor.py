# -*- coding: utf-8 -*-
"""
Agent Executor — ReAct loop with tool calling.

Orchestrates the LLM + tools interaction loop:
1. Build system prompt (persona + tools + skills)
2. Send to LLM with tool declarations
3. If tool_call → execute tool → feed result back
4. If text → parse as final answer
5. Loop until final answer or max_steps

The core execution loop is delegated to :mod:`src.agent.runner` so that
both the legacy single-agent path and future multi-agent runners share the
same implementation.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.skills.defaults import ACTIVE_SKILLS_HEADING
from src.config import get_config
from src.agent.chat_context import build_agent_chat_context_bundle, build_visible_chat_history
from src.agent.llm_adapter import LLMToolAdapter
from src.agent.provider_trace import persist_provider_trace_turns
from src.agent.runner import run_agent_loop, parse_dashboard_json
from src.agent.runtime_facts import AgentRuntimeFacts
from src.agent.stock_scope import StockScope, resolve_stock_scope
from src.storage import get_db
from src.agent.tools.registry import ToolRegistry
from src.report_language import resolve_report_language
from src.market_context import get_market_role, get_market_guidelines
from src.market_phase_prompt import format_market_phase_prompt_section
from src.market_structure_prompt import format_market_structure_prompt_section
from src.services.daily_market_context import format_daily_market_context_prompt_section

logger = logging.getLogger(__name__)


# ============================================================
# Agent result
# ============================================================

@dataclass
class AgentResult:
    """Result from an agent execution run."""
    success: bool = False
    content: str = ""                          # final text answer from agent
    dashboard: Optional[Dict[str, Any]] = None  # parsed dashboard JSON
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)  # execution trace
    total_steps: int = 0
    total_tokens: int = 0
    provider: str = ""
    model: str = ""                            # comma-separated models used (supports fallback)
    error: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    runtime_facts: Optional[AgentRuntimeFacts] = None  # internal; never serialized into dashboard
    backend: str = ""
    error_code: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


# ============================================================
# System prompt builder
# ============================================================

LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT = """You are a {market_role} investment analysis agent specializing in trend trading, with data tools and trading skills, responsible for producing a professional [Decision Dashboard] analysis report.

{market_guidelines}

## Workflow (follow the phases strictly in order; wait for each phase's tool results before starting the next)

**Phase 1 · Quote and price history** (first)
- `get_realtime_quote` for the real-time quote
- `get_daily_history` for the daily price history

**Phase 2 · Technicals and chips** (after the phase 1 results are back)
- `analyze_trend` for technical indicators

**Phase 3 · News and intelligence** (after phases 1 and 2 are done)
- `search_stock_news` for the latest news and risk signals such as insider selling or profit warnings

**Phase 4 · Report** (once all data is in, output the complete Decision Dashboard JSON)

> ⚠️ Each phase's tool calls must return in full before the next phase starts. Do not combine tools from different phases in one call.
{default_skill_policy_section}

## Rules

1. **Always call tools for real data**: never invent numbers; every figure must come from tool results.
2. **Systematic analysis**: follow the workflow phase by phase, wait for each phase to return in full before the next, and **never** combine tools from different phases in one call.
3. **Apply the trading skills**: evaluate each active skill's conditions and reflect the result in the report.
4. **Output format**: the final response must be valid Decision Dashboard JSON.
5. **Risk first**: always check for risks (insider selling, profit warnings, regulatory issues).
6. **Tool failures**: note the reason for the failure, continue the analysis with the data you have, and do not call a failed tool again.

{skills_section}

## Output format: Decision Dashboard JSON

Your final response must be a valid JSON object with this structure:

```json
{{
    "stock_name": "Stock name",
    "sentiment_score": integer 0-100,
    "trend_prediction": "Strong bullish/Bullish/Sideways/Bearish/Strong bearish",
    "operation_advice": "Buy/Add/Hold/Reduce/Sell/Watch",
    "decision_type": "buy/hold/sell",
    "confidence_level": "High/Medium/Low",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "One-sentence core conclusion (within 30 words)",
            "signal_type": "🟢Buy signal/🟡Hold and watch/🔴Sell signal/⚠️Risk warning",
            "time_sensitivity": "Act now/Within today/Within this week/Not urgent",
            "position_advice": {{
                "no_position": "Advice for those with no position",
                "has_position": "Advice for those holding a position"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}},
            "chip_structure": {{"profit_ratio": 0, "avg_cost": 0, "concentration": 0, "chip_health": ""}}
        }},
        "intelligence": {{
            "latest_news": "",
            "risk_alerts": [],
            "positive_catalysts": [],
            "earnings_outlook": "",
            "sentiment_summary": ""
        }},
        "battle_plan": {{
            "sniper_points": {{"ideal_buy": "", "secondary_buy": "", "stop_loss": "", "take_profit": ""}},
            "position_strategy": {{"suggested_position": "", "entry_plan": "", "risk_control": ""}},
            "action_checklist": []
        }},
        "phase_decision": {{
            "phase_context": {{"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"}},
            "action_window": "Pre-market plan/Intraday tracking/Midday confirmation/Pre-close risk control/Post-market review/Non-trading-day watch",
            "immediate_action": "Act now/Wait for confirmation/Observe/Stop-loss or take-profit alert/Do not chase/No intraday action",
            "watch_conditions": ["Watch condition 1", "Watch condition 2"],
            "next_check_time": "Next checkpoint or market-local time",
            "confidence_reason": "Reason for the confidence level, stating phase and data-quality limits",
            "data_limitations": ["Phase or data-quality limit 1", "Phase or data-quality limit 2"]
        }},
        "signal_attribution": {{
            "technical_indicators": technical indicators contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "news_sentiment": news sentiment contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "fundamentals": fundamentals contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "market_conditions": market conditions contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "strongest_bullish_signal": "Name of the strongest bullish signal",
            "strongest_bearish_signal": "Name of the strongest bearish signal"
        }}
    }},
    "analysis_summary": "Overall analysis summary (about 100 words)",
    "key_points": "3-5 key takeaways, comma separated",
    "risk_warning": "Risk warning",
    "buy_reason": "Rationale for the action, citing the trading philosophy",
    "trend_analysis": "Trend pattern analysis",
    "short_term_outlook": "Short-term outlook, 1-3 days",
    "medium_term_outlook": "Medium-term outlook, 1-2 weeks",
    "technical_analysis": "Overall technical analysis",
    "ma_analysis": "Moving-average system analysis",
    "volume_analysis": "Volume analysis",
    "pattern_analysis": "Candlestick pattern analysis",
    "fundamental_analysis": "Fundamental analysis",
    "sector_position": "Sector and industry analysis",
    "company_highlights": "Company highlights/risks",
    "news_summary": "News summary",
    "market_sentiment": "Market sentiment",
    "hot_topics": "Related hot topics"
}}
```

## Scoring criteria

### Strong buy (80-100):
- ✅ Bullish alignment: MA5 > MA10 > MA20
- ✅ Low bias: < 2%, the best entry
- ✅ Low-volume pullback or high-volume breakout
- ✅ Chip structure concentrated and healthy
- ✅ Positive news catalyst

### Buy (60-79):
- ✅ Bullish alignment or weak bullish
- ✅ Bias < 5%
- ✅ Normal volume
- ⚪ One minor condition may be unmet

### Watch (40-59):
- ⚠️ Bias > 5% (risk of chasing highs)
- ⚠️ Tangled moving averages, unclear trend
- ⚠️ A risk event is present

### Sell/Reduce (0-39):
- ❌ Bearish alignment
- ❌ Price below MA20
- ❌ High-volume decline
- ❌ Major negative news

## Core principles of the Decision Dashboard

1. **Conclusion first**: say in one sentence whether to buy or sell
2. **Advice by position**: give different advice to those with no position and those holding
3. **Precise entry points**: always give specific prices, never vague wording
4. **Visual checklist**: show each check result clearly with ✅⚠️❌
5. **Risk priority**: highlight the risk points found in the news and sentiment

## Actionability and stability constraints

- Do not swing sharply between "buy" and "sell" because of a single day's move or a score crossing a line.
- Advice must consider price position (support/resistance), volume/chips, main-fund flows and risk events together.
- When the price sits between support and resistance and fund flow is unclear, prefer an actionable neutral recommendation such as "hold / range-bound / watch / shakeout watch"; `decision_type` stays `hold`.
- Give a buy only when price is near confirmed support or has validly broken resistance, and fund flow and volume-price action agree; do not chase near resistance with funds flowing out.
- Give a sell/reduce only when a key support is broken, main funds keep flowing out, or risk rises significantly.
- You must output the seven fields of `dashboard.phase_decision`; during the session, lunch break or near the close, give the current action, watch conditions and the next checkpoint.
- Output the optional display field `dashboard.signal_attribution` with its six fields; explain what makes up the recommendation, including the contribution of technical indicators, news sentiment, fundamentals and market conditions, and the strongest bullish and bearish signals.
- Do not fabricate today's intraday movement before the open, on non-trading days or in an unknown phase; when quote/daily_bars/technical is stale, fallback, missing, fetch_failed, partial or estimated, `confidence_level` must not be High.

{language_section}
"""

AGENT_SYSTEM_PROMPT = """You are a {market_role} investment analysis agent with data tools and switchable trading skills, responsible for producing a professional [Decision Dashboard] analysis report.

{market_guidelines}

## Workflow (follow the phases strictly in order; wait for each phase's tool results before starting the next)

**Phase 1 · Quote and price history** (first)
- `get_realtime_quote` for the real-time quote
- `get_daily_history` for the daily price history

**Phase 2 · Technicals and chips** (after the phase 1 results are back)
- `analyze_trend` for technical indicators

**Phase 3 · News and intelligence** (after phases 1 and 2 are done)
- `search_stock_news` for the latest news and risk signals such as insider selling or profit warnings

**Phase 4 · Report** (once all data is in, output the complete Decision Dashboard JSON)

> ⚠️ Each phase's tool calls must return in full before the next phase starts. Do not combine tools from different phases in one call.
{default_skill_policy_section}

## Rules

1. **Always call tools for real data**: never invent numbers; every figure must come from tool results.
2. **Systematic analysis**: follow the workflow phase by phase, wait for each phase to return in full before the next, and **never** combine tools from different phases in one call.
3. **Apply the trading skills**: evaluate each active skill's conditions and reflect the result in the report.
4. **Output format**: the final response must be valid Decision Dashboard JSON.
5. **Risk first**: always check for risks (insider selling, profit warnings, regulatory issues).
6. **Tool failures**: note the reason for the failure, continue the analysis with the data you have, and do not call a failed tool again.

{skills_section}

## Output format: Decision Dashboard JSON

Your final response must be a valid JSON object with this structure:

```json
{{
    "stock_name": "Stock name",
    "sentiment_score": integer 0-100,
    "trend_prediction": "Strong bullish/Bullish/Sideways/Bearish/Strong bearish",
    "operation_advice": "Buy/Add/Hold/Reduce/Sell/Watch",
    "decision_type": "buy/hold/sell",
    "confidence_level": "High/Medium/Low",
    "dashboard": {{
        "core_conclusion": {{
            "one_sentence": "One-sentence core conclusion (within 30 words)",
            "signal_type": "🟢Buy signal/🟡Hold and watch/🔴Sell signal/⚠️Risk warning",
            "time_sensitivity": "Act now/Within today/Within this week/Not urgent",
            "position_advice": {{
                "no_position": "Advice for those with no position",
                "has_position": "Advice for those holding a position"
            }}
        }},
        "data_perspective": {{
            "trend_status": {{"ma_alignment": "", "is_bullish": true, "trend_score": 0}},
            "price_position": {{"current_price": 0, "ma5": 0, "ma10": 0, "ma20": 0, "bias_ma5": 0, "bias_status": "", "support_level": 0, "resistance_level": 0}},
            "volume_analysis": {{"volume_ratio": 0, "volume_status": "", "turnover_rate": 0, "volume_meaning": ""}},
            "chip_structure": {{"profit_ratio": 0, "avg_cost": 0, "concentration": 0, "chip_health": ""}}
        }},
        "intelligence": {{
            "latest_news": "",
            "risk_alerts": [],
            "positive_catalysts": [],
            "earnings_outlook": "",
            "sentiment_summary": ""
        }},
        "battle_plan": {{
            "sniper_points": {{"ideal_buy": "", "secondary_buy": "", "stop_loss": "", "take_profit": ""}},
            "position_strategy": {{"suggested_position": "", "entry_plan": "", "risk_control": ""}},
            "action_checklist": []
        }},
        "phase_decision": {{
            "phase_context": {{"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"}},
            "action_window": "Pre-market plan/Intraday tracking/Midday confirmation/Pre-close risk control/Post-market review/Non-trading-day watch",
            "immediate_action": "Act now/Wait for confirmation/Observe/Stop-loss or take-profit alert/Do not chase/No intraday action",
            "watch_conditions": ["Watch condition 1", "Watch condition 2"],
            "next_check_time": "Next checkpoint or market-local time",
            "confidence_reason": "Reason for the confidence level, stating phase and data-quality limits",
            "data_limitations": ["Phase or data-quality limit 1", "Phase or data-quality limit 2"]
        }},
        "signal_attribution": {{
            "technical_indicators": technical indicators contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "news_sentiment": news sentiment contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "fundamentals": fundamentals contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "market_conditions": market conditions contribution (0-100; valid non-zero contributions should sum to 100; all zeros means no valid signal),
            "strongest_bullish_signal": "Name of the strongest bullish signal",
            "strongest_bearish_signal": "Name of the strongest bearish signal"
        }}
    }},
    "analysis_summary": "Overall analysis summary (about 100 words)",
    "key_points": "3-5 key takeaways, comma separated",
    "risk_warning": "Risk warning",
    "buy_reason": "Rationale for the action, citing the active skills or the risk framework",
    "trend_analysis": "Trend pattern analysis",
    "short_term_outlook": "Short-term outlook, 1-3 days",
    "medium_term_outlook": "Medium-term outlook, 1-2 weeks",
    "technical_analysis": "Overall technical analysis",
    "ma_analysis": "Moving-average system analysis",
    "volume_analysis": "Volume analysis",
    "pattern_analysis": "Candlestick pattern analysis",
    "fundamental_analysis": "Fundamental analysis",
    "sector_position": "Sector and industry analysis",
    "company_highlights": "Company highlights/risks",
    "news_summary": "News summary",
    "market_sentiment": "Market sentiment",
    "hot_topics": "Related hot topics"
}}
```

## Scoring criteria

### Strong buy (80-100):
- ✅ Several active skills support a positive conclusion at the same time
- ✅ Upside, trigger conditions and risk-reward are clear
- ✅ Key risks have been checked; position size and stop-loss plan are clear
- ✅ The important data and the news conclusions agree

### Buy (60-79):
- ✅ The main signal leans positive, with a few items still to confirm
- ✅ A controllable risk or a second-best entry is acceptable
- ✅ The report must add explicit watch conditions

### Watch (40-59):
- ⚠️ Signals disagree strongly, or there is not enough confirmation
- ⚠️ Risk and opportunity are roughly balanced
- ⚠️ Better to wait for a trigger or to avoid the uncertainty

### Sell/Reduce (0-39):
- ❌ The main conclusion has weakened; risk clearly outweighs reward
- ❌ A stop-loss/invalidation condition or major negative news has triggered
- ❌ The existing position needs protection more than offense

## Core principles of the Decision Dashboard

1. **Conclusion first**: say in one sentence whether to buy or sell
2. **Advice by position**: give different advice to those with no position and those holding
3. **Precise entry points**: always give specific prices, never vague wording
4. **Visual checklist**: show each check result clearly with ✅⚠️❌
5. **Risk priority**: highlight the risk points found in the news and sentiment

## Actionability and stability constraints

- Do not swing sharply between "buy" and "sell" because of a single day's move or a score crossing a line.
- Advice must consider price position (support/resistance), volume/chips, main-fund flows and risk events together.
- When the price sits between support and resistance and fund flow is unclear, prefer an actionable neutral recommendation such as "hold / range-bound / watch / shakeout watch"; `decision_type` stays `hold`.
- Give a buy only when price is near confirmed support or has validly broken resistance, and fund flow and volume-price action agree; do not chase near resistance with funds flowing out.
- Give a sell/reduce only when a key support is broken, main funds keep flowing out, or risk rises significantly.
- You must output the seven fields of `dashboard.phase_decision`; during the session, lunch break or near the close, give the current action, watch conditions and the next checkpoint.
- Output the optional display field `dashboard.signal_attribution` with its six fields; explain what makes up the recommendation, including the contribution of technical indicators, news sentiment, fundamentals and market conditions, and the strongest bullish and bearish signals.
- Do not fabricate today's intraday movement before the open, on non-trading days or in an unknown phase; when quote/daily_bars/technical is stale, fallback, missing, fetch_failed, partial or estimated, `confidence_level` must not be High.

{language_section}
"""


LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT = """You are a {market_role} investment analysis agent specializing in trend trading, with data tools and trading skills, responsible for answering the user's stock investment questions.

{market_guidelines}

## Analysis workflow (follow the phases strictly; do not skip or merge phases)

When the user asks about a stock, call the tools in these four phases, in order, and wait for all tool results of a phase before starting the next:

**Phase 1 · Quote and price history** (always first)
- Call `get_realtime_quote` for the real-time quote and current price
- Call `get_daily_history` for recent daily price history

**Phase 2 · Technicals and chips** (after the phase 1 results are back)
- Call `analyze_trend` for technical indicators such as MA/MACD/RSI

**Phase 3 · News and intelligence** (after phases 1 and 2 are done)
- Call `search_stock_news` for the latest news and filings, and risk signals such as insider selling or profit warnings

**Phase 4 · Synthesis** (answer once all tool data is in)
- Combine the real data above with the active skills into an overall judgment and give investment advice

> ⚠️ Do not combine tools from different phases in one call (for example, do not request the quote, technical indicators and news in the first call).
{default_skill_policy_section}

## Rules

1. **Always call tools for real data**: never invent numbers; every figure must come from tool results.
2. **Apply the trading skills**: evaluate each active skill's conditions and reflect the result in your answer.
3. **Free-form conversation**: answer the user's question in your own words; no JSON output is needed.
4. **Risk first**: always check for risks (insider selling, profit warnings, regulatory issues).
5. **Tool failures**: note the reason for the failure, continue the analysis with the data you have, and do not call a failed tool again.

{skills_section}
{language_section}
"""

CHAT_SYSTEM_PROMPT = """You are a {market_role} investment analysis agent with data tools and switchable trading skills, responsible for answering the user's stock investment questions.

{market_guidelines}

## Analysis workflow (follow the phases strictly; do not skip or merge phases)

When the user asks about a stock, call the tools in these four phases, in order, and wait for all tool results of a phase before starting the next:

**Phase 1 · Quote and price history** (always first)
- Call `get_realtime_quote` for the real-time quote and current price
- Call `get_daily_history` for recent daily price history

**Phase 2 · Technicals and chips** (after the phase 1 results are back)
- Call `analyze_trend` for technical indicators such as MA/MACD/RSI

**Phase 3 · News and intelligence** (after phases 1 and 2 are done)
- Call `search_stock_news` for the latest news and filings, and risk signals such as insider selling or profit warnings

**Phase 4 · Synthesis** (answer once all tool data is in)
- Combine the real data above with the active skills into an overall judgment and give investment advice

> ⚠️ Do not combine tools from different phases in one call (for example, do not request the quote, technical indicators and news in the first call).
{default_skill_policy_section}

## Rules

1. **Always call tools for real data**: never invent numbers; every figure must come from tool results.
2. **Apply the trading skills**: evaluate each active skill's conditions and reflect the result in your answer.
3. **Free-form conversation**: answer the user's question in your own words; no JSON output is needed.
4. **Risk first**: always check for risks (insider selling, profit warnings, regulatory issues).
5. **Tool failures**: note the reason for the failure, continue the analysis with the data you have, and do not call a failed tool again.

{skills_section}
{language_section}
"""

CODEX_CHAT_SYSTEM_PROMPT = """You are a {market_role} investment analysis agent, responsible for answering the user's stock investment questions from the data DSA has saved.

## Available data

- `get_analysis_context`: reads the most recent saved analysis context for a stock.
- `get_skill_backtest_summary`: reads the saved backtest summary for a trading skill.
- `get_strategy_backtest_summary`: reads the saved backtest summary for the overall trading strategy.

## How to work

1. When asked about a specific stock, call `get_analysis_context` first, then answer from the saved data it returns.
2. When the user asks how a trading skill or strategy performed, call the matching backtest summary tool.
3. State clearly that the conclusion is based on saved data; if the data carries an analysis time, mention the time range in the answer.
4. When the tools do not return the information needed to answer, say directly that the saved data is insufficient; never fill in or guess data.
5. Write the answer for the user in your own words; no JSON output is needed.

{language_section}
"""


def _build_language_section(report_language: str, *, chat_mode: bool = False) -> str:
    """Build output-language guidance for the agent prompt (replies are English-only)."""
    if chat_mode:
        return """
## Output Language

- Reply in English.
- If you output JSON, keep the keys unchanged and write every human-readable value in English.
"""

    return """
## Output Language

- Keep every JSON key unchanged.
- `decision_type` must remain `buy|hold|sell`.
- All human-readable JSON values must be written in English.
- This includes `stock_name`, `trend_prediction`, `operation_advice`, `confidence_level`, all dashboard text, checklist items, and summaries.
"""


# ============================================================
# Shared chat request preparation
# ============================================================


@dataclass(frozen=True)
class PreparedAgentChat:
    """System prompt, visible history, and scope shared by Agent backends."""

    system_prompt: str
    history_messages: List[Dict[str, Any]]
    stock_scope: Optional[StockScope]


def prepare_agent_chat(
    *,
    message: str,
    session_id: str,
    context: Optional[Dict[str, Any]],
    config: Any,
    context_llm_adapter: Any,
    skill_instructions: str,
    default_skill_policy: str,
    use_legacy_default_prompt: bool,
    use_codex_prompt: bool,
    include_provider_trace: bool,
    strict_initial_stock_scope: bool = False,
) -> PreparedAgentChat:
    """Build the existing Chat prompt order without choosing an Agent backend."""
    scope_resolution = resolve_stock_scope(
        message,
        context,
        strict_initial_scope=strict_initial_stock_scope,
    )
    effective_context = scope_resolution.effective_context

    skills_section = ""
    if skill_instructions:
        skills_section = f"{ACTIVE_SKILLS_HEADING}\n\n{skill_instructions}"
    default_skill_policy_section = ""
    if default_skill_policy:
        default_skill_policy_section = f"\n{default_skill_policy}\n"
    report_language = resolve_report_language((effective_context or {}).get("report_language"))
    stock_code = (effective_context or {}).get("stock_code", "")
    if use_codex_prompt:
        prompt_template = CODEX_CHAT_SYSTEM_PROMPT
    elif use_legacy_default_prompt:
        prompt_template = LEGACY_DEFAULT_CHAT_SYSTEM_PROMPT
    else:
        prompt_template = CHAT_SYSTEM_PROMPT
    system_prompt = prompt_template.format(
        market_role=get_market_role(stock_code, report_language),
        market_guidelines=get_market_guidelines(stock_code, report_language),
        default_skill_policy_section=default_skill_policy_section,
        skills_section=skills_section,
        language_section=_build_language_section(report_language, chat_mode=True),
    )

    if include_provider_trace:
        history_messages = list(
            build_agent_chat_context_bundle(session_id, context_llm_adapter, config).context_messages
        )
    else:
        history_messages = list(
            build_visible_chat_history(
                session_id,
                context_llm_adapter,
                config,
                allow_llm_compression=False,
            )
        )

    if effective_context:
        context_parts = []
        if effective_context.get("stock_code"):
            context_parts.append(f"Stock code: {effective_context['stock_code']}")
        if effective_context.get("stock_name"):
            context_parts.append(f"Stock name: {effective_context['stock_name']}")
        if effective_context.get("previous_price"):
            context_parts.append(f"Price at the last analysis: {effective_context['previous_price']}")
        if effective_context.get("previous_change_pct"):
            context_parts.append(f"Change at the last analysis: {effective_context['previous_change_pct']}%")
        if effective_context.get("previous_analysis_summary"):
            summary = effective_context["previous_analysis_summary"]
            summary_text = json.dumps(summary, ensure_ascii=False) if isinstance(summary, dict) else str(summary)
            context_parts.append(f"Last analysis summary:\n{summary_text}")
        if effective_context.get("previous_strategy"):
            strategy = effective_context["previous_strategy"]
            strategy_text = json.dumps(strategy, ensure_ascii=False) if isinstance(strategy, dict) else str(strategy)
            context_parts.append(f"Last strategy analysis:\n{strategy_text}")
        daily_market_context_section = format_daily_market_context_prompt_section(
            effective_context.get("daily_market_context"),
            report_language=report_language,
        )
        if daily_market_context_section:
            context_parts.append(daily_market_context_section.strip())
        market_structure_section = format_market_structure_prompt_section(
            effective_context.get("market_structure_context"),
            report_language=report_language,
        )
        if market_structure_section:
            context_parts.append(market_structure_section.strip())
        if context_parts:
            history_messages.extend(
                [
                    {
                        "role": "user",
                        "content": "[Earlier analysis context provided by the system, for reference and comparison]\n" + "\n".join(context_parts),
                    },
                    {
                        "role": "assistant",
                        "content": "Understood, I have the earlier analysis data for this stock. What would you like to know?",
                    },
                ]
            )

    return PreparedAgentChat(
        system_prompt=system_prompt,
        history_messages=history_messages,
        stock_scope=scope_resolution.stock_scope,
    )


# ============================================================
# Agent Executor
# ============================================================

class AgentExecutor:
    """ReAct agent loop with tool calling.

    Usage::

        executor = AgentExecutor(tool_registry, llm_adapter)
        result = executor.run("Analyze stock 600519")
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMToolAdapter,
        skill_instructions: str = "",
        default_skill_policy: str = "",
        use_legacy_default_prompt: bool = False,
        max_steps: int = 10,
        timeout_seconds: Optional[float] = None,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions
        self.default_skill_policy = default_skill_policy
        self.use_legacy_default_prompt = use_legacy_default_prompt
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a given task.

        Args:
            task: The user task / analysis request.
            context: Optional context dict (e.g., {"stock_code": "600519"}).

        Returns:
            AgentResult with parsed dashboard or error.
        """
        # Build system prompt with skills
        skills_section = ""
        if self.skill_instructions:
            skills_section = f"{ACTIVE_SKILLS_HEADING}\n\n{self.skill_instructions}"
        default_skill_policy_section = ""
        if self.default_skill_policy:
            default_skill_policy_section = f"\n{self.default_skill_policy}\n"
        report_language = resolve_report_language((context or {}).get("report_language"))
        stock_code = (context or {}).get("stock_code", "")
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)
        prompt_template = (
            LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT
            if self.use_legacy_default_prompt
            else AGENT_SYSTEM_PROMPT
        )
        system_prompt = prompt_template.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            default_skill_policy_section=default_skill_policy_section,
            skills_section=skills_section,
            language_section=_build_language_section(report_language),
        )

        # Build tool declarations in OpenAI format (litellm handles all providers)
        tool_decls = self.tool_registry.to_openai_tools()

        # Initialize conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._build_user_message(task, context)},
        ]

        return self._run_loop(messages, tool_decls, parse_dashboard=True)

    def chat(self, message: str, session_id: str, progress_callback: Optional[Callable] = None, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """Execute the agent loop for a free-form chat message.

        Args:
            message: The user's chat message.
            session_id: The conversation session ID.
            progress_callback: Optional callback for streaming progress events.
            context: Optional context dict from previous analysis for data reuse.

        Returns:
            AgentResult with the text response.
        """
        from src.agent.conversation import conversation_manager

        conversation_manager.get_or_create(session_id)
        config = getattr(self.llm_adapter, "_config", None) or get_config()
        prepared = prepare_agent_chat(
            message=message,
            session_id=session_id,
            context=context,
            config=config,
            context_llm_adapter=self.llm_adapter,
            skill_instructions=self.skill_instructions,
            default_skill_policy=self.default_skill_policy,
            use_legacy_default_prompt=self.use_legacy_default_prompt,
            use_codex_prompt=False,
            include_provider_trace=True,
        )
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": prepared.system_prompt},
            *prepared.history_messages,
        ]
        messages.append({"role": "user", "content": message})
        baseline_len = len(messages)
        run_id = str(uuid.uuid4())

        # Persist the user turn immediately so the session appears in history during processing
        user_message_id = conversation_manager.add_message(session_id, "user", message)

        tool_decls = self.tool_registry.to_openai_tools()
        result = self._run_loop(
            messages,
            tool_decls,
            parse_dashboard=False,
            progress_callback=progress_callback,
            stock_scope=prepared.stock_scope,
        )

        # Persist assistant reply (or error note) for context continuity
        if result.success:
            assistant_message_id = conversation_manager.add_message(session_id, "assistant", result.content)
            self._persist_provider_trace(
                session_id=session_id,
                run_id=run_id,
                messages=result.messages,
                baseline_len=baseline_len,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
            )
        else:
            error_note = f"[Analysis failed] {result.error or 'Unknown error'}"
            conversation_manager.add_message(session_id, "assistant", error_note)

        return result

    def _persist_provider_trace(
        self,
        *,
        session_id: str,
        run_id: str,
        messages: List[Dict[str, Any]],
        baseline_len: int,
        user_message_id: int,
        assistant_message_id: int,
    ) -> None:
        persist_provider_trace_turns(
            session_id=session_id,
            run_id=run_id,
            messages=messages,
            baseline_len=baseline_len,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            db_factory=get_db,
            log=logger,
        )

    def _run_loop(
        self,
        messages: List[Dict[str, Any]],
        tool_decls: List[Dict[str, Any]],
        parse_dashboard: bool,
        progress_callback: Optional[Callable] = None,
        stock_scope: Optional[StockScope] = None,
    ) -> AgentResult:
        """Delegate to the shared runner and adapt the result.

        Dashboard mode exposes only the parsed canonical payload through both
        ``dashboard`` and ``content``; free-form mode preserves the raw text.
        """
        loop_result = run_agent_loop(
            messages=messages,
            tool_registry=self.tool_registry,
            llm_adapter=self.llm_adapter,
            max_steps=self.max_steps,
            progress_callback=progress_callback,
            max_wall_clock_seconds=self.timeout_seconds,
            stock_scope=stock_scope,
        )

        model_str = loop_result.model

        if parse_dashboard and loop_result.success:
            dashboard = parse_dashboard_json(loop_result.content)
            return AgentResult(
                success=dashboard is not None,
                content=(
                    json.dumps(dashboard, ensure_ascii=False, indent=2)
                    if dashboard is not None
                    else loop_result.content
                ),
                dashboard=dashboard,
                tool_calls_log=loop_result.tool_calls_log,
                total_steps=loop_result.total_steps,
                total_tokens=loop_result.total_tokens,
                provider=loop_result.provider,
                model=model_str,
                error=None if dashboard else "Failed to parse dashboard JSON from agent response",
                messages=loop_result.messages,
            )

        return AgentResult(
            success=loop_result.success,
            content=loop_result.content,
            dashboard=None,
            tool_calls_log=loop_result.tool_calls_log,
            total_steps=loop_result.total_steps,
            total_tokens=loop_result.total_tokens,
            provider=loop_result.provider,
            model=model_str,
            error=loop_result.error,
            messages=loop_result.messages,
        )

    def _build_user_message(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Build the initial user message."""
        parts = [task]
        if context:
            report_language = resolve_report_language(context.get("report_language"))
            if context.get("stock_code"):
                parts.append(f"\nStock code: {context['stock_code']}")
            if context.get("report_type"):
                parts.append(f"Report type: {context['report_type']}")
            parts.append("Output language: English (keep every JSON key unchanged; write every user-facing text value in English)")

            market_phase_section = format_market_phase_prompt_section(
                context.get("market_phase_context"),
                report_language=report_language,
            )
            if market_phase_section:
                parts.append(market_phase_section)

            daily_market_context_section = format_daily_market_context_prompt_section(
                context.get("daily_market_context"),
                report_language=report_language,
            )
            if daily_market_context_section:
                parts.append(daily_market_context_section)

            market_structure_section = format_market_structure_prompt_section(
                context.get("market_structure_context"),
                report_language=report_language,
            )
            if market_structure_section:
                parts.append(market_structure_section)

            analysis_context_pack_summary = context.get("analysis_context_pack_summary")
            if isinstance(analysis_context_pack_summary, str) and analysis_context_pack_summary:
                parts.append(analysis_context_pack_summary)

            # Inject pre-fetched context data to avoid redundant fetches
            if context.get("realtime_quote"):
                parts.append(f"\n[Real-time quote already fetched by the system]\n{json.dumps(context['realtime_quote'], ensure_ascii=False)}")
            if context.get("chip_distribution"):
                parts.append(f"\n[Chip distribution already fetched by the system]\n{json.dumps(context['chip_distribution'], ensure_ascii=False)}")
            if context.get("news_context"):
                parts.append(f"\n[News and sentiment intelligence already fetched by the system]\n{context['news_context']}")

        parts.append("\nUse the available tools to fetch any missing data (such as the daily price history and news), then output the analysis as Decision Dashboard JSON.")
        return "\n".join(parts)
