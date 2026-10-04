# -*- coding: utf-8 -*-
"""An empty news dimension must be stated plainly in the report.

Background: the news section used to render only when it had content, so a search that
returned nothing made the whole section vanish and the reader could not tell genuine
absence from a silent failure (a rate-limited source, no configured channel). That
presents a fetch failure as "there was no news", which misleads far more than slowness.

These cases pin three states:
1. No search ran (count is None): say the channel is unconfigured and no news evidence was used;
2. A search ran and matched nothing (count == 0): keep the existing zero-hit notice;
3. News was found (count > 0): no missing-data notice appears.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.notification import NotificationService


ZERO_HIT_DISCLOSURE = "⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。"
NO_CHANNEL_DISCLOSURE = "⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。"
EN_ZERO_HIT_DISCLOSURE = (
    "⚠️ No news data could be retrieved for this run; "
    "the conclusions below do not incorporate news-based evidence."
)
EN_NO_CHANNEL_DISCLOSURE = (
    "⚠️ No news search channel is configured; "
    "this analysis does not incorporate news-based evidence."
)
KO_ZERO_HIT_DISCLOSURE = (
    "⚠️ 이번 분석에서 사용 가능한 뉴스 데이터를 가져오지 못해 "
    "아래 결론에는 뉴스 근거를 반영하지 않았습니다."
)
KO_NO_CHANNEL_DISCLOSURE = (
    "⚠️ 뉴스 검색 채널이 설정되지 않아 이번 분석에는 "
    "뉴스 근거를 반영하지 않았습니다."
)


def _make_result(
    *,
    news_summary="",
    news_result_count=None,
    report_language="zh",
    news_evidence_present=False,
):
    """Build a minimal renderable analysis result.

    Only the fields the daily report needs are filled, so nothing irrelevant couples to the behaviour under test.
    """
    from src.analyzer import AnalysisResult

    return AnalysisResult(
        code="600519",
        name="测试标的",
        sentiment_score=50,
        trend_prediction="震荡",
        operation_advice="观望",
        analysis_summary="用于测试的综合分析。",
        report_language=report_language,
        news_summary=news_summary,
        news_result_count=news_result_count,
        news_evidence_present=news_evidence_present,
        success=True,
    )


def _make_service():
    """Build a NotificationService for rendering.

    The real __init__ runs so every rendering attribute exists; this test only reads the returned
    report text and calls no push method, so nothing is sent anywhere.
    """
    return NotificationService()


class EmptyNewsDisclosureTestCase(unittest.TestCase):
    def setUp(self):
        self.service = _make_service()

    def _render(self, result):
        return NotificationService.generate_daily_report(
            self.service, [result], report_date="2026-08-18"
        )

    def test_discloses_when_search_ran_but_returned_nothing(self):
        """A search ran and matched nothing: the report must say so."""
        report = self._render(_make_result(news_result_count=0))

        self.assertIn(ZERO_HIT_DISCLOSURE, report)
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertIn("消息面", report)

    def test_discloses_when_search_was_not_performed(self):
        """With no search channel configured, the report must state that no news evidence was used."""
        report = self._render(_make_result(news_result_count=None))

        self.assertIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)

    def test_unchanged_when_news_is_available(self):
        """With news present, the behaviour matches the old one: the body renders and no notice appears."""
        report = self._render(
            _make_result(news_summary="公司发布季度财报，营收同比增长。", news_result_count=3)
        )

        self.assertIn("公司发布季度财报", report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)

    def test_disclosure_states_the_consequence_not_just_the_absence(self):
        """The notice must spell out the consequence, so the reader knows how much to discount the conclusion, not just that data is missing."""
        report = self._render(_make_result(news_result_count=0))

        self.assertIn("未纳入新闻维度证据", report)


class ResultFieldContractTestCase(unittest.TestCase):
    def test_result_defaults_to_none_not_zero(self):
        """The default must be None, so it can be disclosed differently from a zero-hit search."""
        result = _make_result()

        self.assertIsNone(result.news_result_count)


class ActiveRenderersDiscloseTestCase(unittest.TestCase):
    """The real flow goes through dashboard / brief / single_stock, not generate_daily_report.

    Adding the notice only in generate_daily_report would cover no standard REPORT_TYPE at all.
    These cases pin all four renderers onto the same shared decision.
    """

    def setUp(self):
        self.service = _make_service()

    def test_dashboard_report_discloses_empty_news(self):
        report = NotificationService.generate_dashboard_report(
            self.service, [_make_result(news_result_count=0)], report_date="2026-08-18"
        )

        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_brief_report_discloses_empty_news(self):
        report = NotificationService.generate_brief_report(
            self.service, [_make_result(news_result_count=0)], report_date="2026-08-18"
        )

        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_single_stock_report_discloses_empty_news(self):
        report = NotificationService.generate_single_stock_report(
            self.service, _make_result(news_result_count=0)
        )

        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_renderers_disclose_when_search_not_performed(self):
        for name, call in (
            ("dashboard", lambda r: NotificationService.generate_dashboard_report(
                self.service, [r], report_date="2026-08-18")),
            ("brief", lambda r: NotificationService.generate_brief_report(
                self.service, [r], report_date="2026-08-18")),
            ("single", lambda r: NotificationService.generate_single_stock_report(
                self.service, r)),
        ):
            with self.subTest(renderer=name):
                report = call(_make_result(news_result_count=None))
                self.assertIn(NO_CHANNEL_DISCLOSURE, report)
                self.assertNotIn(ZERO_HIT_DISCLOSURE, report)


class DisclosureIndependentOfModelTextTestCase(unittest.TestCase):
    """The worst combination: the search matched nothing, yet the model still wrote a sentiment call per the schema.

    Deciding from "is the news text empty" would then show the model's sentiment while hiding
    that there was no news evidence. The decision must be independent of the model output.
    """

    def setUp(self):
        self.service = _make_service()

    def test_warns_even_when_model_supplied_sentiment(self):
        result = _make_result(news_result_count=0)
        result.market_sentiment = "市场情绪偏中性。"
        result.hot_topics = "暂无明显热点。"

        report = NotificationService.generate_daily_report(
            self.service, [result], report_date="2026-08-18"
        )

        self.assertIn(ZERO_HIT_DISCLOSURE, report)
        self.assertIn("市场情绪偏中性", report)


class TemplateRendererDiscloseTestCase(unittest.TestCase):
    """With REPORT_RENDERER_ENABLED=true the template path runs and returns early at render().

    Only the string-concatenation branch used to be fixed, so the template path stayed silent - one
    analysis disclosed on some channels and not on others, an inconsistent presentation of the facts.
    """

    def setUp(self):
        self.service = _make_service()

    def _render_with_templates(self, method, result, platform_hint=""):
        from unittest.mock import patch
        from src.config import get_config

        cfg = get_config()
        with patch.object(type(cfg), "report_renderer_enabled", True, create=True):
            return method(self.service, [result], report_date="2026-08-18")

    def test_markdown_template_discloses_empty_news(self):
        from src.services.report_renderer import render

        out = render(
            platform="markdown",
            results=[_make_result(news_result_count=0)],
            report_date="2026-08-18",
            summary_only=False,
            extra_context={"report_language": "zh"},
        )
        self.assertTrue(out)
        self.assertIn(ZERO_HIT_DISCLOSURE, out)

    def test_brief_template_discloses_empty_news(self):
        from src.services.report_renderer import render

        out = render(
            platform="brief",
            results=[_make_result(news_result_count=0)],
            report_date="2026-08-18",
            summary_only=False,
            extra_context={"report_language": "zh"},
        )
        self.assertTrue(out)
        self.assertIn(ZERO_HIT_DISCLOSURE, out)

    def test_templates_disclose_when_search_not_performed(self):
        from src.services.report_renderer import render

        for platform in ("markdown", "brief"):
            with self.subTest(platform=platform):
                out = render(
                    platform=platform,
                    results=[_make_result(news_result_count=None)],
                    report_date="2026-08-18",
                    summary_only=False,
                    extra_context={"report_language": "zh"},
                )
                self.assertIn(NO_CHANNEL_DISCLOSURE, out or "")
                self.assertNotIn(ZERO_HIT_DISCLOSURE, out or "")


class NoSearchProviderDisclosureTestCase(unittest.TestCase):
    """Pins the #2225 fresh-clone case: with no key, public instances stay off by default."""

    def test_no_registered_providers_discloses_missing_news_evidence(self):
        from src.search_service import SearchService

        search_service = SearchService(searxng_public_instances_enabled=False)
        self.assertEqual([], search_service._providers)
        self.assertFalse(search_service.is_available)

        report = NotificationService.generate_daily_report(
            _make_service(), [_make_result(news_result_count=None)], report_date="2026-08-18"
        )
        self.assertIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)


