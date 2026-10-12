import { describe, expect, it } from 'vitest';

import { getReportText, normalizeReportLanguage } from '../reportLanguage';
import { getSentimentLabel } from '../../types/analysis';

describe('reportLanguage English lock', () => {
  it('normalizes every language input to en', () => {
    expect(normalizeReportLanguage('ko')).toBe('en');
    expect(normalizeReportLanguage('zh')).toBe('en');
    expect(normalizeReportLanguage('en')).toBe('en');
    expect(normalizeReportLanguage('fr')).toBe('en');
    expect(normalizeReportLanguage(undefined)).toBe('en');
  });

  it('returns English report copy whatever language a record carries', () => {
    for (const language of ['zh', 'ko', 'en', null]) {
      const text = getReportText(language);
      expect(text.keyInsights).toBe('KEY INSIGHTS');
      expect(text.actionAdvice).toBe('Action Advice');
      expect(text.fullReport).toBe('Full analysis report');
    }
  });

  it('returns English sentiment labels by band', () => {
    expect(getSentimentLabel(90)).toBe('Very Bullish');
    expect(getSentimentLabel(70)).toBe('Bullish');
    expect(getSentimentLabel(50)).toBe('Neutral');
    expect(getSentimentLabel(30)).toBe('Bearish');
    expect(getSentimentLabel(10)).toBe('Very Bearish');
  });
});
