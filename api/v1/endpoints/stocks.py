# -*- coding: utf-8 -*-
"""
===================================
Stock data endpoints
===================================

Responsibilities:
1. POST /api/v1/stocks/extract-from-image extract stock codes from an image
2. POST /api/v1/stocks/parse-import parse CSV/Excel/clipboard input
3. GET /api/v1/stocks/{code}/quote real-time quote endpoint
4. GET /api/v1/stocks/{code}/history historical quote endpoint
"""

import logging
from typing import Optional
import re

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, Depends

from api.deps import get_system_config_service

from api.v1.schemas.stocks import (
    ExtractFromImageResponse,
    ExtractItem,
    KLineData,
    StockHistoryResponse,
    StockProfileResponse,
    StockQuote,
)
from api.v1.schemas.history import WatchlistRequest, WatchlistResponse
from api.v1.schemas.common import ErrorResponse
from src.services.image_stock_extractor import (
    ALLOWED_MIME,
    MAX_SIZE_BYTES,
    extract_stock_codes_from_image,
)
from src.services.import_parser import (
    MAX_FILE_BYTES,
    parse_import_from_bytes,
    parse_import_from_text,
)
from src.services.stock_service import StockService
from src.services.stock_profile_service import InvalidStockProfileCode, StockProfileService
from src.services.run_diagnostics import sanitize_diagnostic_text
from src.services.stock_list_parser import split_stock_list
from src.services.system_config_service import SystemConfigService
from data_provider.base import normalize_stock_code

logger = logging.getLogger(__name__)

router = APIRouter()

# Must be declared before the /{stock_code} route
ALLOWED_MIME_STR = ", ".join(ALLOWED_MIME)


def _read_watchlist_codes(service: SystemConfigService) -> list:
    """Read STOCK_LIST codes as-is (no normalization)."""
    config_data = service.get_config(include_schema=False)
    stock_list_str = ""
    for item in config_data.get("items", []):
        if item.get("key") == "STOCK_LIST":
            stock_list_str = str(item.get("value", ""))
            break
    return split_stock_list(stock_list_str)


def _write_watchlist_codes(service: SystemConfigService, codes: list) -> None:
    """Persist stock codes to STOCK_LIST as-is (no normalization)."""
    config_data = service.get_config(include_schema=False)
    config_version = config_data.get("config_version", "")
    service.update(
        config_version=config_version,
        items=[{"key": "STOCK_LIST", "value": ",".join(codes)}],
        mask_token="******",
        reload_now=True,
    )


# Stock code validation patterns (aligned with frontend validateStockCode)
_STOCK_CODE_RE = re.compile(
    r"^(?:\d{6}"                              # A-share 6-digit
    r"|(?:SH|SZ|BJ)\d{6}"                     # exchange-prefixed A-share
    r"|\d{6}\.(?:SH|SZ|SS|BJ)"                # exchange-suffixed A-share
    r"|\d{1,5}\.HK"                           # HK suffix format
    r"|HK\d{1,5}"                             # HK prefix format
    r"|\d{5}"                                 # bare 5-digit HK code
    r"|[A-Z]{1,5}(?:\.(?:US|[A-Z]))?"         # US ticker
    r"|[A-Z0-9]{1,6}(?:-[A-Z]{1,2})?\.(?:TO|V|CN|NE)"  # Canadian Yahoo suffix symbols
    r")$",
    re.IGNORECASE,
)


def _validate_and_normalize_stock_code(code: str) -> str:
    """Validate stock code format and return canonical form.

    Raises HTTPException(400) if the code does not match supported formats.
    """
    stripped = code.strip()
    if not stripped:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_stock_code", "message": "Stock code must not be empty"},
        )
    if not _STOCK_CODE_RE.match(stripped):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_stock_code",
                "message": f"'{stripped}' is not a valid stock code format",
            },
        )
    return normalize_stock_code(stripped)


def _watchlist_match_key(code: str) -> str:
    """Return the equivalence key used for watchlist add/remove matching."""
    normalized = normalize_stock_code(code.strip())
    if re.fullmatch(r"\d{5}", normalized):
        return f"HK{normalized}"
    return normalized.upper()


