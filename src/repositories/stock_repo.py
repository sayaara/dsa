# -*- coding: utf-8 -*-
"""
===================================
Stock data repository layer
===================================

Responsibilities:
1. Encapsulate database operations for stock data
2. Provide the daily-bar query interface
"""

import logging
from datetime import date
from typing import Optional, List, Dict, Any

import pandas as pd
from sqlalchemy import and_, desc, select

from src.storage import DatabaseManager, StockDaily

logger = logging.getLogger(__name__)


class StockRepository:
    """
    Stock data repository layer

    Encapsulates database operations on the StockDaily table
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        Initialize the repository layer

        Args:
            db_manager: the database manager (optional; defaults to the singleton)
        """
        self.db = db_manager or DatabaseManager.get_instance()

    def get_latest(self, code: str, days: int = 2) -> List[StockDaily]:
        """
        Get data for the most recent N days

        Args:
            code: the stock code
            days: number of days to fetch

        Returns:
            A list of StockDaily objects (descending by date)
        """
        try:
            return self.db.get_latest_data(code, days)
        except Exception as e:
            logger.error(f"Failed to get the latest data: {e}")
            return []

    def get_range(
        self,
        code: str,
        start_date: date,
        end_date: date
    ) -> List[StockDaily]:
        """
        Get data for the given date range

        Args:
            code: the stock code
            start_date: the start date
            end_date: the end date

        Returns:
            A list of StockDaily objects
        """
        try:
            return self.db.get_data_range(code, start_date, end_date)
        except Exception as e:
            logger.error(f"Failed to get data for the date range: {e}")
            return []

    def save_dataframe(
        self,
        df: pd.DataFrame,
        code: str,
        data_source: str = "Unknown"
    ) -> int:
        """
        Save a DataFrame to the database

        Args:
            df: a DataFrame holding daily-bar data
            code: the stock code
            data_source: the data source

        Returns:
            The number of records saved
        """
        try:
            return self.db.save_daily_data(df, code, data_source)
        except Exception as e:
            logger.error(f"Failed to save daily bar data: {e}")
            return 0

    def has_today_data(self, code: str, target_date: Optional[date] = None) -> bool:
        """
        Check whether data exists for the given date

        Args:
            code: the stock code
            target_date: the target date (defaults to today)

        Returns:
            Whether data exists
        """
        try:
            return self.db.has_today_data(code, target_date)
        except Exception as e:
            logger.error(f"Failed to check whether the data exists: {e}")
            return False

    def get_analysis_context(
        self,
        code: str,
        target_date: Optional[date] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the analysis context

        Args:
            code: the stock code
            target_date: the target date

        Returns:
            The analysis context dictionary
        """
        try:
            return self.db.get_analysis_context(code, target_date)
        except Exception as e:
            logger.error(f"Failed to get the analysis context: {e}")
            return None

    def get_start_daily(self, *, code: str, analysis_date: date) -> Optional[StockDaily]:
        """Return StockDaily for analysis_date (preferred) or nearest previous date."""
        with self.db.get_session() as session:
            row = session.execute(
                select(StockDaily)
                .where(and_(StockDaily.code == code, StockDaily.date <= analysis_date))
                .order_by(desc(StockDaily.date))
                .limit(1)
            ).scalar_one_or_none()
            return row

    def get_daily_on_date(self, *, code: str, target_date: date) -> Optional[StockDaily]:
        """Return StockDaily for the exact target_date without trading-day fallback."""
        with self.db.get_session() as session:
            row = session.execute(
                select(StockDaily)
                .where(and_(StockDaily.code == code, StockDaily.date == target_date))
                .limit(1)
            ).scalar_one_or_none()
            return row

    def get_forward_bars(self, *, code: str, analysis_date: date, eval_window_days: int) -> List[StockDaily]:
        """Return forward daily bars after analysis_date, up to eval_window_days."""
        with self.db.get_session() as session:
            rows = session.execute(
                select(StockDaily)
                .where(and_(StockDaily.code == code, StockDaily.date > analysis_date))
                .order_by(StockDaily.date)
                .limit(eval_window_days)
            ).scalars().all()
            return list(rows)
