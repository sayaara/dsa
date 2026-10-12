# -*- coding: utf-8 -*-
"""
===================================
Stock watchlist intelligent analysis system - notification layer
===================================

Responsibilities:
1. Aggregate the analysis results into a daily report
2. Emit Markdown-formatted output
3. Push through several channels (detected automatically):
   - Telegram Bot
   - Email over SMTP
   - Pushover (mobile and desktop push)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from enum import Enum

from src.config import Config, get_config
from src.enums import ReportType
from src.market_phase_summary import format_public_market_status_line, format_public_phase_pack_excerpt
from src.notification_routing import (
    get_notification_route_config,
    split_notification_route_channels,
)
from src.notification_noise import (
    NotificationNoiseDecision,
    evaluate_notification_noise,
    record_notification_noise,
    release_notification_noise,
)
from src.report_language import (
    get_localized_stock_name,
    get_report_labels,
    get_signal_level,
    get_chip_unavailable_reason,
    is_chip_structure_unavailable,
    localize_chip_health,
    localize_conflict_severity,
    localize_consensus_level,
    localize_strategy_signal,
    localize_strategy_skill,
    localize_strategy_conflict_description,
    localize_strategy_synthesis_summary,
    localize_trend_prediction,
    normalize_report_language,
    normalize_strategy_synthesis_payload,
    strategy_invalid_opinion_count,
    resolve_report_language,
)
from src.report_units import format_money_amount, format_per_share_amount
from src.schemas.decision_action import (
    display_action_fields_for_result,
    display_decision_type_for_result,
    display_operation_advice_for_result,
)
from bot.models import BotMessage
from src.utils.sanitize import sanitize_diagnostic_text
from src.formatters import strip_hidden_markdown_metadata
from src.utils.data_processing import (
    signal_attribution_has_content,
    signal_attribution_weight_items,
    normalize_model_used,
)
from src.notification_sender import (
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    GotifySender,
    NtfySender,
    PushoverSender,
    SlackSender,
    TelegramSender,
    resolve_gotify_message_endpoint,
    resolve_ntfy_endpoint,
)

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    """Best-effort float conversion; handles `"3.2%"` and `"1,234"` shapes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _format_strategy_skill_items(items: Any, report_language: Optional[str] = None) -> str:
    report_language = resolve_report_language(report_language)
    none_text = get_report_labels(report_language).get("none_label", "None")
    if not isinstance(items, list):
        return none_text
    formatted: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skill_id") or "").strip()
        signal = str(item.get("signal") or "").strip()
        confidence = item.get("confidence")
        if not skill_id:
            continue
        suffix = f"/{localize_strategy_signal(signal, report_language)}" if signal else ""
        if isinstance(confidence, (int, float)):
            suffix += f"/{confidence:.0%}"
        formatted.append(f"{localize_strategy_skill(skill_id, report_language)}{suffix}")
    return "、".join(formatted) if formatted else none_text


def _append_strategy_synthesis_block(lines: List[str], strategy_synthesis: Any, labels: Dict[str, str], report_language: str) -> None:
    strategy_synthesis = normalize_strategy_synthesis_payload(strategy_synthesis)
    if not strategy_synthesis:
        return
    confidence = strategy_synthesis.get("confidence")
    confidence_text = f"{confidence:.0%}" if isinstance(confidence, (int, float)) else "N/A"
    lines.extend([
        f"### 🧩 {labels['strategy_synthesis_heading']}",
        "",
        (
            f"- {labels['strategy_final_signal_label']}: "
            f"{localize_strategy_signal(strategy_synthesis.get('final_signal', 'N/A'), report_language)} | "
            f"{labels['strategy_consensus_level_label']}: "
            f"{localize_consensus_level(strategy_synthesis.get('consensus_level', 'N/A'), report_language)} | "
            f"{labels['strategy_conflict_label']}: "
            f"{localize_conflict_severity(strategy_synthesis.get('conflict_severity', 'none'), report_language)} "
            f"({strategy_synthesis.get('conflict_count', 0)}) | "
            f"{labels['strategy_confidence_label']}: {confidence_text}"
        ),
    ])
    summary = localize_strategy_synthesis_summary(strategy_synthesis, report_language)
    if summary:
        lines.append(f"- {labels['strategy_summary_label']}: {summary}")
    lines.append(
        f"- {labels['strategy_supporting_skills_label']}: "
        f"{_format_strategy_skill_items(strategy_synthesis.get('supporting_skills'), report_language)}"
    )
    lines.append(
        f"- {labels['strategy_opposing_skills_label']}: "
        f"{_format_strategy_skill_items(strategy_synthesis.get('opposing_skills'), report_language)}"
    )
    invalid_opinion_count = strategy_invalid_opinion_count(strategy_synthesis)
    if invalid_opinion_count:
        invalid_label = labels.get("strategy_invalid_opinions_label", "")
        if invalid_label:
            lines.append(f"- {invalid_label.format(count=invalid_opinion_count)}")
    for conflict in (strategy_synthesis.get("conflicts") or [])[:3]:
        if isinstance(conflict, dict) and conflict.get("conflict_type"):
            participants = conflict.get("participants") or []
            participant_text = "、".join(localize_strategy_skill(participant, report_language) for participant in participants)
            suffix = f"（{participant_text}）" if participant_text else ""
            lines.append(
                f"- {localize_conflict_severity(conflict.get('severity', 'medium'), report_language)}: "
                f"{localize_strategy_conflict_description(conflict.get('conflict_type'), report_language)}{suffix}"
            )
    lines.append("")


if TYPE_CHECKING:
    from src.analyzer import AnalysisResult


class NotificationChannel(Enum):
    """Notification channel types"""
    TELEGRAM = "telegram"  # Telegram
    EMAIL = "email"        # email
    PUSHOVER = "pushover"  # Pushover (mobile and desktop push)
    NTFY = "ntfy"          # ntfy
    GOTIFY = "gotify"      # Gotify
    CUSTOM = "custom"      # custom webhook
    DISCORD = "discord"    # Discord bot
    SLACK = "slack"        # Slack
    ASTRBOT = "astrbot"
    UNKNOWN = "unknown"    # unknown


@dataclass
class ChannelAttemptResult:
    """One static notification channel send attempt."""

    channel: str
    success: bool
    error_code: Optional[str] = None
    retryable: bool = False
    latency_ms: Optional[int] = None
    diagnostics: Optional[str] = None


@dataclass
class NotificationDispatchResult:
    """Structured result for notification dispatch diagnostics."""

    dispatched: bool
    success: bool
    status: str
    channel_results: List[ChannelAttemptResult] = field(default_factory=list)
    message: Optional[str] = None


class ChannelDetector:
    """
    Channel detector - simplified

    Determines the channel type straight from the configuration (no URL parsing needed)
    """

    @staticmethod
    def get_channel_name(channel: NotificationChannel) -> str:
        """Return the channel's display name"""
        names = {
            NotificationChannel.TELEGRAM: "Telegram",
            NotificationChannel.EMAIL: "Email",
            NotificationChannel.PUSHOVER: "Pushover",
            NotificationChannel.NTFY: "ntfy",
            NotificationChannel.GOTIFY: "Gotify",
            NotificationChannel.CUSTOM: "Custom webhook",
            NotificationChannel.DISCORD: "Discord bot",
            NotificationChannel.SLACK: "Slack",
            NotificationChannel.ASTRBOT: "AstrBot",
            NotificationChannel.UNKNOWN: "Unknown channel",
        }
        return names.get(channel, "Unknown channel")


