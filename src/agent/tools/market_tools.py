# -*- coding: utf-8 -*-
"""
Market tools — wraps DataFetcherManager market-level methods as agent tools.

Tools:
- get_market_indices: major market index data
"""

import logging

from src.agent.tools.registry import ToolParameter, ToolDefinition, ToolPolicy

logger = logging.getLogger(__name__)

_MARKET_READ_POLICY = ToolPolicy.declared(
    read_only=True,
    side_effects=["network_read"],
    permissions=["market_data:read"],
)


def _get_fetcher_manager():
    """Lazy import to avoid circular deps."""
    from data_provider import DataFetcherManager
    return DataFetcherManager()


# ============================================================
# get_market_indices
# ============================================================

def _handle_get_market_indices(region: str = "cn") -> dict:
    """Get major market indices."""
    manager = _get_fetcher_manager()
    indices = manager.get_main_indices(region=region)

    if not indices:
        return {"error": f"No market index data available for region '{region}'"}

    return {
        "region": region,
        "indices_count": len(indices),
        "indices": indices,
    }


get_market_indices_tool = ToolDefinition(
    name="get_market_indices",
    description="Get major market indices (S&P 500, Nasdaq, Dow for US; Hang Seng for "
                "Hong Kong). Provides market overview.",
    parameters=[
        ToolParameter(
            name="region",
            type="string",
            description="Market region: 'hk' for Hong Kong, 'us' for US stocks (default: 'us')",
            required=False,
            default="us",
            enum=["hk", "us"],
        ),
    ],
    handler=_handle_get_market_indices,
    category="market",
    policy=_MARKET_READ_POLICY,
)


ALL_MARKET_TOOLS = [
    get_market_indices_tool,
]
