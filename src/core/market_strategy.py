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
        section_title = "### VI. Strategy Framework" if self.region in ("us", "ca") else "### 六、策略框架"
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
    title="港股市场三段式复盘策略",
    positioning="聚焦恒生指数趋势、南向资金博弈与板块轮动，形成次日交易计划。",
    principles=[
        "先看恒指/恒科/国企指数方向，再看南向资金情绪，最后看板块持续性。",
        "结论必须映射到仓位、节奏与风险控制动作。",
        "判断使用当日数据与近3日新闻，不臆测未验证信息。",
    ],
    dimensions=[
        StrategyDimension(
            name="趋势结构",
            objective="判断市场处于上升、震荡还是防守阶段。",
            checkpoints=["恒指/恒科/国企指数是否同向", "放量上涨或缩量下跌是否成立", "关键支撑阻力是否被突破"],
        ),
        StrategyDimension(
            name="资金情绪",
            objective="识别南向资金风险偏好与情绪温度。",
            checkpoints=["南向资金净流入方向与规模", "港元汇率与内地政策含义", "市场广度与龙头集中度"],
        ),
        StrategyDimension(
            name="主线板块",
            objective="提炼可交易主线与规避方向。",
            checkpoints=["科技/互联网平台趋势持续性", "金融/地产对政策转向的敏感度", "防御与成长因子轮动"],
        ),
    ],
    action_framework=[
        "进攻：恒指共振上行 + 南向资金持续流入 + 主线强化。",
        "均衡：指数分化或缩量震荡，控制仓位并等待确认。",
        "防守：指数转弱 + 波动率上升，优先风控与减仓。",
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