class SupportedLanguageDisclosureTestCase(unittest.TestCase):
    """Every supported report language must be mapped explicitly; an unknown language must not default to Chinese."""

    EXPECTED = {
        "zh": (NO_CHANNEL_DISCLOSURE, ZERO_HIT_DISCLOSURE),
        "en": (EN_NO_CHANNEL_DISCLOSURE, EN_ZERO_HIT_DISCLOSURE),
        "ko": (KO_NO_CHANNEL_DISCLOSURE, KO_ZERO_HIT_DISCLOSURE),
    }

    def setUp(self):
        self.service = _make_service()

    def _string_renderers(self, result):
        return {
            "daily": NotificationService.generate_daily_report(
                self.service, [result], report_date="2026-08-18"
            ),
            "dashboard": NotificationService.generate_dashboard_report(
                self.service, [result], report_date="2026-08-18"
            ),
            "brief": NotificationService.generate_brief_report(
                self.service, [result], report_date="2026-08-18"
            ),
            "single": NotificationService.generate_single_stock_report(
                self.service, result
            ),
        }

    def test_every_supported_language_is_used_by_string_renderers(self):
        from src.report_language import SUPPORTED_REPORT_LANGUAGES

        self.assertEqual(set(SUPPORTED_REPORT_LANGUAGES), set(self.EXPECTED))
        for language in SUPPORTED_REPORT_LANGUAGES:
            for count, expected_index in ((None, 0), (0, 1)):
                expected = self.EXPECTED[language][expected_index]
                result = _make_result(
                    news_result_count=count,
                    report_language=language,
                )
                for renderer, report in self._string_renderers(result).items():
                    with self.subTest(
                        language=language,
                        count=count,
                        renderer=renderer,
                    ):
                        self.assertIn(expected, report)
                        if language != "zh":
                            self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)
                            self.assertNotIn(ZERO_HIT_DISCLOSURE, report)

    def test_every_supported_language_is_used_by_templates(self):
        from src.report_language import SUPPORTED_REPORT_LANGUAGES
        from src.services.report_renderer import render

        for language in SUPPORTED_REPORT_LANGUAGES:
            result = _make_result(news_result_count=0, report_language=language)
            for platform in ("markdown", "brief"):
                for summary_only in (False, True):
                    with self.subTest(
                        language=language,
                        platform=platform,
                        summary_only=summary_only,
                    ):
                        out = render(
                            platform=platform,
                            results=[result],
                            report_date="2026-08-18",
                            summary_only=summary_only,
                            extra_context={"report_language": language},
                        )
                        self.assertIn(self.EXPECTED[language][1], out or "")
                        if language != "zh":
                            self.assertNotIn(ZERO_HIT_DISCLOSURE, out or "")

    def test_summary_only_string_renderers_keep_disclosure(self):
        self.service._report_summary_only = True
        result = _make_result(news_result_count=0)

        for renderer, report in (
            (
                "daily",
                NotificationService.generate_daily_report(
                    self.service, [result], report_date="2026-08-18"
                ),
            ),
            (
                "dashboard",
                NotificationService.generate_dashboard_report(
                    self.service, [result], report_date="2026-08-18"
                ),
            ),
        ):
            with self.subTest(renderer=renderer):
                self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_unknown_language_fails_loudly(self):
        from src.services.empty_news import empty_news_disclosure

        with self.assertRaisesRegex(ValueError, "Unsupported report language"):
            empty_news_disclosure(_make_result(news_result_count=0), "future-language")


