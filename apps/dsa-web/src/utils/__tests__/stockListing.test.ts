import { describe, expect, it } from 'vitest';
import { getListingLabel } from '../stockListing';

describe('getListingLabel', () => {
  it('tells the two listings of an interlisted company apart', () => {
    expect(getListingLabel({ market: 'US', canonicalCode: 'SHOP', nameZh: "SHOPIFY 'A' (NAS)" })).toBe('Nasdaq · USD');
    expect(getListingLabel({ market: 'CA', canonicalCode: 'SHOP.TO', nameZh: 'Shopify Inc.' })).toBe('TSX · CAD');
  });

  it('reads the US exchange from the index name tag', () => {
    expect(getListingLabel({ market: 'US', canonicalCode: 'HBM', nameZh: 'HUDBAY MINERALS (NYS)' })).toBe('NYSE · USD');
    expect(getListingLabel({ market: 'US', canonicalCode: 'BTG', nameZh: 'B2GOLD (ASE)' })).toBe('NYSE American · USD');
    expect(getListingLabel({ market: 'US', canonicalCode: 'ACDVF', nameZh: 'AIR CANADA VOTING (OTC) AND VARIABLE VOTING' })).toBe('OTC · USD');
    expect(getListingLabel({ market: 'US', canonicalCode: 'AAPL', nameZh: 'Apple Inc.' })).toBe('US · USD');
  });

  it('labels TSX Venture symbols and leaves other markets alone', () => {
    expect(getListingLabel({ market: 'CA', canonicalCode: 'ABC.V', nameZh: 'Example Venture Corp.' })).toBe('TSXV · CAD');
    expect(getListingLabel({ market: 'INDEX', canonicalCode: '^GSPC', nameZh: 'S&P 500' })).toBeNull();
  });
});
