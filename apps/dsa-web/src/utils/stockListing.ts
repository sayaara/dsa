import type { StockSuggestion } from '../types/stockIndex';

// Exchange tags in the bundled index's US names (`HUDBAY MINERALS (NYS)`).
const US_EXCHANGE_TAGS: Record<string, string> = {
  NYS: 'NYSE',
  NAS: 'Nasdaq',
  ASE: 'NYSE American',
  OTC: 'OTC',
};

/**
 * Exchange and trading currency of a US or Canadian listing (`TSX · CAD`), so the two
 * listings of an interlisted company (`SHOP`, `SHOP.TO`) are told apart.
 */
export function getListingLabel(suggestion: Pick<StockSuggestion, 'market' | 'canonicalCode' | 'nameZh'>): string | null {
  if (suggestion.market === 'CA') {
    const exchange = suggestion.canonicalCode.toUpperCase().endsWith('.V') ? 'TSXV' : 'TSX';
    return `${exchange} · CAD`;
  }
  if (suggestion.market === 'US') {
    const tag = /\((NYS|NAS|ASE|OTC)\)/.exec(suggestion.nameZh.toUpperCase())?.[1];
    return `${tag ? US_EXCHANGE_TAGS[tag] : 'US'} · USD`;
  }
  return null;
}