@router.post(
    "/extract-from-image",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "Extracted stock codes"},
        400: {"description": "Invalid image", "model": ErrorResponse},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Extract stock codes from an image",
    description=(
        "Upload a screenshot or image and extract stock codes with a vision LLM. Supports JPEG, PNG, WebP and"
        " GIF, up to 5 MB."
    ),
)
def extract_from_image(
    file: Optional[UploadFile] = File(None, description="Image file (form field name: file)"),
    include_raw: bool = Query(False, description="Whether to include the raw LLM response in the result"),
) -> ExtractFromImageResponse:
    """
    Extract stock codes from an uploaded image (using a Vision LLM).

    Upload the image using the `file` form field. Provider priority: Gemini / Anthropic / OpenAI (first available).
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "No file provided; upload the image in the form field named file"},
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_type",
                "message": f"Unsupported type: {content_type}. Allowed: {ALLOWED_MIME_STR}",
            },
        )

    try:
        # Read up to the size limit first, then check whether anything is left (clear semantics: reject if it overflows)
        data = file.file.read(MAX_SIZE_BYTES)
        if file.file.read(1):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"Image exceeds the {MAX_SIZE_BYTES // (1024 * 1024)} MB limit",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Failed to read uploaded file: {e}")
        raise HTTPException(
            status_code=400,
            detail={"error": "read_failed", "message": "Failed to read uploaded file"},
        )

    try:
        items, raw_text = extract_stock_codes_from_image(data, content_type)
        extract_items = [
            ExtractItem(code=code, name=name, confidence=conf) for code, name, conf in items
        ]
        codes = [i.code for i in extract_items]
        return ExtractFromImageResponse(
            codes=codes,
            items=extract_items,
            raw_text=raw_text if include_raw else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "extract_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"Image extraction failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "Image extraction failed"},
        )


@router.post(
    "/parse-import",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "Parse result"},
        400: {"description": "No data provided, or parsing failed", "model": ErrorResponse},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Parse CSV / Excel / clipboard",
    description=(
        "Upload a CSV/Excel file or paste text to parse stock codes automatically. Files up to 2 MB, text up "
        "to 100 KB."
    ),
)
async def parse_import(request: Request) -> ExtractFromImageResponse:
    """
    Parse a CSV/Excel file or clipboard text.

    - multipart/form-data + file: uploaded file
    - application/json + {"text": "..."}: pasted text
    - `file` takes precedence; if both are supplied, `text` is ignored
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as e:
            logger.warning("[parse_import] JSON parse failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_json", "message": f"JSON parsing failed: {e}"},
            )
        text = body.get("text") if isinstance(body, dict) else None
        if not text or not isinstance(text, str):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "No text provided; send {\"text\": \"...\"}"},
            )
        try:
            items = parse_import_from_text(text)
        except ValueError as e:
            text_bytes = len(text.encode("utf-8"))
            logger.warning(
                "[parse_import] parse_import_from_text failed: text_bytes=%d, error=%s",
                text_bytes,
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    elif "multipart" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "No file provided; use the form field named file"},
            )
        file_size = getattr(file, "size", None)
        if isinstance(file_size, int) and file_size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"File exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit",
                },
            )
        try:
            data = file.file.read(MAX_FILE_BYTES)
            if file.file.read(1):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "file_too_large",
                        "message": f"File exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit",
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            filename = getattr(file, "filename", None) or ""
            size = getattr(file, "size", None)
            logger.warning(
                "[parse_import] file read failed: filename=%r, size=%s, error=%s",
                filename,
                size,
                e,
            )
            raise HTTPException(
                status_code=400,
                detail={"error": "read_failed", "message": "Failed to read file"},
            )
        filename = getattr(file, "filename", None) or ""
        try:
            items = parse_import_from_bytes(data, filename=filename)
        except ValueError as e:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            logger.warning(
                "[parse_import] parse_import_from_bytes failed: filename=%r, ext=%r, bytes=%d, error=%s",
                filename,
                ext,
                len(data),
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "Upload a file as multipart/form-data, or submit {\"text\": \"...\"} as application/json",
            },
        )

    extract_items = [
        ExtractItem(code=code, name=name, confidence=conf)
        for code, name, conf in items
    ]
    codes = list(dict.fromkeys(i.code for i in extract_items if i.code))
    return ExtractFromImageResponse(codes=codes, items=extract_items, raw_text=None)


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "Current watchlist"},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Get watchlist",
    description="Return every stock code in the current STOCK_LIST configuration.",
)
def get_watchlist(
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        codes = _read_watchlist_codes(service)
        return WatchlistResponse(stock_codes=codes, message=f"{len(codes)} stock(s) in watchlist")
    except Exception as e:
        logger.error(f"Failed to get watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"Failed to get watchlist: {str(e)}"},
        )


@router.post(
    "/watchlist/add",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "Added to watchlist"},
        400: {"description": "Invalid parameters", "model": ErrorResponse},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Add to watchlist",
    description="Add the stock code to STOCK_LIST.",
)
def add_to_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        validated = _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        if _watchlist_match_key(validated) not in existing_keys:
            codes.append(request.stock_code.strip())
            _write_watchlist_codes(service, codes)
        return WatchlistResponse(stock_codes=codes, message=f"Added {request.stock_code.strip()}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add to watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"Failed to add to watchlist: {str(e)}"},
        )