class NotificationService(
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    GotifySender,
    NtfySender,
    PushoverSender,
    SlackSender,
    TelegramSender,
):
    """
    Notification service

    Responsibilities:
    1. Generate the Markdown-formatted daily report
    2. Push the message to every configured channel (concurrently)
    3. Support saving the report locally

    Supported channels:
    - Telegram Bot
    - Email over SMTP
    - Pushover (mobile and desktop push)

    Note: every configured channel receives the push
    """

    def __init__(self, source_message: Optional[BotMessage] = None):
        """
        Initialise the notification service

        Detects every configured channel and pushes to all of them
        """
        config = get_config()
        self._config = config
        self._source_message = source_message
        self._context_channels: List[str] = []

        # Markdown to image (Issue #289)
        self._markdown_to_image_channels = set(
            getattr(config, 'markdown_to_image_channels', []) or []
        )
        self._markdown_to_image_max_chars = getattr(
            config, 'markdown_to_image_max_chars', 15000
        )

        # Summary only (Issue #262): true pushes just the roll-up, without per-stock detail
        self._report_summary_only = getattr(config, 'report_summary_only', False)
        self._report_show_llm_model = getattr(config, 'report_show_llm_model', True)
        self._history_compare_cache: Dict[Tuple[int, str, Tuple[Tuple[str, str], ...]], Dict[str, List[Dict[str, Any]]]] = {}

        # Initialise the individual channels
        AstrbotSender.__init__(self, config)
        CustomWebhookSender.__init__(self, config)
        DiscordSender.__init__(self, config)
        EmailSender.__init__(self, config)
        GotifySender.__init__(self, config)
        NtfySender.__init__(self, config)
        PushoverSender.__init__(self, config)
        SlackSender.__init__(self, config)
        TelegramSender.__init__(self, config)

        # Detect every configured channel
        self._available_channels = self._detect_all_channels()

        if not self._available_channels and not self._context_channels:
            logger.warning("No valid notification channel is configured; no push notifications will be sent")
        else:
            channel_names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
            channel_names.extend(self._context_channels)
            logger.info(f"{len(channel_names)} notification channels configured: {', '.join(channel_names)}")

    def _normalize_report_type(self, report_type: Any) -> ReportType:
        """Normalize string/enum input into ReportType."""
        if isinstance(report_type, ReportType):
            return report_type
        return ReportType.from_str(report_type)

    def _get_report_language(self, payload: Optional[Any] = None) -> str:
        """Resolve report language from result payload or global config."""
        if isinstance(payload, list):
            for item in payload:
                language = getattr(item, "report_language", None)
                if language:
                    return normalize_report_language(language)
        elif payload is not None:
            language = getattr(payload, "report_language", None)
            if language:
                return normalize_report_language(language)

        return resolve_report_language(getattr(get_config(), "report_language", None))

    def _get_labels(self, payload: Optional[Any] = None) -> Dict[str, str]:
        return get_report_labels(self._get_report_language(payload))

    def _get_display_name(self, result: AnalysisResult, language: Optional[str] = None) -> str:
        report_language = normalize_report_language(language or self._get_report_language(result))
        return self._escape_md(
            get_localized_stock_name(result.name, result.code, report_language)
        )

    def _get_history_compare_context(self, results: List[AnalysisResult]) -> Dict[str, Any]:
        """Fetch and cache history comparison data for markdown rendering."""
        config = get_config()
        history_compare_n = getattr(config, 'report_history_compare_n', 0)
        if history_compare_n <= 0 or not results:
            return {"history_by_code": {}}

        report_language = self._get_report_language(results)

        cache_key = (
            history_compare_n,
            report_language,
            tuple(sorted((r.code, getattr(r, 'query_id', '') or '') for r in results)),
        )
        if cache_key in self._history_compare_cache:
            return {"history_by_code": self._history_compare_cache[cache_key]}

        try:
            from src.services.history_comparison_service import get_signal_changes_batch

            exclude_ids = {
                r.code: r.query_id
                for r in results
                if getattr(r, 'query_id', None)
            }
            codes = list(dict.fromkeys(r.code for r in results))
            history_by_code = get_signal_changes_batch(
                codes,
                limit=history_compare_n,
                exclude_query_ids=exclude_ids,
                report_language=report_language,
            )
        except Exception as e:
            logger.debug("History comparison skipped: %s", e)
            history_by_code = {}

        self._history_compare_cache[cache_key] = history_by_code
        return {"history_by_code": history_by_code}

    @staticmethod
    def _empty_news_disclosure(result: "AnalysisResult", language: Optional[str] = None) -> Optional[str]:
        """Return the disclosure wording for a news search that never ran or matched nothing.

        src/services/empty_news owns both the decision and the wording, so the string-concatenation
        renderer and the template renderer share one implementation and no channel stays silent while others disclose.
        """
        language = resolve_report_language(language)
        from src.services.empty_news import empty_news_disclosure

        return empty_news_disclosure(result, language)

    @staticmethod
    def _append_data_sources_line(
        lines: List[str],
        result: AnalysisResult,
        labels: Dict[str, str],
    ) -> bool:
        data_sources = getattr(result, "data_sources", None)
        if not isinstance(data_sources, str):
            return False
        data_sources = data_sources.strip()
        if not data_sources:
            return False
        lines.append(f"*📋 {labels['data_sources_label']}{labels['label_colon']}{data_sources}*")
        return True

    def generate_aggregate_report(
        self,
        results: List[AnalysisResult],
        report_type: Any,
        report_date: Optional[str] = None,
    ) -> str:
        """Generate the aggregate report content used by merge/save/push paths."""
        normalized_type = self._normalize_report_type(report_type)
        if normalized_type == ReportType.BRIEF:
            return self.generate_brief_report(results, report_date=report_date)
        return self.generate_dashboard_report(results, report_date=report_date)

    def _collect_models_used(self, results: List[AnalysisResult]) -> List[str]:
        if not self._should_show_llm_model():
            return []
        models: List[str] = []
        for result in results:
            model = normalize_model_used(getattr(result, "model_used", None))
            if model:
                models.append(model)
        return list(dict.fromkeys(models))

    def _public_phase_pack_excerpt(self, result: AnalysisResult, report_language: str) -> str:
        return format_public_phase_pack_excerpt(
            getattr(result, "market_phase_summary", None),
            getattr(result, "analysis_context_pack_overview", None),
            source=getattr(result, "analysis_visibility_source", None) or "evaluator_snapshot",
            report_language=report_language,
        )

    def _public_market_status_line(self, results: List[AnalysisResult], report_language: str) -> str:
        for result in results or []:
            line = format_public_market_status_line(
                getattr(result, "market_phase_summary", None),
                report_language=report_language,
            )
            if line:
                return line
        return ""

    def _append_market_status_line(
        self,
        lines: List[str],
        results: List[AnalysisResult],
        report_language: str,
    ) -> None:
        status_line = self._public_market_status_line(results, report_language)
        if status_line:
            lines.extend([status_line, ""])
        elif lines and lines[-1] != "":
            lines.append("")

    def _should_show_llm_model(self) -> bool:
        return bool(getattr(self._config, "report_show_llm_model", self._report_show_llm_model))

    @staticmethod
    def detect_configured_channels(config: Config) -> List[NotificationChannel]:
        """
        Detect statically configured notification channels from Config.

        This intentionally mirrors sender availability without instantiating
        sender objects, so diagnostics and runtime use the same channel truth.
        Runtime-only context channels are handled by instance methods.
        """
        channels = []

        if (
            getattr(config, "telegram_bot_token", None)
            and getattr(config, "telegram_chat_id", None)
        ):
            channels.append(NotificationChannel.TELEGRAM)

        if getattr(config, "email_sender", None) and getattr(config, "email_password", None):
            channels.append(NotificationChannel.EMAIL)

        if (
            getattr(config, "pushover_user_key", None)
            and getattr(config, "pushover_api_token", None)
        ):
            channels.append(NotificationChannel.PUSHOVER)

        ntfy_server_url, ntfy_topic = resolve_ntfy_endpoint(getattr(config, "ntfy_url", None))
        if ntfy_server_url and ntfy_topic:
            channels.append(NotificationChannel.NTFY)

        gotify_endpoint = resolve_gotify_message_endpoint(getattr(config, "gotify_url", None))
        if gotify_endpoint and (getattr(config, "gotify_token", None) or "").strip():
            channels.append(NotificationChannel.GOTIFY)

        if getattr(config, "custom_webhook_urls", None):
            channels.append(NotificationChannel.CUSTOM)

        if (
            getattr(config, "discord_webhook_url", None)
            or (
                getattr(config, "discord_bot_token", None)
                and getattr(config, "discord_main_channel_id", None)
            )
        ):
            channels.append(NotificationChannel.DISCORD)

        if (
            getattr(config, "slack_webhook_url", None)
            or (
                getattr(config, "slack_bot_token", None)
                and getattr(config, "slack_channel_id", None)
            )
        ):
            channels.append(NotificationChannel.SLACK)

        if getattr(config, "astrbot_url", None):
            channels.append(NotificationChannel.ASTRBOT)

        return channels

    def _detect_all_channels(self) -> List[NotificationChannel]:
        """
        Detect every configured channel

        Returns:
            The list of configured channels
        """
        return self.detect_configured_channels(self._config)

    def is_available(self) -> bool:
        """Check whether the notification service is usable (at least one channel, or a context channel)"""
        return len(self._available_channels) > 0 or self._has_context_channel()

    def get_available_channels(self) -> List[NotificationChannel]:
        """Return every configured channel"""
        return self._available_channels

    def get_channels_for_route(
        self,
        route_type: Optional[str],
        channels: Optional[List[NotificationChannel]] = None,
    ) -> List[NotificationChannel]:
        """Return channels allowed for a route type.

        ``route_type=None`` keeps the legacy behavior and returns all supplied
        static channels. Empty route config also keeps all supplied channels.
        Non-empty route config that matches no enabled channel returns an empty
        list.
        """
        target_channels = list(channels if channels is not None else self._available_channels)
        if route_type is None:
            return target_channels

        route_config = get_notification_route_config(route_type)
        if route_config is None:
            logger.warning("Unknown notification route type %s; using all configured channels", route_type)
            return target_channels

        configured_route_channels = getattr(self._config, route_config["config_attr"], []) or []
        if not configured_route_channels:
            return target_channels

        valid_channels, invalid_channels = split_notification_route_channels(configured_route_channels)
        if invalid_channels:
            logger.warning(
                "%s contains unknown notification channels, ignoring: %s",
                route_config["env_key"],
                ", ".join(invalid_channels),
            )

        allowed = set(valid_channels)
        return [channel for channel in target_channels if channel.value in allowed]

    def get_channel_names(self) -> str:
        """Return the names of every configured channel"""
        names = [ChannelDetector.get_channel_name(ch) for ch in self._available_channels]
        return ', '.join(names)

    def evaluate_noise_control(
        self,
        content: str,
        *,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
    ) -> NotificationNoiseDecision:
        """Evaluate static-channel notification noise controls."""
        return evaluate_notification_noise(
            self._config,
            content=content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
        )

    @staticmethod
    def record_noise_control(decision: NotificationNoiseDecision) -> None:
        """Record static-channel notification noise state after a successful send."""
        record_notification_noise(decision)

    @staticmethod
    def release_noise_control(decision: NotificationNoiseDecision) -> None:
        """Release static-channel in-flight noise reservation after send failure."""
        release_notification_noise(decision)

    # ===== Context channel =====
    def _has_context_channel(self) -> bool:
        """Decide whether a message-context channel exists (a Telegram conversation, say)"""
        return self._extract_telegram_context_chat_id() is not None

    def _source_platform(self) -> str:
        """Return normalized platform from the source bot message."""
        platform = getattr(self._source_message, "platform", "")
        if hasattr(platform, "value"):
            platform = platform.value
        return str(platform or "").lower()

    def _extract_telegram_context_chat_id(self) -> Optional[str]:
        """Extract the Telegram context chat_id from the source message (used for the async reply)."""
        if not isinstance(self._source_message, BotMessage):
            return None
        if self._source_platform() != "telegram":
            return None
        raw_data = getattr(self._source_message, "raw_data", {}) or {}
        for candidate in (
            getattr(self._source_message, "chat_id", ""),
            raw_data.get("chat_id"),
            raw_data.get("message", {}).get("chat", {}).get("id") if isinstance(raw_data.get("message"), dict) else None,
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            if candidate is not None and not isinstance(candidate, str):
                candidate_text = str(candidate).strip()
                if candidate_text:
                    return candidate_text
        return None

    def should_broadcast_static_channels(self) -> bool:
        """Whether static notification channels should receive this dispatch."""
        return not self._has_context_channel()

    def send_to_context(self, content: str) -> bool:
        """
        Send a message to a message-context channel (a Telegram conversation, for example)

        Args:
            content: the Markdown-formatted content
        """
        return self._send_via_source_context(content)

    def _send_via_source_context(self, content: str) -> bool:
        """
        Send a report through the message context (a Telegram conversation)

        Mainly used by jobs triggered from a bot's Stream mode, so the result returns to the conversation that triggered it.
        """
        success = False

        # Try the Telegram conversation context (reply to the originating chat_id)
        telegram_chat_id = self._extract_telegram_context_chat_id()
        if telegram_chat_id:
            try:
                if self.send_to_telegram(content, chat_id=telegram_chat_id):
                    logger.info("Report pushed through the Telegram context session")
                    success = True
                else:
                    logger.error("Telegram context session push failed")
            except Exception as e:
                logger.error(f"Telegram context session push error: {e}")

        return success

    def generate_daily_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        Generate the Markdown daily report (detailed edition)

        Args:
            results: the list of analysis results
            report_date: the report date (defaults to today)

        Returns:
            The Markdown-formatted daily report
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')
        report_language = self._get_report_language(results)
        labels = get_report_labels(report_language)

        # Title
        report_lines = [
            f"# 📅 {report_date} {labels['report_title']}",
            "",
            f"> {labels['analyzed_prefix']} **{len(results)}** {labels['stock_unit']} | "
            f"{labels['generated_at_label']}{labels['label_colon']}{datetime.now().strftime('%H:%M:%S')}",
        ]
        self._append_market_status_line(report_lines, results, report_language)
        report_lines.extend(["---", ""])

        # Sort by score (highest first)
        sorted_results = sorted(
            results,
            key=lambda x: x.sentiment_score,
            reverse=True
        )

        buy_count, sell_count, hold_count = self._count_display_decisions(results, report_language)
        avg_score = sum(r.sentiment_score for r in results) / len(results) if results else 0

        report_lines.extend([
            f"## 📊 {labels['summary_heading']}",
            "",
            f"| {labels['metric_header']} | {labels['value_header']} |",
            "|------|------|",
            f"| 🟢 {labels['buy_label']} | **{buy_count}** {labels['stock_unit_compact']} |",
            f"| 🟡 {labels['watch_label']} | **{hold_count}** {labels['stock_unit_compact']} |",
            f"| 🔴 {labels['sell_label']} | **{sell_count}** {labels['stock_unit_compact']} |",
            f"| 📈 {labels['avg_score_label']} | **{avg_score:.1f}** |",
            "",
            "---",
            "",
        ])

        # Issue #262: with summary_only, emit only the summary and skip per-stock detail
        if self._report_summary_only:
            report_lines.extend([f"## 📊 {labels['summary_heading']}", ""])
            for r in sorted_results:
                signal_text, emoji, _ = self._get_signal_level(r)
                report_lines.append(
                    f"{emoji} **{self._get_display_name(r, report_language)}({r.code})**: "
                    f"{signal_text} | "
                    f"{labels['score_label']} {r.sentiment_score} | "
                    f"{localize_trend_prediction(r.trend_prediction, report_language)}"
                )
                news_disclosure = self._empty_news_disclosure(r, report_language)
                if news_disclosure:
                    report_lines.append(news_disclosure)
        else:
            report_lines.extend([f"## 📈 {labels['report_title']}", ""])
            # Per-stock detailed analysis
            for result in sorted_results:
                signal_text, emoji, _ = self._get_signal_level(result)
                confidence_stars = result.get_confidence_stars() if hasattr(result, 'get_confidence_stars') else '⭐⭐'

                report_lines.extend([
                    f"### {emoji} {self._get_display_name(result, report_language)} ({result.code})",
                    "",
                    f"**{labels['action_advice_label']}{labels['label_colon']}{signal_text}** | "
                    f"**{labels['score_label']}{labels['label_colon']}{result.sentiment_score}** | "
                    f"**{labels['trend_label']}{labels['label_colon']}{localize_trend_prediction(result.trend_prediction, report_language)}** | "
                    f"**{labels['confidence_label']}{labels['label_colon']}{confidence_stars}**",
                    "",
                ])
                self._append_market_snapshot(report_lines, result)

                # Key points
                if hasattr(result, 'key_points') and result.key_points:
                    report_lines.extend([
                        f"**🎯 {labels['key_points_label']}**{labels['label_colon']}{result.key_points}",
                        "",
                    ])

                # Buy/sell reasoning
                if hasattr(result, 'buy_reason') and result.buy_reason:
                    report_lines.extend([
                        f"**💡 {labels['operation_reason_label']}**{labels['label_colon']}{result.buy_reason}",
                        "",
                    ])

                # Trend analysis
                if hasattr(result, 'trend_analysis') and result.trend_analysis:
                    report_lines.extend([
                        f"#### 📉 {labels['trend_analysis_heading']}",
                        f"{result.trend_analysis}",
                        "",
                    ])

                # Short- and medium-term outlook
                outlook_lines = []
                if hasattr(result, 'short_term_outlook') and result.short_term_outlook:
                    outlook_lines.append(f"- **{labels['short_term_outlook_label']}**{labels['label_colon']}{result.short_term_outlook}")
                if hasattr(result, 'medium_term_outlook') and result.medium_term_outlook:
                    outlook_lines.append(f"- **{labels['medium_term_outlook_label']}**{labels['label_colon']}{result.medium_term_outlook}")
                if outlook_lines:
                    report_lines.extend([
                        f"#### 🔮 {labels['market_outlook_heading']}",
                        *outlook_lines,
                        "",
                    ])

                # Technical analysis
                tech_lines = []
                if result.technical_analysis:
                    tech_lines.append(f"**{labels['technical_overall_label']}**{labels['label_colon']}{result.technical_analysis}")
                if hasattr(result, 'ma_analysis') and result.ma_analysis:
                    tech_lines.append(f"**{labels['ma_analysis_label']}**{labels['label_colon']}{result.ma_analysis}")
                if hasattr(result, 'volume_analysis') and result.volume_analysis:
                    tech_lines.append(f"**{labels['volume_analysis_label']}**{labels['label_colon']}{result.volume_analysis}")
                if hasattr(result, 'pattern_analysis') and result.pattern_analysis:
                    tech_lines.append(f"**{labels['pattern_analysis_label']}**{labels['label_colon']}{result.pattern_analysis}")
                if tech_lines:
                    report_lines.extend([
                        f"#### 📊 {labels['technical_analysis_heading']}",
                        *tech_lines,
                        "",
                    ])

                # Fundamental analysis
                fund_lines = []
                if hasattr(result, 'fundamental_analysis') and result.fundamental_analysis:
                    fund_lines.append(result.fundamental_analysis)
                if hasattr(result, 'sector_position') and result.sector_position:
                    fund_lines.append(f"**{labels['sector_position_label']}**{labels['label_colon']}{result.sector_position}")
                if hasattr(result, 'company_highlights') and result.company_highlights:
                    fund_lines.append(f"**{labels['company_highlights_label']}**{labels['label_colon']}{result.company_highlights}")
                if fund_lines:
                    report_lines.extend([
                        f"#### 🏢 {labels['fundamental_analysis_heading']}",
                        *fund_lines,
                        "",
                    ])

                # News and sentiment
                news_lines = []
                if result.news_summary:
                    news_lines.append(f"**{labels['news_summary_label']}**{labels['label_colon']}{result.news_summary}")
                if hasattr(result, 'market_sentiment') and result.market_sentiment:
                    news_lines.append(f"**{labels['market_sentiment_label']}**{labels['label_colon']}{result.market_sentiment}")
                if hasattr(result, 'hot_topics') and result.hot_topics:
                    news_lines.append(f"**{labels['hot_topics_label']}**{labels['label_colon']}{result.hot_topics}")
                news_disclosure = self._empty_news_disclosure(result, report_language)
                if news_lines or news_disclosure:
                    report_lines.append(f"#### 📰 {labels['news_sentiment_heading']}")
                    if news_disclosure:
                        report_lines.append(news_disclosure)
                    report_lines.extend(news_lines)
                    report_lines.append("")

                # Combined analysis
                if result.analysis_summary:
                    report_lines.extend([
                        f"#### 📝 {labels['overall_analysis_heading']}",
                        result.analysis_summary,
                        "",
                    ])

                # Risk warning
                if hasattr(result, 'risk_warning') and result.risk_warning:
                    report_lines.extend([
                        f"⚠️ **{labels['risk_warning_label']}**{labels['label_colon']}{result.risk_warning}",
                        "",
                    ])

                # Data source notes
                if hasattr(result, 'search_performed') and result.search_performed:
                    report_lines.append(f"*🔍 {labels['web_search_note']}*")
                self._append_data_sources_line(report_lines, result, labels)

                # Error details (when present)
                if not result.success and result.error_message:
                    report_lines.extend([
                        "",
                        f"❌ **{labels['analysis_error_label']}**{labels['label_colon']}{result.error_message[:100]}",
                    ])

                report_lines.extend([
                    "",
                    "---",
                    "",
                ])

        # Footer (the disclaimer is dropped)
        report_lines.extend([
            "",
            f"*{labels['generated_at_label']}{labels['label_colon']}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        return "\n".join(report_lines)

    @staticmethod
    def _escape_md(name: str) -> str:
        """Escape markdown special characters in stock names (e.g. *ST → \\*ST)."""
        return name.replace('*', r'\*') if name else name

    @staticmethod
    def _clean_sniper_value(value: Any) -> str:
        """Normalize sniper point values and remove redundant label prefixes."""
        if value is None:
            return 'N/A'
        if isinstance(value, (int, float)):
            return str(value)
        if not isinstance(value, str):
            return str(value)
        if not value or value == 'N/A':
            return value
        prefixes = ['理想买入点：', '次优买入点：', '止损位：', '目标位：',
                     '理想买入点:', '次优买入点:', '止损位:', '目标位:',
                     'Ideal Entry:', 'Secondary Entry:', 'Stop Loss:', 'Target:']
        for prefix in prefixes:
            if value.startswith(prefix):
                return value[len(prefix):]
        return value

    @staticmethod
    def _phase_decision_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @classmethod
    def _phase_decision_has_content(cls, phase_decision: Dict[str, Any]) -> bool:
        text_keys = (
            "action_window",
            "immediate_action",
            "next_check_time",
            "confidence_reason",
        )
        if any(str(phase_decision.get(key) or "").strip() for key in text_keys):
            return True
        return bool(
            cls._phase_decision_list(phase_decision.get("watch_conditions"))
            or cls._phase_decision_list(phase_decision.get("data_limitations"))
        )

    def _append_phase_decision_block(
        self,
        report_lines: List[str],
        dashboard: Dict[str, Any],
        labels: Dict[str, str],
    ) -> None:
        phase_decision = dashboard.get("phase_decision") if dashboard else None
        if not isinstance(phase_decision, dict):
            return
        if not self._phase_decision_has_content(phase_decision):
            return

        watch_conditions = self._phase_decision_list(phase_decision.get("watch_conditions"))
        data_limitations = self._phase_decision_list(phase_decision.get("data_limitations"))

        report_lines.extend([
            f"### 🛡️ {labels['phase_decision_heading']}",
            "",
            f"| {labels['action_window_label']} | {labels['immediate_action_label']} | {labels['next_check_time_label']} |",
            "|---------|---------|---------|",
            f"| {phase_decision.get('action_window') or 'N/A'} | "
            f"{phase_decision.get('immediate_action') or 'N/A'} | "
            f"{phase_decision.get('next_check_time') or 'N/A'} |",
            "",
        ])

        if watch_conditions:
            report_lines.append(f"**{labels['watch_conditions_label']}**:")
            for condition in watch_conditions:
                report_lines.append(f"- {condition}")
            report_lines.append("")

        confidence_reason = str(phase_decision.get("confidence_reason") or "").strip()
        if confidence_reason:
            report_lines.extend([
                f"**{labels['confidence_reason_label']}**: {confidence_reason}",
                "",
            ])

        if data_limitations:
            report_lines.append(f"**{labels['data_limitations_label']}**:")
            for limitation in data_limitations:
                report_lines.append(f"- {limitation}")
            report_lines.append("")

    def _get_display_operation_advice(
        self,
        result: AnalysisResult,
        report_language: Optional[str] = None,
    ) -> str:
        return display_operation_advice_for_result(
            result,
            report_language=report_language or self._get_report_language(result),
        )

    def _count_display_decisions(
        self,
        results: List[AnalysisResult],
        report_language: Optional[str] = None,
    ) -> Tuple[int, int, int]:
        language = report_language or self._get_report_language(results)
        buckets = [
            display_decision_type_for_result(result, report_language=language)
            for result in results
        ]
        buy_count = sum(1 for bucket in buckets if bucket == "buy")
        sell_count = sum(1 for bucket in buckets if bucket == "sell")
        hold_count = len(buckets) - buy_count - sell_count
        return buy_count, sell_count, hold_count

    def _get_signal_level(self, result: AnalysisResult) -> tuple:
        """Get display text and signal metadata from the resolved action."""
        report_language = self._get_report_language(result)
        display_fields = display_action_fields_for_result(
            result,
            report_language=report_language,
        )
        signal_advice = {
            "buy": "buy",
            "add": "buy",
            "hold": "hold",
            "reduce": "reduce",
            "sell": "sell",
            "watch": "watch",
            "avoid": "hold",
            "alert": "sell",
        }.get(display_fields["action"])
        _, emoji, signal_tag = get_signal_level(
            signal_advice or self._get_display_operation_advice(result, report_language),
            result.sentiment_score,
            report_language,
        )
        return (
            self._get_display_operation_advice(result, report_language),
            emoji,
            signal_tag,
        )

    def generate_dashboard_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None
    ) -> str:
        """
        Generate the decision-dashboard daily report (detailed edition)

        Layout: market overview + key information + headline conclusion + data insight + action plan

        Args:
            results: the list of analysis results
            report_date: the report date (defaults to today)

        Returns:
            The Markdown decision-dashboard daily report
        """
        config = get_config()
        report_language = self._get_report_language(results)
        labels = get_report_labels(report_language)

        reason_label = "Rationale"
        risk_warning_label = "Risk Warning"
        technical_heading = "Technicals"
        ma_label = "Moving Averages"
        volume_analysis_label = "Volume"
        news_heading = "News Flow"
        if getattr(config, 'report_renderer_enabled', False) and results:
            from src.services.report_renderer import render
            out = render(
                platform='markdown',
                results=results,
                report_date=report_date,
                summary_only=self._report_summary_only,
                extra_context={
                    **self._get_history_compare_context(results),
                    "report_language": report_language,
                },
            )
            if out:
                return out

        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')

        # Sort by score (highest first)
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)

        buy_count, sell_count, hold_count = self._count_display_decisions(results, report_language)

        report_lines = [
            f"# 🎯 {report_date} {labels['dashboard_title']}",
            "",
            f"> {labels['analyzed_prefix']} **{len(results)}** {labels['stock_unit']} | "
            f"🟢{labels['buy_label']}:{buy_count} 🟡{labels['watch_label']}:{hold_count} 🔴{labels['sell_label']}:{sell_count}",
        ]
        self._append_market_status_line(report_lines, results, report_language)

        # === New: analysis result summary (Issue #112) ===
        if results:
            report_lines.extend([
                f"## 📊 {labels['summary_heading']}",
                "",
            ])
            for r in sorted_results:
                signal_text, signal_emoji, _ = self._get_signal_level(r)
                display_name = self._get_display_name(r, report_language)
                report_lines.append(
                    f"{signal_emoji} **{display_name}({r.code})**: "
                    f"{signal_text} | "
                    f"{labels['score_label']} {r.sentiment_score} | "
                    f"{localize_trend_prediction(r.trend_prediction, report_language)}"
                )
                if self._report_summary_only:
                    news_disclosure = self._empty_news_disclosure(r, report_language)
                    if news_disclosure:
                        report_lines.append(news_disclosure)
                    self._append_data_sources_line(report_lines, r, labels)
            report_lines.extend([
                "",
                "---",
                "",
            ])

        # Per-stock decision dashboard (Issue #262: skipped under summary_only)
        if not self._report_summary_only:
            for result in sorted_results:
                signal_text, signal_emoji, signal_tag = self._get_signal_level(result)
                dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}

                # Stock name (prefer the name in dashboard or result, escaping *ST and similar)
                stock_name = self._get_display_name(result, report_language)

                report_lines.extend([
                    f"## {signal_emoji} {stock_name} ({result.code})",
                    "",
                ])
                # ========== Sentiment and fundamentals overview (shown first) ==========
                intel = dashboard.get('intelligence', {}) if dashboard else {}
                if intel:
                    report_lines.extend([
                        f"### 📰 {labels['info_heading']}",
                        "",
                    ])
                    # Sentiment summary
                    if intel.get('sentiment_summary'):
                        report_lines.append(f"**💭 {labels['sentiment_summary_label']}**: {intel['sentiment_summary']}")
                    # Earnings expectations
                    if intel.get('earnings_outlook'):
                        report_lines.append(f"**📊 {labels['earnings_outlook_label']}**: {intel['earnings_outlook']}")
                    # Risk alerts (highlighted)
                    risk_alerts = intel.get('risk_alerts', [])
                    if risk_alerts:
                        report_lines.append("")
                        report_lines.append(f"**🚨 {labels['risk_alerts_label']}**:")
                        for alert in risk_alerts:
                            report_lines.append(f"- {alert}")
                    # Positive catalysts
                    catalysts = intel.get('positive_catalysts', [])
                    if catalysts:
                        report_lines.append("")
                        report_lines.append(f"**✨ {labels['positive_catalysts_label']}**:")
                        for cat in catalysts:
                            report_lines.append(f"- {cat}")
                    # Latest news
                    if intel.get('latest_news'):
                        report_lines.append("")
                        report_lines.append(f"**📢 {labels['latest_news_label']}**: {intel['latest_news']}")
                    report_lines.append("")

                # ========== Headline conclusion ==========
                core = dashboard.get('core_conclusion', {}) if dashboard else {}
                one_sentence = core.get('one_sentence', result.analysis_summary)
                time_sense = core.get('time_sensitivity', labels['default_time_sensitivity'])
                pos_advice = core.get('position_advice', {})

                report_lines.extend([
                    f"### 📌 {labels['core_conclusion_heading']}",
                    "",
                    f"**{signal_emoji} {signal_text}** | {localize_trend_prediction(result.trend_prediction, report_language)}",
                    "",
                    f"> **{labels['one_sentence_label']}**: {one_sentence}",
                    "",
                    f"⏰ **{labels['time_sensitivity_label']}**: {time_sense}",
                    "",
                ])
                # Position-category advice
                if pos_advice:
                    report_lines.extend([
                        f"| {labels['position_status_label']} | {labels['action_advice_label']} |",
                        "|---------|---------|",
                        f"| 🆕 **{labels['no_position_label']}** | {pos_advice.get('no_position', self._get_display_operation_advice(result, report_language))} |",
                        f"| 💼 **{labels['has_position_label']}** | {pos_advice.get('has_position', labels['continue_holding'])} |",
                        "",
                    ])

                self._append_market_snapshot(report_lines, result)

                # ========== Data insight ==========
                data_persp = dashboard.get('data_perspective', {}) if dashboard else {}
                if data_persp:
                    trend_data = data_persp.get('trend_status', {})
                    price_data = data_persp.get('price_position', {})
                    vol_data = data_persp.get('volume_analysis', {})
                    chip_data = data_persp.get('chip_structure', {})

                    report_lines.extend([
                        f"### 📊 {labels['data_perspective_heading']}",
                        "",
                    ])
                    # Trend status
                    if trend_data:
                        is_bullish = (
                            f"✅ {labels['yes_label']}"
                            if trend_data.get('is_bullish', False)
                            else f"❌ {labels['no_label']}"
                        )
                        report_lines.extend([
                            f"**{labels['ma_alignment_label']}**: {trend_data.get('ma_alignment', 'N/A')} | "
                            f"{labels['bullish_alignment_label']}: {is_bullish} | "
                            f"{labels['trend_strength_label']}: {trend_data.get('trend_score', 'N/A')}/100",
                            "",
                        ])
                    # Price position
                    if price_data:
                        bias_status = price_data.get('bias_status', 'N/A')
                        report_lines.extend([
                            f"| {labels['price_metrics_label']} | {labels['current_price_label']} |",
                            "|---------|------|",
                            f"| {labels['current_price_label']} | {price_data.get('current_price', 'N/A')} |",
                            f"| {labels['ma5_label']} | {price_data.get('ma5', 'N/A')} |",
                            f"| {labels['ma10_label']} | {price_data.get('ma10', 'N/A')} |",
                            f"| {labels['ma20_label']} | {price_data.get('ma20', 'N/A')} |",
                            f"| {labels['bias_ma5_label']} | {price_data.get('bias_ma5', 'N/A')}% {bias_status} |",
                            f"| {labels['support_level_label']} | {price_data.get('support_level', 'N/A')} |",
                            f"| {labels['resistance_level_label']} | {price_data.get('resistance_level', 'N/A')} |",
                            "",
                        ])
                    # Volume analysis
                    if vol_data:
                        report_lines.extend([
                            f"**{labels['volume_label']}**: {labels['volume_ratio_label']} {vol_data.get('volume_ratio', 'N/A')} ({vol_data.get('volume_status', '')}) | "
                            f"{labels['turnover_rate_label']} {vol_data.get('turnover_rate', 'N/A')}%",
                            f"💡 *{vol_data.get('volume_meaning', '')}*",
                            "",
                        ])
                    # Chip structure
                    if chip_data:
                        if is_chip_structure_unavailable(chip_data):
                            report_lines.extend([
                                f"**{labels['chip_label']}**: {get_chip_unavailable_reason(chip_data, report_language)}",
                                "",
                            ])
                        else:
                            chip_health = localize_chip_health(chip_data.get('chip_health', 'N/A'), report_language)
                            report_lines.extend([
                                f"**{labels['chip_label']}**: {chip_data.get('profit_ratio', 'N/A')} | {chip_data.get('avg_cost', 'N/A')} | "
                                f"{chip_data.get('concentration', 'N/A')} {chip_health}",
                                "",
                            ])
                    else:
                        chip_unavailable_reason = get_chip_unavailable_reason(data_persp, report_language)
                        if chip_unavailable_reason:
                            report_lines.extend([
                                f"**{labels['chip_label']}**: {chip_unavailable_reason}",
                                "",
                            ])

                self._append_phase_decision_block(report_lines, dashboard, labels)

                # ========== Action plan ==========
                battle = dashboard.get('battle_plan', {}) if dashboard else {}
                if battle:
                    report_lines.extend([
                        f"### 🎯 {labels['battle_plan_heading']}",
                        "",
                    ])
                    # Entry levels
                    sniper = battle.get('sniper_points', {})
                    if sniper:
                        report_lines.extend([
                            f"**📍 {labels['action_points_heading']}**",
                            "",
                            f"| {labels['action_points_heading']} | {labels['current_price_label']} |",
                            "|---------|------|",
                            f"| 🎯 {labels['ideal_buy_label']} | {self._clean_sniper_value(sniper.get('ideal_buy', 'N/A'))} |",
                            f"| 🔵 {labels['secondary_buy_label']} | {self._clean_sniper_value(sniper.get('secondary_buy', 'N/A'))} |",
                            f"| 🛑 {labels['stop_loss_label']} | {self._clean_sniper_value(sniper.get('stop_loss', 'N/A'))} |",
                            f"| 🎊 {labels['take_profit_label']} | {self._clean_sniper_value(sniper.get('take_profit', 'N/A'))} |",
                            "",
                        ])
                    # Position strategy
                    position = battle.get('position_strategy', {})
                    if position:
                        report_lines.extend([
                            f"**💰 {labels['suggested_position_label']}**: {position.get('suggested_position', 'N/A')}",
                            f"- {labels['entry_plan_label']}: {position.get('entry_plan', 'N/A')}",
                            f"- {labels['risk_control_label']}: {position.get('risk_control', 'N/A')}",
                            "",
                        ])
                    # Checklist
                    checklist = battle.get('action_checklist', []) if battle else []
                    if checklist:
                        report_lines.extend([
                            f"**✅ {labels['checklist_heading']}**",
                            "",
                        ])
                        for item in checklist:
                            report_lines.append(f"- {item}")
                        report_lines.append("")

                # ========== Signal attribution ==========
                signal_attr = dashboard.get('signal_attribution', {}) if dashboard else {}
                if signal_attribution_has_content(signal_attr):
                    report_lines.extend([
                        f"### 🎯 {labels['signal_attribution_heading']}",
                        "",
                    ])
                    weight_items = signal_attribution_weight_items(signal_attr)
                    if weight_items:
                        report_lines.append(f"**{labels['attribution_weights_label']}**:")
                        weight_labels = {
                            "technical_indicators": ("📈", labels['technical_indicators_label']),
                            "news_sentiment": ("📰", labels['news_sentiment_label']),
                            "fundamentals": ("📊", labels['fundamentals_label']),
                            "market_conditions": ("🌐", labels['market_conditions_label']),
                        }
                        for key, value in weight_items:
                            icon, label = weight_labels[key]
                            report_lines.append(f"- {icon} {label}: {value}%")
                        report_lines.append("")

                    # Strongest signal
                    if signal_attr.get('strongest_bullish_signal'):
                        report_lines.append(f"**🐂 {labels['strongest_bullish_signal_label']}**: {signal_attr['strongest_bullish_signal']}")
                    if signal_attr.get('strongest_bearish_signal'):
                        report_lines.append(f"**🐻 {labels['strongest_bearish_signal_label']}**: {signal_attr['strongest_bearish_signal']}")
                    report_lines.append("")

                # ========== Multi-strategy roll-up ==========
                strategy_synthesis = normalize_strategy_synthesis_payload(
                    dashboard.get('strategy_synthesis') if dashboard else None
                )
                _append_strategy_synthesis_block(report_lines, strategy_synthesis, labels, report_language)

                # 财务摘要 / 股东回报 / 关联板块 (each subsection hides itself when its data is missing)
                self._append_fundamental_blocks(report_lines, result)

                # Fall back to the legacy layout when there is no dashboard
                if not dashboard:
                    # Operation reasoning
                    if result.buy_reason:
                        report_lines.extend([
                            f"**💡 {reason_label}**: {result.buy_reason}",
                            "",
                        ])
                    # Risk warning
                    if result.risk_warning:
                        report_lines.extend([
                            f"**⚠️ {risk_warning_label}**: {result.risk_warning}",
                            "",
                        ])
                    # Technical analysis
                    if result.ma_analysis or result.volume_analysis:
                        report_lines.extend([
                            f"### 📊 {technical_heading}",
                            "",
                        ])
                        if result.ma_analysis:
                            report_lines.append(f"**{ma_label}**: {result.ma_analysis}")
                        if result.volume_analysis:
                            report_lines.append(f"**{volume_analysis_label}**: {result.volume_analysis}")
                        report_lines.append("")
                    # News dimension
                    news_disclosure = self._empty_news_disclosure(result, report_language)
                    if result.news_summary or news_disclosure:
                        report_lines.append(f"### 📰 {news_heading}")
                        if news_disclosure:
                            report_lines.append(news_disclosure)
                        if result.news_summary:
                            report_lines.append(f"{result.news_summary}")
                        report_lines.append("")

                if self._append_data_sources_line(report_lines, result, labels):
                    report_lines.append("")

                report_lines.extend([
                    "---",
                    "",
                ])

        # Footer (the disclaimer is dropped)
        report_lines.extend([
            "",
            f"*{labels['generated_at_label']}{labels['label_colon']}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        models = self._collect_models_used(results)
        if models:
            report_lines.append(f"*{labels['analysis_model_label']}{labels['label_colon']}{', '.join(models)}*")

        return "\n".join(report_lines)

    def generate_brief_report(
        self,
        results: List[AnalysisResult],
        report_date: Optional[str] = None,
    ) -> str:
        """
        Generate brief report (3-5 sentences per stock) for mobile/push.

        Args:
            results: Analysis results list (use [result] for single stock).
            report_date: Report date (default: today).

        Returns:
            Brief markdown content.
        """
        if report_date is None:
            report_date = datetime.now().strftime('%Y-%m-%d')
        report_language = self._get_report_language(results)
        labels = get_report_labels(report_language)
        config = get_config()
        if getattr(config, 'report_renderer_enabled', False) and results:
            from src.services.report_renderer import render
            out = render(
                platform='brief',
                results=results,
                report_date=report_date,
                summary_only=False,
                extra_context={"report_language": report_language},
            )
            if out:
                return out
        # Fallback: brief summary from dashboard report
        if not results:
            return f"# {report_date} {labels['brief_title']}\n\n{labels['no_results']}"
        sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
        buy_count, sell_count, hold_count = self._count_display_decisions(results, report_language)
        lines = [
            f"# {report_date} {labels['brief_title']}",
            "",
            f"> {len(results)} {labels['stock_unit_compact']} | 🟢{buy_count} 🟡{hold_count} 🔴{sell_count}",
        ]
        self._append_market_status_line(lines, results, report_language)
        for r in sorted_results:
            signal_text, emoji, _ = self._get_signal_level(r)
            name = self._get_display_name(r, report_language)
            dash = r.dashboard or {}
            core = dash.get('core_conclusion', {}) or {}
            one = (core.get('one_sentence') or r.analysis_summary or '')[:60]
            lines.append(
                f"**{name}({r.code})** {emoji} "
                f"{signal_text} | "
                f"{labels['score_label']} {r.sentiment_score} | {one}"
            )
            news_disclosure = self._empty_news_disclosure(r, report_language)
            if news_disclosure:
                lines.append(news_disclosure)
            if self._append_data_sources_line(lines, r, labels):
                lines.append("")
        lines.append("")
        lines.append(f"*{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        models = self._collect_models_used(results)
        if models:
            lines.append(f"*{labels['analysis_model_label']}: {', '.join(models)}*")
        return "\n".join(lines)

    def generate_single_stock_report(self, result: AnalysisResult) -> str:
        """
        Generate the analysis report for a single stock (for per-stock push mode, #55)

        Condensed but complete, suited to pushing as soon as each stock finishes

        Args:
            result: the analysis result for one stock

        Returns:
            The Markdown single-stock report
        """
        report_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        report_language = self._get_report_language(result)
        labels = get_report_labels(report_language)
        signal_text, signal_emoji, _ = self._get_signal_level(result)
        dashboard = result.dashboard if hasattr(result, 'dashboard') and result.dashboard else {}
        core = dashboard.get('core_conclusion', {}) if dashboard else {}
        battle = dashboard.get('battle_plan', {}) if dashboard else {}
        intel = dashboard.get('intelligence', {}) if dashboard else {}

        # Stock name (escaping *ST and similar)
        stock_name = self._get_display_name(result, report_language)

        lines = [
            f"## {signal_emoji} {stock_name} ({result.code})",
            "",
            f"> {report_date} | {labels['score_label']}: **{result.sentiment_score}** | {localize_trend_prediction(result.trend_prediction, report_language)}",
            "",
        ]

        excerpt = self._public_phase_pack_excerpt(result, report_language)
        if excerpt:
            lines.extend([excerpt, ""])

        self._append_market_snapshot(lines, result)

        # Headline decision (one sentence)
        one_sentence = core.get('one_sentence', result.analysis_summary) if core else result.analysis_summary
        if one_sentence:
            lines.extend([
                f"### 📌 {labels['core_conclusion_heading']}",
                "",
                f"**{signal_text}**: {one_sentence}",
                "",
            ])

        # Key information (sentiment plus fundamentals)
        info_added = False
        news_disclosure = self._empty_news_disclosure(result, report_language)
        if news_disclosure:
            lines.append(f"### 📰 {labels['info_heading']}")
            lines.append("")
            lines.append(news_disclosure)
            info_added = True
        if intel:
            if intel.get('earnings_outlook'):
                if not info_added:
                    lines.append(f"### 📰 {labels['info_heading']}")
                    lines.append("")
                    info_added = True
                lines.append(f"📊 **{labels['earnings_outlook_label']}**: {str(intel['earnings_outlook'])[:100]}")

            if intel.get('sentiment_summary'):
                if not info_added:
                    lines.append(f"### 📰 {labels['info_heading']}")
                    lines.append("")
                    info_added = True
                lines.append(f"💭 **{labels['sentiment_summary_label']}**: {str(intel['sentiment_summary'])[:80]}")

            # Risk alerts
            risks = intel.get('risk_alerts', [])
            if risks:
                if not info_added:
                    lines.append(f"### 📰 {labels['info_heading']}")
                    lines.append("")
                    info_added = True
                lines.append("")
                lines.append(f"🚨 **{labels['risk_alerts_label']}**:")
                for risk in risks[:3]:
                    lines.append(f"- {str(risk)[:60]}")

            # Positive catalysts
            catalysts = intel.get('positive_catalysts', [])
            if catalysts:
                lines.append("")
                lines.append(f"✨ **{labels['positive_catalysts_label']}**:")
                for cat in catalysts[:3]:
                    lines.append(f"- {str(cat)[:60]}")

        if info_added:
            lines.append("")

        # Entry levels
        sniper = battle.get('sniper_points', {}) if battle else {}
        if sniper:
            lines.extend([
                f"### 🎯 {labels['action_points_heading']}",
                "",
                f"| {labels['ideal_buy_label']} | {labels['stop_loss_label']} | {labels['take_profit_label']} |",
                "|------|------|------|",
            ])
            ideal_buy = sniper.get('ideal_buy', '-')
            stop_loss = sniper.get('stop_loss', '-')
            take_profit = sniper.get('take_profit', '-')
            lines.append(f"| {ideal_buy} | {stop_loss} | {take_profit} |")
            lines.append("")

        # ========== Signal attribution ==========
        signal_attr = dashboard.get('signal_attribution', {}) if dashboard else {}
        if signal_attribution_has_content(signal_attr):
            lines.extend([
                f"### 🎯 {labels.get('signal_attribution_heading', '信号归因分析')}",
                "",
            ])
            # Attribution weights
            weight_items = signal_attribution_weight_items(signal_attr)
            if weight_items:
                lines.append(f"**{labels.get('attribution_weights_label', '归因权重')}**:")
                weight_labels = {
                    "technical_indicators": ("📈", labels.get('technical_indicators_label', '技术指标')),
                    "news_sentiment": ("📰", labels.get('news_sentiment_label', '新闻舆情')),
                    "fundamentals": ("📊", labels.get('fundamentals_label', '基本面')),
                    "market_conditions": ("🌐", labels.get('market_conditions_label', '市场环境')),
                }
                for key, value in weight_items:
                    icon, label = weight_labels[key]
                    lines.append(f"- {icon} {label}: {value}%")
                lines.append("")

            # Strongest signal
            bullish = signal_attr.get('strongest_bullish_signal')
            bearish = signal_attr.get('strongest_bearish_signal')
            if bullish:
                lines.append(f"**🐂 {labels.get('strongest_bullish_signal_label', '最强看多信号')}**: {bullish}")
            if bearish:
                lines.append(f"**🐻 {labels.get('strongest_bearish_signal_label', '最强看空信号')}**: {bearish}")
            lines.append("")

        # Position advice
        pos_advice = core.get('position_advice', {}) if core else {}
        if pos_advice:
            lines.extend([
                f"### 💼 {labels['position_advice_heading']}",
                "",
                f"- 🆕 **{labels['no_position_label']}**: {pos_advice.get('no_position', self._get_display_operation_advice(result, report_language))}",
                f"- 💼 **{labels['has_position_label']}**: {pos_advice.get('has_position', labels['continue_holding'])}",
                "",
            ])

        # 财务摘要 / 股东回报 / 关联板块 (each subsection hides itself when its data is missing)
        self._append_fundamental_blocks(lines, result)

        lines.append("---")
        if self._should_show_llm_model():
            model_used = normalize_model_used(getattr(result, "model_used", None))
            if model_used:
                lines.append(f"*{labels['analysis_model_label']}: {model_used}*")
        lines.append(f"*{labels['not_investment_advice']}*")

        return "\n".join(lines)

    # Display name mapping for realtime data sources
    _SOURCE_DISPLAY_NAMES = {
        "stooq": "Stooq",
        "longbridge": "Longbridge",
        "fallback": "Fallback",
    }

    def _get_source_display_name(self, source: Any, language: Optional[str]) -> str:
        raw_source = str(source or "N/A")
        return self._SOURCE_DISPLAY_NAMES.get(raw_source, raw_source)

    def _append_market_snapshot(self, lines: List[str], result: AnalysisResult) -> None:
        snapshot = getattr(result, 'market_snapshot', None)
        if not snapshot:
            return

        report_language = self._get_report_language(result)
        labels = get_report_labels(report_language)

        lines.extend([
            f"### 📈 {labels['market_snapshot_heading']}",
            "",
            f"| {labels['close_label']} | {labels['prev_close_label']} | {labels['open_label']} | {labels['high_label']} | {labels['low_label']} | {labels['change_pct_label']} | {labels['change_amount_label']} | {labels['amplitude_label']} | {labels['volume_label']} | {labels['amount_label']} |",
            "|------|------|------|------|------|-------|-------|------|--------|--------|",
            f"| {snapshot.get('close', 'N/A')} | {snapshot.get('prev_close', 'N/A')} | "
            f"{snapshot.get('open', 'N/A')} | {snapshot.get('high', 'N/A')} | "
            f"{snapshot.get('low', 'N/A')} | {snapshot.get('pct_chg', 'N/A')} | "
            f"{snapshot.get('change_amount', 'N/A')} | {snapshot.get('amplitude', 'N/A')} | "
            f"{snapshot.get('volume', 'N/A')} | {snapshot.get('amount', 'N/A')} |",
        ])

        if "price" in snapshot:
            display_source = self._get_source_display_name(snapshot.get('source', 'N/A'), report_language)
            lines.extend([
                "",
                f"| {labels['current_price_label']} | {labels['volume_ratio_label']} | {labels['turnover_rate_label']} | {labels['source_label']} |",
                "|-------|------|--------|----------|",
                f"| {snapshot.get('price', 'N/A')} | {snapshot.get('volume_ratio', 'N/A')} | "
                f"{snapshot.get('turnover_rate', 'N/A')} | {display_source} |",
            ])

        lines.append("")

    @staticmethod
    def _format_percent(value: Any) -> str:
        try:
            return f"{float(value):.2f}%"
        except (TypeError, ValueError):
            return "N/A"

    @staticmethod
    def _format_text(value: Any) -> str:
        if value is None:
            return "N/A"
        text = str(value).strip()
        return text if text else "N/A"

    def _get_fundamental_blocks(self, result: AnalysisResult) -> Dict[str, Any]:
        """Extract financial_report / dividend / belong_boards / board rankings.

        Falls back to empty containers when fundamental_context is missing or partial,
        so callers can rely on dict shape without re-checking types.
        """
        ctx = getattr(result, "fundamental_context", None)
        if not isinstance(ctx, dict):
            return {
                "financial_report": {},
                "growth": {},
                "dividend": {},
                "belong_boards": [],
                "sector_top": [],
                "sector_bottom": [],
                "concept_top": [],
                "concept_bottom": [],
            }

        earnings_block = ctx.get("earnings") if isinstance(ctx.get("earnings"), dict) else {}
        earnings_data = earnings_block.get("data") if isinstance(earnings_block.get("data"), dict) else {}
        financial_report = earnings_data.get("financial_report") if isinstance(earnings_data.get("financial_report"), dict) else {}
        dividend = earnings_data.get("dividend") if isinstance(earnings_data.get("dividend"), dict) else {}

        growth_block = ctx.get("growth") if isinstance(ctx.get("growth"), dict) else {}
        growth_data = growth_block.get("data") if isinstance(growth_block.get("data"), dict) else {}

        boards_block = ctx.get("boards") if isinstance(ctx.get("boards"), dict) else {}
        boards_data = boards_block.get("data") if isinstance(boards_block.get("data"), dict) else {}
        sector_top = boards_data.get("top") if isinstance(boards_data.get("top"), list) else []
        sector_bottom = boards_data.get("bottom") if isinstance(boards_data.get("bottom"), list) else []
        concept_block = ctx.get("concept_boards") if isinstance(ctx.get("concept_boards"), dict) else {}
        if not concept_block and isinstance(ctx.get("concepts"), dict):
            concept_block = ctx.get("concepts")
        if not concept_block and isinstance(ctx.get("concept_rankings"), dict):
            concept_block = ctx.get("concept_rankings")
        concept_data = concept_block.get("data") if isinstance(concept_block.get("data"), dict) else concept_block
        if not isinstance(concept_data, dict):
            concept_data = {}
        concept_top = concept_data.get("top") if isinstance(concept_data.get("top"), list) else []
        concept_bottom = concept_data.get("bottom") if isinstance(concept_data.get("bottom"), list) else []

        belong_boards = ctx.get("belong_boards") if isinstance(ctx.get("belong_boards"), list) else []

        return {
            "financial_report": financial_report,
            "growth": growth_data,
            "dividend": dividend,
            "belong_boards": belong_boards,
            "sector_top": sector_top,
            "sector_bottom": sector_bottom,
            "concept_top": concept_top,
            "concept_bottom": concept_bottom,
        }

    def _append_fundamental_blocks(self, lines: List[str], result: AnalysisResult) -> None:
        """Append 财务摘要 / 股东回报 / 关联板块 markdown blocks.

        Each block is only rendered when at least one cell has data; this keeps
        the email compact when the fundamental pipeline returned partial/failed
        results (e.g. HK/US markets, ETF, or provider outages).
        """
        blocks = self._get_fundamental_blocks(result)
        report_language = self._get_report_language(result)
        labels = get_report_labels(report_language)

        self._append_financial_summary(lines, blocks, labels, report_language)
        self._append_shareholder_return(lines, blocks, labels, report_language)
        self._append_related_boards(lines, blocks, labels)

    def _append_financial_summary(
        self,
        lines: List[str],
        blocks: Dict[str, Any],
        labels: Dict[str, str],
        report_language: Optional[str] = None,
    ) -> None:
        report = blocks.get("financial_report") or {}
        growth = blocks.get("growth") or {}
        currency = report.get("currency") if isinstance(report.get("currency"), str) else None
        cells = {
            "report_date": self._format_text(report.get("report_date")),
            "revenue": format_money_amount(report.get("revenue"), currency, report_language),
            "net_profit": format_money_amount(report.get("net_profit_parent"), currency, report_language),
            "operating_cash_flow": format_money_amount(report.get("operating_cash_flow"), currency, report_language),
            "roe": self._format_percent(report.get("roe") if report.get("roe") is not None else growth.get("roe")),
            "revenue_yoy": self._format_percent(growth.get("revenue_yoy")),
            "net_profit_yoy": self._format_percent(growth.get("net_profit_yoy")),
            "gross_margin": self._format_percent(growth.get("gross_margin")),
        }
        if all(v == "N/A" for v in cells.values()):
            return

        lines.extend([
            f"### 💼 {labels['financial_summary_heading']}",
            "",
            (
                f"| {labels['report_date_label']} | {labels['revenue_label']} | "
                f"{labels['net_profit_label']} | {labels['operating_cash_flow_label']} | "
                f"{labels['roe_label']} | {labels['revenue_yoy_label']} | "
                f"{labels['net_profit_yoy_label']} | {labels['gross_margin_label']} |"
            ),
            # Report period centred, amounts and ratios right-aligned - matching the existing market snapshot style
            "|:------:|-------:|-------:|-------:|------:|------:|------:|------:|",
            (
                f"| {cells['report_date']} | {cells['revenue']} | {cells['net_profit']} | "
                f"{cells['operating_cash_flow']} | {cells['roe']} | {cells['revenue_yoy']} | "
                f"{cells['net_profit_yoy']} | {cells['gross_margin']} |"
            ),
            "",
        ])

    def _append_shareholder_return(
        self,
        lines: List[str],
        blocks: Dict[str, Any],
        labels: Dict[str, str],
        report_language: Optional[str] = None,
    ) -> None:
        dividend = blocks.get("dividend") or {}
        report = blocks.get("financial_report") or {}
        # Dividends are paid in the trading currency (yfinance `info.currency`)
        # which can differ from the financial-statement currency (e.g. HK ADRs
        # often report `financialCurrency=CNY` but pay dividends in HKD).
        dividend_currency = dividend.get("currency") if isinstance(dividend.get("currency"), str) else None
        if not dividend_currency:
            dividend_currency = report.get("currency") if isinstance(report.get("currency"), str) else None
        events = dividend.get("events") if isinstance(dividend.get("events"), list) else []
        latest_event = events[0] if events else {}
        if not isinstance(latest_event, dict):
            latest_event = {}

        ttm_event_count = dividend.get("ttm_event_count")
        cells = {
            "ttm_cash": format_per_share_amount(
                dividend.get("ttm_cash_dividend_per_share"), dividend_currency, report_language
            ),
            "ttm_count": str(ttm_event_count) if isinstance(ttm_event_count, int) else "N/A",
            "ttm_yield": self._format_percent(dividend.get("ttm_dividend_yield_pct")),
            "latest_ex": self._format_text(latest_event.get("ex_dividend_date") or latest_event.get("event_date")),
        }
        if all(v == "N/A" for v in cells.values()):
            return

        lines.extend([
            f"### 💵 {labels['shareholder_return_heading']}",
            "",
            (
                f"| {labels['ttm_cash_dividend_label']} | {labels['ttm_event_count_label']} | "
                f"{labels['ttm_dividend_yield_label']} | {labels['latest_ex_dividend_label']} |"
            ),
            "|---------------------:|----------:|--------:|:--------:|",
            (
                f"| {cells['ttm_cash']} | {cells['ttm_count']} | "
                f"{cells['ttm_yield']} | {cells['latest_ex']} |"
            ),
            "",
        ])

    def _append_related_boards(
        self,
        lines: List[str],
        blocks: Dict[str, Any],
        labels: Dict[str, str],
    ) -> None:
        belong_boards = blocks.get("belong_boards") or []
        if not belong_boards:
            return

        sector_signals: Dict[str, Tuple[str, float]] = {}
        concept_signals: Dict[str, Tuple[str, float]] = {}

        def add_signals(target: Dict[str, Tuple[str, float]], rows: Any, label: str) -> None:
            for item in rows or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name or name in target:
                    continue
                change_pct = _safe_float(item.get("change_pct"))
                if change_pct is not None:
                    target[name] = (label, change_pct)

        add_signals(sector_signals, blocks.get("sector_top"), labels["leading_board_label"])
        add_signals(sector_signals, blocks.get("sector_bottom"), labels["lagging_board_label"])
        add_signals(concept_signals, blocks.get("concept_top"), labels["leading_board_label"])
        add_signals(concept_signals, blocks.get("concept_bottom"), labels["lagging_board_label"])

        def resolve_board_type(name: str, board_type: str) -> str:
            normalized_type = board_type.strip().lower()
            sector_signal = sector_signals.get(name)
            concept_signal = concept_signals.get(name)
            if concept_signal and not sector_signal:
                return "concept"
            if sector_signal and not concept_signal:
                return "sector"

            normalized_name = name.strip().lower()
            if any(marker in normalized_name for marker in ("概念", "题材", "concept", "theme")):
                return "concept"
            if any(marker in normalized_name for marker in ("行业", "industry", "sector")):
                return "sector"

            if normalized_type in {"概念", "概念板块", "题材", "concept", "theme"}:
                return "concept"
            if normalized_type in {"行业", "行业板块", "industry", "sector"}:
                return "sector"
            # A-share belong_boards may omit type for concept/theme labels.
            # Keep a deterministic display type instead of leaking N/A.
            return "concept"

        def resolve_signal(name: str, board_group: str) -> Tuple[Optional[str], Optional[float]]:
            if board_group == "sector":
                return sector_signals.get(name, (None, None))
            if board_group == "concept":
                return concept_signals.get(name, (None, None))
            sector_signal = sector_signals.get(name)
            concept_signal = concept_signals.get(name)
            if sector_signal and not concept_signal:
                return sector_signal
            if concept_signal and not sector_signal:
                return concept_signal
            return None, None

        def board_type_label(board_group: str) -> str:
            if board_group == "sector":
                return labels["industry_boards_heading"]
            return labels["concept_boards_heading"]

        # Pre-resolve rows so signal-bearing boards can show their own
        # percentage, while boards without a matching change stay plain.
        prepared: List[Tuple[str, str, Optional[str], Optional[float]]] = []
        for raw in belong_boards[:5]:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            board_type = self._format_text(raw.get("type"))
            board_group = resolve_board_type(name, board_type)
            status_text, change_pct = resolve_signal(name, board_group)
            prepared.append((name, board_type_label(board_group), status_text, change_pct))

        if not prepared:
            return

        lines.append(f"### 🧩 {labels['related_boards_heading']}")
        lines.append("")
        has_signal = any(status is not None and change_pct is not None for _, _, status, change_pct in prepared)
        if has_signal:
            for name, board_type, status_text, change_pct in prepared:
                details = []
                if status_text is not None and change_pct is not None:
                    details.append(f"{board_type} {status_text} {change_pct:+.2f}%")
                suffix = f" ({', '.join(details)})" if details else ""
                lines.append(f"- {name}{suffix}")
        else:
            lines.append(" / ".join(name for name, _, _, _ in prepared))
        lines.append("")

    def _should_use_image_for_channel(
        self, channel: NotificationChannel, image_bytes: Optional[bytes]
    ) -> bool:
        """
        Decide whether to send as image for the given channel (Issue #289).

        Fallback rules (send as Markdown text instead of image):
        - image_bytes is None: conversion failed / imgkit not installed / content over max_chars
        """
        if channel.value not in self._markdown_to_image_channels or image_bytes is None:
            return False
        return True

    @staticmethod
    def _sanitize_notification_diagnostics(text: Any) -> str:
        return sanitize_diagnostic_text(text)

    def _send_to_static_channel(
        self,
        channel: NotificationChannel,
        content: str,
        *,
        image_bytes: Optional[bytes],
        email_stock_codes: Optional[List[str]],
        email_send_to_all: bool,
        route_type: Optional[str] = None,
    ) -> bool:
        use_image = self._should_use_image_for_channel(channel, image_bytes)
        sanitized_content = strip_hidden_markdown_metadata(content).strip()
        if channel == NotificationChannel.TELEGRAM:
            if use_image:
                return self._send_telegram_photo(image_bytes)
            return self.send_to_telegram(content)
        if channel == NotificationChannel.EMAIL:
            receivers = None
            if email_send_to_all and self._stock_email_groups:
                receivers = self.get_all_email_receivers()
            elif email_stock_codes and self._stock_email_groups:
                receivers = self.get_receivers_for_stocks(email_stock_codes)
            if use_image:
                return self._send_email_with_inline_image(image_bytes, receivers=receivers)
            return self.send_to_email(
                sanitized_content,
                receivers=receivers,
            )
        if channel == NotificationChannel.PUSHOVER:
            return self.send_to_pushover(content)
        if channel == NotificationChannel.NTFY:
            return self.send_to_ntfy(sanitized_content)
        if channel == NotificationChannel.GOTIFY:
            return self.send_to_gotify(sanitized_content)
        if channel == NotificationChannel.CUSTOM:
            if use_image:
                return self._send_custom_webhook_image(image_bytes, fallback_content=content)
            return self.send_to_custom(sanitized_content)
        if channel == NotificationChannel.DISCORD:
            return self.send_to_discord(content)
        if channel == NotificationChannel.SLACK:
            if use_image:
                return self._send_slack_image(image_bytes, fallback_content=content)
            return self.send_to_slack(content)
        if channel == NotificationChannel.ASTRBOT:
            return self.send_to_astrbot(sanitized_content)
        logger.warning(f"Unsupported notification channel: {channel}")
        return False

    def send_with_results(
        self,
        content: str,
        email_stock_codes: Optional[List[str]] = None,
        email_send_to_all: bool = False,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
        structured_payload: Optional[Dict[str, Any]] = None,
    ) -> NotificationDispatchResult:
        """
        Send a notification and return per-channel diagnostics.

        ``send()`` keeps the historical bool API and delegates here.

        Fallback rules (Markdown-to-image, Issue #289):
        - When image_bytes is None (conversion failed / imgkit not installed /
          content over max_chars): all channels configured for image will send
          as Markdown text instead.

        Args:
            content: the message content (Markdown)
            email_stock_codes: the stock code list (optional; routes the email channel to the matching group mailbox, Issue #268)
            email_send_to_all: whether the email goes to every configured mailbox (for content with no stock owner, such as the broad-market review)
            route_type: the notification route type; None keeps the legacy behaviour, while report/alert/system_error filter static channels per configuration
            severity: the notification severity; inferred from the route type when unset
            dedup_key: an optional stable deduplication key; the content hash is used when unset
            cooldown_key: an optional cooldown key; the route/severity default is used when unset
            structured_payload: the optional per-stock or market structured result, used only to fill the image template precisely

        Returns:
            Structured dispatch diagnostics.
        """
        context_success = self.send_to_context(content)
        if not self.should_broadcast_static_channels():
            if context_success:
                logger.info("Pushed through the context session; skipping the static notification channels")
                return NotificationDispatchResult(
                    dispatched=True,
                    success=True,
                    status="sent",
                    channel_results=[ChannelAttemptResult(channel="__context__", success=True)],
                )
            logger.warning("Interactive context push failed; skipped the static notification channels")
            return NotificationDispatchResult(
                dispatched=True,
                success=False,
                status="all_failed",
                channel_results=[
                    ChannelAttemptResult(
                        channel="__context__",
                        success=False,
                        error_code="send_failed",
                        retryable=True,
                    )
                ],
                message="interactive context delivery failed; static channels skipped",
            )

        if not self._available_channels:
            if context_success:
                logger.info("Pushed through the message context channel (no other notification channels)")
                return NotificationDispatchResult(
                    dispatched=True,
                    success=True,
                    status="sent",
                    channel_results=[ChannelAttemptResult(channel="__context__", success=True)],
                )
            logger.warning("Notification service unavailable, skipping the push")
            return NotificationDispatchResult(
                dispatched=False,
                success=False,
                status="no_channel",
                message="notification service unavailable",
            )

        target_channels = self.get_channels_for_route(route_type)
        if not target_channels:
            if context_success:
                logger.info("Pushed through the message context channel (no other notification channels after routing)")
                return NotificationDispatchResult(
                    dispatched=True,
                    success=True,
                    status="sent",
                    channel_results=[ChannelAttemptResult(channel="__context__", success=True)],
                )
            logger.warning("Notification route %s matched no configured channel; skipping the static notification channels", route_type)
            return NotificationDispatchResult(
                dispatched=False,
                success=False,
                status="no_channel",
                message=f"notification route {route_type} has no configured channel",
            )

        noise_decision = self.evaluate_noise_control(
            content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
        )
        if not noise_decision.should_send:
            logger.info(noise_decision.message)
            status = "sent" if context_success else "noise_suppressed"
            results = [ChannelAttemptResult(channel="__context__", success=True)] if context_success else []
            return NotificationDispatchResult(
                dispatched=bool(context_success),
                success=bool(context_success),
                status=status,
                channel_results=results,
                message=noise_decision.message,
            )

        # Markdown to image (Issue #289): convert once if any channel needs it.
        # Per-channel decision via _should_use_image_for_channel (see send() docstring for fallback rules).
        image_bytes = None
        channels_needing_image = {
            ch for ch in target_channels
            if ch.value in self._markdown_to_image_channels
            and ch not in {NotificationChannel.NTFY, NotificationChannel.GOTIFY}
        }
        if channels_needing_image:
            from src.md2img import markdown_to_image
            image_bytes = markdown_to_image(
                content,
                max_chars=self._markdown_to_image_max_chars,
                structured_payload=structured_payload,
            )
            if image_bytes:
                logger.info("Markdown converted to an image; sending the image to %s",
                            [ch.value for ch in channels_needing_image])
            elif channels_needing_image:
                try:
                    from src.config import get_config
                    engine = getattr(get_config(), "md2img_engine", "wkhtmltoimage")
                except Exception:
                    engine = "wkhtmltoimage"
                hint = (
                    "npm i -g markdown-to-file" if engine == "markdown-to-file"
                    else "wkhtmltopdf (apt install wkhtmltopdf / brew install wkhtmltopdf)"
                )
                logger.warning(
                    "Markdown-to-image conversion failed; falling back to text. Check the MARKDOWN_TO_IMAGE_CHANNELS configuration and install %s",
                    hint,
                )

        channel_names = ', '.join(ChannelDetector.get_channel_name(ch) for ch in target_channels)
        logger.info(f"Sending notifications to {len(target_channels)} channels: {channel_names}")

        success_count = 0
        fail_count = 0
        channel_results: List[ChannelAttemptResult] = []

        for channel in target_channels:
            channel_name = ChannelDetector.get_channel_name(channel)
            started_at = time.monotonic()
            try:
                result = self._send_to_static_channel(
                    channel,
                    content,
                    image_bytes=image_bytes,
                    email_stock_codes=email_stock_codes,
                    email_send_to_all=email_send_to_all,
                    route_type=route_type,
                )
                latency_ms = int((time.monotonic() - started_at) * 1000)

                if result:
                    success_count += 1
                else:
                    fail_count += 1
                channel_results.append(
                    ChannelAttemptResult(
                        channel=channel.value,
                        success=bool(result),
                        error_code=None if result else "send_failed",
                        retryable=not bool(result),
                        latency_ms=latency_ms,
                    )
                )

            except Exception as e:
                logger.error(f"{channel_name} send failed: {e}")
                fail_count += 1
                channel_results.append(
                    ChannelAttemptResult(
                        channel=channel.value,
                        success=False,
                        error_code="exception",
                        retryable=True,
                        latency_ms=int((time.monotonic() - started_at) * 1000),
                        diagnostics=self._sanitize_notification_diagnostics(str(e)),
                    )
                )

        logger.info(f"Notifications sent: {success_count} succeeded, {fail_count} failed")
        if success_count > 0:
            self.record_noise_control(noise_decision)
        else:
            self.release_noise_control(noise_decision)
        success = success_count > 0 or context_success
        if success_count > 0 and fail_count > 0:
            status = "partial_failed"
        elif success_count > 0 or context_success:
            status = "sent"
        else:
            status = "all_failed"
        if context_success:
            channel_results.insert(0, ChannelAttemptResult(channel="__context__", success=True))
        return NotificationDispatchResult(
            dispatched=True,
            success=success,
            status=status,
            channel_results=channel_results,
        )

    def send(
        self,
        content: str,
        email_stock_codes: Optional[List[str]] = None,
        email_send_to_all: bool = False,
        route_type: Optional[str] = None,
        severity: Optional[str] = None,
        dedup_key: Optional[str] = None,
        cooldown_key: Optional[str] = None,
        structured_payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Unified send interface - pushes to every configured channel.

        Returns:
            Whether at least one channel sent successfully
        """
        result = self.send_with_results(
            content,
            email_stock_codes=email_stock_codes,
            email_send_to_all=email_send_to_all,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
            structured_payload=structured_payload,
        )
        return bool(result.success)

    def save_report_to_file(
        self,
        content: str,
        filename: Optional[str] = None
    ) -> str:
        """
        Save the daily report to a local file

        Args:
            content: the report content
            filename: the file name (optional; generated from the date by default)

        Returns:
            The saved file path
        """
        from pathlib import Path

        if filename is None:
            date_str = datetime.now().strftime('%Y%m%d')
            filename = f"report_{date_str}.md"

        # Make sure the reports directory exists (under the project root)
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(parents=True, exist_ok=True)

        filepath = reports_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"Daily report saved to: {filepath}")
        return str(filepath)


class NotificationBuilder:
    """
    Notification message builder

    Offers convenient message-building helpers
    """

    @staticmethod
    def build_simple_alert(
        title: str,
        content: str,
        alert_type: str = "info"
    ) -> str:
        """
        Build a simple alert message

        Args:
            title: the title
            content: the content
            alert_type: the type (info, warning, error, success)
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        emoji = emoji_map.get(alert_type, "📢")

        return f"{emoji} **{title}**\n\n{content}"

    @staticmethod
    def build_stock_summary(results: List[AnalysisResult]) -> str:
        """
        Build the stock summary (short form)

        Suited to quick notifications
        """
        report_language = normalize_report_language(
            next((getattr(result, "report_language", None) for result in results if getattr(result, "report_language", None)), None)
        )
        labels = get_report_labels(report_language)
        lines = [f"📊 **{labels['summary_heading']}**", ""]

        for r in sorted(results, key=lambda x: x.sentiment_score, reverse=True):
            display_action = display_action_fields_for_result(
                r,
                report_language=report_language,
            )["action"]
            signal_action = {
                "buy": "buy",
                "add": "buy",
                "hold": "hold",
                "reduce": "reduce",
                "sell": "sell",
                "watch": "watch",
                "avoid": "hold",
                "alert": "sell",
            }.get(display_action)
            display_advice = display_operation_advice_for_result(
                r,
                report_language=report_language,
            )
            signal_text, emoji, _ = get_signal_level(
                signal_action or display_advice,
                r.sentiment_score,
                report_language,
            )
            name = get_localized_stock_name(r.name, r.code, report_language)
            lines.append(
                f"{emoji} {name}({r.code}): {display_advice} | "
                f"{labels['score_label']} {r.sentiment_score}"
            )

        return "\n".join(lines)


# Convenience helpers
def get_notification_service() -> NotificationService:
    """Return the notification service instance"""
    return NotificationService()


def send_daily_report(results: List[AnalysisResult]) -> bool:
    """
    Shortcut for sending the daily report

    Detects the channels and pushes automatically
    """
    service = get_notification_service()

    # Generate the report
    report = service.generate_daily_report(results)

    # Save it locally
    service.save_report_to_file(report)

    # Push to the configured channels (detected automatically)
    return service.send(report)


if __name__ == "__main__":
    # Manual test harness
    logging.basicConfig(level=logging.DEBUG)

    # Mock analysis results
    test_results = [
        AnalysisResult(
            code='AAPL',
            name='Apple Inc.',
            sentiment_score=75,
            trend_prediction='Bullish',
            analysis_summary='Strong technicals and supportive news',
            operation_advice='Buy',
            technical_analysis='Broke above MA20 on rising volume; MACD golden cross',
            news_summary='The company announced a dividend and beat earnings expectations',
            report_language='en',
        ),
        AnalysisResult(
            code='MSFT',
            name='Microsoft Corporation',
            sentiment_score=45,
            trend_prediction='Sideways',
            analysis_summary='Range-bound consolidation; waiting for direction',
            operation_advice='Hold',
            technical_analysis='Moving averages converging; volume shrinking',
            news_summary='No major news recently',
            report_language='en',
        ),
        AnalysisResult(
            code='TSLA',
            name='Tesla, Inc.',
            sentiment_score=35,
            trend_prediction='Bearish',
            analysis_summary='Technicals weakening; watch the risk',
            operation_advice='Sell',
            technical_analysis='Broke below MA10 support on thin volume',
            news_summary='Competition is intensifying and margins are under pressure',
            report_language='en',
        ),
    ]

    service = NotificationService()

    # Show the detected channels
    print("=== Notification channel detection ===")
    print(f"Current channels: {service.get_channel_names()}")
    print(f"Channel list: {service.get_available_channels()}")
    print(f"Service available: {service.is_available()}")

    # Generate the daily report
    print("\n=== Daily report generation test ===")
    report = service.generate_daily_report(test_results)
    print(report)

    # Save it to a file
    print("\n=== Save the daily report ===")
    filepath = service.save_report_to_file(report)
    print(f"Saved: {filepath}")

    # Push test
    if service.is_available():
        print(f"\n=== Push test ({service.get_channel_names()}) ===")
        success = service.send(report)
        print(f"Push result: {'success' if success else 'failed'}")
    else:
        print("\nNo notification channel is configured; skipping the push test")
