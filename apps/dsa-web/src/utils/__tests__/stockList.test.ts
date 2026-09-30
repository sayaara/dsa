import { describe, expect, it } from 'vitest';
import { parseStockListValue, serializeStockListValue } from '../stockList';

describe('stockList utils', () => {
  it('parses common copy/paste separators', () => {
    expect(parseStockListValue('600519，300750  hk00700;AAPL、TSLA\nMSFT')).toEqual([
      '600519',
      '300750',
      'hk00700',
      'AAPL',
      'TSLA',
      'MSFT',
    ]);
  });

  it('serializes to canonical commas', () => {
    expect(serializeStockListValue('600519，300750\nAAPL')).toBe('600519,300750,AAPL');
  });
});