class PipelineCountSemanticsTestCase(unittest.TestCase):
    """The three-state count semantics must be produced correctly in the pipeline, or no amount of care in the display layer helps.

    Two gaps that once existed:
    1. When the search service failed outright (empty intel_results) the count stayed None,
       so the case that most needed a notice - every search source down - produced none;
    2. Agent mode (_analyze_with_agent) searched on its own but never recorded a count,
       so a zero hit on that path was always silent.
    """

    def _read_pipeline_source(self):
        from pathlib import Path

        return (Path(__file__).resolve().parents[1] / "src" / "core" / "pipeline.py").read_text(
            encoding="utf-8"
        )

    def test_count_set_to_zero_once_search_is_attempted(self):
        """The count is set to 0 the moment a search starts, not once a result object arrives."""
        src = self._read_pipeline_source()
        idx = src.index("starting multi-dimensional intelligence search")
        window = src[idx : idx + 800]

        self.assertIn("news_result_count = 0", window)
        self.assertLess(
            window.index("news_result_count = 0"),
            window.index("search_comprehensive_intel"),
            "计数必须在发起检索之前置 0，否则整体失败时会落回 None",
        )

    def test_post_hoc_persistence_query_does_not_write_the_count(self):
        """The post-analysis follow-up query only persists intelligence and must never write the count back.

        It runs after executor.run() and is unrelated to the evidence the Agent actually consumed; using it
        for the disclosure distorts in both directions (review OR-COR-5f5d7a2e). The real count comes from
        the evidence scope in src/agent/news_evidence.py.
        """
        src = self._read_pipeline_source()
        idx = src.index("Agent mode: saved")
        window = src[max(0, idx - 1200) : idx]
        # Code only: the comment explaining this constraint itself contains the identifier.
        code_only = "\n".join(
            line for line in window.splitlines() if not line.strip().startswith("#")
        )

        self.assertNotIn("result.news_result_count", code_only)


