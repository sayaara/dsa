/** Locale for dates and times shown in the Web UI. */
export const DISPLAY_LOCALE = 'en-US';

/**
 * Time zone of the market day ("today") and of the server's naive local
 * timestamps. US Eastern time, which New York and Toronto share; the Docker
 * image sets the same `TZ`.
 */
export const MARKET_TIME_ZONE = 'America/New_York';

export const formatDateTime = (value?: string | null): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

export const formatDate = (value?: string): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
};

export const toDateInputValue = (date: Date): string => {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

/** Returns the YYYY-MM-DD date of an instant in the market time zone. */
export const getMarketDateKey = (date: Date): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: MARKET_TIME_ZONE }).format(date);

/** Moves a YYYY-MM-DD date key by whole calendar days. */
export const shiftDateKey = (dateKey: string, days: number): string => {
  const date = new Date(`${dateKey}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};

/**
 * Returns today's date as YYYY-MM-DD in the market time zone.
 * Use this instead of the browser-local date for market-day UI semantics.
 */
export const getTodayInMarketTimeZone = (): string => getMarketDateKey(new Date());

/**
 * Returns the date N days ago as YYYY-MM-DD in the market time zone.
 * Counted from getTodayInMarketTimeZone() so both ends of the date range
 * are expressed in the same time zone as the backend.
 */
export const getRecentStartDate = (days: number): string =>
  shiftDateKey(getTodayInMarketTimeZone(), -days);

const NAIVE_DATE_TIME_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/;

const marketTimeZoneParts = new Intl.DateTimeFormat('en-US', {
  timeZone: MARKET_TIME_ZONE,
  hourCycle: 'h23',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

/** Offset of the market time zone from UTC at an instant, in milliseconds. */
const getMarketTimeZoneOffset = (epochMs: number): number => {
  const parts: Record<string, number> = {};
  for (const part of marketTimeZoneParts.formatToParts(new Date(epochMs))) {
    if (part.type !== 'literal') parts[part.type] = Number(part.value);
  }
  const wallClockAsUtc = Date.UTC(
    parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second,
  );
  return wallClockAsUtc - Math.floor(epochMs / 1000) * 1000;
};

/**
 * Parses a server timestamp to epoch milliseconds (NaN when invalid).
 * Timestamps without an offset are the server's naive local time, which is
 * read as wall-clock time in the market time zone; others parse as given.
 */
export const parseServerDateTime = (value?: string | null): number => {
  if (!value) return Number.NaN;
  const trimmed = value.trim();
  const match = NAIVE_DATE_TIME_PATTERN.exec(trimmed);
  if (!match) return new Date(trimmed).getTime();

  const [, year, month, day, hour, minute, second = '0', fraction = '0'] = match;
  const wallClockAsUtc = Date.UTC(
    Number(year), Number(month) - 1, Number(day),
    Number(hour), Number(minute), Number(second),
    Number(fraction.padEnd(3, '0').slice(0, 3)),
  );
  // Two passes so a wall-clock time next to a DST change gets the offset in
  // force at the resulting instant.
  const firstGuess = wallClockAsUtc - getMarketTimeZoneOffset(wallClockAsUtc);
  return wallClockAsUtc - getMarketTimeZoneOffset(firstGuess);
};

export const formatReportType = (value?: string): string => {
  if (!value) return '—';
  if (value === 'simple') return 'Simple';
  if (value === 'detailed') return 'Standard';
  if (value === 'full') return 'Full';
  if (value === 'brief') return 'Brief';
  if (value === 'market_review') return 'Market';
  return value;
};
