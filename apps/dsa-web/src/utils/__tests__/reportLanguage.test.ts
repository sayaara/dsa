import { describe, expect, it } from 'vitest';

import { getReportText, normalizeReportLanguage } from '../reportLanguage';
import { getSentimentLabel } from '../../types/analysis';

describe('reportLanguage English lock', () => {
  it('normalizes every language input to en', () => {
    expect(normalizeReportLanguage('ko')).toBe('en');
    expect(normalizeReportLanguage('en')).toBe('en');
    expect(normalizeReportLanguage('fr')).toBe('en');
    expect(normalizeReportLanguage(undefined)).toBe('en');
  });

  it('returns English report copy when ko is requested', () => {
    const ko = getReportText(normalizeReportLanguage('ko'));
    expect(ko.keyInsights).toBe('KEY INSIGHTS');
    expect(ko.actionAdvice).toBe('Action Advice');
    expect(ko.fullReport).toBe('Full analysis report');
  });

  it('keeps zh/en report copy unchanged', () => {
    expect(getReportText('zh').keyInsights).toBe('KEY INSIGHTS');
    expect(getReportText('en').keyInsights).toBe('KEY INSIGHTS');
  });

  it('returns Korean sentiment labels by band', () => {
    expect(getSentimentLabel(90, 'ko')).toBe('매우 낙관');
    expect(getSentimentLabel(50, 'ko')).toBe('중립');
    expect(getSentimentLabel(10, 'ko')).toBe('매우 비관');
    expect(getSentimentLabel(90, 'en')).toBe('Very Bullish');
  });
});