class _StubSearchResult:
    def __init__(self, index):
        self.title = f"标题{index}"
        self.snippet = f"摘要{index}"
        self.url = f"https://example.invalid/{index}"
        self.source = "stub"
        self.published_date = "2026-08-20"


class _StubSearchResponse:
    def __init__(self, count, *, success=True, query="stub-query"):
        self.success = success
        self.results = [_StubSearchResult(i) for i in range(count)]
        self.query = query
        self.provider = "stub"
        self.error_message = None if success else "stub failure"


class _StubSearchService:
    """Implements only the interface the search tool actually uses.

    intel_counts is the evidence the Agent really obtained through search_comprehensive_intel, while
    news_count is the search_stock_news result the pipeline fires afterwards purely to persist --
    deliberately different, to prove the disclosure follows the former.
    """

    def __init__(self, *, intel_counts=None, news_count=0, news_success=True, available=True):
        self._intel_counts = intel_counts or {}
        self._news_count = news_count
        self._news_success = news_success
        self._available = available

    @property
    def is_available(self):
        return self._available

    def search_comprehensive_intel(self, stock_code, stock_name, max_searches=6):
        return {
            dimension: _StubSearchResponse(count)
            for dimension, count in self._intel_counts.items()
        }

    def format_intel_report(self, intel_results, stock_name):
        return "stub intel report"

    def search_stock_news(self, stock_code, stock_name, max_results=5):
        return _StubSearchResponse(self._news_count, success=self._news_success)


