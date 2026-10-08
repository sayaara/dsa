interface ValidationResult {
  valid: boolean;
  message?: string;
  normalized: string;
}

const SUPPORTED_QUERY_CHARACTERS = /^[A-Z0-9.\-\u3400-\u9FFF\s]+$/;

// US and Canadian symbol shapes the product analyzes.
const SUPPORTED_STOCK_CODE_PATTERNS = [
  /^[A-Z]{1,5}(?:\.(?:US|[A-EG-KM-Z]))?$/, // US ticker, optional share class (.L London and .F Frankfurt are exchanges)
  /^[A-Z0-9]{1,6}(?:-[A-Z]{1,2})?\.(?:TO|V|CN|NE)$/, // Canadian Yahoo suffix symbols, for example RY.TO
];

// Code shapes of markets the product does not support. They are still recognised as codes
// (not company names) so the user gets the reason instead of a name search.
const UNSUPPORTED_STOCK_CODE_PATTERNS: Array<[RegExp, string]> = [
  [/^\d{6}$/, 'Mainland China codes are not supported'],
  [/^(SH|SZ|BJ)\d{6}$/, 'Mainland China codes are not supported'],
  [/^\d{6}\.(SH|SZ|SS|BJ)$/, 'Mainland China codes are not supported'],
  [/^CSI\d{6}$/, 'Mainland China codes are not supported'],
  [/^\d{6}\.CSI$/, 'Mainland China codes are not supported'],
  [/^\d{5}$/, 'Hong Kong codes are not currently supported'],
  [/^HK\d{1,5}$/, 'Hong Kong codes are not currently supported'],
  [/^\d{1,5}\.HK$/, 'Hong Kong codes are not currently supported'],
  [/^[A-Z]{1,5}\.[LF]$/, 'This exchange is not supported'],
];

const SUPPORTED_MARKETS_HINT = 'only US and Canadian symbols are';

const unsupportedCodeReason = (normalized: string): string | undefined =>
  UNSUPPORTED_STOCK_CODE_PATTERNS.find(([regex]) => regex.test(normalized))?.[1];

/**
 * Check whether the input looks like a stock code, of a supported market or not.
 */
export const looksLikeStockCode = (value: string): boolean => {
  const normalized = value.trim().toUpperCase();
  return (
    SUPPORTED_STOCK_CODE_PATTERNS.some((regex) => regex.test(normalized)) ||
    unsupportedCodeReason(normalized) !== undefined
  );
};

/**
 * Validate the shape of a stock code, of a supported market or not (chat and query routing
 * rely on this contract). Use validateSupportedStockCode where a code is submitted or stored.
 */
export const validateStockCode = (value: string): ValidationResult => {
  const normalized = value.trim().toUpperCase();

  if (!normalized) {
    return { valid: false, message: 'Enter a stock code', normalized };
  }

  const valid = looksLikeStockCode(normalized);

  return {
    valid,
    message: valid ? undefined : 'Invalid stock code format',
    normalized,
  };
};

/**
 * Validate a US or Canadian stock code; other markets' codes are rejected with a reason.
 */
export const validateSupportedStockCode = (value: string): ValidationResult => {
  const result = validateStockCode(value);
  if (!result.valid) {
    return result;
  }

  const unsupportedReason = unsupportedCodeReason(result.normalized);
  if (unsupportedReason) {
    return {
      valid: false,
      message: `${unsupportedReason}; ${SUPPORTED_MARKETS_HINT}`,
      normalized: result.normalized,
    };
  }
  return result;
};

/**
 * Reject obviously invalid free-text queries before they reach the backend.
 */
export const isObviouslyInvalidStockQuery = (value: string): boolean => {
  const normalized = value.trim().toUpperCase();

  if (!normalized || looksLikeStockCode(normalized)) {
    return false;
  }

  if (!SUPPORTED_QUERY_CHARACTERS.test(normalized)) {
    return true;
  }

  const hasLetters = /[A-Z]/.test(normalized);
  const hasDigits = /\d/.test(normalized);

  return hasLetters && hasDigits;
};
