import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DISPLAY_LOCALE,
  MARKET_TIME_ZONE,
  formatDate,
  formatDateTime,
  getMarketDateKey,
  getRecentStartDate,
  getTodayInMarketTimeZone,
  parseServerDateTime,
  shiftDateKey,
} from '../format';

describe('date settings', () => {
  it('uses US English and US Eastern time', () => {
    expect(DISPLAY_LOCALE).toBe('en-US');
    expect(MARKET_TIME_ZONE).toBe('America/New_York');
  });
});

describe('formatDateTime / formatDate', () => {
  it('formats in US English', () => {
    // Local wall-clock input, so the result does not depend on the runner's zone.
    expect(formatDateTime('2026-10-12T15:45:00')).toBe('10/12/2026, 03:45 PM');
    expect(formatDate('2026-10-12T15:45:00')).toBe('10/12/2026');
  });

  it('keeps the placeholder and unparseable values', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
    expect(formatDateTime('not a date')).toBe('not a date');
  });
});

describe('market day', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('changes at midnight in New York, not UTC', () => {
    // 23:59 EDT on Oct 12 is 03:59 UTC on Oct 13.
    expect(getMarketDateKey(new Date('2026-10-13T03:59:00Z'))).toBe('2026-10-12');
    expect(getMarketDateKey(new Date('2026-10-13T04:00:00Z'))).toBe('2026-10-13');
    // 23:59 EST on Dec 1 is 04:59 UTC on Dec 2.
    expect(getMarketDateKey(new Date('2026-12-02T04:59:00Z'))).toBe('2026-12-01');
    expect(getMarketDateKey(new Date('2026-12-02T05:00:00Z'))).toBe('2026-12-02');
  });

  it('reads today and the recent start date in the market time zone', () => {
    vi.useFakeTimers();
    // 22:30 EDT on Oct 12; already Oct 13 in UTC and in Shanghai.
    vi.setSystemTime(new Date('2026-10-13T02:30:00Z'));
    expect(getTodayInMarketTimeZone()).toBe('2026-10-12');
    expect(getRecentStartDate(30)).toBe('2026-09-12');
    expect(getRecentStartDate(0)).toBe('2026-10-12');
  });

  it('shifts date keys by calendar days across months and DST', () => {
    expect(shiftDateKey('2026-11-01', -1)).toBe('2026-10-31');
    expect(shiftDateKey('2026-03-08', 1)).toBe('2026-03-09');
    expect(shiftDateKey('2026-12-31', 1)).toBe('2027-01-01');
  });
});

describe('parseServerDateTime', () => {
  it('reads naive timestamps as New York wall-clock time', () => {
    expect(new Date(parseServerDateTime('2026-10-12T23:30:00')).toISOString()).toBe('2026-10-13T03:30:00.000Z');
    expect(new Date(parseServerDateTime('2026-12-01 09:15')).toISOString()).toBe('2026-12-01T14:15:00.000Z');
    expect(new Date(parseServerDateTime('2026-10-12T09:00:00.123456')).toISOString()).toBe('2026-10-12T13:00:00.123Z');
  });

  it('uses the offset in force on each side of the DST changes', () => {
    // Fall back: 2026-11-01 02:00 EDT -> 01:00 EST.
    expect(new Date(parseServerDateTime('2026-10-31T23:00:00')).toISOString()).toBe('2026-11-01T03:00:00.000Z');
    expect(new Date(parseServerDateTime('2026-11-01T03:00:00')).toISOString()).toBe('2026-11-01T08:00:00.000Z');
    // Spring forward: 2026-03-08 02:00 EST -> 03:00 EDT.
    expect(new Date(parseServerDateTime('2026-03-08T01:30:00')).toISOString()).toBe('2026-03-08T06:30:00.000Z');
    expect(new Date(parseServerDateTime('2026-03-08T03:30:00')).toISOString()).toBe('2026-03-08T07:30:00.000Z');
  });

  it('keeps explicit offsets and rejects invalid values', () => {
    expect(new Date(parseServerDateTime('2026-10-12T10:00:00+08:00')).toISOString()).toBe('2026-10-12T02:00:00.000Z');
    expect(new Date(parseServerDateTime('2026-10-12T10:00:00Z')).toISOString()).toBe('2026-10-12T10:00:00.000Z');
    expect(parseServerDateTime(null)).toBeNaN();
    expect(parseServerDateTime('')).toBeNaN();
    expect(parseServerDateTime('yesterday')).toBeNaN();
  });

  it('puts a late-evening naive timestamp on the New York day', () => {
    const time = parseServerDateTime('2026-10-12T23:30:00');
    expect(getMarketDateKey(new Date(time))).toBe('2026-10-12');
  });
});
