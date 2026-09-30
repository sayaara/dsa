# -*- coding: utf-8 -*-
"""
===================================
Batch analysis command
===================================

Analyzes every stock in the watchlist.
"""

import logging
import threading
import uuid
from typing import List

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class BatchCommand(BotCommand):
    """
    Batch analysis command
    
    Analyzes the configured watchlist in bulk and generates a summary report.
    
    Usage:
        /batch      - analyze the whole watchlist
        /batch 3    - analyze only the first 3
    """
    
    @property
    def name(self) -> str:
        return "batch"
    
    @property
    def aliases(self) -> List[str]:
        return ["b", "批量", "全部"]
    
    @property
    def description(self) -> str:
        return "Analyze the watchlist in batch"
    
    @property
    def usage(self) -> str:
        return "/batch [count]"
    
    @property
    def admin_only(self) -> bool:
        """Batch analysis requires administrator permission (to prevent abuse)"""
        return False  # Set to True if required
    
    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """Run the batch analysis command"""
        from src.config import get_config
        
        config = get_config()
        config.refresh_stock_list()
        
        stock_list = config.stock_list
        
        if not stock_list:
            return BotResponse.error_response(
                "The watchlist is empty. Configure STOCK_LIST first"
            )
        
        # Parse the count argument
        limit = None
        if args:
            try:
                limit = int(args[0])
                if limit <= 0:
                    return BotResponse.error_response("Count must be greater than 0")
            except ValueError:
                return BotResponse.error_response(f"Invalid count: {args[0]}")
        
        # Cap the number analyzed
        if limit:
            stock_list = stock_list[:limit]
        
        logger.info(f"[BatchCommand] 开始批量分析 {len(stock_list)} 只股票")
        
        # Run the analysis on a background thread
        thread = threading.Thread(
            target=self._run_batch_analysis,
            args=(stock_list, message),
            daemon=True
        )
        thread.start()
        
        return BotResponse.markdown_response(
            f"✅ **Batch analysis started**\n\n"
            f"• Count: {len(stock_list)}\n"
            f"• Stocks: {', '.join(stock_list[:5])}"
            f"{'...' if len(stock_list) > 5 else ''}\n\n"
            f"A summary report will be pushed automatically when the analysis finishes."
        )
    
    def _run_batch_analysis(self, stock_list: List[str], message: BotMessage) -> None:
        """Run the batch analysis in the background"""
        try:
            from src.config import get_config
            from main import StockAnalysisPipeline
            
            config = get_config()
            
            # Create the analysis pipeline
            pipeline = StockAnalysisPipeline(
                config=config,
                source_message=message,
                query_id=uuid.uuid4().hex,
                query_source="bot"
            )
            
            # Run the analysis (the summary report is pushed automatically)
            results = pipeline.run(
                stock_codes=stock_list,
                dry_run=False,
                send_notification=True
            )
            
            logger.info(f"[BatchCommand] 批量分析完成，成功 {len(results)} 只")
            
        except Exception as e:
            logger.error(f"[BatchCommand] 批量分析失败: {e}")
            logger.exception(e)
