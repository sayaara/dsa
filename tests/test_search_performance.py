# -*- coding: utf-8 -*-
"""
===================================
Search Algorithm Performance Tests
===================================

Benchmarks the name-to-code resolution engine under load.
"""

import time
import pytest
from src.services.name_to_code_resolver import resolve_name_to_code


class TestSearchPerformance:
    """Benchmark tests for stock search resolution."""

    @pytest.mark.benchmark
    def test_resolve_name_to_code_fast_path_throughput(self):
        """Benchmark the common fast paths without typo/fuzzy fallbacks dominating runtime."""
        inputs = [
            "600519", "00700", "AAPL", "TSLA",
            "贵州茅台", "腾讯控股", "阿里巴巴",
            "aaaaaaa", "1234567",
        ]

        # Warm caches/import paths before timing.
        for s in inputs:
            resolve_name_to_code(s)

        start_time = time.time()
        iterations = 30
        for _ in range(iterations):
            for s in inputs:
                resolve_name_to_code(s)

        duration = time.time() - start_time
        avg_ms = (duration / (iterations * len(inputs))) * 1000

        print(f"\nAverage fast-path resolution time: {avg_ms:.2f}ms")
        assert avg_ms < 20, f"Fast-path resolution too slow: {avg_ms:.2f}ms"
