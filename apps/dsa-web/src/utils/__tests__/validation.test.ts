import { describe, expect, test } from 'vitest';
import {
  isObviouslyInvalidStockQuery,
  looksLikeStockCode,
  validateStockCode,
  validateSupportedStockCode,
} from '../validation';

describe('stock code validation', () => {
  test.each(['7203.T', '005930.KS', '035720.KQ', '2330.TW', '6505.TWO'])(
    'rejects removed Japan/Korea/Taiwan suffix code %s',
    (input) => {
      expect(looksLikeStockCode(input)).toBe(false);
      expect(validateStockCode(input).valid).toBe(false);
    }
  );

  test.each(['RY.TO', 'ry.to', 'SHOP.TO', 'ABX.V', 'XYZ.CN', 'BAM-A.TO', 'REI-UN.TO'])(
    'accepts Canadian Yahoo suffix symbol %s',
    (input) => {
      expect(looksLikeStockCode(input)).toBe(true);
      expect(validateStockCode(input).valid).toBe(true);
      expect(isObviouslyInvalidStockQuery(input)).toBe(false);
    }
  );

  test.each(['TOOLONGNAME.TO', 'RY.TX', 'A--B.TO'])(
    'rejects malformed Canadian symbol %s',
    (input) => {
      expect(looksLikeStockCode(input)).toBe(false);
    }
  );

  test.each(['7203', '005930.K', '035720.KRX'])(
    'does not treat ambiguous query %s as a valid code',
    (input) => {
      const result = validateStockCode(input);
      expect(result.valid).toBe(false);
    }
  );

  test.each([
    ['sh000016', 'SH000016'],
    ['sh000300', 'SH000300'],
    ['sz399001', 'SZ399001'],
  ])('accepts registered SH/SZ index canonical %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test.each([
    ['csi930955', 'CSI930955'],
    ['930955.CSI', '930955.CSI'],
    ['CSI930955', 'CSI930955'],
  ])('accepts registered CSI index forms %s', (input, normalized) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input)).toEqual({
      valid: true,
      normalized,
    });
    expect(isObviouslyInvalidStockQuery(input)).toBe(false);
  });

  test('rejects unregistered CSI forms that are not registered index canonicals', () => {
    // 930956.CSI is not in the registry; the Web validation layer is
    // format-based (registered rows pass), while the API returns a 4xx for
    // unregistered CSI at the backend boundary.
    expect(looksLikeStockCode('930956.CSI')).toBe(true);
    expect(validateStockCode('930956.CSI').valid).toBe(true);
  });
});

describe('supported-market stock code validation', () => {
  test.each([
    ['600519', 'Mainland China'],
    ['sh000300', 'Mainland China'],
    ['000001.SZ', 'Mainland China'],
    ['csi930955', 'Mainland China'],
    ['930955.CSI', 'Mainland China'],
    ['00700', 'Hong Kong'],
    ['hk00700', 'Hong Kong'],
    ['0700.HK', 'Hong Kong'],
    ['VOD.L', 'exchange'],
    ['SAP.F', 'exchange'],
  ])('rejects unsupported-market code %s with a reason', (input, reason) => {
    expect(looksLikeStockCode(input)).toBe(true);
    expect(validateStockCode(input).valid).toBe(true);
    const result = validateSupportedStockCode(input);
    expect(result.valid).toBe(false);
    expect(result.message).toContain(reason);
    expect(result.message).toContain('only US and Canadian symbols are');
  });

  test.each(['AAPL', 'aapl', 'BRK.B', 'BF.B', 'AAPL.US', 'RY.TO', 'TECK-B.TO'])(
    'accepts US and Canadian symbol %s',
    (input) => {
      expect(validateSupportedStockCode(input)).toEqual({ valid: true, normalized: input.toUpperCase() });
    }
  );

  test('keeps the format message for malformed input', () => {
    expect(validateSupportedStockCode('aapl-2026').message).toBe('Invalid stock code format');
  });
});
