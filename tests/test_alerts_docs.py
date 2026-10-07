# -*- coding: utf-8 -*-
"""Contract checks for the alert-center documentation."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "alerts.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_alerts_doc_exists_and_links_p0_scope() -> None:
    doc = _read_doc()

    assert "Issue #1202" in doc
    assert "AGENT_EVENT_ALERT_RULES_JSON" in doc
    assert "EventMonitor" in doc
    assert "P1 Alert API MVP" in doc
    assert "## P0 non-goals" in doc


def test_alerts_doc_covers_legacy_runtime_rules() -> None:
    doc = _read_doc()

    for token in ("price_cross", "price_change_percent", "volume_spike"):
        assert token in doc
    for token in ("sentiment_shift", "risk_flag", "custom"):
        assert token in doc


def test_alerts_doc_defines_required_contract_entities() -> None:
    doc = _read_doc()

    required_sections = (
        "### `alert_rule`",
        "### `alert_trigger`",
        "### `alert_notification`",
        "### `alert_cooldown`",
    )
    for section in required_sections:
        assert section in doc

    required_fields = (
        "target_scope",
        "parameters",
        "cooldown_policy",
        "notification_policy",
        "observed_value",
        "data_timestamp",
        "trigger_id",
        "latency_ms",
        "cooldown_until",
    )
    for field_name in required_fields:
        assert field_name in doc


def test_alerts_doc_covers_storage_evaluation_and_rollback() -> None:
    doc = _read_doc()

    assert (PROJECT_ROOT / "src" / "storage.py").is_file()

    for token in (
        "## Storage approach evaluation",
        "src/storage.py",
        "src/repositories/",
        "src/services/",
        "data/stock_analysis.db",
        "Idempotent initialization",
        "Rollback notes",
    ):
        assert token in doc


def test_alerts_doc_keeps_p0_non_goals_explicit() -> None:
    doc = _read_doc()

    for token in (
        "P0 adds no `api/v1/schemas/alerts.py`",
        "P0 adds no web alert-center page",
        "P0 adds no database table",
        "P0 does not implement writing trigger history",
        "P0 does not migrate, delete, or overwrite `AGENT_EVENT_ALERT_RULES_JSON` automatically",
        "P0 does not rewrite `NotificationService`",
    ):
        assert token in doc


def test_alerts_doc_defines_p1_api_mvp_scope() -> None:
    doc = _read_doc()

    for token in (
        "api/v1/endpoints/alerts.py",
        "api/v1/schemas/alerts.py",
        "GET /api/v1/alerts/rules",
        "POST /api/v1/alerts/rules",
        "GET /api/v1/alerts/rules/{rule_id}",
        "PATCH /api/v1/alerts/rules/{rule_id}",
        "DELETE /api/v1/alerts/rules/{rule_id}",
        "POST /api/v1/alerts/rules/{rule_id}/enable",
        "POST /api/v1/alerts/rules/{rule_id}/disable",
        "POST /api/v1/alerts/rules/{rule_id}/test",
        "GET /api/v1/alerts/triggers",
        "GET /api/v1/alerts/notifications",
        "price_cross",
        "price_change_percent",
        "volume_spike",
        "unsupported",
        "API responses must be redacted",
        "are reserved fields in P1",
        "it does not execute cooldown or custom notification semantics",
    ):
        assert token in doc


def test_alerts_doc_keeps_p1_non_goals_explicit() -> None:
    doc = _read_doc()

    for token in (
        "No web alert-center page, route, or sidebar entry is added.",
        "The schedule worker does not load persisted active rules",
        "Real `alert_trigger` / `alert_notification` writes are not implemented",
        "`alert_cooldown` execution semantics are not implemented",
        "MACD, KDJ, CCI, RSI, portfolio-risk, and Market Light alert rules are not implemented",
        "P1 does not migrate, delete, overwrite, or rewrite legacy configuration automatically",
    ):
        assert token in doc


def test_alerts_doc_defines_p2_worker_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P2 alert evaluation worker",
        "src/services/alert_worker.py",
        "agent_event_monitor",
        "persisted active rules",
        "legacy JSON",
        "`triggered`, `skipped`, `degraded`, and `failed`",
        "`alert_notifications` is not written",
        "does not execute `cooldown_policy`",
    ):
        assert token in doc


def test_alerts_doc_describes_p1_rollback_for_created_tables() -> None:
    doc = _read_doc()

    for token in (
        "P1 adds Alert API code",
        "`alert_rules` / `alert_triggers` / `alert_notifications` SQLite tables",
        "Base.metadata.create_all()",
        "SQLite tables and data already created by `Base.metadata.create_all()` are not deleted automatically",
        "delete the relevant tables by hand",
    ):
        assert token in doc


def test_alerts_doc_defines_p4_notification_and_cooldown_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P4 notification results and persisted cooldown",
        "`alert_cooldowns`",
        "`alert_notifications`",
        "`rule_id + target + data_source + data_timestamp`",
        "deduplicates the same data point",
        "When `data_timestamp` is missing, no deduplication is applied",
        "`__cooldown__`",
        "`__cooldown_read_failed__`",
        "`__noise_suppressed__`",
        "notification_noise.py",
        "On the normal path, a persisted rule uses `alert_cooldowns`",
        "reading the persisted cooldown state fails",
        "A legacy `AGENT_EVENT_ALERT_RULES_JSON` rule keeps using the worker's in-process fingerprint",
        "neither writes nor extends `alert_cooldowns`",
        "The minimal rollback is reverting the P4 PR",
    ):
        assert token in doc


def test_alerts_doc_defines_p5_indicator_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P5 technical-indicator rules",
        "ma_price_cross",
        "rsi_threshold",
        "macd_cross",
        "kdj_cross",
        "cci_threshold",
        "compute_required_bars",
        "requested_days",
        "required_bars > 365",
        "the last two closed daily bars",
        "prev <= threshold < current",
        "Wilder",
        "SMMA",
        "alpha=1/period",
        "EMA(fast_period)",
        "alpha=1/k_period",
        "0.015 * mean_deviation",
        "server local time-zone heuristic",
        "16:00",
        "whose date cannot be determined, is discarded conservatively",
        "still the legacy JSON path",
        "`_RUNTIME_SUPPORTED_ALERT_TYPES` in `src/agent/events.py` are not extended",
        "HTTP 400 + `validation_error`",
        "HTTP 400 + `unsupported_alert_type`",
        "MACD histogram expansion/contraction is not supported",
        "KDJ overbought/oversold zone rules are not supported",
        "MA-to-MA dual moving-average crosses are not supported",
        "Minute bars, precise market-calendar determination",
        "reverting the P5 PR",
        "skip unsupported `alert_type`",
    ):
        assert token in doc


def test_alerts_doc_defines_p6_portfolio_and_watchlist_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P6 holdings and watchlist linkage",
        "The P6 scope/type matrix",
        "`watchlist`",
        "`portfolio_holdings`",
        "`portfolio_account`",
        "`portfolio_stop_loss`",
        "`portfolio_concentration`",
        "`portfolio_drawdown`",
        "`portfolio_price_stale`",
        "Target Identity Contract",
        "`effective_target`",
        "`RuntimeAlertRule.key`",
        "`{parent_key}|{effective_target}`",
        "dry-run",
        "`degraded_count`",
        "soft cap",
        "cooldown_active",
        "parent-rule summary",
        "The legacy `AGENT_EVENT_ALERT_RULES_JSON` supports neither watchlist, portfolio",
        "Sector-level concentration alerts",
        "P6 PR",
    ):
        assert token in doc


def test_alerts_doc_defines_p7_market_light_scope() -> None:
    doc = _read_doc()

    for token in (
        "## P7 structured market-light alerts",
        "MarketLightSnapshot",
        "`target_scope=market`",
        "`market_light_status`",
        "`market_light_score_drop`",
        "`statuses=[\"red\",\"yellow\"]`",
        "`min_drop > 0`",
        "`us` / `ca`",
        "a two-way constraint",
        "`context_snapshot.market_light_snapshots`",
        "`data_quality=unavailable`",
        "`partial_comparison=true`",
        "`missing_dimensions`",
        "canonical scorer",
        "thin wrapper",
        "`load_previous_snapshot(region, before_trade_date)`",
        "the largest `snapshot.trade_date`",
        "A backfill for an older trading day",
        "`TRADING_DAY_CHECK_ENABLED`",
        "`data_source=market_light`",
        "The legacy `AGENT_EVENT_ALERT_RULES_JSON` does not support market rules",
        "reverting the P7 PR",
    ):
        assert token in doc


def test_alerts_doc_covers_issue_1386_p7_user_visibility_boundary() -> None:
    doc = _read_doc()
    p7_section = doc.split("The #1386 P7 user boundary:", 1)[1].split(
        "\n\nRolling back this linkage",
        1,
    )[0]

    for token in (
        "the phase and data-quality summary that was already public at trigger time",
        "does not start a lightweight intraday LLM analysis automatically",
        "adds no alert table, rule type, environment variable, or migration",
        "the analysis API or the web manual analysis entrypoint",
        "an alert notification keeps only the phase label, trigger source, partial-bar warning, data-quality level, and the first two limitations",
    ):
        assert token in p7_section


def test_alerts_doc_defines_p8_user_and_deployment_boundaries() -> None:
    doc = _read_doc()

    for token in (
        "## P8 user configuration and deployment boundaries",
        "`AGENT_EVENT_MONITOR_ENABLED`",
        "`AGENT_EVENT_MONITOR_INTERVAL_MINUTES`",
        "`NOTIFICATION_ALERT_CHANNELS`",
        "`route_type=alert`",
        "Persisted rules from the Alert API or the web alert center",
        "legacy `AGENT_EVENT_ALERT_RULES_JSON`",
        "compatible only with the three basic `single_symbol` rules",
        "P5 technical indicators, P6 watchlist/portfolio, or P7 market light",
        "docker/Dockerfile",
        "`python main.py --schedule`",
        "must keep the `data/` database volume",
        ".github/workflows/00-daily-analysis.yml",
        "a one-shot analysis workflow",
        "it does not run the `--schedule` background alert worker",
        "does not map the `AGENT_EVENT_*` variables",
        "`/alerts`",
        "The desktop app adds no native alert management interface",
        "`triggered`, `skipped`, `degraded`, and `failed`",
        "`rule_id + target + data_source + data_timestamp`",
        "Rolling back P8 only requires reverting the documentation, configuration notes, and web copy changes",
    ):
        assert token in doc


def test_changelog_mentions_alert_p6_release_note() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "P6" in changelog
    assert "自选股" in changelog
    assert "持仓" in changelog
    assert "账户联动规则" in changelog


def test_changelog_mentions_alert_p8_docs_closeout() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "补齐告警中心 P8 文档与配置收口说明" in changelog
    assert "GitHub Actions 与 Desktop 边界" in changelog


def test_changelog_unreleased_keeps_flat_entries() -> None:
    changelog = (PROJECT_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]

    assert "\n### " not in unreleased
