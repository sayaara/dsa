# -*- coding: utf-8 -*-
"""
===================================
Analysis history repository layer
===================================

Responsibilities:
1. Encapsulate database operations for analysis history data
2. Provide the CRUD interface
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from src.storage import DatabaseManager, AnalysisHistory

logger = logging.getLogger(__name__)


class AnalysisRepository:
    """
    Analysis history repository layer
    
    Encapsulates database operations on the AnalysisHistory table
    """
    
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        Initialize the repository layer
        
        Args:
            db_manager: the database manager (optional; defaults to the singleton)
        """
        self.db = db_manager or DatabaseManager.get_instance()
    
    def get_by_query_id(self, query_id: str) -> Optional[AnalysisHistory]:
        """
        Get an analysis record by query_id
        
        Args:
            query_id: the query ID
            
        Returns:
            The AnalysisHistory object, or None when it does not exist
        """
        try:
            records = self.db.get_analysis_history(query_id=query_id, limit=1)
            return records[0] if records else None
        except Exception as e:
            logger.error(f"查询分析记录失败: {e}")
            return None
    
    def get_list(
        self,
        code: Optional[str] = None,
        days: int = 30,
        limit: int = 50
    ) -> List[AnalysisHistory]:
        """
        Get a list of analysis records
        
        Args:
            code: filter by stock code
            days: the time window in days
            limit: maximum number of items to return
            
        Returns:
            A list of AnalysisHistory objects
        """
        try:
            return self.db.get_analysis_history(
                code=code,
                days=days,
                limit=limit
            )
        except Exception as e:
            logger.error(f"获取分析列表失败: {e}")
            return []
    
    def save(
        self,
        result: Any,
        query_id: str,
        report_type: str,
        news_content: Optional[str] = None,
        context_snapshot: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Save an analysis result
        
        Args:
            result: the analysis result object
            query_id: the query ID
            report_type: the report type
            news_content: the news content
            context_snapshot: the context snapshot
            
        Returns:
            The newly saved AnalysisHistory.id; returns 0 when the save fails.
        """
        try:
            return self.db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type=report_type,
                news_content=news_content,
                context_snapshot=context_snapshot
            )
        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")
            return 0
    
    def count_by_code(self, code: str, days: int = 30) -> int:
        """
        Count analysis records for the given stock
        
        Args:
            code: the stock code
            days: the time window in days
            
        Returns:
            The record count
        """
        try:
            records = self.db.get_analysis_history(code=code, days=days, limit=1000)
            return len(records)
        except Exception as e:
            logger.error(f"统计分析记录失败: {e}")
            return 0
