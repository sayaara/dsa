# -*- coding: utf-8 -*-
"""Market strategy blueprints for the CA/HK/US daily market recap."""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class StrategyDimension:
    """Single strategy dimension used by market recap prompts."""

    name: str
    objective: str
    checkpoints: List[str]


@dataclass(frozen=True)
class MarketStrategyBlueprint:
    """Region specific market strategy blueprint."""

    region: str
    title: str
    positioning: str
    principles: List[str]
    dimensions: List[StrategyDimension]
    action_framework: List[str]

    def to_prompt_block(self) -> str:
        """Render blueprint as prompt instructions."""
        principles_text = "\n".join([f"- {item}" for item in self.principles])
        action_text = "\n".join([f"- {item}" for item in self.action_framework])

        dims = []
        for dim in self.dimensions:
            checkpoints = "\n".join([f"  - {cp}" for cp in dim.checkpoints])
            dims.append(f"- {dim.name}: {dim.objective}\n{checkpoints}")
        dimensions_text = "\n".join(dims)

        return (
            f"## Strategy Blueprint: {self.title}\n"
            f"{self.positioning}\n\n"
            f"### Strategy Principles\n{principles_text}\n\n"
            f"### Analysis Dimensions\n{dimensions_text}\n\n"
            f"### Action Framework\n{action_text}"
        )

    def to_markdown_block(self) -> str:
        """Render blueprint as markdown section for template fallback report."""
        dims = "\n".join([f"- **{dim.name}**: {dim.objective}" for dim in self.dimensions])
        section_title = "### VI. Strategy Framework"
        return f"{section_title}\n{dims}\n"


US_BLUEPRINT = MarketStrategyBlueprint(
    region="us",
    title="US Market Regime Strategy",
    positioning="Focus on index trend, macro narrative, and sector rotation to define next-session risk posture.",
    principles=[
        "Read market regime from S&P 500, Nasdaq, and Dow alignment first.",
        "Separate beta move from theme-driven alpha rotation.",
        "Translate recap into actionable risk-on/risk-off stance with clear invalidation points.",
    ],
    dimensions=[
        StrategyDimension(
            name="Trend Regime",
            objective="Classify the market as momentum, range, or risk-off.",
            checkpoints=[
                "Are SPX/NDX/DJI directionally aligned",
                "Did volume confirm the move",
                "Are key index levels reclaimed or lost",
            ],
        ),
        StrategyDimension(
            name="Macro & Flows",
            objective="Map policy/rates narrative into equity risk appetite.",
            checkpoints=[
                "Treasury yield and USD implications",
                "Breadth and leadership concentration",
                "Defensive vs growth factor rotation",
            ],
        ),
        StrategyDimension(
            name="Sector Themes",
            objective="Identify persistent leaders and vulnerable laggards.",
            checkpoints=[
                "AI/semiconductor/software trend persistence",
                "Energy/financials sensitivity to macro data",
                "Volatility signals from VIX and large-cap earnings",
            ],
        ),
    ],
    action_framework=[
        "Risk-on: broad index breakout with expanding participation.",
        "Neutral: mixed index signals; focus on selective relative strength.",
        "Risk-off: failed breakouts and rising volatility; prioritize capital preservation.",
    ],
)

CA_BLUEPRINT = MarketStrategyBlueprint(
    region="ca",
    title="Canadian Market Regime Strategy",
    positioning="Focus on S&P/TSX trend, the commodity and rates narrative, and sector rotation to define next-session risk posture.",
    principles=[
        "Read market regime from the S&P/TSX Composite first, then the TSX Venture Composite for risk appetite at the small-cap end.",
        "Separate commodity-driven moves (energy and materials) from financials and technology rotation.",
        "Translate recap into actionable risk-on/risk-off stance with clear invalidation points.",
    ],
    dimensions=[
        StrategyDimension(
            name="Trend Regime",
            objective="Classify the market as momentum, range, or risk-off.",
            checkpoints=[
                "Are the TSX Composite and TSX Venture directionally aligned",
                "Did volume confirm the move",
                "Are key index levels reclaimed or lost",
            ],
        ),
        StrategyDimension(
            name="Macro & Commodities",
            objective="Map Bank of Canada policy, rates and commodity prices into equity risk appetite.",
            checkpoints=[
                "Bank of Canada and Government of Canada yield implications",
                "USD/CAD and crude oil, natural gas and gold moves",
                "Concentration of leadership in financials, energy and materials",
            ],
        ),
        StrategyDimension(
            name="Sector Themes",
            objective="Identify persistent leaders and vulnerable laggards.",
            checkpoints=[
                "Banks and insurers' sensitivity to rates and credit",
                "Energy and pipeline earnings against oil and gas prices",
                "Gold and base-metal miners against metal prices and USD strength",
            ],
        ),
    ],
    action_framework=[
        "Risk-on: broad index breakout with expanding participation and supportive commodity prices.",
        "Neutral: mixed index signals; focus on selective relative strength.",
        "Risk-off: failed breakouts and falling commodity prices or rising volatility; prioritize capital preservation.",
    ],
)

HK_BLUEPRINT = MarketStrategyBlueprint(
    region="hk",
    title="Hong Kong Market Regime Strategy",
    positioning="Focus on HSI trend, southbound flow dynamics, and sector rotation to define next-session risk posture.",
    principles=[
        "Read market regime from HSI, HSTECH, and HSCEI alignment first.",
        "Track southbound capital flow as a key sentiment driver.",
        "Translate recap into actionable risk-on/risk-off stance with clear invalidation points.",
    ],
    dimensions=[
        StrategyDimension(
            name="Trend Regime",
            objective="Classify the market as momentum, range, or risk-off.",
            checkpoints=[
                "Are HSI/HSTECH/HSCEI directionally aligned",
                "Did volume confirm the move",
                "Are key index levels reclaimed or lost",
            ],
        ),
        StrategyDimension(
            name="Capital Flows",
            objective="Map southbound flow and macro narrative into equity risk appetite.",
            checkpoints=[
                "Southbound net flow direction and magnitude",
                "USD/HKD and China policy implications",
                "Breadth and leadership concentration",
            ],
        ),
        StrategyDimension(
            name="Sector Themes",
            objective="Identify persistent leaders and vulnerable laggards.",
            checkpoints=[
                "Tech/internet platform trend persistence",
                "Financials/property sensitivity to policy shifts",
                "Defensive vs growth factor rotation",
            ],
        ),
    ],
    action_framework=[
        "Risk-on: broad index breakout with expanding southbound participation.",
        "Neutral: mixed index signals; focus on selective relative strength.",
        "Risk-off: failed breakouts and rising volatility; prioritize capital preservation.",
    ],
)


def get_market_strategy_blueprint(region: str) -> MarketStrategyBlueprint:
    """Return strategy blueprint by market region."""
    if region == "us":
        return US_BLUEPRINT
    if region == "hk":
        return HK_BLUEPRINT
    if region == "ca":
        return CA_BLUEPRINT
    return US_BLUEPRINT
