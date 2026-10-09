# -*- coding: utf-8 -*-
"""Portfolio CSV import service with extensible parser registry."""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from data_provider.base import canonical_stock_code
from src.repositories.portfolio_repo import PortfolioRepository
from src.services.portfolio_service import (
    PortfolioBusyError,
    PortfolioConflictError,
    PortfolioOversellError,
    PortfolioService,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CsvParserSpec:
    """CSV parser specification for one broker export format.

    ``column_hints`` maps a trade field (``trade_date``, ``symbol``, ``side``, ``quantity``,
    ``price``, ``trade_uid``, ``fee``, ``tax``, ``currency``) to candidate column headers,
    matched case-insensitively. ``fee`` and ``tax`` add up every matching column.
    """

    broker: str
    aliases: Tuple[str, ...]
    display_name: str
    column_hints: Dict[str, Tuple[str, ...]]


GENERIC_CSV_SPEC = CsvParserSpec(
    broker="generic",
    aliases=("csv",),
    display_name="Generic CSV",
    column_hints={
        "trade_date": ("date", "trade date", "transaction date"),
        "symbol": ("symbol", "ticker"),
        "side": ("side", "action", "type"),
        "quantity": ("quantity", "qty", "shares"),
        "price": ("price", "trade price", "average price"),
        "trade_uid": ("trade id", "transaction id", "order id"),
        "fee": ("fee", "fees", "commission"),
        "tax": ("tax", "taxes"),
        "currency": ("currency",),
    },
)

DEFAULT_PARSER_SPECS: Tuple[CsvParserSpec, ...] = (GENERIC_CSV_SPEC,)

_BUY_LABELS = frozenset({"buy", "b", "bought"})
_SELL_LABELS = frozenset({"sell", "s", "sold"})


class PortfolioImportService:
    """Parse broker CSV and commit normalized trade records with dedup."""
    _shared_parser_registry: Dict[str, CsvParserSpec] = {}
    _shared_broker_alias_map: Dict[str, str] = {}
    _shared_registry_initialized: bool = False

    def __init__(
        self,
        *,
        portfolio_service: Optional[PortfolioService] = None,
        repo: Optional[PortfolioRepository] = None,
    ):
        self.portfolio_service = portfolio_service or PortfolioService()
        self.repo = repo or PortfolioRepository()
        self._parser_registry = self.__class__._shared_parser_registry
        self._broker_alias_map = self.__class__._shared_broker_alias_map
        if not self.__class__._shared_registry_initialized:
            self._init_default_parsers()
            self.__class__._shared_registry_initialized = True

    def _init_default_parsers(self) -> None:
        for spec in DEFAULT_PARSER_SPECS:
            self.register_parser(spec)

    def register_parser(self, spec: CsvParserSpec) -> None:
        """Register or replace one broker parser spec."""
        broker = (spec.broker or "").strip().lower()
        if not broker:
            raise ValueError("broker is required")
        new_aliases = tuple(sorted({alias.strip().lower() for alias in spec.aliases if alias}))
        for alias in new_aliases:
            if alias == broker:
                raise ValueError(f"alias '{alias}' cannot be the same as broker id")
            existing_target = self._broker_alias_map.get(alias)
            if existing_target and existing_target != broker:
                raise ValueError(
                    f"alias '{alias}' already registered by broker '{existing_target}'"
                )
        for alias, target in list(self._broker_alias_map.items()):
            if target == broker and alias not in new_aliases:
                self._broker_alias_map.pop(alias, None)
        self._parser_registry[broker] = CsvParserSpec(
            broker=broker,
            aliases=new_aliases,
            display_name=spec.display_name or broker,
            column_hints={
                field: tuple(name.strip().lower() for name in names)
                for field, names in (spec.column_hints or {}).items()
            },
        )
        for alias in self._parser_registry[broker].aliases:
            self._broker_alias_map[alias] = broker

    def list_supported_brokers(self) -> List[Dict[str, Any]]:
        """List canonical broker ids and aliases for frontend selector."""
        items: List[Dict[str, Any]] = []
        for broker in sorted(self._parser_registry.keys()):
            aliases = sorted(alias for alias, target in self._broker_alias_map.items() if target == broker)
            items.append(
                {
                    "broker": broker,
                    "aliases": aliases,
                    "display_name": self._parser_registry[broker].display_name,
                }
            )
        return items

    def parse_trade_csv(
        self,
        *,
        broker: str,
        content: bytes,
    ) -> Dict[str, Any]:
        broker_norm = self._normalize_broker(broker)
        parser_spec = self._parser_registry[broker_norm]
        df = self._read_csv(content)
        df.columns = [str(column).strip().lower() for column in df.columns]

        records: List[Dict[str, Any]] = []
        skipped = 0
        errors: List[str] = []

        for idx, row in df.iterrows():
            normalized = self._normalize_trade_row(row=row, parser_spec=parser_spec)
            if normalized is None:
                skipped += 1
                continue
            try:
                # Keep a stable line-level marker so repeated imports of the same
                # file remain idempotent, while identical split fills on separate
                # CSV lines do not collapse into one dedup key.
                normalized["_source_line_number"] = int(idx) + 2
                normalized["dedup_hash"] = self._build_dedup_hash(normalized)
                records.append(normalized)
            except Exception as exc:  # pragma: no cover - defensive path
                skipped += 1
                errors.append(f"row={idx + 1}: {exc}")

        return {
            "broker": broker_norm,
            "record_count": len(records),
            "skipped_count": skipped,
            "error_count": len(errors),
            "records": records,
            "errors": errors[:20],
        }

    def commit_trade_records(
        self,
        *,
        account_id: int,
        broker: str,
        records: List[Dict[str, Any]],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        broker_norm = self._normalize_broker(broker)

        inserted_count = 0
        duplicate_count = 0
        failed_count = 0
        errors: List[str] = []
        seen_trade_uids: set[str] = set()
        seen_dedup_hashes: set[str] = set()

        for i, record in enumerate(records):
            try:
                trade_uid = (record.get("trade_uid") or "").strip() or None
                dedup_hash = (record.get("dedup_hash") or "").strip()
                if not dedup_hash:
                    dedup_hash = self._build_dedup_hash(record)

                if trade_uid and self.repo.has_trade_uid(account_id, trade_uid):
                    duplicate_count += 1
                    continue
                dedup_hash_to_use: Optional[str] = dedup_hash or None
                if dedup_hash_to_use and self.repo.has_trade_dedup_hash(account_id, dedup_hash_to_use):
                    duplicate_count += 1
                    continue

                if dry_run:
                    if trade_uid and trade_uid in seen_trade_uids:
                        duplicate_count += 1
                        continue
                    if dedup_hash_to_use and dedup_hash_to_use in seen_dedup_hashes:
                        duplicate_count += 1
                        continue
                    inserted_count += 1
                    if trade_uid:
                        seen_trade_uids.add(trade_uid)
                    if dedup_hash_to_use:
                        seen_dedup_hashes.add(dedup_hash_to_use)
                    continue

                trade_date_value = record.get("trade_date")
                if isinstance(trade_date_value, date):
                    trade_date_obj = trade_date_value
                else:
                    trade_date_obj = date.fromisoformat(str(trade_date_value))

                self.portfolio_service.record_trade(
                    account_id=account_id,
                    symbol=str(record["symbol"]),
                    trade_date=trade_date_obj,
                    side=str(record["side"]),
                    quantity=float(record["quantity"]),
                    price=float(record["price"]),
                    fee=float(record.get("fee", 0.0) or 0.0),
                    tax=float(record.get("tax", 0.0) or 0.0),
                    market=record.get("market"),
                    currency=record.get("currency"),
                    trade_uid=trade_uid,
                    dedup_hash=dedup_hash_to_use,
                    note=(record.get("note") or "").strip() or f"csv_import:{broker_norm}",
                )
                inserted_count += 1
            except PortfolioConflictError:
                duplicate_count += 1
            except PortfolioOversellError as exc:
                failed_count += 1
                errors.append(f"idx={i}: {exc}")
            except PortfolioBusyError as exc:
                failed_count += 1
                errors.append(f"idx={i}: portfolio_busy: {exc}")
            except Exception as exc:
                failed_count += 1
                errors.append(f"idx={i}: {exc}")

        return {
            "account_id": account_id,
            "record_count": len(records),
            "inserted_count": inserted_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
            "dry_run": bool(dry_run),
            "errors": errors[:20],
        }

    def _normalize_broker(self, value: str) -> str:
        broker = (value or "").strip().lower()
        broker = self._broker_alias_map.get(broker, broker)
        if broker not in self._parser_registry:
            supported = ", ".join(sorted(self._parser_registry.keys()))
            raise ValueError(f"broker must be one of: {supported}")
        return broker

    @staticmethod
    def _read_csv(content: bytes) -> pd.DataFrame:
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                return pd.read_csv(
                    io.BytesIO(content),
                    encoding=encoding,
                    dtype=str,
                    keep_default_na=False,
                )
            except UnicodeDecodeError:
                continue
        return pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)

    def _normalize_trade_row(
        self,
        *,
        row: Any,
        parser_spec: CsvParserSpec,
    ) -> Optional[Dict[str, Any]]:
        hints = parser_spec.column_hints

        trade_date_obj = self._parse_date(self._pick(row, *hints.get("trade_date", ())))
        if trade_date_obj is None:
            return None

        symbol = canonical_stock_code(str(self._pick(row, *hints.get("symbol", ())) or "").strip())
        if not symbol:
            return None

        side = self._normalize_side(self._pick(row, *hints.get("side", ())))
        if side is None:
            return None

        quantity = self._parse_float(self._pick(row, *hints.get("quantity", ())))
        price = self._parse_float(self._pick(row, *hints.get("price", ())))
        if quantity is None or quantity <= 0 or price is None or price <= 0:
            return None

        fee = self._sum_columns(row, hints.get("fee", ()))
        tax = self._sum_columns(row, hints.get("tax", ()))
        trade_uid = self._pick(row, *hints.get("trade_uid", ()))
        currency = self._pick(row, *hints.get("currency", ()))

        return {
            "trade_date": trade_date_obj,
            "symbol": symbol,
            "side": side,
            "quantity": float(quantity),
            "price": float(price),
            "fee": float(fee),
            "tax": float(tax),
            "trade_uid": (str(trade_uid).strip() if trade_uid is not None else None) or None,
            "currency": self._normalize_currency_label(currency),
        }

    @classmethod
    def _sum_columns(cls, row: Any, columns: Tuple[str, ...]) -> float:
        total = 0.0
        for column in columns:
            value = cls._parse_float(cls._pick(row, column))
            if value is not None:
                total += value
        return total

    @staticmethod
    def _normalize_currency_label(value: Any) -> Optional[str]:
        """Return a three-letter ISO 4217 code from a currency cell, else None.

        Anything that is not a three-letter code returns ``None`` so the account's market
        default applies instead of storing a label that FX lookups cannot use.
        """
        if value is None:
            return None
        code = str(value).strip().upper()
        if len(code) == 3 and code.isascii() and code.isalpha():
            return code
        return None

    @staticmethod
    def _pick(row: Any, *candidates: str) -> Any:
        for name in candidates:
            if name in row.index:
                value = row.get(name)
                if value is not None and str(value).strip() != "" and str(value).strip().lower() != "nan":
                    return value
        return None

    @staticmethod
    def _parse_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text.lower() == "nan":
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return None
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()

    @staticmethod
    def _normalize_side(value: Any) -> Optional[str]:
        text = str(value or "").strip().lower()
        if text in _BUY_LABELS:
            return "buy"
        if text in _SELL_LABELS:
            return "sell"
        return None

    @staticmethod
    def _build_dedup_hash(record: Dict[str, Any]) -> str:
        payload = "|".join(
            [
                str(record.get("trade_date") or ""),
                str(record.get("symbol") or ""),
                str(record.get("side") or ""),
                f"{float(record.get('quantity', 0.0)):.8f}",
                f"{float(record.get('price', 0.0)):.8f}",
                f"{float(record.get('fee', 0.0)):.8f}",
                f"{float(record.get('tax', 0.0)):.8f}",
                str(record.get("currency") or ""),
                str(record.get("_source_line_number") or record.get("source_line_number") or ""),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