class AgentNewsEvidenceTestCase(unittest.TestCase):
    """The Agent-mode disclosure must follow the news evidence the Agent actually consumed.

    The gap that once existed (review OR-COR-5f5d7a2e): the count came from a search_stock_news()
    call fired after the analysis. The Agent could have used news through search_comprehensive_intel
    and still be labelled 「未纳入新闻面证据」 because that follow-up failed; conversely an Agent that
    found nothing could have the notice suppressed because the follow-up returned something.
    """

    def setUp(self):
        from src.agent import news_evidence

        self.news_evidence = news_evidence
        token = news_evidence.activate_news_evidence_scope()
        self.accumulator = news_evidence.get_current_news_evidence()
        self.addCleanup(news_evidence.reset_news_evidence_scope, token)

    def _install_service(self, service):
        from unittest.mock import patch

        patcher = patch(
            "src.agent.tools.search_tools._get_search_service", return_value=service
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        db_patcher = patch("src.agent.tools.search_tools._get_db")
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

    def test_agent_evidence_survives_a_failing_post_hoc_query(self):
        """The Agent used 6 news items and the follow-up matched nothing - it must not claim no news evidence."""
        from src.agent.tools.search_tools import _handle_search_comprehensive_intel

        service = _StubSearchService(
            intel_counts={"latest_news": 4, "risk_check": 2}, news_count=0
        )
        self._install_service(service)

        _handle_search_comprehensive_intel("600519", "测试标的")

        # The pipeline's post-hoc persistence query returns something entirely different and bypasses the evidence scope
        post_hoc = service.search_stock_news("600519", "测试标的", max_results=5)
        self.assertEqual(0, len(post_hoc.results))

        self.assertEqual(6, self.accumulator.resolve(search_available=True))

    def test_agent_zero_hit_is_not_masked_by_a_successful_post_hoc_query(self):
        """The other direction: the Agent found nothing and the follow-up did - the notice must not be suppressed."""
        from src.agent.tools.search_tools import _handle_search_comprehensive_intel

        service = _StubSearchService(
            intel_counts={"latest_news": 0}, news_count=5
        )
        self._install_service(service)

        _handle_search_comprehensive_intel("600519", "测试标的")

        post_hoc = service.search_stock_news("600519", "测试标的", max_results=5)
        self.assertEqual(5, len(post_hoc.results))

        self.assertEqual(0, self.accumulator.resolve(search_available=True))

    def test_failed_agent_search_records_zero_rather_than_nothing(self):
        """A search that started and failed is "searched and got nothing", not "no channel configured"."""
        from src.agent.tools.search_tools import _handle_search_stock_news

        service = _StubSearchService(news_count=0, news_success=False)
        self._install_service(service)

        _handle_search_stock_news("600519", "测试标的")

        self.assertEqual(0, self.accumulator.resolve(search_available=True))

    def test_unavailable_channel_resolves_to_not_configured(self):
        """When the channel is unavailable the tool returns an error and records nothing, so the count must be None."""
        from src.agent.tools.search_tools import _handle_search_stock_news

        service = _StubSearchService(available=False)
        self._install_service(service)

        _handle_search_stock_news("600519", "测试标的")

        self.assertIsNone(self.accumulator.resolve(search_available=False))

    def test_available_channel_never_searched_reports_zero_hit_not_missing_channel(self):
        """Channel available but the Agent never searched: still "no news found", never "no channel configured"."""
        self.assertEqual(0, self.accumulator.resolve(search_available=True))

    def test_tool_threads_accumulate_into_the_parent_scope(self):
        """The tool runs in a thread pool, so the accumulation must be visible to the pipeline.

        src/agent/runner.py submits tool calls with contextvars.copy_context() + pool.submit(ctx.run, ...).
        The ContextVar must hold a mutable accumulator object; an immutable value would be invisible to the parent thread.
        """
        import contextvars
        from concurrent.futures import ThreadPoolExecutor

        record = self.news_evidence.record_news_evidence
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = []
            for count in (2, 0, 5):
                ctx = contextvars.copy_context()
                futures.append(pool.submit(ctx.run, record, count))
            for future in futures:
                future.result()

        self.assertEqual(7, self.accumulator.resolve(search_available=True))

    def test_recording_outside_a_scope_is_ignored(self):
        """A follow-up news search on the report page must not affect this analysis's disclosure decision."""
        token = self.news_evidence.activate_news_evidence_scope()
        outer = self.news_evidence.get_current_news_evidence()
        self.news_evidence.reset_news_evidence_scope(token)

        self.news_evidence.record_news_evidence(99)

        self.assertEqual(0, outer.resolve(search_available=True))


class NewsEvidenceSourcesTestCase(unittest.TestCase):
    """The disclosure asserts whether the conclusion used news evidence, not how many hits a search got.

    `news_context` is assembled from three sources, and only the live search produces a count:

    1. Live multi-dimension search - updates news_result_count
    2. Social sentiment (US stocks) - no count update
    3. The locally persisted news pool - no count update

    Counting alone would misreport an analysis fed by the last two as 「未纳入新闻面证据」
    (review OR-COR-2e4b9d61 named the third source; the second is the same defect class and is pinned here too).
    """

    def _result(self, *, count, evidence):
        return _make_result(news_result_count=count, news_evidence_present=evidence)

    def test_local_intel_without_search_channel_is_not_reported_as_missing(self):
        """Once the local news pool feeds the analysis, no search channel is no excuse for claiming no news evidence."""
        report = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=None, evidence=True)],
            report_date="2026-08-20",
        )
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)

    def test_social_sentiment_without_search_hits_is_not_reported_as_missing(self):
        """Social sentiment also enters news_context, so a zero hit cannot deny the evidence used."""
        report = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=0, evidence=True)],
            report_date="2026-08-20",
        )
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)

    def test_no_evidence_at_all_still_discloses_with_the_right_reason(self):
        """With genuinely no evidence at all, the two original reason texts must be unchanged."""
        no_channel = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=None, evidence=False)],
            report_date="2026-08-20",
        )
        zero_hit = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=0, evidence=False)],
            report_date="2026-08-20",
        )
        self.assertIn(NO_CHANNEL_DISCLOSURE, no_channel)
        self.assertIn(ZERO_HIT_DISCLOSURE, zero_hit)

    def test_evidence_helper_registers_sources_one_by_one(self):
        from src.services.empty_news import news_evidence_present

        # Real hit count / social sentiment / local news pool - any one of them counts as evidence
        self.assertTrue(news_evidence_present(4, None, None))
        self.assertTrue(news_evidence_present(0, "reddit 讨论……", None))
        self.assertTrue(news_evidence_present(0, None, "## 本地资讯证据池"))
        self.assertFalse(news_evidence_present(0, None, None))
        self.assertFalse(news_evidence_present(0, "", "   \n\t "))
        self.assertFalse(news_evidence_present(None, None, None))

    def test_zero_hit_placeholder_report_is_not_mistaken_for_evidence(self):
        """On a zero hit format_intel_report still emits placeholder text, which must never count as evidence.

        This is a real counter-example (review OR-COR-8f4c2d1b): `format_intel_report()` emits the
        「【XX 情报搜索结果】」 heading and a 「未找到相关
        信息」 line per dimension even when every dimension fails, so the block is never empty. The old
        implementation passed the whole news_context into the decision, turning "searched and got nothing"
        into "has evidence" and swallowing exactly the disclosure this PR adds. The counter-example uses the real function, not a mock.
        """
        from src.search_service import SearchService
        from src.services.empty_news import news_evidence_present

        class _FailedResponse:
            success = False
            results = []
            provider = "stub"

        service = SearchService.__new__(SearchService)
        placeholder = SearchService.format_intel_report(
            service,
            {"latest_news": _FailedResponse(), "risk_check": _FailedResponse()},
            "测试标的",
        )

        # Precondition: this placeholder text really is non-empty, or the counter-example is meaningless
        self.assertTrue(placeholder.strip())
        self.assertIn("No relevant information found", placeholder)

        # Registered by source: 0 live hits, no social, no local pool - must be judged as no evidence
        self.assertFalse(news_evidence_present(0, None, None))

        # End to end: this case must produce the zero-hit disclosure in the report
        report = NotificationService.generate_daily_report(
            _make_service(),
            [_make_result(news_result_count=0, news_evidence_present=False)],
            report_date="2026-08-21",
        )
        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_stored_record_round_trips_the_evidence_flag(self):
        from src.services.empty_news import (
            empty_news_disclosure_from_stored,
            persisted_news_evidence_present,
        )

        stored = self._result(count=None, evidence=True).to_dict()
        self.assertIn("news_evidence_present", stored)
        self.assertTrue(persisted_news_evidence_present(stored, None))
        self.assertIsNone(empty_news_disclosure_from_stored(stored, None, "zh"))

    def test_legacy_record_without_the_flag_keeps_its_original_behaviour(self):
        """Old records without the field fall back to the count, without retroactively changing how they once rendered."""
        from src.services.empty_news import persisted_news_evidence_present

        self.assertTrue(persisted_news_evidence_present({"news_result_count": 4}, 4))
        self.assertFalse(persisted_news_evidence_present({"news_result_count": 0}, 0))

    def test_pipeline_registers_sources_and_never_passes_the_whole_context(self):
        """Both pipeline paths must register by source, and neither may pass the assembled news_context.

        Source assertion: anyone handing the whole news_context back to the decision function fails this case,
        and that is exactly how zero-hit placeholder text passes itself off as evidence.
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "src" / "core" / "pipeline.py").read_text(
            encoding="utf-8"
        )
        code_only = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )

        calls = code_only.count("result.news_evidence_present = news_evidence_present(")
        self.assertEqual(2, calls, "普通路径与 Agent 路径各要有一次登记")

        # All three sources must appear in the registration arguments
        self.assertIn("social_evidence_context", code_only)
        self.assertIn("persisted_intelligence_context", code_only)

        # The whole news_context must never be handed to the decision function again
        self.assertNotIn("news_evidence_present(\n                        news_context", code_only)
        self.assertNotIn("news_evidence_present(news_context", code_only)
        self.assertNotIn('news_evidence_present(\n                    initial_context.get("news_context")', code_only)


if __name__ == "__main__":
    unittest.main()