@router.post(
    "/watchlist/remove",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "Removed from watchlist"},
        400: {"description": "Invalid parameters", "model": ErrorResponse},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Remove from watchlist",
    description="Remove the stock code from STOCK_LIST.",
)
def remove_from_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        validated = _validate_and_normalize_stock_code(request.stock_code)
        codes = _read_watchlist_codes(service)
        existing_keys = [_watchlist_match_key(c) for c in codes]
        requested_key = _watchlist_match_key(validated)
        if requested_key in existing_keys:
            idx = existing_keys.index(requested_key)
            codes.pop(idx)
            _write_watchlist_codes(service, codes)
        return WatchlistResponse(stock_codes=codes, message=f"Removed {request.stock_code.strip()}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove from watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"Failed to remove from watchlist: {str(e)}"},
        )


@router.get(
    "/{stock_code}/profile",
    response_model=StockProfileResponse,
    responses={
        400: {"description": "Invalid stock code", "model": ErrorResponse},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Get stock research profile",
    description=(
        "Aggregate quotes, history, research artifacts, news, holdings and monitoring rules, each with its "
        "own quality status."
    ),
)
def get_stock_profile(
    stock_code: str,
    history_days: int = Query(60, ge=1, le=365, description="Days of daily history"),
) -> StockProfileResponse:
    """Return partial profile data without failing on one optional block."""
    _validate_and_normalize_stock_code(stock_code)
    try:
        return StockProfileResponse(
            **StockProfileService().get_profile(stock_code, history_days=history_days)
        )
    except InvalidStockProfileCode:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_stock_code", "message": "Stock code does not match the exchange"},
        )
    except Exception as exc:
        sanitized = sanitize_diagnostic_text(str(exc), max_length=300) or "internal profile error"
        logger.error("Failed to get stock research profile: %s", sanitized)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "Failed to get stock research profile"},
        )


@router.get(
    "/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        200: {"description": "Quote data"},
        404: {"description": "Stock not found", "model": ErrorResponse},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Get real-time stock quote",
    description="Return the latest quote for a stock"
)
def get_stock_quote(stock_code: str) -> StockQuote:
    """
    Get a real-time stock quote

    Fetch the latest quote data for the given stock

    Args:
        stock_code: stock code (for example AAPL, 00700, RY.TO)

    Returns:
        StockQuote: real-time quote data

    Raises:
        HTTPException: 404 - stock not found
    """
    try:
        service = StockService()

        # Use def rather than async def so FastAPI runs this in its thread pool
        result = service.get_realtime_quote(stock_code)

        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"No quote data found for {stock_code}"
                }
            )

        return StockQuote(
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            current_price=result.get("current_price", 0.0),
            change=result.get("change"),
            change_percent=result.get("change_percent"),
            open=result.get("open"),
            high=result.get("high"),
            low=result.get("low"),
            prev_close=result.get("prev_close"),
            volume=result.get("volume"),
            amount=result.get("amount"),
            update_time=result.get("update_time")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get real-time quote: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to get real-time quote: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        200: {"description": "Price history data"},
        422: {"description": "Unsupported period parameter", "model": ErrorResponse},
        500: {"description": "Server error", "model": ErrorResponse},
    },
    summary="Get stock price history",
    description="Return historical candlestick data for a stock"
)
def get_stock_history(
    stock_code: str,
    period: str = Query("daily", description="Candlestick period", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365, description="Number of days")
) -> StockHistoryResponse:
    """
    Get historical stock quotes

    Fetch historical K-line data for the given stock

    Args:
        stock_code: stock code
        period: K-line interval (daily/weekly/monthly)
        days: number of days to fetch

    Returns:
        StockHistoryResponse: historical quote data
    """
    try:
        service = StockService()

        # Use def rather than async def so FastAPI runs this in its thread pool
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=days
        )

        # Convert to the response model
        data = [
            KLineData(
                date=item.get("date"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent")
            )
            for item in result.get("data", [])
        ]

        return StockHistoryResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            data=data
        )

    except ValueError as e:
        # Error for an unsupported period value (such as weekly/monthly)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to get price history: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"Failed to get price history: {str(e)}"
            }
        )
