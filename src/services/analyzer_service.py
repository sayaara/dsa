# -*- coding: utf-8 -*-
"""
===================================
Stock watchlist intelligence system - analysis service layer
===================================

Responsibilities:
1. Encapsulate the core analysis logic for multiple callers (CLI, WebUI, Bot)
2. Provide a clear API that does not depend on command-line arguments
3. Support dependency injection for easier testing and extension
4. Manage the analysis flow and configuration in one place
"""

import uuid
from typing import List, Optional

from src.analyzer import AnalysisResult
from src.core.market_review import run_market_review
from src.core.pipeline import StockAnalysisPipeline
from src.config import Config, get_config
from src.enums import ReportType
from src.notification import NotificationService


def analyze_stock(
    stock_code: str,
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
) -> Optional[AnalysisResult]:
    """
    Analyze a single stock

    Args:
        stock_code: the stock code
        config: the configuration object (optional; defaults to the singleton)
        full_report: whether to generate the full report
        notifier: the notification service (optional)

    Returns:
        The analysis result object
    """
    if config is None:
        config = get_config()

    # Create the analysis pipeline
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )

    # Use the notification service when one is provided
    if notifier:
        pipeline.notifier = notifier

    # Set the report type from the full_report argument
    report_type = ReportType.FULL if full_report else ReportType.SIMPLE

    # Run the single-stock analysis
    result = pipeline.process_single_stock(
        code=stock_code,
        skip_analysis=False,
        single_stock_notify=notifier is not None,
        report_type=report_type,
    )

    return result


def analyze_stocks(
    stock_codes: List[str],
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
) -> List[AnalysisResult]:
    """
    Analyze multiple stocks

    Args:
        stock_codes: the list of stock codes
        config: the configuration object (optional; defaults to the singleton)
        full_report: whether to generate the full report
        notifier: the notification service (optional)

    Returns:
        The list of analysis results
    """
    if config is None:
        config = get_config()

    results = []
    for stock_code in stock_codes:
        result = analyze_stock(stock_code, config, full_report, notifier)
        if result:
            results.append(result)

    return results


def perform_market_review(
    config: Config = None,
    notifier: Optional[NotificationService] = None,
) -> Optional[str]:
    """
    Run the broad-market review

    Args:
        config: the configuration object (optional; defaults to the singleton)
        notifier: the notification service (optional)

    Returns:
        The review report content
    """
    if config is None:
        config = get_config()

    # Create the analysis pipeline to obtain the analyzer and search_service
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli",
    )

    # Use the provided notification service, or create a new one
    review_notifier = notifier or pipeline.notifier

    # Call the broad-market review function
    return run_market_review(
        notifier=review_notifier,
        analyzer=pipeline.analyzer,
        search_service=pipeline.search_service,
        config=config,
        trigger_source="service",
    )
