# -*- coding: utf-8 -*-
"""Contract checks for the AnalysisContextPack P0/P1 contract doc."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "analysis-context-pack.md"
FULL_GUIDE_PATH = PROJECT_ROOT / "docs" / "full-guide.md"
FULL_GUIDE_EN_PATH = PROJECT_ROOT / "docs" / "full-guide.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _section(doc: str, heading: str) -> str:
    marker = f"## {heading}"
    assert marker in doc
    return doc.split(marker, 1)[1].split("\n## ", 1)[0]


def test_analysis_context_pack_doc_has_required_sections() -> None:
    doc = _read_doc()

    for heading in (
        "## Terminology and boundaries",
        "## P0 scope and non-goals",
        "## P1 internal contract",
        "## P2 builder contract",
        "## P3 Runtime Consumption",
        "## P4 history records, task status, and web visibility",
        "## P5 data-quality scoring and prompt data limitations",
        "## P6 documentation, migration, and rollback",
        "## Field quality statuses",
        "## Existing status mapping",
        "## The seven-path inventory",
        "## Source anchors",
        "## Compatibility and safety boundaries",
    ):
        assert heading in doc


def test_analysis_context_pack_doc_disambiguates_context_surfaces() -> None:
    section = _section(_read_doc(), "Terminology and boundaries")

    for token in (
        "`storage.get_analysis_context()`",
        "`enhanced_context`",
        "`analysis_history.context_snapshot`",
        "Agent executor message context",
        "Agent orchestrator `AgentContext`",
        "`AGENT_ARCH=single`",
        "`AGENT_ARCH=multi`",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p0_quality_states() -> None:
    section = _section(_read_doc(), "Field quality statuses")

    for state in (
        "`available`",
        "`missing`",
        "`not_supported`",
        "`fallback`",
        "`stale`",
        "`estimated`",
        "`partial`",
        "`fetch_failed`",
    ):
        assert state in section
    assert "P0 fixes the future pack's field quality statuses at seven words first" in section
    assert "P5 adds `fetch_failed` within the same 1.0 umbrella" in section


def test_analysis_context_pack_doc_covers_seven_paths() -> None:
    section = _section(_read_doc(), "The seven-path inventory")

    for heading in (
        "### Ordinary analysis",
        "### Agent",
        "### Alerts",
        "### Holdings",
        "### Backtesting",
        "### History",
        "### Notifications",
    ):
        assert heading in section


def test_analysis_context_pack_doc_records_agent_context_visibility() -> None:
    section = _section(_read_doc(), "The seven-path inventory")

    for token in (
        "`initial_context`",
        "`fundamental_context`",
        "with no explicit injection of `fundamental_context` or `trend_result`",
        "pre-fetched data",
        "the orchestrator does not pre-inject `fundamental_context`",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_non_goals_and_safety_boundaries() -> None:
    doc = _read_doc()

    for token in (
        "P1 has added the `AnalysisContextPack` internal schema",
        "it still adds no builder",
        "wires in no runtime",
        "exposes no complete pack",
        "does not pack-ify `market_review`",
        "`market_light`",
        "P5 has added that status within the same 1.0 umbrella",
        "`analysis_history.context_snapshot.enhanced_context.date`",
        "The complete pack is not public by default",
        "API key",
        "token",
        "cookie",
        "complete webhook URL",
        "email password",
    ):
        assert token in doc


def test_analysis_context_pack_doc_defines_p1_schema_contract() -> None:
    section = _section(_read_doc(), "P1 internal contract")

    for token in (
        "`src/schemas/analysis_context_pack.py`",
        "`PACK_VERSION = \"1.0\"`",
        "`ContextFieldStatus`",
        "`AnalysisSubject`",
        "`AnalysisContextItem`",
        "`AnalysisContextBlock`",
        "`DataQuality`",
        "`AnalysisContextPack`",
        "`MarketPhaseContext.to_dict()`",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_block_catalog() -> None:
    section = _section(_read_doc(), "P1 internal contract")

    for token in (
        "P1 Block Catalog",
        "`quote`",
        "`daily_bars`",
        "`technical`",
        "`fundamentals`",
        "`news`",
        "`portfolio`",
        "`chip` / `capital_flow`",
        "`events` / `market_context`",
        "does not add a duplicate `identity` block",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_time_and_status_semantics() -> None:
    section = _section(_read_doc(), "P1 internal contract")

    for token in (
        "`AnalysisContextPack.created_at` uses `datetime`",
        "`model_dump(mode=\"json\")` emits as an ISO 8601 string",
        "`AnalysisContextItem.timestamp`",
        "`AnalysisContextBlock.timestamp`",
        "Optional[str]",
        "validates that format at construction time",
        "date-only",
        "`block.status` expresses the whole block's availability",
        "`item.status` expresses field-level quality",
        "does not implement automatic aggregation from `item.status` to `block.status`",
    ):
        assert token in section


def test_analysis_context_pack_doc_records_p1_redaction_contract() -> None:
    section = _section(_read_doc(), "P1 internal contract")

    for token in (
        "`AnalysisContextPack.to_safe_dict()`",
        "`redact_sensitive_mapping()`",
        "`api_key`",
        "`access_token`",
        "`authorization_header`",
        "`webhook_url`",
        "`license_key`",
        "[REDACTED]",
        "`data_api`",
        "does not scan ordinary string values",
        "does not apply URL regex redaction",
    ):
        assert token in section


def test_analysis_context_pack_doc_keeps_later_phases_out_of_p1() -> None:
    section = _section(_read_doc(), "P1 internal contract")

    for token in (
        "populates no runtime data",
        "adds no fetcher",
        "changes no prompt",
        "writes no history/task/report metadata",
        "exposes no complete pack to the API, web, bot, desktop, or notifications",
        "P2 builder",
        "P3 runtime",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p2_builder_boundaries() -> None:
    section = _section(_read_doc(), "P2 builder contract")

    for token in (
        "`AnalysisContextBuilder`",
        "assembler",
        "the artifacts the pipeline has already fetched",
        "zero-fetch",
        "`PipelineAnalysisArtifacts`",
        "`code`, `stock_name`, and `market`",
        "`price_stale`",
        "`quote_stale`",
        "`intraday_realtime_overlay`",
        "`fetch_failed`",
        "P3 runtime",
        "changes no prompt",
        "writes no history/task/report metadata",
    ):
        assert token in section


def test_analysis_context_pack_docs_record_issue_1386_p3_quality_boundaries() -> None:
    section = _section(_read_doc(), "P2 builder contract")

    for token in (
        "`fetched_at`",
        "`provider_timestamp`",
        "`is_stale`",
        "`stale_seconds`",
        "`fallback_from`",
        "`STALE > FALLBACK > AVAILABLE`",
        "The builder only maps upstream artifacts and performs no quality scoring",
        "`is_partial_bar`, `is_estimated`, and `estimated_fields`",
        "`daily_bars` carries no partial/estimated marker",
    ):
        assert token in section

    full_guide_en = FULL_GUIDE_EN_PATH.read_text(encoding="utf-8")
    assert "Intraday Data Packet and Realtime Quality Control (Issue #1386 P3)" in full_guide_en
    assert "source` keeps the actual successful provider token" in full_guide_en


def test_analysis_context_pack_doc_defines_p3_runtime_consumption_boundaries() -> None:
    section = _section(_read_doc(), "P3 Runtime Consumption")

    for token in (
        "`StockAnalysisPipeline` is the only producer of that summary",
        "`PipelineAnalysisArtifacts` -> `AnalysisContextBuilder.build()`",
        "`format_analysis_context_pack_prompt_section()`",
        "`analysis_context_pack_summary`",
        "basic information -> the #1386 `market_phase_context` rendered block -> `analysis_context_pack_summary`",
        "a raw payload such as `news.content`, `trend_result`, `chip`, or `fundamental_context`",
        "`AgentExecutor._build_user_message()`",
        "`AgentOrchestrator._build_context()`",
        "`ctx.meta[\"analysis_context_pack_summary\"]`",
        "is forbidden to write `ctx.data`",
        "`BaseAgent._build_messages()`",
        "`_inject_cached_data()`",
        "a `missing` `news` block is the expected P3 state",
        "`analysis_history.context_snapshot`",
        "`analysis_context_pack`",
        "`analysis_context_pack_summary`",
        "Agent tool-level pack cache reuse",
        "P4 adds the low-sensitivity overview on top of that",
        "P5 keeps reusing the summary consumption path",
    ):
        assert token in section

    assert "P3-min" not in section


def test_analysis_context_pack_doc_defines_p4_visibility_contract() -> None:
    section = _section(_read_doc(), "P4 history records, task status, and web visibility")

    for token in (
        "`analysis_context_pack_overview`",
        "a dedicated renderer",
        "`AnalysisContextPack.to_safe_dict()`",
        "`report.details.analysis_context_pack_overview`",
        "`analysisContextPackOverview`",
        "`GET /api/v1/history/{record_id}`",
        "the synchronous `POST /api/v1/analysis/analyze`",
        "the overview depends on a persisted `analysis_history.context_snapshot`",
        "completed `GET /api/v1/analysis/status/{task_id}`",
        "`sanitize_context_snapshot_for_api()`",
        "`extract_analysis_context_pack_overview()`",
        "`items.value`",
        "`trend_result`",
        "`fundamental_context`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "the whole `analysis_history.context_snapshot` is not persisted",
        "`market_phase_summary`",
        "`enhanced_context`",
        "`AnalysisContextSummary`",
        "positioned after the strategy levels and news and before the run diagnostics",
        "collapsed by default",
        "any non-zero other status counts",
        "do not cover the AnalysisContextPack data-quality summary on a pending/processing TaskPanel",
        "change neither the notification summary",
        "the collapsed header also shows the quality score and level",
        "the `fetch_failed` status",
    ):
        assert token in section

    assert "after the run diagnostics and before the strategy levels" not in section


def test_analysis_context_pack_doc_defines_p5_data_quality_contract() -> None:
    section = _section(_read_doc(), "P5 data-quality scoring and prompt data limitations")

    for token in (
        "`PACK_VERSION`",
        "`fetch_failed`",
        "`fundamental_context.status == \"failed\"`",
        "`overall_score`",
        "`level`",
        "`block_scores`",
        "`limitations`",
        "`quote=25`",
        "`fetch_failed=25`",
        "`Data Limitations`",
        "`confidence_level` not to be `高` / `High`",
        "`phase × degraded data`",
        "fail-open",
        "does not replace the P5 confidence/safety rules",
        "`analysis_context_pack_overview.data_quality`",
        "`details.context_snapshot`",
        "adds no fetcher",
        "changes no LLM output JSON schema",
        "`dashboard.phase_decision`",
    ):
        assert token in section


def test_analysis_context_pack_doc_defines_p6_migration_and_rollback_contract() -> None:
    section = _section(_read_doc(), "P6 documentation, migration, and rollback")

    for token in (
        "Four data surfaces must be understood separately",
        "The internal complete pack",
        "`analysis_context_pack_summary`",
        "`analysis_context_pack_overview`",
        "`analysis_history.context_snapshot`",
        "The summary visibility matrix",
        "`SAVE_CONTEXT_SNAPSHOT=true`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "`--no-context-snapshot`",
        "the whole `analysis_history.context_snapshot` is not persisted",
        "provided this run's history already persisted `analysis_history.context_snapshot`",
        "`enhanced_context`",
        "`market_phase_summary`",
        "`diagnostics`",
        "`realtime_quote_raw`",
        "does not affect this run's `AnalysisContextPack` construction",
        "or the in-memory `result.diagnostic_context_snapshot`",
        "Does not exist today",
        "A runtime pack master switch",
        "A release or code rollback",
        "secret",
        "token",
        "webhook",
    ):
        assert token in section


def test_analysis_context_pack_doc_maps_existing_status_terms() -> None:
    section = _section(_read_doc(), "Existing status mapping")

    for token in (
        "`degraded`",
        "`insufficient_data`",
        "`partial_failed`",
        "`data_missing`",
        "`price_stale`",
        "`data_quality=ok/partial/unavailable`",
        "No mapping",
    ):
        assert token in section


def test_analysis_context_pack_doc_lists_source_anchors() -> None:
    section = _section(_read_doc(), "Source anchors")

    for path in (
        "src/core/pipeline.py",
        "src/storage.py",
        "src/analyzer.py",
        "src/agent/orchestrator.py",
        "src/agent/executor.py",
        "src/agent/tools/data_tools.py",
        "src/services/alert_worker.py",
        "src/services/portfolio_service.py",
        "src/services/backtest_service.py",
        "src/repositories/backtest_repo.py",
        "src/services/history_service.py",
        "api/v1/endpoints/history.py",
        "api/v1/endpoints/analysis.py",
        "api/v1/schemas/history.py",
        "api/v1/schemas/portfolio.py",
        "src/notification.py",
        "docs/alerts.md",
        "docs/notifications.md",
    ):
        assert path in section


def test_analysis_context_pack_doc_updates_indexes_and_changelog() -> None:
    index_en = (PROJECT_ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert (
        "[Analysis Context Pack Contract, Runtime Consumption, And Visibility](analysis-context-pack.md) "
        "<sub><sub>![P6 Badge](https://img.shields.io/badge/P6-orange?style=flat)</sub></sub>"
    ) in index_en
    assert "P1/P2 internal contracts, P3 prompt-summary consumption, P4 history/API/Web low-sensitivity visibility, P5 data-quality scoring, and P6 migration/rollback notes" in index_en
    assert "#1386 market-phase analysis, migration, and rollback entry points" in index_en
    assert "新增 AnalysisContextPack P0 上下文盘点" in changelog
    assert "新增 AnalysisContextPack P1 内部契约与脱敏序列化测试" in changelog
    assert "新增 AnalysisContextPack P2 builder" in changelog
    assert "普通分析与 Agent 运行时 Prompt 接入 AnalysisContextPack 低敏摘要" in changelog
    assert "AnalysisContextPack P4 低敏 overview 接入历史详情" in changelog
    assert "AnalysisContextPack P5 增加数据质量评分" in changelog
    assert "明确 AnalysisContextPack P6 文档、迁移与回滚边界" in changelog
    assert "#1386 P7 盘前/盘中/盘后分析的入口、迁移、回滚和用户可见说明" in changelog
    assert "#1386 P5 为个股分析报告新增 `dashboard.phase_decision`" in changelog
    assert "优化 Web 报告详情页信息层级" in changelog


def test_full_guides_cover_issue_1386_p7_user_migration_closeout() -> None:
    guide_en = (PROJECT_ROOT / "docs" / "full-guide.md").read_text(encoding="utf-8")

    for token in (
        "Documentation, Configuration, And Migration Notes (Issue #1386 P7)",
        "pre-market / intraday / post-market analysis",
        "opening plan and watch conditions",
        "Intraday / lunch break / near close",
        "live state, risk, and opportunity alerts",
        "`analysis_phase=auto|premarket|intraday|postmarket`",
        "final report phase remains `report.meta.market_phase_summary.phase`",
        "Web main analysis / re-analysis / portfolio manual analysis",
        "no phase override selector",
        "the in-progress task panel shows the requested phase",
        "the final report page shows the final phase label",
        "Bot / CLI / schedule / default GitHub Actions",
        "Only consume public `market_phase_summary` and low-sensitivity `analysis_context_pack_overview`",
        "do not expose the full pack, prompt summary, news body text, or sensitive portfolio details",
        "Older callers that omit `analysis_phase` remain compatible",
        "Backtest queries support `analysis_phase=premarket|intraday|postmarket|unknown`",
        "`SAVE_CONTEXT_SNAPSHOT=false`",
        "does not disable current-run `AnalysisContextPack` construction",
        "low-sensitivity `analysis_context_pack_summary`",
        "`analysis_phase=postmarket`",
        "requires a release rollback or code rollback",
    ):
        assert token in guide_en


def test_full_guides_clarify_pack_summary_does_not_replace_legacy_payload_channels() -> None:
    guide = (PROJECT_ROOT / "docs" / "full-guide.md").read_text(encoding="utf-8")
    guide_en = (PROJECT_ROOT / "docs" / "full-guide.md").read_text(encoding="utf-8")

    assert "`report.details.analysis_context_pack_overview`" in guide
    assert "completed `/api/v1/analysis/status/{task_id}`" in guide
    assert "`dashboard.phase_decision`" in guide
    assert "`fetch_failed`" in guide
    assert "`report.meta.market_phase_summary`" in guide

    assert "in this new pack-summary section" in guide_en
    assert "not full `news.content`" in guide_en
    assert "Existing `news_context`, Agent pre-fetched JSON, and `enhanced_context` raw-payload channels keep their pre-P3 behavior" in guide_en
    assert "`report.details.analysis_context_pack_overview`" in guide_en
    assert "completed `/api/v1/analysis/status/{task_id}`" in guide_en
    assert "The Web report page renders a collapsed data-block summary after Strategy and News" in guide_en
    assert "available/missing counts, non-zero other status counts, and trigger source" in guide_en
    assert "the Web report page shows the data-block summary collapsed after Strategy and News" in guide_en
    assert "API `details.context_snapshot` strips the top-level `analysis_context_pack_overview`" in guide_en
    assert "sync analysis responses also extract the overview from the just-persisted `analysis_history.context_snapshot`" in guide_en
    assert "new records do not guarantee this field when `SAVE_CONTEXT_SNAPSHOT=false`" in guide_en
    assert "AnalysisContextPack Data Quality Scoring and Prompt Limitations (Issue #1389 P5)" in guide_en
    assert "Intraday Decision Guardrails and Quality Checks (Issue #1386 P5)" in guide_en
    assert "`dashboard.phase_decision`" in guide_en
    assert "`fetch_failed`" in guide_en
    assert "adds quality score/level to the header" in guide_en
    assert "`report.meta.market_phase_summary`" in guide_en
    assert "API `details.context_snapshot` strips the top-level `market_phase_summary`" in guide_en
    assert "AnalysisContextPack Documentation, Migration, and Rollback (Issue #1389 P6)" in guide_en
    assert "`SAVE_CONTEXT_SNAPSHOT` is an existing environment variable" in guide_en
    assert "the full `analysis_history.context_snapshot` is not persisted" in guide_en
    assert "does not disable current-run `AnalysisContextPack` construction" in guide_en
    assert "There is no runtime pack master switch" in guide_en
