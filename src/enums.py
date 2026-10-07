# -*- coding: utf-8 -*-
"""
===================================
Enumeration type definitions
===================================

Centralises the enumerations the system uses, for type safety and readability.
"""

from enum import Enum


class ReportType(str, Enum):
    """
    Report type enumeration

    Selects the report format pushed when an analysis is triggered through the API.
    Inheriting from str lets members compare and serialise as plain strings.
    """
    SIMPLE = "simple"  # concise report: uses generate_single_stock_report
    FULL = "full"      # full report: uses generate_dashboard_report
    BRIEF = "brief"    # brief mode: a 3-5 sentence summary, suited to mobile and push

    @classmethod
    def from_str(cls, value: str) -> "ReportType":
        """
        Convert a string into an enum member safely

        Args:
            value: the string value

        Returns:
            The matching enum member, or the default SIMPLE for invalid input
        """
        try:
            normalized = value.lower().strip()
            if normalized == "detailed":
                normalized = cls.FULL.value
            return cls(normalized)
        except (ValueError, AttributeError):
            return cls.SIMPLE

    @property
    def display_name(self) -> str:
        """Return the display name"""
        return {
            ReportType.SIMPLE: "Simple report",
            ReportType.FULL: "Full report",
            ReportType.BRIEF: "Brief report",
        }.get(self, "Simple report")
